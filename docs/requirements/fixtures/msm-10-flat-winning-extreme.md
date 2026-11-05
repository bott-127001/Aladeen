# Fixture MSM-10: Flat Candle Winning Extreme Search (Upward)

- **Source Section**: `Market Structure Marking.docx` Section 2.2 & Section 3.1
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-10`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 102.0 | 99.0 | 101.0 | Green (Start, UB = 101.0) |
| 1 | 2026-10-01 04:00 | 106.0 | 107.0 | 105.0 | 106.0 | Flat (Open == Close == 106.0, UB = 106.0) |
| 2 | 2026-10-01 08:00 | 105.0 | 105.5 | 103.0 | 104.0 | Red (Pullback 1, Low = 103.0) |
| 3 | 2026-10-01 12:00 | 104.0 | 104.5 | 101.0 | 102.0 | Red (Pullback 2, Close = 102.0 < 103.0) |
| 4 | 2026-10-01 16:00 | 102.0 | 109.0 | 102.0 | 108.0 | Green (Break: Close = 108.0 > 106.0) |

## Search Window Evaluations

1. **Tentative High Search in `[0, 1]`**:
   - Candle 0: `UB = 101.0`
   - Candle 1 (Flat): `UB = max(106.0, 106.0) = 106.0`
   - Flat candle 1 has the winning extreme body edge.
   - Tentative High = `106.0` at index `1`.
2. **Confirmed Low Search in `[1, 4]`**:
   - `LB(1) = 106.0`, `LB(2) = 104.0`, `LB(3) = 102.0`, `LB(4) = 102.0`.
   - Tied at 102.0 across `[3, 4]`. Latest candle tie-breaker selects **index 4**.
   - Confirmed Low = `102.0` at index `4`.
   - Next search start index = **4**.
