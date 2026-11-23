"""Dispatch core: spoilage-clock matching, claim and OTP handoff state machine, impact.

No HTTP here. Every listing is created by post(). Only OTP-confirmed deliveries count as impact.
"""
import math
import re
import secrets
import threading
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, F, Q, Sum, Value, When
from django.utils import timezone

from .models import Event, Listing, Offer, Org

# ---- Tunable rules (illustrative demo defaults; see README) ----
SPEED_KMH = 25
ROAD_FACTOR = 1.3
HANDLING_MIN = 10
MARGIN_MIN = 30
K = 3  # offers per tier
TIERS = [(0.0, 3), (0.25, 6), (0.5, 12), (0.7, 25)]  # (elapsed fraction, radius km)
MEALS_PER_KG = (0.5, 0.4, 0.3)  # low / mid / high ASSUMPTION
CO2E_PER_KG = (1.9, 2.5, 3.3)  # INDICATIVE placeholder, cite a source before publishing
RS_PER_MEAL = 4
OTP_MAX_ATTEMPTS = 5
OTP_TTL_MINUTES = 10

KG_MIN, KG_MAX = 1, 500
ALLERGENS = ["nuts", "dairy", "gluten", "egg"]

# Safe windows are conservative demo defaults. Validate with FSSAI guidance and a
# local food-safety officer before any real use.
CATEGORIES = {
    "cooked_rice": {"label": "Cooked rice", "safe_hours": 4,
                    "storage": "Keep hot or chill quickly; eat within the window."},
    "curry_dal": {"label": "Curry / dal", "safe_hours": 4,
                  "storage": "Keep hot or chill quickly; eat within the window."},
    "sweets_dairy": {"label": "Sweets / dairy", "safe_hours": 6,
                     "storage": "Refrigerate; dairy spoils fastest."},
    "bakery": {"label": "Bakery", "safe_hours": 24, "storage": "Keep dry and covered."},
    "produce": {"label": "Produce", "safe_hours": 48, "storage": "Keep cool and ventilated."},
    "packaged": {"label": "Packaged", "safe_hours": 72,
                 "storage": "Keep sealed; check the pack date."},
}

DISCLAIMER = ("The platform connects people and does not certify food safety. "
              "Allergens are as declared by the donor.")

POSTED, CLAIMED, COLLECTED, DELIVERED, EXPIRED = (
    Listing.POSTED, Listing.CLAIMED, Listing.COLLECTED, Listing.DELIVERED, Listing.EXPIRED,
)


class Err(Exception):
    """Maps to an HTTP status in views. Message goes into {"error": ...}."""

    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


# ---- Simulated clock (per process, demo only) ----
_clock_lock = threading.Lock()
_clock = {"scale": 1.0, "real0": timezone.now(), "sim0": timezone.now()}


def now():
    real = timezone.now()
    with _clock_lock:
        return _clock["sim0"] + (real - _clock["real0"]) * _clock["scale"]


def set_scale(scale):
    with _clock_lock:
        real = timezone.now()
        current = _clock["sim0"] + (real - _clock["real0"]) * _clock["scale"]
        _clock.update(scale=max(1.0, min(float(scale), 600.0)), real0=real, sim0=current)
        return _clock["scale"]


def reset_clock():
    with _clock_lock:
        t = timezone.now()
        _clock.update(scale=1.0, real0=t, sim0=t)


