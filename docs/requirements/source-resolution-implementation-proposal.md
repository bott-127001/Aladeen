# Milestone 38 Implementation Proposal: Source-Resolution Authority Architecture & Verification Plan (Revised — HANDOFF-135)

**Status**: Documentation-Only Implementation Proposal (Awaiting Review & Approval Before Implementation)  
**Accepted Requirements Baseline**: Commit `8ea1ec2fdd8e9b699f4dbbc86d71a10a6e2a3e44` (Milestone 37 / HANDOFF-132)  
**Accepted Executable Baseline**: Commit `600925471e1fc56d01ba6621ed86f728d7eb76a0` (Milestone 36 / HANDOFF-125)  
**Branch**: `feature/confirmation-monitor`  
**Safety Boundary**: Strict read-only market data retrieval. Zero live MT5 broker trading, zero order execution, zero account modification, zero filesystem ledger writes, zero database storage, zero network ingestion, zero candidate ranking/arbitration, zero final signal publication, zero runtime preprocessor code in this proposal.

---

## 1. Architectural Scope & Objective

Milestone 37 established the formal requirements, canonical record definitions, scope-isolated identifiers, deterministic serialization rules, and acceptance inventory for upstream source-resolution authority (`docs/requirements/source-resolution-authority.md`).

The objective of Milestone 38 (HANDOFF-135 Revision) is to provide an exact, bounded implementation proposal establishing:
1. **Concrete Evidence Composition & Observation Binding**: Concrete composition of `CoordinatorSnapshot` and `TJLSnapshot` with observation metadata in an immutable evidence bundle.
2. **Independent Immutable Evaluation Context**: Definition of `SourceResolutionRequestContext` and strictly immutable, permutation-invariant `SourceResolutionResult`.
3. **Phase 1 Trust Model & Positive Output Limits**: Explicit synthetic offline contract scope with clear non-claims regarding live upstream resolution derivation.
4. **Complete Positive Authorization Gate & Deterministic Precedence**: Exhaustive 12-gate prerequisite pipeline and clear distinction between `False` (valid unresolved) and omitted/`UNKNOWN` (invalid/mismatched/stale/conflicting).
5. **As-Of Evidence Selection & Historical Invariance**: Temporal filtering ensuring future assertions cannot rewrite or demote historical evaluations.
6. **Reconciled Full 25-Case Inventory**: All 25 resolution contracts (`SRC-RES-01` through `SRC-RES-25`) including member isolation and predecessor supersession, plus supporting structural assertions.
7. **Tightened Phase 1 File Allowlist**: Strict 4-file boundary with zero modification to accepted strategy engines, adapter, or matcher.

---

## 2. Evidence Composition & Independent Evaluation Context

### 2.1 Approved Component Placement: Standalone Evaluator (Option B)
- **Module Path**: `src/aladeen/strategy/source_resolution.py`
- **Rationale**: Isolates validation logic outside accepted adapter and matcher code, avoids modifying existing adapter logic, and allows isolated contract testing.
- **Scope Restriction**: Placement approval only. Production adapter integration, runtime service wiring, and automated derivation remain unapproved and deferred.

### 2.2 Concrete Upstream Evidence Composition (`SourceResolutionEvidenceBundle`)
Upstream state contracts span distinct engine layers:
- `CoordinatorSnapshot` (`aladeen.strategy.coordinator`) provides coordinator-level resolution state (`is_unresolved`, `unresolved_diagnostic`).
- `TJLSnapshot` (`aladeen.strategy.tjl_coordinator`) provides structural member identity, active sets (`current_eligible_set`), transition history (`transition_history`), and `structural_epoch`.

Neither class is modified with new fields. Instead, the offline evaluation framework composes them into an immutable evidence bundle with explicit observation binding:

```python
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import FrozenSet, Mapping, Sequence, Tuple
from aladeen.strategy.coordinator import CoordinatorSnapshot
from aladeen.strategy.tjl_coordinator import TJLSnapshot

@dataclass(frozen=True)
class SourceResolutionEvidenceBundle:
    """Concrete composition of upstream observations and bound context."""
    coordinator_snapshot: CoordinatorSnapshot   # Coordinator observation (aladeen.strategy.coordinator)
    tjl_snapshot: TJLSnapshot                   # TJL observation (aladeen.strategy.tjl_coordinator)
    observation_feed_id: str                    # Common observation binding
    observation_symbol: str
    observation_timeframe: str
    observation_run_id: str
    observation_time: datetime
```

