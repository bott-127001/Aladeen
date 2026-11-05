# Fixture MSM-12: Two Completed Pairs with Post-Break Pullback Restriction and Trend Status

- **Source Section**: `Market Structure Marking.docx` Section 3.1, Section 4 & `approved-clarifications.md` (OPEN-01)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-12`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 102.5 | 99.0 | 102.0 | Green (Start) |
| 1 | 2026-10-01 04:00 | 102.0 | 106.0 | 101.5 | 105.0 | Green (Peak 1, UB = 105.0, LB = 102.0) |
| 2 | 2026-10-01 08:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red (Pullback 1-A, Low = 102.0) |
| 3 | 2026-10-01 12:00 | 103.0 | 103.5 | 100.5 | 101.0 | Red (Pullback 1-B, Close = 101.0 < 102.0, LB = 101.0) |
| 4 | 2026-10-01 16:00 | 102.0 | 108.0 | 101.5 | 107.0 | Green (Break 1: Close = 107.0 > 105.0) |
| 5 | 2026-10-01 20:00 | 107.0 | 112.0 | 106.5 | 111.0 | Green (Peak 2, UB = 111.0, LB = 107.0) |
| 6 | 2026-10-02 00:00 | 111.0 | 111.5 | 107.0 | 108.0 | Red (Pullback 2-A, candidate p1 = 6 > 4, Low = 107.0) |
| 7 | 2026-10-02 04:00 | 108.0 | 108.5 | 104.5 | 105.0 | Red (Pullback 2-B, Close = 105.0 < 107.0, LB = 105.0) |
| 8 | 2026-10-02 08:00 | 106.0 | 115.0 | 105.5 | 114.0 | Green (Break 2: Close = 114.0 > 111.0) |

## Cycle 1 Execution
- Pullback `(2, 3)` identifies Tentative High = `105.0` at index `1`.
- Candle 4 breaks 105.0. Confirmed Low search in `[1, 4]` selects index `3` (`LB = 101.0`).
- Confirmed Pair 1: `H1 = 105.0 (idx 1)`, `L1 = 101.0 (idx 3)`.
- Trend Status: `"Marking upward structure"` (< 2 confirmed pairs).
- Search start advances to `3`.
- Post-break rule: Next candidate `p1` must satisfy `p1 > 4` (break candle cannot be reused as pullback candle).

## Cycle 2 Execution
- Candidate pair `(6, 7)` tested (`p1 = 6 > 4`): valid red pullback.
- Tentative High search in `[search_start = 3, p1 - 1 = 5]`: highest UB is candle 5 (`111.0`).
- Tentative High = `111.0` at index `5`.
- Candle 8 breaks 111.0 (`close = 114.0 > 111.0`).
- Confirmed Low search in `[5, 8]` selects index `7` (`LB = 105.0`).
- Confirmed Pair 2: `H2 = 111.0 (idx 5)`, `L2 = 105.0 (idx 7)`.
- Search start advances to `7`.

## Trend Status Evaluation (≥ 2 Confirmed Pairs)
- `H2 (111.0) > H1 (105.0)` is True.
- `L2 (105.0) > L1 (101.0)` is True.
- Diagnostic Trend Status evaluates to: **`"Upward trend"`**.
