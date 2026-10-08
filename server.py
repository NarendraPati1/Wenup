"""React-to-backend bridge: a thin FastAPI layer over the Intake engine (no business logic lives here)."""
import os
import uuid
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import Gateway, GroqProvider, Intake, Settings
from backend.models import FALLBACK_Q, FIELD_ORDER
from backend.observability import CallLog, summarize_attempts, tracer

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
tracer.init()

app = FastAPI(title="Wenup Document Intake")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_TTL = 3600  # 1 hour

sessions: dict[str, Intake] = {}
locks: dict[str, threading.Lock] = {}
touched: dict[str, float] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str
    state: dict[str, Any] | None = None


class ChoiceRequest(BaseModel):
    session_id: str
    field: str
    value: bool | str | list[str]


# ---------------------------------------------------------------- helpers
def new_intake(session_id: str, user_id: str) -> Intake:
    settings = Settings.from_env()
    if not settings.api_keys:
        raise HTTPException(500, "GROQ_API_KEY is not configured")
    log = CallLog()
    gateway = Gateway(GroqProvider(settings.api_keys, settings.timeout), settings, log=log, tracer=tracer)
    intake = Intake(gateway, log=log, tracer=tracer, user_id=user_id, model_label=settings.model)
    intake.session_id = session_id  # Set session_id after creation
    return intake


def sweep():
    """Remove expired sessions from memory."""
    now = time.time()
    expired = [sid for sid, t in touched.items() if now - t > SESSION_TTL]
    for sid in expired:
        if sid in sessions:
            sessions[sid].forget_session()
            sessions.pop(sid, None)
        locks.pop(sid, None)
        touched.pop(sid, None)


def get_session(session_id: str) -> tuple[Intake, threading.Lock]:
    """Retrieve a session or raise 404 if expired/missing."""
    sweep()
    if session_id not in sessions:
        raise HTTPException(404, "Session expired or not found")
    touched[session_id] = time.time()
    return sessions[session_id], locks[session_id]


def frontend_state(intake: Intake, session_id: str) -> dict[str, Any]:
    """The engine state as the React app expects it. specific_gifts / additional_wishes are now real engine fields:
    None = not asked yet, [] = the client said "none"."""
    s = intake.state
    children = s.get("children_names") or []
    return {
        "full_name": s.get("full_name"),
        "home_address": s.get("home_address"),
        "covers_worldwide_assets": s.get("covers_worldwide_assets"),
        "has_children": s.get("has_children"),
        "children": children or None,
        "children_names": children or None,
        "executor": s.get("executor") or {"name": None, "relationship": None},
        "specific_gifts": s.get("specific_gifts"),
        "additional_wishes": s.get("additional_wishes"),
        "_meta": {"session_id": session_id, "llm_calls": intake.calls},
    }


def progress(intake: Intake) -> dict[str, Any]:
    """Counted by the engine's own notion of 'missing', so the bar always agrees with what the assistant asks next."""
    total = len(FIELD_ORDER) if intake.state.get("has_children") is True else len(FIELD_ORDER) - 1   # names only count when there are children
    completed = max(0, total - len(intake.sess.missing()))
    return {
        "completed": completed,
        "total": total,
        "label": f"{completed} of {total} completed",
        "percentage": round(completed * 100 / total),
    }


def session_stats(intake: Intake) -> dict[str, int]:
    t = summarize_attempts(intake.log)
    return {
        "llm_calls": intake.calls,
        "live_calls": len(intake.log),
        "cache_hits": sum(1 for a in intake.log if (a.get("cached_tokens") or 0) > 0),
        "prompt_tokens": t["in"],
        "completion_tokens": t["out"],
        "cached_tokens": t["cached"],
    }


def request_session(request: ChatRequest) -> tuple[str, Intake]:
    state_id = ((request.state or {}).get("_meta") or {}).get("session_id")
    session_id = request.session_id or state_id
    if not session_id:
        raise HTTPException(400, "session_id is required")
    sweep()
    if session_id not in sessions:
        raise HTTPException(404, "Session expired or not found")
    touched[session_id] = time.time()
    return session_id, sessions[session_id]


