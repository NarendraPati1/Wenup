"""Data model: field registry, state helpers, LLM output schema, error types."""
import re
from typing import List, Literal, Optional
from pydantic import BaseModel, Field



# ======== fields ========


FIELD_ORDER = ["full_name", "home_address", "covers_worldwide_assets", "has_children",
               "children_names", "executor.name", "executor.relationship", "specific_gifts", "additional_wishes"]
LABELS = {"full_name": "your name", "home_address": "your address",
          "covers_worldwide_assets": "the worldwide-assets question", "has_children": "the children question",
          "children_names": "your children's names", "executor.name": "your executor's name",
          "executor.relationship": "your executor's relationship to you",
          "specific_gifts": "any specific gifts you'd like to leave",
          "additional_wishes": "any additional wishes"}
FALLBACK_Q = {"full_name": "What's your full name, first and last?",
              "home_address": "What's your complete home address?",
              "covers_worldwide_assets": "Should this cover your assets worldwide?",
              "has_children": "Do you have any children?",
              "children_names": "What are your children's names?",
              "executor.name": "Who would you like to name as your executor?",
              "executor.relationship": "How is your executor related to you?",
              "specific_gifts": "Are there any specific gifts you'd like to leave to particular people?",
              "additional_wishes": "Do you have any additional wishes to include?"}
FIELD_PURPOSES = {
    "full_name": "printed at the top of the draft document to say whose wishes these are",
    "home_address": "printed under the name so the draft states where the person lives",
    "covers_worldwide_assets": "decides whether the draft covers assets in every country or only in the home country",
    "has_children": "decides whether the draft has a family section that lists children",
    "children_names": "listed in the family section of the draft",
    "executor.name": "the executor is the person who would carry out the wishes written in the document",
    "executor.relationship": "stated next to the executor's name, for example brother or friend",
    "specific_gifts": "lists any particular items or amounts you want to give to specific people",
    "additional_wishes": "includes any other instructions or wishes you have for the document",
}

GATED = {"full_name", "home_address", "executor.name"}   # silent overwrite not allowed without a correction cue
GROUNDED = {"full_name", "executor.name", "children_names"}   # values must be words the user actually wrote
# Intent comes from the model; this regex is only a narrow backup for unmistakable correction phrases.
STRONG_CORRECTION = re.compile(r"\b(actually|i meant|my mistake|correction)\b", re.I)
EXEC_CUE = re.compile(
    r"\b(executor|executrix|appoint\w*|nominat\w*|trustee|in charge of (my )?(will|estate)|carry out my)\b", re.I)
LIST_FIELDS = {"children_names", "specific_gifts", "additional_wishes"}     # items accumulate across turns
OPTIONAL_LISTS = {"specific_gifts", "additional_wishes"}                    # None = not asked, [] = "none"
# "no / none / nothing else / I don't have any": a short message like this answers an optional question with "none".
NONE_RE = re.compile(r"^\W*(no|nope|nah|none|nothing|nil|n/?a|not really|i (don'?t|do not) (have|want) any|"
                     r"that'?s (all|it)|all good)\b", re.I)
MEMORY_MAX = 40


# ======== state ========


def new_state():
    return {"full_name": None, "home_address": None, "covers_worldwide_assets": None,
            "has_children": None, "children_names": [],
            "executor": {"name": None, "relationship": None},
            "specific_gifts": None, "additional_wishes": None}   # None = not asked yet, [] = client said "none"


def get(s, p):
    a, _, b = p.partition(".")
    return s[a][b] if b else s[a]


def set_(s, p, v):
    a, _, b = p.partition(".")
    if b:
        s[a][b] = v
    else:
        s[a] = v


def state_diff(a, b):
    """Fields whose value differs between two states: {path: {"from": old, "to": new}}."""
    out = {}
    for p in FIELD_ORDER:
        if get(a, p) != get(b, p):
            out[p] = {"from": get(a, p), "to": get(b, p)}
    return out


# ======== schema ========


class ExecutorOut(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None


class Person(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None


class Note(BaseModel):
    key: Optional[str] = None
    fact: Optional[str] = None
    evidence: Optional[str] = None


class Turn(BaseModel):
    intent: Literal["answer", "correction", "skip", "question",
                    "uncertain", "confirm", "decline", "off_topic", "unsafe", "probe", "other"] = "answer"
    full_name: Optional[str] = None
    home_address: Optional[str] = None
    covers_worldwide_assets: Optional[bool] = None
    has_children: Optional[bool] = None
    children_names: Optional[List[str]] = None
    executor: Optional[ExecutorOut] = None
    specific_gifts: Optional[List[str]] = None
    additional_wishes: Optional[List[str]] = None
    skipped_fields: List[str] = Field(default_factory=list)
    mentions: Optional[List[Person]] = None
    notes: Optional[List[Note]] = None
    partial_address: Optional[str] = None
    asking: Optional[str] = None
    reply: str = ""


# ======== errors ========


class LLMError(Exception):
    """The model layer failed after all routing / retry policies were exhausted."""


class RateLimit(LLMError):
    """Every route is rate limited (waiting briefly helps for per-minute limits, not for daily ones)."""


class ProviderError(LLMError):
    """One failed attempt against one route. `kind` tells the gateway what to do about it:

    rate_limit         per-minute limit: cool the route down, try the next one
    daily_limit        daily limit: park the route for an hour
    auth               bad / revoked key: disable that key slot for the session
    dead_model         model missing or decommissioned: disable that model for the session
    unsupported_param  the model rejected `include_reasoning`: retry once without it
    bad_request        other 4xx: this route cannot serve the request, try the next one
    transient          timeout / connection / 5xx: retry once, then cool down briefly
    bad_output         the model answered, but not with valid JSON for our schema: retry once, then next route
    """

    def __init__(self, kind, message, wait=None, status=None, headers=None):
        super().__init__(message)
        self.kind = kind
        self.wait = wait
        self.status = status
        self.headers = headers or {}
