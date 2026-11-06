# Offline Authority-Propagation Requirements & Acceptance Specification

**Milestone**: Milestone 34 — Offline Authority-Propagation Requirements  
**Status**: Requirements & Contract Specification (Documentation & Acceptance-Fixture Planning Only)  
**Safety Scope**: Pure offline read-only specification. Zero MT5 live trading, zero order execution, zero account modification, zero candidate arbitration/ranking, zero usage ledger writes, zero final signal publication.  
**Baseline Engine Integrity**: Strategy engines (`src/aladeen/strategy/engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`) remain 100% untouched.

---

## 1. Objective & Scope

In Milestone 33 (accepted at `b05a391554c73f80652d4dada5310510ba20fbf5`), source-to-candidate integration was proven offline on declared synthetic timelines using supplied synthetic authority assertions (usage, resolution, coverage, sequence domains).

The objective of Milestone 34 is to formally specify how these currently supplied authority assertions transition into **traceable offline inputs** without inventing upstream facts, broker feeds, or execution rights. This specification defines:
1. Exact evidence origin, identity, scope, availability, and fail-closed validation for each authority domain, strictly separating coverage extent from knowledge availability time.
2. An explicit 6-step preprocessing pipeline in `AuthorityContextBuilder` enforcing deterministic replacement-chain, supersession, and conflict precedence rules before mapping into accepted matcher inputs.
3. Complete coverage acceptance predicates and deterministic usage state transition rules.
4. Concrete schemas, fields, trust boundaries, and supersession behaviors for proposed authority records.
5. An executable and honest 51-case acceptance inventory distinguishing existing executable evidence, proposed synthetic authority contracts with deterministic subcases, proposed traceable offline integration cases, and blocked cases.
6. Authority-to-origin mapping across strategy layers.

---

## 2. Authority Inputs, Scope & Origins

A container, boolean, or enum is a representation—not its own proof. Every authority claim must be backed by an immutable, timestamped origin record evaluated strictly at the requested evaluation boundary ($T_{\text{eval}}$).

### 2.1 Domain 1: Source Resolution Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | TJL snapshot emitted by `TJLCoordinator.get_snapshot()` and adapted by `TJLSynchronizer`. |
| **Entity Identity** | `SourceMemberKey` formatted as `format_member_key(set_id, role)` and physical `StableLevelId(symbol_feed_id, source_timeframe, bar_time, side)`. |
| **Scope** | Bound to exact `SequenceDomain(feed_id, run_id)` and source timeframe (e.g. `D1`). |
| **Availability Time** | Closed-bar availability $T_{\text{avail}} = \text{EligibleSet.eligibility\_available\_time}$. |
| **Accepted Runtime Contract** | Upstream resolution is passed in `MatchingContext.source_resolution_status: Mapping[str, bool]`.<br>- If key is missing: rejects fail-closed as `ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`.<br>- If key is explicitly `False`: blocks fail-closed as `ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY`. |
| **Unresolved Pipeline Boundary (Honest Disclosure)** | Upstream set presence, closed bar status, and valid geometry alone do **NOT** prove full upstream pipeline resolution. In the live dashboard, unresolved state occurs when calculation cursors desynchronize (`processed_bar_index < received_bar_index`). The formal mapping between cursor synchronization and explicit source resolution flags remains *pending reconciliation with upstream pipeline cursor contracts*. |

### 2.2 Domain 2: Usage Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Explicit offline usage evidence ledger record `ProposedUsageEvidenceRecord` or upstream source proof. |
| **Entity Identity** | Physical level identifier `StableLevelId(symbol_feed_id, source_timeframe, bar_time, side)` (NOT the ephemeral role or set label). |
| **Scope** | Persistent physical price level. Usage authority survives level set replacements (e.g. SET_1 $\rightarrow$ SET_2) and role relabeling (e.g. TJL1 $\rightarrow$ TJL2). |
| **Availability Time** | `established_time` ($\le T_{\text{eval}}$) and knowledge `available_time` ($\le T_{\text{eval}}$). |
| **Accepted Runtime Contract** | Status values from `UsageEvidenceStatus`: `UNUSED`, `USED`, `UNKNOWN`.<br>- If `UNKNOWN`: rejects fail-closed as `ConfirmationRejectionReason.UNKNOWN_USAGE`.<br>- If `USED`: rejects fail-closed as `ConfirmationRejectionReason.STALE_EVIDENCE_FOR_GENERATION` (if active generation has consumed it) or `ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE` (if activation is terminal). |
| **Invariant: No Negative Proof** | Absence of a usage record does **NOT** prove `UNUSED`. Any level lacking explicit, authoritative proof of unused state MUST default to `UNKNOWN`. |

