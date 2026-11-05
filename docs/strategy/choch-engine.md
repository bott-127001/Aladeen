# Change of Character (CHOCH) Engine & Coordinator Specification

Last Updated: 2026-11-05 (Hardened Lifecycle, Event Identity, and Input Contracts — HANDOFF-021)

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
        │ 3. Clear active-cycle last_support / last_resistance        │
        │ 4. Build 3 original-candle zones (SBR/RBS, QML, Double Top) │
        │ 5. Invert marking direction                                 │
        │ 6. Restart search_start at Point 3 original candle          │
        │ 7. Enforce post-confirmation pullback scan (p1 >= c2 + 1)   │
        └─────────────────────────────────────────────────────────────┘
```

### Module Responsibilities
- **`ChochDetector` (`src/aladeen/strategy/choch_detector.py`)**:
  Pure mathematical detection unit. Evaluates completed candles for two consecutive closing breaks beyond the active confirmed level while tentative Point 3 is active.
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
- `process_candles(data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> CoordinatorSnapshot`: Fresh batch execution over a sequence of candles. Validates start candle configuration and data integrity upfront before mutating state.
- `process_candle(candle: StrategyCandle) -> CoordinatorSnapshot`: Sequential execution for incremental bar delivery. Guards against forming bars and enforces chronological monotonicity.
- `replay_candles(data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> List[CoordinatorSnapshot]`: Replays candle stream bar-by-bar from a clean state and returns snapshots after each completed candle.
- `reset() -> None`: Resets coordinator to clean initial state.
- `get_snapshot() -> CoordinatorSnapshot`: Returns current state snapshot.

#### `ChochDetector`
Standalone detector for CHOCH transitions.
- `__init__(initial_direction: Direction)`: Initializes detector with initial structural direction.
- `process_candle(...) -> ChochSnapshot`: Evaluates a single completed candle. Requires `StrategyCandle`. Rejects forming/unconfirmed candles without state mutation. Enforces chronological sequence position ordering.
- `reset_for_new_direction(new_direction: Direction) -> None`: Clears candidate, unresolved status, and confirmed event output upon direction reversal.

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
  point_3_identified_bar_index: int
  point_3_identified_at: Optional[datetime]
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
  point_3_identified_bar_index: int
  point_3_identified_at: Optional[datetime]
  zones: Tuple[ChochZone, ...]           # Exactly 3 zones required
  new_direction: Direction
  restart_reference_candle_index: int
  restart_reference_open_time: datetime
  first_eligible_pullback_pos: int       # c2_chronological_pos + 1
  event_id: str                          # Stable unique event identifier
  ```
- **`CoordinatorSnapshot`**:
  ```python
  msm_snapshot: MSMSnapshot              # Last authoritative MSM state (frozen if unresolved)
  choch_snapshot: ChochSnapshot          # Last authoritative CHOCH state (frozen if unresolved)
  confirmed_choch_events: Tuple[ConfirmedChoch, ...]
  active_direction: Direction            # Last authoritative marking direction
  is_unresolved: bool                    # True if ambiguous transition occurred
  last_processed_index: int              # Last authoritatively processed candle index
  unresolved_diagnostic: Optional[ChochDiagnostic]  # Ambiguity diagnostic if unresolved
  unresolved_candle_index: Optional[int] # Candle source index where ambiguity occurred
  last_received_index: int               # Latest received input candle index
  ```

### Consumer Guidance for Integrated State

Consumers of `CoordinatorSnapshot` must inspect `is_unresolved`:
- **When `is_unresolved == False`**: `msm_snapshot`, `active_direction`, and `choch_snapshot` represent the current authoritative market structure. `last_processed_index` matches `last_received_index`.
- **When `is_unresolved == True`**:
  - `msm_snapshot` and `active_direction` are **frozen at the last authoritative state prior to ambiguity**. They must NOT be presented as the resolved current market structure.
  - `unresolved_diagnostic` and `unresolved_candle_index` provide the specific reason and bar where evaluation stopped pending source reconciliation.
  - `last_received_index` indicates that later market data was received, but no speculative continuation or dependent reversal was advanced.

---

## 3. Lifecycle, Event Lifetime & Input Contract Guarantees

1. **Explicit Single-Transition Event Lifetime**:
   - `ChochDetector.process_candle()` clears transient `_confirmed_choch = None` at the start of each candle evaluation.
   - When a transition confirms, `confirmed_choch` is populated strictly for that transition candle.
   - On direction reset (`reset_for_new_direction()`), `_confirmed_choch` is explicitly cleared. Subsequent candles in the new direction never expose or re-emit an old confirmation.
2. **Chronological Identification Timing**:
   - Timing relative to Point 3 identification compares UTC availability timestamps when known (`close_time < identified_time`).
   - When availability timestamps are unknown, timing compares chronological stream positions (`chronological_pos < identified_bar_pos`), completely decoupled from source candle IDs (which may be arbitrary or decreasing).
   - Unknown identification timestamps remain `None`; they are never fabricated from `candle_open_time`.
3. **Full Prerequisite Binding for Candidates**:
   - In-progress candidate state ($c_1$) is bound to complete prerequisite identity: structural direction, broken level source index, broken level price, Point 3 source index, Point 3 identified bar index, and Point 3 identified time.
   - Any change in prerequisites invalidates the pending candidate (`PREREQUISITE_CHANGED`) before processing subsequent closes.
4. **Completed-Candle Contract Enforcement**:
   - Both `ChochDetector` and `MSMChochCoordinator` guard against forming and unconfirmed inputs.
   - Forming candles cause zero state mutations, advance no counters, and cannot confirm candidates.
   - Out-of-order or duplicate inputs fail closed with `ValueError` without corrupting state.
5. **Atomic Coordinated Transitions & Staged Validation**:
   - Every candle transition is staged in a local working copy (`copy.deepcopy` of MSM engine and CHOCH detector).
   - Validations (chronology, uniqueness, MSM progression, detector qualification, and restart reference existence) occur before modifying coordinator state.
   - Any exception during evaluation or restart leaves both child engines and coordinator state 100% unmutated.
   - Subsequent valid input can be processed normally after a rejected transition.
6. **Unresolved State Containment Policy**:
   - A candle simultaneously identifying Point 3 and closing beyond the level ($c_1 == p_2$) triggers `UNRESOLVED_SAME_CLOSE`.
   - The coordinator does not commit staged MSM continuation or detector changes.
   - The authoritative integrated state (`msm_snapshot`, `choch_snapshot`, `active_direction`, `last_processed_index`) remains strictly frozen at the pre-ambiguity state.
   - Later received candles update `last_received_index` but do not advance authoritative structure. No speculative continuation is published as resolved market structure.
7. **Strict 3-Zone Provenance Requirement**:
   - CHOCH confirmation requires provenance for all three original-candle zones (SBR/RBS, QML/A+, Double Top/Bottom).
   - If any required source candle is missing, confirmation is withheld with `REQUIRED_ZONE_PROVENANCE_MISSING`. Partial 2-zone events are never published.
8. **Cycle Restart & Structure Clearance**:
   - In `restart_after_choch()`, old-direction confirmed pairs are preserved in history for audit, but active `last_support` and `last_resistance` are cleared to `None`. Old levels are never silently reused as newly established opposite-direction structure.
