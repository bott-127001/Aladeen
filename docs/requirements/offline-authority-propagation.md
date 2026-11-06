# Offline Authority-Propagation Requirements & Acceptance Specification

**Milestone**: Milestone 34 — Offline Authority-Propagation Requirements  
**Status**: Requirements & Contract Specification (Documentation & Acceptance-Fixture Planning Only)  
**Safety Scope**: Pure offline read-only specification. Zero MT5 live trading, zero order execution, zero account modification, zero candidate arbitration/ranking, zero usage ledger writes, zero final signal publication.  
**Baseline Engine Integrity**: Strategy engines (`src/aladeen/strategy/engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`) remain 100% untouched.

---

## 1. Objective & Scope

In Milestone 33 (accepted at `b05a391554c73f80652d4dada5310510ba20fbf5`), source-to-candidate integration was proven offline on declared synthetic timelines using supplied synthetic authority assertions (usage, resolution, coverage, sequence domains).

The objective of Milestone 34 is to formally specify how these currently supplied authority assertions transition into **traceable offline inputs** without inventing upstream facts, broker feeds, or execution rights. This specification defines:
1. Exact evidence origin, identity, scope, availability, and fail-closed validation for each authority domain.
2. Decisive behaviors for missing, stale, contradictory, duplicate, or unsequenced evidence.
3. A structured acceptance inventory categorizing existing executable evidence, proposed synthetic authority contracts, proposed traceable offline integration cases, and blocked cases.
4. Authority-to-origin mapping across strategy layers.

---

## 2. Authority Inputs, Scope & Origins

A container, boolean, or enum is a representation—not its own proof. Every authority claim must be backed by an immutable, timestamped origin record evaluated strictly at the requested evaluation boundary ($T_{\text{eval}}$).

### 2.1 Domain 1: Source Resolution Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | TJL snapshot emitted by `TJLCoordinator.get_snapshot()` or synchronizer snapshot `ActivationSnapshot`. |
| **Entity Identity** | `SourceMemberKey` formatted as `format_member_key(set_id, role)` and physical `StableLevelId(symbol, timeframe, bar_time, side)`. |
| **Scope** | Bound to exact `SequenceDomain(feed_id, run_id)` and source timeframe (e.g. `D1`). |
| **Availability Time** | `EligibleSet.eligibility_available_time` ($T_{\text{avail}}$) establishing the exact closed-bar timestamp when the level set became authoritative. |
| **Validation Rules** | Level geometry must be non-inverted (`lower_edge <= upper_edge`), level width must be non-negative, direction must match coordinator configuration, and bar status must be closed (`is_forming == False`). |
| **Frozen / Unresolved Representation** | Explicitly represented via `source_resolution_status[member_key] == False` or an explicit `UnresolvedSourceNotice(last_authoritative_snapshot, processed_bar_index, received_bar_index)` emitted when upstream cursors desynchronize. |
| **Fail-Closed Behavior** | If source resolution is missing, false, or frozen, candidate formation is decisively rejected with `ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY`. Exactly 0 candidates formed. |

### 2.2 Domain 2: Usage Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Explicit offline usage evidence ledger record `UsageEvidenceRecord` or upstream source proof. |
| **Entity Identity** | Physical level identifier `StableLevelId(symbol, timeframe, bar_time, side)` (NOT the ephemeral role or set label). |
| **Scope** | Persistent physical price level. Usage authority survives level set replacements (e.g. SET_1 $\rightarrow$ SET_2) and role relabeling (e.g. TJL1 $\rightarrow$ TJL2). |
| **Availability Time** | `UsageEvidenceRecord.established_time` ($\le T_{\text{eval}}$). |
| **Permitted Statuses** | `UsageEvidenceStatus.UNUSED`, `UsageEvidenceStatus.USED`, `UsageEvidenceStatus.UNKNOWN`. |
| **Invariant: No Negative Proof** | Absence of a usage record does **NOT** prove `UNUSED`. Any level lacking explicit, authoritative proof of unused state MUST default to `UNKNOWN`. |
| **Fail-Closed Behavior** | If usage status is `UNKNOWN`, candidate matching rejects fail-closed with `ConfirmationRejectionReason.USAGE_UNCERTAIN`. If status is `USED`, matching rejects fail-closed with `ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE`. Exactly 0 candidates formed. |

