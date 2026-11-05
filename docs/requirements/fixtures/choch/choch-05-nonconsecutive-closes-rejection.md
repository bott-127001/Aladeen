# Fixture CHOCH-05: Non-Consecutive Closes Rejection

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 3.1 & `docs/requirements/approved-clarifications.md` (OPEN-01)
- **Starting Structure**: Upward structure with Last Support at `1.105` and active Point 3 at `1.155`.
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_nonconsecutive_qualifying_closes_rejected`)

## Description
The two qualifying closes must be strictly consecutive ($c_2$ immediately following $c_1$). If an intervening candle closes on or inside the structural boundary, the confirmation sequence is broken.

## Candidate Candles

| Index | Close | Qualifies ($< 1.105$)? | State Progression |
|---|---|---|---|
| 8 | 1.095 | Yes | Pending close count = 1 |
| 9 | 1.108 | No | Non-qualifying close; pending count resets to 0 |
| 10 | 1.090 | Yes | Pending close count = 1 (new sequence) |

## Expected Behavior
- Candle 8 and Candle 10 cannot be paired across Candle 9.
- Evaluation at index 10: Only 1 qualifying close in the active sequence.
- Result: `confirmed = false`, `reason = "NON_CONSECUTIVE_CLOSES"`.
