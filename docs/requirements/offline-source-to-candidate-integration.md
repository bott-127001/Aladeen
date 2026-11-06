# Offline Source-to-Candidate Integration Requirements & Acceptance Contract — Milestone 32

**Milestone**: Milestone 32 — Offline Source-to-Candidate Integration Requirements & Acceptance Contract  
**Active Branch**: `feature/confirmation-monitor`  
**Accepted Milestone 31 Baseline Commit**: `083d8df43c71ed0a56c6b020178dbdfdd3bf23d0` (HANDOFF-098)  
**Accepted Milestone 30 Baseline Commit**: `411f49f884fbcf417a531ad1ac75a52779ce0d7a`  
**Accepted Milestone 29 Baseline Commit**: `0144ddb8150b4132a7b60d24698105d897514cb2`  
**Requirements Baseline Commit**: `3f6689c194c95ca3761833f8831bb8a3f5b4740d`  

> [!IMPORTANT]
> **Safety Boundary & Deliverable Scope**:
> - This document defines the **integration contract, authority origins, deterministic lifecycle rules, fixture inventory, and decisive assertions** connecting accepted source structural levels, activation records, continuous confirmation detection, authoritative envelopes, and offline candidate matching.
> - Strictly **requirements, contract specification, and fixture inventory only**. Zero new runtime implementation, zero arbitration logic, zero usage ledger consumption, zero trade signal publication, zero order execution, zero MT5 live trading calls, and zero merging to `main`.
> - All strategy engines (`msm_engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`) remain **100% untouched (`0 diff` against `3f6689c194c95ca3761833f8831bb8a3f5b4740d`)**.

---

## 1. Domain Architecture & Integration Pipeline

The offline source-to-candidate integration pipeline establishes an end-to-end, fail-closed chain connecting five independent calculation stages:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. Source Structural Engine (TJL Engine: D1, H4, H1)                                   │
│    - Emits immutable SourceLevelSet and SourceMemberReference records.                 │
│    - Defines geometry [lower_edge, upper_edge], direction, role (TJL1, TJL2_A_PLUS),   │
│      eligibility_available_time, and StableLevelId.                                    │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Price Touch Print
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. Activation Engine (Pending Activation Lifecycle)                                    │
│    - Detects price tap into member boundary [lower_edge, upper_edge].                  │
│    - Manages ActivationRecord: state (PENDING_ACTIVATION, REARMED_PENDING),           │
│      generation_seq, first_touch_time, trigger_observation_id.                         │
│    - Maps source timeframe to confirmation timeframe (D1->H1, H4->M5, H1->M1).         │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Matching Evaluation Request
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. Continuous Confirmation Detection (MSMChochCoordinator, ISSEngine)                 │
│    - Continuously evaluates lower-timeframe StrategyCandle stream.                     │
│    - Emits ConfirmedChoch or ConfirmedISSEvent upon structural pattern completion.    │
│    - Identifies confirmation_candle_index, confirmation_time, completion_close_price.  │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Direct Candle Lookup & Stream Envelope
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 4. Authoritative Stream Enveloping & Evidence Adaptation                               │
│    - Resolves confirming candle directly from processed input candle collection.       │
│    - Wraps in immutable ValidatedCandleStreamEnvelope (feed_id, sequence_domain, etc.). │
│    - Adapts to immutable ConfirmationEvidenceRecord via confirmation_adapters.py.     │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Candidate Setup Evaluation
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 5. Offline Confirmation Matcher (ConfirmationMatcher, ConfirmationPairMatcher)         │
│    - Gated by immutable MatchingContext (source_resolution_status, current_members).   │
│    - Validates direction, timeframe, touch-before-confirmation causality, boundaries. │
│    - Consolidates dual patterns into CandidateSetupRecord with setup-stable identity.  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Authority Origins & Fail-Closed Boundary Specifications

To eliminate ambiguity and prevent manufactured metadata or heuristic guessing, every authority field must have a strictly designated single source of truth. If an authoritative value is absent or unknown, the system must fail closed.

