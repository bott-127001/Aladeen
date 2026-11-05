# Fixture MSM-04: Flat Candle Interruption

- **Source Section**: `Market Structure Marking.docx` Section 2.2 (Flat Candle Rules)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-04`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 104.0 | Green (Start) |
| 1 | 2026-10-01 04:00 | 104.0 | 104.5 | 101.0 | 102.0 | Red (Candle 1) |
| 2 | 2026-10-01 08:00 | 102.0 | 103.0 | 101.0 | 102.0 | Flat (Open == Close == 102.0) |
| 3 | 2026-10-01 12:00 | 102.0 | 102.5 | 99.0 | 100.0 | Red (Candle 3) |

## Observable State Sequence

1. Candle 2 is flat (`open == close`). It is neither green nor red.
2. Candidate `(1, 2)` rejected (candle 2 not red).
3. Candidate `(2, 3)` rejected (candle 2 not red).
4. Pullback count remains 0; state remains `SEARCHING_PULLBACK`.
