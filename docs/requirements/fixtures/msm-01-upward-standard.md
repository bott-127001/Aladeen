# Fixture MSM-01: Upward Standard Cycle (Clean Confirmation)

- **Source Section**: `Market Structure Marking.docx` Section 3 (Upward Algorithm) & Section 2.4 (Tie-Breaker)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-01`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 102.0 | 99.0 | 101.0 | Green (Start candle) |
| 1 | 2026-10-01 04:00 | 101.0 | 106.0 | 100.5 | 105.0 | Green (Climbing) |
| 2 | 2026-10-01 08:00 | 105.0 | 108.0 | 104.0 | 107.0 | Green (Swing peak) |
| 3 | 2026-10-01 12:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1, Low = 103.0) |
| 4 | 2026-10-01 16:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2, Close = 102.0 < 103.0) |
| 5 | 2026-10-01 20:00 | 102.0 | 105.0 | 101.0 | 103.5 | Green (Inside range) |
| 6 | 2026-10-02 00:00 | 103.5 | 110.0 | 103.0 | 109.0 | Green (Closing break: Close = 109.0 > 107.0) |

## Search Window Evaluations

1. **Tentative High Search**:
   - Window: `[0, 2]` (`[search_start, p1 - 1]`)
   - Eligible upper body edges:
     - Candle 0: `UB = max(100.0, 101.0) = 101.0`
     - Candle 1: `UB = max(101.0, 105.0) = 105.0`
     - Candle 2: `UB = max(105.0, 107.0) = 107.0`
   - Maximum UB: `107.0` at index `2`.
   - **Tentative High**: `107.0` at index `2` (identified at bar 4).

2. **Confirmed Low Search**:
   - Window: `[2, 6]` (`[tentative_high, break_candle]`, inclusive of both endpoints)
   - Eligible lower body edges:
     - Candle 2: `LB = min(105.0, 107.0) = 105.0`
     - Candle 3: `LB = min(107.0, 104.0) = 104.0`
     - Candle 4: `LB = min(104.0, 102.0) = 102.0`
     - Candle 5: `LB = min(102.0, 103.5) = 102.0`
     - Candle 6: `LB = min(103.5, 109.0) = 103.5`
   - Minimum LB: `102.0`, occurring at indices `[4, 5]`.
   - **Tie-Breaker**: Section 2.4 selects the latest eligible candle: **index 5**.
   - **Confirmed Low**: `102.0` at index `5` (confirmed at bar 6).

## Confirmed Results
- **Confirmed High**: `107.0` at index `2`
- **Confirmed Low**: `102.0` at index `5` (Last Support)
- **Next Search Start Reference**: Index `5`
- **Next Pullback Candidate Search (`p1`)**: Must be `> 6` (strictly after break candle)
- **Diagnostic Trend Status**: `"Marking upward structure"`
