"""Guardrails + verifier: the model only PROPOSES; this layer validates, grounds, gates, then checks the reply."""
import re
from .validation import misfiled_address, resolve_address, grounded, norm, tokens, VALIDATORS, Invalid, similarity
from .models import GATED, GROUNDED, LIST_FIELDS, NONE_RE, OPTIONAL_LISTS, STRONG_CORRECTION, Turn, get, set_, FALLBACK_Q, FIELD_ORDER, LABELS
from .session import Session


# ======== guardrails ========


def flatten(t: Turn):
    out = {}
    for k in ("full_name", "home_address", "covers_worldwide_assets", "has_children", "children_names",
              "specific_gifts", "additional_wishes"):
        v = getattr(t, k)
        if v is None or (isinstance(v, (str, list)) and not v):
            continue
        out[k] = v
    if t.executor:
        if t.executor.name:
            out["executor.name"] = t.executor.name
        if t.executor.relationship:
            out["executor.relationship"] = t.executor.relationship
    if t.partial_address and not t.home_address:                 # a partial address is still a proposal for the field
        out["home_address"] = t.partial_address
    return out


def apply_proposal(sess: Session, turn: Turn, msg: str):
    """Apply the model's proposal: validate, ground, gate, derive. Returns {"rejected": {...}, "dropped": [...]}."""
    s = sess.state
    rejected, dropped, proposals, misfiled = {}, [], {}, []
    
    # Don't process state for blocked intents
    if turn.intent in ("off_topic", "probe", "unsafe"):
        return {"rejected": {}, "dropped": []}

    if sess.pending:                                        # resolve an open confirmation first
        if turn.intent == "confirm":
            for p, v in sess.pending["changes"].items():
                set_(s, p, v)
                if p == "has_children" and v is False:
                    s["children_names"] = []
            sess.pending = None
        elif turn.intent == "decline":
            sess.refused.update(sess.pending["changes"])
            sess.pending = None
        else:
            sess.pending["unanswered"] += 1
            if sess.pending["unanswered"] >= 2:             # don't nag forever
                sess.pending = None

    sess.mem.remember_people(turn, msg, s["full_name"])
    sess.mem.remember_notes(turn, msg)

    if turn.intent == "uncertain":                          # "maybe" / "idk": store nothing, skip nothing
        return {"rejected": {}, "dropped": []}

    cue = turn.intent == "correction" or bool(STRONG_CORRECTION.search(msg))
    corpus = sess.corpus(msg)

    for p in OPTIONAL_LISTS:                                 # "no gifts" / "none": an explicit empty list, only for the question just asked
        if (s[p] is None and sess.last_target == p and turn.intent == "answer"
                and not flatten(turn).get(p) and len(msg.split()) <= 8 and NONE_RE.match(msg)):
            s[p] = []
    for p, raw in flatten(turn).items():
        if p == "home_address" and sess.fixed_addr:    # the app already repaired it
            continue
        if p == "home_address":
            val = resolve_address(sess, raw, msg, rejected, dropped)
            if val is None:
                continue
        else:
            if (p == "full_name" and sess.name_partial and sess.last_target == "full_name"
                    and len(str(raw).split()) == 1 and norm(raw) != norm(sess.name_partial)):
                raw = f"{sess.name_partial} {raw}"               # first name earlier + surname now
            try:
                val = VALIDATORS[p](raw)
            except Invalid as e:
                if p == "full_name" and len(str(raw).split()) == 1 and grounded(raw, corpus):
                    sess.name_partial = " ".join(str(raw).split())   # remember the first name, ask for the surname
                if misfiled_address(sess, p, raw, msg):         # an address piece in a name field: not a bad name
                    misfiled.append(raw)
                    continue
                rejected[p] = str(e)
                continue
        if p in OPTIONAL_LISTS and not val:                   # [] only counts through the explicit "none" path above
            continue
        if p in GROUNDED:
            if p == "children_names":
                kept = [n for n in val if grounded(n, corpus)]
                dropped += [n for n in val if n not in kept]
                val = kept
                if not val:
                    continue
            elif not grounded(val, corpus):
                dropped.append(val)
                continue
        old = get(s, p)
        if p.startswith("executor.") and not sess.executor_context(msg):
            if sess.refused.get(p) != val:                   # a role nobody asked about: propose, never store
                proposals[p] = val
            continue
        # List fields accumulate unless there's a correction cue
        if p in LIST_FIELDS and not cue:
            prev = old or []
            val = prev + [n for n in val if n.lower() not in {o.lower() for o in prev}]
        if p in GATED and old not in (None, []) and old != val and not cue \
                and not (p == "home_address" and tokens(old) <= tokens(val)):   # adding detail is not a conflict
            sess.hold({p: val}, {p: old})
            continue
        if p == "has_children" and val is False and s["children_names"] and not cue:
            sess.hold({p: False}, {p: True})
            continue
        set_(s, p, val)
        if p == "full_name":
            sess.name_partial = None
    for raw in misfiled:
        val = resolve_address(sess, raw, msg, rejected, dropped)
        if val:
            s["home_address"] = val
    if proposals:
        sess.hold(proposals, {p: None for p in proposals})

    if s["children_names"]:                                  # derivations
        s["has_children"] = True
    if s["has_children"] is False:
        s["children_names"] = []
    sess.derive_relationship()                               # executor named earlier as "my wife X"

    skips = list(turn.skipped_fields)                        # skips: explicit paths, or the question just asked
    if turn.intent == "skip" and not skips and sess.last_target in sess.missing():
        skips = [sess.last_target]
    for p in skips:
        if p in sess.missing():
            sess.skipped[p] = sess.skipped.get(p, 0) + 1
    for p in list(sess.skipped):
        if p not in sess.missing():
            del sess.skipped[p]
    return {"rejected": rejected, "dropped": dropped}


# ======== verifier ========


REPEAT_SIM = 0.7   # a reply this similar to the previous one counts as a repeat


def reply_problem(turn: Turn, tgt):
    """Why this reply cannot be shown (None = fine). Only a clearly wrong field or question count counts."""
    r = (turn.reply or "").strip()
    if not r:
        return "empty reply"
    q = r.count("?")
    if tgt is None:
        return "asked a question although everything is collected" if q else None
    if q != 1:
        return f"{q} question marks instead of 1"
    if turn.asking in (set(FIELD_ORDER) | {"confirm"}) and turn.asking != tgt:
        return f"asked about {turn.asking} instead of {tgt}"
    return None


def reply_ok(turn: Turn, tgt):
    return reply_problem(turn, tgt) is None


def is_repeat(turn: Turn, reply, history):
    return (turn.intent in ("question", "uncertain") and bool(history)
            and similarity(reply, history[-1][1]) >= REPEAT_SIM)


def fallback_reply(sess, reply, tgt, rejected):
    """Last resort only (model failed twice): keep what it said minus questions, add a plain question."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", reply or "") if x and "?" not in x]
    lead = " ".join(sents[:2])
    if tgt is None:
        return lead or "Thank you, I have everything I need."
    if tgt in rejected:
        lead, q = f"Sorry, {rejected[tgt]}.", FALLBACK_Q[tgt]
    elif tgt == "confirm":
        pe = sess.pending
        parts = [f"change {LABELS[p]} from {pe['old'][p]} to {v}" if pe["old"][p] is not None
                 else f"set {LABELS[p]} to {v}" for p, v in pe["changes"].items()]
        q = "Just to be sure, should I " + " and ".join(parts) + "?"
    else:
        q = FALLBACK_Q[tgt]
    return f"{lead} {q}".strip()
