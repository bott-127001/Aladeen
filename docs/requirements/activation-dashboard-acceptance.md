# Activation Read-Only Dashboard Integration — Requirements & Acceptance Specification

**Milestone**: Requirements & Acceptance Contract for Read-Only Activation Dashboard Integration (HANDOFF-063)  
**Accepted Engine Baseline**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)  
**Branch**: `requirements/activation-dashboard-acceptance`  
**Status**: Requirements & Acceptance Specification Phase (Zero runtime changes)  

---

## 1. Executive Summary, Bounded Scope & Explicit Exclusions

### 1.1 Purpose
The purpose of this milestone is to define the rigorous presentation contract, UI evidence mapping, data ownership rules, offline evidence boundary, and deterministic acceptance scenarios for displaying pure offline activation lifecycle evidence within the existing Aladeen / TopG read-only dashboard.

This requirements phase establishes how the dashboard will render activation lifecycle states, evidence gating, rearm controllers, and historical outcomes without altering domain calculation semantics, consuming uncommitted events, synthesizing unverified prints, or making trade/execution decisions.

### 1.2 Bounded Scope
1. **Pure Presentation Projection**: Specify a pure mathematical/functional projection from immutable domain snapshots (`ActivationSnapshot`, `TJLSnapshot`) to dashboard UI components (inspection cards, status badges, structured tables).
2. **Explicit Observation Audit**: Visualize which exact price prints triggered an activation, which authoritative events cancelled it, and which rearm controllers manage outside departure.
3. **Exact-Observation Semantics**:
   - **Exact observed price evidence** (`ExactPricePrint`) alone establishes an activation touch.
   - OHLC candle overlap, interpolated price paths, or candle intervals alone **cannot** establish a touch.
   - A candle interval's ordering flag does not manufacture an independent exact price observation.
4. **Evidence Gating Transparency**: Render usage evidence uncertainty (`UNKNOWN`), coverage status (`COMPLETE`, `INCOMPLETE`, `UNCERTAIN`), and fail-closed blocked reasons (`USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`, `BLOCKED_UNKNOWN_ORDER`) prominently and unambiguously.
5. **Retained Synchronizer Ownership**: Establish clear service-layer ownership of `TJLSynchronizer`. Rendering must never instantiate transient synchronizers or mutate state.
6. **Deterministic Presentation**: Define consistent sorting, pagination, and formatting rules ensuring repeated renders yield bit-for-bit identical component trees.

### 1.3 Strict Exclusions
No work in this milestone or the downstream dashboard integration may implement, suggest, or imply:
1. **No Order Execution or Automated Trading**: Strictly zero order placement, zero order modification, zero position tracking, zero MT5 trading API calls, and zero broker interaction.
2. **No Confirmation Detection or Selection**: Confirmation timeframes (e.g., M1 for H1 source) are displayed solely as static metadata from the authoritative timeframe mapping table (`TIMEFRAME_CONFIRMATION_MAP`); this contract does **not** authorize a confirmation detection or arbitration engine.
3. **No Cross-Timeframe Arbitration or Winner Selection**: No multi-timeframe ranking, priority arbitration, or winner scoring across competing levels.
4. **No Usage-Ledger Mutations or Lifetime Commit Writes**: No persistent usage ledger, no write-back of zone consumption, and no inferred lifetime usage tracking.
5. **No Trade Entry Signals or Execution Advice**: Activations are lifecycle observations of physical price-zone interactions; they are explicitly not trade entry signals, trading alerts, or execution approvals.
6. **No Live MT5 Terminal Credentials**: Never request, store, print, log, or commit MT5 passwords, server credentials, or account balances.
7. **No Resolution of Core Ambiguities**: Upstream $c_1 == p_2$ boundary ambiguity and ISS multi-candle pullbacks remain isolated and unresolved.
8. **No Merge into `main`**: All work remains strictly isolated on dedicated feature/requirements branches.

---

## 2. Non-Negotiable Presentation Semantics & Terminology

