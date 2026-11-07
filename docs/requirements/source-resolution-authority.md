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
1. **Define Verified-Through vs. Required Resolution Horizons**: Strictly decouple initial member establishment from continuous calculation validity, preventing stale `RESOLVED` records from authorizing later candidates across subsequent ambiguous candles.
2. **Specify Unambiguous Canonical Record Identity & Scope**: Establish length-prefixed canonical identifiers distinguishing full entity stream identity, immutable assertion identity (`assertion_seq`), and verified boundary.
3. **Formalize Causal Assertion Ordering for Unresolved Notices**: Explicitly define an assertion-sequence ordering (`assertion_seq`) that accommodates `BLOCKED_UNRESOLVED` receipt diagnostics without requiring advancing transition indices or relying on naive wall-clock comparisons.
4. **Define Verifiable Chained Transition-Prefix Extension**: Specify cryptographic cumulative prefix hashing with canonical JSON serialization, anchor binding, and explicit integrity vs. authority boundaries.
5. **Exhaustively Inspect Upstream State & Attribute Fields**: Categorize all claims across existing source fields, derived engineering identities, caller-supplied metadata, and missing contracts.
6. **Reject False-Positive Heuristics**: Establish strict boundaries proving that current-set presence alone, valid zone geometry alone, closed-bar status alone, and cursor equality alone do **not** prove source resolution.
7. **Define Code-Aligned Matcher Mappings**: Qualify decision matrix precedence with exact implemented blocking conditions.
8. **Catalogue Traceable Acceptance Inventory**: Group existing tests with exact node IDs, stable cases `SRC-RES-01` through `SRC-RES-23`, integration cases, and controls.
9. **Maintain Established Offline Baseline**: Reconcile authoritative 740-test suite execution.

---

## 2. Exhaustive Upstream State Inspection & Field Attribution

Every claim regarding upstream execution state is categorized and attributed to exact repository paths, classes, and fields.

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
| `TJLSnapshot` | `outgoing_cancellation_intent`| `bool` | `tjl_types.py:115` | Signals that predecessor set must be cancelled. |
| `TJLSnapshot` | `last_transition` | `Optional[TJLTransitionRecord]`| `tjl_types.py:116` | Most recent transition record. |
| `TJLSnapshot` | `transition_history` | `Tuple[TJLTransitionRecord, ...]`| `tjl_types.py:117`| Monotonic ledger of all state transitions. |
| `TJLSnapshot` | `is_unresolved` | `bool` | `tjl_types.py:118` | `True` if reducer is blocked or halted by ambiguity. |
| `TJLSnapshot` | `unresolved_diagnostic` | `Optional[str]` | `tjl_types.py:119` | Diagnostic reason for unresolved state. |
| `TJLSnapshot` | `last_processed_index` | `int` | `tjl_types.py:120` | Last candle index authoritatively reduced. |
| `TJLSnapshot` | `last_received_index` | `int` | `tjl_types.py:121` | Last candle index received. |
| `TJLSnapshot` | `structural_epoch` | `int` | `tjl_types.py:122` | Monotonic epoch incremented on direction-changing CHOCH. |
| `TJLTransitionRecord` | `transition_type` | `TJLTransitionType` | `tjl_types.py:97` | Enum: `FIRST_CREATION`, `SET_REPLACEMENT`, `CHOCH_INVALIDATION`, `CONTINUATION_RETAINED`, `LABELS_ONLY`, `IDEMPOTENT_NO_OP`, `BLOCKED_UNRESOLVED`. |
| `TJLTransitionRecord` | `outgoing_cancelled_set_id` | `Optional[str]` | `tjl_types.py:103`| Exact predecessor set ID invalidated/replaced by this transition. |
| `TJLTransitionRecord` | `transition_time` | `Optional[datetime]` | `tjl_types.py:102` | Timestamp of transition; **Optional[datetime]** (may be None if source timestamp is absent). |
| `CurrentEligibleSet` | `eligibility_available_time` | `Optional[datetime]` | `tjl_types.py:84` | Timestamp when the set became eligible; **Optional[datetime]**. If None, availability remains unknown fail-closed. |

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
| `TJLSynchronizer.sync()` | Receipt Diagnostic Handling | Code Logic | `activation_adapter.py:344-351` | **Key Finding**: Explicitly permits `last_transition.transition_type == BLOCKED_UNRESOLVED` as a receipt diagnostic that is **NOT required to be in transition_history**. |
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
| `ActivationSessionCoordinator` | `_bound_context_key` | `Optional[Tuple]` | `service.py:137` | 6-tuple: `(data_source, engine_id, symbol, timeframe, start_candle_time, calculation_mode)`. **Note**: Element 0 is `data_source` (e.g. `"MT5"` or `"SYNTHETIC"`), NOT `feed_id`. |

---

## 3. Separation of Resolution Horizons: Establishment vs. Continuous Validity

