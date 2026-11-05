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
- `direction -> Direction`: Current authoritative main structural marking direction (tracks dynamic direction reversals post-CHOCH).
- `process_candles(candles: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> ISSSnapshot`:
  Clean batch execution. Runs on an isolated temporary engine; atomically commits upon success.
- `process_candle(candle: Union[StrategyCandle, dict]) -> ISSSnapshot`:
  Incremental single-candle ingest. Handles dict or `StrategyCandle` inputs.
  **Source ID Policy**: Incremental dictionary inputs must explicitly provide an integer `'index'`. Inferred ID arithmetic from previous candles is strictly prohibited.
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
          ├─► Main CHOCH Confirms ──────────────► Cancel unfinished candidate (MAIN_CHOCH_CANCELLED),
          │                                      Authoritative direction switches!
          │
          ├─► Main Continuation Break ──────────► Cancel unfinished candidate (MAIN_CONTINUATION_CANCELLED)
          │
          └─► Main Level 2 Confirmed & Main Level 3 Active (under current authoritative direction!)
                    │
                    ▼
          [Candidate Identification]
                    │
                    ├─► Fresh Identification ──► Freeze exact [min, max] boundary (no rounding),
                    │                            Initialize Internal MSMEngine (opposite direction,
                    │                            reference = Main L3, strictly_after_candle_time = main p2 open)
                    │
                    ▼
          [Candidate Internal Processing]
                    │
                    ├─► Any marked point outside boundary ──► OUT_OF_BOUNDS_REJECTED (delete markings)
                    │
                    ├─► 5th point identified & close inside ──► CONFIRMED (create RBS/SBR & A+ zones)
                    │
                    └─► 5th point identified & close outside ─► OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
                                                               (attempted 5 points locked; tracking points continue)
```

---

## 5. Parity & Failure Safety Guarantees
1. **Authoritative Direction Tracking**: Fresh candidates are instantiated using the main coordinator's authoritative current direction (`self.direction`), supporting completed main CHOCH reversals followed by valid new-direction ISS candidates.
2. **Exact Boundary Evaluation**: Captured boundaries preserve exact floating-point values without rounding. Boundary evaluations enforce strict mathematical inequalities without artificial tolerances.
3. **Unknown Availability Preserved**: When candle close timestamps are unavailable, availability metadata (`frozen_at_time`, `confirmation_time`, `confirmation_availability_time`) remains `None`. Forward-scan restriction is enforced via `strictly_after_candle_time` on monotonic open timestamps without inventing availability timestamps.
4. **Complete Transactional Transitions**: Every sequential candle ingestion is executed on staged working copies (`main_coord`, `candidate`, `confirmed_events`, `candles`, `indices`). Any exception during main coordination, internal engine advance, boundary evaluation, or zone/event construction leaves engine state 100% unmutated.
5. **Tracking-Only Separation & Precedence**:
   - If an internal Point 5 is identified on a candle that closes beyond Main Level 3, the candle confirms main continuation and removes Main Level 3. The main continuation break takes precedence, producing `MAIN_CONTINUATION_CANCELLED` with zero ISS events.
   - If a candidate enters `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY`, its original 5 attempted points are preserved in `snapshot.attempted_points`, while ongoing tracking swings are exposed in `snapshot.tracking_points`.
   - If a subsequent candle confirms main continuation or Main CHOCH, the tracking-only candidate transitions to `MAIN_CONTINUATION_CANCELLED` or `MAIN_CHOCH_CANCELLED`, clearing active tracking flags and processes (`is_tracking_only = False`, `tracking_points = ()`, `attempted_points = None`).
   - Confirmed ISS history (`confirmed_events`) is immutable and strictly preserved across subsequent main continuation or CHOCH events.
6. **Progress Reporting (Processed vs Received)**:
   - When the main integrated path encounters an unresolved ambiguity (e.g. `c1 == p2`), the authoritative `last_processed_index` marker remains strictly frozen at the pre-ambiguity candle.
   - `last_received_index` advances monotonically as incoming candles are received and validated, preventing unverified input from being presented as authoritative ISS evaluations.
7. **Batch / Sequential / Replay Parity**: 100% snapshot, internal point, and zone equivalence across all three execution modes.
8. **Forming Candle Isolation**: Candles with `is_forming=True` or `bar_status != "CONFIRMED_COMPLETED"` are safely ignored without mutating settled history.

---

## 6. Dashboard Integration Architecture (`HANDOFF-031`)
1. **Calculation Mode**: Added `CalculationMode.INTEGRATED_MSM_CHOCH_ISS = "INTEGRATED_MSM_CHOCH_ISS"` in `src/aladeen/strategy/service.py`. When active, `calculate_msm()` invokes `ISSEngine`, exposing its internal coordinator snapshot for MSM and CHOCH history to ensure 100% synchronization without coordinator drift.
2. **Context Configuration**: `MSMContext` contains immutable visual flags:
   - `show_iss_markers`: Controls rendering of 5th-point confirmation star markers on the chart.
   - `show_iss_zones`: Controls rendering of RBS/SBR and Buying/Selling A+ zone areas and lines.
   - `show_iss_points`: Controls rendering of internal 5-point structure markers.
3. **Presentation Invariance**: Display toggles (`iss-display-toggles`) are purely visual. Toggling them updates `msm-applied-store` and re-renders chart traces without recalculating strategy parameters or resetting active directions.
4. **Draft Edit Isolation**: Modifying strategy controls (`strategy-calculation-mode`, `msm-direction-selector`, `msm-start-candle-dropdown`) puts the UI into an unapplied draft state ("🟡 Unapplied changes"), preserving the applied strategy until the user clicks Apply.
5. **Chart Overlay Semantics**:
   - ISS confirmation markers display on the 5th-point identification candle.
   - All tooltips explicitly state: `"Confirmed ISS Event [Structural Event — Not Order Entry Signal]"`.
   - Structural zones start at `confirmation_availability_time`. If unknown, zero time-extended boxes are plotted.
   - Attempted and ongoing tracking points for tracking-only candidates are visually marked `"Tracking Only — Not Eligible"`.
6. **Inspection Panel**:
   - Candidate Identity & Status Box (Candidate ID, direction, Level 2/3 references, boundary `[min, max]`, authoritative processed bar vs latest received bar).
   - Internal 5-Point Structure table with boundary checks and confirmation statuses.
   - Attempted & Ongoing Tracking Points tables.
   - Active ISS Structural Zones table.
   - Confirmed ISS History table.