### 2.1 Pending Does Not Mean Actionable
A `PENDING_ACTIVATION` state indicates solely that an exact price print touched the physical boundary of an eligible source member on or after its eligibility availability time.
- It is **not** an approved trade, an entry signal, or an executable setup.
- The UI must prominently display non-execution disclaimers: `"LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL"`.
- If usage evidence is `UNKNOWN` or coverage is `INCOMPLETE` / `UNCERTAIN`, the UI must display a blocked badge (`"EVIDENCE UNCERTAIN (BLOCKED)"`) prohibiting any interpretation of actionability.

### 2.2 Distinguishing Registered Members from Evidence-Eligible Members
- **Registered Member**: A source level currently tracked in `ActivationSnapshot.current_members`.
- **Evidence-Eligible Member**: A registered member whose lifecycle state is `INACTIVE_ELIGIBLE`, whose `eligibility_available_time` is known and satisfied, and whose `usage_evidence_status` is verified `UNUSED`.
- A member may be registered but **ineligible** (state `INACTIVE_INELIGIBLE`) if its availability time is unknown, if it is gated by uncertain usage, or if its source epoch has not yet begun.

### 2.3 History Is Not Current Eligibility
- **Terminal Outcomes**: An activation in `CANCELLED_SOURCE_CHOCH`, `CANCELLED_SOURCE_REPLACEMENT`, or `CANCELLED_EXTERNAL_ENTRY` is an immutable historical record. It must be rendered in a separate **Terminal Activation History** table, visually decoupled from current eligible members.
- **Rearm Controllers**: An out-of-zone rearm controller (`RearmController`) managing departure is a decoupled state machine awaiting departure or retouch. It is **not** an activation and must not be rendered as current active eligibility. Its associated membership may still exist in `current_members` until cancelled by a source event.
- **Retired Outgoing Memberships**: When a source set is cancelled, its set identity and member keys are permanently retired within the run. Outgoing members must be immediately removed from the active membership view.
- **Successor Set Provenance**: A successor set (`SET_2`) containing an identical physical level (`StableLevelId`) must display its distinct successor set ID, with continuous physical level attribution clearly noted in the level metadata.

### 2.4 Unknown Stays Unknown
- Missing or indeterminate evidence must be rendered explicitly as `"Unknown"`, `"—"`, or `"None"`.
- The presentation layer must **never** substitute wall-clock timestamps, prior candle close times, interpolated touch times, or fabricated ordering for missing evidence.
- If a cancellation transition has an unknown timestamp (`timestamp is None`), the UI must explicitly display `"Unknown"` in the timestamp column, and display the causal sequence separately in its own column (e.g. `"#125"`). Conflicting combined representations (such as `"Unknown (Sequence Ref: #125)"` in the timestamp column) are strictly prohibited.

### 2.5 Unresolved Source Evidence Remains Visible
- If the upstream source snapshot is unresolved (`is_unresolved == True`), the UI must render the canonical amber warning banner:
  `"LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"`
- The display must clearly differentiate between the **Authoritative Processed Bar** (`last_processed_index`) and the **Latest Received Input Bar** (`last_received_index`), both sourced from `TJLSnapshot`.
- Finalized cancellations already consumed by the synchronizer must remain visible in terminal history, but frozen source data must never imply fresh eligibility.

---

## 3. Public Field Input & Provenance Matrix

The table below provides a field-by-field audit of every UI attribute rendered across the 8 display groups, specifying its public source object, attribute, availability, missing-value presentation, and join requirements:

