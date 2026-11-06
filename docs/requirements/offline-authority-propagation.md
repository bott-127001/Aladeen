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
2. Concrete schemas, fields, trust boundaries, and supersession behaviors for proposed authority records.
3. Decisive fail-closed behaviors for missing, stale, contradictory, duplicate, or unsequenced evidence, strictly aligned with accepted runtime types and diagnostics.
4. A 34-case acceptance inventory categorizing existing executable evidence, proposed synthetic authority contracts, proposed traceable offline integration cases, and blocked cases.
5. Authority-to-origin mapping across strategy layers.

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
| **Availability Time** | `established_time` ($\le T_{\text{eval}}$) and `available_time` ($\le T_{\text{eval}}$). |
| **Accepted Runtime Contract** | Status values from `UsageEvidenceStatus`: `UNUSED`, `USED`, `UNKNOWN`.<br>- If `UNKNOWN`: rejects fail-closed as `ConfirmationRejectionReason.UNKNOWN_USAGE`.<br>- If `USED`: rejects fail-closed as `ConfirmationRejectionReason.STALE_EVIDENCE_FOR_GENERATION` (if active generation has consumed it) or `ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE` (if activation is terminal). |
| **Invariant: No Negative Proof** | Absence of a usage record does **NOT** prove `UNUSED`. Any level lacking explicit, authoritative proof of unused state MUST default to `UNKNOWN`. |

### 2.3 Domain 3: Feed Coverage Authority — Separation of Extent from Knowledge Availability

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Feed completeness certificate `ProposedFeedCoverageRecord` issued by an authoritative offline feed audit process. |
| **Entity Identity** | `(feed_id, sequence_domain, timeframe, covered_interval_start, covered_interval_end, confirmation_config_id)`. |
| **Coverage Extent** | The closed interval $[T_{\text{covered\_start}}, T_{\text{covered\_end}}]$ across which continuous, gap-free bar data has been verified. |
| **Knowledge Availability Time** | The timestamp $T_{\text{issued}}$ when the coverage certificate was generated and made available to the system. |
| **Required Evaluation Interval** | The stream interval $[T_{\text{req\_start}}, T_{\text{req\_end}}]$ required by the confirmation configuration up to $T_{\text{eval}}$. |
| **Two-Part Decisive Acceptance Rule** | An evaluation at $T_{\text{eval}}$ is authorized for coverage **if and only if both conditions are met**:<br>1. **Spatial Coverage**: $T_{\text{covered\_start}} \le T_{\text{req\_start}}$ AND $T_{\text{covered\_end}} \ge T_{\text{req\_end}}$.<br>2. **Temporal Knowledge Availability**: $T_{\text{issued}} \le T_{\text{eval}}$.<br>*Retroactive Prohibition*: A certificate issued at $T_{\text{issued}} > T_{\text{eval}}$ cannot retroactively authorize an evaluation at $T_{\text{eval}}$, even if its covered extent covers that historical time. |
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
| **Temporal Visibility Gating** | Matcher has visibility **ONLY** into authority records where $\text{availability\_time} \le T_{\text{eval}}$. Future records are invisible and fail closed. |
| **Immutability & Idempotence** | Repeated evaluations at identical $T_{\text{eval}}$ yield strictly identical `ConfirmationMatchResult` instances (`res1 == res2`). External caller mutations of context dictionaries do not affect the frozen context. |

---

## 3. Explicit Proposed Authority Record Schemas

To transition from synthetic assertions to traceable inputs, we propose explicit, typed schemas. These schemas are proposed contract extensions and do not modify existing accepted runtime types.

### 3.1 Proposed Usage Evidence Record (`ProposedUsageEvidenceRecord`)

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
    optional_integrity_hash: Optional[str] = None  # Optional SHA-256 for tampering detection (NOT authority proof)
