# Market Structure Marking (MSM) — Engine API & Specification

Last Updated: 2026-11-05 (Milestone: Offline MSM Engine Baseline — Hardened)

---

## 1. Scope & Isolation Boundary

The `aladeen.strategy` package provides a standalone, deterministic calculation engine for Market Structure Marking.

- **Zero Outside Dependencies**: Strictly independent of MT5, Dash, Plotly, network I/O, and persistent databases.
- **Strictly Read-Only & Pure**: Input DataFrames, lists, and dicts are never mutated; returned state snapshots are immutable.
- **Out of Scope in this Milestone**:
  - No CHOCH (Change of Character) integration.
  - No automatic direction reversal.
  - No order execution or signal generation.
  - No UI or chart overlay integration.

---

## 2. Ingestion & Reset Semantics (R7.3)

The engine provides two clearly separated, distinct execution models:

1. **Batch Execution & Replay (`process_candles`, `replay`)**:
   - **Contract**: Fresh-run operation.
   - Calling `process_candles(data)` or `replay(data)` performs transactional validation on `data` upfront. If all records pass validation, the engine resets to a clean run identity and executes over `data`.
   - Calling `process_candles` twice on the same engine never duplicates internal history.
   - Processing an extended snapshot cleanly recalculates without duplicating prior rows.
   - **Fail-Closed Transactional Boundary**: If any candle in the batch is malformed, an exception is raised immediately and the engine's prior state is untouched.

2. **Incremental Sequential Ingestion (`process_candle`)**:
   - **Contract**: Incremental forward streaming.
   - Strictly enforces that incoming candle timestamps are monotonically increasing (`candle.open_time > last_completed.open_time`).
   - Duplicate or out-of-order candles raise `ValueError`.
   - Forming bars (`is_forming == True`) return the current completed state without mutating internal history.

---

## 3. Index & Provenance Model (R7.1, R7.4)

Internal buffer positions are strictly decoupled from external source candle indices:

- **Internal Positions**:
  - The engine uses 0-based list positions (`_search_start_pos`, `_pullback_scan_pos`, `_next_eligible_pullback_pos`) exclusively for internal sliding window tests and array slicing.
- **Source Candle Indices**:
  - Input candles may have arbitrary, nonzero, or noncontiguous indices (e.g. `100, 110, 120...` or filtered slices).
  - The engine maps buffer positions back to the original source candle index on every generated event.
- **Identification vs. Confirmation Provenance (R7.4)**:
  - Every `SwingPoint` explicitly records both its identification event and confirmation event:
    - `identified_bar_index`: Source index of the bar whose completion established the level as tentative (pullback completion bar `p2`).
    - `identified_time`: Knowledge/availability time when the level was identified.
    - `confirmed_bar_index`: Source index of the break bar `k` that confirmed the level (`None` while tentative).
    - `confirmed_time`: Knowledge/availability time when the level was confirmed (`None` while tentative).
  - Confirmation never overwrites or erases the original tentative identification provenance.

---

## 4. Strict Validation at Every Public Entry Point (R7.2)

Every entry point (`process_candles`, `process_candle`, `replay`) enforces the identical strict boundary:

- **Prices**: Must be real finite positive numbers (`float` or `int`, never `bool`, never strings, never `+inf`/`-inf`/`nan`).
- **OHLC Geometry**: `high >= low`, `high >= max(open, close)`, `low <= min(open, close)`.
- **Timestamps**:
  - `open_time`: Must be a timezone-aware UTC datetime. Naive timestamps and `NaT` are strictly rejected.
  - `close_time` (when supplied): Must be timezone-aware UTC datetime and strictly later than `open_time`.
- **Direction**: Must be an instance of `Direction` enum (`UPWARD` or `DOWNWARD`). Invalid strings or types are rejected before engine state initialization.
- **Completion Evidence**: Explicit and coherent (`is_forming=True` with `bar_status='CONFIRMED_COMPLETED'` is rejected as contradictory).
- **Start Candle Selection (OPEN-08)**: Must exist in dataset and be completed historical bar. Forming or absent start candles raise `ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")`.

---

## 5. Reviewer Correction Recorded (MSM-14 Prefix 0..9)

In MSM-14 prefix 0..9, red pullback `(8, 9)` is identified.
Under the approved strategy rule:
*"find the highest upper body edge from the search-start candle through the candle immediately before the first red candle. Include the search-start candle; exclude both pullback candles."*

- Search window: `[search_start = 5, p1 - 1 = 7]`.
- Upper body edges in `[5, 7]`: Candle 5 (103.5), Candle 6 (109.0), Candle 7 (111.0).
- Selected Tentative High: **Price 111.0 at source index 7** (identified at bar 9).
- Per reviewer correction, index 8 is the first pullback candle (`p1`) and is strictly excluded from the tentative search window.
