# Internal Structure Shift (ISS) Engine API Specification

## 1. Overview & Architecture

The **Internal Structure Shift (ISS)** engine detects 5-point internal structural shifts that form within a frozen price range captured between Main Level 2 (confirmed structural swing) and Main Level 3 (active tentative extreme).

### Core Boundaries & Constraints
- **Scope**: Pure offline read-only mathematical calculation. Zero UI/MT5 dependencies, zero order execution, zero network access.
- **Directionality**: Internal structural marking runs in the **opposite direction** of the prevailing main trend.
- **Historical Search Reference**: Main Level 3's original source candle.
- **Forward-Scan Restriction**: The earliest internal pullback pair must occur strictly after the main pullback's second candle ($p_1, p_2 > \text{main } p_2$).
- **Confirmation Timing**: Evaluated at the **identification** of the fifth internal point (two confirmed pairs + next tentative point). Does **not** require a continuation break of the fifth point.
- **Zone Derivation**: Exactly two structural zones formed strictly from **Point 3** and **Point 4** original candles.

---

## 2. Domain Models & Types (`src/aladeen/strategy/iss_types.py`)

All domain models are strictly immutable (`frozen=True`) dataclasses:

### 2.1 Enums
- `ISSLifecycleStatus`:
  - `PENDING_PREREQUISITES`: Waiting for confirmed Main Level 2 and identified Main Level 3.
  - `ELIGIBLE_SEARCH`: Candidate active, progressively monitoring internal points inside boundary.
  - `CONFIRMED`: All 5 points inside boundary and completion close inside boundary; zones created.
  - `OUT_OF_BOUNDS_REJECTED`: Any marked point body edge falls outside boundary; markings deleted, zero zones.
  - `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY`: All 5 points inside, but completion close falls outside boundary; tracking only, zero zones, never revives under same Main L3.
  - `MAIN_CONTINUATION_CANCELLED`: Main continuation break occurs while candidate is unfinished; candidate cancelled.
  - `MAIN_CHOCH_CANCELLED`: Main CHOCH confirms while candidate is unfinished/tracking; candidate cancelled.
- `ISSZoneType`:
  - `RBS`: Resistance-Become-Support (from Point 3 in Bearish Main).
  - `BUYING_A_PLUS`: Buying A+ (from Point 4 in Bearish Main).
  - `SBR`: Support-Become-Resistance (from Point 3 in Bullish Main).
  - `SELLING_A_PLUS`: Selling A+ (from Point 4 in Bullish Main).
- `ISSDiagnosticType`:
  - Detailed diagnostic categorization for transitions, rejections, cancellations, and unresolved pauses.

### 2.2 Dataclasses
- `FrozenBoundary`:
  - `min_price: float`, `max_price: float`, `main_level_2_price: float`, `main_level_3_price: float`
  - `frozen_at_candle_index: int`, `frozen_at_time: datetime`
  - `contains_price(price: float) -> bool`: Inclusive equality ($\min \le P \le \max$).
- `CandidateIdentity`:
  - `candidate_id: str`, `sequence_number: int`, `main_direction: Direction`
  - `main_level_2_index: int`, `main_level_2_price: float`
  - `main_level_3_index: int`, `main_level_3_price: float`
  - `main_level_3_identified_bar_index: int`
  - Unique ID distinguishes new identification events even on identical source candles.
- `InternalPoint`:
  - `point_number: int` (1..5), `role: str` ("CH1", "CL1", "CH2", "CL2", "TENTATIVE_HIGH", "TENTATIVE_LOW")
  - `source_candle_index: int`, `candle_open_time: datetime`, `body_edge_price: float`
  - `is_confirmed: bool`, `identified_bar_index: int`, `confirmed_bar_index: Optional[int]`
  - `is_inside_boundary: bool`
- `ISSZone`:
  - `zone_type: ISSZoneType`, `lower_price: float`, `upper_price: float`, `is_line: bool`
  - `source_candle_index: int`, `source_candle_open_time: datetime`
  - `source_point_number: int` (3 or 4), `source_point_role: str`
  - `confirmation_availability_time: Optional[datetime]`
  - High-side geometry: $[UB, \text{high}]$; Low-side geometry: $[\text{low}, LB]$.
  - Zero-width zones produce `is_line=True` with `lower_price == upper_price`.
- `ConfirmedISSEvent`:
  - Immutable record of confirmed ISS event, captured boundary, 5 points, and 2 zones.
- `ISSSnapshot`:
  - Snapshot at any candle: lifecycle status, candidate identity, boundary, visible internal points, active zones, confirmed events history, tracking-only flag, unresolved diagnostics.

---

## 3. Engine Public API (`src/aladeen/strategy/iss_engine.py`)

### 3.1 Class: `ISSEngine`
```python
engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
```

### 3.2 Methods & Properties
- `process_candles(candles: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> ISSSnapshot`:
  Clean batch execution. Runs on an isolated temporary engine; atomically commits upon success.
- `process_candle(candle: Union[StrategyCandle, dict]) -> ISSSnapshot`:
  Incremental single-candle ingest. Handles dict or `StrategyCandle` inputs.
- `replay_snapshots(candles: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> List[ISSSnapshot]`:
  Replays candles bar-by-bar and returns the sequence of snapshots after each candle.
- `current_snapshot -> ISSSnapshot`: Current immutable engine state snapshot.
- `confirmed_events -> Tuple[ConfirmedISSEvent, ...]`: All historical confirmed ISS events.
- `active_zones -> Tuple[ISSZone, ...]`: Active confirmed zones (empty if in-progress or rejected).
- `is_unresolved -> bool`: True if main path is paused on ambiguous unresolved transition.

---

## 4. Main / Internal Coordination Design

```
[Completed Candle Input]
          │
          ▼
[Main Coordinator (MSM + CHOCH)]
          │
          ├─► Unresolved Ambiguity (c1 == p2) ──► Pause ISS active progression, report diagnostic
          │
          ├─► Main CHOCH Confirms ──────────────► Cancel unfinished candidate (MAIN_CHOCH_CANCELLED)
          │
          ├─► Main Continuation Break ──────────► Cancel unfinished candidate (MAIN_CONTINUATION_CANCELLED)
          │
          └─► Main Level 2 Confirmed & Main Level 3 Active
                    │
                    ▼
          [Candidate Identification]
                    │
                    ├─► Fresh Identification ──► Freeze [min, max] boundary, initialize Internal MSMEngine
                    │                            (opposite direction, reference = Main L3, delayed scan)
                    │
                    ▼
          [Candidate Internal Processing]
                    │
                    ├─► Any marked point outside boundary ──► OUT_OF_BOUNDS_REJECTED (delete markings)
                    │
                    ├─► 5th point identified & close inside ──► CONFIRMED (create RBS/SBR & A+ zones)
                    │
                    └─► 5th point identified & close outside ─► OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
                                                               (retain markings for tracking, zero zones)
```

---

## 5. Parity & Failure Safety Guarantees
1. **Batch / Sequential / Replay Parity**: 100% snapshot, internal point, and zone equivalence across all three execution modes.
2. **Forming Candle Isolation**: Candles with `is_forming=True` or `bar_status != "CONFIRMED_COMPLETED"` are safely ignored without mutating settled history.
3. **Transactional Commit**: Mid-batch validation failures or exceptions leave previous engine state 100% unmutated.
4. **Historical Event Immutability**: Subsequent main continuation breaks or CHOCH reversals retain previously confirmed ISS events in immutable history.
