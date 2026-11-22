"""Intake: rule-based parser (Telugu / English / mixed), optional LLM extractor, reconciliation,
clarification questions and the draft lifecycle (ingest, answer, confirm, cancel).

Trust boundary: nothing here creates a Listing except confirm(), which calls engine.post().
The LLM only proposes values; it is schema-validated and cannot touch safe windows.
"""
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from . import engine, llm
from .engine import ALLERGENS, CATEGORIES, DISCLAIMER, KG_MAX, KG_MIN, Err
from .models import Draft

PLATE_KG = 0.35  # ILLUSTRATIVE, validate with a real caterer
TRAY_KG = 2.5  # ILLUSTRATIVE, validate with a real caterer
CLARIFY_MAX = 2  # free-text questions per draft; allergen chips do not count
DRAFT_TTL_MIN = 15
LLM_TIMEOUT_S = 3
CHIPS = ALLERGENS + ["none"]
FIELDS = ("category", "kg", "ready_by", "allergens")
ORDER = ("category", "kg", "ready_by", "allergens")  # question order, one at a time

LEXICON = {
    "cooked_rice": ["biryani", "biriyani", "briyani", "biryaani", "pulao", "pulav", "pulaavu",
                    "rice", "annam",
                    "బిర్యానీ", "బిర్యాని", "పులావ్", "పులావు", "అన్నం"],
    "curry_dal": ["curry", "koora", "kura", "pappu", "dal", "dhal", "sambar", "rasam",
                  "charu", "కూర", "పప్పు", "సాంబార్", "చారు"],
    "sweets_dairy": ["sweets", "sweet", "mithai", "curd", "yogurt", "paneer",
                     "laddu", "ladoo", "jalebi", "payasam",
                     "పెరుగు", "స్వీట్", "స్వీట్స్", "మిఠాయి", "పనీర్", "లడ్డూ", "పాయసం"],
    "bakery": ["bakery", "bread", "cake", "pastry", "buns", "bun",
               "బేకరీ", "బ్రెడ్", "కేక్", "పేస్ట్రీ", "బన్"],
    "produce": ["fruits", "fruit", "vegetables", "vegetable", "veggies", "produce",
                "పండ్లు", "పండు", "కూరగాయలు", "కూరగాయ", "పళ్ళు"],
    "packaged": ["packaged", "packed", "sealed", "biscuits", "biscuit", "packets", "packet",
                 "chips", "ప్యాకెట్", "ప్యాకెట్లు", "బిస్కెట్లు", "బిస్కెట్"],
}

ALLERGEN_WORDS = {
    "nuts": ["nuts", "nut", "peanut", "peanuts", "cashew", "cashews",
             "పల్లీ", "పల్లీలు", "జీడిపప్పు"],
    "dairy": ["dairy", "milk", "paalu", "పాలు", "పాల", "paneer", "పనీర్", "cheese", "చీజ్"],
    "gluten": ["gluten", "wheat", "maida", "గ్లూటెన్", "గోధుమ", "మైదా"],
    "egg": ["egg", "eggs", "గుడ్డు", "గుడ్లు"],
}

QUESTIONS = {
    "category": ("What food is it? (e.g. biryani, curry, sweets)",
                 "ఏ ఆహారం? (ఉదా: బిర్యానీ, కూర, స్వీట్స్)"),
    "kg": ("How many kilograms (or plates)?", "ఎన్ని కిలోలు (లేదా ప్లేట్లు)?"),
    "ready_by": ("By what time should it be picked up?", "ఏ సమయానికి తీసుకెళ్లాలి?"),
    "allergens": ("Does it contain any allergens? Tap one or more, or none.",
                  "ఏవైనా అలెర్జీ కారకాలు ఉన్నాయా? ఒకటి లేదా none ఎంచుకోండి."),
}

# Clauses that try to instruct the system are dropped before any extraction.
INJECTION = re.compile(
    r"ignore|disregard|forget\b|system prompt|instruction|\brules?\b|safe (time|window)"
    r"|override|you are (now )?an? |పట్టించుకో|విస్మరి", re.I)
_TE_DIGITS = {0x0C66 + i: str(i) for i in range(10)}
_KG = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:kgs?|kilo\S*|కిలో\S*|కేజీ\S*)")
_NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
              "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
              "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
              "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_KG_WORD = re.compile(
    r"(?<![a-z])((?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen"
    r"|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\s*(?:kgs?|kilo\S*)")
