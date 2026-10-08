"""Facts ledger: tracks HOW each fact was learned (stated/confirmed/derived)."""
from typing import List, NamedTuple


class Fact(NamedTuple):
    """A single fact with its source."""
    key: str
    value: str
    source: str  # "stated" (user said it) | "confirmed" (user confirmed) | "derived" (code inferred)


def build_ledger(state: dict) -> List[Fact]:
    """
    Build facts ledger from state.
    Shows what we know and HOW we learned it.
    """
    facts: List[Fact] = []
    
    # Full name
    if state.get("full_name"):
        facts.append(Fact("full_name", state["full_name"], "stated"))
    
    # Home address
    if state.get("home_address"):
        facts.append(Fact("home_address", state["home_address"], "stated"))
    
    # Worldwide assets
    if state.get("covers_worldwide_assets") is not None:
        value = "yes" if state["covers_worldwide_assets"] else "no"
        facts.append(Fact("covers_worldwide_assets", value, "stated"))
    
    # Has children
    if state.get("has_children") is not None:
        value = "yes" if state["has_children"] else "no"
        facts.append(Fact("has_children", value, "stated"))
    
    # Children names
    children = state.get("children_names") or []
    if children:
        for name in children:
            facts.append(Fact("child", name, "stated"))
    
    # Executor
    executor = state.get("executor") or {}
    if executor.get("name"):
        facts.append(Fact("executor.name", executor["name"], "stated"))
    if executor.get("relationship"):
        facts.append(Fact("executor.relationship", executor["relationship"], "stated"))
    
    # Specific gifts
    gifts = state.get("specific_gifts")
    if gifts is not None:
        if gifts:
            for gift in gifts:
                facts.append(Fact("specific_gift", gift, "stated"))
        else:
            facts.append(Fact("specific_gifts", "none", "stated"))
    
    # Additional wishes
    wishes = state.get("additional_wishes")
    if wishes is not None:
        if wishes:
            for wish in wishes:
                facts.append(Fact("additional_wish", wish, "stated"))
        else:
            facts.append(Fact("additional_wishes", "none", "stated"))
    
    return facts


def format_ledger(state: dict) -> str:
    """Format ledger for display."""
    facts = build_ledger(state)
    
    if not facts:
        return "KNOWN FACTS:\n  (nothing yet)"
    
    lines = ["KNOWN FACTS:"]
    for fact in facts:
        lines.append(f"  - {fact.key} = {fact.value} [{fact.source}]")
    
    return "\n".join(lines)