### 3.1 The Staleness Problem: Establishment Time $\ne$ Resolution Horizon
In prior drafts, `effective_source_boundary` was defined solely as the source candle close establishing the member (e.g. candle 9 close).
Under that flawed definition, an authority record proving resolution through candle 9 close would continue authorizing candidates indefinitely into the future as long as `evidence_available_time <= evaluation_time`.
This is unsafe:
- A set forms at candle 9 ($T_9$).
- Candidate evaluation occurs at candle 15 ($T_{15}$).
- Between $T_9$ and $T_{15}$, the upstream engine may encounter an unresolved ambiguity at candle 12 ($T_{12}$), freezing the coordinator (`is_unresolved = True`).
- An old record establishing resolution at $T_9$ must **not** authorize candidate matching at $T_{15}$ when the engine is unresolved at $T_{12}$.

### 3.2 Four Distinct Temporal Horizons
The resolution-evidence contract specifies four separate temporal parameters:

1. **`member_establishment_time` (`Optional[datetime]`)**:
   - The close timestamp of the source candle where the eligible set was created (`CurrentEligibleSet.eligibility_available_time`). If `None`, availability remains unknown fail-closed.
2. **`verified_source_boundary` (`datetime`)**:
   - The exact source calculation timestamp through which resolution was authoritatively verified without unresolved ambiguity (`is_unresolved == False` and all received bars processed up to this close).
3. **`required_source_boundary` (`datetime`)**:
   - The source boundary required for a candidate evaluation at $T_{\text{eval}}$. Specifically, the close time of the latest closed source candle preceding or equal to $T_{\text{eval}}$.
4. **`evidence_available_time` (`datetime`)**:
   - The timestamp when the resolution evidence record was generated and made accessible to downstream consumers ($T_{\text{avail}} \ge T_{\text{verified}}$).

### 3.3 Horizon Provenance & Declaration
- In offline execution, `required_source_boundary` cannot be inferred from `last_received_index` or wall-clock (doing so would recreate the paused-feed false positive).
- It derives strictly from a declared canonical source schedule (`SourceScheduleDeclaration`) or an explicit offline candle collection with closed bar boundaries.

### 3.4 Complete Authorization Predicate
A resolution authority record authorizes candidate evaluation at $T_{\text{eval}}$ **if and only if** all of the following conditions are met:
1. **Scope & Configuration Concordance**: Full stream scope (`feed_id`, `run_id`, `data_source`, `source_engine_id`, `symbol_feed_id`, `source_timeframe`, `source_config_hash`, and `structural_epoch`) matches the target evaluation context.
2. **Transition Prefix Validity**: `transition_prefix_index` and `transition_prefix_hash` match active un-rewritten engine history.
3. **Temporal Validity**:
   $$T_{\text{avail}} \le T_{\text{eval}} \quad \text{AND} \quad T_{\text{verified}} \ge T_{\text{required\_boundary}}$$
4. **Active Current Membership**:
   $$\text{member\_key} \in \text{context.current\_members}$$
5. **Known Establishment**:
   $$\text{member\_establishment\_time is not None} \quad \text{AND} \quad \text{member\_establishment\_time} \le T_{\text{verified}}$$
6. **Unambiguous Engine State**:
   $$\text{resolution\_state} == \text{SourceResolutionState.RESOLVED} \quad \text{AND} \quad \text{is\_unresolved} == \text{False}$$
7. **Absence of Contradictions or Superseding Transitions**: No contradictory assertion or successor transition has invalidated the member.

If $T_{\text{verified}} < T_{\text{required\_boundary}}$, the record is **insufficient / stale**, and cannot authorize the evaluation. It is omitted from `source_resolution_status`. If the engine halted due to ambiguity prior to $T_{\text{required\_boundary}}$, the state is explicitly `UNRESOLVED_FROZEN`.

---

## 4. Strict Rejection of False-Positive Heuristics

To maintain mathematical integrity, four heuristics are formally rejected:

1. **Current-Set Presence Proves Resolution (REJECTED)**:
   - In `TJLReducer` and `MSMChochCoordinator`, an unresolved ambiguity (`is_unresolved = True` at index 15) does **not** erase `current_eligible_set` that was established earlier at index 8. The set remains populated in snapshot memory, but the engine is halted. Treating set presence alone as resolution would generate candidates on stale or unconfirmed structures while the engine is halted.
2. **Valid Zone Geometry Proves Resolution (REJECTED)**:
   - Finite prices (`lower_price < upper_price`) describe spatial price boundaries, not temporal validity, engine lifecycle state, or causal availability.
3. **A Closed Bar Proves Resolution (REJECTED)**:
   - A closed candle may trigger an ambiguous continuation reset, an out-of-order sequence rejection, or a blocked state in `ChochDetector`. The bar is closed, but the strategy state is unresolved.
4. **Cursor Equality Alone Proves Resolution (REJECTED)**:
   - `last_processed_index == last_received_index` (or `last_synced_transition_index == len(history) - 1`) merely indicates that the engine processed its received candle buffer. If the feed paused at candle 10, both indices are equal at 10, but that provides zero authority regarding candle 15 evaluation time. Furthermore, if the coordinator halted due to ambiguity at candle 10, both indices can still be equal at 10 while `is_unresolved = True`.

---

## 5. Proposed Source-Resolution Evidence Contract (`ProposedSourceResolutionRecord`)