| Authority Domain | Mandatory Source of Truth | Verification Standard | Fail-Closed Error / Rejection |
|---|---|---|---|
| **Member Resolution** | `MatchingContext.source_resolution_status: Mapping[str, bool]` | Strict boolean (`type(v) is bool`). Must be explicitly `True` for evaluated member key. | Non-bool raises `TypeError`. Absent member raises `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`. Value `False` rejects as `BLOCKED_UNRESOLVED_SOURCE_STRUCTURE`. |
| **Source Member Presence** | `MatchingContext.current_members: Mapping[str, SourceMemberReference]` | Evaluated `activation.member_key` must exist in `current_members`. Identity fields (`engine_id`, `symbol`, `source_timeframe`, `set_id`, `lower_edge`, `upper_edge`, `level_id`) must match activation. | Absent member rejects as `MEMBER_NOT_IN_CURRENT_SET`. Inconsistent attributes reject as `INCONSISTENT_MEMBER_SNAPSHOT`. |
| **Member Usage Status** | `SourceMemberReference.usage_evidence_status` | Must equal `UsageEvidenceStatus.UNUSED`. | `UsageEvidenceStatus.USED` rejects as `MEMBER_ALREADY_USED`. |
| **Snapshot Coverage** | `MatchingContext.coverage_status` | Must equal `CoverageStatus.COMPLETE`. | `CoverageStatus.PARTIAL` or `UNKNOWN` rejects with diagnostic. |
| **Activation Touch Authority** | `ActivationRecord.first_touch_time` & `trigger_observation_id` | Both fields must be populated (`first_touch_time is not None`, non-empty string ID). | Missing fields return diagnostic `MISSING_TOUCH_EVIDENCE` without raising `TypeError`. |
| **Member Eligibility Causality** | `SourceMemberReference.eligibility_available_time` | Must be populated. Activation touch must satisfy `first_touch_time >= eligibility_available_time`. | Missing eligibility time rejects as `MEMBER_ELIGIBILITY_UNKNOWN`. Earlier touch rejects as `ACTIVATION_BEFORE_MEMBER_ELIGIBILITY`. |
| **Candle-Time Authority** | `ValidatedCandleStreamEnvelope.candle` (`StrategyCandle`) | Candle `open_time` and `close_time` must be present and authoritative. Event `confirmation_time` must equal `close_time`. Interval duration `(c_close - c_open)` must match declared timeframe duration. `bar_status == "CONFIRMED_COMPLETED"` and `not is_forming`. | Missing or conflicting candle times fail closed with `ValueError` at adaptation. Incomplete bar sets `is_completed=False` (no candidate formed). |
| **Stream & Config Authority** | `ValidatedCandleStreamEnvelope` | All parameters (`symbol`, `feed_id`, `timeframe`, `price_basis`, `confirmation_config_id`, `confirmation_candle_id`, `sequence_domain`) must strictly agree with adapter arguments. | Any parameter contradiction raises `ValueError` fail-closed. |
| **Sequence Domain** | `SequenceDomain(feed_id, run_id)` | Envelope domain must match caller domain. Activation domain must match evaluation domain. | Mismatch raises `ValueError` at adaptation or rejects as `CROSS_DOMAIN_EVIDENCE_REJECTED` at matcher. |
| **Evaluation Time Horizon** | `MatchingContext.evaluation_time` | Confirmation close timestamp must satisfy `confirmation_close_timestamp <= evaluation_time`. | Confirmation occurring after evaluation time rejects as `CONFIRMATION_AFTER_EVALUATION_TIME`. |

---

## 3. Deterministic Lifecycle Rules

The offline integration contract preserves all accepted engine rules without alteration, defining exact lifecycle behavior across five state-transition scenarios:

### 3.1. TJL Level Replacement
- **Trigger**: Higher timeframe (e.g. D1) structural shift causes the TJL Engine to detect a new 3-point trend set, issuing a new `set_id` and replacing active levels.
- **Contract**:
  - The previous set is deactivated; previous members are no longer present in `current_members`.
  - Stale activations referencing the replaced set transition to `CANCELLED_REPLACED`.
  - Offline matcher rejects any confirmation evidence referencing old activations as `MEMBER_NOT_IN_CURRENT_SET`.

