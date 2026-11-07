# Milestone 38 Implementation Proposal: Source-Resolution Authority Architecture & Verification Plan

**Status**: Documentation-Only Implementation Proposal (Awaiting Review & Approval Before Implementation)  
**Accepted Requirements Baseline**: Commit `8ea1ec2fdd8e9b699f4dbbc86d71a10a6e2a3e44` (Milestone 37 / HANDOFF-132)  
**Accepted Executable Baseline**: Commit `600925471e1fc56d01ba6621ed86f728d7eb76a0` (Milestone 36 / HANDOFF-125)  
**Branch**: `feature/confirmation-monitor`  
**Safety Boundary**: Strict read-only market data retrieval. Zero live MT5 broker trading, zero order execution, zero account modification, zero filesystem ledger writes, zero database storage, zero network ingestion, zero candidate ranking/arbitration, zero final signal publication, zero runtime preprocessor code in this proposal.

---

## 1. Architectural Scope & Objective

Milestone 37 established the formal requirements, canonical record definitions, scope-isolated identifiers, deterministic serialization rules, and acceptance inventory for upstream source-resolution authority (`docs/requirements/source-resolution-authority.md`).

The objective of Milestone 38 is to provide a comprehensive, documentation-only implementation proposal detailing:
1. **Component Boundary & Placement Evaluation**: Analysis of standalone evaluator vs. embedded preprocessor placement options.
2. **Trusted Offline Inputs vs. Caller Claims**: Formal classification of verified snapshot state vs. caller-supplied offline metadata.
3. **Blocked Upstream Contracts**: Explicit non-goals preserving safety boundaries and preventing premature heuristic runtime expansion.
4. **Selected Acceptance Cases**: Phased scheduling of the 33 accepted test cases (`SRC-RES-01` through `SRC-RES-25`, `SRC-INT-01` through `SRC-INT-04`, `FP-CTRL-01` through `FP-CTRL-04`).
5. **Exact File Allowlist**: Explicitly bounded set of files permitted for creation/modification, maintaining zero diff against core strategy engines and matcher baselines.

---

## 2. Proposed Component Boundary & Placement Evaluation

In accordance with Perplexity's guidance, the placement of the source-resolution evaluator is evaluated under two distinct architectural options:

### Option A: Embedded `SourceResolutionPreprocessor` inside `AuthorityContextBuilder`
- **Location**: Added directly to `src/aladeen/strategy/activation_adapter.py` (or a sub-module imported by `activation_adapter.py`).
- **Structure**: Modeled after `CoveragePreprocessor` and `UsagePreprocessor`.
- **Interface**:
  ```python
  class SourceResolutionPreprocessor:
      def __init__(self, trust_config: TrustConfiguration) -> None:
          ...
      def evaluate_source_resolution(
          self,
          records: Sequence[SourceResolutionRecord],
          evaluation_time: datetime,
          required_boundary: datetime,
      ) -> Mapping[str, bool]:
          ...
  ```
- **Trade-offs**:
  - *Advantages*: Integrates symmetrically into the existing tripartite authority pipeline (`CoveragePreprocessor`, `UsagePreprocessor`, `SourceResolutionPreprocessor`) within `AuthorityContextBuilder.build_matching_context()`.
  - *Disadvantages*: Couples pure source-resolution validation logic to activation adapter structures; increases file complexity in `activation_adapter.py` (already 500+ lines).

### Option B: Standalone Module `SourceResolutionEvaluator` (Recommended)
- **Location**: Standalone dedicated module `src/aladeen/strategy/source_resolution.py`.
- **Structure**: Pure, stateless offline evaluator operating on immutable dataclasses.
- **Interface**:
  ```python
  class SourceResolutionEvaluator:
      """Pure offline evaluator mapping source resolution records to authoritative tri-state outcomes."""
      def __init__(self, trust_config: SourceResolutionTrustConfig | None = None) -> None:
          ...
      def evaluate_records(
          self,
          records: Sequence[SourceResolutionRecord],
          evaluation_time: datetime,
          required_boundary: datetime,
          active_eligible_set: SetDescriptor | None = None,
      ) -> SourceResolutionResult:
          ...
  ```