#### Observation Binding & Mismatch Rejection:
The evaluator verifies internal consistency between the snapshots and the observation metadata:
1. `tjl_snapshot.source_engine_id == request.expected_source_engine_id`
2. `tjl_snapshot.symbol_feed_id == request.expected_symbol_feed_id`
3. `tjl_snapshot.source_timeframe == request.expected_source_timeframe`
4. `tjl_snapshot.structural_epoch == request.expected_structural_epoch`
5. `bundle.observation_feed_id == request.expected_feed_id`
6. `bundle.observation_symbol == request.expected_symbol_feed_id`
7. `bundle.observation_timeframe == request.expected_source_timeframe`
8. `bundle.observation_run_id == request.expected_run_id`

Any mismatch or internal contradiction emits diagnostic `EVIDENCE_OBSERVATION_MISMATCH` and fails closed (all keys omitted).

### 2.3 Independent Immutable Evaluation Context (`SourceResolutionRequestContext`)
A record cannot be validated against claims copied from that record itself. An independent caller-provided evaluation context supplies expected scope, evaluation horizons, evidence bundles, and mandatory trust configuration:

```python
@dataclass(frozen=True)
class SourceResolutionTrustConfig:
    """Explicit trust configuration for offline contract evaluation."""
    allow_synthetic_records: bool = True
    enforce_microsecond_precision: bool = True
    require_monotonic_assertions: bool = True

@dataclass(frozen=True)
class SourceResolutionRequestContext:
    """Independent immutable evaluation context providing expected scope and authoritative evidence."""
    # 1. Independent Expected Scope (Must NOT be copied from incoming records)
    expected_data_source: str
    expected_feed_id: str
    expected_run_id: str
    expected_source_engine_id: str
    expected_symbol_feed_id: str
    expected_source_timeframe: str
    expected_source_config_hash: str
    expected_structural_epoch: int

    # 2. Temporal & Evaluation Horizons
    evaluation_time: datetime
    required_source_boundary: datetime

    # 3. Authoritative Evidence & Bounds (Mandatory; None strictly prohibited)
    expected_member_universe: Tuple[str, ...]                  # Expected member keys to evaluate
    evidence_bundle: SourceResolutionEvidenceBundle            # Concrete composition of upstream observations
    declared_anchor_payload: bytes                             # Length-prefixed anchor bytes for prefix hash validation
    trust_config: SourceResolutionTrustConfig                  # Mandatory trust config; None strictly rejected fail-closed
```

### 2.4 Evaluator Interface & Deep Defensive Immutability
```python
@dataclass(frozen=True)
class SourceResolutionResult:
    """Strictly immutable result container invariant under input record permutations."""
    status_map: MappingProxyType[str, bool]           # Immutable mapping wrapping defensive dictionary copy
    diagnostics: Tuple[SourceDiagnostic, ...]         # Deterministically sorted tuple of diagnostics
    omitted_keys: FrozenSet[str]                      # Immutable frozenset of omitted/unknown keys

class SourceResolutionEvaluator:
    """Pure offline evaluator validating source resolution records against independent request context."""
    def evaluate_records(
        self,
        request: SourceResolutionRequestContext,
        records: Sequence[SourceResolutionRecord],
    ) -> SourceResolutionResult:
        ...
```

- **Deep Defensive Immutability**:
  - `status_map` wraps a defensive copy in `types.MappingProxyType`.
  - Diagnostics and omitted keys are defensively converted to immutable tuples/frozensets.
  - Diagnostics and omitted keys are deterministically sorted so identical inputs in any permutation produce byte-identical results.

---

## 3. Phase 1 Trust Model & Limits of Positive Output

### 3.1 Explicit Phase 1 Trust Scope
- **Synthetic Offline Contract Evaluator**: Phase 1 is strictly an offline synthetic contract evaluator verifying that supplied record payloads conform to canonical specifications, match independent context expectations, and satisfy snapshot invariants under declared fixture/issuer assumptions.
- **Limits of Positive Output (`True`)**:
  - A `True` result emitted in `status_map` indicates **validation under declared offline contract assumptions**.
  - It does **not** establish live upstream resolution derivation, live tick certification, or operational multi-candle broker execution authority.
- **Fail-Closed Missing Trust Binding**:
  - If `request.trust_config is None` or `request.evidence_bundle is None`, the evaluator strictly rejects fail-closed with diagnostic `TRUST_CONFIGURATION_MISSING` or `EVIDENCE_BUNDLE_MISSING`. All keys in `expected_member_universe` are omitted (`UNKNOWN`). Permissive defaults are strictly forbidden.