# ---- Geometry and capacity ----
def km(a, b):
    """Haversine distance between two Orgs, in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def travel_min(a, b):
    return km(a, b) * ROAD_FACTOR / SPEED_KMH * 60


def free_capacity(org):
    used = (Listing.objects.filter(receiver=org, status__in=[CLAIMED, COLLECTED])
            .aggregate(s=Sum("kg"))["s"] or 0)
    return org.capacity - used


def free_capacities(orgs=None):
    """Batch-compute free capacity map for receivers to eliminate N+1 DB queries."""
    qs = Listing.objects.filter(status__in=[CLAIMED, COLLECTED], receiver__isnull=False)
    if orgs is not None:
        qs = qs.filter(receiver__in=orgs)
    used_map = {row["receiver_id"]: (row["used"] or 0.0)
                for row in qs.values("receiver_id").annotate(used=Sum("kg"))}
    return used_map


def free_volunteers():
    busy = (Listing.objects.filter(status__in=[CLAIMED, COLLECTED])
            .exclude(volunteer=None).values_list("volunteer_id", flat=True))
    return list(Org.objects.filter(role="volunteer").exclude(id__in=list(busy)))


# ---- Matching ----
def rank(listing, at, radius):
    """Return feasible receivers for this listing within radius, best first."""
    donor = listing.donor
    remaining = (listing.expires - at).total_seconds() / 60
    window = (listing.expires - listing.created).total_seconds() / 60
    if remaining - MARGIN_MIN <= 0:
        return []
    u = min(1.0, max(0.0, 1 - remaining / window))
    weights = {"proximity": 0.30 + 0.20 * u, "quantity": 0.20,
               "need": 0.30 - 0.10 * u, "fairness": 0.20 - 0.10 * u}
    vols = free_volunteers()
    receivers = list(Org.objects.filter(role="receiver"))
    used_map = free_capacities(receivers)
    out = []
    for r in receivers:
        d = km(donor, r)
        if d > radius:  # hard filter: distance
            continue
        free = r.capacity - (used_map.get(r.id) or 0.0)
        if free < listing.kg:  # hard filter: capacity
            continue
        lead = min((travel_min(v, donor) for v in vols), default=travel_min(r, donor))
        if at + timedelta(minutes=lead) > listing.pickup_by:  # hard filter: collector reaches donor
            continue
        eta = HANDLING_MIN + lead + travel_min(donor, r)
        if eta > remaining - MARGIN_MIN:  # hard filter: ETA inside safe window
            continue
        hours = (at - r.last_served).total_seconds() / 3600 if r.last_served else 48.0
        comps = {
            "proximity": 1 - eta / (remaining - MARGIN_MIN),
            "quantity": min(1.0, listing.kg / free),
            "need": r.need,
            "fairness": min(1.0, hours / 48),
        }
        score = sum(weights[k] * comps[k] for k in comps)
        out.append({"receiver": r, "score": round(score, 4), "eta": round(eta, 1),
                    "distance": round(d, 2),
                    "parts": {"components": {k: round(v, 4) for k, v in comps.items()},
                              "weights": {k: round(v, 4) for k, v in weights.items()}}})
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def _event(listing, at, text):
    Event.objects.create(listing=listing, at=at, text=text[:300])


def escalate(listing, at):
    """Offer the top K new receivers at the first tier (after the current one) that has any."""
    if listing.status != POSTED:
        return False
    already = set(listing.offers.values_list("receiver_id", flat=True))
    for t in range(listing.tier + 1, len(TIERS)):
        radius = TIERS[t][1]
        cands = [c for c in rank(listing, at, radius) if c["receiver"].id not in already]
        listing.tier = t
        listing.save(update_fields=["tier"])
        if cands:
            for c in cands[:K]:
                Offer.objects.create(listing=listing, receiver=c["receiver"], score=c["score"],
                                     parts=c["parts"], eta=c["eta"], tier=t)
            _event(listing, at, f"Offered to {min(K, len(cands))} receiver(s) within {radius} km (tier {t})")
            return True
    return False


def due_tier(listing, at):
    total = (listing.pickup_by - listing.created).total_seconds()
    f = 1.0 if total <= 0 else min(1.0, max(0.0, (at - listing.created).total_seconds() / total))
    due = 0
    for i, (start, _) in enumerate(TIERS):
        if f >= start:
            due = i
    return due


# ---- Posting ----
def _validate(org, category, kg, allergens):
    if org.role != "donor":
        raise Err(403, "only donors can post listings")
    if category not in CATEGORIES:
        raise Err(400, "unknown category")
    try:
        kg = round(float(kg), 2)
    except (TypeError, ValueError):
        raise Err(400, f"kg must be a number between {KG_MIN} and {KG_MAX}")
    if not (KG_MIN <= kg <= KG_MAX) or math.isnan(kg):
        raise Err(400, f"kg must be between {KG_MIN} and {KG_MAX}")
    if not isinstance(allergens, list) or not allergens:
        raise Err(400, "allergens must be declared (use 'none' if there are none)")
    if any(a not in ALLERGENS + ["none"] for a in allergens):
        raise Err(400, "unknown allergen")
    if "none" in allergens and len(allergens) > 1:
        raise Err(400, "'none' cannot be combined with other allergens")
    return kg


def pickup_window(category, at, pickup_in_min):
    """expires = now + safe window; pickup_by = min(donor deadline, expires - margin)."""
    expires = at + timedelta(hours=CATEGORIES[category]["safe_hours"])
    donor_deadline = at + timedelta(minutes=pickup_in_min)
    pickup_by = min(donor_deadline, expires - timedelta(minutes=MARGIN_MIN))
    if pickup_by <= at:
        raise Err(400, "pickup time is already past")
    return expires, pickup_by, donor_deadline > pickup_by


def clamp_message(expires, pickup_by):
    fmt = lambda d: timezone.localtime(d).strftime("%I:%M %p").lstrip("0")
    return (f"Safe window ends {fmt(expires - timedelta(minutes=MARGIN_MIN))}, "
            f"so pickup is set to {fmt(pickup_by)}.")


def post(org, category, kg, allergens, pickup_in_min, source="form", at=None):
    """The single writer for Listing. Returns (listing, clamped)."""
    at = at or now()
    kg = _validate(org, category, kg, allergens)
    try:
        pickup_in_min = int(pickup_in_min)
    except (TypeError, ValueError):
        raise Err(400, "pickup_in_min must be a whole number of minutes")
    if pickup_in_min <= 0:
        raise Err(400, "pickup_in_min must be positive")
    expires, pickup_by, clamped = pickup_window(category, at, pickup_in_min)
    with transaction.atomic():
        listing = Listing.objects.create(
            donor=org, category=category, kg=kg, allergens=list(allergens), created=at,
            expires=expires, pickup_by=pickup_by, source=source)
        _event(listing, at, f"Posted {kg:g} kg {CATEGORIES[category]['label']}")
        escalate(listing, at)
    return listing, clamped


# ---- Claim, decline, handoff ----
def _get_listing(listing_id):
    try:
        return Listing.objects.select_related("donor", "receiver", "volunteer").get(pk=listing_id)
    except Listing.DoesNotExist:
        raise Err(404, "listing not found")


def _otp():
    return f"{secrets.randbelow(10 ** 4):04d}"


def claim(org, listing_id, at=None):
    at = at or now()
    if org.role != "receiver":
        raise Err(403, "only receivers can claim")
    listing = _get_listing(listing_id)
    offer = listing.offers.filter(receiver=org, status="pending").first()
    if offer is None:
        raise Err(403, "this listing was not offered to you")
    if at >= listing.pickup_by:
        raise Err(409, "pickup window has closed")
    if free_capacity(org) < listing.kg:
        raise Err(409, "not enough free capacity")
    with transaction.atomic():
        won = Listing.objects.filter(pk=listing.pk, status=POSTED).update(
            status=CLAIMED, receiver=org, claimed_at=at)
        if not won:
            raise Err(409, "already claimed by another receiver")
        listing.refresh_from_db()
        vols = free_volunteers()
        vol = min(vols, key=lambda v: travel_min(v, listing.donor)) if vols else None
        listing.volunteer = vol
        listing.pickup_otp = _otp()
        listing.drop_otp = _otp()
        listing.otp_issued_at = at
        listing.pickup_attempts = listing.drop_attempts = 0
        listing.save()
        offer.status = "accepted"
        offer.save(update_fields=["status"])
        listing.offers.filter(status="pending").exclude(pk=offer.pk).update(status="expired")
        who = f"volunteer {vol.name} assigned" if vol else "no volunteer free; receiver self-collects"
        _event(listing, at, f"Claimed by {org.name}; {who}")
    return listing


def decline(org, listing_id, at=None):
    at = at or now()
    if org.role != "receiver":
        raise Err(403, "only receivers can decline")
    listing = _get_listing(listing_id)
    offer = listing.offers.filter(receiver=org, status="pending").first()
    if offer is None:
        raise Err(404, "no open offer for you on this listing")
    offer.status = "declined"
    offer.save(update_fields=["status"])
    _event(listing, at, f"{org.name} declined")
    if listing.status == POSTED and not listing.offers.filter(status="pending").exists():
        escalate(listing, at)
    return listing


def _collector(listing):
    return listing.volunteer or listing.receiver


def _handoff(org, listing_id, otp, step, at):
    """Shared OTP step. step is 'pickup' or 'drop'. Not wrapped in a transaction, so a
    failed attempt's counter increment is kept."""
    listing = _get_listing(listing_id)
    need_status = CLAIMED if step == "pickup" else COLLECTED
    if listing.status != need_status:
        raise Err(409, f"listing is {listing.status}; this step needs {need_status}")
    collector = _collector(listing)
    if collector is None or org.id != collector.id:
        raise Err(403, "only the assigned collector can do this")
    if at >= listing.expires:
        raise Err(409, "OTP expired: the safe window has closed")
    otp = (otp or "").strip() if isinstance(otp, str) else ""
    if not re.fullmatch(r"\d{4}", otp):
        raise Err(400, "OTP must be 4 digits")
    attr = "pickup_attempts" if step == "pickup" else "drop_attempts"
    code = listing.pickup_otp if step == "pickup" else listing.drop_otp
    attempts = getattr(listing, attr)
    if attempts >= OTP_MAX_ATTEMPTS:
        raise Err(409, "OTP locked after too many wrong attempts")
    if listing.otp_issued_at is not None and at - listing.otp_issued_at > timedelta(minutes=OTP_TTL_MINUTES):
        raise Err(409, f"OTP expired: the code is more than {OTP_TTL_MINUTES} minutes old")
    if not secrets.compare_digest(otp, code):
        attempts += 1
        setattr(listing, attr, attempts)
        listing.save(update_fields=[attr])
        _event(listing, at, f"Wrong {step} OTP attempt ({attempts}/{OTP_MAX_ATTEMPTS})")
        if attempts >= OTP_MAX_ATTEMPTS:
            _event(listing, at, f"{step} OTP locked after {attempts} wrong attempts")
            raise Err(409, "OTP locked after too many wrong attempts")
        raise Err(403, f"wrong OTP ({OTP_MAX_ATTEMPTS - attempts} attempts left)")
    if step == "pickup":
        listing.status = COLLECTED
        listing.collected_at = at
        listing.save(update_fields=["status", "collected_at"])
        _event(listing, at, "Pickup confirmed with OTP")
    else:
        with transaction.atomic():
            listing.status = DELIVERED
            listing.delivered_at = at
            listing.save(update_fields=["status", "delivered_at"])
            if listing.receiver_id:
                Org.objects.filter(pk=listing.receiver_id).update(last_served=at)
            _event(listing, at, "Delivery confirmed with OTP; counted as impact")
    return listing


