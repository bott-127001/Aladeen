# Fixture CHOCH-09: Cycle Completion and Sequence Reset

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 2.1 & `docs/requirements/approved-clarifications.md` (OPEN-01, OPEN-08)
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_tentative_point_confirmed_resets_choch_sequence`)

## Description
When price breaks above Tentative High in an upward structure (closing break $\text{close} > \text{tentative\_high}$):
1. The tentative extreme is converted to a Confirmed High.
2. The current cycle completes normally via MSM continuation.
3. The tentative Point 3 status is lost.
4. Any in-progress CHOCH break count is reset to 0.
5. CHOCH is locked out until a new Tentative Point 3 is established in the new cycle.

## Progression

| Index | Close | Event |
|---|---|---|
| 5 | 1.155 | Point 3 peak (tentative high = 1.155) |
| 7 | 1.125 | Point 3 active |
| 8 | 1.165 | Continuation break: `close = 1.165 > 1.155`. Tentative High confirmed; cycle continues. Tentative Point 3 deactivated. CHOCH close counter reset. |
| 9 | 1.095 | Closes below previous support (1.105), but Point 3 is no longer active. |
| 10 | 1.085 | Closes below previous support, but Point 3 is still absent. |

## Expected Behavior
- After index 8: `tentative_point_3_active = false`, `confirmed_high_updated = 1.155`.
- At index 10: `confirmed = false`, `reason = "NO_ACTIVE_POINT_3_AFTER_CYCLE_COMPLETION"`.
