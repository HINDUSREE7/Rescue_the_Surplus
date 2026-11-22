# Rescue the Surplus — Product Requirements Document

**Codebenders ACE Builders' Hackathon 2026 · Problem Statement 2 (Society & Environment)**
**Stack:** Django 5 · Postgres/PostGIS (SQLite for demo) · Celery beat · SSE/Channels · Leaflet
**Status of this repo:** working prototype, 9 passing tests, synthetic data only.

---

## 1. One-line pitch

A **spoilage-clock dispatch system**: every listing carries a safe-to-eat deadline, and the platform only offers it to receivers who can physically arrive inside that deadline, widening the search automatically if nobody claims it.

Most entries will be a post-and-claim board. The differentiator is that **time is the first-class constraint**, not an afterthought, and that every match is explainable.

## 2. Scope (the problem statement says "pick one city and one donor type")

| Choice | Decision | Why |
|---|---|---|
| City | Guntur–Vijayawada corridor, Andhra Pradesh | Dense event/wedding economy, short distances (3–25 km), local to the team |
| Donor | Wedding caterers and function halls (secondary: hostel messes) | Large, predictable, time-critical surplus; one decision-maker per event |
| Receivers | NGOs, community kitchens, shelters | Have fixed addresses and known capacity |
| Volunteers | Small verified pool doing last-mile | Decouples donor pickup from receiver vehicles |

**Non-goals (v1):** payments, tax receipts, food-safety certification, retail/FMCG surplus, multi-city routing, native apps.

## 3. Users and jobs-to-be-done

- **Donor (caterer/hall manager, busy, phone-first):** "Tell someone to take this food in under a minute, and don't make me chase them."
- **Receiver (NGO coordinator):** "Only show me food I can actually collect and serve safely, sized to what I can take."
- **Volunteer:** "Give me one clear pickup, with the OTP and the address, and a deadline."
- **Sponsor (CSR lead / city authority):** "Show me verified meals and the assumptions behind them."

## 4. Requirement traceability (problem statement → product)

| Statement requirement | Implementation | How it is verified |
|---|---|---|
| Donor flow under a minute | Category chips (pre-filled kg), quantity slider, pickup-within slider, one-tap **Repeat last** | Manual timing; `ApiTests.test_http_flow` |
| Smart matching by distance, quantity, timing, need | `engine.rank()`: feasibility filters + urgency-weighted score (§7) | `test_post_creates_ranked_offers_inside_spoilage_window` |
| Live status posted → claimed → collected → delivered | State machine + OTP at each handoff + event timeline + SSE push | `test_full_flow_with_otps_and_impact` |
| Impact view with assumptions | `engine.impact()` returns ranges and an assumptions list rendered in the UI | `test_full_flow…` (meals 120/150/200 for 60 kg) |
| Handling and safety info per listing | Safety card on every listing: window, storage, allergens, disclaimer | Visible in `card()` in the UI |
| Guardrail: don't certify safety | Disclaimer on every card; no safety claims anywhere | Review |
| Guardrail: no tax/legal promises | None made; business model avoids tax language | Review |
| Guardrail: synthetic data only | `seed.py` uses fictional "(sample)" orgs at approximate coordinates | Review |
| Business case | §14 | — |

## 5. Core workflows

### 5.1 Post and match
```
Donor ── POST /api/listings {category, kg, pickupInMin, allergens}
  └─ validate → expires = now + category safe window
              → pickup_by = min(donor deadline, expires − 30 min serving margin)
  └─ escalate(tier 0): rank receivers within 3 km → top 3 get an Offer (with score breakdown)
  └─ SSE ping → receivers' screens update
```

### 5.2 Escalation (the spoilage clock)
```
every 2–10 s (tick):
  elapsed = (now − created) / (pickup_by − created)
  due tier = last tier whose start ≤ elapsed        tiers: 0% r=3 km · 25% r=6 · 50% r=12 · 70% r=25
  if no open offer, or tier is behind schedule → widen radius, offer to next 3 not yet offered
  if now ≥ pickup_by → EXPIRED (counted openly as waste)
Receiver declines all open offers → escalate immediately (no waiting for the timer).
```