### 2.3 Domain 3: Feed Coverage Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Feed completeness certificate `FeedCoverageRecord` produced by offline feed validation audit. |
| **Entity Identity** | Tuple `(feed_id, sequence_domain, timeframe, covered_interval_start, covered_interval_end, confirmation_config_id)`. |
| **Scope** | Bound strictly to the evaluated feed, interval, timeframe, and confirmation configuration. |
| **Availability Time** | `certified_until` timestamp $\ge T_{\text{eval}}$. |
| **Permitted Statuses** | `CoverageStatus.COMPLETE`, `CoverageStatus.INCOMPLETE`. |
| **Invariant: No Gap Absence Proof** | Absence of a detected candle gap does **NOT** prove completeness. The interval must be actively covered by an authoritative coverage certificate. |
| **Fail-Closed Behavior** | If coverage is `INCOMPLETE` or uncertified at $T_{\text{eval}}$, candidate matching rejects fail-closed with `ConfirmationRejectionReason.INCOMPLETE_COVERAGE`. Exactly 0 candidates formed. |

### 2.4 Domain 4: Touch Ordering & Sequence Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Exact price print stream `ExactPricePrint` delivered to `ActivationEngine.process_event()`. |
| **Entity Identity** | `observation_id` linked immutably to `ActivationRecord.trigger_observation_id` and `generation_seq`. |
| **Scope** | Bound to single, unbroken `SequenceDomain(feed_id, run_id)` with strictly monotonically increasing sequence references (`sequence_ref`). |
| **Availability Time** | `ExactPricePrint.timestamp` ($T_{\text{touch}}$) and integer `sequence_ref`. |
| **Equal-Timestamp Ordering** | Where confirmation close timestamp equals physical touch timestamp ($T_{\text{conf}} == T_{\text{touch}}$):<br>1. If sequence reference missing on either record $\rightarrow$ reject fail-closed as `ConfirmationRejectionReason.UNKNOWN_ORDER`.<br>2. If sequence domains differ $\rightarrow$ reject fail-closed as `ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED`.<br>3. If $\text{sequence\_ref}_{\text{conf}} \le \text{sequence\_ref}_{\text{touch}}$ $\rightarrow$ reject fail-closed as `ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION`.<br>4. Only if $\text{sequence\_ref}_{\text{conf}} > \text{sequence\_ref}_{\text{touch}}$ within identical domain is match causally valid. |
| **Fail-Closed Behavior** | Any sequence violation, missing reference, or cross-domain ambiguity rejects fail-closed. Exactly 0 candidates formed. |

### 2.5 Domain 5: Confirmation Stream Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Strategy confirmation detector (`CHOCHDetector`, `ISSEngine`) evaluated on closed candle stream bound within `ValidatedCandleStreamEnvelope`. |
| **Entity Identity** | `event_id`, `producer_id`, `confirmation_config_id`, `confirmation_candle_id`. |
| **Scope** | Bound to closed confirming candle, timeframe, price basis, and sequence domain. |
| **Availability Time** | `ConfirmationEvidenceRecord.close_timestamp` ($T_{\text{close}}$) equal to `StrategyCandle.close_time`. |
| **Validation Rules** | Candle must be closed (`is_forming == False`, `bar_status == "CLOSED"`), envelope must bind identical configuration and domain, evidence must contain non-empty structural dependencies (`structural_dependency_references`). |
| **Fail-Closed Behavior** | If confirmation candle is still forming, unclosed, or closed after evaluation boundary ($T_{\text{close}} > T_{\text{eval}}$), candidate matching rejects fail-closed with `ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE`. Exactly 0 candidates formed. |

### 2.6 Domain 6: Evaluation Boundary Authority

| Contract Dimension | Specification |
| :--- | :--- |
| **Evidence Origin** | Explicit caller-supplied `MatchingContext.evaluation_time` ($T_{\text{eval}}$). |
| **Scope** | Point-in-time evaluation horizon for batch or pair matching. |
| **Temporal Gating Rule** | The matcher has visibility **ONLY** into authority records where `availability_time <= T_{\text{eval}}`. Records available at $T > T_{\text{eval}}$ are strictly future evidence and fail closed. |
| **Idempotence & Immutability** | Repeated evaluations at identical $T_{\text{eval}}$ under unchanged context yield strictly equal `ConfirmationMatchResult` instances. Mutation of caller input dictionaries does not affect frozen matching context. |

---

## 3. Decisive Unknowns & Temporal Validity Rules

To ensure strict safety and non-invention, the engine must handle ambiguous, contradictory, or degraded inputs decisively fail-closed:

1. **Missing Evidence**:
   - Any required authority input (source resolution, usage, coverage, touch ordering, confirmation evidence) omitted from `MatchingContext` or records results in immediate fail-closed rejection. No default assumptions (e.g. no assuming `UNUSED` when usage is omitted).
2. **Stale Evidence**:
   - Evidence whose valid lifespan has elapsed or whose underlying source level set has been superseded (replacement via `CANCELLED_SOURCE_REPLACEMENT` or invalidation via `CANCELLED_SOURCE_CHOCH`) cannot revive. Matcher rejects fail-closed with `MEMBERSHIP_CANCELLED_OR_REPLACED` or `INELIGIBLE_ACTIVATION_STATE`.
3. **Contradictory Authority**:
   - If two authority records assert conflicting statuses for the same entity (e.g., one record asserts `UNUSED` while another asserts `USED` at the same evaluation boundary), matching fails closed with `CONTRADICTORY_AUTHORITY`.
4. **Duplicate Identities with Conflicting Payloads**:
   - If two records share an identical `activation_id`, `event_id`, or `observation_id` but differ in price, timestamp, or domain payload, the pipeline halts matching for that entity and rejects fail-closed with `CONFLICTING_RECORD_PAYLOAD`.
5. **Equal Timestamps Lacking Authoritative Ordering**:
   - Where timestamps are identical and sequence references are absent, uncomparable, or across domains, the system rejects fail-closed as `UNKNOWN_ORDER` or `CROSS_DOMAIN_ORDERING_REJECTED`.
6. **Physical-Level Usage Surviving Set Replacement**:
   - Physical price levels are tracked by `StableLevelId`. If Level $L$ is marked `USED` during `SET_1`, it remains `USED` when inherited into `SET_2`, even if its role changes from `TJL1` to `TJL2`.

---

## 4. Acceptance Inventory

The following table catalogs existing evidence, proposed synthetic authority contracts, proposed traceable offline integration cases, and blocked cases requiring upstream resolution:

