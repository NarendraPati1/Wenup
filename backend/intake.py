"""
backend/intake.py — Core AI Logic & Langfuse Tracing

This is where the magic happens!
1. We package up the user's message, chat history, and current document state.
2. We send it to Groq's high-speed AI to decide what to ask next and what information to update.
3. We record all performance and tokens into Langfuse so we can inspect and debug everything live!
"""
import json
import re
import uuid
from typing import Optional

from pydantic import ValidationError

from .config import (
    client_primary,
    client_fallback,
    PRIMARY_MODEL,
    FALLBACK_MODEL,
    MAX_MESSAGE_CHARS,
    langfuse,
    LANGFUSE_ENABLED,
)
from .models import DocumentIntakeState, IntakeTurn
from .prompts import SYSTEM_PROMPT


# ── 1. JSON Parser Helper ─────────────────────────────────────────────────────
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


# ── 2. Chat History Cleaner ───────────────────────────────────────────────────
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


# ── 3. State Sanitizer & Formatter ────────────────────────────────────────────
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


# ── 4. Quick-Choice Suggestion Buttons ────────────────────────────────────────
def question_options_for_reply(state: DocumentIntakeState, reply: str) -> list:
    """
    In plain English:
    When the assistant asks a simple question (like 'Do you have children?' or 'Worldwide or local assets?'),
    we can show clickable buttons directly on the UI (e.g. [Worldwide assets] / [Only local assets]).
    This function checks what the AI asked and returns the appropriate buttons!
    """
    reply_lower = reply.lower()

    if state.covers_worldwide_assets is None:
        asset_kws = ["worldwide", "local asset", "cover asset", "assets you hold",
                     "jurisdiction", "which asset", "asset scope"]
        if any(kw in reply_lower for kw in asset_kws):
            return [
                {"label": "Worldwide assets",  "field": "covers_worldwide_assets", "value": True},
                {"label": "Only local assets", "field": "covers_worldwide_assets", "value": False},
            ]

    if state.has_children is None:
        child_kws = ["children", "child", "kids", "have any child", "do you have child"]
        if any(kw in reply_lower for kw in child_kws):
            return [
                {"label": "Yes, I have children", "field": "has_children", "value": True},
                {"label": "No children",          "field": "has_children", "value": False},
            ]

    return []



