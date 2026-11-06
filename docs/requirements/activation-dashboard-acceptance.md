# Activation Read-Only Dashboard Integration — Requirements & Acceptance Specification

**Milestone**: Requirements & Acceptance Contract for Read-Only Activation Dashboard Integration (HANDOFF-065)  
**Accepted Engine Baseline**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)  
**Branch**: `requirements/activation-dashboard-acceptance`  
**Status**: Requirements & Acceptance Specification Phase (Zero runtime changes)  

---

## 1. Executive Summary, Bounded Scope & Explicit Exclusions

### 1.1 Purpose & Bounded Scope
Defines the presentation contract, UI evidence mapping, data ownership rules, offline evidence boundary, and deterministic acceptance scenarios for displaying pure offline activation lifecycle evidence within the Aladeen read-only dashboard.
- **Pure Presentation Projection**: Pure functional mapping from immutable domain snapshots (`ActivationSnapshot`, `TJLSnapshot`) to dashboard UI components.
- **Exact-Observation Semantics**: Exact observed price evidence (`ExactPricePrint`) alone establishes an activation touch. OHLC candle overlap, interpolated paths, or candle intervals alone **cannot** establish a touch. An interval's ordering flag does not manufacture an independent exact observation.
- **Evidence Gating Transparency**: Render usage evidence (`UNUSED`, `USED`, `UNKNOWN`), coverage status (`COMPLETE`, `INCOMPLETE`, `UNCERTAIN`), and raw fail-closed blocked reasons (`USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`, `UNKNOWN_AVAILABILITY_TIMING`, `BLOCKED_UNKNOWN_ORDER`).
- **Retained Synchronizer Ownership**: Service layer owns `TJLSynchronizer`. Rendering never instantiates transient synchronizers or mutates state.
- **Deterministic Presentation**: Component trees and sort orders are bit-for-bit identical across repeated renders.

### 1.2 Strict Exclusions
Strictly zero order execution, zero MT5 trading calls, zero live account modification, zero confirmation detection/arbitration, zero cross-timeframe ranking/winner selection, zero usage-ledger commits/writes, and zero trade entry signals. Upstream $c_1 == p_2$ boundary ambiguity and ISS multi-candle pullbacks remain isolated and unresolved. No merge into `main`.

---

## 2. Non-Negotiable Presentation Semantics

1. **Pending Does Not Mean Actionable**: `PENDING_ACTIVATION` indicates solely an exact price touch on an eligible zone on or after availability. Displays prominent disclaimer: `"LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL"`. Uncertain usage or coverage visibly blocks actionability.
2. **Distinguishing Registered Members from Evidence-Eligible Members**: A registered member is in `current_members`. An evidence-eligible member is in `INACTIVE_ELIGIBLE` with known/satisfied availability and `UNUSED` usage. Missing usage defaults to `UNKNOWN`, rendering untouched members `INACTIVE_INELIGIBLE` (`USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`) until verified `UNUSED`.
3. **History Is Not Current Eligibility**: Terminal outcomes (`CANCELLED_*`) are immutable historical records in a separate history table. Rearm controllers manage outside departure and are not active activations. Cancelled outgoing set IDs and member keys are retired immediately. Distinct successor sets (`SET_2`) with same physical level display distinct set IDs.
4. **Unknown Stays Unknown**: Missing evidence displays as `"Unknown"` or `"—"`. Zero wall-clock timestamp substitution, interpolated touch times, or fabricated ordering. Cancellation timestamp column shows `"Unknown"`; sequence reference displays in its separate column (`"#125"`).
5. **Unresolved Source Evidence Remains Visible**: Upstream unresolved snapshots display canonical banner: `"LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"`, showing processed bar (`last_processed_index`) vs received bar (`last_received_index`).

---

## 3. Public Field Input & Provenance Matrix

Every rendered field maps directly to public dataclass attributes without inventing domain fields:

