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
- [ ] LLM intake module and stub class, with CONFIDENCE_MIN threshold
- [ ] Confirmation card shows the clamp message before confirm
- [ ] Chat-bubble conversation view in UI
- [ ] Impact strip rendered in UI
- [ ] Assumptions drawer (collapsible)
- [ ] Sponsor view panel
- [ ] OTP expiry
- [ ] Rate limiting on public endpoints
- [ ] Coordinate coarsening in API responses
- [ ] Clock-speed selector in UI
- [ ] Repeat-last control
- [ ] Raw-text retention purge for drafts
- [ ] HTTP-level tests (flow, 401/403/400/404) and PRD-named full-flow tests
- [ ] EVAL.md evaluation harness