### 3.2. Structural Invalidation (Main CHOCH)
- **Trigger**: Source timeframe forms an opposite-direction Main CHOCH (e.g. Bullish Main CHOCH invalidates downward TJL levels).
- **Contract**:
  - Activation engine cancels active levels immediately (`CANCELLED_SOURCE_INVALIDATED`).
  - Active pending activations are cancelled.
  - Offline matcher rejects confirmation evidence attempting to pair with invalidated activations as `INELIGIBLE_ACTIVATION_STATE`.

### 3.3. Rearm Lifecycle & Generation Tracking
- **Trigger**: A pending activation was cancelled while price moved outside the zone, and subsequent price action re-enters the zone with a fresh touch.
- **Contract**:
  - Activation Engine transitions the level to `REARMED_PENDING` and increments `generation_seq` (e.g. Gen 1 $\rightarrow$ Gen 2).
  - The new activation record carries a fresh `first_touch_time` and `trigger_observation_id`.
  - Stale confirmation evidence (from Gen 1 or confirmed prior to Gen 2 touch) is strictly rejected as `CONFIRMATION_BEFORE_TOUCH`.
  - Fresh confirmation evidence completing after the Gen 2 touch matches successfully.

### 3.4. Repeated Snapshots & Idempotency
- **Trigger**: Re-evaluation of the same market snapshot or re-running matcher over identical inputs.
- **Contract**:
  - Candidate identity is derived strictly from the setup key: `f"CAND[{len(setup_key)}:{setup_key}]"`, where `setup_key = f"{activation.member_key}|{activation.generation_seq}"`.
  - Batch consolidator coalesces identical duplicate activations and identical confirmation events deterministically.
  - Candidate record outputs, ordering, and field values are 100% deterministic and independent of arrival permutations or wall-clock timestamps.

### 3.5. Unresolved Multi-Candle Pullback Ambiguity
- **Trigger**: ISS engine detects an ISS pattern requiring multi-candle pullback resolution where structural boundaries remain ambiguous.
- **Contract**:
  - Evidence record explicitly carries `has_unresolved_dependencies = True`.
  - Offline matcher blocks candidate formation fail-closed, returning `ConfirmationMatchStatus.BLOCKED` with reason `BLOCKED_UNRESOLVED_CONFIRMATION_GAP` and `candidate_record = None`.

---

## 4. Fixture Categories & Acceptance Inventory

Milestone 32 establishes four distinct, segregated fixture categories to ensure comprehensive, unambiguous verification:

```
tests/fixtures/
├── integration/
│   ├── genuine_candle_derived/          # Category 1: End-to-end continuous detection streams
│   │   ├── choch_d1_h1_bearish.json     # D1 source level + genuine H1 continuous CHOCH stream
│   │   └── iss_d1_h1_bullish.json       # D1 source level + genuine H1 continuous ISS stream
│   ├── exact_print_activation/          # Category 2: Tick/candle touch observation print sequences
│   │   ├── touch_and_rearm_lifecycle.json
│   │   └── replacement_cancellation.json
│   ├── synthetic_contract/              # Category 3: Exhaustive combinatorial & property tests
│   │   ├── batch_consolidation_matrix.json
│   │   └── permutation_invariance.json
│   └── negative_blocked_paths/          # Category 4: Fail-closed negative scenarios
│       ├── missing_candle_close.json
│       ├── unsupported_timeframe.json
│       ├── cross_domain_mismatch.json
│       └── unresolved_iss_gap.json
```

### Category 1: Genuine Candle-Derived Source and Confirmation Integration
- **Purpose**: Verify end-to-end continuous detection without mocks or manufactured candle timestamps.
- **Data Source**: Preserved MT5/acceptance JSON fixtures (`choch_acceptance.json`, `iss_acceptance.json`).
- **Standard**:
  - Inputs are parsed into typed `StrategyCandle` collections with authoritative `time`, `close_time`, `is_forming`, `bar_status`.
  - Detector engines (`MSMChochCoordinator`, `ISSEngine`) execute continuously from configured start candles.
  - Confirming candles are retrieved directly by index from the processed input collection.
  - Envelopes bind looked-up candles directly to matcher evaluation.

