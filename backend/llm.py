"""Model layer: settings, route/completion types, Groq provider, routing gateway."""
import os
import re
import time
import json
from dataclasses import dataclass, field
from typing import Tuple, Optional
from .models import ProviderError, LLMError, RateLimit, Turn
from .observability import tracer as default_tracer, CallLog
from .prompts import PREFIX_ID


# ======== config ========


DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_MODELS = "openai/gpt-oss-20b"   # set GROQ_FALLBACK_MODELS= (empty) to disable model fallback


def _flag(name, default="1"):
    return os.getenv(name, default).strip() == "1"


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def load_api_keys():
    """GROQ_API_KEY, GROQ_API_KEY_2 ... GROQ_API_KEY_9 and/or GROQ_API_KEYS=a,b,c -> (("key1", secret), ...).
    The slot names ("key1", "key2") are what shows up in logs and traces; the secrets never do."""
    raw = [os.getenv("GROQ_API_KEY", "")]
    raw += [os.getenv(f"GROQ_API_KEY_{i}", "") for i in range(2, 10)]
    raw += os.getenv("GROQ_API_KEYS", "").split(",")
    seen, out = set(), []
    for k in (x.strip() for x in raw):
        if k and k not in seen:
            seen.add(k)
            out.append((f"key{len(out) + 1}", k))
    return tuple(out)