---

## 4. Complete Positive Authorization Gate & Deterministic Precedence

### 4.1 Exhaustive 12-Point Positive Authorization Gate
A member key can **NEVER** emit `True` in `status_map` unless **ALL** 12 of the following mandatory prerequisites are satisfied simultaneously:

1. **Independent Scope Match**:
   `record.data_source == request.expected_data_source`, `record.feed_id == request.expected_feed_id`, `record.run_id == request.expected_run_id`, `record.source_engine_id == request.expected_source_engine_id`, `record.symbol_feed_id == request.expected_symbol_feed_id`, `record.source_timeframe == request.expected_source_timeframe`, `record.source_config_hash == request.expected_source_config_hash`, `record.structural_epoch == request.expected_structural_epoch`.
2. **Observation Binding Match**: Evidence bundle attributes match request context expectations across symbol, feed, timeframe, run, and epoch.
3. **Canonical Anchor Validation**: `request.declared_anchor_payload` strictly equals the canonical anchor recomputed from expected context via `format_transition_anchor_payload(...)`. Arbitrary or mismatched anchor bytes are rejected fail-closed.
4. **Record Resolution State**: `record.resolution_state == SourceResolutionState.RESOLVED`.
5. **Known Member Establishment Time**: Active member establishment time is known (`eligibility_available_time is not None`) and occurred on or before verified boundary ($T_{\text{est}} \le T_{\text{verified}}$). Missing establishment time rejects fail-closed (`SRC-RES-14`).
6. **Active Member Geometry & Level Identity**: Set ID, role, member key, physical level ID, and zone geometry (`lower_price`, `upper_price`) in record strictly agree with the active member in `evidence_bundle.tjl_snapshot.current_eligible_set`.
7. **Member Isolation & Predecessor Supersession**: Resolution for member A (`TJL1`) strictly isolates from member B (`TJL2`) (`SRC-RES-11`). Superseded member from predecessor set loses `RESOLVED` status upon successor set creation (`SRC-RES-12`).
8. **Authoritative Engine Resolution State**:
   `evidence_bundle.coordinator_snapshot.is_unresolved == False` AND `evidence_bundle.tjl_snapshot.is_unresolved == False`.
9. **Temporal Horizons & Declared Schedule Provenance**:
   - `record.evidence_available_time <= request.evaluation_time` ($T_{\text{avail}} \le T_{\text{eval}}$).
   - `record.verified_source_boundary >= request.required_source_boundary` ($T_{\text{verified}} \ge T_{\text{req}}$).
   - Required boundary retains its declared offline schedule/collection provenance.
10. **Transition History Prefix Cryptographic Integrity**:
    The evaluator recomputes the prefix hash chain from the verified canonical anchor across transitions `0..record.transition_prefix_index` from `evidence_bundle.tjl_snapshot.transition_history`. Recomputed hash strictly matches `record.transition_prefix_hash` (`SRC-RES-20`).
11. **Single Deterministic Serialization & Formatting Integrity**:
    - `record.record_id` strictly matches `format_source_resolution_record_id(...)` incorporating full 9-component stream scope, `assertion_seq`, and canonical UTC `verified_iso`.
    - Prices must be strictly finite Python `float` values (`math.isfinite(price) == True`), serialized with `repr(price)` (`SRC-RES-25`). Non-finite floats or silent coercion reject fail-closed.
    - Timestamps must be timezone-aware UTC, formatted with `Z`, preserving microseconds losslessly.
12. **Absence of Applicable Conflicting or Later Unresolved Demoting Notices**:
    - No contradictory duplicate payload under the same `record_id` (`CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY`).
    - No causally later `UNRESOLVED_FROZEN` notice within the stream available *as of evaluation time* ($assertion\_seq_{\text{new}} > assertion\_seq_{\text{old}}$).

### 4.2 Deterministic Precedence: `False` vs. Omission (`UNKNOWN`)
To prevent invalid records from becoming authoritative merely by carrying an unresolved label:
- **`False` (`UNRESOLVED_FROZEN`)**: Emitted **only** when evidence is valid, matches scope, verified boundary meets or freezes at known point, and is available as-of evaluation time with `is_unresolved == True` or `resolution_state == UNRESOLVED_FROZEN`.
- **Omission from `status_map` (`UNKNOWN`)**: Emitted for missing records, scope mismatches, observation mismatches, corrupt hashes, non-finite prices, naive timestamps, stale horizons ($T_{\text{verified}} < T_{\text{req}}$), future availability ($T_{\text{avail}} > T_{\text{eval}}$), or unordered conflicting payloads.