```

**Trust & Validation Rules**:
- **Trust Assumption**: Issued only by an approved upstream trading ledger or authorized offline fixture harness.
- **Physical Level Persistence**: The `level_id` is tied to the physical candle geometry, not the transient set ID. If Level $L$ is marked `USED`, that status persists even if SET_1 is replaced by SET_2.
- **Duplicate Handling**: If two records with identical `record_id` have differing payloads, the matcher halts matching for that level and emits `ConfirmationRejectionReason.CONFLICTING_IDENTITY`.
- **Supersession**: A record with `status == USED` is terminal for that physical level. It cannot be superseded by a later `UNUSED` record.

### 3.2 Proposed Feed Coverage Record (`ProposedFeedCoverageRecord`)

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
    issued_time: datetime                   # Knowledge availability timestamp (when certificate was published)
```

**Trust & Validation Rules**:
- **Trust Assumption**: Generated by an offline feed gap auditor inspecting raw MT5 historical export files.
- **Point-in-Time Evaluation Rule**: At evaluation time $T_{\text{eval}}$, the record is considered valid only if $T_{\text{issued}} \le T_{\text{eval}}$. A certificate generated at 16:00 UTC cannot be used to justify an evaluation at 12:00 UTC.
- **Duplicate & Supersession Rules**: If two certificates conflict on status for overlapping intervals, status degrades to `CoverageStatus.UNCERTAIN` $\rightarrow$ fail-closed. Newer revisions supersede older ones only after $T_{\text{issued}}$.

---

## 4. Acceptance Inventory (34 Cases)

The inventory catalogs 34 discrete cases across 4 categories:

### 4.1 Existing Executable Evidence (16 Cases)

| Case ID | Contract & File Reference | Input Evidence | Expected Status / Reason | Result Assertion |
| :--- | :--- | :--- | :--- | :--- |
| **INT-01** | Bearish CHOCH Matching (`tests/test_confirmation_matcher.py` L2160) | Synthetic member + H1 CHOCH envelope | `MATCHED` | 1 SELL candidate (1.0850) |
| **INT-02** | Bearish ISS Matching (`tests/test_confirmation_matcher.py` L2240) | Synthetic member + H1 ISS envelope | `MATCHED` | 1 SELL candidate (1.1120) |
| **INT-03** | Interleaved CHOCH Schedule (`tests/test_source_candidate_choch_chain.py`) | Retained CHOCH detector across 5 boundaries | B1..3: `[]`; B4: `MATCHED` | Zero candidates prior to close; 1 SELL candidate at close |
| **INT-04** | Interleaved ISS Schedule (`tests/test_source_candidate_iss_chain.py`) | Retained ISS engine across 5 boundaries | B1..3: `[]`; B4: `MATCHED` | Zero candidates prior to close; 1 SELL candidate at close |
| **ACT-01** | Rearm Path A (`tests/test_source_candidate_rearm.py`) | Inside at cancel $\rightarrow$ departure $\rightarrow$ retouch | `OUT_OF_ZONE_ARMED` $\rightarrow$ `REARMED_PENDING` | Predecessor immutable |
| **ACT-02** | Replacement Cancellation (`tests/test_source_candidate_cancellation.py`) | Set replacement $\rightarrow$ post-out/in prints | `CANCELLED_SOURCE_REPLACEMENT` | Zero candidates (`MEMBERSHIP_CANCELLED_OR_REPLACED`) |
| **ACT-03** | Main CHOCH Invalidation (`tests/test_source_candidate_cancellation.py`) | Invalidation $\rightarrow$ post-out/in prints | `CANCELLED_SOURCE_CHOCH` | Zero candidates (`INELIGIBLE_ACTIVATION_STATE`) |
| **ACT-04** | Rearm Path B (`tests/test_source_candidate_rearm.py`) | Outside at cancel $\rightarrow$ arming $\rightarrow$ retouch | `OUT_OF_ZONE_ARMED` $\rightarrow$ `REARMED_PENDING` | Predecessor immutable |
| **ORD-01** | Equal Time Missing Sequence (`tests/test_source_candidate_ordering.py`) | $T_{\text{conf}} == T_{\text{touch}}$, missing seq | `UNKNOWN_ORDER` | Zero candidates |
| **ORD-02** | Equal Time Cross-Domain (`tests/test_source_candidate_ordering.py`) | $T_{\text{conf}} == T_{\text{touch}}$, domain mismatch | `CROSS_DOMAIN_ORDERING_REJECTED` | Zero candidates |
| **ORD-03** | Equal Time Earlier/Equal Seq (`tests/test_source_candidate_ordering.py`) | $T_{\text{conf}} == T_{\text{touch}}$, seq $\le$ touch | `PRE_ACTIVATION_CONFIRMATION` | Zero candidates |
| **ORD-04** | Equal Time Causal Seq (`tests/test_source_candidate_ordering.py`) | $T_{\text{conf}} == T_{\text{touch}}$, seq $>$ touch | `MATCHED` | 1 candidate formed |
| **BND-A** | Boundary A: Usage (`tests/test_source_candidate_authority_boundaries.py`) | `UsageEvidenceStatus.UNKNOWN` | `UNKNOWN_USAGE` | Zero candidates |
| **BND-B** | Boundary B: Coverage (`tests/test_source_candidate_authority_boundaries.py`) | `CoverageStatus.INCOMPLETE` / `UNCERTAIN` | `INCOMPLETE_COVERAGE` | Zero candidates |
| **BND-C** | Boundary C: Source Resolution (`tests/test_source_candidate_authority_boundaries.py`) | `source_resolution_status == False` | `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY` | Zero candidates |
| **BND-D** | Boundary D: Evidence Dependencies (`tests/test_source_candidate_authority_boundaries.py`) | `has_unresolved_dependencies == True` | `UNRESOLVED_DEPENDENCY` | Zero candidates |