- **Return Type**:
  ```python
  @dataclass(frozen=True)
  class SourceResolutionResult:
      status_map: Mapping[str, bool]             # Maps member_key -> True (RESOLVED) or False (UNRESOLVED_FROZEN)
      diagnostics: Tuple[SourceDiagnostic, ...]  # Recorded diagnostics (e.g. CONFLICTING, STALE, FUTURE)
      omitted_keys: FrozenSet[str]               # Keys omitted due to UNKNOWN status, conflicts, or future knowledge
  ```
- **Integration**: `AuthorityContextBuilder` can simply import `SourceResolutionEvaluator` (or accept its output `status_map`) without modifying existing core classes.
- **Trade-offs**:
  - *Advantages*: Decoupled, 100% independently unit-testable; zero risk of regressions in existing adapter logic; strict single-responsibility principle.
  - *Disadvantages*: Requires a clean integration seam if `AuthorityContextBuilder` is eventually wired to instantiate it.

**Architectural Recommendation**: Option B (Standalone module in `src/aladeen/strategy/source_resolution.py`).

---

## 3. Trusted Offline Inputs vs. Caller Claims

The implementation will strictly enforce the 4-tier origin classification established in Milestone 37 (§7):

| Tier | Category | Concrete Fields | Trust & Validation Boundary |
|---|---|---|---|
| **Tier 1** | **Existing Upstream State** | `CoordinatorSnapshot.is_unresolved`, `current_eligible_set`, `transition_history`, `set_id`, `role`, `lower_price`, `upper_price` | Authoritative for structural set geometry and member existence. Cannot be overridden by caller metadata. |
| **Tier 2** | **Derived Engineering Identity** | `member_key`, `source_config_hash`, `record_id`, `transition_prefix_hash` | Cryptographically and deterministically computed. Recomputed by evaluator to verify integrity; mismatched hashes trigger fail-closed rejection. |
| **Tier 3** | **Caller-Supplied Offline Metadata** | `assertion_seq`, `evidence_available_time`, `verified_source_boundary`, `required_source_boundary`, `feed_id`, `run_id`, `data_source` | **Untrusted offline claims**. Evaluator validates that $T_{\text{avail}} \le T_{\text{eval}}$, $T_{\text{verified}} \ge T_{\text{req}}$, timestamps are timezone-aware UTC with microseconds preserved, prices are finite floats, and sequence numbers are monotonic. |
| **Tier 4** | **Missing / Blocked Upstream Contracts** | Continuous live tick certification, multi-process cursor sync | **Blocked**. Absent from offline evaluation. |

### Deterministic Fail-Closed Validation Rules:
1. **Timestamp Normalization**: Naive timestamps (`tzinfo is None`) are rejected with diagnostic `UNVALIDATED_TIMEZONE_REJECTED` $\rightarrow$ maps to omitted key (`UNKNOWN`).
2. **Price Canonicalization**: Prices must be strictly of type `float` and finite (`math.isfinite(price) == True`). Non-finite floats (`NaN`, `Inf`) or non-float types trigger `INVALID_PRICE_GEOMETRY` $\rightarrow$ maps to omitted key.
3. **Anchor & Prefix Hashing**: Hashes recomputed on candidate records using length-prefixed anchor bytes and canonical JSON. Mismatch triggers `ALTERED_TRANSITION_HISTORY_PREFIX` $\rightarrow$ maps to omitted key.
4. **Scope Mismatch**: Cross-symbol, cross-feed, cross-run, cross-timeframe, or cross-epoch mismatches fail closed with appropriate diagnostics $\rightarrow$ omitted keys.

