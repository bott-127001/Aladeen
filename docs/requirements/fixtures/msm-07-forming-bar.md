# Fixture MSM-07: Completed Candles Only & Forming Bar Exclusion

- **Source Section**: `Market Structure Marking.docx` Section 1 & `approved-clarifications.md` (OPEN-08)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-07`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color | is_forming |
|---|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 104.0 | Green | False |
| 1 | 2026-10-01 04:00 | 104.0 | 106.0 | 103.0 | 105.0 | Green | False |
| 2 | 2026-10-01 08:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red | False |
| 3 | 2026-10-01 12:00 | 103.0 | 103.5 | 100.0 | 101.0 | Red | False |
| 4 | 2026-10-01 16:00 | 101.0 | 110.0 | 101.0 | 108.0 | Green | **True** (Latest bar) |

## Observable State Sequence

1. Completed candles 0–3 establish tentative high = `105.0` at index `1`.
2. Candle 4 has `close = 108.0 > 105.0`, but has `is_forming == True`.
3. Engine must **not** confirm high on candle 4.
4. Tentative high remains unconfirmed; 0 confirmed pairs.
