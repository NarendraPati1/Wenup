"""Deterministic checks: text helpers, validators (names, addresses, relationships), address merging/repair."""
import difflib
import re



# ======== text ========


UK_POSTCODE = re.compile(r"\b[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}\b")


def strip_postcode(t):
    """Address without its UK postcode (a postcode alone must never count as a house number)."""
    return " ".join(UK_POSTCODE.sub(" ", str(t)).split())


NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10}


def norm(t):
    return " ".join(re.sub(r"[^\w ]+", " ", str(t).lower()).split())


def tokens(t):
    return set(norm(t).split())


def count_from(text):
    m = re.search(r"\d+", text or "")
    if m:
        return int(m.group())
    return next((NUMBER_WORDS[w] for w in norm(text or "").split() if w in NUMBER_WORDS), None)


def grounded(value, corpus):
    """Anti-hallucination: every token of a name must appear in what the user actually wrote."""
    toks, have = norm(value).split(), set(norm(corpus).split())
    return bool(toks) and all(t in have for t in toks)


def similarity(a, b):
    A, B = set(norm(a).split()), set(norm(b).split())
    return len(A & B) / len(A | B) if A and B else 0.0


def close(a, b):
    """Typo-tolerant token match: 'mon' ~ 'monarch', 'punes' ~ 'pune'. Tokens containing digits must match exactly."""
    if a == b:
        return True
    if not a or not b or any(c.isdigit() for c in a + b):
        return False
    if len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def covered(a, b):
    """True if every token of text a is (fuzzily) present in text b."""
    ta, tb = tokens(a), tokens(b)
    return bool(ta) and all(any(close(x, y) for y in tb) for x in ta)


def dedupe_parts(parts):
    """Drop a piece that is already (fuzzily) contained in another, longer piece."""
    keep = []
    for i, p in enumerate(parts):
        n = len(tokens(p))
        dup = any(j != i and covered(p, q) and (len(tokens(q)) > n or (len(tokens(q)) == n and j < i))
                  for j, q in enumerate(parts))
        if not dup:
            keep.append(p)
    return keep


def merge_parts(new, base):
    """Address pieces: new text first, then the earlier words the new text does not already (fuzzily) contain."""
    have = tokens(new)
    new_parts = [p.strip() for p in new.split(",") if p.strip()]
    kept = []
    for p in base.split(","):
        rest = " ".join(w for w in p.split() if not any(close(norm(w), h) for h in have))
        if rest:
            kept.append(rest)
    parts = dedupe_parts(new_parts + kept)
    return ", ".join(sorted(parts, key=lambda p: not any(c.isdigit() for c in strip_postcode(p))))   # flat/house numbers lead (stable)


# ======== validators ========


class Invalid(ValueError):
    pass


NAME_RE = re.compile(r"[^\W\d_]+(?:[ '.\-]+[^\W\d_]+)*\.?")
REL_ALIASES = {"bro": "brother", "sis": "sister", "mom": "mother", "mum": "mother", "dad": "father",
               "attorney": "lawyer", "kid": "child"}
TITLES = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame", "lord", "lady", "rev"}
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]{2,}")   # CJK names are written without spaces


def _fix_case(v):
    return " ".join(w.title() if (w.islower() or w.isupper()) and len(w) > 1 else w for w in v.split(" "))


def v_name(v, need_full=False):
    v = " ".join(str(v).split())
    if len(v) < 2 or len(v) > 80 or not NAME_RE.fullmatch(v):
        raise Invalid("that doesn't look like a valid name")
    if need_full:
        words = [w for w in v.split() if w.lower().rstrip(".") not in TITLES]    # "Mr Smith" is not a full name
        if len(words) < 2 and not CJK.fullmatch(v):
            raise Invalid("I need both a first and a last name")
        v = " ".join(words) if words else v
    return _fix_case(v)


def v_full_name(v):
    return v_name(v, need_full=True)


def _has_house_number(v):
    """A digit token counts as a house/flat number unless it is a 6-digit postal code."""
    return any(re.search(r"\d", t) and not re.fullmatch(r"\d{6}", t) for t in re.split(r"[\s,]+", v))


