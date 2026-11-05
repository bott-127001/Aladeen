# Fixture MSM-11: Non-Green Upward Break & Non-Red Downward Break

- **Source Section**: `Market Structure Marking.docx` Section 3.1 & 3.2 (Break candle color does not matter)
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-11A`, `MSM-11B`)

## Part A: Upward Break by a Red Candle
- **Starting Input**: Index 0, Direction = `UPWARD`

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 106.0 | 99.0 | 105.0 | Green (UB = 105.0) |
| 1 | 2026-10-01 04:00 | 105.0 | 105.5 | 101.0 | 102.0 | Red (Pullback 1, Low = 101.0) |
| 2 | 2026-10-01 08:00 | 102.0 | 102.5 | 99.0 | 100.0 | Red (Pullback 2, Close = 100.0 < 101.0) |
| 3 | 2026-10-01 12:00 | 108.0 | 108.5 | 105.5 | 106.0 | Red (Open 108.0 > Close 106.0; Close 106.0 > 105.0) |

- Tentative High = `105.0` at index `0`.
- Candle 3 is red, but closes at `106.0 > 105.0`. Strict upward break satisfied!
- Confirmed Low search in `[0, 3]`: `LB(0) = 100.0`, `LB(1) = 102.0`, `LB(2) = 100.0`, `LB(3) = 106.0`. Tied at 100.0 across `[0, 2]`. Latest candle selects **index 2**.
- Confirmed Low = `100.0` at index `2`. Next search start = index `2`.

---

## Part B: Downward Break by a Green Candle
- **Starting Input**: Index 0, Direction = `DOWNWARD`

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 200.0 | 201.0 | 194.0 | 195.0 | Red (LB = 195.0) |
| 1 | 2026-10-01 04:00 | 195.0 | 199.0 | 194.5 | 198.0 | Green (Pullback 1, High = 199.0) |
| 2 | 2026-10-01 08:00 | 198.0 | 201.0 | 197.5 | 200.0 | Green (Pullback 2, Close = 200.0 > 199.0) |
| 3 | 2026-10-01 12:00 | 190.0 | 194.5 | 189.5 | 193.0 | Green (Open 190.0 < Close 193.0; Close 193.0 < 195.0) |

- Tentative Low = `195.0` at index `0`.
- Candle 3 is green, but closes at `193.0 < 195.0`. Strict downward break satisfied!
- Confirmed High search in `[0, 3]`: `UB(0) = 200.0`, `UB(1) = 198.0`, `UB(2) = 200.0`, `UB(3) = 193.0`. Tied at 200.0 across `[0, 2]`. Latest candle selects **index 2**.
- Confirmed High = `200.0` at index `2`. Next search start = index `2`.