| Case ID | Contract Category | Input Evidence | Expected Status / Diagnostic | No-Candidate Assertion | Execution Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **INT-01** | Existing Executable Evidence | Basic bearish D1 TJL source + touch + H1 CHOCH confirmation | `MATCHED` | 1 SELL candidate formed | Executable (Milestone 32, `test_confirmation_matcher.py`) |
| **INT-02** | Existing Executable Evidence | Basic bullish D1 TJL source + touch + H1 ISS confirmation | `MATCHED` | 1 BUY candidate formed | Executable (Milestone 32, `test_confirmation_matcher.py`) |
| **INT-03** | Existing Executable Evidence | Interleaved CHOCH schedule (5 boundaries, retained detector) | Boundaries 1..3: `[]` candidates; B4: `MATCHED` | Zero candidates prior to confirmation close | Executable (Milestone 33 accepted at `b05a391`) |
| **INT-04** | Existing Executable Evidence | Interleaved ISS schedule (5 boundaries, retained engine) | Boundaries 1..3: `[]` candidates; B4: `MATCHED` | Zero candidates prior to confirmation close | Executable (Milestone 33 accepted at `b05a391`) |
| **ACT-01** | Existing Executable Evidence | Rearm Path A: Inside at cancel $\rightarrow$ departure $\rightarrow$ retouch | `ARMED_AWAITING_RETOUCH` $\rightarrow$ `PENDING_ACTIVATION` | Immutable predecessor | Executable (`test_source_candidate_rearm.py`) |
| **ACT-02** | Existing Executable Evidence | Replacement cancellation $\rightarrow$ post-outside & post-inside prints | `CANCELLED_SOURCE_REPLACEMENT` | Zero candidates (`MEMBERSHIP_CANCELLED_OR_REPLACED`) | Executable (`test_source_candidate_cancellation.py`) |
| **ACT-03** | Existing Executable Evidence | Main CHOCH invalidation $\rightarrow$ post-outside & post-inside prints | `CANCELLED_SOURCE_CHOCH` | Zero candidates (`INELIGIBLE_ACTIVATION_STATE`) | Executable (`test_source_candidate_cancellation.py`) |
| **ACT-04** | Existing Executable Evidence | Rearm Path B: Already outside at cancel $\rightarrow$ arming $\rightarrow$ retouch | `ARMED_AWAITING_RETOUCH` $\rightarrow$ `PENDING_ACTIVATION` | Immutable predecessor | Executable (`test_source_candidate_rearm.py`) |
| **ORD-01** | Existing Executable Evidence | Timestamp tie lacking sequence reference | `UNKNOWN_ORDER` | Zero candidates | Executable (`test_source_candidate_ordering.py`) |
| **ORD-02** | Existing Executable Evidence | Timestamp tie across divergent sequence domains | `CROSS_DOMAIN_ORDERING_REJECTED` | Zero candidates | Executable (`test_source_candidate_ordering.py`) |
| **ORD-03** | Existing Executable Evidence | Timestamp tie with sequence ref $\le$ touch sequence | `PRE_ACTIVATION_CONFIRMATION` | Zero candidates | Executable (`test_source_candidate_ordering.py`) |
| **ORD-04** | Existing Executable Evidence | Timestamp tie with sequence ref $>$ touch sequence | `MATCHED` | 1 candidate formed | Executable (`test_source_candidate_ordering.py`) |
| **BND-A** | Existing Executable Evidence | Unresolved source resolution (`source_resolution_status=False`) | `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY` | Zero candidates | Executable (`test_source_candidate_authority_boundaries.py`) |
| **BND-B** | Existing Executable Evidence | Incomplete feed coverage (`CoverageStatus.INCOMPLETE`) | `INCOMPLETE_COVERAGE` | Zero candidates | Executable (`test_source_candidate_authority_boundaries.py`) |
| **BND-C** | Existing Executable Evidence | Unknown usage evidence (`UsageEvidenceStatus.UNKNOWN`) | `USAGE_UNCERTAIN` | Zero candidates | Executable (`test_source_candidate_authority_boundaries.py`) |
| **BND-D** | Existing Executable Evidence | Unresolved evidence dependencies (`has_unresolved_dependencies=True`) | `UNRESOLVED_DEPENDENCY` | Zero candidates | Executable (`test_source_candidate_authority_boundaries.py`) |
| **AUT-SYN-01** | Proposed Synthetic Contract | Contradictory usage authority (`UNUSED` vs `USED` at $T_{\text{eval}}$) | `CONTRADICTORY_AUTHORITY` | Zero candidates | Proposed Specification |
| **AUT-SYN-02** | Proposed Synthetic Contract | Expired feed coverage certificate ($T_{\text{cert}} < T_{\text{eval}}$) | `EXPIRED_COVERAGE_CERTIFICATE` | Zero candidates | Proposed Specification |
| **AUT-SYN-03** | Proposed Synthetic Contract | Coverage certificate config mismatch (`CONF_CFG_01` vs `02`) | `COVERAGE_CONFIG_MISMATCH` | Zero candidates | Proposed Specification |
| **AUT-SYN-04** | Proposed Synthetic Contract | Duplicate activation IDs with differing price payloads | `CONFLICTING_RECORD_PAYLOAD` | Zero candidates | Proposed Specification |
| **AUT-SYN-05** | Proposed Synthetic Contract | Duplicate confirmation event IDs with differing close prices | `CONFLICTING_RECORD_PAYLOAD` | Zero candidates | Proposed Specification |
| **AUT-SYN-06** | Proposed Synthetic Contract | Persistent usage across set replacement (SET_1 used $\rightarrow$ SET_2) | `INELIGIBLE_ACTIVATION_STATE` | Zero candidates | Proposed Specification |
| **AUT-SYN-07** | Proposed Synthetic Contract | Evaluation boundary preceding availability ($T_{\text{eval}} < T_{\text{avail}}$) | `SOURCE_NOT_YET_AVAILABLE` | Zero candidates | Proposed Specification |
| **AUT-SYN-08** | Proposed Synthetic Contract | Unresolved upstream cursor notice (`UnresolvedSourceNotice`) | `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY` | Zero candidates | Proposed Specification |
| **AUT-INT-01** | Proposed Traceable Offline Case | Traceable usage ledger audit trail with SHA256 record hashes | `MATCHED` under valid ledger; rejected under missing hash | Zero candidates on invalid hash | Proposed Specification |
| **AUT-INT-02** | Proposed Traceable Offline Case | Feed coverage audit trail with gap-certified candle ranges | `MATCHED` under full audit; rejected on uncertified sub-range | Zero candidates on uncertified range | Proposed Specification |
| **AUT-INT-03** | Proposed Traceable Offline Case | End-to-end multi-candle replay with point-in-time authority checks | Decisive candidate transition at exact closed candle | Zero candidates at intermediate steps | Proposed Specification |
| **AUT-INT-04** | Proposed Traceable Offline Case | Multi-level concurrent activation with independent usage proofs | Isolated candidate formation per level | Independent gating per level | Proposed Specification |
| **AUT-INT-05** | Proposed Traceable Offline Case | Invalidation replay with lingering usage verification | Preserved terminal history; persistent level usage | Zero revival | Proposed Specification |
| **AUT-INT-06** | Proposed Traceable Offline Case | Rearm cycle with audit trail of departure/retouch observations | Gen 2 candidate with immutable Gen 1 predecessor | Zero Gen 1 revival | Proposed Specification |
| **AUT-BLK-01** | Blocked Case | Multi-broker cross-feed tick authority | Blocked: requires live MT5 feed contract | Blocked | Blocked (Requires Samarth MT5 broker contract) |
| **AUT-BLK-02** | Blocked Case | Broker calendar holiday/weekend gap authority | Blocked: requires broker session schedule contract | Blocked | Blocked (Requires broker calendar reconciliation) |
| **AUT-BLK-03** | Blocked Case | Automated usage write-back to persistent database ledger | Blocked: writes prohibited by read-only safety boundary | Blocked | Blocked (Safety boundary exclusion) |
| **AUT-BLK-04** | Blocked Case | Production live event-bus authority propagation | Blocked: requires IPC / distributed architecture | Blocked | Blocked (Out of local dashboard scope) |

