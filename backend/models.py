"""
backend/models.py — Data Blueprints (Pydantic Models)

In plain English:
Think of this file as the blueprints or "fill-in-the-blank forms" for our app.
It defines exactly what information we need to collect from the user (like name, address, kids, etc.)
and makes sure the data always stays in the right format.
"""
from typing import List, Optional, Union

from pydantic import BaseModel, Field


# ── 1. The Executor Blueprint ──────────────────────────────────────────────────
# An "Executor" is the trusted person appointed to carry out the person's wishes.
class Executor(BaseModel):
    # Name of the executor (e.g., "Jane Doe"). None means we haven't asked or collected it yet.
    name: Optional[str] = None
    # Relationship to the user (e.g., "sister", "friend", "lawyer").
    relationship: Optional[str] = None


# ── 2. The Main Intake State (The Digital Clipboard) ───────────────────────────
# As the user chats with the AI, this object holds all the confirmed details.
# Every time the user shares something new, this clipboard gets updated!
class DocumentIntakeState(BaseModel):
    # The user's full legal name (e.g. "Johnathan Smith")
    full_name: Optional[str] = None

    # The user's home residential address
    home_address: Optional[str] = None

    # True = covers worldwide assets; False = local assets only; None = not asked yet
    covers_worldwide_assets: Optional[bool] = None

    # True = user has children; False = user has no children; None = not answered yet
    has_children: Optional[bool] = None

    # List of children's names (e.g., ["Alice", "Bob"]). Starts as empty list []
    children_names: List[str] = Field(default_factory=list)

    # Details about who will be the executor
    executor: Executor = Field(default_factory=Executor)

    # Specific gifts/bequests (e.g. ["vintage watch to nephew Mark"]).
    # Note: None = question hasn't been asked yet; [] = user explicitly confirmed "none".
    specific_gifts: Optional[List[str]] = None

    # Any extra wishes, funeral requests, or special notes
    additional_wishes: Optional[Union[str, List[str]]] = None


# ── 3. What the AI Sends Back Every Turn ───────────────────────────────────────
# When the AI finishes thinking, it returns the updated clipboard (all fields above)
# PLUS the actual reply text to show in the chat bubble!
class IntakeTurn(DocumentIntakeState):
    """Full LLM response: state fields + the reply message."""
    # The conversational reply text from the assistant (e.g., "Got it! And what is your address?")
    reply: str