### 2.3 Domain 3: Feed Coverage Authority — Complete Acceptance Predicate & Separation of Extent

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Feed completeness certificate `ProposedFeedCoverageRecord` issued by an authoritative offline feed audit process. |
| **Entity Identity** | `(feed_id, sequence_domain, timeframe, covered_interval_start, covered_interval_end, confirmation_config_id)`. |
| **Coverage Extent** | The closed interval $[T_{\text{covered\_start}}, T_{\text{covered\_end}}]$ across which continuous, gap-free bar data has been verified. |
| **Knowledge Availability Time** | The timestamp $T_{\text{available}}$ when the coverage certificate became available to the evaluator store. (Separated from $T_{\text{issued}}$: issuance alone does not imply delivery or knowledge). |
| **Required Evaluation Interval** | The stream interval $[T_{\text{req\_start}}, T_{\text{req\_end}}]$ required by the confirmation configuration up to $T_{\text{eval}}$. |
| **Complete Coverage Acceptance Predicate** | An evaluation at $T_{\text{eval}}$ is authorized for coverage **if and only if ALL of the following 7 conditions hold simultaneously**:<br>1. **Approved Issuer**: `issuer_id` belongs to the configured trusted issuer set under an explicitly declared trust assumption.<br>2. **Valid Schema & Identity**: `schema_version == "v1"` and `record_id` is unique with no payload conflict.<br>3. **Exact Scope Match**: `feed_id`, `sequence_domain`, `timeframe`, and `confirmation_config_id` match the evaluation request exactly.<br>4. **Complete Status**: `status == CoverageStatus.COMPLETE` (neither `INCOMPLETE` nor `UNCERTAIN`).<br>5. **Full Spatial Extent**: $T_{\text{covered\_start}} \le T_{\text{req\_start}}$ AND $T_{\text{covered\_end}} \ge T_{\text{req\_end}}$.<br>6. **Knowledge Availability by Boundary**: $T_{\text{available}} \le T_{\text{eval}}$ (no retroactive authorization from later-arriving certificates).<br>7. **No Active Supersession**: Certificate has not been superseded by a validated higher-revision certificate available at or before $T_{\text{eval}}$. |
| **Retroactive Prohibition** | A certificate with $T_{\text{available}} > T_{\text{eval}}$ cannot retroactively authorize an evaluation at $T_{\text{eval}}$, even if its covered extent covers that historical time. |
| **Accepted Runtime Contract** | `CoverageStatus`: `COMPLETE`, `INCOMPLETE`, `UNCERTAIN`. Both `INCOMPLETE` and `UNCERTAIN` reject fail-closed as `ConfirmationRejectionReason.INCOMPLETE_COVERAGE`. |
| **Invariant: No Gap Absence Proof** | Absence of a detected candle gap does **NOT** prove completeness. The interval must be actively certified. |

### 2.4 Domain 4: Touch Ordering & Sequence Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | `ExactPricePrint` observation stream delivered to `ActivationEngine.process_event()`. |
| **Entity Identity** | `observation_id` linked immutably to `ActivationRecord.trigger_observation_id` and `generation_seq`. |
| **Scope** | Bound to single, unbroken `SequenceDomain(feed_id, run_id)` with strictly monotonically increasing sequence references (`sequence_ref`). |
| **Availability Time** | `ExactPricePrint.timestamp` ($T_{\text{touch}}$) and integer `sequence_ref`. |
| **Equal-Timestamp Ordering** | Where confirmation close timestamp equals physical touch timestamp ($T_{\text{conf}} == T_{\text{touch}}$):<br>1. If sequence reference missing on either record $\rightarrow$ reject fail-closed as `ConfirmationRejectionReason.UNKNOWN_ORDER`.<br>2. If sequence domains differ $\rightarrow$ reject fail-closed as `ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED`.<br>3. If $\text{sequence\_ref}_{\text{conf}} \le \text{sequence\_ref}_{\text{touch}}$ $\rightarrow$ reject fail-closed as `ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION`.<br>4. Only if $\text{sequence\_ref}_{\text{conf}} > \text{sequence\_ref}_{\text{touch}}$ within identical domain is match causally valid. |
| **Rearm Lifecycle States** | Upon zone departure after cancellation inside zone: rearm controller reaches `ActivationState.OUT_OF_ZONE_ARMED`. Upon physical retouch: fresh active activation is created with state `ActivationState.REARMED_PENDING` (Gen 2). |

### 2.5 Domain 5: Confirmation Stream Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Incremental confirmation detector (`CHOCHDetector`, `ISSEngine`) evaluated on closed candles bound within `ValidatedCandleStreamEnvelope`. |
| **Entity Identity** | `event_id`, `producer_id`, `confirmation_config_id`, `confirmation_candle_id`. |
| **Scope** | Bound to closed confirming candle, timeframe, price basis, and sequence domain. |
| **Availability Time** | Candle close timestamp $T_{\text{close}} = \text{StrategyCandle.close\_time}$. |
| **Candle Completion Contract** | Confirming candle must have `is_forming == False` and `bar_status == "CONFIRMED_COMPLETED"`. Incomplete evidence (missing timestamps or unclosed candle) rejects as `ConfirmationRejectionReason.INCOMPLETE_EVIDENCE`. |
| **Temporal Gating** | If confirming candle closes after evaluation boundary ($T_{\text{close}} > T_{\text{eval}}$), candidate matching rejects fail-closed as `ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE`. |

