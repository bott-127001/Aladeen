# Offline Source-to-Candidate Integration Requirements & Acceptance Contract — Milestone 32

**Milestone**: Milestone 32 — Offline Source-to-Candidate Integration Requirements & Acceptance Contract  
**Active Branch**: `feature/confirmation-monitor`  
**Accepted Milestone 31 Baseline Commit**: `083d8df43c71ed0a56c6b020178dbdfdd3bf23d0` (HANDOFF-098)  
**Accepted Milestone 30 Baseline Commit**: `411f49f884fbcf417a531ad1ac75a52779ce0d7a`  
**Accepted Milestone 29 Baseline Commit**: `0144ddb8150b4132a7b60d24698105d897514cb2`  
**Requirements Baseline Commit**: `3f6689c194c95ca3761833f8831bb8a3f5b4740d`  

> [!IMPORTANT]
> **Safety Boundary & Deliverable Scope**:
> - This document defines the **integration contract, upstream authority propagation, deterministic cancellation/rearm lifecycle rules, fixture inventory with explicit execution status, and decisive assertions** connecting accepted source structural levels, activation records, independent confirmation detection, authoritative envelopes, and offline candidate matching.
> - Strictly **requirements, contract specification, and fixture inventory only**. Zero new runtime code, zero engine-rule changes, zero arbitration logic, zero usage ledger consumption, zero trade signal publication, zero order execution, zero MT5 live trading calls, and zero merging to `main`.
> - All strategy engines (`msm_engine.py`, `choch_detector.py`, `iss_engine.py`, `tjl_coordinator.py`, `activation_engine.py`, `activation_adapter.py`) remain **100% untouched (`0 diff` against `3f6689c194c95ca3761833f8831bb8a3f5b4740d`)**.

---

## 1. Domain Architecture & Concurrent Calculation Pipeline

Confirmation detection operates continuously and independently on lower-timeframe candle streams *before* and *across* higher-timeframe source activation taps. The offline matcher is invoked during batch or event evaluation to pair active activations with completed, envelopes-validated confirmation evidence:

```
┌────────────────────────────────────────────────────────┐  ┌────────────────────────────────────────────────────────┐
│ 1. Source Structural Engine (TJL Engine: D1, H4, H1)   │  │ 3. Independent Continuous Detection (LTF Candles)      │
│    - Emits immutable SourceLevelSet & Members          │  │    - MSMChochCoordinator / ISSEngine evaluate stream   │
│    - Defines geometry, direction, role (TJL1/A+),      │  │    - Operates concurrently before & across tap timing  │
│      eligibility_available_time, StableLevelId         │  │    - Emits ConfirmedChoch / ConfirmedISSEvent events   │
└──────────────────────────┬─────────────────────────────┘  └──────────────────────────┬─────────────────────────────┘
                           │ Price Touch Print                                         │ Direct Confirming Candle
                           ▼                                                           ▼
┌────────────────────────────────────────────────────────┐  ┌────────────────────────────────────────────────────────┐
│ 2. Activation Engine (Pending Activation Lifecycle)    │  │ 4. Authoritative Stream Enveloping                     │
│    - Detects touch into member [lower, upper]          │  │    - Looked up directly from input candle collection   │
│    - Manages state (PENDING_ACTIVATION, REARMED_PENDING)│  │    - ValidatedCandleStreamEnvelope (feed_id, domain)   │
│    - Tracks generation_seq, first_touch_time, obs_id   │  │    - Adapts to immutable ConfirmationEvidenceRecord    │
└──────────────────────────┬─────────────────────────────┘  └──────────────────────────┬─────────────────────────────┘
                           │                                                           │
                           └─────────────────────────────┬─────────────────────────────┘
                                                         │ Offline Match Request & Authority Context
                                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 5. Offline Confirmation Matcher (ConfirmationMatcher, ConfirmationPairMatcher, ConfirmationBatchConsolidator)      │
│    - Gated by immutable MatchingContext (source_resolution_status, current_members, evaluation_time, domain)       │
│    - Validates direction, timeframe, touch causality (touch <= confirmation_close), boundaries, and usage          │
│    - Derives setup-stable canonical identity: CAND[len(CSK):CSK[...]]                                              │
│    - Consolidates dual patterns (CHOCH + ISS) into unified CandidateSetupRecord                                    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Upstream Authority Propagation & Fail-Closed Boundaries

A calculation container or parameter wrapper (such as `MatchingContext` or `ValidatedCandleStreamEnvelope`) merely carries an assertion. Architectural integrity requires tracing each authority back to its upstream origin. If an upstream mapping is not established, it must be marked as an unresolved integration contract—it must **never** default to resolved, unused, or complete.

| Authority Domain | Upstream Authority Origin | Evaluation Container / Representation | Verification Standard & Contract | Fail-Closed Diagnostic Reason |
|---|---|---|---|---|
| **Member Resolution Authority** | Higher-timeframe market structure state transition and multi-timeframe synchronization record. | `MatchingContext.source_resolution_status: Mapping[str, bool]` | Strict boolean (`type(v) is bool`). Must be explicitly `True` for evaluated member key. If upstream source state is unresolved or unverified, marked `False` or omitted. | Non-bool: raises `TypeError`.<br>Absent key: `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`.<br>Value `False`: `BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY`. |
| **Current Membership Authority** | TJL Engine active set snapshot (`SourceLevelSet` emission from 3-point trend marking). | `MatchingContext.current_members: Mapping[str, SourceMemberReference]` | Member key `MK[{len:set}][{len:role}]` must exist in active set. Identity fields (`engine_id`, `symbol`, `source_timeframe`, `set_id`, `lower_edge`, `upper_edge`, `level_id`) must match activation. | Absent member: `MEMBERSHIP_CANCELLED_OR_REPLACED`.<br>Mismatched metadata: `CONTEXT_MISMATCH`. |
| **Usage Status Authority** | Authoritative transaction usage ledger or commit audit trail. | `SourceMemberReference.usage_evidence_status: UsageEvidenceStatus` | Must equal `UsageEvidenceStatus.UNUSED`. If upstream usage ledger is unqueried or unverified, must remain `UsageEvidenceStatus.UNKNOWN`. | `UsageEvidenceStatus.UNKNOWN`: `UNKNOWN_USAGE`.<br>Activation referencing consumed member: `STALE_EVIDENCE_FOR_GENERATION`. |
| **Stream Completeness & Coverage** | Data ingestion feed monitor and gap-detection ledger across evaluation window. | `MatchingContext.coverage_status: CoverageStatus` | Must equal `CoverageStatus.COMPLETE`. If feed gaps or sequence breaks exist, must be marked `INCOMPLETE` or `UNCERTAIN`. | `CoverageStatus.INCOMPLETE` or `UNCERTAIN`: `INCOMPLETE_COVERAGE`. |
| **Touch Observation Authority** | Validated physical trade print or quote tick inside member geometric boundary `[lower_edge, upper_edge]`. | `ActivationRecord.first_touch_time` & `trigger_observation_id` | Both fields must be present. Print price must fall within zone. Observation ID must be non-empty string. | Missing touch time or observation ID: `MISSING_TOUCH_EVIDENCE` (diagnostic without raising). |
| **Member Eligibility Causality** | Source level publication timestamp in broker source calendar. | `SourceMemberReference.eligibility_available_time: Optional[datetime]` | Must be populated. Touch observation must satisfy `first_touch_time >= eligibility_available_time`. | Missing availability time: `UNKNOWN_ELIGIBILITY_AVAILABLE_TIME`.<br>Touch before availability: `TOUCH_BEFORE_ELIGIBILITY`. |
| **Candle-Time & Completion Authority** | Lower-timeframe candle stream bar-close event. | `ValidatedCandleStreamEnvelope.candle` (`StrategyCandle`) | Candle `open_time` and `close_time` must be present. Event `confirmation_time` must equal candle `close_time`. Interval duration `(c_close - c_open)` must match declared timeframe duration. `bar_status == "CONFIRMED_COMPLETED"` and `not is_forming`. | Missing or contradictory times: `ValueError` fail-closed.<br>Incomplete bar: sets `is_completed=False`, resulting in `INCOMPLETE_EVIDENCE`. |
| **Stream & Config Authority** | Lower-timeframe strategy configuration registry and broker feed registration. | `ValidatedCandleStreamEnvelope` metadata fields | Envelope `symbol`, `feed_id`, `timeframe`, `price_basis`, `confirmation_config_id`, `confirmation_candle_id`, `sequence_domain` must agree with adapter parameters. | Parameter contradiction: `ValueError` fail-closed. |
| **Sequence Domain Authority** | Scoped engine execution run identifier binding feed and execution session. | `SequenceDomain(feed_id, run_id)` | Envelope sequence domain must match caller parameter domain. Activation domain must match evaluation sequence domain. | Cross-domain mismatch: `ValueError` at adaptation or `CROSS_DOMAIN_ORDERING_REJECTED` at matcher. |
| **Evaluation Time Horizon** | System evaluation batch timestamp boundary. | `MatchingContext.evaluation_time: datetime` | Confirmation close timestamp must satisfy `confirmation_close_timestamp <= evaluation_time`. | Evidence confirming after evaluation time: `EVIDENCE_NOT_YET_AVAILABLE`. |
| **Direction Compatibility** | Strategy directional rules (`MTF-Analysis.pdf` §3, §6). | Activation `direction` and evidence `direction` | Source trend direction must match confirmation trade direction (Bullish $\rightarrow$ Buy; Bearish $\rightarrow$ Sell). | Mismatched direction: `DIRECTION_MISMATCH`. |
| **Timeframe Mapping Compatibility** | Strategy MTF rules (`MTF-Analysis.pdf` §6: D1$\rightarrow$H1, H4$\rightarrow$M5, H1$\rightarrow$M1). | Activation `source_timeframe` and evidence `confirmation_timeframe` | Must match authorized pairs in `TIMEFRAME_CONFIRMATION_MAP`. Unsupported timeframes (e.g. M15) reject fail-closed. | Unsupported or non-mapped timeframe: `TIMEFRAME_MISMATCH` or `ValueError`. |

---

## 3. Deterministic Lifecycle Rules: Terminal Cancellation vs. Valid Rearm

To eliminate the risk of reviving invalidated memberships, the integration contract strictly distinguishes **terminal cancellation** from **rearm-eligible transient cancellation**:

```
                                  ┌────────────────────────┐
                                  │   INACTIVE_ELIGIBLE    │
                                  └───────────┬────────────┘
                                              │ Price Touch
                                              ▼
                                  ┌────────────────────────┐
                                  │   PENDING_ACTIVATION   │
                                  └───────────┬────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
        [Source Replacement]         [Source Main CHOCH]       [External Entry Commit]
                    │                         │                         │
                    ▼                         ▼                         ▼
      ┌───────────────────────────┐ ┌───────────────────┐ ┌───────────────────────────┐
      │CANCELLED_SOURCE_REPLACEMENT│ │CANCELLED_SOURCE_  │ │ CANCELLED_EXTERNAL_ENTRY  │
      │   (TERMINAL / INELIGIBLE) │ │      CHOCH        │ │   (REARM-ELIGIBLE ONLY)   │
      └───────────────────────────┘ │ (TERMINAL /       │ └─────────────┬─────────────┘
                                    │   INELIGIBLE)     │               │
                                    └───────────────────┘               ▼
                                                           [Is Price Inside or Outside?]
                                                                        │
                                        ┌───────────────────────────────┴───────────────────────────────┐
                                        │ (Path A: Inside at Cancel)                                    │ (Path B: Already Outside at Cancel)
                                        ▼                                                               ▼
                           [Wait for Outside Observation]                                   [Directly Armed for Retouch]
                                        │                                                               │
                                        └───────────────────────────────┬───────────────────────────────┘
                                                                        │
                                                                        ▼
                                                           ┌─────────────────────────┐
                                                           │    OUT_OF_ZONE_ARMED    │
                                                           └────────────┬────────────┘
                                                                        │ Later Inside Touch Observation
                                                                        ▼
                                                           ┌─────────────────────────┐
                                                           │     REARMED_PENDING     │
                                                           │  (generation_seq += 1)  │
                                                           └─────────────────────────┘
