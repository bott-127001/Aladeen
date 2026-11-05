# Market Structure Marking (MSM) — Acceptance Specification

Last Updated: 2026-11-05

> [!IMPORTANT]
> **Specification Authority**:
> Derived from original strategy document `Market Structure Marking.docx` (transcribed at [`docs/strategy/extracted/market-structure-marking.md`](../strategy/extracted/market-structure-marking.md)), which references `TopG.pdf` (pages 1–8) as stated ancestry, and approved clarifications [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (EMPTY RANGE, OPEN-01, OPEN-08, OPEN-10).
> This document specifies verifiable acceptance criteria, explicit OHLC test fixtures, and mathematical boundary semantics for the MSM engine. No strategy logic or execution engine is implemented in this specification.

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
   - If tied, choose the latest candle (highest index).
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
     - If tied, choose the latest candle (highest index).
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
4. Record `tentative_low = {price: LB(idx), candle_idx: idx, time: time[idx]}`.

#### Phase C: Waiting for Closing Break
1. Scan candles `k > p2` for `close[k] < tentative_low.price`.
2. Break candle `k`'s color does not matter (green, red, or flat).
3. No subsequent pullbacks evaluated while waiting.

#### Phase D: Pair Confirmation & Search-Start Advance
1. On qualifying break candle `k`:
   - `tentative_low` becomes **Confirmed Low**.
   - Confirmed high search window: `[tentative_low.candle_idx, k]` (inclusive of both endpoints).
   - Confirmed high price is `max(UB(i))` for `i in [tentative_low.candle_idx, k]`. Latest candle if tied.
   - Record `confirmed_high = {price: UB(idx), candle_idx: idx, time: time[idx]}`.
2. Newly confirmed high becomes **last resistance**.
3. Advance `search_start_idx` to `confirmed_high.candle_idx`.
4. Next pullback search begins strictly after the break candle: candidate `p1 > k`.

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

## 5. Acceptance Test Fixtures Index

To ensure exhaustive reviewability without truncation, each fixture is fully documented in its own dedicated specification file with complete OHLC tables, enumerated search ranges, body-edge calculations, and latest-candle tie-breaker resolutions.

All acceptance data is independently machine-readable and verifiable in [`tests/fixtures/msm_acceptance.json`](../../tests/fixtures/msm_acceptance.json).

| Fixture ID | Title & Focus | Direction | Dedicated File | Machine Target |
|---|---|---|---|---|
| **MSM-01** | Upward Standard Cycle (Clean Confirmation & Confirmed Low Tie) | UPWARD | [`fixtures/msm-01-upward-standard.md`](fixtures/msm-01-upward-standard.md) | `MSM-01` |
| **MSM-02** | Downward Standard Cycle (Clean Confirmation & Confirmed High Tie) | DOWNWARD | [`fixtures/msm-02-downward-standard.md`](fixtures/msm-02-downward-standard.md) | `MSM-02` |
| **MSM-03** | Strict Equality Failures (Pullback & Break Equality Rejections) | UPWARD | [`fixtures/msm-03-strict-equality.md`](fixtures/msm-03-strict-equality.md) | `MSM-03` |
| **MSM-04** | Flat Candle Interruption (Consecutive Color Sequence Break) | UPWARD | [`fixtures/msm-04-flat-candle.md`](fixtures/msm-04-flat-candle.md) | `MSM-04` |
| **MSM-05** | Empty-Range Skip (Reconciled Clarification: Skip & Retain Start) | UPWARD | [`fixtures/msm-05-empty-range.md`](fixtures/msm-05-empty-range.md) | `MSM-05` |
| **MSM-06** | Waiting-State Lockout (No Overlapping Cycles While Awaiting Break) | UPWARD | [`fixtures/msm-06-waiting-lockout.md`](fixtures/msm-06-waiting-lockout.md) | `MSM-06` |
| **MSM-07** | Completed Candles Only & Forming Bar Exclusion | UPWARD | [`fixtures/msm-07-forming-bar.md`](fixtures/msm-07-forming-bar.md) | `MSM-07` |
| **MSM-08** | Tied Extremes in Both Directions (Bullish Tie & Bearish Tie) | BOTH | [`fixtures/msm-08-tied-extremes.md`](fixtures/msm-08-tied-extremes.md) | `MSM-08A`, `MSM-08B` |
| **MSM-09** | Downward Equality Failures (Green Pullback & Break Failures) | DOWNWARD | [`fixtures/msm-09-downward-equality.md`](fixtures/msm-09-downward-equality.md) | `MSM-09` |
| **MSM-10** | Flat Candle Winning Extreme Search (Highest Body Edge) | UPWARD | [`fixtures/msm-10-flat-winning-extreme.md`](fixtures/msm-10-flat-winning-extreme.md) | `MSM-10` |
| **MSM-11** | Non-Color Breaks (Red Upward Break & Green Downward Break) | BOTH | [`fixtures/msm-11-non-color-breaks.md`](fixtures/msm-11-non-color-breaks.md) | `MSM-11A`, `MSM-11B` |
| **MSM-12** | Two Completed Pairs, Post-Break Rule (`p1 > k`) & Trend Status | UPWARD | [`fixtures/msm-12-two-pairs-trend.md`](fixtures/msm-12-two-pairs-trend.md) | `MSM-12` |
| **MSM-13** | Validation Rejections (Missing Start Candle & Forming Start Candle) | UPWARD | [`fixtures/msm-13-validation-rejections.md`](fixtures/msm-13-validation-rejections.md) | `MSM-13A`, `MSM-13B` |
| **MSM-14** | Deterministic Replay / Prefix Consistency with Knowledge Times | UPWARD | [`fixtures/msm-14-prefix-consistency.md`](fixtures/msm-14-prefix-consistency.md) | `MSM-14` |

---

## 6. Consequential Interpretations & Reconciled Scope

All core rules of Market Structure Marking are formally reconciled and verified:
1. Empty-range edge case: **Reconciled** (skip pullback, retain search start reference).
2. Trend status: **Reconciled** (display-only, separate from engine direction).
3. Equal values: **Reconciled** (latest candle for body-edge ties; strict comparison fails equality).
4. Flat candles: **Reconciled** (interrupts consecutive color sequence; eligible for searches and breaks).
5. Post-break candidate restriction: **Reconciled** (candidate `p1` must occur strictly after the closing break candle).
6. Non-green/non-red breaks: **Reconciled** (break candle color does not matter).
7. Deterministic prefix immutability: **Reconciled** (historical confirmed levels immutable across prefix expansions, with explicit distinction between candle time and event knowledge time).

There are no remaining unresolved ambiguities in the MSM module specification.
