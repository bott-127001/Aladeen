# Market Structure Marking (MSM) — Acceptance Specification

Last Updated: 2026-11-05

> [!IMPORTANT]
> **Specification Authority**:
> Derived from original strategy authority `TopG.pdf` (pages 1–8), `Market Structure Marking.docx` (transcribed at [`market-structure-marking.md`](file:///docs/strategy/extracted/market-structure-marking.md)), and approved clarifications [`approved-clarifications.md`](file:///docs/requirements/approved-clarifications.md) (EMPTY RANGE, OPEN-01, OPEN-08, OPEN-10).
> This document specifies verifiable acceptance criteria, explicit OHLC test fixtures, and mathematical boundary semantics for the MSM engine. No strategy logic is implemented in this specification.

---

## 1. Engine Configuration & Validation

### 1.1 Inputs
- **`candle_data`**: A validated DataFrame complying with the shared Candle Data Contract:
  - Strictly monotonic DatetimeIndex normalized to UTC.
  - Finite positive numeric OHLC columns (`open`, `high`, `low`, `close`).
  - Explicit bar completion flags (`is_forming`, `is_latest_bar`, `bar_status`).
- **`start_candle_time`**: Timestamp of the user-selected starting candle.
- **`direction`**: Initial marking direction (`UPWARD` or `DOWNWARD`).

### 1.2 Start Candle Validation
- **Completed Bars Only**: The selected `start_candle_time` must exist in `candle_data` and have `is_forming == False` (and `bar_status == CONFIRMED_COMPLETED`).
- **Forming Bar Rejection (OPEN-08)**: If `start_candle_time` corresponds to a currently forming or unconfirmed bar, or is not found in the index, initialization must raise `ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")`.
- **Clean Run Identity (OPEN-08)**: Editing or changing the starting candle creates a fresh calculation run with zero state inheritance or prior signal contamination.

---

## 2. Candle Geometry, Measurements & Strict Logic

### 2.1 Body Edges vs. Wick Extremes
- **Upper Body Edge**: `UB(i) = max(open[i], close[i])`
- **Lower Body Edge**: `LB(i) = min(open[i], close[i])`
- **Top Wick Tip**: `high[i]`
- **Bottom Wick Tip**: `low[i]`

All tentative and confirmed high/low swing levels record and compare **body edges**, never wick tips.
Wick extremes are used exclusively in the 2-candle pullback comparison.

### 2.2 Candle Color Definitions
- **Green (Bullish)**: `close[i] > open[i]`
- **Red (Bearish)**: `close[i] < open[i]`
- **Flat (Neutral)**: `close[i] == open[i]`

A flat candle is neither red nor green. A flat candle strictly interrupts a consecutive color sequence. However, flat candles remain fully eligible for body-edge extreme searches and closing breaks.

### 2.3 Strict Inequality Principle
In all strategy comparisons, equality never satisfies:
- Strict pullback break: `close[2] < low[1]` (for red) or `close[2] > high[1]` (for green). An exact touch (`close[2] == low[1]`) is a failure.
- Strict closing break: `close[break] > tentative_high` (for upward) or `close[break] < tentative_low` (for downward). An exact touch (`close == level`) is a failure.

### 2.4 Latest Candle Tie-Breaker
When multiple candles in an eligible search window share the exact same extreme body-edge price, the engine must select the candle with the **highest index (latest timestamp)**.

---

## 3. Core State Machine & Search Ranges

The engine operates as a deterministic, sequential state machine over completed historical candles:

```
[Search: Pullback] ──(Valid 2-candle pullback)──► [Tentative Point Marked]
       ▲                                                    │
       │                                         (Strict closing break)
       │                                                    ▼
[Advance Search Start] ◄──(Record Confirmed Pair)────── [Confirmed Pair]
```

### 3.1 Upward Marking Algorithm

#### Phase A: Pullback Detection
1. Begin scanning forward from `search_start_idx`.
2. A valid pullback requires two consecutive red candles `(p1, p2)` such that:
   - `close[p1] < open[p1]`
   - `close[p2] < open[p2]`
   - `close[p2] < low[p1]` (strict closing break of p1's bottom wick tip)
3. If `p1` and `p2` fail, advance candidate window by one bar (test `p2, p3`).

#### Phase B: Tentative High Search & Empty-Range Handling
1. Search window for tentative high: `[search_start_idx, p1 - 1]`.
   - **Inclusive** of `search_start_idx`.
   - **Strictly exclusive** of both pullback candles (`p1` and `p2`).
2. **Empty-Range Rule (Reconciled from Section 7 & approved clarifications)**:
   - If `search_start_idx == p1`, the search range is empty (0 eligible candles).
   - The engine **skips** this pullback pair `(p1, p2)`.
   - The engine retains `search_start_idx` unchanged and continues scanning forward for the next valid pullback pair.
3. For a non-empty range, tentative high price is `max(UB(i))` for `i in [search_start_idx, p1 - 1]`.
   - If tied, choose the latest candle.
   - Record `tentative_high = {price: UB(idx), candle_idx: idx, time: time[idx]}`.

#### Phase C: Waiting for Closing Break
1. Scan candles `k > p2` for a candle that closes strictly above the tentative high: `close[k] > tentative_high.price`.
2. Neither pullback candle (`p1` or `p2`) can serve as the closing break.
3. The break candle `k`'s color does not matter (green, red, or flat).
4. While waiting for a closing break, no subsequent pullbacks are evaluated (no independent overlapping cycles).

#### Phase D: Pair Confirmation & Search-Start Advance
1. On qualifying break candle `k`:
   - `tentative_high` becomes **Confirmed High**.
   - Search window for confirmed low: `[tentative_high.candle_idx, k]`.
     - **Inclusive of both endpoints** (from the high candle through the break candle).
   - Confirmed low price is `min(LB(i))` for `i in [tentative_high.candle_idx, k]`.
     - If tied, choose the latest candle.
   - Record `confirmed_low = {price: LB(idx), candle_idx: idx, time: time[idx]}`.
2. The newly confirmed low becomes **last support**.
3. Advance `search_start_idx` to `confirmed_low.candle_idx`.
4. The next pullback search begins strictly after the closing break candle: candidate `p1 > k`. (The break candle cannot be reused as a pullback candle).

---

### 3.2 Downward Marking Algorithm (Mirror)

#### Phase A: Pullback Detection
1. Scanning forward from `search_start_idx`.
2. Requires two consecutive green candles `(p1, p2)` such that:
   - `close[p1] > open[p1]`
   - `close[p2] > open[p2]`
   - `close[p2] > high[p1]` (strict closing break of p1's top wick tip)

#### Phase B: Tentative Low Search & Empty-Range Handling
1. Search window for tentative low: `[search_start_idx, p1 - 1]`.
   - Inclusive of `search_start_idx`, strictly exclusive of `p1` and `p2`.
2. If `search_start_idx == p1`, range is empty: skip pair, retain `search_start_idx`, continue scan.
3. Tentative low price is `min(LB(i))` for `i in [search_start_idx, p1 - 1]`. Latest candle if tied.

#### Phase C: Waiting for Closing Break
1. Scan candles `k > p2` for `close[k] < tentative_low.price`.

#### Phase D: Pair Confirmation & Search-Start Advance
1. On qualifying break candle `k`:
   - `tentative_low` becomes **Confirmed Low**.
   - Confirmed high search window: `[tentative_low.candle_idx, k]` (inclusive of both endpoints).
   - Confirmed high price is `max(UB(i))` for `i in [tentative_low.candle_idx, k]`. Latest candle if tied.
2. Newly confirmed high becomes **last resistance**.
3. Advance `search_start_idx` to `confirmed_high.candle_idx`.
4. Next pullback search begins strictly after the break candle (`p1 > k`).

---

## 4. Trend Status Specification (OPEN-01)

Per approved clarification OPEN-01, Trend Status is purely diagnostic/display-only. It has zero authority over engine direction.

- **Initial State (< 2 confirmed pairs)**:
  - If direction is UPWARD: `"Marking upward structure"`
  - If direction is DOWNWARD: `"Marking downward structure"`
- **Evaluation (≥ 2 confirmed pairs)**:
  Let `(H_prev, L_prev)` be pair N-1, and `(H_curr, L_curr)` be pair N:
  - **Upward Trend**: `H_curr.price > H_prev.price` AND `L_curr.price > L_prev.price`.
  - **Downward Trend**: `H_curr.price < H_prev.price` AND `L_curr.price < L_prev.price`.
  - **Trend Not Confirmed**: If either strict inequality fails (including price equality).

---

## 5. Concrete Acceptance Test Fixtures

All fixtures specify deterministic OHLC data with 4-hour candle timestamps in UTC.

### Fixture MSM-01: Upward Standard Cycle (Clean Confirmation)
- **Source Section**: Section 3 (Upward Algorithm)
- **Starting Input**: Index 0, Direction = UPWARD.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 102.0 | 99.0 | 101.0 | Green (Start candle) |
| 1 | 2026-10-01 04:00 | 101.0 | 106.0 | 100.5 | 105.0 | Green (Climbing) |
| 2 | 2026-10-01 08:00 | 105.0 | 108.0 | 104.0 | 107.0 | Green (Swing peak) |
| 3 | 2026-10-01 12:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1, Low=103.0) |
| 4 | 2026-10-01 16:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2, Close=102.0 < 103.0) |
| 5 | 2026-10-01 20:00 | 102.0 | 105.0 | 101.0 | 103.5 | Green (Inside range) |
| 6 | 2026-10-02 00:00 | 103.5 | 110.0 | 103.0 | 109.0 | Green (Closing break: Close=109 > 107) |

- **Expected Observable Results**:
  1. Valid pullback identified at candles `(3, 4)`.
  2. Tentative high search range: `[0, 2]`. Highest upper body edge is candle 2 (`UB = max(105, 107) = 107.0`). Tentative High = 107.0 at index 2.
  3. Candle 6 closes at 109.0 (> 107.0), triggering confirmation.
  4. Confirmed high = 107.0 at index 2.
  5. Confirmed low search range: `[2, 6]`. Lowest lower body edge is candle 4 (`LB = min(104, 102) = 102.0`) vs candle 5 (`LB = min(102, 103.5) = 102.0`). Tied at 102.0! Latest candle tie-breaker selects candle 5.
  6. Confirmed low = 102.0 at index 5 (Last Support).
  7. Next search start candle index = 5. Pullback search begins at index > 6.

---

### Fixture MSM-02: Downward Standard Cycle (Clean Confirmation)
- **Source Section**: Section 4 (Downward Algorithm)
- **Starting Input**: Index 0, Direction = DOWNWARD.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 200.0 | 201.0 | 198.0 | 199.0 | Red (Start candle) |
| 1 | 2026-10-01 04:00 | 199.0 | 199.5 | 194.0 | 195.0 | Red (Falling) |
| 2 | 2026-10-01 08:00 | 195.0 | 196.0 | 191.0 | 192.0 | Red (Swing trough) |
| 3 | 2026-10-01 12:00 | 192.0 | 196.0 | 191.5 | 195.0 | Green (Pullback 1, High=196.0) |
| 4 | 2026-10-01 16:00 | 195.0 | 198.0 | 194.5 | 197.0 | Green (Pullback 2, Close=197.0 > 196.0) |
| 5 | 2026-10-01 20:00 | 197.0 | 197.5 | 193.0 | 194.0 | Red (Inside range) |
| 6 | 2026-10-02 00:00 | 194.0 | 194.5 | 189.0 | 190.0 | Red (Closing break: Close=190 < 192) |

- **Expected Observable Results**:
  1. Valid green pullback at `(3, 4)`.
  2. Tentative low search range: `[0, 2]`. Lowest lower body edge is candle 2 (`LB = min(195, 192) = 192.0`). Tentative Low = 192.0 at index 2.
  3. Candle 6 closes at 190.0 (< 192.0), confirming the pair.
  4. Confirmed low = 192.0 at index 2.
  5. Confirmed high search range: `[2, 6]`. Highest upper body edge is candle 4 (`UB = max(195, 197) = 197.0`).
  6. Confirmed high = 197.0 at index 4 (Last Resistance).
  7. Next search start candle index = 4. Pullback search begins at index > 6.

---

### Fixture MSM-03: Strict Equality Failures
- **Source Section**: Section 2 (Strict Comparison Rule)
- **Starting Input**: Index 0, Direction = UPWARD.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 104.0 | Green (Start) |
| 1 | 2026-10-01 04:00 | 104.0 | 104.5 | 101.0 | 102.0 | Red (Pullback 1, Low = 101.0) |
| 2 | 2026-10-01 08:00 | 102.0 | 102.5 | 100.0 | 101.0 | Red (Pullback 2, Close = 101.0 == Low_1) |
| 3 | 2026-10-01 12:00 | 101.0 | 103.0 | 100.0 | 100.5 | Red (Pullback candidate with 2) |
| 4 | 2026-10-01 16:00 | 100.5 | 101.0 | 98.0 | 99.0 | Red (Valid pullback pair with 3) |
| 5 | 2026-10-01 20:00 | 99.0 | 104.5 | 99.0 | 104.0 | Green (Close = 104.0 == Tentative High) |

- **Expected Observable Results**:
  1. Candles `(1, 2)`: `close[2] = 101.0` is exactly equal to `low[1] = 101.0`. Strict inequality fails (`101.0 < 101.0` is False). Pullback rejected!
  2. Candidate shifts: `(2, 3)` tested: `low[2] = 100.0`, `close[3] = 100.5 > 100.0`. Pullback rejected.
  3. Candidate shifts: `(3, 4)` tested: `low[3] = 100.0`, `close[4] = 99.0 < 100.0`. Pullback accepted!
  4. Tentative high search range: `[0, 2]`. Max body edge is candle 0 (`UB = 104.0`). Tentative high = 104.0 at index 0.
  5. Candle 5 closes at 104.0. Strict closing break requires `close > 104.0`. `104.0 > 104.0` is False! Candle 5 does NOT trigger confirmation. State remains Waiting for Break.

---

### Fixture MSM-04: Flat Candle Interruption
- **Source Section**: Section 2 (Flat Candle Rules)
- **Starting Input**: Index 0, Direction = UPWARD.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 104.0 | Green (Start) |
| 1 | 2026-10-01 04:00 | 104.0 | 104.5 | 101.0 | 102.0 | Red (Candle 1) |
| 2 | 2026-10-01 08:00 | 102.0 | 103.0 | 101.0 | 102.0 | Flat (Open == Close == 102.0) |
| 3 | 2026-10-01 12:00 | 102.0 | 102.5 | 99.0 | 100.0 | Red (Candle 3) |

- **Expected Observable Results**:
  1. Candle 2 is flat (`open == close`). It is neither red nor green.
  2. The candidate pair `(1, 2)` is rejected because candle 2 is not red.
  3. The candidate pair `(2, 3)` is rejected because candle 2 is not red.
  4. Pullback count remains 0; search continues forward.

---

### Fixture MSM-05: Empty-Range Skip (Reconciled Clarification)
- **Source Section**: Section 7 & `approved-clarifications.md` (EMPTY RANGE)
- **Starting Input**: Index 0, Direction = UPWARD.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red (Start candle is itself red!) |
| 1 | 2026-10-01 04:00 | 103.0 | 103.5 | 100.0 | 101.0 | Red (Close 101.0 < Low_0 102.0) |
| 2 | 2026-10-01 08:00 | 101.0 | 106.0 | 100.5 | 105.0 | Green (Climbing) |
| 3 | 2026-10-01 12:00 | 105.0 | 108.0 | 104.0 | 107.0 | Green |
| 4 | 2026-10-01 16:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1) |
| 5 | 2026-10-01 20:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2, Close < Low_4) |
| 6 | 2026-10-02 00:00 | 102.0 | 110.0 | 102.0 | 109.0 | Green (Break of tentative high) |

