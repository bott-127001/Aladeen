# Source-Resolution Authority Requirements & Upstream State Inspection Specification

**Milestone**: Milestone 37 — Source-Resolution Authority Requirements  
**Status**: Requirements & Upstream State Inspection Specification (Documentation & Acceptance-Fixture Planning Only)  
**Safety Scope**: Pure offline read-only specification. Zero MT5 live trading, zero order execution, zero account modification, zero candidate arbitration/ranking, zero usage ledger writes, zero final signal publication, zero runtime builder implementation in this milestone.  
**Baseline Engine & Matcher Integrity**: Strategy engines (`src/aladeen/strategy/engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`, `types.py`, `validator.py`) and matcher logic (`src/aladeen/strategy/confirmation_pair_matcher.py`) strictly maintain **0 diff**.

---

## 1. Executive Summary & Objective

In Milestone 36 (accepted at `600925471e1fc56d01ba6621ed86f728d7eb76a0`, HANDOFF-125), offline integration between source member registration, exact-price activation, CHOCH confirmation detection, request-bound feed coverage preprocessing, and physical-level usage preprocessing was formally established across 14 modular integration tests and 740 offline regression tests.

However, upstream source-resolution authority in Milestone 36 remained an explicitly supplied parameter (`source_resolution_status: Mapping[str, bool]`). Supplying a labeled synthetic `True` mapping proves that downstream gating enforces source-resolution authority fail-closed, but does **not** prove upstream resolution derivation.

The objective of Milestone 37 is to:
1. **Inspect Actual Upstream State**: Perform an exhaustive audit of accepted coordinator, synchronizer, snapshot, transition, and cursor fields across repository paths, identifying exactly what upstream evidence exists and what does not.
2. **Reject False-Positive Heuristics**: Establish strict boundaries proving that current-set presence alone, valid zone geometry alone, closed-bar status alone, and cursor equality alone do **not** prove source resolution.
3. **Define Proposed Resolution-Evidence Contract**: Specify a formal, traceable contract (`ProposedSourceResolutionRecord`) covering member identity, scope non-transitivity, effective source boundary vs. evidence availability time, tri-state resolution semantics, conflict handling, and supersession.
4. **Define Fail-Closed Matcher Mapping**: Map missing, unresolved, stale, future, and cross-domain records to established matcher rejection reasons and blocked status.
5. **Build a Traceable Acceptance Inventory**: Catalogue existing executable evidence, proposed synthetic contracts, proposed integration cases, blocked live gaps, and negative false-positive controls.

---

## 2. Exhaustive Upstream State Inspection & Field Attribution

Every claim regarding upstream execution state must be attributed to exact repository paths, classes, and fields.

### 2.1 Upstream Coordinator Layer (`src/aladeen/strategy/coordinator.py`)

The sequential coordinator links `MSMEngine` and `ChochDetector` lifecycle transitions.

| Component / Class | Field / Property | Type | Repository Attribution | Upstream Semantics & Limitations |
| :--- | :--- | :--- | :--- | :--- |
| `CoordinatorSnapshot` | `msm_snapshot` | `MSMSnapshot` | `coordinator.py:19` | Authoritative MSM snapshot; frozen at last pre-ambiguity state if unresolved. |
| `CoordinatorSnapshot` | `choch_snapshot` | `ChochSnapshot` | `coordinator.py:20` | Authoritative CHOCH snapshot; frozen at last pre-ambiguity state if unresolved. |
| `CoordinatorSnapshot` | `confirmed_choch_events` | `Tuple[ConfirmedChoch, ...]` | `coordinator.py:21` | Monotonic history of confirmed structural CHOCH events. |
| `CoordinatorSnapshot` | `active_direction` | `Direction` | `coordinator.py:22` | Current structural marking direction (`UPWARD` or `DOWNWARD`). |
| `CoordinatorSnapshot` | `is_unresolved` | `bool` | `coordinator.py:23` | **Key Ambiguity Flag**: `True` if ambiguous transition occurred (e.g. `c1 == p2`, continuation reset, forming candle rejected). |
| `CoordinatorSnapshot` | `last_processed_index` | `int` | `coordinator.py:24` | Source index of the last completed candle processed authoritatively through MSM & CHOCH. |
| `CoordinatorSnapshot` | `unresolved_diagnostic` | `Optional[ChochDiagnostic]` | `coordinator.py:25` | Diagnostic record explaining the exact ambiguity if unresolved. |
| `CoordinatorSnapshot` | `unresolved_candle_index`| `Optional[int]` | `coordinator.py:26` | Source candle index where ambiguity occurred. |
| `CoordinatorSnapshot` | `last_received_index` | `int` | `coordinator.py:27` | Source index of the latest received candle; advances even when coordinator is frozen/unresolved. |
| `MSMChochCoordinator` | `process_candles()` | Method | `coordinator.py:65` | Batch calculation on isolated temporary coordinator; atomically updates state only upon success. |