| Group | UI Display Field | Source Object | Exact Public Attribute | Availability | Missing-Value Representation | Join / Authoritative Key |
|---|---|---|---|---|---|---|
| **G1 Context** | Engine ID | `ActivationSnapshot` | `.engine_id` | Always available | `"None"` | Direct from snapshot |
| **G1 Context** | Symbol / Feed ID | `ActivationSnapshot` | `.symbol` | Always available | `"None"` | Direct from snapshot |
| **G1 Context** | Source Timeframe | `ActivationSnapshot` | `.source_timeframe` | Always available | `"None"` | Direct from snapshot |
| **G1 Context** | Mapped Confirmation TF | `ActivationSnapshot` | `.confirmation_timeframe` | Always available | `"None"` | Direct from snapshot (metadata mapping) |
| **G1 Context** | Sequence Domain | `ActivationSnapshot` | `.sequence_domain.domain_id` | Always available | `"None"` | Direct from snapshot |
| **G2 Membership** | Set ID | `SourceMemberReference` | `.set_id` | Always available | `"None"` | Keyed by `member_key` in `current_members` |
| **G2 Membership** | Role | `SourceMemberReference` | `.role` | Always available | `"None"` | Keyed by `member_key` in `current_members` |
| **G2 Membership** | Stable Level ID | `SourceMemberReference` | `.level_id` | Optional | `"—"` | Direct attribute on member reference |
| **G2 Membership** | Physical Level Side | `SourceMemberReference` | `.side` | Always available | `"None"` | Direct attribute on member reference |
| **G2 Membership** | Lower Edge Price | `SourceMemberReference` | `.lower_edge` | Always available | `"0.0"` | Formatted float `f"{val:.5f}"` |
| **G2 Membership** | Upper Edge Price | `SourceMemberReference` | `.upper_edge` | Always available | `"0.0"` | Formatted float `f"{val:.5f}"` |
| **G2 Membership** | Thickness-0 Line Flag | `SourceMemberReference` | `.is_line` | Always available | `"False"` | Direct boolean |
| **G2 Membership** | Available Time | `SourceMemberReference` | `.eligibility_available_time` | Optional | `"Unknown"` | Formatted ISO UTC or `"Unknown"` |
| **G3 Activation** | Activation ID | `ActivationRecord` | `.activation_id` | Always available | `"None"` | Keyed by `member_key` in `active_activations` |
| **G3 Activation** | Lifecycle State | `ActivationRecord` | `.state.value` | Always available | `"None"` | Covers all states: `INACTIVE_ELIGIBLE`, `INACTIVE_INELIGIBLE`, `PENDING_ACTIVATION`, `REARMED_PENDING`, `BLOCKED_UNKNOWN_ORDER` |
| **G3 Activation** | Generation Sequence | `ActivationRecord` | `.generation_seq` | Always available | `"0"` | Integer `generation_seq` |
| **G3 Activation** | First Touch Time | `ActivationRecord` | `.first_touch_time` | Optional | `"—"` | Formatted ISO UTC if present, else `"—"` |
| **G3 Activation** | First Touch Price | `ActivationRecord` | `.first_touch_price` | Optional | `"—"` | Formatted float `f"{val:.5f}"` if present, else `"—"` |
| **G3 Activation** | Trigger Observation ID | `ActivationRecord` | `.trigger_observation_id` | Optional | `"—"` | String ID if present, else `"—"` |
| **G3 Activation** | Prior Activation ID | `ActivationRecord` | `.prior_activation_id` | Optional | `"—"` | Links reactivated generation to prior record |
| **G4 Gating** | Usage Evidence Status | `ActivationRecord` | `.usage_evidence_status.value` | Always available | `"UNKNOWN"` | Enum: `UNUSED`, `USED`, `UNKNOWN` |
| **G4 Gating** | Coverage Status | `ActivationSnapshot` | `.coverage_status.value` | Always available | `"UNKNOWN"` | Enum: `COMPLETE`, `INCOMPLETE`, `UNCERTAIN` |
| **G4 Gating** | Blocked Reason | `ActivationRecord` | `.blocked_reason` | Optional | `"—"` | String reason if blocked, else `"—"` |
| **G5 Cancellation** | Cancellation Reason | `ActivationRecord` | `.cancellation_reason.value` | Optional | `"—"` | Sourced from terminal `ActivationRecord` |
| **G5 Cancellation** | Cancellation Time | `ActivationRecord` | `.cancellation_time` | Optional | `"Unknown"` | Dedicated Timestamp Column: Formatted UTC or `"Unknown"` |
| **G5 Cancellation** | Cancellation Sequence | `ActivationRecord` | `.cancellation_sequence_ref` | Optional | `"—"` | Dedicated Sequence Column: `f"#{val}"` or `"—"` |
| **G5 Cancellation** | Cancelled Set ID | `ActivationRecord` | `.set_id` | Always available | `"None"` | The record's own `set_id` (original event target metadata is not stored on record and is not fabricated) |
| **G5 Cancellation** | Cancelled Role | `ActivationRecord` | `.role` | Always available | `"None"` | The record's own `role` |
| **G6 Rearm Controller**| Controller Key | `RearmController` | `.member_key` | Always available | `"None"` | Keyed by `member_key` in `rearm_controllers` |
| **G6 Rearm Controller**| Prior Activation ID | `RearmController` | `.prior_activation_id` | Always available | `"None"` | Authoritative link to terminal activation |
| **G6 Rearm Controller**| Controller State | `RearmController` | `.state.value` | Always available | `"None"` | `CANCELLED_EXTERNAL_ENTRY` or `OUT_OF_ZONE_ARMED` |
| **G6 Rearm Controller**| Rearm Armed Flag | `RearmController` | `.rearm_armed` | Always available | `"False"` | True if outside departure observed |
| **G6 Rearm Controller**| Last Observed Pos | `RearmController` | `.last_observed_position` | Optional | `"Unknown"` | `"INSIDE"` or `"OUTSIDE"` |
| **G7 History** | Terminal Activations | `ActivationSnapshot` | `.terminal_activations` | Always available | `[]` | Immutable sequence of terminal `ActivationRecord`s |
| **G8 Synchronization** | Engine Last Seq | `ActivationSnapshot` | `.last_processed_sequence` | Optional | `"—"` | Engine sequence cursor |
| **G8 Synchronization** | Engine Last Time | `ActivationSnapshot` | `.last_processed_timestamp` | Optional | `"—"` | Engine timestamp cursor |
| **G8 Synchronization** | Synced Trans Index | `TJLSynchronizer` | `.last_synced_transition_index` | Optional | `"—"` | Sourced from synchronizer (not snapshot) |
| **G8 Synchronization** | Source Unresolved | `TJLSnapshot` | `.is_unresolved` | Always available | `"False"` | Sourced from `TJLSnapshot` / `MSMServiceResult` |
| **G8 Synchronization** | Unresolved Diag | `TJLSnapshot` | `.unresolved_diagnostic` | Optional | `"—"` | Sourced from `TJLSnapshot` / `MSMServiceResult` |
| **G8 Synchronization** | Processed Bar Index | `TJLSnapshot` | `.last_processed_index` | Always available | `"-1"` | Authoritative bar from `TJLSnapshot` |
| **G8 Synchronization** | Received Bar Index | `TJLSnapshot` | `.last_received_index` | Always available | `"-1"` | Latest received bar from `TJLSnapshot` |