_PLATES = re.compile(r"(\d+)\s*(?:plates?|ప్లేట\S*)")
_TRAYS = re.compile(r"(\d+)\s*(?:trays?|ట్రే\S*)")
_REL = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|గంట\S*|minutes?|mins?|min|నిమిష\S*)")
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?!\d)")
_NONE = re.compile(r"\bno\s+allerg|allerg\w*\s+(?:none|ledu|లేదు)|\bnone\b|\bnothing\s+allerg")
_NEG_AFTER = re.compile(r"\s*(?:ledu|లేదు|లేవు|kaadu|కాదు)(?![a-z])")  # "nuts ledu" = no nuts
PART_OF_DAY = {"morning": 9, "ఉదయం": 9, "afternoon": 14, "మధ్యాహ్నం": 14,
               "evening": 18, "సాయంత్రం": 18, "night": 21, "రాత్రి": 21}


# ---- Text helpers ----
def sanitize(text):
    """Drop instruction-like clauses. Returns (clean_text, dropped_flag)."""
    kept, dropped = [], False
    for clause in re.split(r"[,;\n]+", (text or "")[:1000]):
        if INJECTION.search(clause):
            dropped = True
        elif clause.strip():
            kept.append(clause.strip())
    return ", ".join(kept), dropped


def _norm(text):
    return text.lower().translate(_TE_DIGITS)


def _term_re(term):
    if term.isascii():
        # Speech typos: a repeated letter still matches ("sweetss", "nutss", "biriyanii").
        body = "".join(re.escape(c) + "+" for c in term)
        return re.compile(rf"(?<![a-z]){body}(?![a-z])")
    return re.compile(re.escape(term))  # Telugu script: substring match


def _has(t, term):
    return _term_re(term).search(t) is not None


def detect_lang(text):
    return "te" if re.search(r"[\u0C00-\u0C7F]", text or "") else "en"


# ---- Rule-based extraction ----
def _categories(t):
    hits = []
    for cat, terms in LEXICON.items():
        for term in terms:
            for m in _term_re(term).finditer(t):
                hits.append((m.start(), m.end(), cat))
    keep = set()
    for s, e, c in hits:
        # A match inside a longer match of another category is not a separate hit
        # (e.g. Telugu "కూర" inside "కూరగాయలు").
        if any(s2 <= s and e <= e2 and (s2, e2) != (s, e) and c2 != c for s2, e2, c2 in hits):
            continue
        keep.add(c)
    return keep


def _quantity(t):
    m = _KG.search(t)
    if m:
        return float(m.group(1)), None
    m = _KG_WORD.search(t)
    if m:  # spoken number, e.g. "sixty kilo"; bounds are still checked by the caller
        return float(sum(_NUM_WORDS[w] for w in re.split(r"[\s-]+", m.group(1)))), None
    m = _PLATES.search(t)
    if m:
        n = int(m.group(1))
        return round(n * PLATE_KG, 2), f"{n} plates x {PLATE_KG} kg (illustrative)"
    m = _TRAYS.search(t)
    if m:
        n = int(m.group(1))
        return round(n * TRAY_KG, 2), f"{n} trays x {TRAY_KG} kg (illustrative)"
    return None, None


def _ready_by(t, now):
    """Absolute clock time (next future occurrence), relative duration, or part of day."""
    local = timezone.localtime(now)
    for m in _CLOCK.finditer(t):
        hh, mm_s, ap = int(m.group(1)), m.group(2), m.group(3)
        if mm_s is None and ap is None:
            continue  # bare numbers ("2 hours", "200 plates") are not clock times
        mm = int(mm_s or 0)
        if mm > 59 or hh > 23 or (ap and not 1 <= hh <= 12):
            continue
        if ap:
            hours = [hh % 12 + (12 if ap == "pm" else 0)]
        elif hh == 0 or hh > 12:
            hours = [hh]
        else:  # no am/pm: next future occurrence of either 12-hour reading
            hours = [hh % 12, hh % 12 + 12]
        cands = []
        for h in hours:
            c = local.replace(hour=h, minute=mm, second=0, microsecond=0)
            if c <= local:
                c += timedelta(days=1)
            cands.append(c)
        return min(cands)
    rel = _REL.search(t)
    if rel:
        n = float(rel.group(1))
        unit = rel.group(2)
        mins = n * 60 if unit.startswith(("h", "గంట")) else n
        return now + timedelta(minutes=round(mins))
    part = next((h for k, h in PART_OF_DAY.items() if k in t), None)
    if part is not None:
        if "tomorrow" in t or "రేపు" in t:
            return (local + timedelta(days=1)).replace(hour=part, minute=0, second=0, microsecond=0)
        c = local.replace(hour=part, minute=0, second=0, microsecond=0)
        return c + timedelta(days=1) if c <= local else c
    return None


