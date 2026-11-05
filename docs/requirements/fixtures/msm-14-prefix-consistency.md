# Fixture MSM-14: Deterministic Replay / Prefix Consistency with Knowledge Times

- **Source Section**: `Market Structure Marking.docx` Section 1.2, OPEN-08, OPEN-09 (Deterministic Execution)
- **Starting Input**: Index 0, Direction = `UPWARD`
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-14`)

## Full 10-Candle Dataset

Timestamps represent candle open times. Event availability/knowledge time occurs at candle close (for H4: 4 hours after open).

| Index | Open Timestamp (UTC) | Close / Availability (UTC) | Open | High | Low | Close | Role / Color |
|---|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 2026-10-01 04:00 | 100.0 | 102.0 | 99.0 | 101.0 | Start candle |
| 1 | 2026-10-01 04:00 | 2026-10-01 08:00 | 101.0 | 106.0 | 100.5 | 105.0 | Green |
| 2 | 2026-10-01 08:00 | 2026-10-01 12:00 | 105.0 | 108.0 | 104.0 | 107.0 | Swing peak (UB = 107.0) |
| 3 | 2026-10-01 12:00 | 2026-10-01 16:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1, Low = 103.0) |
| 4 | 2026-10-01 16:00 | 2026-10-01 20:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2, Close = 102.0 < 103.0) |
| 5 | 2026-10-01 20:00 | 2026-10-02 00:00 | 102.0 | 105.0 | 101.0 | 103.5 | Green (Inside range) |
| 6 | 2026-10-02 00:00 | 2026-10-02 04:00 | 103.5 | 110.0 | 103.0 | 109.0 | Green (Break of 107.0) |
| 7 | 2026-10-02 04:00 | 2026-10-02 08:00 | 109.0 | 112.0 | 108.0 | 111.0 | Green (UB = 111.0) |
| 8 | 2026-10-02 08:00 | 1026-10-02 12:00 | 111.0 | 111.5 | 106.0 | 107.0 | Red (Pullback 2-A, Low = 106.0, UB = 111.0) |
| 9 | 2026-10-02 12:00 | 2026-10-02 16:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 2-B, Close = 104.0 < 106.0) |

---

## Prefix Consistency & Knowledge Time Semantics

A candle's open timestamp must never be conflated with the event availability time when its completion, pullback, or break becomes known.

1. **Prefix 0..4 (Evaluated upon Index 4 completion at Knowledge Time `2026-10-01 20:00 UTC`)**:
   - Completed candles available: 0 through 4.
   - Observable state: Pullback `(3, 4)` identified upon bar 4 close (`20:00 UTC`).
   - Tentative High search range: `[0, 2]`. Max body edge: candle 2 (`107.0`).
   - Tentative High marked: `price = 107.0, candle_index = 2, source_open_time = 2026-10-01 08:00, identified_at_knowledge_time = 2026-10-01 20:00 UTC`.
   - Confirmed pairs count: 0.
   - Engine state: `WAITING_FOR_BREAK`.

2. **Prefix 0..6 (Evaluated upon Index 6 completion at Knowledge Time `2026-10-02 04:00 UTC`)**:
   - Completed candles available: 0 through 6.
   - Candle 6 closes at 109.0 (> 107.0), triggering confirmation at `2026-10-02 04:00 UTC`.
   - Confirmed Low search range: `[2, 6]`. Lowest LB is tied between indices 4 and 5 at 102.0. Latest-candle tie-breaker selects candle 5.
   - Confirmed Pair 1 recorded:
     - High: `price = 107.0, candle_index = 2, source_open_time = 2026-10-01 08:00, confirmed_at_knowledge_time = 2026-10-02 04:00 UTC`.
     - Low: `price = 102.0, candle_index = 5, source_open_time = 2026-10-01 20:00, confirmed_at_knowledge_time = 2026-10-02 04:00 UTC`.
   - Confirmed pairs count: 1.
   - Next search start index: `5`.
   - Next candidate pullback search begins strictly after break candle (`p1 > 6`).
   - Engine state: `SEARCHING_PULLBACK`.

3. **Full Dataset Prefix 0..9 (Evaluated upon Index 9 completion at Knowledge Time `2026-10-02 16:00 UTC`)**:
   - Completed candles available: 0 through 9.
   - **Historical Invariance**: Confirmed Pair 1 remains strictly identical to prefix 0..6:
     - Confirmed High at candle 2 (`2026-10-01 08:00 UTC`, price 107.0).
     - Confirmed Low at candle 5 (`2026-10-01 20:00 UTC`, price 102.0).
     - Confirmed knowledge time remains `2026-10-02 04:00 UTC`.
   - **Cycle 2 Pullback Identification**:
     - Candles 8 and 9 form the next valid red pullback (`close[9] = 104.0 < low[8] = 106.0`).
     - Pullback identified upon bar 9 completion at `2026-10-02 16:00 UTC`.
     - Search window for second tentative high: `[search_start = 5, p1 - 1 = 7]`.
     - In `[5, 7]`: Candle 5 (`UB = 103.5`), Candle 6 (`UB = 109.0`), Candle 7 (`UB = 111.0`).
     - Highest UB in `[5, 7]` is `111.0` at index `7`.
     - *(Note on tie-breaker rule: If search range strictly excludes both pullback candles [5, 7], max UB is 111.0 at index 7. If index 8 were included [5, 8], both 7 and 8 tie at UB=111.0, selecting latest index 8).*
     - Second Tentative High marked: `price = 111.0, identified_at_knowledge_time = 2026-10-02 16:00 UTC`.
   - Confirmed pairs count remains 1 (waiting for break of 111.0).
   - Engine state: `WAITING_FOR_BREAK`.
   - Data extension does not mutate, retroactively shift, or recalculate prior confirmed swing levels.