---

## 5. As-Of Evidence Selection & Historical Invariance

### 5.1 As-Of Selection Pipeline
Before sorting, deduplicating, or evaluating causal sequences, the evaluator applies strict as-of temporal filtering:
$$\text{Eligible Records} = \{ r \in \text{records} \mid r.\text{evidence\_available\_time} \le \text{request}.\text{evaluation\_time} \}$$

- Records with $r.\text{evidence\_available\_time} > \text{request}.\text{evaluation\_time}$ are categorized as future knowledge. They emit diagnostic `FUTURE_EVIDENCE` and are strictly excluded from affecting resolution or membership decisions as of $T_{\text{eval}}$.

### 5.2 Historical-Result Invariance
- If a resolved assertion is available at $T=10$, and an unresolved assertion is available at $T=15$:
  - Evaluation as-of $T=12$ evaluates **only** the $T=10$ assertion (maps to `True`). The $T=15$ notice does NOT exist as-of $T=12$ and cannot rewrite historical authority.
  - Evaluation as-of $T=16$ evaluates both assertions; the later assertion at $T=15$ demotes the stream to `False`.
- **Invariance Invariant**: Adding future assertions ($T_{\text{avail}} > T_{\text{eval}}$) produces byte-identical `status_map`, `diagnostics`, and `omitted_keys` for evaluations at $T_{\text{eval}}$.

---

## 6. Blocked Upstream Contracts (Explicit Non-Goals)

The implementation strictly preserves safety boundaries by excluding:
1. **`SRC-GAP-01` (Multi-Process Cursor Sync)**: No inter-process communication, shared memory locks, or distributed cursor tracking. Evaluator runs purely in-memory in the current process.
2. **`SRC-GAP-02` (Real-Time Live MT5 Ingestion)**: No live socket connections or polling loops to MT5 terminals. All inputs are offline pre-recorded batches or synthetic fixtures.
3. **`SRC-GAP-03` (Persistent Cross-Restart Database Ledger)**: No SQLite, JSON, or filesystem database writes for source-resolution records. State lives strictly in-memory during evaluation.
4. **`SRC-GAP-04` (Live Broker Execution)**: Zero trade placement, order execution, or account modification calls (strictly prohibited by `AGENTS.md`).

---

## 7. Reconciled Phase 1 Contract Inventory (All 25 Resolution Cases)

Phase 1 implements and tests all 25 resolution contracts under `tests/test_source_resolution_authority.py`:

