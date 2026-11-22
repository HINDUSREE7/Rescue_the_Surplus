# Rescue the Surplus (hackathon prototype)

Donors say or type surplus food ("60 kilo biryani migilindi, 11:30 lopu"). The system turns it into a
validated listing after one confirming tap, then offers it only to receivers who can arrive inside the
food's safe window. If nobody claims it, the search widens on a spoilage clock. Guntur–Vijayawada
corridor, synthetic data only. Django 5 + SQLite, one HTML file with Leaflet, no build step.

## Install and run

```
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ and call `POST /api/demo/reset` (or use the Reset button) to load the sample orgs.

Tests: `python manage.py test`

Optional LLM extractor: set `RTS_LLM_URL` to a JSON-over-HTTP endpoint. It receives `{"text", "schema"}`
and must return a JSON object. It has a 3 s timeout. Without it, the rule-based parser is used.

## Auth (demo only)

Identity is the `X-Org` header carrying the org id. This is not real authentication. Production needs
phone-OTP sessions, server-side roles, CSRF, and rate limits (see PRD §11).

## Trust boundary

- Only `core.engine.post()` creates a `Listing`. The intake only creates it through `confirm()`, after the donor taps.
- Safe windows, expiry and status come from the engine (`CATEGORIES`, `MARGIN_MIN`) only. The LLM cannot set them.
- Allergens are never assumed. Silence asks the donor.
- Instruction-like clauses in messages are dropped before extraction.

## Endpoints

GET `/api/meta`, `/api/orgs`, `/api/view`, `/api/impact`, `/api/stream` (SSE).
POST `/api/listings` (form), `/api/ingest`, `/api/ingest/answer`, `/api/ingest/confirm`, `/api/ingest/cancel`,
`/api/listings/<id>/claim|decline|collect|deliver`, `/api/demo/reset|speed|scenario`.
Errors are `{"error": "..."}` with 400/401/403/404/409.

## Defaults chosen (illustrative, not validated)

- Safe windows, storage text, meal and CO₂e factors, plate/tray kg (`PLATE_KG` 0.35, `TRAY_KG` 2.5) are demo placeholders.
  Validate with FSSAI guidance and a food-safety officer before real use.
- Ambiguous clock time ("11:30") resolves to the next future occurrence, trying both am and pm.
- OTP: 4 digits (per user request), 5 attempts.
- Draft TTL 15 min; `CLARIFY_MAX` = 2 free-text questions, then an editable form.
- Stream loop and `/api/view` call `engine.tick()`, so the clock advances without a separate ticker.

## PRD conflicts and how they were resolved

- **Repo layout:** the Final PRD §20 places intake in `core/intake/`. The task asked for a flat `core/parser.py`. The flat layout was used.
- **Test count:** the Final PRD refers to "9 core tests" and `ApiTests`, which are not in the named list. The 15 named tests in the task were used.

- **Clarification limit:** allergen chips do not count toward `CLARIFY_MAX = 2` (Final PRD §0 item 1).
- **LLM confidence:** the Final PRD derives confidence from agreement between the LLM and the rules, not from the model's self-report. Implemented that way.
- **Not implemented:** `lexicon.py`/`llm.py` split (folded into `parser.py`); `rules.py` (the constants live in `core/engine.py`);
  `Channels`/Redis, Postgres/PostGIS, Celery, the management `seed` command, and the admin site (scale path, PRD §13).
  Telugu-script injection phrases are only partly covered.