### 5.1 Schema Definition

```python
@dataclass(frozen=True)
class ProposedSourceResolutionRecord:
    """Offline authority record establishing verified calculation resolution for a source member."""
    # 1. Identity & Schema Versioning
    record_id: str                             # Canonical immutable ID: format_source_resolution_record_id(...)
    schema_version: int                        # Schema version integer (e.g. 1)
    assertion_seq: int                         # Monotonic assertion sequence number within stream
    source_engine_id: str                      # Existing field: e.g. "ENGINE_EURUSD_D1"
    symbol_feed_id: str                        # Existing field: e.g. "EURUSD"
    source_timeframe: str                      # Existing field: e.g. "D1"
    set_id: str                                # Existing field: e.g. "SET_EURUSD_D1_UPWARD_1"
    role: str                                  # Existing field: "TJL1" or "TJL2_A_PLUS"
    member_key: str                            # Derived engineering identity: format_member_key(set_id, role)
    level_id: StableLevelId                    # Derived engineering identity: StableLevelId(...)
    structural_epoch: int                      # Existing field: TJLSnapshot.structural_epoch

    # 2. Scope & Domain Binding
    data_source: str                           # Caller-supplied: e.g. "MT5" or "SYNTHETIC"
    feed_id: str                               # Caller-supplied offline metadata
    run_id: str                                # Caller-supplied offline metadata: e.g. "RUN_20261107_01"
    sequence_domain: SequenceDomain            # Derived engineering identity: SequenceDomain(feed_id, run_id)
    source_config_hash: str                    # Derived engineering identity: hash of MSMConfig parameters

    # 3. Separate Temporal Horizons
    member_establishment_time: Optional[datetime]  # Existing field: CurrentEligibleSet.eligibility_available_time
    verified_source_boundary: datetime             # Verified through this source candle close
    evidence_available_time: datetime              # Caller-supplied offline availability timestamp

    # 4. Authority State
    resolution_state: SourceResolutionState    # RESOLVED, UNRESOLVED_FROZEN, or UNKNOWN

    # 5. Provenance & Chained History Integrity
    transition_prefix_index: int               # Existing field: index in transition_history (-1 for initial)
    transition_prefix_hash: str                # Chained SHA-256 hash of transitions [0..prefix_index]
    provenance_ref: str                        # Derived engineering string or caller-supplied batch ID
    diagnostic_reason: Optional[str] = None    # Descriptive reason if UNRESOLVED_FROZEN or UNKNOWN
```

### 5.2 Canonical Formatting Functions
In strict accordance with accepted strategy types:
1. **Canonical Member Key Encoding (`src/aladeen/strategy/activation_types.py:19`)**:
   ```python
   def format_member_key(set_id: str, role: str) -> str:
       return f"MK[{len(set_id)}:{set_id}][{len(role)}:{role}]"
   ```
   Example: `MK[4:SET1][4:TJL1]`.
2. **Canonical Record Identifier Encoding**:
   The record ID uniquely identifies the **specific assertion event** within the stream, incorporating `assertion_seq` so that subsequent assertions sharing the same `verified_source_boundary` do not collide:
   ```python
   def format_source_resolution_record_id(
       schema_version: int,
       feed_id: str,
       run_id: str,
       source_engine_id: str,
       member_key: str,
       assertion_seq: int,
       verified_iso: str,
   ) -> str:
       return (
           f"SRR[v{schema_version}]"
           f"[{len(feed_id)}:{feed_id}]"
           f"[{len(run_id)}:{run_id}]"
           f"[{len(source_engine_id)}:{source_engine_id}]"
           f"[{len(member_key)}:{member_key}]"
           f"[seq:{assertion_seq}]"
           f"[{len(verified_iso)}:{verified_iso}]"
       )
   ```

### 5.3 Tri-State Semantics (`SourceResolutionState`)
1. **`RESOLVED`**:
   - Upstream engine verified through `verified_source_boundary` with `is_unresolved == False`.
   - `verified_source_boundary >= required_source_boundary`.
   - Member is active in `current_eligible_set`.
   - No superseding or invalidating transitions have occurred.
   - Maps to `True` in `MatchingContext.source_resolution_status[member_key]`.
2. **`UNRESOLVED_FROZEN`**:
   - Upstream engine encountered ambiguity (`is_unresolved == True` or `BLOCKED_UNRESOLVED`) at or before `required_source_boundary`.
   - Maps to `False` in `MatchingContext.source_resolution_status[member_key]`.
3. **`UNKNOWN`**:
   - Missing record, scope mismatch, unproven engine, stale horizon, contradictory unordered assertions, or future knowledge ($T_{\text{avail}} > T_{\text{eval}}$).
   - Maps to **omission from `source_resolution_status`** (key absent).

