# Fixture CHOCH-03: Single Qualifying Close Rejection

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 3.1 & `docs/requirements/approved-clarifications.md` (OPEN-01, OPEN-03)
- **Starting Structure**: Upward structure with Last Support at `1.105` (index 3) and active Point 3 at `1.155` (index 5).
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_bearish_single_qualifying_close_rejected`)

## Description
A single completed candle close below the broken level is insufficient to confirm a Change of Character. If candle $c_1$ closes below support, but candle $c_2$ closes at or above support, the CHOCH is not confirmed and the pending break counter resets to 0.

## Candidate Candles

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Behavior |
|---|---|---|---|---|---|---|
| 8 | 2026-10-02 08:00 | 1.120 | 1.125 | 1.090 | 1.095 | Candle $c_1$: Close = 1.095 < 1.105 (Qualifies as first close) |
| 9 | 2026-10-02 12:00 | 1.095 | 1.115 | 1.092 | 1.110 | Candle $c_2$: Close = 1.110 >= 1.105 (Fails to confirm) |

## Expected Behavior
- At index 8: 1 qualifying close recorded; CHOCH is unconfirmed.
- At index 9: Candle closes above Last Support; consecutive close requirement is violated.
- Result: `confirmed = false`, `reason = "SECOND_CLOSE_FAILED_ABOVE_OR_EQUAL"`.
- Qualifying close counter resets to 0.