### 2.6 Domain 6: Evaluation Boundary Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Explicit caller-supplied `MatchingContext.evaluation_time` ($T_{\text{eval}}$). |
| **Scope** | Point-in-time evaluation horizon for batch or pair matching. |
| **Temporal Visibility Gating** | Matcher has visibility **ONLY** into authority records where $\text{available\_time} \le T_{\text{eval}}$. Future records are invisible and fail closed. |
| **Immutability & Idempotence** | Repeated evaluations at identical $T_{\text{eval}}$ yield strictly identical `ConfirmationMatchResult` instances (`res1 == res2`). External caller mutations of context dictionaries do not affect the frozen context. |

---

## 3. Explicit Proposed Authority Record Schemas, Preprocessing Pipeline & Precedence

To transition from synthetic assertions to traceable inputs, we propose explicit, typed schemas and a deterministic preprocessing order. These schemas are proposed contract extensions and do not modify existing accepted runtime types.

### 3.1 Proposed Preprocessing Order (`AuthorityContextBuilder`)

The accepted `ConfirmationMatcher` consumes `MatchingContext` and does **not** consume raw database or audit certificate records directly. We define an explicit 6-step pipeline in `AuthorityContextBuilder`:

1. **Step 1: Point-in-Time Visibility Filter**:
   - Filter records by knowledge availability: discard any record where $\text{available\_time} > T_{\text{eval}}$. Future records cannot affect the evaluation.
2. **Step 2: Schema, Issuer, Identity & Scope Validation**:
   - Check `schema_version == "v1"` and `issuer_id` against trusted issuers.
   - Exact scope match (`feed_id`, `sequence_domain`, `timeframe`, `confirmation_config_id`).
   - Identical-Duplicate Coalescence: Exact duplicate immutable records (identical `record_id` and identical payload) coalesce idempotently. Differing payloads under the same `record_id` emit `ConfirmationRejectionReason.CONFLICTING_IDENTITY`.
3. **Step 3: Predecessor Validation & Supersession Resolution**:
   - Validate replacement chains: predecessor existence and visibility at boundary, strict scope match, strictly higher revision, acyclic graph, and absence of forks.
   - Validated successors replace their predecessors. Invalid successors are rejected without silently retiring valid prior authority.
4. **Step 4: Conflict Resolution**:
   - Evaluate conflicts among remaining applicable records. Conflicting statuses intersecting the required evaluation interval degrade to `CoverageStatus.UNCERTAIN` or `UsageEvidenceStatus.UNKNOWN`. Conflicts entirely outside the required interval do not impair independently valid certificates.
5. **Step 5: Independent Interval Coverage Evaluation**:
   - Test each valid, non-superseded certificate independently against the required evaluation interval $[T_{\text{req\_start}}, T_{\text{req\_end}}]$. A certificate covering the entire required interval satisfies extent. Compatible overlapping certificates do not shrink coverage.
6. **Step 6: Matcher Context Mapping & Diagnostic Preservation**:
   - Map resolved authority into `MatchingContext` (`coverage_status`, `source_resolution_status`) and `SourceMemberReference` (`usage_evidence_status`).
   - Retain authority-specific diagnostics separately at the preprocessor boundary. Candidate formation remains conditional on all matcher gates passing simultaneously.

### 3.2 Proposed Usage Evidence Record (`ProposedUsageEvidenceRecord`)

```python
@dataclass(frozen=True)
class ProposedUsageEvidenceRecord:
    """Proposed schema for authoritative physical-level usage evidence."""
    record_id: str                          # Unique immutable ID (e.g. "USG_EURUSD_D1_20261001_001")
    schema_version: str                     # Contract version (e.g. "v1")
    issuer_id: str                          # Originating authority (e.g. "UPSTREAM_TRADE_LEDGER_OFFLINE")
    level_id: StableLevelId                 # Physical level: symbol_feed_id, source_timeframe, bar_time, side
    status: UsageEvidenceStatus             # UNUSED, USED, UNKNOWN
    established_time: datetime              # Timestamp when status was authoritatively established
    available_time: datetime                # Timestamp when record became available in offline store
    provenance_ref: str                     # Reference to upstream audit log, trade ticket, or fixture ID
    predecessor_record_id: Optional[str] = None # Explicit predecessor reference for causal state transitions
    optional_integrity_hash: Optional[str] = None # Optional SHA-256 for tampering detection (NOT authority proof)
```

