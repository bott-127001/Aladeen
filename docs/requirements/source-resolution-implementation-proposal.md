# Milestone 38 Implementation Proposal: Source-Resolution Authority Architecture & Verification Plan (Revised — HANDOFF-134)

**Status**: Documentation-Only Implementation Proposal (Awaiting Review & Approval Before Implementation)  
**Accepted Requirements Baseline**: Commit `8ea1ec2fdd8e9b699f4dbbc86d71a10a6e2a3e44` (Milestone 37 / HANDOFF-132)  
**Accepted Executable Baseline**: Commit `600925471e1fc56d01ba6621ed86f728d7eb76a0` (Milestone 36 / HANDOFF-125)  
**Branch**: `feature/confirmation-monitor`  
**Safety Boundary**: Strict read-only market data retrieval. Zero live MT5 broker trading, zero order execution, zero account modification, zero filesystem ledger writes, zero database storage, zero network ingestion, zero candidate ranking/arbitration, zero final signal publication, zero runtime preprocessor code in this proposal.

---

## 1. Architectural Scope & Objective

Milestone 37 established the formal requirements, canonical record definitions, scope-isolated identifiers, deterministic serialization rules, and acceptance inventory for upstream source-resolution authority (`docs/requirements/source-resolution-authority.md`).

The objective of Milestone 38 (HANDOFF-134 Revision) is to provide an exact, bounded implementation proposal establishing:
1. **Component Boundary & Placement**: Approved standalone evaluator (`SourceResolutionEvaluator`) with an independent, immutable evaluation context (`SourceResolutionRequestContext`).
2. **Phase 1 Trust Model & Limits of Positive Output**: Explicit synthetic offline contract scope with clear non-claims regarding live upstream resolution derivation.
3. **Mandatory Safety Prerequisites**: Strict gating requiring all scope, temporal, membership, and integrity checks before any `True` outcome is possible.
4. **Tightened Phase 1 File Allowlist**: Strict 4-file boundary with zero modification to accepted strategy engines, adapter, or matcher.
5. **Exact Selected Case IDs & Expected Outcomes**: Specific 21-case contract inventory for the initial implementation increment.

---

## 2. Component Boundary & Independent Evaluation Context

### 2.1 Approved Component Placement: Standalone Evaluator (Option B)
- **Module Path**: `src/aladeen/strategy/source_resolution.py`
- **Rationale**: Isolates validation logic outside accepted adapter and matcher code, avoids modifying existing adapter logic, and allows isolated contract testing.
- **Scope Restriction**: Placement approval only. Production adapter integration, runtime service wiring, and automated derivation remain unapproved and deferred.

### 2.2 Independent Immutable Evaluation Context (`SourceResolutionRequestContext`)
A record cannot be validated against claims copied from that record itself. An independent, caller-provided evaluation context must supply the expected scope, boundary requirements, and authoritative snapshot references:

```python
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import FrozenSet, Mapping, Sequence, Tuple
from aladeen.strategy.types import CoordinatorSnapshot

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
    expected_member_universe: Tuple[str, ...]         # Expected member keys to evaluate
    authoritative_snapshot: CoordinatorSnapshot       # Bound coordinator snapshot for membership & is_unresolved
    declared_anchor_payload: bytes                    # Length-prefixed anchor bytes for prefix hash validation
    trust_config: SourceResolutionTrustConfig         # Mandatory trust config; None strictly rejected fail-closed
```

