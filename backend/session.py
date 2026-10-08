"""Session: per-conversation memory, what is missing / what to ask next."""
import re
from .models import MEMORY_MAX, FIELD_ORDER, EXEC_CUE, get, new_state
from .validation import count_from, covered, grounded, norm, Invalid, v_name, v_rel


# ======== memory ========


class SessionMemory:
    def __init__(self):
        self.people = {}   # normalized name -> {name, relationship}: everyone the user mentioned
        self.notes = {}    # key -> {fact, evidence}

    # ---- people: "my wife Gayatri" is remembered, so she is never asked about again ----
    def remember_people(self, turn, msg, own_name=None):
        for m in (turn.mentions or []):
            if not (m.name and m.relationship):
                continue
            try:
                name, rel = v_name(m.name), v_rel(m.relationship)
            except Invalid:
                continue
            if not (grounded(name, msg) and grounded(m.relationship, msg)):    # both words must come from the user
                continue
            if own_name and norm(name) == norm(own_name):
                continue
            self.people[norm(name)] = {"name": name, "relationship": rel}

    def person_for(self, name):
        for p in self.people.values():
            if covered(name, p["name"]) or covered(p["name"], name):
                return p
        return None

    # ---- notes: the LLM proposes free-form facts, the code keeps only the ones backed by a real quote ----
    def remember_notes(self, turn, msg):
        for n in (turn.notes or []):
            key = re.sub(r"[^a-z0-9_]+", "_", (n.key or "").lower()).strip("_")
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", key):
                continue
            fact = " ".join((n.fact or "").split())
            if not fact:
                self.notes.pop(key, None)                        # the client took it back
                continue
            ev = norm(n.evidence or "")
            if len(fact) > 200 or len(ev) < 2 or ev not in norm(msg):
                continue                                         # no real quote from the user = not stored
            if len(self.notes) >= MEMORY_MAX and key not in self.notes:
                continue
            self.notes[key] = {"fact": fact, "evidence": n.evidence.strip()}

    def expected_children(self):
        for k, v in self.notes.items():
            if re.search(r"child|kid", k) and re.search(r"count|number|total", k):
                n = count_from(v["fact"])
                if n and 0 < n <= 20:
                    return n
        return None

    def clear(self):
        self.people.clear()
        self.notes.clear()


# ======== session ========


class Session:
    def __init__(self):
        self.state = new_state()
        self.skipped = {}         # path -> times skipped (2 = left open on purpose)
        self.pending = None       # {"changes": {path: new}, "old": {path: old}, "unanswered": n} awaiting confirmation
        self.refused = {}         # path -> value the user already refused (never proposed again)
        self.last_target = None   # what the assistant asked about on its last turn
        self.addr_partial = None  # pieces of an address given so far, not yet complete
        self.name_partial = None  # a first name given on its own, waiting for the surname
        self.history = []         # [(user_text, assistant_reply)]
        self.mem = SessionMemory()
        self.fixed_addr = False   # True when the app already repaired a typo in the address this turn

    # ---- what is missing / what to ask next ----
    def expected_children(self):
        return self.mem.expected_children()

    def missing(self):
        s, out = self.state, []
        for p in FIELD_ORDER:
            if p == "children_names":
                if s["has_children"] is True:
                    exp = self.expected_children()                 # "I have 3 kids" -> keep asking until 3 names
                    if not s["children_names"] or (exp and len(s["children_names"]) < exp):
                        out.append(p)
            elif get(s, p) is None:
                out.append(p)
        return out

    def deferred(self):
        return [p for p in self.missing() if self.skipped.get(p, 0) >= 2]

    def queue(self):
        m = [p for p in self.missing() if self.skipped.get(p, 0) < 2]
        return [p for p in m if p not in self.skipped] + [p for p in m if p in self.skipped]  # skipped come last

    def target(self, rejected):
        if rejected:
            return next(p for p in FIELD_ORDER if p in rejected)
        if self.pending:
            return "confirm"
        q = self.queue()
        return q[0] if q else None

    def done(self):
        return not self.queue() and not self.pending

    # ---- helpers used by the guardrails ----
    def corpus(self, msg):
        s = self.state
        known = [s["full_name"], s["executor"]["name"]] + list(s["children_names"]) + [p["name"] for p in self.mem.people.values()]
        return " ".join([u for u, _ in self.history[-3:]] + [msg] + [k for k in known if k])

    def executor_context(self, msg):
        """May executor facts be stored from this message? Only if the user mentions the executor, the last
        question was about the executor, or the executor is already partly filled. 'X is my wife' alone is not."""
        ex = self.state["executor"]
        return (bool(EXEC_CUE.search(msg)) or (self.last_target or "").startswith("executor.")
                or ex["name"] is not None or ex["relationship"] is not None)

    def derive_relationship(self):
        ex = self.state["executor"]
        if ex["name"] and ex["relationship"] is None:
            p = self.mem.person_for(ex["name"])
            if p:
                ex["relationship"] = p["relationship"]

    def hold(self, changes, old):
        if self.pending is None:                                 # one open confirmation at a time
            self.pending = {"changes": changes, "old": old, "unanswered": 0}

    def forget(self):
        self.mem.clear()
        self.history.clear()
        self.addr_partial = None
        self.name_partial = None

    def facts_ledger(self):
        """Build a facts ledger showing what we know and how we learned it."""
        from .ledger import build_ledger
        return build_ledger(self.state)