| Case ID | Contract Description | Mandatory Input Condition | Expected Output |
|---|---|---|---|
| `SRC-RES-01` | Fully verified positive record | All 12 mandatory prerequisites satisfied | Maps to `True` in `status_map` (under declared offline contract assumptions) |
| `SRC-RES-02` | Valid unresolved record | Valid record with `UNRESOLVED_FROZEN` | Maps to `False` in `status_map` |
| `SRC-RES-03` | Missing record | Member in universe, no record supplied | Omitted from `status_map` (`UNKNOWN`) |
| `SRC-RES-04` | Future authority | $T_{\text{avail}} > T_{\text{eval}}$ | Omitted from `status_map` (`UNKNOWN`), `FUTURE_EVIDENCE` diagnostic |
| `SRC-RES-05` | Cross-symbol mismatch | `record.symbol_feed_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_SYMBOL` |
| `SRC-RES-06` | Cross-timeframe mismatch | `record.source_timeframe != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_TIMEFRAME` |
| `SRC-RES-07` | Cross-engine mismatch | `record.source_engine_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_ENGINE` |
| `SRC-RES-08` | Cross-run mismatch | `record.run_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_RUN` |
| `SRC-RES-09` | Identical duplicate records | Duplicate identical records | Idempotent deduplication, no error |
| `SRC-RES-10` | Contradictory duplicate records | Conflicting states at equal sequence | Omitted from `status_map` (`UNKNOWN`), `CONFLICTING_SOURCE_RESOLUTION_AUTHORITY` |
| `SRC-RES-11` | Member isolation | Resolution for `TJL1` does not authorize `TJL2` | `TJL1` $\rightarrow$ `True`, `TJL2` $\rightarrow$ omitted (`UNKNOWN`) |
| `SRC-RES-12` | Predecessor set supersession | Member from predecessor set loses resolved status | Predecessor member $\rightarrow$ omitted (`UNKNOWN`) |
| `SRC-RES-13` | Stale resolution boundary | $T_{\text{verified}} < T_{\text{req}}$ | Omitted from `status_map` (`UNKNOWN`), `STALE_RESOLUTION_BOUNDARY` |
| `SRC-RES-14` | Unknown establishment time | Member establishment time missing | Omitted from `status_map` (`UNKNOWN`) |
| `SRC-RES-15` | Cross-feed mismatch | `record.feed_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_FEED` |
| `SRC-RES-16` | Config hash mismatch | `record.source_config_hash != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_CONFIG` |
| `SRC-RES-17` | Prefix hash mismatch | `record.transition_prefix_hash` corrupted | Omitted from `status_map` (`UNKNOWN`), `ALTERED_TRANSITION_HISTORY_PREFIX` |
| `SRC-RES-18` | Later unresolved notice | Later unresolved notice with unchanged $T_{\text{verified}}$ | Demotes stream to `False` in `status_map` |
| `SRC-RES-19` | Conflicting payload on same ID | Differing payload on identical `record_id` | Omitted from `status_map` (`UNKNOWN`), `CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY` |
| `SRC-RES-20` | Altered prefix extension | Prefix recomputation mismatch | Omitted from `status_map` (`UNKNOWN`), `ALTERED_TRANSITION_HISTORY_PREFIX` |
| `SRC-RES-21` | Ordered vs unordered conflict | Differing sequence follows order; unordered omits | Causal sequence precedence or omission |
| `SRC-RES-22` | Later unresolved at same boundary | Distinct `assertion_seq` at same boundary | Demotes stream to `False` in `status_map` |
| `SRC-RES-23` | Receipt diagnostic sequence | Monotonic sequence separates receipt from prefix | Correct sequence ordering |
| `SRC-RES-24` | Stream isolation | Two streams differing only in config/epoch | Distinct `record_id`s, strictly isolated evaluations |
| `SRC-RES-25` | Canonical serialization determinism | Distinct float prices $\rightarrow$ distinct hashes; repeat equality; NaN/Inf reject | Deterministic canonical JSON and SHA-256 hashes |

### 7.1 Supporting Structural & Invariant Assertions
In addition to the 25 numbered cases, `tests/test_source_resolution_authority.py` will include dedicated supporting assertions:
- `test_missing_trust_config_fails_closed`: `trust_config=None` omits all keys with `TRUST_CONFIGURATION_MISSING`.
- `test_evidence_bundle_mismatch_fails_closed`: Snapshot observation mismatch emits `EVIDENCE_OBSERVATION_MISMATCH`.
- `test_historical_as_of_invariance`: Ingesting future assertions does not alter historical evaluation outputs.
- `test_deep_defensive_immutability`: Mutating returned dictionaries or nested containers raises errors or leaves result unaffected.
- `test_permutation_invariance`: Permuting input record ordering produces byte-identical `status_map`, `diagnostics`, and `omitted_keys`.

*Note*: Integration scenarios (`SRC-INT-01`..`04`) and negative controls (`FP-CTRL-01`..`04`) are scheduled for Phase 3.

---

## 8. Tightened Phase 1-Only File Allowlist

The file boundary for the initial Phase 1 increment is strictly restricted to 4 files:

| File Path | Permitted Action | Description |
|---|---|---|
| `src/aladeen/strategy/source_resolution.py` | **Create** | Standalone pure offline evaluator, evidence bundle, immutable request/result containers, canonical formatters, and prefix hasher. |
| `tests/test_source_resolution_authority.py` | **Create** | Isolated contract and unit test suite verifying Phase 1 contracts (`SRC-RES-01` through `SRC-RES-25`) and supporting assertions. |
| `docs/requirements/source-resolution-implementation-proposal.md` | **Create / Update** | This implementation proposal document. |
| `docs/development/status.md` | **Append Only** | Tracking entries for Milestones 38+. |

### Strictly Prohibited Files (Zero Diff Invariants):
- `tests/test_source_resolution_integration.py` (Reserved for separately approved Phase 3 work).
- `src/aladeen/strategy/activation_adapter.py` (Zero modifications; no builder wiring or adapter imports in Phase 1).
- `src/aladeen/strategy/confirmation_pair_matcher.py` (Zero diff against `7285a1d16a4413c051c4ecd032a53c49683f1600`).
- Core strategy engines (`engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `types.py`, `validator.py`) (Zero diff against `3f6689c194c95ca3761833f8831bb8a3f5b4740d`).
- Dedicated branch: `feature/confirmation-monitor`. Never merge into `main`.
