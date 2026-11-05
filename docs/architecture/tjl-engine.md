# Trend Joining Level (TJL) Engine Architecture & Specification

## 1. Overview
The Trend Joining Level (TJL) engine implements pure offline calculation of:
- Directional swing point labeling (`TJL1`, `TJL2_A_PLUS`).
- Original-candle zone geometry (`[UB, High]` for high-side, `[Low, LB]` for low-side, zero-width lines when thickness is 0).
- Stable Level Identity formula: `(symbol_feed_id, source_timeframe, source_open_time, HIGH|LOW)`.
- Current eligible set lifecycle progression across $t_0 \to t_1 \to t_2$.
- Idempotent re-observation and single-shot outgoing cancellation intent emission.
- Immediate source CHOCH invalidation and post-CHOCH structure gap.

## 2. Architecture & Module Boundaries
```
Completed Market Candles
          │
          ▼
┌───────────────────────────────┐
│     MSMChochCoordinator       │ (Accepted deterministic MSM + CHOCH path)
└──────────────┬────────────────┘
               │ Emits structural observations
               ▼
┌───────────────────────────────┐
│         TJLReducer            │ (Pure functional lifecycle state machine)
└──────────────┬────────────────┘
               │ Emits immutable snapshots & transition records
               ▼
         TJLSnapshot
```

### Module Split
- **`src/aladeen/strategy/tjl_types.py`**:
  - `StableLevelId`: Immutable 4-element value object `(symbol_feed_id, source_timeframe, source_open_time, side)`.
  - `TJLLabel`: `TJL1` (confirmed extreme in trend direction), `TJL2_A_PLUS` (opposite confirmed extreme).
  - `TJLSide`: `HIGH`, `LOW`.
  - `TJLZone`: Immutable structural zone computed directly from original swing candle OHLC.
  - `TJLFingerprint`: `(source_engine_id, direction, ch_point_id, cl_point_id, p3_point_id)`.
  - `CurrentEligibleSet`: Active eligible set container bundling two confirmed zones, Point 3 anchor, and availability time.
  - `TJLTransitionRecord`: Atomic transition diagnostic record.
  - `TJLStructuralObservation`: Decoupled input payload for the pure reducer.
  - `TJLSnapshot`: Authoritative immutable engine state snapshot.

- **`src/aladeen/strategy/tjl_reducer.py`**:
  - Pure state machine.
  - Enforces:
    - Labels before eligibility ($t_0$): confirmed points labeled, but `current_eligible_set = None` when P3 is absent.
    - First set creation: creates Set 1 upon first active P3 identification with `outgoing_cancellation_intent = False`.
    - $t_1$ continuation break: assigns new labels to newly confirmed points, but retains existing active set without replacement.
    - $t_2$ pullback completion: replaces set when new fingerprint is identified, emitting `outgoing_cancellation_intent = True`.
    - Idempotence: re-observation of identical fingerprint produces `IDEMPOTENT_NO_OP` with 0 replacements and does NOT refresh original `eligibility_available_time`.
    - Source CHOCH invalidation: immediately removes active set, sets `outgoing_cancellation_intent = True`, and preserves historical zones/sets.
    - Unresolved containment: blocks speculative progression when upstream structure is ambiguous.

- **`src/aladeen/strategy/tjl_coordinator.py`**:
  - Links `MSMChochCoordinator` to `TJLReducer`.
  - Ingests completed candles and translates coordinator states to `TJLStructuralObservation`s.
  - Provides:
    - `process_candles(candles) -> TJLSnapshot` (clean batch with atomic rollback on failure).
    - `process_candle(candle) -> TJLSnapshot` (incremental completed-candle processing).
    - `replay_candles(candles) -> List[TJLSnapshot]` (bar-by-bar historical replay).

## 3. Public API Summary
```python
from aladeen.strategy import (
    TJLCoordinator,
    TJLReducer,
    TJLSnapshot,
    CurrentEligibleSet,
    TJLZone,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLTransitionType,
)

# Initialize coordinator
coord = TJLCoordinator(
    config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
    symbol_feed_id="FEED_EURUSD_H1",
    source_timeframe="H1",
)

# Process candles
snapshot = coord.process_candles(candles)
current_set = snapshot.current_eligible_set
```

## 4. Verification & Testing Split
- **`tests/test_tjl_types.py`**: 5 unit tests covering domain types, immutability, geometry calculations, and `StableLevelId` equality.
- **`tests/test_tjl_reducer.py`**: 9 isolated lifecycle tests covering synthetic structural transitions (Case A, Case B, Case C, idempotence, CHOCH invalidation, unresolved containment, atomic rollback).
- **`tests/test_tjl_coordinator.py`**: 7 candle-derived integration tests covering real candle sequences (`tjl_01`, `tjl_02`, `tjl_05`, `tjl_06`, `tjl_09`), batch vs sequential vs replay consistency, forming bar isolation, and mid-batch failure rollback.
- **`tests/test_tjl_fixture_integrity.py`**: 15 tests validating raw fixture data and acceptance specifications.