- **Expected Observable Results**:
  1. Candles `(0, 1)` form a valid pullback pair (`close[1] < low[0]`).
  2. Tentative search window would be `[search_start, p1 - 1] = [0, -1]`, which is empty!
  3. **Empty-Range Rule Applied**: Skip pullback pair `(0, 1)`. Retain `search_start = 0`.
  4. Continue scan: next valid pullback found at `(4, 5)`.
  5. Search window for tentative high is `[0, 3]`. Highest body edge is candle 3 (`UB = 107.0`).
  6. Tentative high = 107.0 at index 3.
  7. Candle 6 closes at 109.0 (> 107.0), confirming high at index 3 and low at index 5.

---

### Fixture MSM-06: Waiting-State Lockout (No Overlapping Tentative Points)
- **Source Section**: Section 3 (Step 5: "Do not start another independent cycle while waiting")
- **Starting Input**: Index 0, Direction = UPWARD.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 108.0 | 99.0 | 107.0 | Green (Start & Peak UB=107) |
| 1 | 2026-10-01 04:00 | 107.0 | 107.5 | 103.0 | 104.0 | Red (Pullback 1) |
| 2 | 2026-10-01 08:00 | 104.0 | 104.5 | 101.5 | 102.0 | Red (Pullback 2 -> Tentative High = 107) |
| 3 | 2026-10-01 12:00 | 102.0 | 106.0 | 101.5 | 105.0 | Green |
| 4 | 2026-10-01 16:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red (Secondary Pullback 1) |
| 5 | 2026-10-01 20:00 | 103.0 | 103.5 | 100.0 | 101.0 | Red (Secondary Pullback 2) |
| 6 | 2026-10-02 00:00 | 101.0 | 110.0 | 101.0 | 109.0 | Green (Closes > 107) |