**Deterministic Conflict & Equal-Time Usage Precedence**:
1. **Validated Predecessor & Equal-Time Causality**:
   - An explicit, validated predecessor link (`predecessor_record_id == predecessor.record_id` where $T_{\text{established\_successor}} \ge T_{\text{established\_predecessor}}$) establishes causal order even when knowledge availability timestamps tie ($T_{\text{available\_successor}} == T_{\text{available\_predecessor}}$).
   - This represents a legitimate causal lifecycle transition (`UNUSED` $\rightarrow$ `USED`), NOT a conflict.
2. **Invalid Predecessor Relationships**:
   - Unknown, wrong-level, cyclic, or forked predecessor relationships cannot establish a valid usage transition. An invalid transition is rejected without silently retiring a valid prior record; if no prior record exists, status defaults to `UsageEvidenceStatus.UNKNOWN`.
3. **Temporal Gating**:
   - A future or unavailable successor ($T_{\text{available}} > T_{\text{eval}}$) cannot affect an earlier point-in-time evaluation.
4. **Contradictory Simultaneous Assertions**:
   - Two records asserting differing statuses (`UNUSED` vs `USED`) for the same `level_id` at the same evaluation boundary without a valid causal predecessor reference degrade to `UsageEvidenceStatus.UNKNOWN` (rejecting fail-closed as `UNKNOWN_USAGE`).
5. **Physical Level Persistence**:
   - Once a level reaches `USED`, that status is terminal for the physical level geometry (`StableLevelId`). It survives set replacements (SET_1 $\rightarrow$ SET_2) and cannot transition back to `UNUSED`.

### 3.3 Proposed Feed Coverage Record (`ProposedFeedCoverageRecord`)

```python
@dataclass(frozen=True)
class ProposedFeedCoverageRecord:
    """Proposed schema for authoritative market-data feed completeness certification."""
    record_id: str                          # Unique immutable ID (e.g. "COV_EURUSD_H1_20261001_v1")
    schema_version: str                     # Contract version (e.g. "v1")
    issuer_id: str                          # Originating auditor (e.g. "OFFLINE_FEED_AUDITOR_v1")
    feed_id: str                            # Associated feed identifier (e.g. "FEED_EURUSD_H1")
    sequence_domain: SequenceDomain         # Sequence domain of the feed audit
    timeframe: str                          # Timeframe evaluated (e.g. "H1")
    confirmation_config_id: str             # Configuration ID verified
    covered_interval_start: datetime        # Start of continuous interval (inclusive)
    covered_interval_end: datetime          # End of continuous interval (inclusive)
    status: CoverageStatus                  # COMPLETE, INCOMPLETE, UNCERTAIN
    issued_time: datetime                   # Timestamp when certificate was computed by auditor
    available_time: datetime                # Timestamp when certificate was received/published to store
    revision_seq: int = 1                   # Monotonically increasing integer revision sequence
    supersedes_record_id: Optional[str] = None # Explicit reference to superseded certificate
```

**Deterministic Replacement-Chain Validation & Precedence**:
1. **Replacement-Chain Validation Before Retiring Prior Authority**:
   - A superseding revision is recognized and permitted to replace prior authority **if and only if all of the following validation checks pass**:
     a) **Predecessor Existence & Visibility**: The predecessor record identified by `supersedes_record_id` exists and is visible at the evaluation boundary ($T_{\text{predecessor.available}} \le T_{\text{eval}}$). If the predecessor is unknown or unavailable at $T_{\text{eval}}$, the replacement is invalid; the predecessor (if visible) remains authoritative or matching fails closed.
     b) **Strict Scope Match**: Both records belong to the exact same scope: identical `feed_id`, `sequence_domain`, `timeframe`, `confirmation_config_id`, and `issuer_id`. A mismatch in scope makes the replacement invalid $\rightarrow$ fails closed.
     c) **Strictly Higher Revision**: `successor.revision_seq > predecessor.revision_seq`.
     d) **Acyclic Chain**: Predecessor links form a strictly acyclic chain. A cycle (e.g. A $\rightarrow$ B $\rightarrow$ A) is detected and fails closed.
     e) **No Ambiguous Forks**: If two distinct successor records both claim the same `supersedes_record_id` with conflicting payloads, the chain is an ambiguous fork $\rightarrow$ preprocessor fails closed for the affected scope with `CoverageStatus.UNCERTAIN`.
     f) **Successor Validity**: The successor itself satisfies all schema, trust, identity, and temporal availability ($T_{\text{successor.available}} \le T_{\text{eval}}$) rules.
   - An invalid replacement must **never silently retire** valid prior authority.
2. **Point-in-Time Visibility of Revisions**:
   - For $T_{\text{eval}} < \text{available\_time}_{\text{successor}}$: The prior certificate remains authoritative.
   - For $T_{\text{eval}} \ge \text{available\_time}_{\text{successor}}$: The validated successor replaces the prior certificate in its entirety.