### 4.2 Proposed Synthetic Authority Contracts (8 Cases)

| Case ID | Contract Description | Test Setup | Expected Reason | Candidate Assertion |
| :--- | :--- | :--- | :--- | :--- |
| **AUT-SYN-01** | Contradictory Usage Evidence | Two records for same `level_id` asserting `UNUSED` and `USED` at $T_{\text{eval}}$ | Proposed: degrade to `UNKNOWN_USAGE` / `CONFLICTING_IDENTITY` | Zero candidates |
| **AUT-SYN-02** | Retroactive Coverage Rejection | Coverage extent covers interval, but $T_{\text{issued}} > T_{\text{eval}}$ | `INCOMPLETE_COVERAGE` (not yet known at $T_{\text{eval}}$) | Zero candidates |
| **AUT-SYN-03** | Coverage Config Mismatch | Certificate generated for `CONF_CFG_02`, evaluation requests `CONF_CFG_01` | `INCOMPLETE_COVERAGE` | Zero candidates |
| **AUT-SYN-04** | Duplicate Conflicting Activations | Duplicate `activation_id` with contradictory touch prices | `CONFLICTING_IDENTITY` | Zero candidates |
| **AUT-SYN-05** | Duplicate Conflicting Confirmations | Duplicate `event_id` with contradictory close prices | `CONFLICTING_IDENTITY` | Zero candidates |
| **AUT-SYN-06** | Persistent Usage on Set Replacement | SET_1 uses Level $L$ (`USED`); SET_2 created on Level $L$; touch occurs | `STALE_EVIDENCE_FOR_GENERATION` | Zero candidates (Level $L$ used) |
| **AUT-SYN-07** | Evaluation Before Availability | Evaluation requested at $T_{\text{eval}} < T_{\text{avail}}$ of source set | Missing member in `current_members` | Zero candidates |
| **AUT-SYN-08** | Incomplete Confirmation Candle | Candle has `is_forming == True` or `bar_status != "CONFIRMED_COMPLETED"` | `INCOMPLETE_EVIDENCE` | Zero candidates |

### 4.3 Proposed Traceable Offline Integration Cases (6 Cases)