- **Expected Observable Results**:
  1. Pullback `(1, 2)` establishes tentative high = 107.0 at index 0.
  2. While waiting for a close > 107.0, candles `(4, 5)` form another red pullback.
  3. The engine **must ignore** the pullback at `(4, 5)`. It does NOT mark a new tentative high or overwrite the active tentative high.
  4. Candle 6 breaks 107.0, confirming the original tentative high at index 0 and confirmed low at index 5.

---

### Fixture MSM-07: Completed Candles Only & Forming Bar Exclusion
- **Source Section**: Section 1 (Completed Candles Only)
- **Starting Input**: Index 0, Direction = UPWARD.
- Candle 4 has `is_forming = True`.

| Index | Timestamp (UTC) | Open | High | Low | Close | Color / Role | is_forming |
|---|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 100.0 | 105.0 | 99.0 | 104.0 | Green | False |
| 1 | 2026-10-01 04:00 | 104.0 | 106.0 | 103.0 | 105.0 | Green | False |
| 2 | 2026-10-01 08:00 | 105.0 | 105.5 | 102.0 | 103.0 | Red | False |
| 3 | 2026-10-01 12:00 | 103.0 | 103.5 | 100.0 | 101.0 | Red | False |
| 4 | 2026-10-01 16:00 | 101.0 | 110.0 | 101.0 | 108.0 | Green | **True** (Latest bar) |