def collect(org, listing_id, otp, at=None):
    return _handoff(org, listing_id, otp, "pickup", at or now())


def deliver(org, listing_id, otp, at=None):
    return _handoff(org, listing_id, otp, "drop", at or now())


# ---- Clock-driven maintenance ----
def _expire(listing, at):
    listing.status = EXPIRED
    listing.save(update_fields=["status"])
    listing.offers.filter(status="pending").update(status="expired")
    _event(listing, at, f"Expired at pickup-by: {listing.kg:g} kg counted as waste")


def _no_show(listing, at):
    """Claimed but not collected by pickup_by: penalise, reopen if the window allows, else expire."""
    prev = listing.receiver
    listing.offers.filter(receiver=prev).update(status="expired")  # keeps prev excluded
    if prev is not None:
        Org.objects.filter(pk=prev.pk).update(no_shows=prev.no_shows + 1)
        _event(listing, at, f"No-show by {prev.name}; penalty recorded")
    if listing.expires - timedelta(minutes=MARGIN_MIN) > at + timedelta(minutes=HANDLING_MIN):
        listing.status = POSTED
        listing.receiver = None
        listing.volunteer = None
        listing.pickup_otp = listing.drop_otp = ""
        listing.otp_issued_at = None
        listing.pickup_attempts = listing.drop_attempts = 0
        listing.claimed_at = None
        listing.tier = 0
        listing.pickup_by = listing.expires - timedelta(minutes=MARGIN_MIN)
        listing.save()
        _event(listing, at, "Reopened for matching (safe window still open)")
        escalate(listing, at)
    else:
        _expire(listing, at)


