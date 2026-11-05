# Market Structure Marking (MSM) — Engine API & Specification

Last Updated: 2026-11-05 (Milestone: Offline MSM Engine Baseline)

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

## 2. Public API Architecture

Located under `src/aladeen/strategy/`:

```
src/aladeen/strategy/
├── __init__.py       # Public package exports
├── types.py          # Value objects, enums, immutable dataclasses
├── validator.py      # Input adaptation & starting-candle validation
└── engine.py         # Deterministic sequential state machine
```

### 2.1 Core Types & Value Objects (`types.py`)

- **`Direction`** (`Enum`): `UPWARD`, `DOWNWARD`.
- **`EngineState`** (`Enum`): `SEARCHING_PULLBACK`, `WAITING_FOR_BREAK`.
- **`CandleColor`** (`Enum`): `GREEN` (`close > open`), `RED` (`close < open`), `FLAT` (`close == open`).
- **`TrendStatus`** (`Enum`): Display-only diagnostic strings (`"Marking upward structure"`, `"Marking downward structure"`, `"Upward trend"`, `"Downward trend"`, `"Trend not confirmed"`).
- **`StrategyCandle`** (`@dataclass(frozen=True)`):
  - `index`: `int`
  - `open_time`: `datetime` (UTC)
  - `open`, `high`, `low`, `close`: `float` (finite positive numbers)
  - `close_time`: `Optional[datetime]` (UTC availability/close timestamp)
  - `is_forming`: `bool`
  - `bar_status`: `str`
  - `upper_body_edge`: `max(open, close)`
  - `lower_body_edge`: `min(open, close)`
  - `color`: `CandleColor`
- **`SwingPoint`** (`@dataclass(frozen=True)`):
  - `price`: `float`
  - `candle_index`: `int`
  - `candle_open_time`: `datetime`
  - `event_bar_index`: `int` (bar index upon which this point was identified/confirmed)
  - `event_time`: `Optional[datetime]` (knowledge/availability time)
- **`ConfirmedPair`** (`@dataclass(frozen=True)`):
  - `pair_index`: `int`
  - `high`: `SwingPoint`
  - `low`: `SwingPoint`
  - `confirmation_bar_index`: `int`
  - `confirmation_time`: `Optional[datetime]`
- **`MSMConfig`** (`@dataclass(frozen=True)`):
  - `start_candle_time`: `datetime` (UTC)
  - `direction`: `Direction`
- **`MSMSnapshot`** (`@dataclass(frozen=True)`):
  - `state`: `EngineState`
  - `direction`: `Direction`
  - `search_start_index`: `int`
  - `tentative_point`: `Optional[SwingPoint]`
  - `confirmed_pairs`: `Tuple[ConfirmedPair, ...]`
  - `trend_status`: `str`
  - `last_processed_index`: `int`
  - `last_support`: `Optional[SwingPoint]`
  - `last_resistance`: `Optional[SwingPoint]`
  - `next_eligible_pullback_index`: `int`

---

### 2.2 Engine Interface (`engine.py`)

```python
class MSMEngine:
    def __init__(self, config: MSMConfig) -> None: ...
    def reset(self) -> None: ...
    def process_candle(self, candle: StrategyCandle) -> MSMSnapshot: ...
    def process_candles(self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> MSMSnapshot: ...
    def replay(self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> List[MSMSnapshot]: ...
    def get_snapshot(self) -> MSMSnapshot: ...
```

- **Clean Run Identity**: `reset()` or re-initialization creates an isolated engine run with zero prior state contamination.
- **Batch / Sequential Parity**: `process_candles` yields the identical final state as sequential `process_candle` calls or `replay()[-1]`.

---

## 3. Event & Timestamp Semantics

To prevent temporal lookahead and data leakage, three distinct temporal concepts are strictly separated:

1. **Source Candle Open Timestamp** (`candle_open_time`):
   - The opening timestamp of the historical candle containing the swing body edge.