---

## 4. Offline Service Evidence Boundary & Context Lifecycle

### 4.1 Offline Service Evidence Boundary
In this read-only dashboard milestone, the dashboard operates strictly within the offline application service boundary:
1. **Source Members & Transitions**: Provided directly to `TJLSynchronizer.sync()` from the accepted `TJLSnapshot` produced by `TJLCoordinator` during the current candle run.
2. **Exact Price Prints**: Sourced exclusively from validated offline `ExactPricePrint` sequence streams. In the absence of an exact intraday observation stream, current members remain in `INACTIVE_ELIGIBLE` (or `INACTIVE_INELIGIBLE` if availability is pending). Candle highs, lows, or closes are **never** synthesized or promoted into fabricated prints.
3. **Usage Evidence**: Strictly defaults to `UsageEvidenceStatus.UNKNOWN` unless supplied by an explicit offline test fixture or authoritative input.
4. **Coverage Declarations**: Initialized from market batch evidence (`COMPLETE`, `INCOMPLETE`, or `UNCERTAIN`).
5. **External Finalized Commits**: Zero external commit injection in normal dashboard operations. Only processed when supplied by explicit offline test fixtures.
6. **Empty / Inactive Context Fallback**: If no activation snapshot or exact observations are supplied, the panel displays a clean placeholder: `"AWAITING EXACT OBSERVATIONS — NO PRINTS PROCESSED"`.

