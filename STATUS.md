# STATUS: Rescue the Surplus vs Final PRD
Verification: `manage.py test` ran 15 tests, all OK; `manage.py check` reported no issues. scripts/verify.sh does not exist in this project. Dev server not re-run for this audit.

| # | Item | Status | Proof (file:line) / note |
|---|---|---|---|
| 1 | engine.post single writer | DONE | core/engine.py:218 `def post`; Listing.objects.create at engine.py:230 (only write) |
| 2 | Listing.source | DONE | engine.py:218 `source="form"` parameter; field in core/models.py |
| 3 | Draft model | DONE | class Draft in core/models.py |
| 4 | Intake flow ingest/answer/confirm/cancel | DONE | core/urls.py:13-16; core/parser.py:425 `confirm()` |
| 5 | Idempotent confirm | DONE | core/tests/test_core.py:168 test_confirm_idempotent |
| 6 | Draft TTL and org ownership | DONE | core/parser.py:320 `_load`, :327 `_check_open`; tests test_core.py:175, :184. Raw-text retention purge not implemented. |
| 7 | Allergen always asked | DONE | test_core.py:81 test_allergen_not_assumed |
| 8 | LLM stub + reconcile | PARTIAL | reconcile tests test_core.py:93, :138, :145; no separate LLM module/stub class; CONFIDENCE_MIN not defined |
| 9 | Lexicon covers all categories | DONE | test_core.py:130 |
| 10 | /api/ingest* routes | DONE | core/urls.py:13-16 |
| 11 | Chat bubbles | MISSING | none in public/index.html |
| 12 | Allergen chips | DONE | public/index.html (chip render, approx lines 18-19, 123-124) |
| 13 | Confirmation card | PARTIAL | card render approx public/index.html:108; clamp message shown only in status bar, not on card |
| 14 | Confidence strip | DONE | public/index.html approx line 113 |
| 15 | No-show reopen | DONE | core/engine.py no-show handler (approx 361-391); test_core.py:196 |
| 16 | OTP attempt limit | PARTIAL | test_core.py:207; attempt logic engine.py approx 316-328; OTP expiry not implemented |
| 17 | Rate limit | MISSING | no throttle in core/apps.py or views.py |
| 18 | Coordinate coarsening | MISSING | API returns exact lat/lon; no rounding |
| 19 | Impact strip | PARTIAL | impact computed; not rendered in UI |
| 20 | Assumptions drawer | PARTIAL | shown inline, always visible; no drawer (public/index.html approx 190) |
| 21 | Clock-speed selector | MISSING | API endpoint exists; no UI control |
| 22 | Repeat last | MISSING | no control in UI |
| 23 | Sponsor view | PARTIAL | reuses generic feed (public/index.html approx 37); no dedicated panel |
| 24 | EVAL.md | MISSING | file does not exist |

Totals: 12 DONE, 6 PARTIAL (8, 13, 16, 19, 20, 23), 6 MISSING (11, 17, 18, 21, 22, 24).

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