### 5.3 Claim and pickup
```
Receiver ── claim ──► atomic UPDATE … WHERE status='posted'  (loser gets 409)
   └─ other offers → expired; nearest free volunteer assigned (else receiver self-collects)
   └─ two OTPs generated: pickup_otp (shown to donor), drop_otp (shown to receiver)
Collector enters pickup_otp  → COLLECTED
Collector enters drop_otp    → DELIVERED → receiver.last_served = now → impact counters update
```

### 5.4 State machine
`POSTED → CLAIMED → COLLECTED → DELIVERED`, with `POSTED → EXPIRED` as the only other exit. Only OTP-confirmed `DELIVERED` counts toward impact.

## 6. Architecture

```
 Browser (donor / NGO / volunteer / sponsor views; Leaflet map)
    │  JSON over HTTPS            ▲ SSE (change signal → client refetches)
    ▼                             │
 ┌─────────────── Django (ASGI/WSGI, gunicorn) ───────────────┐
 │ core/views.py   thin JSON endpoints, uniform error shape     │
 │ core/engine.py  matching, escalation, state machine, impact  │  ← all business logic, no HTTP
 │ core/rules.py   every tunable constant (surfaced in the UI)  │
 │ core/models.py  Org · Listing · Offer · Event                │
 │ admin           ops console: verify NGOs, moderate listings  │
 └───────────────┬──────────────────────────┬──────────────────┘
                 │ ORM                       │ tick() every 5–10 s
        Postgres (+PostGIS)            Celery beat → worker  (dev: in-process thread)
                 │                           │
              Redis (pub/sub for SSE/Channels, rate limits, cache)
```

**Design decisions**
- **Logic lives in `engine.py` as plain functions** over the ORM, so it is unit-testable without HTTP and portable.
- **The UI refetches on a change signal** instead of diffing streamed state: far less code and no stale-state bugs.
- **One `Org` table keyed by role** keeps v1 small; split into profiles when roles diverge.
- **Explainability is stored, not recomputed:** each `Offer.parts` keeps `{components, weights}` as they were at offer time.

### Data model
| Table | Key fields |
|---|---|
| `Org` | role, name, lat, lng, capacity (kg now), need (0–1), last_served |
| `Listing` | donor, category, kg, allergens, created, expires (safe window end), pickup_by, status (indexed), tier, receiver, volunteer, pickup_otp, drop_otp, timestamps |
| `Offer` | listing, receiver, score, parts (JSON), eta, tier, status; unique (listing, receiver) |
| `Event` | listing, at, text (the timeline) |

## 7. Matching algorithm

**Step 1 — hard feasibility filters** (a receiver failing any is never shown):
1. `free_capacity ≥ kg` (capacity minus kg already claimed/collected)
2. `distance ≤ tier radius`
3. `ETA ≤ remaining_safe_window − 30 min`, where `ETA = 10 min handling + volunteer lead time + travel(donor→receiver)`
4. A collector can reach the donor before the donor's `pickup_by`

Travel time = Haversine km × 1.3 road factor ÷ 25 km/h (all in `rules.py`).

**Step 2 — score** (higher is better), four components each in 0..1:

| Component | Definition | Rationale |
|---|---|---|
| Proximity | `1 − ETA / (remaining − margin)` | Spare time left inside the window |
| Quantity fit | `kg / free_capacity` | Right-size: don't send 20 kg to a 100 kg kitchen if a better fit exists |
| Need | Receiver's declared need | Prioritises where it matters |
| Fairness | `min(1, hours_since_last_served / 48)` | One NGO can't hog every listing |

**Weights shift with urgency** `u = 1 − remaining / safe_window`:
`proximity = 0.30 + 0.20u · quantity = 0.20 · need = 0.30 − 0.10u · fairness = 0.20 − 0.10u` (always sums to 1).
As the clock runs down, speed matters more than fairness.