def intake_turn(
    user_message: str,
    chat_history: list,
    current_state: DocumentIntakeState,
    session_id: str | None = None,
):
    """
    Main function executed whenever the user sends a message.

    Responsibilities:
    1. Build conversation context.
    2. Call the primary Groq model.
    3. Validate the LLM's JSON response using Pydantic.
    4. Update the document intake state.
    5. Retry using a fallback model if the primary fails.
    6. Track execution, latency and token usage in Langfuse.

    Returns:
        tuple: (reply_text, updated_document_state)
    """

    # --------------------------------------------------
    # STEP 1: BUILD THE MESSAGES FOR THE LLM
    # --------------------------------------------------

    messages = [
        # System prompt contains the main instructions,
        # rules and behavior of the Document Intake Assistant.
        {"role": "system", "content": SYSTEM_PROMPT},

        # Pass the currently collected document information.
        # model_dump_json() converts the Pydantic object into JSON.
        # This allows the LLM to understand what information
        # has already been collected from previous conversations.
        {
            "role": "system",
            "content": "Current captured state:\n"
                       + current_state.model_dump_json()
        },

        # Include previous user and assistant messages.
        # This gives the LLM conversational context.
        *chat_history,

        # Add the latest user message at the end.
        {"role": "user", "content": user_message},
    ]

    # --------------------------------------------------
    # STEP 2: INITIALIZE LANGFUSE TRACING
    # --------------------------------------------------

    # root_span represents the complete execution of this function.
    # Initially, no tracing span exists.
    root_span = None

    # Only create a trace if Langfuse is enabled and initialized.
    if LANGFUSE_ENABLED and langfuse:
        try:
            root_span = langfuse.start_observation(
                name="intake_turn",

                # A span represents an operation or workflow.
                as_type="span",

                # Record the input received by this function.
                input={
                    "user_message": user_message,
                    "state": current_state.model_dump()
                },

                # Additional information useful for debugging.
                metadata={
                    "session_id": session_id or "unknown",
                    "sdk": "langfuse-v5"
                },
            )

        except Exception as _lf_err:
            # If Langfuse fails, the application should still work.
            print(f"[Langfuse] Failed to open trace span: {_lf_err}")
            root_span = None

    # --------------------------------------------------
    # STEP 3: INITIALIZE RESULT VARIABLES
    # --------------------------------------------------

    # Stores the last error encountered during model execution.
    last_err = None

    # Stores the final response generated by the LLM.
    result_reply = None

    # If both models fail, preserve the previous document state.
    # This prevents accidental loss of already collected information.
    result_state = current_state

    # --------------------------------------------------
    # STEP 4: TRY PRIMARY MODEL, THEN FALLBACK MODEL
    # --------------------------------------------------

    # First iteration:
    #   client_primary + PRIMARY_MODEL
    #
    # Second iteration:
    #   client_fallback + FALLBACK_MODEL
    #
    # If the primary model fails for any reason,
    # execution automatically moves to the fallback model.

    for groq_client, model in (
        (client_primary, PRIMARY_MODEL),
        (client_fallback, FALLBACK_MODEL)
    ):

        # Each model call gets its own generation span.
        gen_span = None

        if root_span is not None:
            try:
                gen_span = root_span.start_observation(
                    name="groq_completion",

                    # A generation span specifically tracks an LLM call.
                    as_type="generation",

                    # Record which model is being called.
                    model=model,

                    # Record the complete prompt sent to the model.
                    input=messages,
                )

            except Exception as _lf_err:
                print(
                    f"[Langfuse] Failed to open generation span: {_lf_err}"
                )
                gen_span = None

        # --------------------------------------------------
        # STEP 5: CALL GROQ API AND PROCESS THE RESPONSE
        # --------------------------------------------------

        try:

            # Send the messages to the Groq Chat Completions API.
            completion = groq_client.chat.completions.create(
                model=model,
                messages=messages,

                # Lower temperature makes responses more consistent.
                temperature=0.2,

                # Maximum number of tokens in the generated response.
                max_tokens=2048,
            )

            # Extract the actual text generated by the LLM.
            # If content is None, use an empty string.
            content = completion.choices[0].message.content or ""

            # --------------------------------------------------
            # STEP 6: EXTRACT AND VALIDATE JSON
            # --------------------------------------------------

            # The LLM is expected to return structured JSON.
            #
            # extract_json_object():
            # Extracts a JSON object from the LLM response.
            #
            # IntakeTurn.model_validate():
            # Validates that JSON against the IntakeTurn Pydantic schema.
            #
            # If required fields or types are incorrect,
            # Pydantic raises a ValidationError.
            turn = IntakeTurn.model_validate(
                extract_json_object(content)
            )

            # --------------------------------------------------
            # STEP 7: CONVERT RESPONSE INTO DOCUMENT STATE
            # --------------------------------------------------

            # turn contains both:
            #   1. reply: message to show the user.
            #   2. Other structured fields: collected document information.
            #
            # model_dump(exclude={"reply"}) removes the reply field.
            #
            # DocumentIntakeState then validates the remaining
            # information against the document state schema.
            new_state = DocumentIntakeState(
                **turn.model_dump(exclude={"reply"})
            )

            # --------------------------------------------------
            # STEP 8: RECORD SUCCESSFUL GENERATION IN LANGFUSE
            # --------------------------------------------------

            if gen_span is not None:
                try:

                    # Extract token usage returned by Groq.
                    usage = completion.usage

                    # Update Langfuse with generated output and token usage.
                    gen_span.update(
                        output=content,

                        usage_details={
                            # Number of input tokens sent to the model.
                            "input": usage.prompt_tokens if usage else 0,

                            # Number of tokens generated by the model.
                            "output": usage.completion_tokens if usage else 0,
                        },
                    ).end()

                except Exception as _lf_err:
                    print(
                        f"[Langfuse] Failed to close generation span: {_lf_err}"
                    )

            # --------------------------------------------------
            # STEP 9: STORE THE SUCCESSFUL RESULT
            # --------------------------------------------------

            # Extract the conversational reply.
            result_reply = turn.reply

            # Save the newly validated document state.
            result_state = new_state

            # Important:
            # We successfully received and validated a response.
            # Stop the loop. No need to call the fallback model.
            break

        # --------------------------------------------------
        # STEP 10: HANDLE FAILURE AND TRIGGER FALLBACK
        # --------------------------------------------------

        except Exception as e:

            # Store the error so we can report it if both models fail.
            last_err = e

            # Mark this generation span as failed.
            if gen_span is not None:
                try:
                    gen_span.update(
                        level="ERROR",
                        status_message=str(e)
                    ).end()

                except Exception:
                    pass

            # No break here!
            # The loop automatically moves to the next model.
            # If primary failed, fallback gets a chance.

    # --------------------------------------------------
    # STEP 11: CLOSE THE ROOT LANGFUSE TRACE
    # --------------------------------------------------

    if root_span is not None:
        try:

            # If at least one model succeeded:
            if result_reply is not None:

                # Record the final response and updated document state.
                root_span.update(
                    output={
                        "reply": result_reply,
                        "state": result_state.model_dump()
                    },

                    metadata={"success": True},
                ).end()

            else:

                # Both models failed.
                # Record the final error.
                root_span.update(
                    level="ERROR",
                    status_message=str(last_err),
                    metadata={"success": False},
                ).end()

        except Exception as _lf_err:
            print(f"[Langfuse] Failed to close root span: {_lf_err}")

        # Flush sends pending trace information to Langfuse.
        # This helps ensure observations are delivered.
        try:
            langfuse.flush()
        except Exception:
            pass

    # --------------------------------------------------
    # STEP 12: RETURN FINAL RESULT
    # --------------------------------------------------

    # Returns two values:
    # 1. Text that should be displayed to the user.
    # 2. Updated structured document intake state.
    return result_reply, result_state