### 5.4 Three Identity Layers & Disambiguation Rules
The contract strictly distinguishes three distinct identity concepts:
1. **Entity / History Stream Identity**: Defined by the complete scope tuple `(feed_id, run_id, data_source, source_engine_id, symbol_feed_id, source_timeframe, source_config_hash, structural_epoch, member_key)`. This represents the continuous state stream for a specific member across successive candle evaluations.
2. **Immutable Assertion Identity (`record_id`)**: The immutable identifier of a specific assertion event in that stream, distinguished by `assertion_seq`.
3. **Record Payload Equality**: Two records sharing the identical `record_id` must have identical payload attributes. If two records share the same `record_id` but differ in `resolution_state`, `level_id`, or `transition_prefix_index`, a **Conflicting Payload on Immutable Record ID** violation is detected $\rightarrow$ triggers diagnostic `CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY` and maps to absent key (`SRC-RES-19`).

#### Disambiguation of Stream Updates & Authoritative Ordering:
- **Separation of Assertion Order from Transition Prefix**:
  In `TJLSynchronizer.sync()` (lines 344-351), a `BLOCKED_UNRESOLVED` receipt diagnostic is explicitly permitted without being appended to `transition_history`. Therefore, an unresolved notice cannot be assumed to advance `transition_prefix_index`.
  - Authoritative ordering within a stream is established strictly by **`assertion_seq`** (a strictly increasing integer allocated per observation/calculation step in that stream).
  - Transition prefix index tracks finalized structural history; `assertion_seq` tracks sequential calculation notices.
- **Advancement of Verified Resolution**: Same stream, advancing `assertion_seq`, strictly advancing `verified_source_boundary` ($T_{\text{verified\_new}} > T_{\text{verified\_old}}$), advancing/equal `transition_prefix_index`, valid chained transition-prefix extension, and advancing $T_{\text{avail}}$. Supersedes earlier assertions.
- **Later Unresolved / Frozen Notice (Without Boundary Advancement)**:
  An upstream ambiguity encountered during the next bar leaves `verified_source_boundary` unchanged (frozen at prior completed bar), but produces a causally later `UNRESOLVED_FROZEN` record with an advancing assertion sequence ($assertion\_seq_{\text{new}} > assertion\_seq_{\text{old}}$) and distinct `record_id`.
  - **Decisive Invariant**: A causally later `UNRESOLVED_FROZEN` notice within the same stream **immediately demotes** the stream state to `UNRESOLVED_FROZEN` (maps to `False`) for any evaluation requiring a horizon beyond the freeze point. The earlier `RESOLVED` record **cannot survive** (`SRC-RES-18`, `SRC-RES-22`).
- **Unordered Contradictory Assertions vs. Proven Unresolved State**:
  - **Proven Unresolved State**: A causally ordered assertion with `resolution_state == UNRESOLVED_FROZEN` maps to **`False`** (`BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY`).
  - **Contradictory Unordered Assertions**: Competing records for the same stream and horizon that lack authoritative sequence ordering or carry identical `assertion_seq` with conflicting states map to **omission from mapping** (`UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`, `SRC-RES-10`, `SRC-RES-21`).

### 5.5 Canonical Serialization & Chained Transition-Prefix Extension
A hash of a prefix cannot be directly compared against a hash of a longer prefix. To enable deterministic, verifiable history extension:

1. **Scope Anchor Binding**:
   The transition hash chain is bound to an initial context anchor:
   $$\text{Anchor} = \text{SHA256}(\text{"ANCHOR:"} + \text{data\_source} + ":" + \text{feed\_id} + ":" + \text{run\_id} + ":" + \text{source\_engine\_id} + ":" + \text{symbol\_feed\_id} + ":" + \text{source\_timeframe} + ":" + \text{source\_config\_hash} + ":" + \text{str(structural\_epoch)})$$
2. **Empty History Representation**:
   For initial state with no transitions (`transition_prefix_index == -1`):
   $$H_{\text{prefix}}(-1) = \text{Anchor}$$
3. **Canonical Serialization of `TJLTransitionRecord` (`CanonicalJSON(T_i)`)**:
   - **Encoding**: UTF-8 encoded JSON with keys strictly sorted lexicographically (`sort_keys=True`) and compact separators (`","`, `":"` with zero extraneous whitespace).
   - **Timestamps**: Normalized UTC ISO-8601 with trailing `Z` and microsecond precision normalized (e.g. `YYYY-MM-DDTHH:MM:SS.000000Z`). `None` serialized as JSON `null`.
   - **Enums**: Serialized strictly as uppercase string values (`trans.transition_type.value`, e.g. `"SET_REPLACEMENT"`).
   - **Prices & Geometry**: Formatted as exact string representations (`f"{price:.6f}"`), preventing platform-dependent floating-point divergence.
   - **Null Values**: Serialized as JSON `null`.
4. **Chained Cumulative Hashing**:
   - Each transition record is hashed to a 64-character lowercase hexadecimal digest:
     $$H(T_i) = \text{SHA256}(\text{CanonicalJSON}(T_i).\text{encode('utf-8')})$$
   - Chaining step accumulates hex string digests:
     $$H_{\text{prefix}}(k) = \text{SHA256}((H_{\text{prefix}}(k-1) + ":" + H(T_k)).\text{encode('utf-8')})$$
5. **Prefix-Index Bounds**:
   $k \in [-1, N-1]$ where $N = \text{len}(\text{snapshot.transition\_history})$.