| Case ID | Description | Verifiable Mechanism | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **AUT-INT-01** | Traceable Usage Ledger Audit | Offline file-backed ledger supplying `ProposedUsageEvidenceRecord` instances | Matches under verified ledger; rejects as `UNKNOWN_USAGE` under missing level |
| **AUT-INT-02** | Traceable Feed Coverage Audit | Feed auditor emitting `ProposedFeedCoverageRecord` across continuous ranges | Matches when $[T_{\text{start}}, T_{\text{end}}]$ covers required interval and $T_{\text{issued}} \le T_{\text{eval}}$ |
| **AUT-INT-03** | Point-in-Time Multi-Step Replay | Step-by-step evaluator testing availability boundaries against sliding $T_{\text{eval}}$ | Zero candidates until exact closed confirming candle; candidates form post-close |
| **AUT-INT-04** | Concurrent Multi-Level Gating | Dual-level setup (TJL1 and TJL2) where TJL1 is `USED` and TJL2 is `UNUSED` | TJL1 rejects (`STALE_EVIDENCE_FOR_GENERATION`); TJL2 matches (`MATCHED`) |
| **AUT-INT-05** | Persistent Usage Lingering Proof | Full lifecycle: SET_1 touch $\rightarrow$ usage commit $\rightarrow$ SET_2 replacement | SET_1 cannot revive; SET_2 recognises Level $L$ is already used |
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
|                        | TJLSynchronizer sync snapshot      | (Missing -> UNKNOWN_SOURCE_RESOLUTION_    |
|                        |                                    |  AUTHORITY; False -> BLOCKED_UNRESOLVED_  |
|                        |                                    |  SOURCE_DEPENDENCY)                       |
+------------------------+------------------------------------+-------------------------------------------+
| Physical Level Usage   | Upstream Usage Ledger              | UsageEvidenceStatus                       |
|                        | StableLevelId physical persistence | (UNUSED -> Match; UNKNOWN -> UNKNOWN_    |
|                        |                                    |  USAGE; USED -> STALE_EVIDENCE)           |
+------------------------+------------------------------------+-------------------------------------------+
| Feed Coverage          | Offline Data Audit Certificate     | CoverageStatus                            |
|                        | ProposedFeedCoverageRecord         | (COMPLETE -> Match; INCOMPLETE/UNCERTAIN  |
|                        | (Extent + Knowledge Availability)  |  -> INCOMPLETE_COVERAGE)                  |
+------------------------+------------------------------------+-------------------------------------------+
| Touch Ordering         | ExactPricePrint stream             | SequenceDomain + integer sequence_ref     |
|                        | ActivationEngine.process_event()   | (Equal time tie-breaking: seq_conf > seq) |
+------------------------+------------------------------------+-------------------------------------------+
| Confirmation Stream    | Confirmation Detector / Envelope   | ConfirmationEvidenceRecord                |
|                        | ValidatedCandleStreamEnvelope      | (close_timestamp <= T_eval;               |
|                        |                                    |  bar_status == "CONFIRMED_COMPLETED")     |
+------------------------+------------------------------------+-------------------------------------------+
| Evaluation Boundary    | Caller Point-in-Time Request       | MatchingContext.evaluation_time (T_eval)  |
|                        | Point-in-time temporal visibility  | (availability_time <= T_eval gating)      |
+------------------------+------------------------------------+-------------------------------------------+
```

---

## 6. Unresolved Decisions & Open Questions (per `AGENTS.md`)

Per `AGENTS.md` (Strict Non-Invention Rule), the following items are formally recorded as **pending reconciliation with approved clarifications**:

1. **Broker Calendar Reconciliation**: Offline tests assume continuous 24-hour daily sessions starting at 00:00 UTC. Live broker trading sessions, Sunday opens, Friday closes, and bank holidays remain unreconciled and cannot be assumed.
2. **Persistent Usage Storage Contract**: Format, concurrency model, and durability guarantees for persistent usage recording across dashboard sessions remain unspecified. Writes remain strictly excluded under current read-only boundaries.
3. **Upstream Cursor Synchronization Proof**: The formal mechanism linking upstream MSM/TJL cursor synchronization (`processed_bar_index == received_bar_index`) to explicit `source_resolution_status` mapping remains pending reconciliation.
4. **Multi-Feed Disambiguation Authority**: When multiple feeds provide overlapping quotes for the same instrument, tie-breaking authority has not been established. Cross-domain sequence comparison is decisively rejected (`CROSS_DOMAIN_ORDERING_REJECTED`).

---

## 7. Strict Safety Boundary Enforcement

- **Requirements & Documentation Only**: Zero runtime code modified. Zero new executable modules created.
- **Safety Boundary**: Zero MT5 live trading calls, zero order placement, zero account modification, zero candidate winner selection, zero ranking/arbitration policy, zero usage ledger writes, zero final signal publication.
- **Branch Boundary**: Committed and pushed strictly on `feature/confirmation-monitor`. Merging into `main` is strictly prohibited.
