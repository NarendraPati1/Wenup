"""Terminal front end."""
import json
from .llm import Settings, Gateway, GroqProvider
from .engine import Intake
from .observability import tracer, CallLog, session_summary
from .prompts import PREFIX_ID


def build_app(settings: Settings):
    log = CallLog()
    gateway = Gateway(GroqProvider(settings.api_keys, settings.timeout), settings, log=log, tracer=tracer)
    return Intake(gateway, log=log, tracer=tracer, user_id=settings.user_id, model_label=settings.model), gateway, log


def print_turn_diagnostics(tr, shown_usage):
    print(f"[{tr['llm_calls']} LLM call(s), {tr['ms']} ms]")
    for a in tr["attempts"]:
        print(f"   attempt {a['attempt']} [{a.get('route')}]: {a['ms']} ms (queue {round((a.get('queue_time') or 0) * 1000)} ms), "
              f"finish={a.get('finish')}, in={a.get('in_tokens')} cached={a.get('cached_tokens')} "
              f"({round((a.get('cache_ratio') or 0) * 100)}%), out={a.get('out_tokens')} "
              f"(reasoning {a.get('reasoning_tokens')}), "
              f"remaining tokens={(a.get('headers') or {}).get('x-ratelimit-remaining-tokens')}"
              + (f", waited {a['waited_s']}s" if "waited_s" in a else "")
              + (f"\n      ERROR {a['error']}" if "error" in a else ""))
        if a.get("reasoning"):
            print(f"      reasoning: {a['reasoning'][:300].replace(chr(10), ' ')}...")
        if not shown_usage and a.get("usage_raw"):
            print(f"      raw usage (shown once): {a['usage_raw']}")
            shown_usage = True
    if (tr.get("tokens") or {}).get("fallback_used"):
        print("   (a fallback key/model answered this turn)")
    if tr.get("retry_reason"):
        print(f"   second call because the reply {tr['retry_reason']}")
    return shown_usage


def main():
    from dotenv import load_dotenv
    load_dotenv()
    settings = Settings.from_env()
    if not settings.api_keys:
        raise SystemExit("Set GROQ_API_KEY (and optionally GROQ_API_KEY_2, ...) in your environment or .env")
    lf_status = tracer.init()                  # must come after load_dotenv() so the LANGFUSE_* keys are visible
    app, gateway, log = build_app(settings)
    print("Document Intake Assistant")
    print("Commands: /doc (show document), /state (show raw state), exit (quit)\n")
    print(f"AI: {app.start()}\n")
    
    while True:
        text = input("You: ").strip()
        if text.lower() in ("exit", "quit"):
            break
        if not text:
            continue
        
        # Handle commands
        if text.lower() == "/doc":
            from backend.ledger import format_ledger
            print("\n" + format_ledger(app.state))
            print()
            continue
        
        if text.lower() == "/state":
            print("\n" + json.dumps(app.state, indent=2, ensure_ascii=False) + "\n")
            continue
        
        # Regular message
        reply = app.handle(text)
        print(f"\nAI: {reply}\n")
        
        if app.done():
            left = app.deferred()
            print("(All fields collected." + (f" Left open on purpose: {', '.join(left)}." if left else "") + ")\n")
        
        # Save trace to file
        if app.trace:
            with open(settings.trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(app.trace[-1], ensure_ascii=False) + "\n")
    
    app.forget_session()
    tracer.flush()
    print("Session memory cleared.")
