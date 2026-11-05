# Fixture MSM-14: Deterministic Replay / Prefix Consistency with Knowledge Times

- **Source Section**: `Market Structure Marking.docx` Section 1.2, OPEN-08, OPEN-09 (Deterministic Execution)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-14`)

## Full 10-Candle Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 102.0 | 99.0 | 101.0 | Start candle |
| 1 | 2026-10-01 04:00 | 101.0 | 106.0 | 100.5 | 105.0 | Green |
| 2 | 2026-10-01 08:00 | 105.0 | 108.0 | 104.0 | 107.0 | Swing peak (UB = 107.0) |
| 3 | 2026-10-01 12:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1) |
| 4 | 2026-10-01 16:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2) |
| 5 | 2026-10-01 20:00 | 102.0 | 105.0 | 101.0 | 103.5 | Green (Inside range) |
| 6 | 2026-10-02 00:00 | 103.5 | 110.0 | 103.0 | 109.0 | Green (Break of 107.0) |
| 7 | 2026-10-02 04:00 | 109.0 | 112.0 | 108.0 | 111.0 | Green |
| 8 | 2026-10-02 08:00 | 111.0 | 111.5 | 106.0 | 107.0 | Red |
| 9 | 2026-10-02 12:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red |

## Prefix Consistency & Knowledge Time Semantics

1. **Prefix 0..4 (Knowledge Time `2026-10-01 16:00`)**:
   - Completed candles available: 0 through 4.
   - Observable state: Pullback `(3, 4)` identified.
   - Tentative High marked: `price = 107.0, candle_index = 2, candle_time = 2026-10-01 08:00`.
   - Confirmed pairs: 0. State: `WAITING_FOR_BREAK`.

2. **Prefix 0..6 (Knowledge Time `2026-10-02 00:00`)**:
   - Completed candles available: 0 through 6.
   - Candle 6 breaks 107.0.
   - Confirmed High: `107.0` at candle `2` (`2026-10-01 08:00`), confirmed at `2026-10-02 00:00`.
   - Confirmed Low: `102.0` at candle `5` (`2026-10-01 20:00`), confirmed at `2026-10-02 00:00`.
   - Confirmed pairs: 1. Next search start index: `5`.

3. **Full Dataset 0..9 (Knowledge Time `2026-10-02 12:00`)**:
   - Completed candles available: 0 through 9.
   - Confirmed Pair 1 remains strictly identical to prefix 0..6:
     - High: `107.0` at candle `2` (`2026-10-01 08:00`).
     - Low: `102.0` at candle `5` (`2026-10-01 20:00`).
     - Event knowledge time remains `2026-10-02 00:00`.
   - Extension by candles 7..9 does not shift, modify, or delete historical Pair 1.