### 4.2 Session Isolation & Reset Lifecycle
To guarantee strict state isolation across dashboard operations:
- When the user changes symbol, timeframe, data source, or triggers a recalculation:
  - The service layer **discards** any existing `ActivationEngine` and `TJLSynchronizer` instances.
  - A fresh, isolated `ActivationEngine` is instantiated with the new context parameters `(engine_id, symbol, source_timeframe)`.
  - A fresh, isolated `TJLSynchronizer` is bound to the new engine.
  - Cross-context state retention, shared cache leakage, or retained transition cursors across symbol/timeframe switches are strictly prohibited.

### 4.3 Pure Presentation Projection
The dashboard presentation layer must be implemented as a pure function:
```python
def build_activation_inspection_elements(
    activation_snapshot: Optional[ActivationSnapshot],
    tjl_snapshot: Optional[TJLSnapshot] = None,
    last_synced_transition_index: Optional[int] = None,
) -> list[html.Div]:
    ...
```
- **Zero Reducer Side Effects**: The projection function must never call `engine.process_event()`, `engine.register_source_member()`, `engine.reset()`, or `synchronizer.sync()`.
- **Zero Cursor Side Effects**: The projection function must never advance synchronizer cursors or consume unread transitions.
- **Snapshot Immutability**: All inputs to the projection function are frozen/immutable dataclasses.

### 4.4 Deterministic Sorting
To guarantee deterministic offline testing and stable DOM rendering, collections must be sorted predictably:
1. **Current Members**: Sorted alphabetically by `(set_id, role)`.
2. **Active Activations**: Sorted alphabetically by `(set_id, role)`.
3. **Rearm Controllers**: Sorted alphabetically by `(member_key, prior_activation_id)`.
4. **Terminal History**: Deterministic multi-tier sort without conflating missing values with valid sequence zero:
   `key = (rec.cancellation_sequence_ref is not None, rec.cancellation_sequence_ref or 0, rec.cancellation_time is not None, rec.cancellation_time or min_date, rec.activation_id)` descending.

---

## 5. Acceptance Scenarios & Precise Assertion Contract

The acceptance suite specifies 16 deterministic scenarios. For each scenario, we define:
- **Planned Evidence Category**: Strictly one of `synthetic`, `engine-derived`, `candle-pipeline-derived`.
- **Construction Procedure**: The exact mechanism used to generate the scenario inputs.
- **Actual Execution Status**: `"specified; not yet executed through the presentation implementation"`.
- **Expected View & Assertions**: Precise display attributes and testable assertions.

### Scenario 1: Eligible, Untouched Member (`dash_act_01_eligible_untouched`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by registering `CurrentEligibleSet` through `TJLSynchronizer` with zero price prints.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Active set `SET_1` with `TJL1` (upper: 1.1400, lower: 1.1350, available: `2026-10-02 08:00 UTC`). Zero touch events.
- **Expected View**: State = `INACTIVE_ELIGIBLE`. Zone bounds and availability time displayed cleanly.
- **Assertions**: `first_touch_time` is `None` (rendered as `"—"`), `trigger_observation_id` is `None`, `is_actionable == False`, no first-touch claim in DOM.

### Scenario 2: First Exact Touch (`dash_act_02_first_exact_touch`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by feeding `ExactPricePrint` inside zone bounds to `ActivationEngine` at sequence 101.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: `SET_1/TJL1` receives `ExactPricePrint(OBS_01, price=1.1370, time=2026-10-02 08:15 UTC)`.
- **Expected View**: State = `PENDING_ACTIVATION`. Badge = `"PENDING ACTIVATION (GEN 1)"`.
- **Assertions**: `first_touch_time == "2026-10-02 08:15:00 UTC"`, `first_touch_price == 1.1370`, `trigger_observation_id == "OBS_01"`, `is_actionable == False` (non-execution disclaimer rendered).

