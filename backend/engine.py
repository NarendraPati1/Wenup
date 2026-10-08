"""The orchestrator: context -> model -> guardrails -> verifier -> optional retry -> trace."""
import copy
import time
import uuid
from .validation import typo_fix_address
from .prompts import build_messages, build_payload, PREFIX_ID
from .models import LLMError, RateLimit, FALLBACK_Q, state_diff
from .guardrails import apply_proposal, fallback_reply, is_repeat, reply_ok, reply_problem
from .observability import annotate_turn, tracer as default_tracer, CallLog, route_path, summarize_attempts
from .session import Session


class Intake:
    def __init__(self, llm_call, log=None, tracer=default_tracer, user_id="local-dev", model_label=""):
        self.llm_call = llm_call                           # (messages, patient) -> Turn
        self.log = log if log is not None else CallLog()   # shared with the gateway: one record per API attempt
        self.tracer, self.user_id, self.model_label = tracer, user_id, model_label
        self.session_id = uuid.uuid4().hex[:12]            # groups all turns of this conversation in Langfuse
        self.sess = Session()
        self.trace = []
        self.calls = 0                                     # LLM calls made so far (for latency tracing)

    # ---- convenience views used by the CLI / tests ----
    @property
    def state(self):
        return self.sess.state

    @property
    def history(self):
        return self.sess.history

    @property
    def memory(self):
        return self.sess.mem.notes

    def done(self):
        return self.sess.done()

    def deferred(self):
        return self.sess.deferred()

    def forget_session(self):
        self.sess.forget()

    # ---- LLM plumbing ----
    def payload(self, msg, must_ask=None, rejected=None, note=None):
        return build_payload(self.sess, msg, must_ask=must_ask, rejected=rejected, note=note)

    def call(self, payload, compact=False):
        """One gateway call: system (static, cached) + user (dynamic payload)."""
        self.calls += 1
        turn = self.llm_call(build_messages(payload), patient=not compact)
        if turn is None:
            raise LLMError("empty model output")
        return turn

    # ---- public API ----
    def start(self):
        with self.tracer.observation(as_type="span", name="intake-start", input="(conversation start)") as span:
            self.tracer.trace(session_id=self.session_id, user_id=self.user_id, version=PREFIX_ID, tags=["document-intake"])
            tgt = self.sess.target({})
            self.sess.last_target = tgt
            note = "First message of the conversation: greet the client warmly in one or two sentences and ask the first question."
            try:
                turn = self.call(self.payload("(conversation start)", must_ask=tgt, note=note))
                reply = turn.reply.strip() if reply_ok(turn, tgt) else "Hi! " + FALLBACK_Q[tgt]
            except LLMError as e:
                reply = "Hi! " + FALLBACK_Q[tgt]
                self.tracer.update(span, level="WARNING", status_message=f"start fell back to a canned greeting: {e}")
            self.tracer.update(span, output=reply, metadata={"session_id": self.session_id, "prefix_id": PREFIX_ID,
                                                             "tokens": summarize_attempts(self.log)})
            return reply

    def handle(self, msg: str) -> str:
        """One user turn = one Langfuse trace (span) containing one generation per API attempt."""
        with self.tracer.observation(as_type="span", name="intake-turn", input=msg.strip()) as span:
            self.tracer.trace(session_id=self.session_id, user_id=self.user_id, version=PREFIX_ID,
                              tags=["document-intake"], metadata={"model": self.model_label})
            reply = self._handle(msg)
            tr = self.trace[-1] if self.trace else {}
            annotate_turn(self.tracer, span, tr, reply, session_id=self.session_id, turn_no=len(self.history),
                          prefix_id=PREFIX_ID, user_id=self.user_id, model=self.model_label)
            return reply

    def _handle(self, msg: str) -> str:
        msg = msg.strip()
        sess = self.sess
        t0, calls0, log0 = time.perf_counter(), self.calls, len(self.log)
        sess.fixed_addr = False
        before = copy.deepcopy(sess.state)

        fix = typo_fix_address(sess.state["home_address"], msg)    # repaired in code, so the single LLM call just words it
        must, note = None, None
        if fix:
            sess.state["home_address"], sess.fixed_addr = fix, True
            must = sess.target({})
            note = (f'The app already corrected home_address to "{fix}" because the client fixed a typo. '
                    "intent is correction. Say briefly that it is fixed, then ask about must_ask.")
        try:
            turn = self.call(self.payload(msg, must_ask=must, note=note))                  # LLM call #1 (the normal path)
        except LLMError as e:                                    # state untouched, history stays clean
            lead = "The AI service is rate limiting me right now" if isinstance(e, RateLimit) else "Sorry, I had trouble with that"
            attempts = list(self.log[log0:])
            self.trace.append({"user": msg, "error": str(e), "llm_calls": self.calls - calls0,
                               "ms": round((time.perf_counter() - t0) * 1000), "attempts": attempts,
                               "tokens": summarize_attempts(attempts), "routes": route_path(attempts),
                               "state": copy.deepcopy(sess.state)})
            return f"{lead} ({e}). Could you send your last message again in a moment?"

        # Guardrail: Block unsafe, off-topic, or probing messages
        if turn.intent in ("off_topic", "unsafe", "probe"):
            deflections = {
                "off_topic": "I can only help with drafting your Personal Wishes Document, so I'll leave that aside.",
                "unsafe": "I can't help with that. I'm here only to help you draft your Personal Wishes Document.",
                "probe": "I can't discuss how I work, but I'm happy to continue with your document."
            }
            reply = deflections.get(turn.intent, "I can only help with drafting your Personal Wishes Document.")
            tgt = sess.target({})
            if tgt:
                reply += f" {FALLBACK_Q[tgt]}"
            sess.history.append((msg, reply))
            attempts = list(self.log[log0:])
            self.trace.append({"user": msg, "intent": turn.intent, "blocked": True,
                               "llm_calls": self.calls - calls0, "ms": round((time.perf_counter() - t0) * 1000),
                               "attempts": attempts, "routes": route_path(attempts),
                               "reply": reply, "state": copy.deepcopy(sess.state)})
            self.tracer.event("intent-blocked", level="WARNING", input={"intent": turn.intent, "message": msg}, output=reply)
            return reply

        info = apply_proposal(sess, turn, msg)
        self.tracer.event(
            "proposal-applied",
            input={"intent": turn.intent, "extracted": turn.model_dump(exclude={"reply"}), "model_reply": turn.reply},
            output={"state_diff": state_diff(before, sess.state), "rejected": info["rejected"],
                    "dropped": info["dropped"], "pending": copy.deepcopy(sess.pending),
                    "skipped": dict(sess.skipped), "memory_keys": sorted(sess.mem.notes),
                    "known_people": list(sess.mem.people.values())},
            level="WARNING" if (info["rejected"] or info["dropped"]) else "DEFAULT")
        sess.fixed_addr = False
        tgt = sess.target(info["rejected"])
        reply, retried, fell_back, retry_reason = turn.reply.strip(), False, False, None

        problem = reply_problem(turn, tgt)
        repeat = problem is None and is_repeat(turn, reply, sess.history)
        if repeat:
            problem = "repeated its previous message"
        if problem:                                     # LLM call #2 only on a mismatch or a repeated reply
            retried, retry_reason = True, problem
            self.tracer.event("retry-reason", level="WARNING",
                              input={"problem": problem, "target": tgt, "first_reply": reply, "asking": turn.asking})
            full = "Return the full JSON object exactly as in OUTPUT."
            note = ("Your previous reply repeats your last message. The client may be asking a question or be confused: "
                    "answer it directly first, then ask about must_ask in different words. " + full if repeat else
                    "Your previous reply did not match what the app needs. Answer the same user_message again, "
                    "asking about must_ask. " + full)
            try:
                t2 = self.call(self.payload(msg, must_ask=tgt, rejected=info["rejected"], note=note), compact=True)
                reply = t2.reply.strip()
                if not reply_ok(t2, tgt):
                    fell_back, reply = True, fallback_reply(sess, reply, tgt, info["rejected"])
            except LLMError:
                fell_back, reply = True, fallback_reply(sess, reply, tgt, info["rejected"])
        if fell_back:
            self.tracer.event("fallback-reply", level="WARNING", output=reply, input={"problem": problem, "target": tgt})

        sess.last_target = tgt
        sess.history.append((msg, reply))
        attempts = list(self.log[log0:])
        self.trace.append({"user": msg, "intent": turn.intent,
                           "extracted": turn.model_dump(exclude={"reply"}), **info,
                           "target": tgt, "retried": retried, "retry_reason": retry_reason, "fallback": fell_back,
                           "llm_calls": self.calls - calls0, "ms": round((time.perf_counter() - t0) * 1000),
                           "attempts": attempts, "routes": route_path(attempts),
                           "reply": reply, "first_reply": turn.reply.strip(),
                           "state_diff": state_diff(before, sess.state),
                           "tokens": summarize_attempts(attempts),
                           "memory_keys": sorted(sess.mem.notes),
                           "state": copy.deepcopy(sess.state), "pending": copy.deepcopy(sess.pending)})
        return reply