### 2.2 Upstream TJL Coordinator Layer (`src/aladeen/strategy/tjl_coordinator.py`)

Wires `MSMChochCoordinator` to `TJLReducer`.

| Component / Class | Field / Property | Type | Repository Attribution | Upstream Semantics & Limitations |
| :--- | :--- | :--- | :--- | :--- |
| `TJLCoordinator` | `symbol_feed_id` | `str` | `tjl_coordinator.py:24` | Target symbol identifier (e.g. `EURUSD`). |
| `TJLCoordinator` | `source_timeframe` | `str` | `tjl_coordinator.py:25` | Target timeframe (e.g. `D1`). |
| `TJLCoordinator` | `source_engine_id` | `str` | `tjl_coordinator.py:26` | Engine identifier (e.g. `ENGINE_EURUSD_D1`). |
| `TJLCoordinator` | `is_unresolved` | `bool` | `tjl_coordinator.py:40` | Reflects `_reducer.is_unresolved`. |
| `TJLCoordinator` | `last_processed_index` | `int` | `tjl_coordinator.py:44` | Reflects `_reducer.last_processed_index`. |
| `TJLCoordinator` | `last_received_index` | `int` | `tjl_coordinator.py:48` | Reflects `_reducer.last_received_index`. |
| `TJLCoordinator` | `process_candles()` | Method | `tjl_coordinator.py:60` | Ingests candles, derives structural observations from completed MSM/CHOCH events, and steps `TJLReducer`. |

### 2.3 Upstream TJL Reducer & State Types (`src/aladeen/strategy/tjl_reducer.py`, `tjl_types.py`)

Pure lifecycle state machine managing TJL labels, geometry, and current-set eligibility.

| Component / Class | Field / Property | Type | Repository Attribution | Upstream Semantics & Limitations |
| :--- | :--- | :--- | :--- | :--- |
| `TJLSnapshot` | `source_engine_id` | `str` | `tjl_types.py:108` | Originating engine identity. |
| `TJLSnapshot` | `symbol_feed_id` | `str` | `tjl_types.py:109` | Symbol scope. |
| `TJLSnapshot` | `source_timeframe` | `str` | `tjl_types.py:110` | Timeframe scope. |
| `TJLSnapshot` | `direction` | `Optional[Direction]` | `tjl_types.py:111` | Active direction. |
| `TJLSnapshot` | `current_eligible_set` | `Optional[CurrentEligibleSet]`| `tjl_types.py:112` | Active eligible set (`set_id`, `tjl1_zone`, `tjl2_zone`, `p3_price`, `eligibility_available_time`). |
| `TJLSnapshot` | `all_labeled_zones` | `Tuple[TJLZone, ...]` | `tjl_types.py:113` | Cumulative tuple of all labeled zones across execution. |
| `TJLSnapshot` | `historical_sets` | `Tuple[CurrentEligibleSet, ...]`| `tjl_types.py:114`| Superseded or invalidated eligible sets. |
| `TJLSnapshot` | `outgoing_cancellation_intent`| `bool` | `tjl_types.py:115` | Signals that previous set must be cancelled. |
| `TJLSnapshot` | `last_transition` | `Optional[TJLTransitionRecord]`| `tjl_types.py:116` | Most recent transition record. |
| `TJLSnapshot` | `transition_history` | `Tuple[TJLTransitionRecord, ...]`| `tjl_types.py:117`| Monotonic ledger of all state transitions. |
| `TJLSnapshot` | `is_unresolved` | `bool` | `tjl_types.py:118` | `True` if reducer is blocked or halted by ambiguity. |
| `TJLSnapshot` | `unresolved_diagnostic` | `Optional[str]` | `tjl_types.py:119` | Diagnostic reason for unresolved state. |
| `TJLSnapshot` | `last_processed_index` | `int` | `tjl_types.py:120` | Last candle index authoritatively reduced. |
| `TJLSnapshot` | `last_received_index` | `int` | `tjl_types.py:121` | Last candle index received. |
| `TJLSnapshot` | `structural_epoch` | `int` | `tjl_types.py:122` | Monotonic epoch incremented on direction-changing CHOCH. |
| `TJLTransitionRecord` | `transition_type` | `TJLTransitionType` | `tjl_types.py:97` | Enum: `FIRST_CREATION`, `SET_REPLACEMENT`, `CHOCH_INVALIDATION`, `CONTINUATION_RETAINED`, `LABELS_ONLY`, `IDEMPOTENT_NO_OP`, `BLOCKED_UNRESOLVED`. |
| `TJLTransitionRecord` | `outgoing_cancelled_set_id` | `Optional[str]` | `tjl_types.py:103`| Exact predecessor set ID invalidated/replaced by this transition. |
| `CurrentEligibleSet` | `eligibility_available_time` | `datetime` | `tjl_types.py:84` | Timestamp when the set became eligible (candle close of establishing bar). |

