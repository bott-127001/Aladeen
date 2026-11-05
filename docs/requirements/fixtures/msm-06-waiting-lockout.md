# Fixture MSM-06: Waiting-State Lockout (No Overlapping Cycles)

- **Source Section**: `Market Structure Marking.docx` Section 3 (Step 5: Lockout)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-06`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 108.0 | 99.0 | 107.0 | Green (Start & Peak UB = 107.0) |
| 1 | 2026-10-01 04:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1) |
| 2 | 2026-10-01 08:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2 -> Tentative High = 107.0) |
| 3 | 2026-10-01 12:00 | 102.0 | 106.0 | 101.5 | 105.0 | Green |
| 4 | 2026-10-01 16:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red (Secondary Pullback 1) |
| 5 | 2026-10-01 20:00 | 103.0 | 103.5 | 100.0 | 101.0 | Red (Secondary Pullback 2) |
| 6 | 2026-10-02 00:00 | 101.0 | 110.0 | 101.0 | 109.0 | Green (Closing break: Close = 109.0 > 107.0) |

## Observable State Sequence

1. Pullback `(1, 2)` establishes tentative high = `107.0` at index `0`.
2. While waiting for a closing break of 107.0, candles `(4, 5)` form another red pullback.
3. Lockout rule: Engine must **ignore** pullback `(4, 5)`.
4. Candle 6 breaks 107.0. Confirmed Low search in `[0, 6]`: lowest LB is candle 0 (`LB = 100.0`).
5. Confirmed Low = `100.0` at index `0`. Next search start = index `0`.