3. **Overlapping Coverage Extent Evaluation (No Unsupported Shrinking)**:
   - Each valid certificate is evaluated independently against the required evaluation interval $[T_{\text{req\_start}}, T_{\text{req\_end}}]$.
   - A certificate that independently covers the entire required interval ($T_{\text{covered\_start}} \le T_{\text{req\_start}}$ and $T_{\text{covered\_end}} \ge T_{\text{req\_end}}$) satisfies the extent condition.
   - Additional compatible certificates covering different or overlapping extents **do not shrink** valid coverage; intersection is never applied to compatible certificates.
   - If two certificates assert conflicting statuses on an overlapping interval:
     * If the conflict intersects the required evaluation interval: Status degrades to `CoverageStatus.UNCERTAIN` $\rightarrow$ fail-closed as `INCOMPLETE_COVERAGE`.
     * If the conflict lies entirely outside the required evaluation interval: An independent certificate covering the entire required interval remains authoritative.
4. **Equal-Time Updates & Causality**:
   - An explicit, validated predecessor link (`supersedes_record_id == predecessor.record_id` with `revision_seq > predecessor.revision_seq`) establishes causal order even when availability timestamps tie ($T_{\text{avail\_succ}} == T_{\text{avail\_pred}}$).
   - Unlinked conflicting equal-time records without an explicit predecessor reference lack causal sequence and MUST degrade to `CoverageStatus.UNCERTAIN` $\rightarrow$ fail-closed.

---

## 4. Acceptance Inventory (51 Cases)

The inventory catalogs 51 discrete cases across 4 categories:

### 4.1 Existing Executable Evidence (16 Cases)

| Case ID | Contract & Exact Test Function | Input Evidence | Expected Status / Reason | Result Assertion |
| :--- | :--- | :--- | :--- | :--- |
| **INT-01** | `test_actual_candle_derived_choch_pattern_pre_tap_formation_post_tap_completion`<br>(`tests/test_confirmation_matcher.py` L2092) | Synthetic member + H1 CHOCH envelope | `MATCHED` | 1 SELL candidate (1.0850) |
| **INT-02** | `test_actual_candle_derived_iss_authoritative_matching_and_unresolved_blocking`<br>(`tests/test_confirmation_matcher.py` L2192) | Synthetic member + H1 ISS envelope | `MATCHED` | 1 SELL candidate (1.1120) |
| **INT-03** | `test_int_03_genuine_source_exact_print_choch_chronological_schedule`<br>(`tests/test_source_candidate_choch_chain.py` L114) | Retained CHOCH detector across 5 boundaries | B1..3: `[]`; B4: `MATCHED` | Zero candidates prior to close; 1 SELL candidate at close |
| **INT-04** | `test_int_04_genuine_source_exact_print_iss_chronological_schedule`<br>(`tests/test_source_candidate_iss_chain.py` L114) | Retained ISS engine across 5 boundaries | B1..3: `[]`; B4: `MATCHED` | Zero candidates prior to close; 1 SELL candidate at close |
| **ACT-01** | `test_act_01_rearm_path_a_inside_at_cancel_with_immutable_predecessor`<br>(`tests/test_source_candidate_rearm.py` L58) | Inside at cancel $\rightarrow$ departure $\rightarrow$ retouch | `OUT_OF_ZONE_ARMED` $\rightarrow$ `REARMED_PENDING` | Predecessor immutable |
| **ACT-02** | `test_act_02_source_set_replacement_terminal_non_revival`<br>(`tests/test_source_candidate_cancellation.py` L85) | Set replacement $\rightarrow$ post-out/in prints | `CANCELLED_SOURCE_REPLACEMENT` | Zero candidates (`MEMBERSHIP_CANCELLED_OR_REPLACED`) |
| **ACT-03** | `test_act_03_source_main_choch_invalidation_terminal_non_revival`<br>(`tests/test_source_candidate_cancellation.py` L266) | Invalidation $\rightarrow$ post-out/in prints | `CANCELLED_SOURCE_CHOCH` | Zero candidates (`INELIGIBLE_ACTIVATION_STATE`) |
| **ACT-04** | `test_act_04_rearm_path_b_already_outside_at_cancel_with_immutable_predecessor`<br>(`tests/test_source_candidate_rearm.py` L152) | Outside at cancel $\rightarrow$ arming $\rightarrow$ retouch | `OUT_OF_ZONE_ARMED` $\rightarrow$ `REARMED_PENDING` | Predecessor immutable |
| **ORD-01** | `test_equal_time_causal_ordering_matrix`<br>(`tests/test_source_candidate_ordering.py` L99) | $T_{\text{conf}} == T_{\text{touch}}$, missing seq | `UNKNOWN_ORDER` | Zero candidates |
| **ORD-02** | `test_equal_time_causal_ordering_matrix`<br>(`tests/test_source_candidate_ordering.py` L134) | $T_{\text{conf}} == T_{\text{touch}}$, domain mismatch | `CROSS_DOMAIN_ORDERING_REJECTED` | Zero candidates |
| **ORD-03** | `test_equal_time_causal_ordering_matrix`<br>(`tests/test_source_candidate_ordering.py` L160) | $T_{\text{conf}} == T_{\text{touch}}$, seq $\le$ touch | `PRE_ACTIVATION_CONFIRMATION` | Zero candidates |
| **ORD-04** | `test_equal_time_causal_ordering_matrix`<br>(`tests/test_source_candidate_ordering.py` L206) | $T_{\text{conf}} == T_{\text{touch}}$, seq $>$ touch | `MATCHED` | 1 candidate formed |
| **BND-A** | `test_supplied_synthetic_authority_boundaries`<br>(`tests/test_source_candidate_authority_boundaries.py` L103) | `UsageEvidenceStatus.UNKNOWN` | `UNKNOWN_USAGE` | Zero candidates |
| **BND-B** | `test_supplied_synthetic_authority_boundaries`<br>(`tests/test_source_candidate_authority_boundaries.py` L153) | `CoverageStatus.INCOMPLETE` | `INCOMPLETE_COVERAGE` | Zero candidates |
| **BND-C** | `test_supplied_synthetic_authority_boundaries`<br>(`tests/test_source_candidate_authority_boundaries.py` L170) | `source_resolution_status == False` | `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY` | Zero candidates |
| **BND-D** | `test_supplied_synthetic_authority_boundaries`<br>(`tests/test_source_candidate_authority_boundaries.py` L187) | `has_unresolved_dependencies == True` | `UNRESOLVED_DEPENDENCY` | Zero candidates |