def _mentions(t, terms):
    """(asserted, negated) for one allergen's terms. A term followed by 'ledu' is negated."""
    asserted = negated = False
    for w in terms:
        for m in _term_re(w).finditer(t):
            if _NEG_AFTER.match(t, m.end()):
                negated = True
            else:
                asserted = True
    return asserted, negated


def _allergens(t):
    found, any_negated = [], False
    for a in ALLERGENS:
        asserted, negated = _mentions(t, ALLERGEN_WORDS[a])
        if asserted:
            found.append(a)
        any_negated = any_negated or negated
    if found:
        return found
    if any_negated or _NONE.search(t):
        return ["none"]
    return None  # never assumed: silence means ask


def parse_rules(text, now):
    """Rule-based extraction. Values are None when not stated."""
    clean, dropped = sanitize(text)
    t = _norm(clean)
    out = {"category": None, "kg": None, "ready_by": None, "allergens": None,
           "conversion": None, "errors": [],
           "flags": ["injection_ignored"] if dropped else []}
    cats = _categories(t)
    if len(cats) == 1:
        out["category"] = cats.pop()
    elif len(cats) > 1:
        out["flags"].append("ambiguous_category")
    kg, conv = _quantity(t)
    if kg is not None:
        if KG_MIN <= kg <= KG_MAX:
            out["kg"], out["conversion"] = kg, conv
        else:
            out["errors"].append(f"kg must be between {KG_MIN} and {KG_MAX}")
    out["ready_by"] = _ready_by(t, now)
    out["allergens"] = _allergens(t)
    return out