### 2.4 Synchronizer & Activation Adapter (`src/aladeen/strategy/activation_adapter.py`)

Transactional adapter maintaining an explicit processed-transition cursor over `TJLSnapshot`.

| Component / Class | Field / Property | Type | Repository Attribution | Upstream Semantics & Limitations |
| :--- | :--- | :--- | :--- | :--- |
| `TJLSynchronizer` | `engine` | `ActivationEngine` | `activation_adapter.py:302` | Bound downstream activation engine. |
| `TJLSynchronizer` | `last_synced_transition_index` | `int` | `activation_adapter.py:303` | **Explicit Transition Cursor**: Index into `snapshot.transition_history`. Initialized to `-1`. |
| `TJLSynchronizer` | `_consumed_transitions` | `List[TJLTransitionRecord]`| `activation_adapter.py:305` | History of consumed transitions; enforced strictly prefix-continuous against incoming snapshots. |
| `TJLSynchronizer` | `_bound_engine_id` | `Optional[str]` | `activation_adapter.py:306` | Context-locked engine identifier. |
| `TJLSynchronizer` | `_bound_symbol_feed_id` | `Optional[str]` | `activation_adapter.py:307` | Context-locked symbol identifier. |
| `TJLSynchronizer` | `_bound_source_timeframe` | `Optional[str]` | `activation_adapter.py:308` | Context-locked source timeframe. |
| `TJLSynchronizer.sync()` | Fresh Member Registration Guard | Code Logic | `activation_adapter.py:414-419` | `if not snapshot.is_unresolved and snapshot.current_eligible_set is not None: register_source_members(...)`. **Suppresses fresh eligibility registration from unresolved snapshots**. |

### 2.5 Multi-Timeframe Service Layer (`src/aladeen/strategy/service.py`)

Coordinates high-level service calculation runs across MSM, CHOCH, ISS, and TJL.

| Component / Class | Field / Property | Type | Repository Attribution | Upstream Semantics & Limitations |
| :--- | :--- | :--- | :--- | :--- |
| `MSMServiceResult` | `is_unresolved` | `bool` | `service.py:100` | Service-level unresolved indicator. |
| `MSMServiceResult` | `unresolved_diagnostic` | `Optional[ChochDiagnostic]`| `service.py:101`| Diagnostic explaining why calculation halted. |
| `MSMServiceResult` | `unresolved_candle_index`| `Optional[int]` | `service.py:102` | Index of ambiguous candle. |
| `MSMServiceResult` | `last_processed_index` | `int` | `service.py:103` | Last processed candle index across service engines. |
| `MSMServiceResult` | `last_received_index` | `int` | `service.py:104` | Last received candle index across service engines. |
| `MSMServiceResult` | `last_synced_transition_index` | `Optional[int]` | `service.py:97` | Cursor position after syncing TJL snapshot to activation engine. |
| `ActivationSessionCoordinator` | `_current_run_id` | `str` | `service.py:133` | Monotonic run session scope. |
| `ActivationSessionCoordinator` | `_bound_context_key` | `Optional[Tuple]` | `service.py:137` | 6-tuple: `(data_source, engine_id, symbol, timeframe, start_candle_time, calculation_mode)`. |