### 4.2 Proposed Synthetic Authority Contracts (25 Cases)

| Case ID | Contract Description | Test Setup | Expected Preprocessor/Matcher Diagnostic | Candidate Assertion |
| :--- | :--- | :--- | :--- | :--- |
| **AUT-SYN-01** | Contradictory Usage Evidence | Two records for same `level_id` asserting `UNUSED` and `USED` without causal sequence | Preprocessor degrades to `UNKNOWN_USAGE` | Zero candidates |
| **AUT-SYN-02** | Retroactive Coverage Rejection | Coverage extent covers interval, but $T_{\text{available}} > T_{\text{eval}}$ | `INCOMPLETE_COVERAGE` (not available at $T_{\text{eval}}$) | Zero candidates |
| **AUT-SYN-03** | Coverage Config Mismatch | Certificate generated for `CONF_CFG_02`, evaluation requests `CONF_CFG_01` | `INCOMPLETE_COVERAGE` | Zero candidates |
| **AUT-SYN-04** | Duplicate Conflicting Activations | Duplicate `activation_id` with contradictory touch prices | `CONFLICTING_IDENTITY` | Zero candidates |
| **AUT-SYN-05** | Duplicate Conflicting Confirmations | Duplicate `event_id` with contradictory close prices | `CONFLICTING_IDENTITY` | Zero candidates |
| **AUT-SYN-06** | Persistent Usage on Set Replacement | SET_1 uses Level $L$ (`USED`); SET_2 created on Level $L$; touch occurs | `STALE_EVIDENCE_FOR_GENERATION` | Zero candidates (Level $L$ used) |
| **AUT-SYN-07** | Evaluation Before Availability | Evaluation requested at $T_{\text{eval}} < T_{\text{avail}}$ of source set | Missing member in `current_members` | Zero candidates |
| **AUT-SYN-08** | Unresolved Source Cursor Notice | Upstream notice emitted when `processed_bar < received_bar` | `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY` | Zero candidates |
| **AUT-SYN-09** | Uncertain Coverage Degradation | Coverage status explicitly set to `CoverageStatus.UNCERTAIN` | `INCOMPLETE_COVERAGE` | Zero candidates |
| **AUT-SYN-10** | Incomplete Confirmation Candle | Candle has `is_forming == True` or `bar_status != "CONFIRMED_COMPLETED"` | `INCOMPLETE_EVIDENCE` | Zero candidates |
| **AUT-SYN-11** | Missing Authority Record | Level omitted entirely from usage records (no record exists) | Defaults to `UNKNOWN_USAGE` (no negative proof) | Zero candidates |
| **AUT-SYN-12** | Wrong Scope (Feed, Run, Timeframe) | Certificate scope mismatches: wrong `feed_id`, wrong `run_id`, or wrong `timeframe` | Preprocessor rejects scope $\rightarrow$ `INCOMPLETE_COVERAGE` | Zero candidates |
| **AUT-SYN-13** | Future Usage Knowledge Availability | Usage record established at $T_1 \le T_{\text{eval}}$ but $T_{\text{available}} > T_{\text{eval}}$ | Unavailable at $T_{\text{eval}} \rightarrow$ `UNKNOWN_USAGE` | Zero candidates |
| **AUT-SYN-14** | Validated Superseded Precedence | Validated Rev 2 available at $T_2 > T_1$; evaluated at $T_{\text{eval}} \ge T_2$ | Validated Rev 2 replaces Rev 1 in its entirety | Governed by Rev 2 |
| **AUT-SYN-15** | Conflicting Authority-Record IDs | Two authority records share `record_id` with differing payloads | `CONFLICTING_IDENTITY` | Zero candidates |
| **AUT-SYN-16a** | Unknown Predecessor (Prior Valid Exists) | Successor claims non-existent predecessor; valid prior certificate exists | Invalid successor rejected; prior valid certificate preserved | Prior certificate governs |
| **AUT-SYN-16b** | Unknown Predecessor (No Prior Valid) | Successor claims non-existent predecessor; no prior certificate exists | Invalid successor rejected; coverage fails closed | Zero candidates (`INCOMPLETE_COVERAGE`) |
| **AUT-SYN-17a** | Wrong-Scope Supersession (Prior Valid Exists) | Successor has wrong scope; valid prior certificate exists in requested scope | Out-of-scope successor ignored; prior valid certificate preserved | Prior certificate governs |
| **AUT-SYN-17b** | Wrong-Scope Supersession (No Prior Valid) | Successor has wrong scope; no prior certificate exists in requested scope | Coverage fails closed for requested scope | Zero candidates (`INCOMPLETE_COVERAGE`) |
| **AUT-SYN-18** | Cyclic Predecessor Link | Predecessor chain forms a cycle (A $\rightarrow$ B $\rightarrow$ A) | Cyclic chain detected $\rightarrow$ `CoverageStatus.UNCERTAIN` | Zero candidates |
| **AUT-SYN-19** | Forked Successors | Successor B and Successor C both claim Predecessor A with conflicting payloads | Ambiguous fork $\rightarrow$ `CoverageStatus.UNCERTAIN` | Zero candidates |
| **AUT-SYN-20** | Compatible Overlapping Certificates | Cert A $[T_0, T_2]$ and Cert B $[T_1, T_3]$ both `COMPLETE`; Cert A covers $[T_{\text{req\_start}}, T_{\text{req\_end}}]$ | Extent satisfied independently $\rightarrow$ coverage authorized | Candidate match permitted (if all gates pass) |
| **AUT-SYN-21** | Overlapping Conflict Inside Required Interval | Cert A (`COMPLETE`) and Cert B (`INCOMPLETE`) overlap inside required interval | Intersecting conflict $\rightarrow$ `CoverageStatus.UNCERTAIN` | Zero candidates |
| **AUT-SYN-22** | Overlapping Conflict Outside Required Interval | Conflict between Cert B and Cert C is entirely outside required interval; Cert A covers required interval | Cert A independently satisfies required interval | Candidate match permitted (if all gates pass) |
| **AUT-SYN-23** | Equal-Time Linked vs Unlinked Precedence | Sub-case A: Equal-time linked update (`supersedes_record_id` valid) $\rightarrow$ successor valid.<br>Sub-case B: Equal-time unlinked conflicting update $\rightarrow$ `UNCERTAIN`. | Linked: Successor governs.<br>Unlinked: Degrades to `CoverageStatus.UNCERTAIN`. | Sub-case A: Valid.<br>Sub-case B: 0 candidates. |