def v_address(v):
    v = " ".join(str(v).split())
    parts = dedupe_parts([p.strip() for p in v.split(",") if p.strip()])   # 'Mantra Mon' + 'Mantra Monarch' = one piece
    if len(parts) > 1:
        v = ", ".join(parts)
    core = strip_postcode(v)                      # judge the address without its UK postcode
    core_parts = [p.strip() for p in core.split(",") if p.strip()]
    if len(core) < 8 or len(core.split()) < 4 or not (_has_house_number(core) or len(core_parts) >= 3):
        raise Invalid("I still need the full address: a flat or house number (or building, area and city given separately), "
                      "not just a city or area")
    return v


def v_rel(v):
    s = " ".join(re.sub(r"[^a-z \-]", "", str(v).lower()).split())
    s = re.sub(r"^(my|the|his|her|their)\s+", "", s)
    s = REL_ALIASES.get(s, s)
    if not re.fullmatch(r"[a-z][a-z \-]{1,39}", s):
        raise Invalid("that doesn't look like a relationship (for example brother, friend, lawyer)")
    return s


def v_bool(v):
    if isinstance(v, bool):
        return v
    raise Invalid("I need a yes or no")


def v_names(v):
    out, seen = [], set()
    for n in (v if isinstance(v, list) else [v]):
        n = v_name(n)
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    if not out:
        raise Invalid("I need at least one name")
    return out


def v_text_list(v):
    """Validator for lists of text items (gifts, wishes). Empty list is valid."""
    if v is None:
        return None
    if not isinstance(v, list):
        v = [v]
    out = []
    for item in v:
        text = " ".join(str(item).split())
        if text and len(text) <= 500:  # Max 500 chars per item
            out.append(text)
    return out  # Empty list is valid (means "none")


VALIDATORS = {"full_name": v_full_name, "home_address": v_address, "covers_worldwide_assets": v_bool,
              "has_children": v_bool, "children_names": v_names, "executor.name": v_name,
              "executor.relationship": v_rel, "specific_gifts": v_text_list, "additional_wishes": v_text_list}


# ======== address ========


def addr_grounded(sess, text, msg):
    """Address words must come from what the user wrote (typos tolerated: 70% of the words are enough)."""
    s = sess.state
    have = tokens(" ".join([u for u, _ in sess.history] + [msg, s["home_address"] or "", sess.addr_partial or ""]))
    toks = [t for t in norm(text).split() if len(t) >= 3]
    return not toks or sum(t in have for t in toks) / len(toks) >= 0.7


def resolve_address(sess, raw, msg, rejected, dropped):
    """Addresses arrive in pieces: merge each piece with what is already known instead of replacing it."""
    raw = " ".join(str(raw).split())
    stored, partial = sess.state["home_address"], sess.addr_partial
    if stored and tokens(raw) <= tokens(stored):
        return stored                                        # nothing new
    try:
        cand = v_address(raw)                                # complete on its own
        if partial and not stored and sess.last_target == "home_address":
            cand = merge_parts(raw, partial)                 # we were mid-address: keep the earlier pieces
    except Invalid:
        base = stored or partial
        cand = merge_parts(raw, base) if base else raw       # a fragment refines what we already have
    try:
        val = v_address(cand)
    except Invalid as e:
        if addr_grounded(sess, cand, msg):
            sess.addr_partial = cand                         # remember the pieces; the model sees them next turn
            if not stored:
                rejected["home_address"] = str(e)
        else:
            dropped.append(cand)
        return None
    if not addr_grounded(sess, val, msg):
        dropped.append(val)
        return None
    sess.addr_partial = None
    return val


def misfiled_address(sess, p, raw, msg):
    """Safety net: while we were asking for the address, the model filed the answer under a name field."""
    return (p in ("full_name", "executor.name") and sess.last_target == "home_address"
            and not sess.state["home_address"] and tokens(raw) <= tokens(msg))


def typo_fix_address(addr, msg):
    """Deterministic typo repair: "its monarch" turns "Mantra Mon" into "Mantra Monarch" without asking again."""
    words = re.findall(r"[^\W\d_]+", msg)
    if not addr or not words or len(words) > 8:
        return None
    fixed, msg_tokens = addr, tokens(msg)
    for w in words:
        wl = w.lower()
        if len(wl) < 4 or wl in tokens(fixed):
            continue
        for a in re.findall(r"[^\W\d_]+", fixed):
            al = a.lower()
            if len(al) >= 3 and al != wl and al not in msg_tokens and close(al, wl):
                fixed = re.sub(rf"\b{re.escape(a)}\b", w.title() if w.islower() else w, fixed, count=1)
                break
    return fixed if fixed != addr else None