---

## 3. Strict Non-Invention & Rejection of False-Positive Heuristics

To maintain mathematical integrity and prevent dangerous premature resolution assumptions, four common heuristics must be formally rejected:

### 3.1 Heuristic 1 Rejected: "Current-Set Presence Proves Resolution"
- **False Assumption**: If `TJLSnapshot.current_eligible_set` is non-None, the source members are resolved and valid for candidate generation.
- **Why It Is False**: In `TJLReducer` and `MSMChochCoordinator`, an unresolved ambiguity (e.g. `is_unresolved = True` caused by an ambiguous candle at index 15) does **not** erase `current_eligible_set` that was established earlier at index 8. The set remains populated in snapshot memory, but the engine is in a frozen/ambiguous state. Treating set presence alone as resolution would generate candidates on stale or invalidated structures while the engine is halted.

### 3.2 Heuristic 2 Rejected: "Valid Zone Geometry Proves Resolution"
- **False Assumption**: If a `TJLZone` has finite, non-zero prices (`lower_price < upper_price`), it is mathematically resolved.
- **Why It Is False**: Geometry describes price level boundaries; it does not describe engine lifecycle state, causal availability, or whether the level has been superseded by an upstream CHOCH invalidation.

### 3.3 Heuristic 3 Rejected: "A Closed Bar Proves Resolution"
- **False Assumption**: If the source candle is marked `is_forming = False` (closed), the calculation for that bar is resolved.
- **Why It Is False**: A closed candle may trigger an ambiguous continuation reset, an out-of-order sequence rejection, or a blocked state in `ChochDetector`. The bar is closed, but the strategy state is unresolved.

### 3.4 Heuristic 4 Rejected: "Cursor Equality Alone Proves Resolution"
- **False Assumption**: If `last_processed_index == last_received_index` (or `last_synced_transition_index == len(history) - 1`), all upstream calculations are resolved.
- **Why It Is False**:
  1. A stream that paused or completed at candle 10 has `last_processed_index == 10` and `last_received_index == 10`. However, if the candidate evaluation time is $T_{\text{eval}} = \text{candle 15}$, cursor equality at candle 10 tells us nothing about candles 11 through 15.
  2. If the coordinator halted due to ambiguity at candle 10, both indices could be equal at 10 if no further candles were fed into the coordinator, but `is_unresolved` is `True`.
  3. Cursor equality merely indicates that the reducer reached the end of its received buffer; it does not attest to member-level eligibility, absence of conflicting transitions, or causal validity relative to candidate evaluation time.

---

## 4. Proposed Source-Resolution Evidence Contract (`ProposedSourceResolutionRecord`)

To replace synthetic ad-hoc mappings with traceable offline authority, we define the schema and semantics for `ProposedSourceResolutionRecord`.

### 4.1 Schema Definition

```python
@dataclass(frozen=True)
class ProposedSourceResolutionRecord:
    """Offline authority record establishing verified calculation resolution for a source member."""
    # 1. Identity
    source_engine_id: str                      # e.g. "ENGINE_EURUSD_D1"
    symbol_feed_id: str                        # e.g. "EURUSD"
    source_timeframe: str                      # e.g. "D1"
    set_id: str                                # e.g. "SET_EURUSD_D1_UPWARD_1"
    role: str                                  # "TJL1" or "TJL2_A_PLUS"
    member_key: str                            # e.g. "SET_EURUSD_D1_UPWARD_1:TJL1"
    level_id: StableLevelId                    # Physical level binding
    structural_epoch: int                      # Reducer epoch (monotonic integer)

    # 2. Scope & Domain Binding
    feed_id: str                               # Data feed identifier
    run_id: str                                # Service calculation run ID
    sequence_domain: SequenceDomain            # Sequence domain binding
    source_config_id: str                      # Configuration hash / identifier

    # 3. Temporal & Causal Boundaries
    effective_source_boundary: datetime        # Source bar close time establishing the member
    evidence_available_time: datetime          # When resolution calculation completed & became available

    # 4. Authority State
    resolution_state: SourceResolutionState    # RESOLVED, UNRESOLVED_FROZEN, or UNKNOWN

    # 5. Provenance & Audit
    provenance_ref: str                        # e.g. "TRANS_FIRST_CREATION_8_0", snapshot hash, or run ID
    diagnostic_reason: Optional[str] = None    # Descriptive reason if UNRESOLVED_FROZEN or UNKNOWN
```