### 4.3 Proposed Traceable Offline Integration Cases (6 Cases)

| Case ID | Description | Verifiable Mechanism | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **AUT-INT-01** | Traceable Usage Ledger Audit | Offline file-backed ledger supplying `ProposedUsageEvidenceRecord` instances | Passes usage gate under verified ledger; rejects as `UNKNOWN_USAGE` under missing level |
| **AUT-INT-02** | Traceable Feed Coverage Audit | Feed auditor emitting `ProposedFeedCoverageRecord` across continuous ranges | Passes coverage gate when $[T_{\text{start}}, T_{\text{end}}]$ covers required interval and $T_{\text{available}} \le T_{\text{eval}}$ |
| **AUT-INT-03** | Point-in-Time Multi-Step Replay | Step-by-step evaluator testing availability boundaries against sliding $T_{\text{eval}}$ | Zero candidates until exact closed confirming candle; candidates form post-close |
| **AUT-INT-04** | Concurrent Multi-Level Gating | Dual-level setup (TJL1 and TJL2) where TJL1 is `USED` and TJL2 is `UNUSED` | TJL1 rejects (`STALE_EVIDENCE_FOR_GENERATION`); TJL2 matches (`MATCHED`) |
| **AUT-INT-05** | Persistent Usage Lingering Proof | Consumes externally supplied usage history: SET_1 touch $\rightarrow$ SET_2 replacement | SET_1 cannot revive; SET_2 recognises Level $L$ is already used |
| **AUT-INT-06** | Rearm Audit Trail Verification | Full rearm cycle with observation log: cancel $\rightarrow$ departure $\rightarrow$ retouch | Gen 1 predecessor immutable; Gen 2 active activation verified |

### 4.4 Blocked Cases Requiring Upstream Contracts (4 Cases)