**Step 3 — offer top K=3**, widening by tier. Offers are broadcast to a few receivers so a single slow responder cannot stall the listing; first valid claim wins.

**Complexity:** O(R) per tier with R = receivers in the city (hundreds), plus one aggregate query for capacity. At city scale replace the Python loop with PostGIS `ST_DWithin` on a GiST index and keep the scoring in Python over the shortlisted rows (§13).

**Correctness:** claim is one conditional `UPDATE … WHERE status='posted'`; two simultaneous claims → exactly one row updated. Ticker uses `select_for_update(skip_locked=True)` so multiple workers never double-escalate.

## 8. API

Auth in the prototype is the `X-Org` header (demo only; see §11). All responses are JSON; errors are `{"error": "..."}` with 400/401/403/404/409.

| Method & path | Who | Purpose |
|---|---|---|
| `GET /api/meta` · `/api/orgs` | all | Categories, tiers, assumptions; organisations for the map |
| `GET /api/view` | all | Role-scoped listings with offers, events, OTPs the caller may see |
| `POST /api/listings` | donor | `{category, kg, pickupInMin, allergens[]}` → creates and starts matching |
| `POST /api/listings/{id}/claim` · `/decline` | receiver | First valid claim wins |
| `POST /api/listings/{id}/collect` · `/deliver` | assigned collector | `{otp}` |
| `GET /api/impact` | all | Delivered/expired kg, meals and CO₂e ranges, assumptions, sponsor value |
| `GET /api/stream` | all | SSE change signal |
| `POST /api/demo/{reset,speed,scenario}` | demo | Reset data, compress the clock, run the pitch story |

## 9. Impact methodology (be conservative; judges will probe this)

- Counts **only OTP-confirmed deliveries**. Posted/claimed food is not impact.
- **Meals = kg ÷ kg-per-meal**, shown as a range (0.5 / 0.4 / 0.3 kg per meal → low / mid / high). Headline uses mid.
- **CO₂e avoided = kg × factor**, shown as a range (1.9 / 2.5 / 3.3 kg CO₂e per kg). These are *indicative placeholder factors*: replace with a cited factor (and name the source in the UI) before publishing any claim.
- **Expired kg and rescue rate are shown**, so the number is not inflated.
- Every figure has its assumption one click away ("Assumptions behind every number").

## 10. Safety and compliance guardrails