### 4.2 Tri-State Semantics (`SourceResolutionState`)

```python
class SourceResolutionState(Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED_FROZEN = "UNRESOLVED_FROZEN"
    UNKNOWN = "UNKNOWN"
```

1. **`RESOLVED`**:
   - The upstream engine processed completed candles up to or beyond `effective_source_boundary`.
   - `is_unresolved == False` across all ingested candles through `effective_source_boundary`.
   - The member is actively present in `current_eligible_set`.
   - No superseding or invalidating transitions (`SET_REPLACEMENT`, `CHOCH_INVALIDATION`) have occurred prior to or at `effective_source_boundary`.
   - Maps to `True` in `MatchingContext.source_resolution_status[member_key]`.

2. **`UNRESOLVED_FROZEN`**:
   - The upstream engine encountered an unresolved ambiguity (`is_unresolved == True` or `last_transition.transition_type == BLOCKED_UNRESOLVED`) at or before `effective_source_boundary`.
   - Or the member belongs to an incomplete/tentative structure.
   - Maps to `False` in `MatchingContext.source_resolution_status[member_key]`.

3. **`UNKNOWN`**:
   - No resolution record exists for the member, or the record fails scope validation (cross-symbol, cross-timeframe, cross-feed, or cross-run mismatch).
   - Or record availability time is in the future relative to evaluation time ($T_{\text{avail}} > T_{\text{eval}}$).
   - Maps to **omission** from `MatchingContext.source_resolution_status` (key not present).

### 4.3 Scope Non-Transitivity & Isolation

Resolution authority is non-transitive:
- Authority for `(EURUSD, D1, ENGINE_EURUSD_D1, RUN_A)` **cannot** authorize `(EURUSD, H4)` or `(GBPUSD, D1)`.
- Authority for `RUN_A` **cannot** authorize `RUN_B`.
- Authority for member `SET_1:TJL1` **cannot** authorize member `SET_1:TJL2_A_PLUS`. Each member requires independent resolution verification.

### 4.4 Causal Availability vs. Effective Boundary

- **Effective Source Boundary ($T_{\text{source\_close}}$)**: The close time of the source candle that established the member.
- **Evidence Available Time ($T_{\text{avail}}$)**: The timestamp when the resolution evidence was emitted and became accessible to downstream consumers ($T_{\text{avail}} \ge T_{\text{source\_close}}$).
- **Evaluation Time ($T_{\text{eval}}$)**: The timestamp of candidate matching.
- **Causal Rule**: Resolution evidence is valid for evaluation at $T_{\text{eval}}$ **if and only if**:
  $$T_{\text{avail}} \le T_{\text{eval}}$$
  Any record with $T_{\text{avail}} > T_{\text{eval}}$ is future knowledge and must be treated as `UNKNOWN` for evaluation at $T_{\text{eval}}$.

### 4.5 Duplicate & Conflict Handling

When processing multiple resolution records for the same `member_key`:
1. **Identical Records**: Deduplicated idempotently.
2. **Conflicting Records**: If two records for the same `member_key` report different states (e.g., one asserts `RESOLVED` and another asserts `UNRESOLVED_FROZEN` for the same evaluation window):
   - Fail-closed rule: The conflict is unresolvable.
   - Demote state to `UNKNOWN` or reject the batch with diagnostic `CONFLICTING_SOURCE_RESOLUTION_AUTHORITY`. Under no circumstances may optimistic `RESOLVED` status be selected in a conflict.

### 4.6 Supersession & Stale Authority Prevention

When an upstream `SET_REPLACEMENT` or `CHOCH_INVALIDATION` transition occurs:
1. The predecessor set transitions into `historical_sets`.
2. Any previously emitted `RESOLVED` status for the predecessor member (e.g. `SET_1:TJL1`) is **superseded**.
3. It cannot authorize candidate generation for evaluation times occurring after the replacement/invalidation event.
4. Predecessor resolution authority **never transfers** to the successor set (`SET_2:TJL1`). The successor set requires fresh resolution authority based on its own establishing candle close.