---

## 5. Authority-to-Origin Mapping

The following mapping establishes the architectural source of truth for each authority domain:

```
+---------------------------------------------------------------------------------------+
|                                 AUTHORITY ORIGIN MAP                                  |
+---------------------------------------------------------------------------------------+
| Domain                 | Originating Layer / Contract       | Runtime Representation  |
+------------------------+------------------------------------+-------------------------+
| Source Resolution      | TJLCoordinator / Synchronizer      | SourceMemberReference   |
|                        | get_snapshot().current_eligible_set| source_resolution_status|
+------------------------+------------------------------------+-------------------------+
| Level Usage            | Upstream Usage Ledger              | UsageEvidenceStatus     |
|                        | StableLevelId persistence          | (UNUSED, USED, UNKNOWN) |
+------------------------+------------------------------------+-------------------------+
| Feed Coverage          | Offline Data Audit Certificate     | CoverageStatus          |
|                        | FeedCoverageRecord (timeframe/feed)| (COMPLETE, INCOMPLETE)  |
+------------------------+------------------------------------+-------------------------+
| Touch Sequence         | ExactPricePrint stream             | SequenceDomain +        |
|                        | ActivationEngine.process_event()   | integer sequence_ref    |
+------------------------+------------------------------------+-------------------------+
| Confirmation Stream    | Confirmation Detector / Envelope   | ConfirmationEvidence    |
|                        | ValidatedCandleStreamEnvelope      | Record + close_timestamp|
+------------------------+------------------------------------+-------------------------+
| Evaluation Boundary    | Caller Point-in-Time Request       | MatchingContext         |
|                        | evaluation_time (T_eval)           | evaluation_time         |
+------------------------+------------------------------------+-------------------------+
```

---

## 6. Unresolved Decisions & Open Questions

Per `AGENTS.md` (Strict Non-Invention Rule), the following items are formally recorded as **pending reconciliation with approved clarifications**:

1. **Broker Calendar Reconciliation**: Offline tests assume continuous 24-hour daily sessions starting at 00:00 UTC. Live broker trading sessions, Sunday opens, Friday closes, and bank holidays remain unreconciled and cannot be assumed.
2. **Persistent Usage Storage Contract**: The format, concurrency model, and durability guarantees for persistent usage recording across dashboard sessions remain unspecified. Writes remain strictly excluded under current read-only boundaries.
3. **Multi-Feed Disambiguation Authority**: When multiple feeds provide overlapping quotes for the same instrument (e.g. broker raw feed vs synthetic test feed), the tie-breaking authority has not been established. Cross-domain sequence comparison is decisively rejected (`CROSS_DOMAIN_ORDERING_REJECTED`).

---

## 7. Strict Safety Boundary Enforcement

- **Read-Only Invariant**: Pure offline specification. Zero MT5 order execution, zero automated trade placement, zero account balance modification.
- **No In-Scope Strategy Engine Modifications**: Core engines (`src/aladeen/strategy/engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`) remain 100% untouched.
- **Dedicated Branch**: All work committed strictly on `feature/confirmation-monitor`. Merging into `main` is prohibited.