| Group | UI Display Field | Source Object | Exact Public Attribute | Availability | Missing Value | Authoritative Key |
|---|---|---|---|---|---|---|
| **G1 Context** | Engine ID | `ActivationSnapshot` | `.engine_id` | Always | `"None"` | Snapshot attribute |
| **G1 Context** | Symbol / Feed ID | `ActivationSnapshot` | `.symbol` | Always | `"None"` | Snapshot attribute |
| **G1 Context** | Source Timeframe | `ActivationSnapshot` | `.source_timeframe` | Always | `"None"` | Snapshot attribute |
| **G1 Context** | Mapped Confirmation TF | `ActivationSnapshot` | `.confirmation_timeframe` | Always | `"None"` | Snapshot attribute (metadata mapping) |
| **G1 Context** | Sequence Domain Feed ID | `ActivationSnapshot` | `.sequence_domain.feed_id` | Always | `"None"` | Snapshot attribute |
| **G1 Context** | Sequence Domain Run ID | `ActivationSnapshot` | `.sequence_domain.run_id` | Always | `"None"` | Snapshot attribute |
| **G2 Membership** | Set ID | `SourceMemberReference` | `.set_id` | Always | `"None"` | Keyed by `member_key` in `current_members` |
| **G2 Membership** | Role | `SourceMemberReference` | `.role` | Always | `"None"` | Keyed by `member_key` in `current_members` |
| **G2 Membership** | Stable Level ID | `SourceMemberReference` | `.level_id` | Optional | `"—"` | Direct attribute on member reference |
| **G2 Membership** | Physical Level Side | `SourceMemberReference` | `.side` | Always | `"None"` | Direct attribute on member reference |
| **G2 Membership** | Lower Edge Price | `SourceMemberReference` | `.lower_edge` | Always | `"Unknown"` | Precision-preserving float string |
| **G2 Membership** | Upper Edge Price | `SourceMemberReference` | `.upper_edge` | Always | `"Unknown"` | Precision-preserving float string |
| **G2 Membership** | Thickness-0 Line Flag | `SourceMemberReference` | `.is_line` | Always | `"False"` | Direct boolean |
| **G2 Membership** | Available Time | `SourceMemberReference` | `.eligibility_available_time` | Optional | `"Unknown"` | Formatted ISO UTC or `"Unknown"` |
| **G3 Activation** | Activation ID | `ActivationRecord` | `.activation_id` | Always | `"None"` | Keyed by `member_key` in `active_activations` |
| **G3 Activation** | Lifecycle State | `ActivationRecord` | `.state.value` | Always | `"None"` | States: `INACTIVE_ELIGIBLE`, `INACTIVE_INELIGIBLE`, `PENDING_ACTIVATION`, `REARMED_PENDING`, `BLOCKED_UNKNOWN_ORDER` |
| **G3 Activation** | Generation Sequence | `ActivationRecord` | `.generation_seq` | Always | `"0"` | Integer generation count |
| **G3 Activation** | First Touch Time | `ActivationRecord` | `.first_touch_time` | Optional | `"—"` | Formatted ISO UTC if present |
| **G3 Activation** | First Touch Price | `ActivationRecord` | `.first_touch_price` | Optional | `"—"` | Precision-preserving float string |
| **G3 Activation** | Trigger Observation ID | `ActivationRecord` | `.trigger_observation_id` | Optional | `"—"` | String ID if present |
| **G3 Activation** | Prior Activation ID | `ActivationRecord` | `.prior_activation_id` | Optional | `"—"` | Canonical ID linking reactivated generation |
| **G4 Gating** | Usage Evidence Status | `ActivationRecord` | `.usage_evidence_status.value` | Always | `"UNKNOWN"` | Enum: `UNUSED`, `USED`, `UNKNOWN` |
| **G4 Gating** | Coverage Status | `ActivationSnapshot` | `.coverage_status.value` | Always | `"UNKNOWN"` | Enum: `COMPLETE`, `INCOMPLETE`, `UNCERTAIN` |
| **G4 Gating** | Blocked Reason | `ActivationRecord` | `.blocked_reason` | Optional | `"—"` | Raw domain string (e.g. `UNKNOWN_AVAILABILITY_TIMING`) |
| **G5 Cancel** | Cancellation Reason | `ActivationRecord` | `.cancellation_reason.value` | Optional | `"—"` | Sourced from terminal `ActivationRecord` |
| **G5 Cancel** | Cancellation Time | `ActivationRecord` | `.cancellation_time` | Optional | `"Unknown"` | Dedicated Timestamp Column: Formatted UTC or `"Unknown"` |
| **G5 Cancel** | Cancellation Sequence | `ActivationRecord` | `.cancellation_sequence_ref` | Optional | `"—"` | Dedicated Sequence Column: `f"#{val}"` or `"—"` |
| **G5 Cancel** | Cancelled Set ID | `ActivationRecord` | `.set_id` | Always | `"None"` | Record's own immutable set ID (no event target reconstruction) |
| **G5 Cancel** | Cancelled Role | `ActivationRecord` | `.role` | Always | `"None"` | Record's own immutable role |
| **G6 Rearm** | Controller Key | `RearmController` | `.member_key` | Always | `"None"` | Keyed by `member_key` in `rearm_controllers` |
| **G6 Rearm** | Prior Activation ID | `RearmController` | `.prior_activation_id` | Always | `"None"` | Authoritative link to terminal activation |
| **G6 Rearm** | Controller State | `RearmController` | `.state.value` | Always | `"None"` | `CANCELLED_EXTERNAL_ENTRY` or `OUT_OF_ZONE_ARMED` |
| **G6 Rearm** | Rearm Armed Flag | `RearmController` | `.rearm_armed` | Always | `"False"` | True if outside departure observed |
| **G6 Rearm** | Last Observed Pos | `RearmController` | `.last_observed_position` | Optional | `"Unknown"` | `"INSIDE"` or `"OUTSIDE"` |
| **G7 History** | Terminal Activations | `ActivationSnapshot` | `.terminal_activations` | Always | `[]` | Immutable sequence of terminal `ActivationRecord`s |
| **G8 Sync** | Engine Last Seq | `ActivationSnapshot` | `.last_processed_sequence` | Optional | `"—"` | Engine sequence cursor (not observation count) |
| **G8 Sync** | Engine Last Time | `ActivationSnapshot` | `.last_processed_timestamp` | Optional | `"—"` | Engine timestamp cursor |
| **G8 Sync** | Synced Trans Index | `TJLSynchronizer` | `.last_synced_transition_index` | Optional | `"—"` | Sourced from synchronizer (not snapshot) |
| **G8 Sync** | Source Unresolved | `TJLSnapshot` | `.is_unresolved` | Always | `"False"` | Sourced from `TJLSnapshot` / `MSMServiceResult` |
| **G8 Sync** | Unresolved Diag | `TJLSnapshot` | `.unresolved_diagnostic` | Optional | `"—"` | Sourced from `TJLSnapshot` / `MSMServiceResult` |
| **G8 Sync** | Processed Bar Index | `TJLSnapshot` | `.last_processed_index` | Always | `"-1"` | Authoritative bar from `TJLSnapshot` |
| **G8 Sync** | Received Bar Index | `TJLSnapshot` | `.last_received_index` | Always | `"-1"` | Latest received bar from `TJLSnapshot` |

