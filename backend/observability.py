"""Langfuse tracing + local telemetry."""
import atexit
import os
import sys
from contextlib import contextmanager


# ======== observability ========


class Tracer:
    def __init__(self):
        self.lf = None

    # ---- lifecycle ----
    def init(self):
        """Call once, after load_dotenv(). Returns a short status string for the startup banner."""
        if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
            return "off (set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable)"
        try:
            from langfuse import get_client
            self.lf = get_client()
        except Exception as e:
            self.lf = None
            return f"off ({type(e).__name__}: run `pip install -U langfuse`)"
        atexit.register(self.flush)                  # short-lived CLI: make sure queued traces are sent on exit
        try:
            ok = self.lf.auth_check()
        except Exception:
            ok = None
        if ok is False:
            return "on, but the auth check failed (check the keys and LANGFUSE_HOST)"
        return "on" if ok else "on (auth check unavailable)"

    def flush(self):
        if self.lf is not None:
            try:
                self.lf.flush()
            except Exception:
                pass

    # ---- primitives ----
    @contextmanager
    def observation(self, **kw):
        """Yields a Langfuse observation (span / generation), or None when tracing is off or misbehaving."""
        cm = obs = None
        if self.lf is not None:
            try:
                cm = self.lf.start_as_current_observation(**kw)
                obs = cm.__enter__()
            except Exception:
                cm = obs = None
        try:
            yield obs
        except BaseException:
            self._exit(cm, sys.exc_info())
            raise
        else:
            self._exit(cm, (None, None, None))

    @staticmethod
    def _exit(cm, exc_info):
        if cm is None:
            return
        try:
            cm.__exit__(*exc_info)
        except Exception:
            pass

    @staticmethod
    def update(obs, **kw):
        if obs is None:
            return
        try:
            obs.update(**kw)
        except Exception:
            pass

    def trace(self, **kw):
        """Attach session id / tags / user / input / output to the trace that is currently active."""
        if self.lf is None:
            return
        try:
            self.lf.update_current_trace(**kw)
        except Exception:
            pass

    def event(self, name, **kw):
        """A point-in-time event nested under the current span (shows in the trace tree)."""
        if self.lf is None:
            return
        try:
            self.lf.create_event(name=name, **kw)
        except Exception:
            pass

    def score(self, name, value, comment=None):
        """Numeric score on the current trace: filter, chart and alert on these in Langfuse."""
        if self.lf is None or value is None:
            return
        try:
            self.lf.score_current_trace(name=name, value=float(value), data_type="NUMERIC", comment=comment)
        except Exception:
            pass


tracer = Tracer()      # shared default instance


def annotate_turn(t, span, tr, reply, *, session_id, turn_no, prefix_id, user_id, model):
    """Everything we record about one finished user turn: span output + metadata, trace tags, scores."""
    tk = tr.get("tokens") or {}
    meta = {k: tr.get(k) for k in ("intent", "target", "llm_calls", "retried", "retry_reason", "fallback",
                                   "ms", "rejected", "dropped", "error", "memory_keys", "state",
                                   "state_diff", "pending", "tokens", "routes")}
    meta.update(session_id=session_id, turn_no=turn_no, prefix_id=prefix_id)
    out = {"reply": reply, "state_diff": tr.get("state_diff")}
    if tr.get("error"):
        t.update(span, output=out, level="ERROR", status_message=str(tr["error"])[:300], metadata=meta)
    elif tr.get("fallback") or tr.get("retried"):
        t.update(span, output=out, level="WARNING",
                 status_message=f"second call: {tr.get('retry_reason')}" if tr.get("retried") else "canned fallback reply",
                 metadata=meta)
    else:
        t.update(span, output=out, metadata=meta)

    tags = ["document-intake", f"intent:{tr.get('intent') or 'error'}"]
    tags += [tag for tag, on in (("retried", tr.get("retried")), ("fallback", tr.get("fallback")),
                                 ("error", tr.get("error")), ("truncated", tk.get("truncated")),
                                 ("model-fallback", tk.get("fallback_used")),
                                 ("conflict-pending", tr.get("pending"))) if on]
    t.trace(input=tr.get("user"), output=reply, tags=tags)

    t.score("cache_hit_ratio", tk.get("cache_hit_ratio"))
    t.score("llm_calls", tr.get("llm_calls"))
    t.score("api_attempts", tk.get("calls"))
    t.score("retried", 1 if tr.get("retried") else 0, tr.get("retry_reason"))
    t.score("fallback", 1 if tr.get("fallback") else 0)
    t.score("model_fallback_used", 1 if tk.get("fallback_used") else 0)
    t.score("rejected_fields", len(tr.get("rejected") or {}))
    t.score("dropped_ungrounded", len(tr.get("dropped") or []))
    t.score("reasoning_tokens", tk.get("reasoning"))
    t.score("turn_latency_ms", tr.get("ms"))
    t.score("queue_ms", tk.get("queue_ms"))


# ======== telemetry ========


class CallLog(list):
    """One record per API attempt (route, duration, finish reason, tokens, headers, errors)."""


def summarize_attempts(attempts):
    """Totals across the API attempts of one turn (or a whole session)."""
    s = {"calls": len(attempts), "in": 0, "cached": 0, "out": 0, "reasoning": 0,
         "llm_ms": 0, "queue_ms": 0, "truncated": False, "errors": 0, "waited_s": 0.0, "fallback_used": False}
    for a in attempts:
        s["in"] += a.get("in_tokens") or 0
        s["cached"] += a.get("cached_tokens") or 0
        s["out"] += a.get("out_tokens") or 0
        s["reasoning"] += a.get("reasoning_tokens") or 0
        s["llm_ms"] += a.get("ms") or 0
        s["queue_ms"] += round((a.get("queue_time") or 0) * 1000)
        s["waited_s"] += a.get("waited_s") or 0
        s["truncated"] = s["truncated"] or a.get("finish") == "length"
        s["errors"] += 1 if a.get("error") else 0
        s["fallback_used"] = s["fallback_used"] or (a.get("fallback_depth") or 0) > 0
    s["cache_hit_ratio"] = round(s["cached"] / s["in"], 3) if s["in"] else None
    return s


def route_path(attempts):
    """Compact list of what happened per attempt, e.g. ['m1@key1: rate_limit', 'm1@key2: ok']."""
    out = []
    for a in attempts:
        err = (a.get("error") or "").split(":")[0]
        out.append(f"{a.get('route', '?')}: {err or 'ok'}")
    return out


def session_summary(app, log, tracer):
    """Totals for the whole conversation; also sent to Langfuse as its own small trace."""
    s = summarize_attempts(log)
    s.update(turns=len(app.history),
             retried_turns=sum(1 for t in app.trace if t.get("retried")),
             fallback_turns=sum(1 for t in app.trace if t.get("fallback")),
             error_turns=sum(1 for t in app.trace if t.get("error")),
             final_state=app.state, memory=sorted(app.memory))
    with tracer.observation(as_type="span", name="session-summary", input={"session_id": app.session_id}) as sp:
        tracer.trace(session_id=app.session_id, tags=["document-intake", "session-summary"])
        tracer.update(sp, output=s)
    return s
