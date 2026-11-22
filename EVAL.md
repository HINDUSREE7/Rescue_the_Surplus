# EVAL: intake parser (scripts/eval_intake.py)

**Caveat: synthetic set, no native-speaker review yet.** The 30 synthetic items were written by the developer, not collected from donors, and no native Telugu speaker has reviewed them. The 8 sample items come from the PRD.

## Harness

Command, from the project root:

`python scripts\eval_intake.py [--mode rules|stub|reconciled|all]`

- Default is `all`, which runs `rules`, `stub`, and `reconciled` in that order.
- The script sets up Django itself and runs the real parser against the configured DB inside a transaction that is rolled back. No server, no network.
- Output is stdout only. The script writes **no output files**. For a saved record, redirect stdout yourself.
- Stdout, in order: an `items per group:` line; then, for each mode, a `== mode: X ==` block with a field table (correct / applicable / accuracy), a `failures:` list (or `failures: none`), an `injection: N/3 safe window unchanged` line, and a `total items: 38, mode: X` line.
- Exit code is always 0. The script reports; it does not gate.

## Dataset

38 items: sample 8; telugu_script 4; romanised_telugu 4; english 4; mixed 3; speech_typo 4; plates_trays 3; ambiguous_time 2; injection 3 (each with a clean_text twin); out_of_range 3.

## Modes

- **rules:** LLM disabled; rule-based parser only.
- **stub:** a fixed stub returns `{"kg": 12, "category": "curry_dal"}` for every item. It exercises validation and reconciliation; it is NOT a model and says nothing about model quality.
- **reconciled:** the same stub output plus two window-tampering keys (`expires`, `safe_hours`) that the LLM must not be able to change. The real merge path (`parser._extract` -> `reconcile()`) runs in both `stub` and `reconciled`; the only difference is the extra keys. The stub and reconciled numbers are identical, so this run shows no separate reconciliation effect.
- **all** (default): runs the three modes above in order.
- The `stub` and `reconciled` modes patch `parser.call_llm`. The harness therefore does not exercise `HttpLLM` or `get_extractor()`.

## LLM

- `core/llm.py` defines `CONFIDENCE_MIN = 0.7`.
- `StubLLM` is deterministic, makes no network calls, and measures no real model.
- `HttpLLM` is enabled only when the environment variable `RTS_LLM_URL` is set. No results for it are recorded in this document.
- `get_extractor()` is the entry point for obtaining the extractor; how it chooses between `StubLLM` and `HttpLLM` is in `core/llm.py`.
- Confidence is the agreement between the LLM output and the rules output (`agreement()`). It is not the model's self-report.

## OTP expiry

- OTPs expire after `OTP_TTL_MINUTES` (10, defined in `core/engine.py`).
- An expired OTP is rejected with HTTP 409, "OTP expired", and does not consume an attempt.
- `scripts/eval_intake.py` does not cover OTP behaviour; no numbers in this document apply to it.

## Results

Before lexicon fixes (rules mode, failures = 8):

| Field | Correct | Applicable | Accuracy |
|---|---|---|---|
| category | 34 | 36 | 94.4% |
| kg | 33 | 35 | 94.3% |
| allergens | 17 | 21 | 81.0% |

After lexicon fixes (rules mode, failures = 0):

| Field | Correct | Applicable | Accuracy |
|---|---|---|---|
| category | 36 | 36 | 100.0% |
| kg | 35 | 35 | 100.0% |
| allergens | 21 | 21 | 100.0% |

Stub mode after fixes: category 9/36 (25.0%), kg 4/35 (11.4%), allergens 21/21 (100.0%).
Reconciled mode after fixes: identical to stub.

Injection: 3/3 safe window unchanged in all three modes, before and after.

## Failures

- **Before fixes, rules mode:**
  - t4 allergens (Telugu gluten word missing)
  - r2 allergens (negation "ledu"-style not handled)
  - sp1 kg (spoken number before "kilo")
  - sp2 category and allergens (repeated letters, e.g. "biriyanii")
  - sp3 category (repeated letters)
  - sp4 allergens ("nothing allergic" phrase missing)
  - o3 kg (negative kg accepted by the pattern)
- **After fixes, rules mode:** none.
- **Stub and reconciled modes:** category and kg fail on almost every item, because the fixed stub value is wrong for most items. These are expected for a fixed stub and are not parser defects.
- **Out-of-range items in stub and reconciled modes** show kg 12.0 where rejection was expected; the stub value is accepted when the rules have no kg. This is a real reconciliation question for the team to decide (should a missing rules value be filled from the LLM?), not a fix made here.

## Caveats

- **Tuning and test set are the same.** The lexicon fixes were made against the failures of these same 38 items, so the 100% rules result is optimistic. A held-out set is needed before any accuracy claim.
- Synthetic set, no native-speaker review yet.
- The stub is not a model; stub numbers do not measure any LLM.
- No run against a real model is recorded. `HttpLLM`, `get_extractor()`, and the `CONFIDENCE_MIN` gate are not exercised by any mode in `scripts/eval_intake.py`, and whether they are exercised elsewhere is not confirmed.