def tick(at=None):
    at = at or now()
    with transaction.atomic():
        qs = Listing.objects.select_for_update(skip_locked=True).filter(
            status__in=[POSTED, CLAIMED]).select_related("donor", "receiver", "volunteer").prefetch_related("offers")
        for listing in qs:
            if listing.status == CLAIMED:
                if at >= listing.pickup_by:
                    _no_show(listing, at)
                continue
            if at >= listing.pickup_by:
                _expire(listing, at)
                continue
            behind = listing.tier < due_tier(listing, at)
            pending = any(o.status == "pending" for o in listing.offers.all())
            if behind or not pending:
                escalate(listing, at)


# ---- Views and impact ----
def impact():
    aggregates = Listing.objects.aggregate(
        delivered=Sum(Case(When(status=DELIVERED, then=F("kg")), default=Value(0.0))),
        expired=Sum(Case(When(status=EXPIRED, then=F("kg")), default=Value(0.0))),
    )
    delivered = float(aggregates["delivered"] or 0.0)
    expired = float(aggregates["expired"] or 0.0)
    closed = delivered + expired
    return {
        "delivered_kg": round(delivered, 1),
        "expired_kg": round(expired, 1),
        "rescue_rate": round(delivered / closed, 3) if closed else None,
        "meals": [round(delivered / f) for f in MEALS_PER_KG],  # low, mid, high
        "co2e_kg": [round(delivered * f, 1) for f in CO2E_PER_KG],
        "sponsor_value_rs": round(delivered / MEALS_PER_KG[1]) * RS_PER_MEAL,
        "assumptions": [
            "Only OTP-confirmed deliveries count.",
            "Meals = kg / 0.5 (low), / 0.4 (mid), / 0.3 (high) kg per meal.",
            "CO2e = kg x 1.9 / 2.5 / 3.3; indicative placeholders, cite a source before publishing.",
            f"Sponsor value = mid meals x Rs {RS_PER_MEAL} per meal.",
            "Expired kg is shown openly as waste.",
            "Safe windows (4 h for cooked food, 6 h for dairy sweets and others per category) are illustrative demo defaults, not clinical guidance.",
        ],
    }


