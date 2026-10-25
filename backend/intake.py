"""
backend/intake.py — Core AI Logic & Langfuse Tracing

In plain English:
This is where the magic happens!
1. We package up the user's message, chat history, and current document state.
2. We send it to Groq's high-speed AI to decide what to ask next and what information to update.
3. We check if the user said something that contradicts what they told us earlier (e.g. saying
   "I have no kids" earlier, but now saying "give my car to my daughter").
4. We record all performance and tokens into Langfuse so we can inspect and debug everything live!
"""
import json
import re
import uuid
from typing import Optional, Tuple
from pydantic import ValidationError

from .config import (
    client_primary, client_fallback,
    PRIMARY_MODEL, FALLBACK_MODEL,
    MAX_MESSAGE_CHARS,
    langfuse, LANGFUSE_ENABLED,
)
from .models import DocumentIntakeState, IntakeTurn
from .prompts import SYSTEM_PROMPT


# ── 1. Contradiction Detection Helper ─────────────────────────────────────────
def detect_contradiction_in_reply(reply: str, old_state: DocumentIntakeState, new_state: DocumentIntakeState) -> Optional[dict]:
    """
    In plain English:
    Did the user just contradict themselves?
    For example:
    - User said 'I have no children', but later says 'leave my jewelry to my daughter'.
    - User gave one name for their executor, but later gives a completely different name.
    
    If the AI's reply indicates a contradiction, this function flags it so we can log it!
    """
    reply_lower = reply.lower()
    
    # Phrases the AI uses when it catches the user contradicting earlier info
    contradiction_indicators = [
        "i notice you mentioned",
        "you mentioned having no children earlier",
        "contradicts",
        "conflict",
        "you said",
        "but you just mentioned",
        "earlier you",
        "previously you",
        "please clarify",
        "which information is correct",
        "which is correct",
    ]
    
    # Check if the AI used any of those warning phrases in its reply
    has_contradiction_language = any(indicator in reply_lower for indicator in contradiction_indicators)
    
    if not has_contradiction_language:
        return None  # No contradiction detected, everything looks good!
    
    # Now figure out WHICH topic was contradicted:
    contradiction_type = "unknown"
    details = {}
    
    # Case A: Children status contradiction
    if old_state.has_children is False and ("son" in reply_lower or "daughter" in reply_lower or "child" in reply_lower):
        contradiction_type = "children_status"
        details = {
            "old_value": "has_children=False",
            "conflict": "mentioned_children_in_gifts_or_conversation",
        }
    elif old_state.has_children is True and ("no child" in reply_lower or "no dependent" in reply_lower):
        contradiction_type = "children_status"
        details = {
            "old_value": "has_children=True",
            "conflict": "later_denied_children",
        }
    
    # Case B: Name contradiction
    if old_state.full_name and new_state.full_name and old_state.full_name != new_state.full_name:
        contradiction_type = "name_conflict"
        details = {
            "old_value": old_state.full_name,
            "new_value": new_state.full_name,
        }
    
    # Case C: Executor contradiction
    if old_state.executor.name and new_state.executor.name and old_state.executor.name != new_state.executor.name:
        contradiction_type = "executor_conflict"
        details = {
            "old_value": old_state.executor.name,
            "new_value": new_state.executor.name,
        }
    
    # Case D: Asset scope contradiction (switching between worldwide vs local only)
    if old_state.covers_worldwide_assets is not None and new_state.covers_worldwide_assets is not None:
        if old_state.covers_worldwide_assets != new_state.covers_worldwide_assets:
            contradiction_type = "asset_scope"
            details = {
                "old_value": "worldwide" if old_state.covers_worldwide_assets else "local",
                "new_value": "worldwide" if new_state.covers_worldwide_assets else "local",
            }
    
    # Case E: Gifts contradiction (said "no gifts" earlier, but now mentioning gifts)
    if old_state.specific_gifts == [] and "gift" in reply_lower:
        contradiction_type = "gifts_conflict"
        details = {
            "old_value": "no_gifts",
            "conflict": "mentioned_gifts_after_saying_none",
        }
    
    return {
        "detected": True,
        "type": contradiction_type,
        "reply_excerpt": reply[:200],
        "details": details,
    }


