"""
backend/routes.py — The Web API Endpoints (The Front Doors)

This file handles incoming web requests from the frontend browser:
1. /api/initial — "Welcome! Let's start a fresh chat session."
2. /api/chat    — "The user just sent a message; let the AI think and reply."
3. /api/choice  — "The user clicked a quick-button option (like 'Worldwide assets')."
"""
import uuid

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from .models import DocumentIntakeState, Executor
from .intake import (
    clean_history,
    normalize_state,
    state_for_response,
    question_options_for_reply,
    intake_turn,
)

# Create our router; all URLs in here start with "/api" (e.g., /api/chat)
api_router = APIRouter(prefix="/api")

# Default progress stats shown to the user before they fill anything out
_EMPTY_PROGRESS = {"completed": 0, "total": 9, "label": "0 of 9 completed", "percentage": 0}


# ── 1. Starting a New Chat ────────────────────────────────────────────────────
@api_router.get("/initial")
def api_initial():
    """
    Called when someone opens or reloads the web page.
    Generates a unique session ID and gives the first warm greeting.
    """
    session_id = str(uuid.uuid4())        # Fresh random session ID
    initial_state = DocumentIntakeState()  # Empty starting clipboard
    return {
        "assistant_message": "Hi! I'm your document assistant. Let's get started — what is your full name?",
        "state": state_for_response(initial_state, session_id),
        "options": [],
        "progress": _EMPTY_PROGRESS,
    }


# ── 2. Handling a User Message ────────────────────────────────────────────────
@api_router.post("/chat")
def api_chat(data: dict = Body(default_factory=dict)):
    """
    Called every time the user types a message and hits 'Send'.
    Sends the message to the AI, updates the document state, and returns the AI's reply.
    """
    # 1. Grab and validate the user's message
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return JSONResponse(status_code=400, content={"error": "message is required"})

    from .config import MAX_MESSAGE_CHARS

    # 2. Trim excess spaces and cap length so nobody sends a huge essay
    message = message.strip()[:MAX_MESSAGE_CHARS]

    # 3. Clean up chat history so it only has valid user/assistant messages
    history = clean_history(data.get("messages") or data.get("history") or [])

    # 4. Convert the incoming state dictionary into our typed DocumentIntakeState model
    state = normalize_state(data.get("state"))

    # 5. Make sure we have a session ID so we can group conversation logs in Langfuse
    session_id = (
        data.get("session_id")
        or (data.get("state") or {}).get("_meta", {}).get("session_id")
        or str(uuid.uuid4())
    )

    # 6. Ask the AI to process this turn! (Calls the Groq API)
    reply, new_state = intake_turn(message, history, state, session_id=session_id)

    # 7. If the AI completely failed (e.g. all Groq servers were unreachable)
    if reply is None:
        return JSONResponse(status_code=500, content={
            "assistant_message": "Sorry, something went wrong on my end. Could you please repeat that?",
            "state": state_for_response(new_state, session_id),
            "options": [],
            "ok": False,
            "progress": _EMPTY_PROGRESS,
        })

    # 8. Success! Send back the AI's reply, the updated document state, and any handy quick-buttons
    return {
        "assistant_message": reply,
        "state": state_for_response(new_state, session_id),
        "options": question_options_for_reply(new_state, reply),
        "ok": True,
        "progress": _EMPTY_PROGRESS,
    }


# ── 3. Handling a Quick-Choice Button Click ────────────────────────────────────
@api_router.post("/choice")
def api_choice(data: dict = Body(default_factory=dict)):
    """
    Called when the user clicks a pre-set button like:
    [ Worldwide assets ] or [ Only local assets ]
    Instead of typing it out, clicking instantly locks in the value!
    """
    state = normalize_state(data.get("state"))
    session_id = (
        data.get("session_id")
        or (data.get("state") or {}).get("_meta", {}).get("session_id")
        or str(uuid.uuid4())
    )
    field = data.get("field")
    value = data.get("value")
    label = data.get("label", str(value))

    if not field:
        return JSONResponse(status_code=400, content={"error": "field is required"})

    # Directly save the chosen button value to the state clipboard
    if hasattr(state, field):
        setattr(state, field, value)
    elif isinstance(state.executor, Executor) and hasattr(state.executor, field):
        setattr(state.executor, field, value)

    # Now let the AI acknowledge the choice and move smoothly to the next question
    history = clean_history(data.get("messages") or [])
    reply, new_state = intake_turn(label, history, state, session_id=session_id)

    if reply is None:
        reply = "Thanks, I've noted that. Let's continue."
        new_state = state

    return {
        "assistant_message": reply,
        "state": state_for_response(new_state, session_id),
        "options": question_options_for_reply(new_state, reply),
        "progress": _EMPTY_PROGRESS,
    }