def _listing_json(listing, org):
    offers = listing.offers.select_related("receiver")
    if org.role == "receiver":
        offers = offers.filter(receiver=org)
    show_pickup = org.role == "donor" and org.id == listing.donor_id
    show_drop = org.role == "receiver" and org.id == listing.receiver_id
    return {
        "id": listing.id,
        "category": listing.category,
        "label": CATEGORIES[listing.category]["label"],
        "storage": CATEGORIES[listing.category]["storage"],
        "kg": listing.kg,
        "allergens": listing.allergens,
        "created": listing.created.isoformat(),
        "expires": listing.expires.isoformat(),
        "pickup_by": listing.pickup_by.isoformat(),
        "status": listing.status,
        "tier": listing.tier,
        "source": listing.source,
        "donor": {"id": listing.donor_id, "name": listing.donor.name,
                  "lat": round(listing.donor.lat, 2) if listing.donor.lat is not None else None,
                  "lng": round(listing.donor.lng, 2) if listing.donor.lng is not None else None},
        "receiver": ({"id": listing.receiver_id, "name": listing.receiver.name,
                      "lat": round(listing.receiver.lat, 2) if listing.receiver.lat is not None else None,
                      "lng": round(listing.receiver.lng, 2) if listing.receiver.lng is not None else None}
                     if listing.receiver_id else None),
        "volunteer": listing.volunteer.name if listing.volunteer_id else None,
        "pickup_otp": listing.pickup_otp if show_pickup else None,
        "drop_otp": listing.drop_otp if show_drop else None,
        "offers": [{"receiver": o.receiver.name, "receiver_id": o.receiver_id,
                    "score": o.score, "eta": o.eta, "tier": o.tier, "status": o.status,
                    "radius_km": TIERS[o.tier][1] if 0 <= o.tier < len(TIERS) else None,
                    "parts": o.parts} for o in offers],
        "events": [{"at": e.at.isoformat(), "text": e.text}
                   for e in listing.events.all()],
        "disclaimer": DISCLAIMER,
    }


