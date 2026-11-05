# Change of Character (CHOCH) Engine & Coordinator Specification

Last Updated: 2026-11-05

## 1. Overview & Architectural Responsibilities

The Change of Character (CHOCH) subsystem operates alongside the deterministic Market Structure Marking (MSM) engine to monitor trend failure and coordinate structural direction reversals.

```
                           ┌─────────────────────────┐
                           │   Completed Candles     │
                           └───────────┬─────────────┘
                                       │
                                       ▼
                   ┌───────────────────────────────────────┐
                   │        MSMChochCoordinator            │
                   │                                       │
                   │  ┌──────────────┐   ┌──────────────┐  │
                   │  │  MSMEngine   │   │ChochDetector │  │
                   │  └──────┬───────┘   └──────▲───────┘  │
                   │         │ (Swing Points,   │          │
                   │         │  Last Support/   │          │
                   │         │  Resistance, P3) │          │
                   │         └──────────────────┘          │
                   └───────────────────┬───────────────────┘
                                       │
                     On Confirmed CHOCH (or Unresolved)
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │ 1. Terminate old unfinished MSM cycle                       │
        │ 2. Preserve confirmed MSM history                           │
        │ 3. Build 3 original-candle zones (SBR/RBS, QML, Double Top) │
        │ 4. Invert marking direction                                 │
        │ 5. Restart search_start at Point 3 original candle          │
        │ 6. Enforce post-confirmation pullback scan (p1 >= c2 + 1)   │
        └─────────────────────────────────────────────────────────────┘
```

### Module Responsibilities
- **`ChochDetector` (`src/aladeen/strategy/choch_detector.py`)**:
  Pure mathematical detection unit. Monitors completed candles for two consecutive closing breaks beyond the active confirmed level while tentative Point 3 is active.
- **`MSMChochCoordinator` (`src/aladeen/strategy/coordinator.py`)**:
  Lifecycle orchestrator. Feeds candles sequentially through `MSMEngine` and `ChochDetector`, handles transition resets, builds structural zones, and restarts the MSM state machine in the new direction.
- **`ChochTypes` (`src/aladeen/strategy/choch_types.py`)**:
  Immutable domain types and value objects.

---

## 2. Public API Reference

### Core Classes

#### `MSMChochCoordinator`
The primary entry point for coordinated MSM + CHOCH evaluation.
- `__init__(config: MSMConfig)`: Initializes coordinator with starting candle time and initial direction.
- `process_candles(data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> CoordinatorSnapshot`: Fresh batch execution over a sequence of candles.
- `process_candle(candle: StrategyCandle) -> CoordinatorSnapshot`: Sequential execution for incremental bar delivery.
- `reset() -> None`: Resets coordinator to initial state.
- `get_snapshot() -> CoordinatorSnapshot`: Returns current state snapshot.

#### `ChochDetector`
Standalone detector for CHOCH transitions.
- `__init__(initial_direction: Direction)`: Initializes detector.
- `process_candle(candle, chronological_pos, msm_direction, last_support, last_resistance, tentative_point, candle_lookup, confirmed_high, confirmed_low) -> ChochSnapshot`: Evaluates single candle.
- `reset_for_new_direction(new_direction: Direction) -> None`: Clears candidate state for new direction.

### Immutable Data Types

- **`ChochZone`**:
  ```python
  zone_type: ChochZoneType               # SBR, RBS, QML_A_PLUS, DOUBLE_TOP, DOUBLE_BOTTOM
  lower_price: float
  upper_price: float
  is_line: bool                          # True when lower_price == upper_price (thickness 0)
  source_candle_index: int
  source_candle_open_time: datetime
  ```
- **`ChochCandidate`**:
  ```python
  direction: Direction
  broken_level_price: float
  broken_level_source_index: int
  point_3_source_index: int
  point_3_identified_at: datetime
  c1_candle_index: int
  c1_chronological_pos: int
  c1_open_time: datetime
  c1_close: float
  close_count: int
  ```