---

## 4. Blocked Upstream Contracts (Explicit Non-Goals)

To preserve architectural safety boundaries and prevent premature heuristic creep:
1. **`SRC-GAP-01` (Multi-Process Cursor Sync)**: No inter-process communication, shared memory locks, or distributed cursor tracking will be written. The evaluator operates purely in-memory in the current process.
2. **`SRC-GAP-02` (Real-Time Live MT5 Ingestion)**: No live socket connections or polling loops to MT5 terminals. All inputs are offline pre-recorded batches or synthetic fixtures.
3. **`SRC-GAP-03` (Persistent Cross-Restart Database Ledger)**: No SQLite, JSON, or filesystem database writes for source-resolution records. State lives strictly in-memory during evaluation.
4. **`SRC-GAP-04` (Live Broker Execution)**: Zero trade placement, order execution, or account modification calls.

---

## 5. Selected Acceptance Cases & Phased Implementation Plan

The 33 acceptance cases from Milestone 37 are organized into three sequential verification phases:

### Phase 1: Core Resolution Contracts & Scope Isolation (12 Cases)
- `SRC-RES-01`: Valid `RESOLVED` record $\rightarrow$ `True` in `status_map`.
- `SRC-RES-02`: Valid `UNRESOLVED_FROZEN` record $\rightarrow$ `False` in `status_map`.
- `SRC-RES-03`: Missing record for member $\rightarrow$ omitted key (`UNKNOWN`).
- `SRC-RES-04`: Future authority ($T_{\text{avail}} > T_{\text{eval}}$) $\rightarrow$ omitted key.
- `SRC-RES-05`: Cross-symbol mismatch (`GBPUSD` vs `EURUSD`) $\rightarrow$ omitted key.
- `SRC-RES-06`: Cross-timeframe mismatch (`H4` vs `D1`) $\rightarrow$ omitted key.
- `SRC-RES-07`: Cross-engine mismatch $\rightarrow$ omitted key.
- `SRC-RES-08`: Cross-run mismatch $\rightarrow$ omitted key.
- `SRC-RES-09`: Identical duplicate records $\rightarrow$ deduplicated idempotently.
- `SRC-RES-10`: Contradictory duplicate records $\rightarrow$ diagnostic and omitted key.
- `SRC-RES-13`: Stale resolution boundary ($T_{\text{verified}} < T_{\text{req}}$) $\rightarrow$ omitted key.
- `SRC-RES-14`: Unknown establishment time $\rightarrow$ omitted key.

### Phase 2: Lifecycle, Chaining, Serialization & Conflict Invariants (13 Cases)
- `SRC-RES-11`: Member isolation (`TJL1` does not authorize `TJL2`).
- `SRC-RES-12`: Superseded member from predecessor set loses `RESOLVED` status upon successor set creation.
- `SRC-RES-15`: Cross-feed mismatch $\rightarrow$ omitted key.
- `SRC-RES-16`: Configuration hash mismatch $\rightarrow$ omitted key.
- `SRC-RES-17`: Rewritten transition prefix hash mismatch $\rightarrow$ omitted key.
- `SRC-RES-18`: Later unresolved notice with unchanged $T_{\text{verified}}$ demotes stream to `UNRESOLVED_FROZEN`.
- `SRC-RES-19`: Conflicting payload on immutable `record_id` $\rightarrow$ diagnostic `CONFLICTING_RECORD_PAYLOAD_IMMUTABILITY`.
- `SRC-RES-20`: Altered transition history prefix $\rightarrow$ diagnostic `ALTERED_TRANSITION_HISTORY_PREFIX`.
- `SRC-RES-21`: Ordered vs. unordered conflict reconciliation (equal availability).
- `SRC-RES-22`: Later unresolved assertion sharing boundary demotes state to `UNRESOLVED_FROZEN`.
- `SRC-RES-23`: Assertion sequence order separates receipt diagnostic from transition index.
- `SRC-RES-24`: Stream isolation across differing config hash or epoch under identical sequence and boundary.
- `SRC-RES-25`: Canonical lossless price and timestamp serialization: distinct finite float prices produce distinct tokens/hashes; repeat equality; non-finite float rejection.