6. **Verification of Extension**:
   An update claiming transition index $m > k$ proves extension of the earlier prefix $k$ by supplying access to canonical transitions $T_{k+1} \dots T_m$ and iteratively verifying that accumulating from $H_{\text{prefix}}(k)$ yields $H_{\text{prefix}}(m)$, or by full recomputation over `snapshot.transition_history`.
   - If recomputation through index $k$ does not yield $H_{\text{prefix}}(k)$, an altered prefix is detected $\rightarrow$ triggers diagnostic `ALTERED_TRANSITION_HISTORY_PREFIX` and rejects fail-closed (`SRC-RES-20`).
7. **Integrity vs. Authority Distinction**:
   A valid transition-prefix hash proves only structural history immutability (integrity). It does **not** prove strategy authority. Strategy authority requires verifying that `CoordinatorSnapshot.is_unresolved == False` and that the eligible set was legitimately established under validated configuration.

---

## 6. Deterministic Fail-Closed Matcher Mapping

### 6.1 Conflict Handling: Deterministic Omission
If contradictory resolution records arrive for the same member key and evaluation window:
- Preprocessor emits diagnostic `CONFLICTING_SOURCE_RESOLUTION_AUTHORITY`.
- The member key is **omitted from `source_resolution_status`**.
- In `ConfirmationPairMatcher`, the absent key triggers `ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`, setting status to `ConfirmationMatchStatus.BLOCKED` (0 candidates emitted).

### 6.2 Supersession & Stale Membership: Two-Stage Rejection
When an upstream transition (`SET_REPLACEMENT` or `CHOCH_INVALIDATION`) occurs:
1. **Membership Gating (Gate 2, lines 174-180)**: The outgoing member is removed from `current_eligible_set` and transitions to `historical_sets`. When evaluating an activation bound to the outgoing member, `activation.member_key not in context.current_members` triggers:
   $$\text{rejection\_reasons.append(ConfirmationRejectionReason.MEMBERSHIP\_CANCELLED\_OR\_REPLACED)}$$
   The resolution gate (`else:` branch, lines 182-194) is **skipped**.
   At line 410, since `rejection_reasons` is non-empty, matcher status is set to:
   $$\text{status} = \text{ConfirmationMatchStatus.REJECTED} \quad \text{(0 candidates emitted)}$$
2. **Resolution Authority Expiry**: In addition, any prior `RESOLVED` status for the outgoing member expires; it is omitted from `source_resolution_status`.
Both stages are enforced. Resolution removal alone is not a substitute for membership validation.

### 6.3 Unknown-Time Invalidations: Structural Order Preservation
In `TJLTransitionRecord`, `transition_time` is `Optional[datetime]`. If upstream data sources omit candle timestamps:
- The transition remains authoritatively valid and ordered strictly by its index position in `transition_history`.
- In `activation_adapter.py`, cancellation events are sequenced via sequential integer sequence references (`sequence_ref`).
- **No fabricated timestamp is permitted or required** to make a transition or cancellation effective.

### 6.4 Matcher Decision Matrix

> [!NOTE]
> **Matrix Isolation Assumption**: This decision matrix isolates the named source-resolution condition with all other matcher gates held in their passing/neutral states (coverage COMPLETE, usage UNUSED, direction/timeframe concordant, touch sequence valid).
> In the accepted matcher, incomplete coverage (`context.coverage_status != COMPLETE`) appends `INCOMPLETE_COVERAGE` and produces `ConfirmationMatchStatus.REJECTED`.
> Status elevation to `ConfirmationMatchStatus.BLOCKED` occurs exclusively via the explicitly implemented blocking conditions:
> 1. `ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP`
> 2. `ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY`
> 3. `ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`
> 4. `evidence.has_unresolved_dependencies` or `ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY`

| Source Resolution Record Condition | Context Mapping | Matcher Rejection Reason | Match Status (Isolated) | Candidate Output |
| :--- | :--- | :--- | :--- | :--- |
| `RESOLVED` and $T_{\text{verified}} \ge T_{\text{req}}$ | `member_key: True` | None (Passes Gate 1) | Evaluates subsequent gates | Permitted if all pass |
| `UNRESOLVED_FROZEN` | `member_key: False` | `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY` | `BLOCKED` | 0 Candidates |
| `UNKNOWN` (missing / scope mismatch) | Key absent | `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY` | `BLOCKED` | 0 Candidates |
| Future Knowledge ($T_{\text{avail}} > T_{\text{eval}}$) | Key absent | `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY` | `BLOCKED` | 0 Candidates |
| Stale Boundary ($T_{\text{verified}} < T_{\text{req}}$) | Key absent | `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY` | `BLOCKED` | 0 Candidates |
| Contradictory Records | Key absent | `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY` | `BLOCKED` | 0 Candidates |
| Rewritten Transition Prefix | Key absent | `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY` | `BLOCKED` | 0 Candidates |
| Superseded Member | Absent from `current_members` | `MEMBERSHIP_CANCELLED_OR_REPLACED` | `REJECTED` | 0 Candidates |

---

## 7. Categorized Field-to-Origin Mapping

The mapping explicitly classifies every field into one of four origin categories:

| Proposed Field | Origin Category | Source Repository Path | Originating Construct / Details |
| :--- | :--- | :--- | :--- |
| `source_engine_id` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:108` | `TJLSnapshot.source_engine_id` |
| `symbol_feed_id` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:109` | `TJLSnapshot.symbol_feed_id` |
| `source_timeframe` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:110` | `TJLSnapshot.source_timeframe` |
| `set_id` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:72` | `CurrentEligibleSet.set_id` |
| `role` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:46` | `TJLZone.label.value` (`"TJL1"`, `"TJL2_A_PLUS"`) |
| `structural_epoch` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:122` | `TJLSnapshot.structural_epoch` |
| `member_establishment_time` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:84` | `CurrentEligibleSet.eligibility_available_time` (`Optional[datetime]`) |
| `transition_prefix_index` | **Existing Source Field** | `src/aladeen/strategy/tjl_types.py:117` | Index in `TJLSnapshot.transition_history` |
| `is_unresolved` | **Existing Source Field** | `src/aladeen/strategy/coordinator.py:23` | `CoordinatorSnapshot.is_unresolved` |
| `record_id` | **Derived Engineering Identity** | Proposed Contract Formatter | Canonical format: `format_source_resolution_record_id(...)` |
| `schema_version` | **Derived Engineering Identity** | Proposed Contract Version | Constant integer `1` |
| `member_key` | **Derived Engineering Identity** | `src/aladeen/strategy/activation_types.py:19` | `format_member_key(set_id, role)` -> `MK[len:set][len:role]` |
| `level_id` | **Derived Engineering Identity** | `src/aladeen/strategy/tjl_types.py:34` | `StableLevelId(symbol_feed_id, source_timeframe, bar_time, side)` |
| `sequence_domain` | **Derived Engineering Identity** | `src/aladeen/strategy/activation_types.py:88` | `SequenceDomain(feed_id, run_id)` |
| `source_config_hash` | **Derived Engineering Identity** | `src/aladeen/strategy/coordinator.py:12` | Deterministic hash of `MSMConfig` fields |
| `transition_prefix_hash` | **Derived Engineering Identity** | Proposed Prefix Hasher | Chained SHA-256 hash of transitions `[0..prefix_index]` |
| `provenance_ref` | **Derived Engineering Identity** | `src/aladeen/strategy/activation_adapter.py:402` | Formatted event ID (e.g. `f"EVT_TJL_TRANS_{type}_{idx}"`) |
| `data_source` | **Caller-Supplied Offline Metadata** | `src/aladeen/strategy/service.py:137` | `ActivationSessionCoordinator._bound_context_key[0]` (`"MT5"` or `"SYNTHETIC"`) |
| `feed_id` | **Caller-Supplied Offline Metadata** | Offline Request Specification | Explicit feed identifier (e.g. `"FEED_EURUSD"`) |
| `run_id` | **Caller-Supplied Offline Metadata** | `src/aladeen/strategy/service.py:133` | `ActivationSessionCoordinator._current_run_id` |
| `assertion_seq` | **Caller-Supplied Offline Metadata** | Observation Runner | Strictly monotonic integer sequence allocated per observation in stream |
| `evidence_available_time` | **Caller-Supplied Offline Metadata** | Offline Request Specification | Emitted calculation completion timestamp ($T_{\text{avail}}$) |
| `verified_source_boundary` | **Caller-Supplied Offline Metadata** | Offline Request Specification | Boundary timestamp through which resolution was calculated |
| `required_source_boundary` | **Caller-Supplied Offline Metadata** | Offline Schedule Specification | Required boundary derived from canonical schedule |
| Continuous Resolution Emitter | **Missing Upstream Contract** | Upstream Strategy Engine | Automated continuous horizon certification across live ticks |
| Live Multi-Process Cursor Sync| **Missing Upstream Contract** | Service Infrastructure | Distributed real-time lock-free cursor protocol |

---

## 8. Traceable Acceptance Inventory

The inventory preserves all original case meanings, adds new horizon, scope, update, integrity, and diagnostic cases under distinct IDs, and separates executable evidence from proposed planning.

### 8.1 Group 1: Existing Executable Test Items (74 Exact Node IDs)

#### Modular Integration Suite (14 Tests in `tests/test_source_candidate_authority_*.py`):
1. `tests/test_source_candidate_authority_binding.py::TestSourceCandidateAuthorityBinding::test_case_4_request_binding_rejects_cross_context_reuse`
2. `tests/test_source_candidate_authority_binding.py::TestSourceCandidateAuthorityBinding::test_case_5_conflicting_authority_isolated_to_affected_entity`
3. `tests/test_source_candidate_authority_boundaries.py::TestSourceCandidateAuthorityBoundaries::test_missing_or_future_usage_at_registration_blocks_candidates`
4. `tests/test_source_candidate_authority_boundaries.py::TestSourceCandidateAuthorityBoundaries::test_missing_or_future_usage_at_evaluation_blocks_candidates`
5. `tests/test_source_candidate_authority_boundaries.py::TestSourceCandidateAuthorityBoundaries::test_missing_or_future_coverage_at_evaluation_blocks_candidates`
6. `tests/test_source_candidate_authority_boundaries.py::TestSourceCandidateAuthorityBoundaries::test_later_arriving_certificate_cannot_authorize_earlier_evaluation`
7. `tests/test_source_candidate_authority_boundaries.py::TestSourceCandidateAuthorityBoundaries::test_empty_source_resolution_authority_blocks_candidate`
8. `tests/test_source_candidate_authority_boundaries.py::TestSourceCandidateAuthorityBoundaries::test_supplied_synthetic_authority_boundaries`
9. `tests/test_source_candidate_authority_chain.py::TestSourceCandidateAuthorityChain::test_chronological_authority_backed_schedule_end_to_end`
10. `tests/test_source_candidate_authority_equality.py::TestSourceCandidateAuthorityEquality::test_case_7_repeated_evaluations_produce_identical_outputs_and_immutable_inputs`
11. `tests/test_source_candidate_authority_rearm.py::TestSourceCandidateAuthorityRearm::test_genuine_rearm_lifecycle_asserts_terminal_predecessor_equality`
12. `tests/test_source_candidate_authority_replacement.py::TestSourceCandidateAuthorityReplacement::test_genuine_source_replacement_integration`
13. `tests/test_source_candidate_authority_replacement.py::TestSourceCandidateAuthorityReplacement::test_synthetic_same_level_replacement_contract`
14. `tests/test_source_candidate_authority_replacement.py::TestSourceCandidateAuthorityReplacement::test_synthetic_activation_used_metadata_consistency_contract`

#### Unit Authority Preprocessing Suite (60 Tests in `tests/test_authority_context_builder.py`):
- 60 distinct unit tests verifying `CoveragePreprocessor`, `UsagePreprocessor`, `TrustConfiguration`, and `AuthorityContextBuilder` request binding validation.

### 8.2 Group 2: Proposed Synthetic Resolution Contracts (23 Proposed Cases)
- `SRC-RES-01`: Valid `RESOLVED` record maps to `True` in `source_resolution_status`.
- `SRC-RES-02`: Explicit `UNRESOLVED_FROZEN` record maps to `False` in `source_resolution_status`.
- `SRC-RES-03`: Missing record for member maps to absent key.
- `SRC-RES-04`: Record with $T_{\text{avail}} > T_{\text{eval}}$ maps to absent key (future authority rejection).
- `SRC-RES-05`: Record with cross-symbol mismatch (`GBPUSD` vs `EURUSD`) rejected fail-closed.
- `SRC-RES-06`: Record with cross-timeframe mismatch (`H4` vs `D1`) rejected fail-closed.
- `SRC-RES-07`: Record with cross-engine mismatch rejected fail-closed.
- `SRC-RES-08`: Record with cross-run mismatch rejected fail-closed.
- `SRC-RES-09`: Identical duplicate records deduplicated idempotently without diagnostic error.
- `SRC-RES-10`: Contradictory duplicate records (`RESOLVED` vs `UNRESOLVED_FROZEN`) trigger diagnostic and map to absent key.
- `SRC-RES-11`: Resolution for `TJL1` does not authorize `TJL2_A_PLUS` in the same set.
- `SRC-RES-12`: Superseded member from predecessor set loses `RESOLVED` status upon successor set creation.
- `SRC-RES-13`: Stale resolution boundary ($T_{\text{verified}} < T_{\text{req}}$) maps to absent key.
- `SRC-RES-14`: Member with unknown establishment time (`eligibility_available_time is None`) remains unknown fail-closed.
- `SRC-RES-15`: Cross-feed mismatch (`FEED_A` vs `FEED_B`) rejected fail-closed.
- `SRC-RES-16`: Configuration hash mismatch (`source_config_hash`) rejected fail-closed.
- `SRC-RES-17`: Rewritten transition prefix hash mismatch rejected fail-closed.
- `SRC-RES-18`: Later `UNRESOLVED_FROZEN` notice with unchanged $T_{\text{verified}}$ but advancing transition index demotes stream to `UNRESOLVED_FROZEN` (earlier `RESOLVED` does not survive).
- `SRC-RES-19`: Conflicting payload under identical `record_id` triggers diagnostic `CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY` and maps to absent key.
- `SRC-RES-20`: Transition-prefix extension verification failure (hash mismatch on prefix recomputation) triggers `ALTERED_TRANSITION_HISTORY_PREFIX` and rejects fail-closed.
- `SRC-RES-21`: Equal-availability tie: at equal availability timestamps, an unresolved notice or invalidation takes deterministic fail-closed precedence over resolution.
- `SRC-RES-22`: Later unresolved assertion sharing verified boundary with distinct `assertion_seq`/`record_id` within the same stream demotes state to `UNRESOLVED_FROZEN` without triggering duplicate-ID corruption.
- `SRC-RES-23`: Assertion sequence order separates receipt diagnostic from transition index (receipt diagnostic increments `assertion_seq` while leaving `transition_prefix_index` unchanged, establishing authoritative order).

### 8.3 Group 3: Proposed Integration Cases (4 Proposed Cases)
- `SRC-INT-01`: Clean 3-way authority (Valid Source Resolution + COMPLETE Coverage + UNUSED Usage) produces valid candidate.
- `SRC-INT-02`: Clean Coverage + Clean Usage, but `UNRESOLVED_FROZEN` Source Resolution $\rightarrow$ `BLOCKED`, 0 candidates.
- `SRC-INT-03`: Clean Coverage + Clean Usage, but `UNKNOWN` Source Resolution $\rightarrow$ `BLOCKED`, 0 candidates.
- `SRC-INT-04`: Replacement lifecycle: Set 1 replaced by Set 2 $\rightarrow$ Set 1 rejected at Gate 2 (`MEMBERSHIP_CANCELLED_OR_REPLACED`), Set 2 evaluated under fresh resolution authority.

### 8.4 Group 4: Negative False-Positive Controls (4 Cases)
- `FP-CTRL-01`: **Current-Set Presence Alone (Synthetic)**: Inject populated `current_eligible_set` from an engine where `is_unresolved = True`. Assert source resolution remains `UNRESOLVED_FROZEN`, matcher blocks, 0 candidates.
- `FP-CTRL-02`: **Valid Geometry Alone (Synthetic)**: Inject zones with valid finite prices (`lower_price < upper_price`) without upstream resolution record. Assert source resolution remains `UNKNOWN`, matcher blocks, 0 candidates.
- `FP-CTRL-03`: **Closed Bar Alone (Candle-Driven)**: Ingest real candle sequence where a closed candle triggers `ChochDiagnosticType.BLOCKED_BY_UNRESOLVED_STATE`. Assert resolution remains `UNRESOLVED_FROZEN`, matcher blocks, 0 candidates.
- `FP-CTRL-04`: **Cursor Equality Alone (Synthetic)**: Force `last_processed_index == last_received_index` while engine `is_unresolved = True`. Assert source resolution remains `UNRESOLVED_FROZEN`, matcher blocks, 0 candidates.

### 8.5 Group 5: Blocked Upstream Gaps (4 Blocked Cases)
- `SRC-GAP-01`: Asynchronous multi-process cursor synchronization across independent Python processes.
- `SRC-GAP-02`: Real-time streaming bar updates from live MT5 terminal connection.
- `SRC-GAP-03`: Persistent cross-restart source resolution database ledger.
- `SRC-GAP-04`: Live broker execution and order submission (strictly prohibited by `AGENTS.md`).

---

## 9. Established Offline Test Boundary & Alternate Execution Record

### 9.1 Established Offline Test Boundary (Authoritative)
The established offline repository test suite uses the accepted 8 browser-controlled and runner exclusions:
```bash
python -m pytest tests/ \
  --ignore=tests/test_tjl_browser_controlled.py \
  --ignore=tests/test_iss_browser_controlled.py \
  --ignore=tests/test_activation_browser_controlled.py \
  --ignore=tests/activation_browser_runner.py \
  --ignore=tests/activation_browser_harness.py \
  --ignore=tests/test_browser_race_controlled.py \
  --ignore=tests/test_choch_browser_verification.py \
  --ignore=tests/browser_check.py \
  -q