- **`ConfirmedChoch`**:
  ```python
  choch_type: ChochType                  # BEARISH_CHOCH, BULLISH_CHOCH
  broken_level_type: str                 # "LAST_SUPPORT" or "LAST_RESISTANCE"
  broken_level_price: float
  broken_level_source_index: int
  c1_candle_index: int
  c2_candle_index: int
  c1_chronological_pos: int
  c2_chronological_pos: int              # Must equal c1_chronological_pos + 1
  c1_open_time: datetime
  c2_open_time: datetime
  confirmation_time: Optional[datetime]  # c2.close_time
  point_3_source_index: int
  point_3_open_time: datetime
  point_3_identified_at: datetime
  zones: Tuple[ChochZone, ...]
  new_direction: Direction
  restart_reference_candle_index: int
  restart_reference_open_time: datetime
  first_eligible_pullback_pos: int       # c2_chronological_pos + 1
  ```
- **`CoordinatorSnapshot`**:
  ```python
  msm_snapshot: MSMSnapshot
  choch_snapshot: ChochSnapshot
  confirmed_choch_events: Tuple[ConfirmedChoch, ...]
  active_direction: Direction
  is_unresolved: bool
  last_processed_index: int
  ```

---

## 3. Adjacency, Timing & Strict Inequality Rules

1. **Chronological Positions vs. Source IDs**:
   - Qualifying close adjacency is strictly enforced in chronological candle sequence positions ($c_2$ at position $k+1$ where $c_1$ is at $k$).
   - Arithmetic on source IDs ($c_2.\text{index} == c_1.\text{index} + 1$) is never required, ensuring robustness across non-contiguous or external bar numbering.
2. **Strict Inequality**:
   - Bearish: $\text{close} < \text{last\_support}$. Exact equality $\text{close} == \text{last\_support}$ fails closed.
   - Bullish: $\text{close} > \text{last\_resistance}$. Exact equality $\text{close} == \text{last\_resistance}$ fails closed.
   - Wick crossing without closing break fails closed.
3. **Candle Color Independence**:
   - Closing prices govern qualification. Green candles can qualify for Bearish CHOCH; red candles can qualify for Bullish CHOCH.

---

## 4. Lifecycle & History Across Direction Changes

Upon CHOCH confirmation:
1. **Unfinished Cycle Termination**: The prevailing MSM cycle ends immediately. Its tentative Point 3 is cleared.
2. **History Preservation**: All prior confirmed swing points and confirmed pairs (`confirmed_pairs`) remain immutable in history. Subsequent new-direction pairs are appended (`pair_index = 2`, etc.).
3. **Three Original-Candle Zones Established**:
   - Bearish: SBR (from broken support candle), QML / A+ (from preceding confirmed high), Double Top (from Point 3).
   - Bullish: RBS (from broken resistance candle), QML / A+ (from preceding confirmed low), Double Bottom (from Point 3).
   - Zero-wick swing candles produce single horizontal price lines (`[price, price]`, `is_line=True`).
4. **New Cycle Search Reference**:
   - `search_start` in the new direction is set to Point 3's original candle position.
5. **Post-Confirmation Pullback Boundary**:
   - The forward scan boundary for the first pullback in the new direction is set strictly after the confirmation bar:
     $$\text{position}(p_1) \ge \text{position}(c_2) + 1$$
   - Candles formed prior to or at $c_2$ cannot be replayed or recycled as new-direction pullbacks.

---

## 5. Unresolved Same-Close Path Behavior ($c_1 == p_2$)

When the second pullback candle `p2` completes, Point 3 is identified. If that same candle also closes strictly beyond the broken level:
- `ChochDetector` emits a diagnostic:
  `ChochDiagnostic(diagnostic_type=ChochDiagnosticType.UNRESOLVED_SAME_CLOSE, is_unresolved=True)`
- `CoordinatorSnapshot.is_unresolved` is set to `True`.
- The engine does NOT count the close as $c_1$ and does NOT reject it as invalid; it isolates the path.
- Downstream CHOCH confirmation is withheld, and direction switching is suspended without guessing.
- All source-settled later-candle cases ($c_1 \ge p_2 + 1$) proceed with complete determinism.