---

## 4. Offline Service Evidence Boundary, Observation Lifecycle & Architecture Safeguards

### 4.1 Offline Evidence-Source Boundary & Input Rules
1. **Strict Offline Evidence-Source Boundary**:
   - **No Candle OHLC Print Synthesis**: Candle OHLC values (open, high, low, close) must never be synthesized or interpolated into price prints. Exact price prints (`ExactPricePrint`) are sourced strictly from discrete offline tick/trade streams.
   - **Fail-Closed Usage Default**: Usage evidence status defaults strictly to `UNKNOWN` in the absence of explicit authoritative usage evidence, rendering untouched members `INACTIVE_INELIGIBLE` (`USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`).
   - **Supplied Batch Coverage Only**: Coverage status (`COMPLETE`, `INCOMPLETE`, `UNCERTAIN`) is derived exclusively from supplied batch coverage declarations (`CoverageEvidence`). The UI never assumes or alters coverage status.
   - **Offline-Only External Commits**: External commit notifications (`ExternalCommitEvent`) are absent from normal live dashboard operation and are supplied strictly through explicit offline test inputs or simulated scenario streams.
2. **Engine Cursor vs. Observation Counter**:
   - `ActivationSnapshot.last_processed_sequence` advances for registration events, cancellations, coverage declarations, commits, and candle evidence. It is **not** an observation counter.
   - The UI does **not** infer "zero observations processed" from `last_processed_sequence is None`.
   - If an explicit immutable service diagnostic `exact_observation_count: Optional[int]` is supplied by the service layer, the UI displays `f"Exact Observations Processed: {count}"`; otherwise, the panel omits any unverified observation-count claim.
3. **Observation Lifecycle Cases**:
   - *Non-observation events processed*: When registrations, coverage declarations, or cancellations advance sequence without price prints, members display in initial registered states with no observation count claim.
   - *Observation processed without touch*: An exact price print outside zone bounds advances engine sequence without changing `INACTIVE_ELIGIBLE` state or establishing a first touch.
   - *Existing evidence with no new prints*: Prior pending activations and terminal records remain fully visible; absence of new prints in a refresh cycle never clears or masks established evidence.