### Category 2: Exact-Print-Driven Activation Lifecycle
- **Purpose**: Verify activation engine state transitions, touch observations, cancellation, and rearm increments.
- **Data Source**: Authoritative price-touch print sequences with explicit timestamps and prices.
- **Standard**:
  - Verifies `PENDING_ACTIVATION` $\rightarrow$ cancel $\rightarrow$ leave zone $\rightarrow$ `REARMED_PENDING` (Gen 2).
  - Verifies `first_touch_time` and `trigger_observation_id` provenance propagation.

### Category 3: Synthetic Typed Contract Tests
- **Purpose**: Verify mathematical identity, permutation invariance, defensive freezing, and consolidation logic.
- **Data Source**: In-memory synthetic value objects conforming strictly to domain schemas.
- **Standard**:
  - Exhaustive permutations of activations and evidence records.
  - Defensive freezing against dictionary mutation via `MappingProxyType`.
  - Strict type checking (e.g. strict boolean enforcement in `source_resolution_status`).

### Category 4: Unresolved or Unsupported Paths (Must Remain Blocked)
- **Purpose**: Guarantee fail-closed security boundaries.
- **Standard**:
  - Missing candle close time (`close_time is None`).
  - Unsupported timeframe (e.g. `"M15"`).
  - Missing or contradictory envelope sequence domain.
  - Disagreement between event confirmation time and candle close time.
  - Unresolved ISS pullback dependencies (`has_unresolved_dependencies = True`).
  - Unknown source resolution authority.

---

## 5. Decisive Acceptance Assertions

Milestone 32 requires the following decisive assertions to be validated across all integration test suites:

1. **No Candidate Before Member Availability**:
   - Given an activation touch timestamp $T_{touch}$ and member availability timestamp $T_{avail}$:
   - If $T_{touch} < T_{avail}$, matching fails closed immediately with rejection reason `ACTIVATION_BEFORE_MEMBER_ELIGIBILITY` and `candidate_record is None`.
2. **No Candidate Before Confirmation Completion**:
   - If `confirming_candle.is_forming is True` or `confirming_candle.bar_status != "CONFIRMED_COMPLETED"`:
   - Evidence adaptation sets `is_completed = False`. Matcher rejects evidence as `CONFIRMATION_NOT_COMPLETED` and produces no candidate.
3. **No Reuse Across Invalidated Generations**:
   - An activation with `generation_seq = 2` must not match confirmation evidence whose confirmation timestamp occurred prior to the Gen 2 touch timestamp.
   - Any prior-generation evidence is rejected as `CONFIRMATION_BEFORE_TOUCH`.
4. **Deterministic Repeated Evaluation & Permutation Invariance**:
   - Evaluating batch $B_1 = ([A_1, A_2], [E_1, E_2])$ and batch $B_2 = ([A_2, A_1], [E_2, E_1])$ yields identical candidates with identical candidate IDs, identical ordering, and identical attributes.
5. **Zero Mutation of Accepted Engine Inputs**:
   - All external mappings passed into `MatchingContext` (`current_members`, `source_resolution_status`, `touch_sequence_evidence`) are defensively copied and wrapped in `MappingProxyType`.
   - Subsequent mutations to caller dictionaries have zero effect on internal context state.

---

## 6. Upstream Contract Boundaries & Explicit Non-Heuristics

To maintain architectural integrity, all known boundary limitations are explicitly cataloged below. Under no circumstances should an agent implement a speculative heuristic to bridge these boundaries:

1. **Automated Cross-Timeframe Stream Ingestion**:
   - In offline testing, multi-timeframe candle streams are coordinated explicitly via test fixtures and envelopes.
   - Live multi-symbol / multi-timeframe streaming coordination belongs to future runtime pipeline milestones.
2. **Arbitration and Usage Ledger Consumption**:
   - Milestone 31/32 produces `CandidateSetupRecord` candidates with setup-stable identity.
   - Resolving competing candidates across timeframes (M1 vs M5 vs H1), writing usage ledger commits, and final signal publication belong to Milestone 33+ arbitration.
3. **Automated Multi-Candle Pullback Structural Resolution**:
   - Multi-candle pullback ISS patterns with ambiguous internal swing points are not resolved via arbitrary heuristics. They are explicitly marked with `has_unresolved_dependencies = True` and fail closed.
4. **Order Execution & Broker Communication**:
   - Strictly outside project scope per [`AGENTS.md`](../../AGENTS.md). The dashboard is read-only.