### Scenario 3: Repeated Touch (`dash_act_03_repeated_touch`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by feeding multiple consecutive in-zone `ExactPricePrint`s to `ActivationEngine`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Following Scenario 2, second print `ExactPricePrint(OBS_02, price=1.1380, time=2026-10-02 08:20 UTC)` arrives.
- **Expected View**: State remains `PENDING_ACTIVATION`.
- **Assertions**: `first_touch_time` remains strictly `"2026-10-02 08:15:00 UTC"`, `first_touch_price` remains `1.1370`, `trigger_observation_id` remains `"OBS_01"`. Zero overwrite from `OBS_02`.

### Scenario 4: Unknown Usage Evidence (`dash_act_04_unknown_usage`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by registering member with `UsageEvidenceStatus.UNKNOWN` followed by in-zone price print.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: `SET_1/TJL1` active with `usage_evidence_status = UNKNOWN`.
- **Expected View**: State = `PENDING_ACTIVATION`, but Gating Badge = `"UNKNOWN (FAIL-CLOSED)"`. Blocked Reason = `"USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"`.
- **Assertions**: Gating status prominently rendered in amber/red; styling strictly prohibits active/executable appearance; `is_actionable == False`.

### Scenario 5: Incomplete and Uncertain Coverage (`dash_act_05_incomplete_coverage`)
- **Planned Category**: `synthetic`
- **Construction Procedure**: Synthetic `ActivationSnapshot` instances with valid domain enum values `CoverageStatus.INCOMPLETE` and `CoverageStatus.UNCERTAIN`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Activation engine coverage set to `CoverageStatus.INCOMPLETE` and `CoverageStatus.UNCERTAIN`.
- **Expected View**: Coverage Badge = `"COVERAGE INCOMPLETE"` or `"COVERAGE UNCERTAIN"`.
- **Assertions**: Coverage warning rendered independently of member state. Disclaimers note data gap. `is_actionable == False`.

### Scenario 6: Unknown Availability Time (`dash_act_06_unknown_availability`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by registering member reference with `eligibility_available_time = None`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Member registered with `eligibility_available_time = None`.
- **Expected View**: State = `INACTIVE_INELIGIBLE`. Availability column displays `"Unknown"`. Blocked Reason = `"MISSING_AVAILABILITY_EVIDENCE"`.
- **Assertions**: Zero inferred activation time, zero default to current time. `is_actionable == False`.

### Scenario 7: Source Cancellation (`dash_act_07_source_cancellation`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by processing `SourceCancellationEvent(reason=SOURCE_CHOCH, target_set_id="SET_1")` on `ActivationEngine`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Active `SET_1/TJL1` cancelled via `SourceCancellationEvent`.
- **Expected View**: `SET_1` completely absent from Active Set Members table. Record appears in Terminal History with state `CANCELLED_SOURCE_CHOCH`.
- **Assertions**: Active member count = 0; Terminal history count = 1; `cancellation_reason == "SOURCE_CHOCH"`. `is_actionable == False`.

### Scenario 8: Cancellation with Unknown Timestamp (`dash_act_08_cancellation_unknown_time`)
- **Planned Category**: `synthetic`
- **Construction Procedure**: Synthetic terminal `ActivationRecord` with `cancellation_time = None` and `cancellation_sequence_ref = 125`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Cancellation event with `timestamp = None`, `sequence_ref = 125`.
- **Expected View**: Dedicated Timestamp Column shows `"Unknown"`. Dedicated Sequence Column shows `"#125"`.
- **Assertions**: Timestamp rendered as `"Unknown"`; sequence displayed in separate dedicated column; zero wall-clock interpolation. `is_actionable == False`.

