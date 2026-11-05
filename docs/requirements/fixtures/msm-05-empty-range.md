# Fixture MSM-05: Empty-Range Skip (Reconciled Clarification)

- **Source Section**: `Market Structure Marking.docx` Section 7 & `approved-clarifications.md` (EMPTY RANGE)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-05`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red (Start candle) |
| 1 | 2026-10-01 04:00 | 103.0 | 103.5 | 100.0 | 101.0 | Red (Close 101.0 < Low_0 102.0) |
| 2 | 2026-10-01 08:00 | 101.0 | 106.0 | 100.5 | 105.0 | Green (Climbing) |
| 3 | 2026-10-01 12:00 | 105.0 | 108.0 | 104.0 | 107.0 | Green (Peak) |
| 4 | 2026-10-01 16:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1) |
| 5 | 2026-10-01 20:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2, Close < Low_4) |
| 6 | 2026-10-02 00:00 | 102.0 | 110.0 | 102.0 | 109.0 | Green (Closing break: Close = 109 > 107) |

## Search Window Evaluations

1. **Empty-Range Skip**:
   - First candidate pullback `(0, 1)` is valid red sequence (`close[1] < low[0]`).
   - Search window: `[search_start = 0, p1 - 1 = -1]`. Window is empty (0 candles).
   - Empty-Range Rule: Skip pair `(0, 1)`, retain `search_start = 0`.
2. **Second Pullback Search**:
   - Valid pullback found at `(4, 5)`.
   - Tentative High search range: `[0, 3]`.
   - Max UB is candle 3 (`UB = 107.0`).
   - Tentative High = `107.0` at index `3`.
3. **Confirmed Low Search**:
   - Range: `[3, 6]`.
   - Lower body edges: candle 3 (105.0), candle 4 (104.0), candle 5 (102.0), candle 6 (102.0).
   - Tied at `102.0` between indices `[5, 6]`. Latest candle tie-breaker selects **index 6**.
   - Confirmed Low = `102.0` at index `6`.
   - Next search start reference = **index 6**.
