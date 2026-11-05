# Fixture MSM-09: Downward Equality Failures

- **Source Section**: `Market Structure Marking.docx` Section 2.3 & Section 4
- **Starting Input**: Index 0, Direction = `DOWNWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-09`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 200.0 | 201.0 | 191.0 | 192.0 | Red (Start candle, LB = 192.0) |
| 1 | 2026-10-01 04:00 | 192.0 | 196.0 | 191.5 | 195.0 | Green (Pullback 1, High = 196.0) |
| 2 | 2026-10-01 08:00 | 195.0 | 197.0 | 194.0 | 196.0 | Green (Pullback 2, Close = 196.0 == High_1) |
| 3 | 2026-10-01 12:00 | 196.0 | 199.0 | 195.5 | 198.5 | Green (Pullback 3, Close = 198.5 > High_2) |
| 4 | 2026-10-01 16:00 | 198.5 | 199.0 | 191.5 | 192.0 | Red (Close = 192.0 == Tentative Low) |

## Observable State Sequence

1. **Pullback Equality Failure at `(1, 2)`**:
   - `close[2] = 196.0 == high[1] = 196.0`. Fails strict inequality (`196.0 > 196.0` is False). Rejected.
2. **Valid Pullback at `(2, 3)`**:
   - `close[3] = 198.5 > high[2] = 197.0`. Accepted.
3. **Tentative Low Search in `[0, 1]`**:
   - `LB(0) = 192.0`, `LB(1) = 192.0`.
   - Tied at 192.0! Latest candle tie-breaker selects **index 1**.
   - Tentative Low = `192.0` at index `1`.
4. **Break Equality Failure at Candle 4**:
   - `close[4] = 192.0`. Strict downward break requires `close < 192.0`.
   - `192.0 < 192.0` is False. Confirmation is not triggered. State remains `WAITING_FOR_BREAK`.
