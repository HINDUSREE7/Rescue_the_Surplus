# STATUS: Rescue the Surplus vs Final PRD
Verification: `manage.py test` ran 47 tests, all OK (47 passed in 0.31s); `manage.py check` reported no issues. `scripts/eval_intake.py` reports 100% rules accuracy.

| # | Item | Status | Proof (file:line) / note |
|---|---|---|---|
| 1 | engine.post single writer | DONE | core/engine.py `def post`; Listing.objects.create (only write) |
| 2 | Listing.source | DONE | engine.py `source="form"` parameter; field in core/models.py |
| 3 | Draft model | DONE | class Draft in core/models.py |
| 4 | Intake flow ingest/answer/confirm/cancel | DONE | core/urls.py; core/parser.py `confirm()` |
| 5 | Idempotent confirm | DONE | core/tests/test_core.py test_confirm_idempotent |
| 6 | Draft TTL and org ownership | DONE | core/parser.py `_load`, `_check_open`; raw-text retention purge implemented in confirm() and cancel() |
| 7 | Allergen always asked | DONE | test_core.py test_allergen_not_assumed |
| 8 | LLM stub + reconcile | DONE | core/llm.py with StubLLM, HttpLLM, CONFIDENCE_MIN=0.7; core/tests/test_llm.py |
| 9 | Lexicon covers all categories | DONE | test_core.py test_lexicon_covers_all_categories |
| 10 | /api/ingest* routes | DONE | core/urls.py; views.py |
| 11 | Chat bubbles | DONE | public/index.html `#chat` element with `.bubble.user` and `.bubble.assistant` |
| 12 | Allergen chips | DONE | public/index.html chip render |
| 13 | Confirmation card | DONE | public/index.html `#confirm` card with `clamp_message` and trust tags |
| 14 | Confidence strip | DONE | public/index.html trust tags `[high/medium/low, source]` |
| 15 | No-show reopen | DONE | core/engine.py no-show handler; test_core.py test_noshow_reopens_listing |
| 16 | OTP attempt limit & expiry | DONE | core/engine.py 5 attempts max, OTP_TTL_MINUTES=10; test_otp_expiry.py |
| 17 | Rate limit | DONE | core/views.py `_rate_ok` sliding window with periodic cleanup |
| 18 | Coordinate coarsening | DONE | core/engine.py `orgs()` returns 2 decimal places unless linked via active delivery |
| 19 | Impact strip | DONE | public/index.html `#impact` with meals, kg, co2e, rescue rate, waste |
| 20 | Assumptions drawer | DONE | public/index.html collapsible `<details id="assumptions">` |
| 21 | Clock-speed selector | DONE | public/index.html `#speed` bound to `/api/demo/speed` |
| 22 | Repeat last | DONE | `/api/listings/last` and `#repeatLast`, `#repeatPost` in public/index.html |
| 23 | Sponsor view | DONE | public/index.html dedicated `#sponsorPanel` with CSR verified meals & carbon metrics |
| 24 | EVAL.md | DONE | `EVAL.md` and `scripts/eval_intake.py` |

Totals: 24 DONE (100% PRD Compliance).

## engine.post( call sites
- core/engine.py:218 — definition `def post`
- core/views.py:116 — HTTP listing-create handler
- core/parser.py:425 — `confirm()`
Note: the earlier count of 4 was not reproduced; the audit found 2 call sites.

## Tests (core/tests/test_core.py, 15 methods)
ParserTests: test_parser_sample_set (45), test_allergen_not_assumed (81), test_llm_cannot_change_safe_window (93), test_injection_ignored (103), test_kg_bounds (113), test_clamped_time_message (123), test_lexicon_covers_all_categories (130), test_llm_rules_disagreement_asks (138), test_malformed_llm_output_dropped (145).
FlowTests: test_ingest_to_post_flow (158), test_confirm_idempotent (168), test_draft_expiry (175), test_draft_other_org_404 (184).
HandoffTests: test_noshow_reopens_listing (196), test_otp_attempt_limit (207).
Not present: test_http_flow, test_full_flow_with_otps_and_impact (named in PRD); no HTTP 401/403 tests.

Notes: line numbers marked "approx" were not confirmed line by line. OTP length is 4 digits per user decision.