### 2.3 Evaluator Interface & Strictly Immutable Result Type
```python
@dataclass(frozen=True)
class SourceResolutionResult:
    """Strictly immutable result container invariant under input record permutations."""
    status_map: MappingProxyType[str, bool]           # Immutable mapping (types.MappingProxyType)
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

- **Permutation Invariance**: Input records may arrive in any sequence. The evaluator sorts and evaluates deterministically, producing identical `status_map`, `diagnostics`, and `omitted_keys` across repeated runs and permutations.

---

## 3. Phase 1 Trust Model & Limits of Positive Output

### 3.1 Explicit Phase 1 Trust Scope
- **Synthetic Offline Contract Evaluator**: Phase 1 is strictly an offline synthetic contract evaluator verifying that supplied record payloads conform to canonical specifications, match independent context expectations, and satisfy snapshot invariants under declared fixture/issuer assumptions.
- **Limits of Positive Output (`True`)**:
  - A `True` result emitted in `status_map` indicates **validation under declared offline contract assumptions**.
  - It does **not** establish live upstream resolution derivation, live tick certification, or operational multi-candle broker execution authority.
- **Fail-Closed Missing Trust Binding**:
  - If `request.trust_config is None` or `request.authoritative_snapshot is None`, the evaluator strictly rejects fail-closed with diagnostic `TRUST_CONFIGURATION_MISSING` or `AUTHORITATIVE_SNAPSHOT_MISSING`. All keys in `expected_member_universe` are omitted (`UNKNOWN`). Permissive defaults are strictly forbidden.

---

## 4. Mandatory Prerequisites Before ANY Positive Result (`True`)

A member key can **NEVER** emit `True` in `status_map` unless **ALL** of the following mandatory prerequisites are satisfied simultaneously:

1. **Independent Scope Match**:
   - `record.data_source == request.expected_data_source`
   - `record.feed_id == request.expected_feed_id`
   - `record.run_id == request.expected_run_id`
   - `record.source_engine_id == request.expected_source_engine_id`
   - `record.symbol_feed_id == request.expected_symbol_feed_id`
   - `record.source_timeframe == request.expected_source_timeframe`
   - `record.source_config_hash == request.expected_source_config_hash`
   - `record.structural_epoch == request.expected_structural_epoch`
   Any scope mismatch emits diagnostic (e.g. `SCOPE_MISMATCH_FEED`, `SCOPE_MISMATCH_ENGINE`) and omits the key.

2. **Mandatory Authoritative Membership Evidence**:
   - `member_key` exists in `request.expected_member_universe`.
   - `member_key` is active in `request.authoritative_snapshot.current_eligible_set`.
   - Missing membership evidence immediately omits the key.

3. **Authoritative Engine Resolution State**:
   - Upstream engine snapshot reports `request.authoritative_snapshot.is_unresolved == False`.
   - If `is_unresolved == True`, the member immediately maps to `False` (`UNRESOLVED_FROZEN`) or is omitted.

4. **Temporal Horizon Validity**:
   - Evaluation completed on or before evaluation time: `record.evidence_available_time <= request.evaluation_time` ($T_{\text{avail}} \le T_{\text{eval}}$).
   - Calculation verified through required boundary: `record.verified_source_boundary >= request.required_source_boundary` ($T_{\text{verified}} \ge T_{\text{req}}$).
   - Stale or future records omit the key.

5. **Transition History Prefix Cryptographic Integrity**:
   - The evaluator recomputes the prefix hash chain from `request.declared_anchor_payload` across transitions `0..record.transition_prefix_index` from `request.authoritative_snapshot.transition_history`.
   - Recomputed hash strictly matches `record.transition_prefix_hash`. Mismatch emits `ALTERED_TRANSITION_HISTORY_PREFIX` and omits the key.

6. **Single Deterministic Serialization & Formatting Integrity**:
   - `record.record_id` strictly matches `format_source_resolution_record_id(...)` incorporating full 9-component stream scope, `assertion_seq`, and canonical UTC `verified_iso`.
   - Prices must be strictly finite Python `float` values (`math.isfinite(price) == True`), serialized with `repr(price)`. Non-finite floats or silent coercion reject fail-closed.
   - Timestamps must be timezone-aware UTC, formatted with `Z`, preserving microseconds losslessly.

7. **Absence of Conflicting or Superseding Notices**:
   - No contradictory duplicate payload under the same `record_id` (`CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY`).
   - No causally later `UNRESOLVED_FROZEN` notice within the stream ($assertion\_seq_{\text{new}} > assertion\_seq_{\text{old}}$).

If any prerequisite fails, the member key cannot emit `True`. It maps to `False` (if explicitly unresolved/frozen) or is omitted from `status_map` (`UNKNOWN`).

---

## 5. Blocked Upstream Contracts (Explicit Non-Goals)

The implementation strictly preserves safety boundaries by excluding:
1. **`SRC-GAP-01` (Multi-Process Cursor Sync)**: No inter-process communication, shared memory locks, or distributed cursor tracking. Evaluator runs purely in-memory in the current process.
2. **`SRC-GAP-02` (Real-Time Live MT5 Ingestion)**: No live socket connections or polling loops to MT5 terminals. All inputs are offline pre-recorded batches or synthetic fixtures.
3. **`SRC-GAP-03` (Persistent Cross-Restart Database Ledger)**: No SQLite, JSON, or filesystem database writes for source-resolution records. State lives strictly in-memory during evaluation.
4. **`SRC-GAP-04` (Live Broker Execution)**: Zero trade placement, order execution, or account modification calls (strictly prohibited by `AGENTS.md`).

---

## 6. Phase 1 Selected Case IDs & Expected Outcomes (21 Contract Items)

Phase 1 focuses on pure contract validation in `tests/test_source_resolution_authority.py`, covering 21 distinct contract items:

| Case ID | Contract Description | Mandatory Input Condition | Expected Output |
|---|---|---|---|
| `SRC-RES-03` | Missing record | Member in universe, no record supplied | Omitted from `status_map` (`UNKNOWN`) |
| `SRC-RES-04` | Future authority | $T_{\text{avail}} > T_{\text{eval}}$ | Omitted from `status_map` (`UNKNOWN`), `FUTURE_EVIDENCE` diagnostic |
| `SRC-RES-05` | Cross-symbol mismatch | `record.symbol_feed_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_SYMBOL` |
| `SRC-RES-06` | Cross-timeframe mismatch | `record.source_timeframe != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_TIMEFRAME` |
| `SRC-RES-07` | Cross-engine mismatch | `record.source_engine_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_ENGINE` |
| `SRC-RES-08` | Cross-run mismatch | `record.run_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_RUN` |
| `SRC-RES-13` | Stale resolution boundary | $T_{\text{verified}} < T_{\text{req}}$ | Omitted from `status_map` (`UNKNOWN`), `STALE_RESOLUTION_BOUNDARY` |
| `SRC-RES-14` | Unknown establishment time | Member establishment time missing | Omitted from `status_map` (`UNKNOWN`) |
| `SRC-RES-15` | Cross-feed mismatch | `record.feed_id != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_FEED` |
| `SRC-RES-16` | Config hash mismatch | `record.source_config_hash != expected` | Omitted from `status_map` (`UNKNOWN`), `SCOPE_MISMATCH_CONFIG` |
| `SRC-RES-17` | Prefix hash mismatch | `record.transition_prefix_hash` corrupted | Omitted from `status_map` (`UNKNOWN`), `ALTERED_TRANSITION_HISTORY_PREFIX` |
| `SRC-RES-19` | Conflicting payload on same ID | Differing payload on identical `record_id` | Omitted from `status_map` (`UNKNOWN`), `CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY` |
| `SRC-RES-20` | Altered prefix extension | Prefix recomputation mismatch | Omitted from `status_map` (`UNKNOWN`), `ALTERED_TRANSITION_HISTORY_PREFIX` |
| `SRC-RES-24` | Stream isolation | Two streams differing only in config/epoch | Distinct `record_id`s, strictly isolated evaluations |
| `SRC-RES-25` | Canonical serialization determinism | Distinct float prices $\rightarrow$ distinct hashes; repeat equality; NaN/Inf reject | Deterministic canonical JSON and SHA-256 hashes |
| `SRC-RES-09` | Identical duplicate records | Duplicate identical records | Idempotent deduplication, no error |
| `SRC-RES-10` | Contradictory duplicate records | Conflicting states at equal sequence | Omitted from `status_map` (`UNKNOWN`), `CONFLICTING_SOURCE_RESOLUTION_AUTHORITY` |
| `SRC-RES-21` | Ordered vs unordered conflict | Differing sequence follows order; unordered omits | Causal sequence precedence or omission |
| `SRC-RES-23` | Receipt diagnostic sequence | Monotonic sequence separates receipt from prefix | Correct sequence ordering |
| `SRC-RES-02` | Valid unresolved record | Valid record with `UNRESOLVED_FROZEN` | Maps to `False` in `status_map` |
| `SRC-RES-18` | Later unresolved notice | Later unresolved notice with unchanged $T_{\text{verified}}$ | Demotes stream to `False` in `status_map` |
| `SRC-RES-22` | Later unresolved at same boundary | Distinct `assertion_seq` at same boundary | Demotes stream to `False` in `status_map` |
| `SRC-RES-01` | Fully verified positive record | All 8 mandatory prerequisites satisfied | Maps to `True` in `status_map` (under declared offline contract assumptions) |

*Note*: Remaining integration cases (`SRC-INT-01`..`04`) and negative controls (`FP-CTRL-01`..`04`) are deferred to Phase 3.

---

## 7. Tightened Phase 1-Only File Allowlist

The file boundary for the initial Phase 1 increment is strictly restricted to 4 files:

| File Path | Permitted Action | Description |
|---|---|---|
| `src/aladeen/strategy/source_resolution.py` | **Create** | Standalone pure offline evaluator, immutable request/result containers, canonical formatters, and prefix hasher. |
| `tests/test_source_resolution_authority.py` | **Create** | Isolated contract and unit test suite verifying Phase 1 selected cases. |
| `docs/requirements/source-resolution-implementation-proposal.md` | **Create / Update** | This implementation proposal document. |
| `docs/development/status.md` | **Append Only** | Tracking entries for Milestones 38+. |

### Strictly Prohibited Files (Zero Diff Invariants):
- `tests/test_source_resolution_integration.py` (Reserved for separately approved Phase 3 work).
- `src/aladeen/strategy/activation_adapter.py` (Zero modifications; no builder wiring or adapter imports in Phase 1).
- `src/aladeen/strategy/confirmation_pair_matcher.py` (Zero diff against `7285a1d16a4413c051c4ecd032a53c49683f1600`).
- Core strategy engines (`engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `types.py`, `validator.py`) (Zero diff against `3f6689c194c95ca3761833f8831bb8a3f5b4740d`).
- Dedicated branch: `feature/confirmation-monitor`. Never merge into `main`.