- **Expected Observable Results**:
  1. Candles 0–3 are completed. Pullback `(2, 3)` is completed, creating tentative high = 105.0 at index 1.
  2. Candle 4 has `close = 108.0 > 105.0`, but has `is_forming == True`.
  3. The engine **must not** confirm the high on candle 4. The tentative high remains unconfirmed until candle 4 is completed in a subsequent fetch.

---

### Fixture MSM-08: Deterministic Replay / Prefix Consistency
- **Source Section**: OPEN-08 & OPEN-09 (Deterministic Execution)
- **Requirement**:
  Given a dataset of N completed candles producing confirmed levels `L_1, ..., L_m`, processing an extended dataset of N + K completed candles must yield the exact same confirmed levels `L_1, ..., L_m` for the initial N candles. Historical confirmed swing points and their timestamps are strictly immutable.

---

## 6. Consequential Interpretations & Open Inquiries

All core rules of Market Structure Marking are formally reconciled and verified:
1. Empty-range edge case: **Reconciled** (skip pullback, retain start reference).
2. Trend status: **Reconciled** (display-only, separate from engine direction).
3. Equal values: **Reconciled** (latest candle for body-edge ties; strict comparison fails equality).
4. Flat candles: **Reconciled** (interrupts color run; eligible for searches and breaks).

There are no remaining unresolved ambiguities in the MSM module specification.