@dataclass(frozen=True)
class Settings:
    # --- model routing ---
    model: str = DEFAULT_MODEL
    fallback_models: Tuple[str, ...] = ()
    api_keys: Tuple[Tuple[str, str], ...] = ()          # (slot name, secret)
    # --- generation parameters ---
    temperature: float = 0.2
    reasoning_effort: str = "low"
    max_completion_tokens: int = 3000
    timeout: float = 30.0
    # --- gateway policy ---
    max_wait: float = 20.0            # longest we will sleep for a rate limit (seconds)
    max_attempts: int = 6             # API attempts per LLM call, across all keys / models
    transient_cooldown: float = 10.0  # seconds a route is skipped after repeated timeouts / 5xx
    # --- observability ---
    log_system_prompt: bool = True
    log_reasoning: bool = True
    user_id: str = "local-dev"
    price_in: float = 0.0             # $ per 1M tokens, optional (cost tracking in Langfuse)
    price_cached_in: float = 0.0
    price_out: float = 0.0
    trace_file: str = "intake_trace.jsonl"

    @property
    def params(self):
        return {"temperature": self.temperature, "reasoning_effort": self.reasoning_effort,
                "max_completion_tokens": self.max_completion_tokens}

    @classmethod
    def from_env(cls):
        fallbacks = tuple(m.strip() for m in os.getenv("GROQ_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS).split(",")
                          if m.strip())
        return cls(
            model=os.getenv("GROQ_MODEL", DEFAULT_MODEL),
            fallback_models=fallbacks,
            api_keys=load_api_keys(),
            max_wait=_float("LLM_MAX_WAIT", "20"),
            max_attempts=int(_float("LLM_MAX_ATTEMPTS", "6")),
            log_system_prompt=_flag("LF_LOG_SYSTEM_PROMPT"),
            log_reasoning=_flag("LF_LOG_REASONING"),
            user_id=os.getenv("LF_USER_ID", "local-dev"),
            price_in=_float("PRICE_IN_PER_M", "0"),
            price_cached_in=_float("PRICE_CACHED_IN_PER_M", "0"),
            price_out=_float("PRICE_OUT_PER_M", "0"),
            trace_file=os.getenv("TRACE_FILE", "intake_trace.jsonl"),
        )


# ======== types ========


@dataclass(frozen=True)
class Route:
    """One way to reach a model: which API key slot, which model. Only the slot NAME is ever logged."""
    key_slot: str
    model: str

    @property
    def label(self):
        return f"{self.model}@{self.key_slot}"


@dataclass
class Completion:
    """Everything one successful API call returns, normalised."""
    content: str
    finish: Optional[str] = None
    in_tokens: Optional[int] = None
    out_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    reasoning: Optional[str] = None
    timings: dict = field(default_factory=dict)      # queue_time / prompt_time / completion_time / total_time (seconds)
    headers: dict = field(default_factory=dict)      # request id + rate-limit headers
    response_id: Optional[str] = None
    fingerprint: Optional[str] = None
    usage_raw: str = ""


# ======== groq_provider ========


RL_HEADERS = ("x-request-id", "x-ratelimit-limit-requests", "x-ratelimit-limit-tokens",
              "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens",
              "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "retry-after")


def parse_wait(text):
    """'try again in 7.66s' / '1m25.5s' / '850ms' -> seconds (None when absent)."""
    m = re.search(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)", text)
    if not m:
        return None
    units = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * units[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", m.group(1)))


def _headers(h):
    try:
        return {k: h.get(k) for k in RL_HEADERS if h.get(k) is not None}
    except Exception:
        return {}


def _extra(obj, name):
    """Attribute from an SDK object, falling back to model_extra (Groq adds non-OpenAI fields there)."""
    v = getattr(obj, name, None)
    if v is None:
        v = (getattr(obj, "model_extra", None) or {}).get(name)
    return v


def _cached_tokens(u):
    """cached prompt tokens from the usage object, even when the SDK keeps the field only in model_extra / a dict."""
    try:
        d = u.model_dump()
    except Exception:
        d = {}
    pd = d.get("prompt_tokens_details") or (getattr(u, "model_extra", None) or {}).get("prompt_tokens_details")
    if pd is None:
        pd = getattr(u, "prompt_tokens_details", None)
    if isinstance(pd, dict):
        return pd.get("cached_tokens")
    return getattr(pd, "cached_tokens", None)


def classify_error(e):
    """Turn any SDK exception into a ProviderError whose `kind` tells the gateway what policy applies."""
    text, name = str(e), type(e).__name__
    status = getattr(e, "status_code", None)
    low = text.lower()
    headers = _headers(getattr(getattr(e, "response", None), "headers", None))
    if name == "RateLimitError" or status == 429 or "rate limit" in low:
        wait = parse_wait(text)
        if wait is None:
            try:
                wait = float(headers.get("retry-after"))
            except (TypeError, ValueError):
                wait = None
        return ProviderError("daily_limit" if "per day" in low else "rate_limit", text[:400], wait, status, headers)
    if status in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
        return ProviderError("auth", text[:400], None, status, headers)
    if status == 404 or any(x in low for x in ("model_not_found", "decommissioned", "does not exist")):
        return ProviderError("dead_model", text[:400], None, status, headers)
    if status == 400 and "include_reasoning" in low:
        return ProviderError("unsupported_param", text[:400], None, status, headers)
    if status is not None and 400 <= status < 500:
        return ProviderError("bad_request", text[:400], None, status, headers)
    return ProviderError("transient", f"{name}: {text[:400]}", None, status, headers)   # timeouts, connection errors, 5xx


class GroqProvider:
    def __init__(self, api_keys, timeout=30.0):
        self.keys = dict(api_keys)          # slot name -> secret (never logged)
        self.timeout = timeout
        self._clients = {}

    def _client(self, slot):
        if slot not in self._clients:
            from groq import Groq
            self._clients[slot] = Groq(api_key=self.keys[slot], timeout=self.timeout, max_retries=0)
        return self._clients[slot]

    def complete(self, route: Route, messages, params, include_reasoning=True):
        extra = {"extra_body": {"include_reasoning": True}} if include_reasoning else {}
        try:
            raw = self._client(route.key_slot).chat.completions.with_raw_response.create(
                model=route.model, messages=messages, response_format={"type": "json_object"}, **extra, **params)
            r = raw.parse()
        except Exception as e:
            raise classify_error(e) from e
        ch, u = r.choices[0], r.usage
        det = getattr(u, "completion_tokens_details", None)
        return Completion(
            content=ch.message.content or "", finish=ch.finish_reason,
            in_tokens=getattr(u, "prompt_tokens", None), out_tokens=getattr(u, "completion_tokens", None),
            cached_tokens=_cached_tokens(u), reasoning_tokens=getattr(det, "reasoning_tokens", None),
            reasoning=_extra(ch.message, "reasoning"),
            timings={k: _extra(u, k) for k in ("queue_time", "prompt_time", "completion_time", "total_time")},
            headers=_headers(raw.headers), response_id=getattr(r, "id", None),
            fingerprint=getattr(r, "system_fingerprint", None), usage_raw=str(u)[:400])


# ======== gateway ========


ROLES = {"system": "system", "human": "user", "ai": "assistant"}
RATE_KINDS = ("rate_limit", "daily_limit")
FOREVER = float("inf")


class Gateway:
    def __init__(self, provider, settings, log=None, tracer=default_tracer, sleep=time.sleep, clock=time.monotonic):
        self.provider, self.s, self.tracer = provider, settings, tracer
        self.log = log if log is not None else CallLog()
        self._sleep_fn, self.clock = sleep, clock
        slots = [slot for slot, _ in settings.api_keys] or ["key1"]
        models = []
        for m in [settings.model, *settings.fallback_models]:
            if m and m not in models:
                models.append(m)
        self.routes = [Route(slot, m) for m in models for slot in slots]
        self.cooldown = {}           # Route -> monotonic time until which it is skipped (inf = disabled for the session)
        self.no_reasoning = set()    # models that rejected include_reasoning
        self._waited = 0.0           # seconds slept before the next attempt (recorded on that attempt)

    # ---- the callable the engine uses: (messages, patient) -> Turn ----
    def __call__(self, messages, patient=True):
        msgs = [{"role": ROLES[r], "content": c} for r, c in messages]
        attempts, last, waited = 0, None, False
        while True:
            cands = [r for r in self.routes if self._available(r)]
            if not cands:                                    # every route is cooling down
                wait = self._soonest_wait()
                if waited or not patient or wait is None or wait > self.s.max_wait:
                    raise self._final_error(last)
                self._sleep(wait + 1.0)
                waited = True
                continue
            for route in cands:
                if not self._available(route):               # disabled by an earlier failure in this same round
                    continue
                for retry in (0, 1):
                    if attempts >= self.s.max_attempts:
                        raise self._final_error(last)
                    attempts += 1
                    try:
                        return self._attempt(route, msgs, patient, attempts)
                    except ProviderError as e:
                        last = e
                        if self._on_error(route, e, retry) == "next":
                            break
            # every candidate failed this round: wait once for a per-minute limit, otherwise give up
            wait = self._soonest_wait()
            if waited or not patient or wait is None or wait > self.s.max_wait or not (last and last.kind in RATE_KINDS):
                raise self._final_error(last)
            self._sleep(wait + 1.0)
            waited = True

    # ---- policy ----
    def _available(self, route):
        return self.cooldown.get(route, 0.0) <= self.clock()

    def _soonest_wait(self):
        now = self.clock()
        waits = [until - now for until in self.cooldown.values() if until != FOREVER and until > now]
        return min(waits) if waits else None

    def _sleep(self, secs):
        print(f"   (all routes busy: waiting {secs:.1f}s, then retrying)")
        self.tracer.event("rate-limit-wait", level="WARNING", input={"wait_s": round(secs, 1)})
        self._waited += secs
        self._sleep_fn(secs)

    def _cool(self, pred, until, kind, route):
        for r in self.routes:
            if pred(r):
                self.cooldown[r] = until
        self.tracer.event("route-cooldown", level="WARNING", input={
            "route": route.label, "kind": kind,
            "for_s": None if until == FOREVER else round(until - self.clock(), 1)})

    def _on_error(self, route, e, retry):
        """What to do after a failed attempt: 'retry' the same route, or move to the 'next' one."""
        k, now = e.kind, self.clock()
        if k in RATE_KINDS:
            secs = 3600.0 if k == "daily_limit" else (e.wait if e.wait is not None else 5.0)
            self._cool(lambda r: r == route, now + secs, k, route)
            return "next"
        if k == "auth":                                       # revoked key: disable every route that uses this slot
            self._cool(lambda r: r.key_slot == route.key_slot, FOREVER, k, route)
            return "next"
        if k == "dead_model":                                 # missing model: disable every route to it
            self._cool(lambda r: r.model == route.model, FOREVER, k, route)
            return "next"
        if k == "unsupported_param":
            self.no_reasoning.add(route.model)
            return "retry" if retry == 0 else "next"
        if k == "bad_request":
            return "next"
        if retry == 0:                                        # transient / bad_output: one more try on the same route
            return "retry"
        if k == "transient":
            self._cool(lambda r: r == route, now + self.s.transient_cooldown, k, route)
        return "next"

    def _final_error(self, last):
        wait = self._soonest_wait()
        if last is None or last.kind in RATE_KINDS:
            what = "daily limit" if (last is not None and last.kind == "daily_limit") else "per-minute token limit"
            tail = f"; retry in about {round(wait)}s" if wait else ""
            return RateLimit(f"{what} on {len(self.routes)} route(s){tail}")
        return LLMError(str(last)[:200])

    # ---- one API attempt = one Langfuse generation ----
    def _lf_messages(self, msgs):
        """System prompt: full text (LF_LOG_SYSTEM_PROMPT=1) or a short marker. The per-turn payload is parsed into a dict."""
        out = []
        for m in msgs:
            if m["role"] == "system" and not self.s.log_system_prompt:
                out.append({"role": "system", "content": f"[static system prompt, id {PREFIX_ID}, {len(m['content'])} chars]"})
            elif m["role"] == "user":
                try:
                    out.append({"role": "user", "content": json.loads(m["content"])})
                except ValueError:
                    out.append(m)
            else:
                out.append(m)
        return out

    def _attempt(self, route, msgs, patient, attempt_no):
        s, t0 = self.s, time.perf_counter()
        depth = self.routes.index(route)
        rec = {"attempt": attempt_no, "route": route.label, "model": route.model, "key_slot": route.key_slot,
               "fallback_depth": depth}
        if self._waited:
            rec["waited_s"], self._waited = round(self._waited, 1), 0.0
        if depth > 0:
            self.tracer.event("fallback-used", level="WARNING",
                              input={"route": route.label, "primary": self.routes[0].label})
        meta = {"attempt": attempt_no, "patient": patient, "prefix_id": PREFIX_ID, "route": route.label,
                "key_slot": route.key_slot, "fallback_depth": depth}
        with self.tracer.observation(as_type="generation", name="groq-chat", model=route.model,
                                     input=self._lf_messages(msgs), model_parameters=s.params, metadata=meta) as gen:
            try:
                c = self.provider.complete(route, msgs, s.params, include_reasoning=route.model not in self.no_reasoning)
                cache_ratio = round(c.cached_tokens / c.in_tokens, 3) if (c.cached_tokens is not None and c.in_tokens) else None
                reasoning = c.reasoning if s.log_reasoning else None
                rec.update(finish=c.finish, out_tokens=c.out_tokens, reasoning_tokens=c.reasoning_tokens,
                           in_tokens=c.in_tokens, cached_tokens=c.cached_tokens, cache_ratio=cache_ratio,
                           reasoning=reasoning, headers=c.headers, response_id=c.response_id,
                           fingerprint=c.fingerprint, output_chars=len(c.content or ""), usage_raw=c.usage_raw,
                           **c.timings)
                usage = {"input": c.in_tokens or 0, "output": c.out_tokens or 0,
                         "total": (c.in_tokens or 0) + (c.out_tokens or 0)}
                if c.cached_tokens is not None:
                    usage["input_cached_tokens"] = c.cached_tokens
                if c.reasoning_tokens is not None:
                    usage["output_reasoning_tokens"] = c.reasoning_tokens
                upd = dict(output=c.content, usage_details=usage)
                if s.price_in or s.price_out:
                    cached = c.cached_tokens or 0
                    upd["cost_details"] = {
                        "input": ((c.in_tokens or 0) - cached) * s.price_in / 1e6
                                 + cached * (s.price_cached_in or s.price_in) / 1e6,
                        "output": (c.out_tokens or 0) * s.price_out / 1e6}
                if c.finish == "length":                      # cut off by max_completion_tokens: JSON likely broken
                    upd.update(level="WARNING", status_message="finish_reason=length (output truncated)")
                upd["metadata"] = {**meta, "finish_reason": c.finish, "cached_tokens": c.cached_tokens,
                                   "cache_hit_ratio": cache_ratio, "reasoning_tokens": c.reasoning_tokens,
                                   "reasoning": (reasoning or "")[:10000] or None,
                                   "reasoning_chars": len(reasoning or ""), "groq_timings_s": c.timings,
                                   "rate_limit_headers": c.headers, "response_id": c.response_id,
                                   "system_fingerprint": c.fingerprint,
                                   "wall_ms": round((time.perf_counter() - t0) * 1000)}
                self.tracer.update(gen, **upd)
                try:
                    turn = Turn.model_validate_json(c.content)
                except Exception as e:
                    raise ProviderError("bad_output", f"{type(e).__name__}: {str(e)[:200]}") from e
            except ProviderError as e:
                rec["ms"] = round((time.perf_counter() - t0) * 1000)
                rec["error"] = f"{e.kind}: {str(e)[:400]}"
                if e.headers and not rec.get("headers"):
                    rec["headers"] = e.headers
                self.log.append(rec)
                self.tracer.update(gen, level="ERROR", status_message=f"{e.kind}: {str(e)[:300]}",
                                   metadata={**meta, "error_kind": e.kind, "error_text": str(e)[:1000],
                                             "rate_limit_headers": rec.get("headers")})
                raise
        rec["ms"] = round((time.perf_counter() - t0) * 1000)
        self.log.append(rec)
        return turn
