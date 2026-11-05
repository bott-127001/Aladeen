# Fixture MSM-08: Tied Extremes in Both Directions

- **Source Section**: `Market Structure Marking.docx` Section 2.4 (Tie-Breaker Rule)
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-08A`, `MSM-08B`)

## Part A: Upward Tied Tentative High & Tied Confirmed Low
- **Starting Input**: Index 0, Direction = `UPWARD`

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 105.0 | Green (UB = 105.0) |
| 1 | 2026-10-01 04:00 | 104.0 | 106.0 | 102.0 | 105.0 | Green (UB = 105.0) |
| 2 | 2026-10-01 08:00 | 105.0 | 105.5 | 101.0 | 102.0 | Red (Pullback 1, Low = 101.0) |
| 3 | 2026-10-01 12:00 | 102.0 | 102.5 | 99.5 | 100.0 | Red (Pullback 2, Close = 100.0 < 101.0) |
| 4 | 2026-10-01 16:00 | 100.0 | 108.0 | 100.0 | 107.0 | Green (Break: Close = 107.0 > 105.0) |

- **Tentative High Search in `[0, 1]`**:
  - `UB(0) = 105.0`, `UB(1) = 105.0`.
  - Tied at 105.0! Latest candle selects **index 1**.
  - Tentative High = `105.0` at index `1`.
- **Confirmed Low Search in `[1, 4]`**:
  - `LB(1) = 104.0`, `LB(2) = 102.0`, `LB(3) = 100.0`, `LB(4) = 100.0`.
  - Tied at 100.0 across `[3, 4]`. Latest candle selects **index 4**.
  - Confirmed Low = `100.0` at index `4`.
  - Next search start index = **4**.

---

## Part B: Downward Tied Tentative Low & Tied Confirmed High
- **Starting Input**: Index 0, Direction = `DOWNWARD`

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 200.0 | 201.0 | 194.0 | 195.0 | Red (LB = 195.0) |
| 1 | 2026-10-01 04:00 | 196.0 | 197.0 | 194.5 | 195.0 | Red (LB = 195.0) |
| 2 | 2026-10-01 08:00 | 195.0 | 199.0 | 194.5 | 198.0 | Green (Pullback 1, High = 199.0) |
| 3 | 2026-10-01 12:00 | 198.0 | 201.0 | 197.5 | 200.0 | Green (Pullback 2, Close = 200.0 > 199.0) |
| 4 | 2026-10-01 16:00 | 200.0 | 200.5 | 192.0 | 193.0 | Red (Break: Close = 193.0 < 195.0) |

- **Tentative Low Search in `[0, 1]`**:
  - `LB(0) = 195.0`, `LB(1) = 195.0`.
  - Tied at 195.0! Latest candle selects **index 1**.
  - Tentative Low = `195.0` at index `1`.
- **Confirmed High Search in `[1, 4]`**:
  - `UB(1) = 196.0`, `UB(2) = 198.0`, `UB(3) = 200.0`, `UB(4) = 200.0`.
  - Tied at 200.0 across `[3, 4]`. Latest candle selects **index 4**.
  - Confirmed High = `200.0` at index `4` (Last Resistance).
  - Next search start index = **4**.
