# Fixture CHOCH-09: Cycle Completion and Sequence Reset

- **Source Authority**: `docs/strategy/Choch.pdf` Section 2.1, with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-08).
- **Fixture Category**: `synthetic_prerequisite_unit`, `source_settled`
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_tentative_point_confirmed_resets_choch_sequence`)

## Description
When price achieves an upward continuation closing break above Tentative High (`close > tentative_high`):
1. The tentative extreme converts to a Confirmed High in the prevailing MSM structure.
2. The tentative Point 3 status is lost.
3. Any in-progress CHOCH close count immediately resets to 0.
4. CHOCH evaluation is locked out until a new Tentative Point 3 is established by a subsequent valid pullback.

## Chronological Progression

| Index | Close | Event |
|---|---|---|
| 5 | 1.155 | Point 3 peak (Tentative High Upper Body = 1.155) |
| 7 | 1.125 | Point 3 identified as active upon completion of pullback candle 2 |
| 8 | 1.165 | Continuation break: `close = 1.165 > 1.155`. Tentative High confirmed; cycle continues. Tentative Point 3 deactivated. CHOCH close counter reset. |
| 9 | 1.095 | Closes below prior support (1.105), but Point 3 is no longer active. |
| 10 | 1.085 | Closes below prior support, but Point 3 is still absent. |

## Expected Behavior
- After index 8: `tentative_point_3_active = false`, `confirmed_high_updated = 1.155`.
- At index 10: `confirmed = false`, `reason = "NO_ACTIVE_POINT_3_AFTER_CYCLE_COMPLETION"`.