```
- **Authoritative Passed Test Count**: **740 / 740 passed** in 39.29s.
- This represents the exact offline regression boundary accepted in Milestone 36. Zero tests were added or removed in this documentation-only milestone.

### 9.2 Author-Reported Alternate Execution (Informational)
- An alternate exploratory run excluding live MT5/service files executed 742 passed tests.
- This alternate execution is recorded purely as an exploratory run; it is **not** the accepted baseline. The authoritative offline suite remains the established 8-exclusion command producing 740 tests.

---

## 10. Unresolved Decisions & Open Questions

In compliance with `AGENTS.md`:
1. **Resolution Preprocessor Placement**:
   - Recommend creating a dedicated `SourceResolutionPreprocessor` inside `AuthorityContextBuilder` alongside `CoveragePreprocessor` and `UsagePreprocessor`. Awaiting Perplexity concurrence before implementation.
2. **Upstream Multi-Candle Resolution Horizon Protocol**:
   - Whether upstream engine coordinator will formally emit a `verified_source_boundary` field on snapshots or if caller provides verified boundary based on completed candle ingestion history.
3. **Multi-Timeframe Cursor Alignment**:
   - Higher-timeframe source resolution (e.g. `D1`) evaluates against confirmation bars (`H1`) by certifying the source boundary through the most recently closed `D1` candle prior to each `H1` evaluation time.

---

## 11. Strict Safety & Authority Boundary Enforcement

- **Strict Read-Only Execution**: Zero MT5 live trading calls, zero order execution, zero account modification, zero credential storage.
- **Zero Inventions**: No invented cursor protocols or automatic resolution heuristics. All mappings fail closed to `UNKNOWN` or `BLOCKED`.
- **Core Strategy Purity**: Core engines (`engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`, `types.py`, `validator.py`) and matcher (`confirmation_pair_matcher.py`) remain 100% untouched (**0 diff**).
- **Protected Branch**: All work is restricted to `feature/confirmation-monitor`. Never merge into `main`.