# ── 2. JSON Parser Helper ─────────────────────────────────────────────────────
def extract_json_object(raw: str) -> dict:
    """
    In plain English:
    The AI returns its answer formatted as JSON. Sometimes it wraps it in markdown backticks
    like ```json { ... } ```. This helper safely extracts the raw { ... } JSON dictionary.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Model response was empty")

    text = raw.strip()
    # Strip markdown code blocks if the model wrapped its output in them
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    # Find the curly braces { ... }
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")

    return json.loads(match.group(0))


# ── 3. Chat History Cleaner ───────────────────────────────────────────────────
def clean_history(raw, max_messages: int = 40) -> list:
    """
    In plain English:
    Cleans up the list of past messages before feeding it to the AI.
    Makes sure only legitimate 'user' and 'assistant' text messages are sent,
    and keeps only the recent history so we don't blow past context limits.
    """
    cleaned = []
    if not isinstance(raw, list):
        return cleaned
    for m in raw[-max_messages:]:
        if not isinstance(m, dict):
            continue
        role, content = m.get("role"), m.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            cleaned.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    return cleaned


# ── 4. State Sanitizer & Formatter ────────────────────────────────────────────
def normalize_state(raw_state) -> DocumentIntakeState:
    """
    Converts incoming raw dictionary data from the browser into our verified
    DocumentIntakeState model. If anything is broken or invalid, returns a fresh blank state.
    """
    if not raw_state:
        return DocumentIntakeState()
    try:
        return DocumentIntakeState.model_validate(raw_state)
    except ValidationError:
        return DocumentIntakeState()


def state_for_response(state: DocumentIntakeState, session_id: str | None = None) -> dict:
    """
    Turns our DocumentIntakeState into a Python dictionary and attaches the session_id
    so the browser and backend stay on the same page.
    """
    payload = state.model_dump()
    payload["_meta"] = {"session_id": session_id or str(uuid.uuid4())}
    return payload


# ── 5. Quick-Choice Suggestion Buttons ────────────────────────────────────────
def question_options_for_reply(state: DocumentIntakeState, reply: str) -> list:
    """
    In plain English:
    When the assistant asks a simple question (like 'Do you have children?' or 'Worldwide or local assets?'),
    we can show clickable buttons directly on the UI (e.g. [Worldwide assets] / [Only local assets]).
    This function checks what the AI asked and returns the appropriate buttons!
    """
    reply_lower = reply.lower()

    # If asset coverage hasn't been set yet and the AI is asking about assets
    if state.covers_worldwide_assets is None:
        asset_kws = ["worldwide", "local asset", "cover asset", "assets you hold",
                     "jurisdiction", "which asset", "asset scope"]
        if any(kw in reply_lower for kw in asset_kws):
            return [
                {"label": "Worldwide assets",  "field": "covers_worldwide_assets", "value": True},
                {"label": "Only local assets", "field": "covers_worldwide_assets", "value": False},
            ]

    # If children question hasn't been answered yet and the AI is asking about children
    if state.has_children is None:
        child_kws = ["children", "child", "kids", "have any child", "do you have child"]
        if any(kw in reply_lower for kw in child_kws):
            return [
                {"label": "Yes, I have children", "field": "has_children", "value": True},
                {"label": "No children",          "field": "has_children", "value": False},
            ]

    return []


# ── 6. The Core LLM Turn (AI Interaction & Tracing) ───────────────────────────
def intake_turn(
    user_message: str,
    chat_history: list,
    current_state: DocumentIntakeState,
    session_id: str | None = None,
):
    """
    In plain English:
    This is the main function that runs for EVERY message from the user.
    - Sends prompt + history + current document data to Groq.
    - If primary model has an issue, automatically falls back to secondary model.
    - Traces every step in Langfuse (tokens, latency, contradictions).
    - Returns (reply_text, updated_document_state).
    """
    # Build the message stack for the AI:
    # 1. System prompt (rules, instructions, persona)
    # 2. What we already know (the current state JSON)
    # 3. Conversation history so far
    # 4. The new message the user just sent
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "Current captured state:\n" + current_state.model_dump_json()},
        *chat_history,
        {"role": "user", "content": user_message},
    ]

    # ── Step A: Open a root trace in Langfuse ──────────────────────────────────
    # This represents the entire user turn in Langfuse dashboard
    root_span = None

    if LANGFUSE_ENABLED and langfuse:
        try:
            root_span = langfuse.start_observation(
                name="intake_turn",
                as_type="span",
                input={"user_message": user_message, "state": current_state.model_dump()},
                metadata={"session_id": session_id or "unknown", "sdk": "langfuse-v5"},
            )
        except Exception as _lf_err:
            print(f"[Langfuse] Failed to open trace span: {_lf_err}")
            root_span = None

    last_err = None
    result_reply = None
    result_state = current_state

    # ── Step B: Call Groq AI (Primary first, then Fallback if needed) ──────────
    for groq_client, model in ((client_primary, PRIMARY_MODEL), (client_fallback, FALLBACK_MODEL)):
        gen_span = None
        # Start a child 'generation' span in Langfuse to track this specific LLM call
        if root_span is not None:
            try:
                gen_span = root_span.start_observation(
                    name="groq_completion",
                    as_type="generation",
                    model=model,
                    input=messages,
                )
            except Exception as _lf_err:
                print(f"[Langfuse] Failed to open generation span: {_lf_err}")
                gen_span = None

        try:
            # Send to Groq API
            completion = groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,   # Lower temperature = more consistent and focused responses
                max_tokens=2048,
            )
            content = completion.choices[0].message.content or ""
            
            # Parse the model's JSON response and update the document state
            turn = IntakeTurn.model_validate(extract_json_object(content))
            new_state = DocumentIntakeState(**turn.model_dump(exclude={"reply"}))

            # Check if any contradiction was detected
            contradiction_info = detect_contradiction_in_reply(turn.reply, current_state, new_state)

            # Close the child generation span in Langfuse with token usage
            if gen_span is not None:
                try:
                    usage = completion.usage
                    gen_span.update(
                        output=content,
                        usage_details={
                            "input": usage.prompt_tokens if usage else 0,
                            "output": usage.completion_tokens if usage else 0,
                        },
                        metadata={
                            "contradiction_detected": contradiction_info is not None,
                            "contradiction_type": contradiction_info["type"] if contradiction_info else None,
                        },
                    ).end()
                except Exception as _lf_err:
                    print(f"[Langfuse] Failed to close generation span: {_lf_err}")

            # If a contradiction was detected, record it as a Warning Event and a Score in Langfuse!
            if contradiction_info and root_span is not None:
                try:
                    root_span.create_event(
                        name="contradiction_detected",
                        metadata={
                            "contradiction_type": contradiction_info["type"],
                            "details": contradiction_info["details"],
                            "reply_excerpt": contradiction_info["reply_excerpt"],
                            "old_state": {
                                "has_children": current_state.has_children,
                                "children_names": current_state.children_names,
                                "full_name": current_state.full_name,
                                "executor_name": current_state.executor.name,
                                "covers_worldwide_assets": current_state.covers_worldwide_assets,
                                "specific_gifts": current_state.specific_gifts,
                            },
                            "new_state": {
                                "has_children": new_state.has_children,
                                "children_names": new_state.children_names,
                                "full_name": new_state.full_name,
                                "executor_name": new_state.executor.name,
                                "covers_worldwide_assets": new_state.covers_worldwide_assets,
                                "specific_gifts": new_state.specific_gifts,
                            },
                        },
                        level="WARNING",
                    )
                    # Log a numerical score (1.0 = contradiction) for dashboard analytics
                    root_span.score(
                        name="contradiction_detected",
                        value=1.0,
                        comment=f"Contradiction type: {contradiction_info['type']}",
                    )
                except Exception as _lf_err:
                    print(f"[Langfuse] Failed to log contradiction event: {_lf_err}")

            result_reply = turn.reply
            result_state = new_state
            break  # Call succeeded! Break out of the retry loop.

        except Exception as e:
            # If the primary model failed, record error and try the fallback model next
            last_err = e
            if gen_span is not None:
                try:
                    gen_span.update(level="ERROR", status_message=str(e)).end()
                except Exception:
                    pass

    # ── Step C: Close root span and flush pending traces to Langfuse ───────────
    if root_span is not None:
        try:
            if result_reply is not None:
                root_span.update(
                    output={"reply": result_reply, "state": result_state.model_dump()},
                    metadata={"success": True},
                ).end()
            else:
                root_span.update(
                    level="ERROR",
                    status_message=str(last_err),
                    metadata={"success": False},
                ).end()
        except Exception as _lf_err:
            print(f"[Langfuse] Failed to close root span: {_lf_err}")
        try:
            langfuse.flush()  # Immediately push data to the Langfuse cloud
        except Exception:
            pass

    return result_reply, result_state