def view(org):
    if org.role == "donor":
        qs = Listing.objects.filter(donor=org)
    elif org.role == "receiver":
        qs = Listing.objects.filter(Q(offers__receiver=org) | Q(receiver=org)).distinct()
    elif org.role == "volunteer":
        qs = Listing.objects.filter(volunteer=org)
    else:  # sponsor: impact only; listing detail is withheld
        qs = Listing.objects.none()
    listings = qs.select_related("donor", "receiver", "volunteer").prefetch_related("offers__receiver", "events").order_by("-created", "-id")[:50]
    return [_listing_json(l, org) for l in listings]


def meta():
    return {
        "categories": {k: {"label": v["label"], "safe_hours": v["safe_hours"],
                           "storage": v["storage"]} for k, v in CATEGORIES.items()},
        "allergens": ALLERGENS + ["none"],
        "tiers": [{"fraction": f, "radius_km": r} for f, r in TIERS],
        "rules": {"speed_kmh": SPEED_KMH, "road_factor": ROAD_FACTOR,
                  "handling_min": HANDLING_MIN, "margin_min": MARGIN_MIN, "k": K,
                  "kg_min": KG_MIN, "kg_max": KG_MAX},
        "disclaimer": DISCLAIMER,
    }


def orgs(viewer=None):
    """Coordinates are coarse (2 dp) unless the viewer is the org itself or a counterparty
    on one of the viewer's claimed/collected/delivered listings."""
    exact = set()
    if viewer is not None:
        exact.add(viewer.id)
        linked = Listing.objects.filter(status__in=[CLAIMED, COLLECTED, DELIVERED]).filter(
            Q(donor=viewer) | Q(receiver=viewer) | Q(volunteer=viewer))
        for ids in linked.values_list("donor_id", "receiver_id", "volunteer_id"):
            exact.update(i for i in ids if i is not None)
    return [{"id": o.id, "role": o.role, "name": o.name,
             "lat": o.lat if o.id in exact else round(o.lat, 2),
             "lng": o.lng if o.id in exact else round(o.lng, 2),
             "capacity": o.capacity, "need": o.need} for o in Org.objects.all()]


# ---- Demo data ----
_SEED_ORGS = [
    (1, "donor", "Wedding Caterer A (sample)", 16.3067, 80.4365, 0, 0),
    (2, "donor", "Function Hall B (sample)", 16.5062, 80.6480, 0, 0),
    (3, "donor", "Caterer C (sample)", 16.2160, 80.6400, 0, 0),
    (4, "donor", "Hostel Mess D (sample)", 16.3500, 80.5500, 0, 0),
    (5, "receiver", "Community Kitchen E (sample)", 16.3100, 80.4500, 60, 0.8),
    (6, "receiver", "Shelter F (sample)", 16.3000, 80.4300, 40, 0.9),
    (7, "receiver", "NGO G (sample)", 16.5100, 80.6300, 80, 0.6),
    (8, "receiver", "NGO H (sample)", 16.2200, 80.6500, 100, 0.5),
    (9, "receiver", "Kitchen I (sample)", 16.3600, 80.5300, 50, 0.7),
    (10, "receiver", "Night Shelter J (sample)", 16.2900, 80.4700, 40, 0.9),
    (11, "volunteer", "Volunteer K (sample)", 16.3050, 80.4400, 0, 0),
    (12, "volunteer", "Volunteer L (sample)", 16.5000, 80.6400, 0, 0),
    (13, "volunteer", "Volunteer M (sample)", 16.2200, 80.6400, 0, 0),
    (14, "volunteer", "Volunteer N (sample)", 16.3500, 80.5400, 0, 0),
    (15, "sponsor", "City CSR Sponsor (sample)", 16.3, 80.5, 0, 0),
]


def reset_demo():
    Org.objects.all().delete()  # cascades to listings, offers, events, drafts
    Org.objects.bulk_create([
        Org(id=i, role=r, name=n, lat=la, lng=lo, capacity=c, need=nd)
        for i, r, n, la, lo, c, nd in _SEED_ORGS
    ])
    reset_clock()
    return orgs()


def run_scenario(scale=1.0):
    """Pitch story: reset, real-time clock (or requested scale), 60 kg biryani posted by Function Hall B."""
    reset_demo()
    set_scale(scale)
    donor = Org.objects.get(pk=2)
    listing, _ = post(donor, "cooked_rice", 60, ["none"], 90, source="form")
    return listing.id