def shortcut_options(intake: Intake) -> list[dict[str, Any]]:
    target = intake.sess.target({})
    if target == "covers_worldwide_assets":
        return [
            {"label": "Worldwide assets", "field": target, "value": True},
            {"label": "Only local assets", "field": target, "value": False},
        ]
    if target == "has_children":
        return [
            {"label": "Yes, I have children", "field": target, "value": True},
            {"label": "No children", "field": target, "value": False},
        ]
    if target == "specific_gifts":
        return [{"label": "No gifts", "field": target, "value": "none"}]
    if target == "additional_wishes":
        return [{"label": "No additional wishes", "field": target, "value": "none"}]
    return []


def payload(intake: Intake, session_id: str, reply: str) -> dict[str, Any]:
    return {
        "assistant_message": reply,
        "state": frontend_state(intake, session_id),
        "progress": progress(intake),
        "session_stats": session_stats(intake),
        "options": shortcut_options(intake),
    }


# ---------------------------------------------------------------- routes
@app.get("/api/initial")
def initial(x_client_id: str = Header(default="anon")) -> dict[str, Any]:
    sid = uuid.uuid4().hex
    sessions[sid] = new_intake(sid, x_client_id)
    locks[sid] = threading.Lock()
    touched[sid] = time.time()
    return payload(sessions[sid], sid, sessions[sid].start())


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    if not request.message.strip():
        raise HTTPException(400, "Message is required")
    intake, lock = get_session(request.session_id)
    with lock:
        return payload(intake, request.session_id, intake.handle(request.message))


@app.get("/api/session/{sid}")
def restore(sid: str) -> dict[str, Any]:
    """Restore session after page refresh."""
    intake, lock = get_session(sid)
    with lock:
        last_reply = intake.history[-1][1] if intake.history else intake.start()
        return payload(intake, sid, last_reply)


# What a button click means, written into the engine state exactly like a typed answer would be.
CHOICE_LABELS = {
    ("covers_worldwide_assets", True): "Worldwide assets",
    ("covers_worldwide_assets", False): "Only local assets",
    ("has_children", True): "Yes, I have children",
    ("has_children", False): "No children",
    ("specific_gifts", "none"): "No gifts",
    ("additional_wishes", "none"): "No additional wishes",
}


@app.post("/api/choice")
def choice(request: ChoiceRequest) -> dict[str, Any]:
    intake, lock = get_session(request.session_id)
    with lock:
        key = (request.field, request.value if isinstance(request.value, (bool, str)) else None)
        if key not in CHOICE_LABELS:
            raise HTTPException(400, "Unsupported choice")
        state = intake.state
        if request.field in ("specific_gifts", "additional_wishes"):
            state[request.field] = []                      # [] = the client said "none"
        else:
            state[request.field] = request.value
            if request.field == "has_children" and request.value is False:
                state["children_names"] = []

        sess = intake.sess
        target = sess.target({})
        reply = FALLBACK_Q[target] if target else "Thank you! All your details have been recorded."
        sess.history.append((CHOICE_LABELS[key], reply))   # the model sees the click as a normal turn
        sess.last_target = target
        return payload(intake, request.session_id, reply)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "active_sessions": len(sessions)}


@app.get("/api/facts/{sid}")
def get_facts(sid: str) -> dict[str, Any]:
    """Get facts ledger for a session."""
    intake, lock = get_session(sid)
    with lock:
        from backend.ledger import format_ledger
        return {
            "facts": format_ledger(intake.state),
            "facts_list": [{"key": f.key, "value": f.value, "source": f.source} 
                          for f in intake.sess.facts_ledger()]
        }


# Serve the built React app (frontend/dist), or the single static page if that is what you ship.
for _dir in (ROOT / "frontend" / "dist", ROOT / "static"):
    if _dir.exists():
        app.mount("/", StaticFiles(directory=_dir, html=True), name="frontend")
        break


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))