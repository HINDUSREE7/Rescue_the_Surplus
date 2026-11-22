import json
import time
from collections import deque
from pathlib import Path

from django.conf import settings
from django.db import OperationalError, close_old_connections
from django.db.models import Count, Max
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse

from . import engine, parser
from .engine import Err
from .models import Event, Listing, Offer, Org


def _org(request):
    raw = request.headers.get("X-Org")
    if not raw:
        raise Err(401, "missing X-Org header")
    try:
        return Org.objects.get(pk=int(raw))
    except (ValueError, Org.DoesNotExist):
        raise Err(401, "unknown X-Org")


def _optional_org(request):
    """Org from X-Org if present and valid, else None. Never raises."""
    raw = request.headers.get("X-Org")
    if not raw:
        return None
    try:
        return Org.objects.get(pk=int(raw))
    except (ValueError, Org.DoesNotExist):
        return None


_RATE_HITS = {}
RATE_MAX = 30
RATE_WINDOW_S = 60


def _rate_ok(key):
    """Sliding-window limiter per key (org id). Returns False when the key is over budget."""
    now = time.monotonic()
    hits = _RATE_HITS.setdefault(key, deque())
    while hits and now - hits[0] > RATE_WINDOW_S:
        hits.popleft()
    if len(hits) >= RATE_MAX:
        return False
    hits.append(now)
    return True


def _body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except ValueError:
        raise Err(400, "body must be JSON")
    if not isinstance(data, dict):
        raise Err(400, "body must be a JSON object")
    return data


def endpoint(method, auth=True, limited=False):
    """Route wrapper: method check, X-Org auth, optional rate limit, and {"error": ...} mapping for Err."""
    def wrap(fn):
        def view(request, *args, **kwargs):
            if request.method != method:
                return JsonResponse({"error": "method not allowed"}, status=405)
            try:
                org = _org(request) if auth else None
                if limited and org is not None and not _rate_ok(org.id):
                    return JsonResponse({"error": "rate limit exceeded; try again in a minute"},
                                        status=429)
                out = fn(request, org, *args, **kwargs)
                if isinstance(out, HttpResponse):
                    return out
                return JsonResponse(out, safe=False)
            except Err as e:
                return JsonResponse({"error": e.msg}, status=e.status)
        view.__name__ = fn.__name__
        return view
    return wrap


def _listing(listing, org):
    return engine._listing_json(listing, org)


# ---- GET ----
@endpoint("GET", auth=False)
def meta(request, org):
    return engine.meta()


@endpoint("GET", auth=False)
def orgs(request, org):
    return engine.orgs(viewer=_optional_org(request))


@endpoint("GET", auth=False)
def impact(request, org):
    return engine.impact()


@endpoint("GET")
def view(request, org):
    engine.tick()
    resp = JsonResponse(engine.view(org), safe=False)
    resp["X-Sim-Now"] = engine.now().isoformat()
    return resp


def _signature():
    ev = Event.objects.aggregate(m=Max("id"))["m"]
    lst = Listing.objects.aggregate(m=Max("id"), c=Count("id"))
    off = Offer.objects.aggregate(m=Max("id"))["m"]
    return f"{ev}:{lst['m']}:{lst['c']}:{off}"


def stream(request):
    """SSE change signal. Clients refetch /api/view on each 'change' event; the loop also ticks."""
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    def gen():
        last = None
        while True:
            try:
                sig = _signature()
            except OperationalError:
                close_old_connections()
                yield ": keep-alive\n\n"
                time.sleep(1)
                continue
            if sig != last:
                last = sig
                yield f"event: change\ndata: {json.dumps({'v': sig})}\n\n"
            else:
                yield ": keep-alive\n\n"
            time.sleep(1)

    resp = StreamingHttpResponse(gen(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    return resp


def index(request):
    path = Path(settings.BASE_DIR) / "public" / "index.html"
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


# ---- Form path ----
@endpoint("POST", limited=True)
def create_listing(request, org):
    b = _body(request)
    listing, clamped = engine.post(org, b.get("category"), b.get("kg"), b.get("allergens"),
                                   b.get("pickupInMin"), source="form")
    out = _listing(listing, org)
    out["clamped"] = clamped
    out["clamp_message"] = engine.clamp_message(listing.expires, listing.pickup_by) if clamped else ""
    return out


@endpoint("GET")
def last_listing(request, org):
    """Repeat-last prefill: the calling donor's most recent listing only."""
    if org.role != "donor":
        raise Err(403, "only donors can repeat a listing")
    last = Listing.objects.filter(donor=org).order_by("-created", "-id").first()
    if last is None:
        raise Err(404, "no previous listing")
    minutes = round((last.pickup_by - last.created).total_seconds() / 60)
    return {"category": last.category, "kg": last.kg, "minutes": minutes,
            "allergens": last.allergens}



# ---- Intake (chat / voice) ----
def _draft_resp(draft):
    return parser.draft_json(draft)


@endpoint("POST", limited=True)
def ingest(request, org):
    b = _body(request)
    channel = b.get("channel") if b.get("channel") in ("chat", "voice") else "chat"
    return _draft_resp(parser.ingest(org, b.get("text"), channel=channel))


@endpoint("POST", limited=True)
def ingest_answer(request, org):
    b = _body(request)
    return _draft_resp(parser.answer(org, b.get("draft_id"), b.get("text")))


@endpoint("POST", limited=True)
def ingest_confirm(request, org):
    b = _body(request)
    listing, msg = parser.confirm(org, b.get("draft_id"), b.get("edits"),
                                  idempotency_key=str(b.get("idempotency_key") or ""))
    out = _listing(listing, org)
    out["clamp_message"] = msg
    return out


@endpoint("POST", limited=True)
def ingest_cancel(request, org):
    b = _body(request)
    return parser.cancel(org, b.get("draft_id"))


# ---- Dispatch ----
@endpoint("POST", limited=True)
def claim(request, org, listing_id):
    return _listing(engine.claim(org, listing_id), org)


@endpoint("POST", limited=True)
def decline(request, org, listing_id):
    return _listing(engine.decline(org, listing_id), org)


@endpoint("POST", limited=True)
def collect(request, org, listing_id):
    return _listing(engine.collect(org, listing_id, _body(request).get("otp")), org)


@endpoint("POST", limited=True)
def deliver(request, org, listing_id):
    return _listing(engine.deliver(org, listing_id, _body(request).get("otp")), org)


# ---- Demo ----
@endpoint("POST", auth=False)
def demo_reset(request, org):
    return engine.reset_demo()


@endpoint("POST", auth=False)
def demo_speed(request, org):
    b = _body(request)
    try:
        scale = float(b.get("scale", 1))
    except (TypeError, ValueError):
        raise Err(400, "scale must be a number")
    return {"scale": engine.set_scale(scale)}


@endpoint("POST", auth=False)
def demo_scenario(request, org):
    b = _body(request)
    try:
        scale = float(b.get("scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    return {"listing_id": engine.run_scenario(scale=scale)}