# ---- LLM extractor (optional, pluggable) ----
def call_llm(text):
    """Set RTS_LLM_URL to a JSON-over-HTTP extractor. Sends message text and the schema only.
    Returns the decoded object, or None when disabled, slow (3 s) or erroring."""
    url = os.environ.get("RTS_LLM_URL")
    if not url:
        return None
    body = json.dumps({"text": text, "schema": list(FIELDS)}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
            return json.loads(resp.read(20000).decode("utf-8"))
    except Exception:
        return None


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_llm(raw, now):
    """Keep only schema fields with the right types and ranges. Anything else is dropped."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    if isinstance(raw.get("category"), str) and raw["category"] in CATEGORIES:
        out["category"] = raw["category"]
    kg = raw.get("kg")
    if _num(kg) and KG_MIN <= kg <= KG_MAX:
        out["kg"] = float(kg)
    pim = raw.get("pickup_in_min")
    if _num(pim) and 1 <= pim <= 24 * 60:
        out["ready_by"] = now + timedelta(minutes=int(pim))
    al = raw.get("allergens")
    if isinstance(al, list) and al and all(isinstance(a, str) and a in CHIPS for a in al):
        vals = list(dict.fromkeys(al))
        if not ("none" in vals and len(vals) > 1):
            out["allergens"] = vals
    return out


# ---- Reconciliation (agreement-based confidence, PRD 5.3) ----
def _same(f, a, b):
    if f == "ready_by":
        return abs((a - b).total_seconds()) <= 300
    if f == "kg":
        return abs(a - b) < 0.01
    if f == "allergens":
        return sorted(a) == sorted(b)
    return a == b


def reconcile(rules, llm, confident=True):
    """confident=False (rules/LLM agreement below llm.CONFIDENCE_MIN) turns every field that
    both sides supplied into a conflict, so it goes through the normal ask path."""
    parsed = {"category": None, "kg": None, "ready_by": None, "allergens": None,
              "conversion": rules.get("conversion"), "errors": list(rules.get("errors", [])),
              "flags": list(rules.get("flags", []))}
    sources, conf, missing = {}, {}, []
    for f in FIELDS:
        r, l = rules.get(f), llm.get(f)
        if r is None and l is None:
            conf[f] = "missing"
            missing.append(f)
            continue
        if r is not None and l is not None:
            if confident and _same(f, r, l):
                value, src, c = r, "both", "high"
            else:
                value, src, c = None, "conflict", "low"
        elif r is not None:
            value, src, c = r, "rules", "medium"
        else:
            value, src, c = l, "llm", "medium"
        parsed[f] = value.isoformat() if isinstance(value, datetime) else value
        sources[f], conf[f] = src, c
        if c == "low":
            missing.append(f)
    return parsed, sources, conf, missing


def ask(missing, clarify_count, lang):
    """Decide what to ask next: one field at a time; allergens are chips and do not count."""
    field = next((f for f in ORDER if f in missing), None)
    if field is None:
        return {"asked": "", "question": None, "chips": [], "form": False}
    q = QUESTIONS[field][1 if lang == "te" else 0]
    if field == "allergens":
        return {"asked": field, "question": q, "chips": CHIPS, "form": False}
    if clarify_count >= CLARIFY_MAX:
        return {"asked": "form", "question": "Please fill in the highlighted fields below.",
                "chips": [], "form": True}
    return {"asked": field, "question": q, "chips": [], "form": False}


def _extract(text, at):
    clean, _ = sanitize(text)
    rules = parse_rules(text, at)
    raw = None
    if clean:
        try:
            raw = call_llm(clean)
        except Exception:
            raw = None
    llm_vals = validate_llm(raw, at)
    # Agreement with the rules decides trust (llm.CONFIDENCE_MIN); the model's self-report is ignored.
    # Allergen lists are compared order-free; with no LLM values there is nothing to disagree with.
    def _view(d):
        return {f: (sorted(d[f]) if f == "allergens" else d[f])
                for f in FIELDS if d.get(f) is not None}
    confident = not llm_vals or llm.agreement(_view(rules), _view(llm_vals)) >= llm.CONFIDENCE_MIN
    parsed, sources, conf, missing = reconcile(rules, llm_vals, confident)
    parsed["extractor"] = "llm" if llm_vals else "fallback"
    return parsed, sources, conf, missing


# ---- Draft lifecycle ----
def _ensure_donor(org):
    if org.role != "donor":
        raise Err(403, "only donors can post listings")


def _load(org, draft_id):
    try:
        return Draft.objects.get(pk=draft_id, org=org)
    except (Draft.DoesNotExist, ValueError, TypeError):
        raise Err(404, "draft not found")


def _check_open(draft, at):
    if draft.status == "open" and at > draft.created + timedelta(minutes=DRAFT_TTL_MIN):
        draft.status = "expired"
        draft.save(update_fields=["status"])
    if draft.status == "expired":
        raise Err(409, "draft expired; please say it again")
    if draft.status == "cancelled":
        raise Err(409, "draft was cancelled")


def _clamp_preview(draft, at):
    """Same clamp rule confirm() applies, previewed on the draft so the card can show it before posting."""
    cat = draft.parsed.get("category")
    ready = draft.parsed.get("ready_by")
    if cat not in CATEGORIES or not ready:
        return ""
    try:
        ready_dt = datetime.fromisoformat(ready)
    except (TypeError, ValueError):
        return ""
    minutes = math.ceil((ready_dt - at).total_seconds() / 60)
    if minutes <= 0:
        return ""
    try:
        expires, pickup_by, clamped = engine.pickup_window(cat, at, minutes)
    except Err:
        return ""
    return engine.clamp_message(expires, pickup_by) if clamped else ""


def draft_json(draft, at=None):
    a = ask(draft.missing, draft.clarify_count, draft.lang)
    # Free-text questions only; allergens are chips and the form fallback is not a question.
    free_text = a["question"] if a["asked"] not in ("", "form", "allergens") else None
    if a["question"]:
        reply = a["question"]
    elif not draft.missing:
        reply = "Please check the card below."  # no Telugu confirmation string exists yet
    else:
        reply = f"Still missing: {', '.join(draft.missing)}."
    return {
        "id": draft.id, "status": draft.status, "lang": draft.lang, "channel": draft.channel,
        "parsed": draft.parsed, "field_sources": draft.field_sources,
        "confidence": draft.confidence, "missing": draft.missing,
        "asked": a["asked"], "question": a["question"], "chips": a["chips"], "form": a["form"],
        "questions": [free_text] if free_text else [],
        "reply_text": reply,
        "conversion": draft.parsed.get("conversion"),
        "extractor": draft.parsed.get("extractor", "fallback"),
        "fields": {f: draft.parsed.get(f) for f in FIELDS},
        "errors": draft.parsed.get("errors", []),
        "clarify_count": draft.clarify_count,
        "clamp_message": _clamp_preview(draft, at or engine.now()) if draft.status == "open" else "",
        "expires": (draft.created + timedelta(minutes=DRAFT_TTL_MIN)).isoformat(),
        "disclaimer": DISCLAIMER,
    }


def ingest(org, text, channel="chat", at=None):
    _ensure_donor(org)
    at = at or engine.now()
    text = (text or "").strip()
    if not text:
        raise Err(400, "text is required")
    if len(text) > 1000:
        raise Err(400, "message is too long (1000 characters max)")
    parsed, sources, conf, missing = _extract(text, at)
    return Draft.objects.create(
        org=org, raw_text=text, lang=detect_lang(text), channel=channel, parsed=parsed,
        field_sources=sources, confidence=conf, missing=missing, created=at)


def answer(org, draft_id, text, at=None):
    at = at or engine.now()
    draft = _load(org, draft_id)
    _check_open(draft, at)
    if draft.status != "open":
        raise Err(409, f"draft is {draft.status}")
    asked = ask(draft.missing, draft.clarify_count, draft.lang)["asked"]
    if asked in ("", "form"):
        raise Err(409, "nothing to answer; edit the form instead")
    clean_rules = parse_rules(text or "", at)
    if asked != "allergens":
        draft.clarify_count += 1
    value = clean_rules.get(asked)
    draft.parsed["errors"] = clean_rules["errors"]
    if value is not None:
        draft.parsed[asked] = value.isoformat() if isinstance(value, datetime) else value
        draft.field_sources[asked] = "donor"
        draft.confidence[asked] = "high"
        draft.missing = [f for f in draft.missing if f != asked]
        if asked == "kg":  # same source as ingest: conversion note comes from the kg quantity
            draft.parsed["conversion"] = clean_rules.get("conversion")
    draft.save()
    return draft


def confirm(org, draft_id, edits=None, idempotency_key="", at=None):
    """The only path that creates a Listing (via engine.post). Returns (listing, clamp_message)."""
    _ensure_donor(org)
    at = at or engine.now()
    draft = _load(org, draft_id)
    if draft.status == "confirmed":
        if idempotency_key and draft.idempotency_key and idempotency_key != draft.idempotency_key:
            raise Err(409, "draft already confirmed with a different key")
        return draft.listing, draft.parsed.get("clamp_message", "")
    _check_open(draft, at)
    if draft.status != "open":
        raise Err(409, f"draft is {draft.status}")
    if edits is None:
        edits = {}
    if not isinstance(edits, dict):
        raise Err(400, "edits must be an object")
    fields = dict(draft.parsed)
    for k in ("category", "kg", "allergens"):
        if k in edits:
            fields[k] = edits[k]
    if edits.get("pickup_in_min") is not None:
        try:
            fields["ready_by"] = (at + timedelta(minutes=int(edits["pickup_in_min"]))).isoformat()
        except (TypeError, ValueError):
            raise Err(400, "pickup_in_min must be a whole number of minutes")
    if fields.get("category") is None:
        raise Err(400, "category is missing")
    if fields.get("allergens") is None:
        raise Err(400, "allergens must be declared (use 'none' if there are none)")
    if fields.get("ready_by") is None:
        raise Err(400, "pickup time is missing")
    ready = datetime.fromisoformat(fields["ready_by"])  # revalidated against the current clock
    minutes = math.ceil((ready - at).total_seconds() / 60)
    if minutes <= 0:
        raise Err(400, "pickup time is already past")
    source = "voice" if draft.channel == "voice" else "chat"
    with transaction.atomic():
        listing, clamped = engine.post(org, fields["category"], fields.get("kg"),
                                       fields["allergens"], minutes, source=source, at=at)
        msg = engine.clamp_message(listing.expires, listing.pickup_by) if clamped else ""
        draft.parsed = {**fields, "clamp_message": msg}
        draft.status = "confirmed"
        draft.listing = listing
        draft.idempotency_key = idempotency_key or ""
        draft.raw_text = ""
        draft.save()
    return listing, msg


def cancel(org, draft_id):
    draft = _load(org, draft_id)
    if draft.status == "confirmed":
        raise Err(409, "draft already confirmed")
    if draft.status == "open":
        draft.status = "cancelled"
        draft.raw_text = ""
        draft.save(update_fields=["status", "raw_text"])
    return {"ok": True}