| Case ID | Dependency | Description | Blocked Reason |
| :--- | :--- | :--- | :--- |
| **AUT-BLK-01** | Live MT5 Tick Authority | Streaming tick-level bid/ask sequence authority | Requires live MT5 broker connection (Excluded from offline scope) |
| **AUT-BLK-02** | Broker Calendar Authority | Exchange holiday and weekend session boundary contracts | Requires broker session calendar reconciliation (Unreconciled) |
| **AUT-BLK-03** | Automated Usage Write-Back | Automated database writes marking physical levels consumed | Strictly prohibited by read-only safety boundary |
| **AUT-BLK-04** | Distributed Event-Bus Authority | Cross-process real-time IPC event distribution | Out of scope for standalone local dashboard |

---

## 5. Authority-to-Origin Mapping

```text
+---------------------------------------------------------------------------------------------------------+
|                                           AUTHORITY ORIGIN MAP                                          |
+------------------------+------------------------------------+-------------------------------------------+
| Domain                 | Originating Layer / Contract       | Accepted Runtime Representation           |
+------------------------+------------------------------------+-------------------------------------------+
| Source Resolution      | TJLCoordinator.get_snapshot()      | MatchingContext.source_resolution_status  |
|                        | TJLSynchronizer sync snapshot      | (True -> Pass gate; False -> BLOCKED_     |
|                        |                                    |  UNRESOLVED; Missing -> UNKNOWN_AUTHORITY)|
+------------------------+------------------------------------+-------------------------------------------+
| Physical Level Usage   | Upstream Usage Ledger              | UsageEvidenceStatus                       |
|                        | StableLevelId physical persistence | (UNUSED -> Pass gate; UNKNOWN -> UNKNOWN_ |
|                        |                                    |  USAGE; USED -> STALE_EVIDENCE)           |
+------------------------+------------------------------------+-------------------------------------------+
| Feed Coverage          | Offline Data Audit Certificate     | CoverageStatus                            |
|                        | ProposedFeedCoverageRecord         | (COMPLETE -> Pass gate; INCOMPLETE or     |
|                        | (Extent + Knowledge Availability)  |  UNCERTAIN -> INCOMPLETE_COVERAGE)        |
+------------------------+------------------------------------+-------------------------------------------+
| Touch Ordering         | ExactPricePrint stream             | SequenceDomain + integer sequence_ref     |
|                        | ActivationEngine.process_event()   | (Equal time tie-breaking: seq_conf > seq) |
+------------------------+------------------------------------+-------------------------------------------+
| Confirmation Stream    | Confirmation Detector / Envelope   | ConfirmationEvidenceRecord                |
|                        | ValidatedCandleStreamEnvelope      | (close_timestamp <= T_eval;               |
|                        |                                    |  bar_status == "CONFIRMED_COMPLETED")     |
+------------------------+------------------------------------+-------------------------------------------+
| Evaluation Boundary    | Caller Point-in-Time Request       | MatchingContext.evaluation_time (T_eval)  |
|                        | Point-in-time temporal visibility  | (available_time <= T_eval gating)         |
+------------------------+------------------------------------+-------------------------------------------+
```
*(Note: Passing an individual gate is a necessary precondition; Candidate matching requires all authority gates to pass simultaneously).*

---

## 6. Unresolved Decisions & Open Questions (per `AGENTS.md`)

Per `AGENTS.md` (Strict Non-Invention Rule), the following items are formally recorded as **pending reconciliation with approved clarifications**:

1. **Broker Calendar Reconciliation**: Offline tests assume continuous 24-hour daily sessions starting at 00:00 UTC. Live broker trading sessions, Sunday opens, Friday closes, and bank holidays remain unreconciled and cannot be assumed.
2. **Persistent Usage Storage Contract**: Format, concurrency model, and durability guarantees for persistent usage recording across dashboard sessions remain unspecified. Writes remain strictly excluded under current read-only boundaries.
3. **Explicit Revocation Records**: Formal schemas and delivery protocols for explicit coverage revocation notices remain unspecified and pending reconciliation.
4. **Upstream Cursor Synchronization Proof**: The formal mechanism linking upstream MSM/TJL cursor synchronization (`processed_bar_index == received_bar_index`) to explicit `source_resolution_status` mapping remains pending reconciliation.
5. **Multi-Feed Disambiguation Authority**: When multiple feeds provide overlapping quotes for the same instrument, tie-breaking authority has not been established. Cross-domain sequence comparison is decisively rejected (`CROSS_DOMAIN_ORDERING_REJECTED`).

---

## 7. Strict Safety Boundary Enforcement

- **Requirements & Documentation Only**: Zero runtime code modified. Zero new executable modules created.
- **Safety Boundary**: Zero MT5 live trading calls, zero order placement, zero account modification, zero candidate winner selection, zero ranking/arbitration policy, zero usage ledger writes, zero final signal publication.
- **Branch Boundary**: Committed and pushed strictly on `feature/confirmation-monitor`. Merging into `main` is strictly prohibited.