### Scenario 9: External Cancellation While Inside Zone (`dash_act_09_external_cancellation_inside`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by `process_external_commit_event()` while `last_observed_position == "INSIDE"`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Level inside zone when external commit arrives.
- **Expected View**: Terminal record shows `CANCELLED_EXTERNAL_ENTRY`. Rearm Controllers table shows active controller with `state="CANCELLED_EXTERNAL_ENTRY"`, `rearm_armed=False`, `status="Awaiting Departure Outside Zone"`.
- **Assertions**: Controller cleanly decoupled from terminal record; controller explicitly indicates departure required before rearming. `is_actionable == False`.

### Scenario 10: Armed Controller (`dash_act_10_armed_controller`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by feeding out-of-zone print following Scenario 9.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Price print outside zone transitions controller to `OUT_OF_ZONE_ARMED` (`rearm_armed=True`).
- **Expected View**: Rearm Controllers table shows `state="OUT_OF_ZONE_ARMED"`, `rearm_armed=True`, Badge = `"ARMED FOR RETOUCH"`.
- **Assertions**: Controller displayed as armed; Active Activations table shows 0 pending activations (arming is not an activation). `is_actionable == False`.

### Scenario 11: Valid Reactivation (`dash_act_11_valid_reactivation`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by feeding retouch print on armed controller into `ActivationEngine`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Following Scenario 10, new print inside zone activates generation 2 (`REARMED_PENDING`).
- **Expected View**: Active Activations table shows `activation_id="..._gen2"`, `generation_seq=2`, `prior_activation_id="..._gen1"`, State = `REARMED_PENDING`. Terminal table retains generation 1 record.
- **Assertions**: Generation 2 linked to Generation 1; Generation 1 immutable in terminal history; provenance chain unbroken. `is_actionable == False`.

### Scenario 12: Successor Set with Persistent Physical Level (`dash_act_12_successor_set_persistent_level`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by cancelling `SET_1` followed by registering distinct successor set `SET_2` with same `StableLevelId`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: `SET_1` cancelled. Distinct successor set `SET_2` registered containing the exact same `StableLevelId`.
- **Expected View**: Active Set Members shows `SET_2/TJL1`. Level ID matches historical `SET_1` level ID. State = `INACTIVE_ELIGIBLE (GEN 0)`.
- **Assertions**: Set identity strictly `SET_2`; physical level attribution matches; zero activation inheritance from cancelled `SET_1`. `is_actionable == False`.

### Scenario 13: Unresolved Source Snapshot (`dash_act_13_unresolved_source_snapshot`)
- **Planned Category**: `candle-pipeline-derived`
- **Construction Procedure**: Generated by executing `TJLCoordinator` on ambiguous GBPUSD candle sequence (`test_authentic_candle_sequence_produces_genuine_tracking_only` pipeline prefix), yielding `is_unresolved=True`, `last_processed_index=15`, `last_received_index=19`.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Source `TJLSnapshot` with `is_unresolved=True`, `last_processed_index=15`, `last_received_index=19`, `unresolved_diagnostic="Simultaneous c1==p2 touch at bar #15"`.
- **Expected View**: Canonical banner: `"LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"`. Diagnostic shows `"Simultaneous c1==p2 touch at bar #15"`, `"Processed Bar: #15"`, `"Received Bar: #19"`.
- **Assertions**: Frozen authoritative bar distinguished from received bar; no fresh eligibility created. `is_actionable == False`.

### Scenario 14: Equal Coarse Timestamps (`dash_act_14_equal_coarse_timestamps`)
- **Planned Category**: `synthetic`
- **Construction Procedure**: Synthetic terminal records sharing identical coarse timestamp `11:00 UTC` with distinct sequence refs 201 and 202.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Multiple events sharing identical coarse timestamp `2026-10-02 11:00:00 UTC` but distinct sequences `seq=201`, `seq=202`.
- **Expected View**: Both records displayed distinctly, disambiguated by canonical activation IDs and sequence references.
- **Assertions**: Zero collapsing or key collisions; sorting strictly preserves sequence ordering. `is_actionable == False`.