### Phase 3: Integration Scenarios & Negative False-Positive Controls (8 Cases)
- `SRC-INT-01`: Clean 3-way authority (Valid Source Resolution + COMPLETE Coverage + UNUSED Usage) $\rightarrow$ valid candidate.
- `SRC-INT-02`: Clean Coverage + Clean Usage, but `UNRESOLVED_FROZEN` Source Resolution $\rightarrow$ `BLOCKED`, 0 candidates.
- `SRC-INT-03`: Clean Coverage + Clean Usage, but `UNKNOWN` Source Resolution $\rightarrow$ `BLOCKED`, 0 candidates.
- `SRC-INT-04`: Replacement lifecycle: Set 1 replaced by Set 2 $\rightarrow$ Set 1 rejected at Gate 2, Set 2 evaluated under fresh resolution authority.
- `FP-CTRL-01`: Current-set presence alone rejects fail-closed when engine `is_unresolved = True`.
- `FP-CTRL-02`: Valid geometry alone rejects fail-closed without upstream resolution record.
- `FP-CTRL-03`: Closed bar alone rejects fail-closed under `BLOCKED_BY_UNRESOLVED_STATE`.
- `FP-CTRL-04`: Cursor equality alone rejects fail-closed when engine `is_unresolved = True`.

---

## 6. Exact File Allowlist

To strictly enforce scope control and strategy integrity, implementation is constrained to the following allowlist:

| File Path | Permitted Action | Description |
|---|---|---|
| `src/aladeen/strategy/source_resolution.py` | **Create** | Standalone pure offline evaluator, typed record dataclasses, length-prefixed formatters, canonical JSON serializer, and prefix hasher. |
| `tests/test_source_resolution_authority.py` | **Create** | Unit and contract test suite covering Phase 1 and Phase 2 acceptance contracts (`SRC-RES-01` through `SRC-RES-25`). |
| `tests/test_source_resolution_integration.py` | **Create** (Phase 3) | Integration and control test suite covering `SRC-INT-01`..`04` and `FP-CTRL-01`..`04`. |
| `docs/requirements/source-resolution-implementation-proposal.md` | **Create / Update** | This implementation proposal document. |
| `docs/development/status.md` | **Append Only** | Development and review tracking entries for Milestones 38+. |

### Strictly Prohibited Files (Zero Diff Invariants):
- **Core Strategy Engines (0 Diff against `3f6689c194c95ca3761833f8831bb8a3f5b4740d`)**:
  - `src/aladeen/strategy/engine.py`
  - `src/aladeen/strategy/choch_detector.py`
  - `src/aladeen/strategy/iss_engine.py`
  - `src/aladeen/strategy/tjl_coordinator.py`
  - `src/aladeen/strategy/activation_engine.py`
  - `src/aladeen/strategy/activation_adapter.py`
  - `src/aladeen/strategy/types.py`
  - `src/aladeen/strategy/validator.py`
- **Confirmation Matcher Logic (0 Diff against `7285a1d16a4413c051c4ecd032a53c49683f1600`)**:
  - `src/aladeen/strategy/confirmation_pair_matcher.py`

---

## 7. Submission Checklist for Perplexity Approval

Before writing any runtime or test code:
- [x] Complete component boundary and placement evaluation (Standalone Option B recommended).
- [x] Full input provenance classification distinguishing verified snapshot state from caller metadata.
- [x] Explicitly enumerated blocked contracts (`SRC-GAP-01` through `04`).
- [x] Phased scheduling for all 33 acceptance items.
- [x] Exact file allowlist with zero-diff invariants on core strategy and matcher baselines.