---

## 5. Fail-Closed Mapping to Confirmation Pair Matcher

The mapping from `ProposedSourceResolutionRecord` to `MatchingContext.source_resolution_status` directly drives the accepted fail-closed branches in `ConfirmationPairMatcher`:

```text
+------------------------------------+------------------------------------+------------------------------------------+------------------------------+
| Resolution Record State            | Context Mapping                    | Matcher Diagnostic Reason                | Matcher Match Status         |
+------------------------------------+------------------------------------+------------------------------------------+------------------------------+
| RESOLVED                           | member_key: True                   | None (Passes Gate 1)                     | Evaluates Subsequent Gates   |
| UNRESOLVED_FROZEN                  | member_key: False                  | BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY     | BLOCKED (0 candidates)       |
| UNKNOWN (missing / future / scope) | member_key absent                  | UNKNOWN_SOURCE_RESOLUTION_AUTHORITY      | BLOCKED (0 candidates)       |
| Conflicting Records                | member_key absent / False          | UNKNOWN_SOURCE_RESOLUTION_AUTHORITY      | BLOCKED (0 candidates)       |
| Superseded Member                  | member_key absent / False          | UNKNOWN_SOURCE_RESOLUTION_AUTHORITY      | BLOCKED (0 candidates)       |
+------------------------------------+------------------------------------+------------------------------------------+------------------------------+
```

### 5.1 Verification in `ConfirmationPairMatcher` (Accepted Code Reference)
In `src/aladeen/strategy/confirmation_pair_matcher.py` (lines 182-194):
```python
# Explicit source resolution authority check (fail closed if unknown or unresolved)
if activation.member_key not in context.source_resolution_status:
    rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY)
    diagnostic_messages.append(
        f"Member {activation.member_key} lacks explicit source_resolution_status in context"
    )
elif context.source_resolution_status[activation.member_key] is not True:
    rejection_reasons.append(ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY)
    diagnostic_messages.append(
        f"Source calculation for member {activation.member_key} is marked unresolved"
    )
```
Lines 386-391:
```python
if (
    ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP in rejection_reasons
    or ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY in rejection_reasons
    or ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY in rejection_reasons
):
    status = ConfirmationMatchStatus.BLOCKED
```

---

## 6. Traceable Acceptance Inventory

The acceptance inventory partitions test evidence into four distinct categories:

### 6.1 Category A: Existing Executable Evidence (74 Tests)
- **Modular Integration Suite (14 Tests)** in `tests/test_source_candidate_authority_*.py`:
  - `test_valid_activation_and_confirmation_produces_candidate` (valid integration chain)
  - `test_rearm_lifecycle_invariance` (rearm history preservation)
  - `test_genuine_replacement_integration` (genuine physical replacement)
  - `test_synthetic_same_level_persistence_contract` (synthetic contract separation)
  - `test_repeated_result_equality` (deterministic equality)
  - `test_disjoint_physical_ids_prevent_cross_role_contamination` (disjoint ID safety)
  - `test_future_usage_at_registration_is_rejected` (future usage guard at registration)
  - `test_future_usage_at_evaluation_is_rejected` (future usage guard at evaluation)
  - `test_future_coverage_blocks_candidate` (future coverage guard through matcher)
  - `test_conflicting_authority_isolation_with_valid_control` (clean control vs conflict)
  - `test_expanded_interval_reuse_rejected` (interval expansion guard)
  - `test_empty_source_resolution_authority_blocks_candidate` (empty source resolution regression)
- **Main Authority Builder Suite (60 Tests)** in `tests/test_authority_context_builder.py`:
  - Unit tests for coverage preprocessor, usage preprocessor, trust configuration, and binding validation.

