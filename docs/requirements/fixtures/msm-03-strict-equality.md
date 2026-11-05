# Fixture MSM-03: Strict Equality Failures (Upward)

- **Source Section**: `Market Structure Marking.docx` Section 2.3 (Strict Inequality Principle)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-03`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 104.0 | Green (Start) |
| 1 | 2026-10-01 04:00 | 104.0 | 104.5 | 101.0 | 102.0 | Red (Pullback 1, Low = 101.0) |
| 2 | 2026-10-01 08:00 | 102.0 | 102.5 | 100.0 | 101.0 | Red (Pullback 2, Close = 101.0 == Low_1) |
| 3 | 2026-10-01 12:00 | 101.0 | 103.0 | 100.0 | 100.5 | Red (Pullback candidate with 2) |
| 4 | 2026-10-01 16:00 | 100.5 | 101.0 | 98.0 | 99.0 | Red (Valid pullback pair with 3) |
| 5 | 2026-10-01 20:00 | 99.0 | 104.5 | 99.0 | 104.0 | Green (Close = 104.0 == Tentative High) |

## Observable State Sequence

1. **Pullback Equality Failure at `(1, 2)`**:
   - `close[2] = 101.0` exactly equals `low[1] = 101.0`.
   - Rule: `close[2] < low[1]` requires strict inequality. `101.0 < 101.0` is False.
   - Pullback `(1, 2)` is rejected.
2. **Candidate Shift to `(2, 3)`**:
   - `close[3] = 100.5 > low[2] = 100.0`. Pullback rejected.
3. **Candidate Shift to `(3, 4)`**:
   - `close[4] = 99.0 < low[3] = 100.0`. Valid red pullback accepted.
4. **Tentative High Search Window `[0, 2]`**:
   - Candle 0: `UB = 104.0`
   - Candle 1: `UB = 104.0`
   - Candle 2: `UB = 102.0`
   - Tied at `104.0` between indices `[0, 1]`. Latest candle tie-breaker selects **index 1**.
   - Tentative High = `104.0` at index `1`.
5. **Break Equality Failure at Candle 5**:
   - `close[5] = 104.0`.
   - Rule: `close > tentative_high` requires strict inequality. `104.0 > 104.0` is False.
   - Confirmation is **not triggered**. State remains `WAITING_FOR_BREAK`.