### Scenario 15: Multiple Source Timeframes (`dash_act_15_multiple_source_timeframes`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Generated by configuring `ActivationEngine` with H4 source timeframe (`confirmation_timeframe="M5"`).
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: H1 engine (`confirmation_timeframe="M1"`) and H4 engine (`confirmation_timeframe="M5"`) inspected.
- **Expected View**: Context header reflects exact engine timeframe and mapped confirmation timeframe.
- **Assertions**: Exact 1:1 mapping verified (`H1 -> M1`, `H4 -> M5`, `D1 -> H1`); zero cross-timeframe arbitration or winner ranking. `is_actionable == False`.

### Scenario 16: Repeated Rendering Invariance (`dash_act_16_repeated_rendering`)
- **Planned Category**: `engine-derived`
- **Construction Procedure**: Calling pure projection function `build_activation_inspection_elements()` multiple times consecutively on identical snapshot.
- **Execution Status**: `specified; not yet executed through the presentation implementation`
- **Presentation Inputs**: Call projection function 5 times consecutively on the same snapshot.
- **Expected View**: All 5 outputs yield bit-for-bit identical component trees.
- **Assertions**: `render_invariant == True`, `component_tree_hash_identical == True`, `engine_state_unmutated == True`, `synchronizer_cursor_unmutated == True`. `is_actionable == False`.

---

## 6. Integration-Gap Assessment & Interface Audit

### 6.1 Repository Paths Inspected
1. `src/aladeen/ui/tjl_inspection.py` (430 lines): Current TJL read-only inspection builder. Provides cards, tables, and transition audits.
2. `src/aladeen/ui/msm_callbacks.py` (1770 lines): Central Dash callbacks orchestrating UI updates. Coordinates candidate envelopes and inspection panel updates.
3. `src/aladeen/ui/layout.py`: Core dashboard layout containing tab containers and inspection panel layout (`#tjl-inspection-container`, `#msm-inspection-container`).
4. `src/aladeen/strategy/service.py` (680 lines): Application service layer returning `MSMServiceResult`.
5. `src/aladeen/strategy/activation_types.py` (335 lines): Data contract defining `ActivationSnapshot`, `ActivationRecord`, `RearmController`, `CoverageStatus`.
6. `src/aladeen/strategy/activation_adapter.py` (258 lines): `TJLSynchronizer` and adapter helpers.

### 6.2 Proposed Observational Interface Additions
Based on the field-level audit in Section 3:
1. **Public Dataclass Completeness**:
   - `ActivationSnapshot`, `ActivationRecord`, `RearmController`, and `TJLSnapshot` collectively supply all fields required for all 8 display groups and all 16 scenarios.
   - Event-level target metadata (`target_set_id`, `affected_direction`) from incoming `SourceCancellationEvent` or `ExternalCommitEvent` is **not** retained on `ActivationRecord`. Rather than inventing new fields or reconstructing targets, the presentation contract displays the record's own immutable `set_id` and `role`.
   - Diagnostics for unresolved states and bar indexing are sourced directly from `TJLSnapshot` and `MSMServiceResult`.
   - `TJLSynchronizer.last_synced_transition_index` can be passed to the pure projection function as an optional parameter.
2. **Proposed UI Module**:
   - In the implementation phase, introduce `src/aladeen/ui/activation_inspection.py` housing `build_activation_inspection_elements()`.
   - Zero private dictionary exposure or engine mutations.

---

## 7. Review and Acceptance Criteria

For HANDOFF-063 acceptance:
1. Complete requirements specification in `docs/requirements/activation-dashboard-acceptance.md` addressing all 5 review directives.
2. Standardized acceptance fixtures in `tests/fixtures/activation_dashboard_acceptance.json` enforcing corrected domain vocabulary (`CoverageStatus.INCOMPLETE`, `CoverageStatus.UNCERTAIN`), canonical banner strings, separate timestamp/sequence columns, and execution status labels.
3. Automated fixture integrity test in `tests/test_activation_dashboard_fixture_integrity.py` passing cleanly offline.
4. Full offline repository test suite passing.
5. Zero runtime code modifications in this phase.