### 6.2 Category B: Proposed Synthetic Resolution Contracts (12 Proposed Cases)
Specific test contracts verifying `ProposedSourceResolutionRecord` handling:
1. `SRC-RES-01`: Valid `RESOLVED` record maps to `True` in `source_resolution_status`.
2. `SRC-RES-02`: Explicit `UNRESOLVED_FROZEN` record maps to `False` in `source_resolution_status`.
3. `SRC-RES-03`: Missing record for member maps to absent key.
4. `SRC-RES-04`: Record with `evidence_available_time > evaluation_time` maps to absent key (future authority rejection).
5. `SRC-RES-05`: Record with cross-symbol mismatch (e.g. `GBPUSD` vs `EURUSD`) rejected fail-closed.
6. `SRC-RES-06`: Record with cross-timeframe mismatch (e.g. `H4` vs `D1`) rejected fail-closed.
7. `SRC-RES-07`: Record with cross-engine mismatch rejected fail-closed.
8. `SRC-RES-08`: Record with cross-run mismatch rejected fail-closed.
9. `SRC-RES-09`: Identical duplicate records deduplicated idempotently without diagnostic error.
10. `SRC-RES-10`: Contradictory duplicate records (`RESOLVED` vs `UNRESOLVED_FROZEN`) rejected fail-closed as conflict.
11. `SRC-RES-11`: Resolution for `TJL1` does not authorize `TJL2_A_PLUS` in the same set.
12. `SRC-RES-12`: Superseded member from predecessor set loses `RESOLVED` status upon successor set creation.

### 6.3 Category C: Proposed Integration Cases (4 Proposed Cases)
Integration of source-resolution authority with coverage and usage authority:
1. `SRC-INT-01`: Clean 3-way authority (Valid Source Resolution + COMPLETE Coverage + UNUSED Usage) produces valid candidate.
2. `SRC-INT-02`: Clean Coverage + Clean Usage, but `UNRESOLVED_FROZEN` Source Resolution $\rightarrow$ `BLOCKED`, 0 candidates.
3. `SRC-INT-03`: Clean Coverage + Clean Usage, but `UNKNOWN` Source Resolution $\rightarrow$ `BLOCKED`, 0 candidates.
4. `SRC-INT-04`: Replacement lifecycle: Set 1 resolved, then Set 2 replaced $\rightarrow$ Set 1 blocked as superseded, Set 2 evaluated under fresh resolution authority.

### 6.4 Category D: Blocked Upstream Gaps (4 Blocked Cases)
Features that cannot be implemented without live external infrastructure:
1. `SRC-GAP-01`: Asynchronous multi-process cursor synchronization across independent Python processes.
2. `SRC-GAP-02`: Real-time streaming bar updates from live MT5 terminal terminal connection.
3. `SRC-GAP-03`: Persistent cross-restart source resolution database ledger.
4. `SRC-GAP-04`: Live broker execution and order submission (strictly prohibited by `AGENTS.md`).

### 6.5 Category E: Negative False-Positive Controls (4 Mandatory Controls)
Decisive negative tests proving heuristics fail closed:
1. `FP-CTRL-01`: **Current-Set Presence Alone**: Inject a populated `current_eligible_set` from an engine where `is_unresolved = True`. Assert source resolution remains `UNRESOLVED_FROZEN`, matcher blocks, 0 candidates.
2. `FP-CTRL-02`: **Valid Geometry Alone**: Inject zones with valid finite prices (`lower_price < upper_price`) without upstream resolution record. Assert source resolution remains `UNKNOWN`, matcher blocks, 0 candidates.
3. `FP-CTRL-03`: **Closed Bar Alone**: Inject a completed candle where subsequent processing was ambiguous. Assert source resolution remains `UNRESOLVED_FROZEN`, matcher blocks, 0 candidates.
4. `FP-CTRL-04`: **Cursor Equality Alone**: Force `last_processed_index == last_received_index` while engine `is_unresolved = True`. Assert source resolution remains `UNRESOLVED_FROZEN`, matcher blocks, 0 candidates.

---

## 7. Field-to-Origin Mapping Table

Comprehensive tabular cross-reference connecting each field of the proposed resolution authority contract to its originating repository source:

