# Fixture MSM-02: Downward Standard Cycle (Clean Confirmation & Confirmed Extreme Tie)

- **Source Section**: `Market Structure Marking.docx` Section 4 (Downward Algorithm) & Section 2.4 (Tie-Breaker)
- **Starting Input**: Index 0, Direction = `DOWNWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-02`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 200.0 | 201.0 | 198.0 | 199.0 | Red (Start candle) |
| 1 | 2026-10-01 04:00 | 199.0 | 199.5 | 194.0 | 195.0 | Red (Falling) |
| 2 | 2026-10-01 08:00 | 195.0 | 196.0 | 191.0 | 192.0 | Red (Swing trough) |
| 3 | 2026-10-01 12:00 | 192.0 | 196.0 | 191.5 | 195.0 | Green (Pullback 1, High = 196.0) |
| 4 | 2026-10-01 16:00 | 195.0 | 198.0 | 194.5 | 197.0 | Green (Pullback 2, Close = 197.0 > 196.0) |
| 5 | 2026-10-01 20:00 | 197.0 | 197.5 | 193.0 | 194.0 | Red (Inside range, UB = 197.0) |
| 6 | 2026-10-02 00:00 | 194.0 | 194.5 | 189.0 | 190.0 | Red (Closing break: Close = 190.0 < 192.0) |

## Search Window Evaluations

1. **Tentative Low Search**:
   - Window: `[0, 2]` (`[search_start, p1 - 1]`)
   - Eligible lower body edges:
     - Candle 0: `LB = min(200.0, 199.0) = 199.0`
     - Candle 1: `LB = min(199.0, 195.0) = 195.0`
     - Candle 2: `LB = min(195.0, 192.0) = 192.0`
   - Minimum LB: `192.0` at index `2`.
   - **Tentative Low**: `192.0` at index `2` (identified at bar 4).

2. **Confirmed High Search**:
   - Window: `[2, 6]` (`[tentative_low, break_candle]`, inclusive of both endpoints)
   - Eligible upper body edges:
     - Candle 2: `UB = max(195.0, 192.0) = 195.0`
     - Candle 3: `UB = max(192.0, 195.0) = 195.0`
     - Candle 4: `UB = max(195.0, 197.0) = 197.0`
     - Candle 5: `UB = max(197.0, 194.0) = 197.0`
     - Candle 6: `UB = max(194.0, 190.0) = 194.0`
   - Maximum UB: `197.0`, occurring at indices `[4, 5]`.
   - **Tie-Breaker**: Section 2.4 selects the latest eligible candle: **index 5**.
   - **Confirmed High**: `197.0` at index `5` (confirmed at bar 6).

## Confirmed Results
- **Confirmed Low**: `192.0` at index `2`
- **Confirmed High**: `197.0` at index `5` (Last Resistance)
- **Next Search Start Reference**: Index `5`
- **Next Pullback Candidate Search (`p1`)**: Must be `> 6`
- **Diagnostic Trend Status**: `"Marking downward structure"`