```

### 3.1. Terminal Cancellation (Strict Non-Revival)
1. **Source Replacement (`CANCELLED_SOURCE_REPLACEMENT`)**:
   - Occurs when the source timeframe TJL engine detects a new 3-point trend set, issuing a new `set_id` and replacing active levels.
   - Outgoing members are deactivated and permanently removed from `current_members`.
   - **Contract**: Replaced memberships are **terminal**. A persistent physical level (`StableLevelId`) does **NOT** authorize revival of replaced members. Any confirmation evidence referencing a replaced activation rejects fail-closed as `MEMBERSHIP_CANCELLED_OR_REPLACED`.
2. **Structural Invalidation (`CANCELLED_SOURCE_CHOCH`)**:
   - Occurs when the source timeframe forms an opposite-direction Main CHOCH, invalidating source trend direction.
   - **Contract**: Invalidated memberships are **terminal**. Activations transition to `CANCELLED_SOURCE_CHOCH`. Any confirmation evidence attempting to pair with an invalidated activation rejects fail-closed as `INELIGIBLE_ACTIVATION_STATE`.

### 3.2. Rearm-Eligible Cancellation (`CANCELLED_EXTERNAL_ENTRY`)
Cancellation permits rearm **only** when caused by an external finalized trade entry commit on a competing level (`CANCELLED_EXTERNAL_ENTRY`), and **only** while the underlying source member remains valid in `current_members` and marked `UsageEvidenceStatus.UNUSED`.

Two deterministic physical observation paths govern rearming:
- **Path A (Inside-at-Cancel)**:
  - If the price is observed inside the member zone `[lower_edge, upper_edge]` at the moment of cancellation:
  - Price must subsequently be observed *outside* the zone, transitioning to `OUT_OF_ZONE_ARMED`.
  - A subsequent physical touch print *inside* the zone transitions the activation to `REARMED_PENDING` with incremented `generation_seq` (e.g. Gen 1 $\rightarrow$ Gen 2).
- **Path B (Already-Outside-at-Cancel)**:
  - If the price was already observed outside the member zone when cancellation finalized:
  - The level directly transitions to `OUT_OF_ZONE_ARMED`.
  - The next observed touch print *inside* the zone transitions the activation to `REARMED_PENDING` with incremented `generation_seq`.

### 3.3. Rearm Causality & Generation Invalidation
- Terminal activation records remain strictly immutable. A fresh activation record is issued with an incremented `generation_seq`, fresh `first_touch_time`, and fresh `trigger_observation_id`, linked via its predecessor activation ID.
- **Causality Assertion**: Confirmation evidence must satisfy `confirmation_close_timestamp >= fresh_touch_time`. Any confirmation completed prior to the Gen 2 touch (including Gen 1 confirmation evidence) is rejected fail-closed as `PRE_ACTIVATION_CONFIRMATION` or `STALE_EVIDENCE_FOR_GENERATION`.

### 3.4. Canonical Candidate Setup Key & Setup-Stable Identity
Per the accepted matcher contract in `aladeen/strategy/confirmation_types.py` (`format_candidate_setup_key`), candidate setup identity is strictly derived from seven canonical length-prefixed parameters:

$$\text{CSK} = \text{CSK}[\text{len}:session][\text{len}:rev][\text{len}:act][\text{len}:member][\text{len}:conf\_cfg][\text{len}:candle][\text{len}:close]$$

Where:
- $session$: `domain_session_id`
- $rev$: `revision_id`
- $act$: `activation_id`
- $member$: `source_member_key` (`MK[{len:set}][{len:role}]`)
- $conf\_cfg$: `confirmation_config_id`
- $candle$: `confirmation_candle_id`
- $close$: ISO-formatted `confirmation_close_timestamp`

The final setup-stable candidate identifier wraps this canonical key:
$$\text{candidate\_id} = \text{CAND}[\text{len}(\text{CSK}):\text{CSK}]$$

This contract guarantees that distinct confirmation candles, distinct configurations, and distinct activation generations produce distinct, unambiguous candidate identities, while remaining completely invariant to whether CHOCH or ISS arrives first.

### 3.5. Multi-Pattern Batch Consolidation
When a single activation receives confirmation from both CHOCH and ISS on the designated confirmation timeframe:
- `is_consolidated = len(all_patterns) > 1` strictly evaluates to `True`.
- Multiple confirmation events under the same pattern (e.g. two CHOCH events) preserve distinct event IDs in `confirmation_event_ids` while keeping `is_consolidated = False`.
- Both event IDs are preserved in `all_event_ids` and `confirmation_event_ids`.
- Zero duplicate candidate records are produced.

---

## 4. Acceptance Fixture Inventory & Execution Matrix

Every fixture scenario is assigned an explicit execution status (`EXISTING`, `PROPOSED`, or `BLOCKED`), along with input provenance and decisive assertion:

| Case ID | Fixture Category | Input Provenance Description | Execution Status | Intended Verification Outcome & Decisive Assertion |
|---|---|---|---|---|
| **INT-01** | Genuine Candle-Derived Stream | D1 synthetic source activation + genuine H1 continuous CHOCH stream adapted from `choch_acceptance.json` (synthesized 1-hour timeline from fixture prices). | **EXISTING**<br>(`tests/test_confirmation_detector_integration.py`) | Continuous coordinator execution emits `ConfirmedChoch` at index 9; confirming candle retrieved directly from processed input stream; matches synthetic D1 activation; produces `CandidateSetupRecord` (`signal_side="SELL"`, `is_consolidated=False`). |
| **INT-02** | Genuine Candle-Derived Stream | D1 synthetic source activation + genuine H1 continuous ISS stream adapted from `iss_acceptance.json` (`iss_02_bullish_basic_end_to_end` with native timestamps and completion attributes). | **EXISTING**<br>(`tests/test_confirmation_detector_integration.py`) | ISSEngine processes canonical candles without retiming; confirming candle looked up directly by index 20; matches synthetic D1 activation; produces `CandidateSetupRecord` (`signal_side="SELL"`, `entry_reference_price=1.1120`). |
| **INT-03** | End-to-End Pipeline Integration | Genuine D1 TJL engine level emission + exact candle touch print + genuine H1 continuous CHOCH detection. | **PROPOSED**<br>(Milestone 32 Stage 2) | Proves complete candle-derived source-to-candidate chain without synthetic activation records. Asserts candidate entry reference price equals looked-up confirming candle close. |
| **INT-04** | End-to-End Pipeline Integration | Genuine D1 TJL engine level emission + exact candle touch print + genuine H1 continuous ISS detection. | **PROPOSED**<br>(Milestone 32 Stage 2) | Proves complete candle-derived source-to-candidate chain for ISS. Asserts single canonical candle collection passes to engine and adapter. |
| **ACT-01** | Exact-Print Activation Lifecycle | High-precision tick/candle touch sequence: initial touch $\rightarrow$ external commit cancel $\rightarrow$ price leaves zone $\rightarrow$ retouch. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L493) | Activation transitions Gen 1 $\rightarrow$ `CANCELLED_EXTERNAL_ENTRY` $\rightarrow$ `OUT_OF_ZONE_ARMED` $\rightarrow$ `REARMED_PENDING` (Gen 2). Rejects Gen 1 evidence as `STALE_EVIDENCE_FOR_GENERATION` or `PRE_ACTIVATION_CONFIRMATION`; matches fresh Gen 2 evidence. |
| **ACT-02** | Exact-Print Activation Lifecycle | Source replacement: new 3-point TJL set issued while activation is pending. | **PROPOSED**<br>(Milestone 32 Stage 2) | Activation transitions to `CANCELLED_SOURCE_REPLACEMENT`. Replaced member omitted from `current_members`. Subsequent confirmation evidence rejects as `MEMBERSHIP_CANCELLED_OR_REPLACED`. |
| **ACT-03** | Exact-Print Activation Lifecycle | Structural invalidation: source Main CHOCH forms while activation is pending. | **PROPOSED**<br>(Milestone 32 Stage 2) | Activation transitions to `CANCELLED_SOURCE_CHOCH`. Subsequent confirmation evidence rejects as `INELIGIBLE_ACTIVATION_STATE`. |
| **ACT-04** | Exact-Print Activation Lifecycle | Rearm Path B: price already outside zone at external commit cancellation. | **PROPOSED**<br>(Milestone 32 Stage 2) | Activation transitions directly from `CANCELLED_EXTERNAL_ENTRY` to `OUT_OF_ZONE_ARMED`. Retouch creates Gen 2 `REARMED_PENDING`. |
| **SYN-01** | Synthetic Typed Contract | Dual confirmation patterns (CHOCH + ISS) matching identical activation. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L1860) | Batch consolidator coalesces records into single `CandidateSetupRecord` with `confirmation_patterns=("CHOCH", "ISS")` and `is_consolidated=True`. |
| **SYN-02** | Synthetic Typed Contract | Multiple events of same pattern (two CHOCH events) matching identical activation. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L1844) | Coalesces into single candidate; preserves distinct event IDs in `confirmation_event_ids`; asserts `is_consolidated=False`. |
| **SYN-03** | Synthetic Typed Contract | Exhaustive permutations of activations and evidence records with duplicate IDs. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L2007) | Permutation invariance verified: outputs, candidate ordering, and setup keys are 100% identical regardless of input arrival order. |
| **SYN-04** | Synthetic Typed Contract | Defensive freezing of external mappings in `MatchingContext`. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L763) | Mutating external dictionaries after context construction has zero effect on context. Context maps wrapped in `MappingProxyType`. |
| **SYN-05** | Synthetic Typed Contract | Strict boolean validation in `source_resolution_status`. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L736) | Passing `"UNRESOLVED"` or integer `1` raises `TypeError("must be strictly a bool")`. |
| **NEG-01** | Negative Blocked Path | Confirming candle missing close time (`close_time=None`) for detector-confirmed evidence. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L1527) | Adapter adaptation fails closed immediately with `ValueError`. |
| **NEG-02** | Negative Blocked Path | Declared confirmation timeframe is unsupported (e.g. `"M15"`). | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L1558) | Adapter adaptation fails closed immediately with `ValueError`. |
| **NEG-03** | Negative Blocked Path | Envelope sequence domain is missing (`sequence_domain=None`) or contradicts parameter. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L1576, L1641) | Adapter adaptation fails closed immediately with `ValueError`. Symmetric across CHOCH and ISS. |
| **NEG-04** | Negative Blocked Path | Disagreement between event confirmation time and candle close time. | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L1706, L1738) | Adapter adaptation fails closed immediately with `ValueError`. Symmetric across CHOCH and ISS. |
| **NEG-05** | Negative Blocked Path | ISS pattern carries unresolved multi-candle pullback ambiguity (`has_unresolved_dependencies=True`). | **EXISTING**<br>(`tests/test_confirmation_detector_integration.py` L260) | Matcher returns status `BLOCKED` with reason `BLOCKED_UNRESOLVED_CONFIRMATION_GAP` and `candidate_record=None`. |
| **NEG-06** | Negative Blocked Path | Unknown source resolution authority (member key omitted from `source_resolution_status`). | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L718) | Matcher fails closed with `UNKNOWN_SOURCE_RESOLUTION_AUTHORITY`. |
| **NEG-07** | Negative Blocked Path | Touch observation occurs before member eligibility (`first_touch_time < eligibility_available_time`). | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L682) | Matcher fails closed with rejection reason `TOUCH_BEFORE_ELIGIBILITY`. |
| **NEG-08** | Negative Blocked Path | Unknown eligibility available time (`eligibility_available_time=None`). | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L664) | Matcher fails closed with rejection reason `UNKNOWN_ELIGIBILITY_AVAILABLE_TIME`. |
| **NEG-09** | Negative Blocked Path | Incomplete market data coverage (`coverage_status=CoverageStatus.INCOMPLETE`). | **EXISTING**<br>(`tests/test_confirmation_matcher.py` L380) | Matcher rejects with `INCOMPLETE_COVERAGE`. |
| **NEG-10** | Negative Blocked Path | Equal-time simultaneous confirmation close tie-breaking without arbitration authority. | **BLOCKED**<br>(Awaits Future Arbitration) | When two valid candidates have identical confirmation timestamps, selection between timeframes (M1 vs M5 vs H1) or roles (TJL2 vs TJL1) requires arbitration authority. Marked blocked pending authorized arbitration milestone. |

---

## 5. Decisive Acceptance Assertions

To guarantee complete, test-verified adherence, any implementation claiming compliance with this contract must satisfy the following decisive assertions:

1. **No Candidate Before Member Eligibility**:
   - Given activation touch timestamp $T_{\text{touch}}$ and member availability timestamp $T_{\text{avail}}$:
   - If $T_{\text{touch}} < T_{\text{avail}}$, matching fails closed with reason `TOUCH_BEFORE_ELIGIBILITY` and `candidate_record is None`.
2. **No Candidate Before Confirmation Completion**:
   - If `confirming_candle.is_forming is True` or `confirming_candle.bar_status != "CONFIRMED_COMPLETED"`:
   - Evidence adaptation sets `is_completed = False`. Matcher rejects evidence with reason `INCOMPLETE_EVIDENCE` and produces no candidate.
3. **No Candidate Reuse Across Invalidated Generations**:
   - An activation with `generation_seq = 2` must not match confirmation evidence whose confirmation timestamp occurred prior to the Gen 2 touch timestamp.
   - Any prior-generation evidence is rejected fail-closed with reason `PRE_ACTIVATION_CONFIRMATION` or `STALE_EVIDENCE_FOR_GENERATION`.
4. **No Revival of Replaced or Invalidated Memberships**:
   - An activation whose member has transitioned to `CANCELLED_SOURCE_REPLACEMENT` or `CANCELLED_SOURCE_CHOCH` must never transition to `REARMED_PENDING`.
   - Matching attempts against cancelled memberships reject with reason `MEMBERSHIP_CANCELLED_OR_REPLACED` or `INELIGIBLE_ACTIVATION_STATE`.
5. **Deterministic Repeated Evaluation & Permutation Invariance**:
   - Evaluating batch $B_1 = ([A_1, A_2], [E_1, E_2])$ and batch $B_2 = ([A_2, A_1], [E_2, E_1])$ yields identical candidates with identical setup-stable `candidate_id` values, identical ordering, and identical attributes.
6. **Zero Mutation of Accepted Engine Inputs**:
   - All external mappings passed into `MatchingContext` (`current_members`, `source_resolution_status`, `touch_sequence_evidence`) are defensively copied and wrapped in `MappingProxyType`.
   - Subsequent mutations to caller dictionaries have zero effect on internal context state.

---

## 6. Upstream Integration Contract Boundaries & Explicit Unresolved Decisions

The following architectural boundaries are explicitly identified as upstream gaps. Under no circumstances should an agent implement speculative heuristics to bridge them:

1. **Automated Multi-Timeframe Stream Coordination**:
   - In offline testing, multi-timeframe candle streams are ingested and coordinated via explicit test fixtures and stream envelopes.
   - Live multi-symbol / multi-timeframe streaming ingestion and temporal synchronization belong to a future pipeline integration milestone.
2. **Arbitration, Usage Ledger Writes & Final Signal Publication**:
   - Milestone 31 and 32 produce and validate `CandidateSetupRecord` candidates with setup-stable identity.
   - Resolving competing candidates across timeframes (M1 vs M5 vs H1 tie-breakers), executing usage ledger consumption commits, and publishing final trade signals are **future, separately authorized milestones**.
3. **Automated Multi-Candle Pullback Structural Resolution**:
   - Multi-candle pullback ISS patterns requiring complex swing-point decomposition are not resolved via arbitrary heuristics. They are explicitly flagged with `has_unresolved_dependencies = True` and fail closed.
4. **Broker Order Execution**:
   - Strictly outside project scope per [`AGENTS.md`](../../AGENTS.md). The dashboard is read-only.