| Proposed Contract Field | Originating Layer | Source Repository Path | Originating Field / Construct |
| :--- | :--- | :--- | :--- |
| `source_engine_id` | TJL Reducer / Snapshot | `src/aladeen/strategy/tjl_types.py` | `TJLSnapshot.source_engine_id` |
| `symbol_feed_id` | TJL Reducer / Snapshot | `src/aladeen/strategy/tjl_types.py` | `TJLSnapshot.symbol_feed_id` |
| `source_timeframe` | TJL Reducer / Snapshot | `src/aladeen/strategy/tjl_types.py` | `TJLSnapshot.source_timeframe` |
| `set_id` | Eligible Set | `src/aladeen/strategy/tjl_types.py` | `CurrentEligibleSet.set_id` |
| `role` | TJL Zone Label | `src/aladeen/strategy/tjl_types.py` | `TJLZone.label.value` (`TJL1`, `TJL2_A_PLUS`) |
| `member_key` | Activation Adapter | `src/aladeen/strategy/activation_types.py` | `format_member_key(set_id, role)` |
| `level_id` | Physical Level | `src/aladeen/strategy/tjl_types.py` | `StableLevelId` |
| `structural_epoch` | TJL Reducer | `src/aladeen/strategy/tjl_types.py` | `TJLSnapshot.structural_epoch` |
| `feed_id` | Session Coordinator | `src/aladeen/strategy/service.py` | `ActivationSessionCoordinator._bound_context_key[0]` |
| `run_id` | Session Coordinator | `src/aladeen/strategy/service.py` | `ActivationSessionCoordinator.current_run_id` |
| `sequence_domain` | Activation Engine | `src/aladeen/strategy/activation_types.py` | `SequenceDomain(feed_id, run_id)` |
| `source_config_id` | Coordinator Config | `src/aladeen/strategy/coordinator.py` | `MSMConfig` |
| `effective_source_boundary` | Eligible Set | `src/aladeen/strategy/tjl_types.py` | `CurrentEligibleSet.eligibility_available_time` |
| `evidence_available_time` | Synchronizer | `src/aladeen/strategy/activation_adapter.py` | `TJLSynchronizer.sync()` timestamp |
| `resolution_state` | Coordinator & Reducer | `src/aladeen/strategy/coordinator.py`, `tjl_reducer.py` | Derived from `!is_unresolved` & `transition_history` |
| `provenance_ref` | Transition Record | `src/aladeen/strategy/tjl_types.py` | `TJLTransitionRecord` event identifier |

---

## 8. Unresolved Decisions & Open Questions

In compliance with `AGENTS.md` ("Document ambiguities as pending reconciliation with approved clarifications"):

1. **Resolution Preprocessor Placement**:
   - *Option A*: Create a dedicated `SourceResolutionPreprocessor` within `AuthorityContextBuilder` alongside `CoveragePreprocessor` and `UsagePreprocessor`.
   - *Option B*: Integrate resolution derivation directly into `TJLSynchronizer` when adapting snapshots into `ActivationEngine`.
   - *Status*: Recommended Option A for clean separation of concerns and matching the existing 6-step authority pipeline. Pending Perplexity concurrence.

2. **Upstream Inter-Engine Multi-Candle Resolution Horizon**:
   - *Question*: When `MSMChochCoordinator` processes candle $N$, does source-resolution authority for candle $N-k$ remain valid indefinitely until an invalidation transition occurs, or does it require periodic re-certification on every newly closed source bar?
   - *Status*: Structural engine semantics indicate that once established, an eligible set remains valid until superseded or invalidated by a transition (`SET_REPLACEMENT`, `CHOCH_INVALIDATION`). Awaiting confirmation during acceptance planning.

3. **Multi-Timeframe Cursor Alignment**:
   - *Question*: For higher-timeframe source (e.g. `D1`) and lower-timeframe confirmation (e.g. `H1`), the source candle closes once every 24 confirmation bars. Is resolution authority refreshed on every `H1` bar or only on `D1` bar boundaries?
   - *Status*: By definition, source resolution depends strictly on the source timeframe (`D1`). Confirmation bars evaluate against the latest established source resolution whose $T_{\text{avail}} \le T_{\text{eval}}$.

---

## 9. Strict Safety & Authority Boundary Enforcement

- **Strict Read-Only Execution**: Zero MT5 live trading calls, zero order execution, zero account modification, zero credential storage.
- **Zero Inventions**: No invented cursor protocols or automatic resolution heuristics. All mappings fail closed to `UNKNOWN` or `BLOCKED`.
- **Core Strategy Purity**: Core engines (`engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`, `types.py`, `validator.py`) and matcher (`confirmation_pair_matcher.py`) remain 100% untouched.
- **Protected Branch**: All work is restricted to `feature/confirmation-monitor`. No merge into `main`.