4. **Session Reset Lifecycle**: On symbol, timeframe, data source, or recalculation changes, the service layer discards existing `ActivationEngine` and `TJLSynchronizer` instances and instantiates fresh, isolated instances. Zero cross-context state or cursor retention.

### 4.2 Architecture Safeguards & Enforceable Clauses
1. **Rendering Purity**: Pure presentation projection (`build_activation_inspection_elements()`) must **never** invoke `process_event()`, `register_source_members()`, `reset()`, or `synchronizer.sync()`.
2. **Preservation of Internal State**: Repeated rendering must preserve bit-for-bit engine checkpoints, synchronizer cursor (`last_synced_transition_index`), and synchronizer usage cache (`_usage_cache`).
3. **Bounded History Display Policy**: Visual pagination or table row limits (e.g., latest 50 rows) may be applied for DOM performance, but underlying `terminal_activations` sequence is never pruned or mutated; total historical count must remain clearly visible.
4. **Diagnostic Error Presentation**: Missing context (`activation_snapshot is None`) or invalid presentation input produces a clean diagnostic component (`"Awaiting activation context"`), never an unhandled exception or crash.
5. **Deterministic Sorting**:
   - Members/Activations: Alphabetical by `(set_id, role)`.
   - Rearm Controllers: Alphabetical by `(member_key, prior_activation_id)`.
   - Terminal History: Multi-tier sort without conflating missing with sequence zero:
     `key = (rec.cancellation_sequence_ref is not None, rec.cancellation_sequence_ref or 0, rec.cancellation_time is not None, rec.cancellation_time or min_date, rec.activation_id)` descending.

---

## 5. Acceptance Scenarios & Precise Assertion Contract

All 16 scenarios have execution status: `specified; not yet executed through the presentation implementation`.