- The platform **connects people and does not certify food safety**. This sentence is on every listing card.
- Each category has a **safe window and storage instruction** (`rules.CATEGORIES`). The values are conservative defaults for the demo; **validate against FSSAI guidance and a local food-safety officer before real use**.
- Allergens are declared by the donor from a fixed list; the card shows "none declared — ask donor" rather than implying "allergen-free".
- No tax, deduction or legal-benefit language anywhere in product or pitch.
- Synthetic data only; no real addresses or personal details. Real deployment needs a data-protection review (India's DPDP Act) before any real organisation is onboarded.

## 11. Security and privacy

| Prototype | Production requirement |
|---|---|
| `X-Org` header identifies the caller | Phone-number OTP login (Django sessions or JWT), role stored server-side, per-role permissions |
| CSRF-exempt JSON endpoints | Re-enable CSRF for session auth, or use token auth with strict CORS |
| OTPs are 4-digit | Add attempt limits (e.g. 5 tries) and expiry; log failures |
| Open rate | Rate-limit by IP and org (Redis); idempotency key on `POST /listings` |
| Exact coordinates shown | Show donors/receivers to each other only after a claim; store coordinates at neighbourhood precision in public views |
| Admin | Staff-only, 2FA, audit log |

## 12. Non-functional requirements

- Post → first offers visible: **< 2 s** (p95).
- Escalation latency: ≤ tick interval (5–10 s) after a tier becomes due.
- Concurrency: exactly-once claim under simultaneous requests (covered by test).
- Availability target for pilot: 99% (single region, managed Postgres, health check on `/api/meta`).
- Works on a low-end phone over 4G: no front-end build, one HTML file, map tiles are the only heavy asset.

## 13. Scale path (what changes at 10× and 100×)

| Pressure | Change |
|---|---|
| Radius queries slow | PostgreSQL + PostGIS, `geography(Point)` columns with GiST index; `ST_DWithin` shortlist, then score in Python |
| Many SSE clients | Django Channels + Redis channel layer (or a pub/sub fan-out); clients still refetch on signal |
| Ticker in a web process | Celery beat every 5–10 s calling `engine.tick()`; `skip_locked` already makes it multi-worker safe |
| Offer fan-out and notifications | Celery tasks for WhatsApp/SMS/push; retries with backoff |
| Hot reads (`/view`, `/impact`) | Redis cache with short TTL, invalidated on mutation; materialised daily impact table |
| Table growth | Partition `Event` and old `Listing` by month; archive delivered rows |
| Multi-city | `city` foreign key on Org and Listing; per-city tier radii and safe-window overrides in config tables |
| Observability | Structured logs, metrics on time-to-claim, expiry rate, escalation depth; Sentry |

## 14. Business case

**Who pays**
1. **Donors:** free core. Paid tier ₹999–2,999/month for waste/ESG reports and recurring-event automation (templates, auto-post from event calendar). No tax claims.
2. **CSR sponsors:** pay per **verified meal rescued** (₹3–5/meal) with a branded live impact dashboard.
3. **City/municipal bodies:** waste-diversion heatmaps and reporting licence.

**Illustrative unit economics** (assumptions to be validated in the pilot, not forecasts)

| Line | Calculation | ₹ / month |
|---|---|---|
| Food rescued | 20 caterers × 4 events × 50 kg | 4,000 kg |
| Meals (mid) | 4,000 ÷ 0.4 | 10,000 |
| Sponsor revenue | 10,000 × ₹4 | 40,000 |
| Donor subscriptions | 30% of 20 = 6 × ₹1,999 | ~12,000 |
| **Revenue** | | **~52,000** |
| Volunteer fuel stipend | 80 pickups × ₹150 | 12,000 |
| Infra and messaging | | 5,000 |
| Part-time coordinator | | 15,000 |
| **Cost** | | **~32,000** |
| **Cost per meal rescued** | 32,000 ÷ 10,000 | **~₹3.2** (below the ₹4 sponsor price) |

**Why a busy caterer returns every week:** auto-fill from last event, a one-tap post, a 60-second job, and a monthly waste report they can show clients. Surplus recurs with every event, so the habit forms around the event calendar.

## 15. KPIs

Time-to-claim (median, p90) · % listings claimed before expiry (rescue rate) · kg and meals delivered · offers per listing before claim (match quality) · donor weekly retention · receiver acceptance rate · volunteer pickup on-time rate · cost per meal.

## 16. Demo script (3 minutes)

1. **Story (20 s):** "11:40 pm, a wedding in Guntur has 60 kg of biryani, and the safe window is 4 hours."
2. **Post (30 s):** press **▶ Pitch scenario** (reset, 120× clock, 60 kg posted as Function Hall B). Show the spoilage bar and the safety card.
3. **Explainable match (30 s):** open the offers list; show the four-colour score bar and ETA for each receiver.
4. **Escalation (40 s):** switch to the offered NGO and press **Decline**; switch back and show the wider tier and new receivers. Then let the clock run to show the timed widening.
5. **Pickup (40 s):** another NGO claims; volunteer auto-assigned; show both OTPs; confirm pickup and delivery as volunteer.
6. **Impact and business (20 s):** impact strip ticks up with ranges; open the assumptions; show the sponsor view and the unit-economics slide.

## 17. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Food-safety liability | Disclaimer, time limits, storage guidance, donor allergen declaration; platform never certifies; partner with an NGO that has a food-safety process |
| Volunteer no-show after claim | v1.1: if not collected by `pickup_by`, reopen the listing and re-offer; reliability score for volunteers |
| Receivers over-claim / hoard | Capacity check, fairness term, claim-then-no-show penalty |
| Donor fatigue | Templates, repeat-last, recurring events, WhatsApp entry |
| Inflated impact claims | Ranges, OTP-only counting, expired kg shown, sourced factors |
| Data privacy | Synthetic data now; DPDP review and coordinate coarsening before launch |

## 18. Known limitations and roadmap

**Not in this prototype (be upfront with judges):** delivery photo proof (OTP only for now), splitting one listing across several receivers, volunteer no-show re-assignment, real phone-OTP auth, notifications (WhatsApp/SMS), multi-city, PostGIS (uses Haversine), and the simulated clock is per-process (demo only).
**v1.1:** reassignment on no-show, delivery photo to object storage, WhatsApp/voice posting, partial claims. **v2:** demand forecasting from event calendars, route batching for volunteers, sponsor billing.

## 19. Repository layout and run

```
manage.py · requirements.txt · README.md · PRD.md
rescue/    settings.py urls.py wsgi.py
core/      models.py engine.py rules.py clock.py seed.py bus.py views.py urls.py admin.py apps.py tests.py
           management/commands/seed.py
public/    index.html   (UI: Leaflet map, role switcher, spoilage bars, score bars, impact strip)
```
```bash
pip install -r requirements.txt
python manage.py migrate && python manage.py seed
SCALE=60 python manage.py runserver
python manage.py test
```

---

## 20. Build-from-scratch prompt (paste into an AI coding assistant, one phase at a time)

> **Role:** You are a senior Django engineer. Build "Rescue the Surplus", a surplus-food dispatch platform, as a Django 5 project with **only Django as a dependency**. Keep the code minimal: no DRF, no front-end build step, no helper layers that a few lines can replace. Put all business logic in `core/engine.py` (plain functions over the ORM, no HTTP) and all tunable numbers in `core/rules.py`. After each phase, run the stated check and fix before continuing. Use synthetic data only.

**Phase 0 — Project.** `django-admin startproject rescue .`, `startapp core`, add `core` to `INSTALLED_APPS`, set `TIME_ZONE='Asia/Kolkata'`, `USE_TZ=True`. Read DB from env: Postgres when `POSTGRES_DB` is set, else SQLite.
*Check:* `python manage.py check` passes.

**Phase 1 — Rules.** `core/rules.py` with: speed 25 km/h, road factor 1.3, handling 10 min, serving margin 30 min, K=3, TIERS `[(0,3),(.25,6),(.5,12),(.7,25)]` as (fraction of pickup window, radius km), meals per kg `(.5,.4,.3)`, CO₂e per kg `(1.9,2.5,3.3)` marked indicative, ₹/meal 4, allergen list, and `CATEGORIES` (label, safe hours, default kg, storage text) for cooked rice 4 h, curry/dal 4 h, sweets/dairy 6 h, bakery 24 h, produce 48 h, packaged 72 h.
*Check:* import works; a comment states windows are illustrative and need food-safety validation.

**Phase 2 — Models.** `Org(role, name, lat, lng, capacity, need, last_served)`; `Listing(donor, category, kg, allergens, created, expires, pickup_by, status[posted|claimed|collected|delivered|expired] indexed, tier=-1, receiver, volunteer, pickup_otp, drop_otp, claimed_at, collected_at, delivered_at)` with `related_name` `received`/`assigned`; `Offer(listing, receiver, score, parts JSON, eta, tier, status[pending|accepted|declined|expired])` with a unique (listing, receiver) constraint; `Event(listing, at, text)` ordered by time. Register all in admin with useful `list_display`.
*Check:* `makemigrations` and `migrate` succeed.

**Phase 3 — Seed and clock.** `seed.reset()` deletes listings and orgs and bulk-creates 4 donors (ids 1–4), 6 NGOs (5–10, capacities 40–100 kg, need 0.5–0.9), 4 volunteers (11–14), 1 sponsor (15) with **explicit ids**, fictional "(sample)" names, approximate Guntur coordinates. `clock.py` provides `now()`, `set_scale()`, `skip()`, `reset()` with a simulated-time multiplier from env `SCALE`. Add `manage.py seed`.
*Check:* `python manage.py seed` prints success.

**Phase 4 — Engine.** Implement in `core/engine.py`:
1. `km()` Haversine and `travel()` minutes.
2. `receivers()` annotated with `free = capacity − Σ kg of claimed/collected listings`; `free_volunteers()` excluding those with live assignments.
3. `rank(listing, donor, now, radius)`: apply the four hard filters in §7, compute the four components, urgency-shifted weights summing to 1, return candidates sorted by score with components and weights.
4. `escalate(listing, now)`: widen one tier at a time, offer the top K not already offered, log an `Event`, stop when any offer is pending.
5. `tick()`: inside `transaction.atomic` using `select_for_update(skip_locked=True)`, expire listings at `pickup_by`, otherwise escalate when the elapsed fraction passes the next tier or no offer is open.
6. `post()` validating role, category, kg 1–500, allergens whitelist; `expires = now + safe hours`; `pickup_by = min(donor wait, expires − margin)`.
7. `claim` using a single conditional `UPDATE … WHERE status='posted'`; expire other offers; assign the nearest free volunteer; generate two 4-digit OTPs with `secrets`.
8. `decline` (escalate immediately if no pending offers remain), and `collect`/`deliver` via one shared OTP-checked step function restricted to the assigned collector (volunteer, else receiver).
9. `view(org_id)` role-scoped listings with offers, events and OTPs visible only to the correct role; `impact()` returning delivered/expired kg, meals and CO₂e ranges, rescue rate, sponsor value and an assumptions list.
*Check:* write `core/tests.py` covering ranked offers inside the window, decline-all escalation, timed escalation, single-winner claim, full OTP flow with impact 120/150/200 meals for 60 kg, expiry counted as waste, role/capacity guards, and role-scoped visibility. `python manage.py test` is green.

**Phase 5 — HTTP.** `core/views.py` with one `endpoint(method)` decorator (parses the `X-Org` header and JSON body, maps `engine.Err` to its status, pings an SSE bus on POST) and one-line views for the routes in §8. `/api/stream` is a `StreamingHttpResponse` that waits on a `threading.Condition` and sends keepalives. `/` serves `public/index.html`.
*Check:* add an API test for post → view, a 403 for a non-donor post, and a 401 without a header.

**Phase 6 — Ticker.** In `apps.py`, start a daemon thread that calls `engine.tick()` every 2 s and pings the bus, only when serving via `runserver`. Document that production uses Celery beat.
*Check:* run with `SCALE=120`, post a listing, see the tier increase with no claims.

**Phase 7 — UI.** One `public/index.html`, vanilla JS, Leaflet from a CDN. Header with role/organisation switcher, clock-speed selector, **Pitch scenario** and **Reset** buttons. Donor panel: category chips that prefill quantity, quantity slider, pickup-within slider, allergen checkboxes, **Post & match**, **Repeat last**. Listing cards with a status stepper, a spoilage countdown bar (green → amber under 50% → red under 25%), a safety card with the non-certification line, a four-segment score bar per offer with ETA and tier, OTP displays, claim/decline and OTP-entry buttons, and a timeline. Map with role-coloured markers and dashed lines for active deliveries. Impact strip with ranges and an assumptions drawer. Refetch on each SSE message. Escape all user-supplied text.
*Check:* run the pitch scenario end to end in a browser.

**Phase 8 — Hardening for real use.** Replace header auth with phone-OTP sessions, re-enable CSRF, add OTP attempt limits, rate limits, idempotency keys, coordinate coarsening, structured logging.

**Phase 9 — Scale.** Move to Postgres/PostGIS with a GiST index and `ST_DWithin` shortlist; Celery beat for `tick()`; Channels + Redis for live updates; caches for `/view` and `/impact`.

**Phase 10 — Pitch assets.** Slide with the §14 unit-economics table, the §16 demo script rehearsed twice, and a limitations slide listing §18 honestly.

**Definition of done:** `python manage.py test` green; the pitch scenario runs start to finish; the impact numbers match the assumptions drawer; no real addresses or personal data anywhere in the repo.