2. **Identification / Confirmation Bar Index** (`event_bar_index` / `confirmation_bar_index`):
   - The exact bar index whose completion triggered the state transition (pullback identified or break confirmed).
3. **Event Knowledge / Availability Time** (`event_time` / `confirmation_time`):
   - The timestamp when the event became knowable. For completed historical candles, this corresponds to the candle close/availability time (`close_time`), strictly after the candle open time.
   - A candle's open timestamp is **never** used as its closing-event knowledge time.
   - For offline test fixtures, explicit synthetic close times are supported. Live broker close boundaries are not inferred locally.

---

## 4. Input & Completion Requirements

- **Completed Bars Only**: Forming bars (`is_forming == True` or `bar_status != "CONFIRMED_COMPLETED"`) are strictly excluded from state machine transitions. Ingesting a forming bar returns the current completed state without mutation.
- **Start Candle Validation (OPEN-08)**:
  - Starting candle must exist in the dataset.
  - Starting candle must be a verified completed bar.
  - If absent or forming, raises `ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")`.
- **Sequential Ingestion Integrity**:
  - Sequential ingestion requires strictly increasing timestamps. Out-of-order or duplicate candles raise `ValueError`.

---

## 5. Reconciled Strategy Rules Implemented

1. **2-Candle Pullback**:
   - Upward: Two consecutive red candles with `close[p2] < low[p1]` (strict inequality).
   - Downward: Two consecutive green candles with `close[p2] > high[p1]` (strict inequality).
   - Flat candle (`open == close`) strictly interrupts consecutive color sequence.
2. **Tentative Search Bounds**:
   - `[search_start_index, p1 - 1]`. Inclusive of `search_start_index`, strictly exclusive of both pullback candles `p1` and `p2`.
3. **Empty-Range Skip**:
   - If `p1 == search_start_index`, search range is empty. Skip pullback `(p1, p2)`, retain `search_start_index` unchanged, and continue scan.
4. **Waiting-State Lockout**:
   - While in `WAITING_FOR_BREAK`, no subsequent pullbacks are marked or evaluated.
5. **Closing Break**:
   - Candidate candle `k > p2`.
   - Upward: `close[k] > tentative_high.price` (strict inequality).
   - Downward: `close[k] < tentative_low.price` (strict inequality).
   - Break candle color does not matter (green, red, or flat).
6. **Confirmed Opposite Extreme Search**:
   - Window: `[tentative_point.candle_index, k]` (inclusive of both endpoints: from tentative extreme candle through the break candle `k`).
   - Upward: Lowest lower body edge in window.
   - Downward: Highest upper body edge in window.
7. **Latest-Candle Tie-Breaker**:
   - Exact price equality on body edges selects the candle with the highest index (latest timestamp).
8. **Advance & Post-Break Candidate Restriction**:
   - Search start advances to confirmed opposite extreme candle index.
   - Next candidate pullback candle `p1` must be strictly after the break candle: `p1 > k` (break candle cannot be reused as a pullback candle).
9. **Trend Status (OPEN-01)**:
   - Diagnostic only; zero authority over engine direction.
   - `< 2 pairs`: `"Marking upward structure"` or `"Marking downward structure"`.
   - `≥ 2 pairs`:
     - Upward trend: `H_curr > H_prev` AND `L_curr > L_prev`.
     - Downward trend: `H_curr < H_prev` AND `L_curr < L_prev`.
     - Else (including equality): `"Trend not confirmed"`.
10. **Replay & Prefix Immutability (OPEN-09)**:
    - Prior confirmed pairs and their historical timestamps never shift, delete, or recalculate when dataset is extended.

---

## 6. Current Limitations & Scope Boundaries

- **No CHOCH Integration**: The MSM engine operates solely in its initialized direction. CHOCH handling, reversal qualification, and multi-timeframe activation belong to separate subsequent modules.
- **Offline Only**: No connection to live MT5 terminals or Dash dashboard callbacks in this milestone.
