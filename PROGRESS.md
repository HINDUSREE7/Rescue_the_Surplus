# PROGRESS: Rescue the Surplus
Only genuinely unfinished work is unchecked.

- [x] Django project scaffold, SQLite, core app
- [x] Data model: Org, Listing, Offer, Event, Draft; migrations 0001 and 0002
- [x] Spoilage clock, feasibility filters, ranked matching (engine.py)
- [x] Post state machine and single write path (engine.post)
- [x] Rule-based Telugu/English/mixed intake parser; allergen always asked
- [x] Intake endpoints ingest/answer/confirm/cancel with idempotent confirm
- [x] Draft TTL and org ownership checks
- [x] No-show reopen; OTP 4 digits with 5-attempt limit
- [x] Impact computed from OTP-confirmed deliveries
- [x] SSE stream and REST endpoints
- [x] Single-page UI: role switcher, text/voice intake, allergen chips, confidence labels, live list, timeline, map
- [x] Demo reset and seed data
- [x] 15 named unit tests passing
- [x] LLM intake module and stub class, with CONFIDENCE_MIN threshold
- [x] Confirmation card shows the clamp message before confirm
- [x] Chat-bubble conversation view in UI
- [x] Impact strip rendered in UI
- [x] Assumptions drawer (collapsible)
- [x] Sponsor view panel
- [x] OTP expiry
- [x] Rate limiting on public endpoints
- [x] Coordinate coarsening in API responses
- [x] Clock-speed selector in UI
- [x] Repeat-last control
- [x] Raw-text retention purge for drafts
- [x] HTTP-level tests (flow, 401/403/400/404) and PRD-named full-flow tests
- [x] EVAL.md evaluation harness