| ID | Name | Category & Construction | Key Invariants & Assertions |
|---|---|---|---|
| `dash_act_01_eligible_untouched` | Eligible, untouched member | `engine-derived`: Register `CurrentEligibleSet` via synchronizer with zero price prints | State = `INACTIVE_ELIGIBLE`. `first_touch_time` is `None` (`"—"`). `has_first_touch_claim == False`. `is_actionable == False`. |
| `dash_act_02_first_exact_touch` | First exact touch | `engine-derived`: Feed in-zone `ExactPricePrint(OBS_01, 1.1370)` at seq 101 | State = `PENDING_ACTIVATION`. `has_first_touch_claim == True`. `first_touch_price_exact == 1.1370`. `trigger_observation_id == "OBS_01"`. `is_actionable == False`. |
| `dash_act_03_repeated_touch` | Repeated touch | `engine-derived`: Feed second print `OBS_02` in-zone | State remains `PENDING_ACTIVATION`. `first_touch_time` strictly preserved. `trigger_observation_id` remains `"OBS_01"`. Zero overwrite. `is_actionable == False`. |
| `dash_act_04_unknown_usage` | Preserved pending under usage uncertainty | `engine-derived`: Register UNUSED -> touch to PENDING -> update usage to UNKNOWN | State = `PENDING_ACTIVATION`. Preserved `first_touch_time` and `generation_seq=1`. `blocked_reason == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"`. Badge = `"UNKNOWN (FAIL-CLOSED)"`. Separate check: initially UNKNOWN member touch fails closed with 0 activations. |
| `dash_act_05_incomplete_coverage` | Incomplete and uncertain coverage | `synthetic`: Synthetic snapshot with valid domain enum `CoverageStatus.INCOMPLETE` & `UNCERTAIN` | Coverage badge = `"COVERAGE INCOMPLETE"` or `"COVERAGE UNCERTAIN"`. `coverage_status_valid_domain == True`. `is_actionable == False`. |
| `dash_act_06_unknown_availability` | Unknown availability blocks activation | `engine-derived`: Member registered with `eligibility_available_time = None` | State = `INACTIVE_INELIGIBLE`. Availability displayed as `"Unknown"`. Raw `blocked_reason == "UNKNOWN_AVAILABILITY_TIMING"`. Presentation text = `"Unknown Availability Timing"`. `inferred_time_used == False`. `is_actionable == False`. |
| `dash_act_07_source_cancellation` | Source cancellation retires member | `engine-derived`: `SourceCancellationEvent(reason=SOURCE_CHOCH, target_set_id="SET_1")` | `active_member_count == 0`. Record in terminal history. `terminal_state == "CANCELLED_SOURCE_CHOCH"`. `is_actionable == False`. |
| `dash_act_08_cancellation_unknown_time` | Cancellation unknown time | `synthetic`: Terminal record with `cancellation_time = None`, `seq = 125` | `cancellation_time_display == "Unknown"`. `sequence_ref_display == "#125"`. `timestamp_shown_as_unknown == True`. `sequence_shown_separately == True`. Zero wall-clock interpolation. `is_actionable == False`. |
| `dash_act_09_external_cancellation_inside` | External cancellation inside zone | `engine-derived`: External commit arrives with level inside zone | Terminal record = `CANCELLED_EXTERNAL_ENTRY` (gen 1). Rearm controller created with `generation_seq == 2` (next generation), `rearm_armed == False`, status = `"Awaiting Departure Outside Zone"`. Decoupled from terminal record. `is_actionable == False`. |
| `dash_act_10_armed_controller` | Armed controller | `engine-derived`: Print outside zone arms controller | Rearm controller state = `OUT_OF_ZONE_ARMED`, `generation_seq == 2`. `rearm_armed == True`. `active_activations_count == 0` (arming is not a pending activation). `is_actionable == False`. |
| `dash_act_11_valid_reactivation` | Valid reactivation generation 2 | `engine-derived`: Retouch on armed controller activates generation 2 | Active state = `REARMED_PENDING`. `generation_seq == 2`. Canonical `prior_activation_id == "ACT_G01[16:ENGINE_EURUSD_H1][2:H1][6:EURUSD][5:SET_1][4:TJL1]"`. Provenance intact. |
| `dash_act_12_successor_set_persistent_level` | Successor set, persistent level | `engine-derived`: Distinct `SET_2` registered containing same `StableLevelId` | `active_set_id == "SET_2"`. `distinct_set_identity == True`. `level_identity_continuous == True`. Zero activation inheritance from cancelled `SET_1`. `is_actionable == False`. |
| `dash_act_13_unresolved_source_snapshot` | Unresolved source snapshot | `candle-pipeline-derived`: `planned/unverified` (Pipeline prefix producing ambiguous swing points) | Canonical banner: `"LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"`. `is_unresolved == True`. `processed_bar_index == 15`, `received_bar_index == 19`. Zero fresh eligibility. `is_actionable == False`. |
| `dash_act_14_equal_coarse_timestamps` | Equal coarse timestamps | `synthetic`: Multiple records sharing timestamp `11:00 UTC` with seqs 201, 202 | `terminal_history_count == 2`. Disambiguated by canonical IDs and `distinct_sequences == [201, 202]`. Zero collapsing. `is_actionable == False`. |
| `dash_act_15_multiple_source_timeframes` | Multiple source timeframes | `engine-derived`: H4 engine context (`confirmation_timeframe="M5"`) | Context header shows `H4 -> M5`. Disclaimer: metadata mapping only. `cross_timeframe_arbitration == False`. `is_actionable == False`. |
| `dash_act_16_repeated_rendering` | Repeated rendering invariance | `engine-derived`: Consecutive calls to pure projection function | `render_invariant == True`. `component_tree_hash_identical == True`. `engine_state_unmutated == True`. `synchronizer_cursor_unmutated == True`. `is_actionable == False`. |

---

## 6. Integration-Gap Assessment & Interface Audit

1. **Inspected Paths**: `tjl_inspection.py` (430 lines), `msm_callbacks.py` (1770 lines), `layout.py`, `service.py` (680 lines), `activation_types.py` (335 lines), `activation_adapter.py` (258 lines).
2. **Public Dataclass Completeness**:
   - `ActivationSnapshot`, `ActivationRecord`, `RearmController`, `TJLSnapshot`, and `TJLSynchronizer` collectively supply all fields required for all 8 display groups and all 16 scenarios.
   - Event-level target metadata (`target_set_id`, `affected_direction`) from incoming events is not stored on `ActivationRecord`. The presentation contract displays the record's own immutable `set_id` and `role` without event-target reconstruction.
   - Unresolved diagnostics and bar indexing are sourced directly from `TJLSnapshot` and `MSMServiceResult`.
   - `TJLSynchronizer.last_synced_transition_index` can be passed to the pure projection function as an optional parameter.
3. **Proposed UI Module**:
   - In implementation phase, introduce `src/aladeen/ui/activation_inspection.py` housing `build_activation_inspection_elements()`. Zero private dictionary exposure or engine mutations.
