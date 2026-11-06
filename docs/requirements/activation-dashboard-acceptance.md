# Activation Read-Only Dashboard Integration — Requirements & Acceptance Specification

**Milestone**: Requirements & Acceptance Contract for Read-Only Activation Dashboard Integration (HANDOFF-062)  
**Accepted Engine Baseline**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)  
**Branch**: `requirements/activation-dashboard-acceptance`  
**Status**: Requirements & Acceptance Specification Phase (Zero runtime changes)  

---

## 1. Executive Summary, Bounded Scope & Explicit Exclusions

### 1.1 Purpose
The purpose of this milestone is to define the rigorous presentation contract, UI evidence mapping, data ownership rules, and deterministic acceptance scenarios for displaying pure offline activation lifecycle evidence within the existing Aladeen / TopG read-only dashboard.

This requirements phase establishes how the dashboard will render activation lifecycle states, evidence gating, rearm controllers, and historical outcomes without altering domain calculation semantics, consuming uncommitted events, or making trade/execution decisions.

### 1.2 Bounded Scope
1. **Pure Presentation Projection**: Specify a pure mathematical/functional projection from immutable domain snapshots (`ActivationSnapshot`, `TJLSnapshot`) to dashboard UI components (inspection cards, status badges, structured tables).
2. **Explicit Observation Audit**: Visualize which exact price prints or candle intervals triggered an activation, which authoritative events cancelled it, and which rearm controllers manage departure.
3. **Evidence Gating Transparency**: Render usage evidence uncertainty (`UNKNOWN`), coverage status (`PARTIAL`, `UNKNOWN`), and fail-closed blocked reasons (`USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`) prominently and unambiguously.
4. **Retained Synchronizer Ownership**: Establish clear service-layer ownership of `TJLSynchronizer`. Rendering must never instantiate transient synchronizers or mutate state.
5. **Deterministic Presentation**: Define consistent sorting, pagination, and formatting rules ensuring repeated renders yield bit-for-bit identical UI trees.

### 1.3 Strict Exclusions
No work in this milestone or the downstream dashboard integration may implement, suggest, or imply:
1. **No Order Execution or Automated Trading**: Strictly zero order placement, zero order modification, zero position tracking, zero MT5 trading API calls, and zero broker interaction.
2. **No Confirmation Detection or Selection**: Confirmation timeframes (e.g., M1 for H1 source) are displayed solely as static metadata from the authoritative timeframe mapping table; this contract does **not** authorize a confirmation detection or arbitration engine.
3. **No Cross-Timeframe Arbitration or Winner Selection**: No multi-timeframe ranking, priority arbitration, or winner scoring across competing levels.
4. **No Usage-Ledger Mutations or Lifetime Commit Writes**: No persistent usage ledger, no write-back of zone consumption, and no inferred lifetime usage tracking.
5. **No Trade Entry Signals or Execution Advice**: Activations are lifecycle observations of physical price-zone interactions; they are explicitly not trade entry signals, trading alerts, or execution approvals.
6. **No Live MT5 Terminal Credentials**: Never request, store, print, log, or commit MT5 passwords, server credentials, or account balances.
7. **No Resolution of Core Ambiguities**: Upstream $c_1 == p_2$ boundary ambiguity and ISS multi-candle pullbacks remain isolated and unresolved.
8. **No Merge into `main`**: All work remains strictly isolated on dedicated feature/requirements branches.

---

## 2. Non-Negotiable Presentation Semantics & Terminology

### 2.1 Pending Does Not Mean Actionable
A `PENDING_ACTIVATION` state indicates solely that an exact price print or verified candle interval touched the physical boundary of an eligible source member on or after its eligibility availability time.
- It is **not** an approved trade, an entry signal, or an executable setup.
- The UI must prominently display non-execution disclaimers: `"LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL"`.
- If usage evidence is `UNKNOWN` or coverage is `PARTIAL`, the UI must display a blocked badge (`"EVIDENCE UNCERTAIN (BLOCKED)"`) prohibiting any interpretation of actionability.

### 2.2 History Is Not Current Eligibility
- **Terminal Outcomes**: An activation in `CANCELLED_SOURCE_CHOCH`, `CANCELLED_SOURCE_REPLACEMENT`, or `CANCELLED_EXTERNAL_ENTRY` is an immutable historical record. It must be rendered in a separate **Terminal Activation History** table, visually decoupled from current eligible members.
- **Rearm Controllers**: An out-of-zone rearm controller (`RearmController`) managing departure is a decoupled state machine awaiting departure or retouch. It is **not** a pending activation and must not be rendered as current active eligibility.
- **Retired Outgoing Memberships**: When a source set is cancelled, its set identity and member keys are permanently retired within the run. Outgoing members must be immediately removed from the active membership view.
- **Successor Set Provenance**: A successor set (`SET_2`) containing an identical physical level (`StableLevelId`) must display its distinct successor set ID, with continuous physical level attribution clearly noted in the level metadata.

### 2.3 Unknown Stays Unknown
- Missing or indeterminate evidence must be rendered explicitly as `"UNKNOWN"`, `"—"`, or `"None"`.
- The presentation layer must **never** substitute wall-clock timestamps, prior candle close times, interpolated touch times, or fabricated ordering for missing evidence.
- If a cancellation transition has an unknown timestamp (`timestamp is None`), the UI must explicitly display `"Unknown (Sequence Ref: #<seq>)"` rather than fabricating a time.
- Causal sequence references (`sequence_ref`) must be presented in their own dedicated column, distinct from physical timestamps.

### 2.4 Unresolved Source Evidence Remains Visible
- If the upstream source snapshot is unresolved (`is_unresolved == True`), the UI must render an amber warning banner: `"LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"`.
- The display must clearly differentiate between the **Authoritative Processed Bar** (`last_processed_index`) and the **Latest Received Input Bar** (`last_received_index`).
- Finalized cancellations already consumed by the synchronizer must remain visible in terminal history, but frozen source data must never imply fresh eligibility.

---

## 3. Required Display Groups & Data Mappings

The activation dashboard presentation is partitioned into eight functional display groups:

| # | Display Group | Required Observable Fields | UI Component & Presentation Rules |
|---|---|---|---|
| **G1** | **Context** | `engine_id`, `symbol`, `source_timeframe`, `confirmation_timeframe`, `sequence_domain` | Context Header Card. Displays active source context and mapped confirmation timeframe. Explicitly notes: `"Confirmation TF is metadata mapping only; no confirmation arbitration active."` |
| **G2** | **Membership** | `set_id`, `role`, `level_id` (`side`, `source_open_time`), `lower_edge`, `upper_edge`, `is_line`, `eligibility_available_time` | Active Set Members Table. Shows currently eligible source members. Retired outgoing members strictly excluded. Displays exact zone price bounds and availability evidence. |
| **G3** | **Activation** | `activation_id`, `state`, `generation_seq`, `first_touch_time`, `first_touch_price`, `trigger_observation_id`, `prior_activation_id` | Active Activations Card/Table. Renders current active states (`INACTIVE_ELIGIBLE`, `PENDING_ACTIVATION`, `REARMED_PENDING`). Displays exact first-touch price and observation ID. Shows generation links for reactivated levels. |
| **G4** | **Evidence Gating** | `usage_evidence_status`, `coverage_status`, `blocked_reason` | Evidence Gating Badges. Green `"UNUSED"` badge if clean; amber `"UNKNOWN (FAIL-CLOSED)"` badge if evidence is uncertain. Displays exact `blocked_reason` text when transitions are blocked. |
| **G5** | **Cancellation** | `cancellation_reason`, `cancellation_time`, `cancellation_sequence_ref`, `target_set_id`, `affected_direction` | Cancellation Audit Block. Displays reason (`SOURCE_CHOCH`, `SOURCE_REPLACEMENT`, `EXTERNAL_ENTRY`). Shows explicit sequence reference and timestamp (or `"Timestamp Unknown"`). |
| **G6** | **Rearm Controller** | `member_key`, `prior_activation_id`, `generation_seq`, `state`, `rearm_armed`, `last_observed_position` | Decoupled Rearm Controllers Table. Displays controllers awaiting departure (`CANCELLED_EXTERNAL_ENTRY`) or armed for retouch (`OUT_OF_ZONE_ARMED`). Explicitly labeled as departure monitors, not active activations. |
| **G7** | **Terminal History** | `Sequence[ActivationRecord]` (terminal records) | Terminal Activation History Table. Immutable audit log of past activations, terminal states, and final outcomes. Visually distinct from active members (muted background, clear terminal stamps). |
| **G8** | **Synchronization** | `last_processed_sequence`, `last_processed_timestamp`, `is_unresolved`, `unresolved_diagnostic` | Synchronization Diagnostic Bar. Displays engine sequence cursor, processed timestamp, and any frozen/unresolved source diagnostics with bar indexing. |

---

## 4. Architecture Contract, Data Ownership & Side-Effect Boundaries

### 4.1 Pure Presentation Projection
The dashboard presentation layer must be implemented as a pure function:
```python
def build_activation_inspection_elements(
    activation_snapshot: Optional[ActivationSnapshot],
    tjl_snapshot: Optional[TJLSnapshot] = None,
) -> list[html.Div]:
    ...
```
- **Zero Reducer Side Effects**: The projection function must never call `engine.process_event()`, `engine.register_source_member()`, `engine.reset()`, or `synchronizer.sync()`.
- **Zero Cursor Side Effects**: The projection function must never advance synchronizer cursors, consume unread transitions, or modify cache dictionaries.
- **Snapshot Immutability**: All inputs to the projection function are frozen/immutable dataclasses.

### 4.2 Single Retained Synchronizer Ownership
- `TJLSynchronizer` must be owned exclusively by the application service layer (`src/aladeen/strategy/service.py`) or session coordinator.
- UI rendering callbacks and inspection builders must **never** instantiate transient `TJLSynchronizer` instances.
- Re-renders with the same data must receive the same immutable `ActivationSnapshot` projection.

### 4.3 Deterministic Ordering
To ensure deterministic offline testing and stable DOM rendering, collections must be sorted predictably:
1. **Current Members**: Sorted alphabetically by `(set_id, role)`.
2. **Active Activations**: Sorted alphabetically by `(set_id, role)`.
3. **Rearm Controllers**: Sorted alphabetically by `(member_key, prior_activation_id)`.
4. **Terminal History**: Sorted deterministically in reverse chronological/sequence order: `(cancellation_sequence_ref or 0, cancellation_time or min_date, activation_id)` descending.

### 4.4 Bounded History Presentation Policy
- The dashboard display may visually paginate or limit visible rows in the terminal table (e.g., latest 50 records) for DOM performance, but must clearly indicate the total historical count.
- Under no circumstances may the presentation layer prune, clear, or mutate the underlying `ActivationSnapshot.terminal_activations` tuple.

### 4.5 Error and Missing-Data Handling
- If `activation_snapshot is None`, render a clean placeholder card: `"AWAITING ACTIVATION CONTEXT — NO ACTIVE ENGINE"`.
- If an individual field is `None`, render `"None"`, `"N/A"`, or `"—"`.
- Never throw unhandled exceptions during UI projection; fail safe with a clear diagnostic container.

---

## 5. Acceptance Scenarios & Precise Assertion Contract

The acceptance suite specifies 16 deterministic scenarios covering all lifecycle states, evidence combinations, and boundary conditions:

### Scenario 1: Eligible, Untouched Member (`dash_act_01_eligible_untouched`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Active set `SET_1` with `TJL1` (upper: 1.1400, lower: 1.1350, available: `2026-10-02 08:00 UTC`). Zero touch events.
- **Expected View**: State = `INACTIVE_ELIGIBLE`. Zone bounds and eligibility time displayed cleanly.
- **Assertions**: `first_touch_time` is `None` (rendered as `"—"`), `trigger_observation_id` is `None`, `is_actionable == False`, no first-touch claim in DOM.

### Scenario 2: First Exact Touch (`dash_act_02_first_exact_touch`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: `SET_1/TJL1` receives `ExactPricePrint(OBS_01, price=1.1370, time=2026-10-02 08:15 UTC)`.
- **Expected View**: State = `PENDING_ACTIVATION`. Badge = `"PENDING ACTIVATION (GEN 1)"`.
- **Assertions**: `first_touch_time == "2026-10-02 08:15:00 UTC"`, `first_touch_price == 1.1370`, `trigger_observation_id == "OBS_01"`, `is_actionable == False` (non-execution disclaimer rendered).

### Scenario 3: Repeated Touch (`dash_act_03_repeated_touch`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Following Scenario 2, second print `ExactPricePrint(OBS_02, price=1.1380, time=2026-10-02 08:20 UTC)` arrives.
- **Expected View**: State remains `PENDING_ACTIVATION`.
- **Assertions**: `first_touch_time` remains strictly `"2026-10-02 08:15:00 UTC"`, `first_touch_price` remains `1.1370`, `trigger_observation_id` remains `"OBS_01"`. Zero overwrite from `OBS_02`.

### Scenario 4: Unknown Usage Evidence (`dash_act_04_unknown_usage`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: `SET_1/TJL1` active with `usage_evidence_status = UNKNOWN`.
- **Expected View**: State = `PENDING_ACTIVATION`, but Gating Badge = `"USAGE UNKNOWN — FAIL-CLOSED"`. Blocked Reason = `"USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"`.
- **Assertions**: Gating status prominently rendered in amber/red; styling strictly prohibits active/executable appearance.

### Scenario 5: Incomplete / Uncertain Coverage (`dash_act_05_incomplete_coverage`)
- **Evidence Category**: `edge_boundary_specification` / `synthetic`
- **Presentation Inputs**: Activation engine coverage set to `CoverageStatus.PARTIAL`.
- **Expected View**: Coverage Badge = `"COVERAGE INCOMPLETE / UNCERTAIN"`.
- **Assertions**: Coverage warning rendered independently of member state. Disclaimers note data gap.

### Scenario 6: Unknown Availability Time (`dash_act_06_unknown_availability`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Member registered with `eligibility_available_time = None`.
- **Expected View**: State = `INACTIVE_INELIGIBLE`. Availability column displays `"Unknown (Pending Evidence)"`.
- **Assertions**: Zero inferred activation time, zero default to current time, blocked reason indicates missing availability.

### Scenario 7: Source Cancellation (`dash_act_07_source_cancellation`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Active `SET_1/TJL1` cancelled via `SourceCancellationEvent(reason=SOURCE_CHOCH, target_set_id="SET_1")`.
- **Expected View**: `SET_1` completely absent from Active Set Members table. Record appears in Terminal History with state `CANCELLED_SOURCE_CHOCH`.
- **Assertions**: Active member count = 0; Terminal history count = 1; `cancellation_reason == "SOURCE_CHOCH"`.

### Scenario 8: Cancellation with Unknown Timestamp (`dash_act_08_cancellation_unknown_time`)
- **Evidence Category**: `edge_boundary_specification` / `synthetic`
- **Presentation Inputs**: Cancellation event with `timestamp = None`, `sequence_ref = 105`.
- **Expected View**: Terminal record shows Cancellation Time = `"Unknown"`, Causal Sequence = `"#105"`.
- **Assertions**: Physical timestamp rendered as `"Unknown"`; sequence displayed in separate dedicated column; zero wall-clock interpolation.

### Scenario 9: External Cancellation While Inside Zone (`dash_act_09_external_cancellation_inside`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Level inside zone when external commit arrives (`last_observed_position="INSIDE"`).
- **Expected View**: Terminal record shows `CANCELLED_EXTERNAL_ENTRY`. Rearm Controllers table shows active controller with `state="CANCELLED_EXTERNAL_ENTRY"`, `rearm_armed=False`, `status="Awaiting Departure Outside Zone"`.
- **Assertions**: Controller cleanly decoupled from terminal record; controller explicitly indicates departure required before rearming.

### Scenario 10: Armed Controller (`dash_act_10_armed_controller`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Following Scenario 9, price print outside zone transitions controller to `OUT_OF_ZONE_ARMED` (`rearm_armed=True`).
- **Expected View**: Rearm Controllers table shows `state="OUT_OF_ZONE_ARMED"`, `rearm_armed=True`, Badge = `"ARMED FOR RETOUCH"`.
- **Assertions**: Controller displayed as armed; Active Activations table shows 0 pending activations (arming is not an activation).

### Scenario 11: Valid Reactivation (`dash_act_11_valid_reactivation`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Following Scenario 10, new print inside zone activates generation 2 (`REARMED_PENDING`).
- **Expected View**: Active Activations table shows `activation_id="..._gen2"`, `generation_seq=2`, `prior_activation_id="..._gen1"`, State = `REARMED_PENDING`. Terminal table retains generation 1 record.
- **Assertions**: Generation 2 linked to Generation 1; Generation 1 immutable in terminal history; provenance chain unbroken.

### Scenario 12: Successor Set with Persistent Physical Level (`dash_act_12_successor_set_persistent_level`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: `SET_1` cancelled. Distinct successor set `SET_2` registered containing the exact same `StableLevelId`.
- **Expected View**: Active Set Members shows `SET_2/TJL1`. Level ID matches historical `SET_1` level ID. State = `INACTIVE_ELIGIBLE (GEN 0)`.
- **Assertions**: Set identity strictly `SET_2`; physical level attribution matches; zero activation inheritance from cancelled `SET_1`.

### Scenario 13: Unresolved Source Snapshot (`dash_act_13_unresolved_source_snapshot`)
- **Evidence Category**: `edge_boundary_specification` / `candle-pipeline-derived`
- **Presentation Inputs**: Source `TJLSnapshot` with `is_unresolved=True`, `last_processed_index=15`, `last_received_index=19`, `diagnostic="Simultaneous c1==p2 touch"`.
- **Expected View**: Prominent amber banner: `"LAST AUTHORITATIVE EVIDENCE (SOURCE UNRESOLVED)"`. Diagnostic shows `"Processed through Bar #15 | Received through Bar #19"`.
- **Assertions**: Frozen authoritative bar distinguished from received bar; no fresh eligibility created.

### Scenario 14: Equal Coarse Timestamps (`dash_act_14_equal_coarse_timestamps`)
- **Evidence Category**: `edge_boundary_specification` / `synthetic`
- **Presentation Inputs**: Multiple events sharing identical coarse timestamp `2026-10-02 09:00:00 UTC` but distinct sequences `seq=201`, `seq=202`.
- **Expected View**: Both records displayed distinctly, disambiguated by canonical activation IDs and sequence references.
- **Assertions**: Zero collapsing or key collisions; sorting strictly preserves sequence ordering.

### Scenario 15: Multiple Source Timeframes (`dash_act_15_multiple_source_timeframes`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: H1 engine (`confirmation_timeframe="M1"`) and H4 engine (`confirmation_timeframe="M5"`) inspected.
- **Expected View**: Context header reflects exact engine timeframe and mapped confirmation timeframe.
- **Assertions**: Exact 1:1 mapping verified (`H1 -> M1`, `H4 -> M5`, `D1 -> H1`); zero cross-timeframe arbitration or winner ranking.

### Scenario 16: Repeated Rendering Invariance (`dash_act_16_repeated_rendering`)
- **Evidence Category**: `source_settled` / `engine-derived`
- **Presentation Inputs**: Call `build_activation_inspection_elements()` 5 times consecutively on the same snapshot.
- **Expected View**: All 5 outputs identical in structure, children, IDs, and text.
- **Assertions**: Snapshot unchanged; synchronizer cursor unchanged; zero memory leaks or mutated globals.

---

## 6. Integration-Gap Assessment

### 6.1 Repository Paths Inspected
1. `src/aladeen/ui/tjl_inspection.py` (430 lines): Current TJL read-only inspection builder. Provides cards, tables, and transition audits.
2. `src/aladeen/ui/msm_callbacks.py` (1770 lines): Central Dash callbacks orchestrating UI updates. Coordinates candidate envelopes and inspection panel updates.
3. `src/aladeen/ui/layout.py`: Core dashboard layout containing tab containers and inspection panel layout (`#tjl-inspection-container`, `#msm-inspection-container`).
4. `src/aladeen/strategy/service.py` (680 lines): Application service layer returning `MSMServiceResult`.
5. `src/aladeen/strategy/activation_types.py` (335 lines): Data contract defining `ActivationSnapshot`, `ActivationRecord`, `RearmController`.
6. `src/aladeen/strategy/activation_adapter.py` (258 lines): `TJLSynchronizer` and adapter helpers.

### 6.2 Proposed Integration Points
- **Module Addition**: In the implementation phase, introduce `src/aladeen/ui/activation_inspection.py` housing `build_activation_inspection_elements()`.
- **Service Layer Bridge**: `MSMServiceResult` will include an optional `activation_snapshot: Optional[ActivationSnapshot] = None`.
- **Synchronizer Lifecycle**: The service layer (`service.py`) will own a session-scoped `TJLSynchronizer` instance that synchronizes accepted `TJLSnapshot` instances, producing `activation_snapshot` before returning `MSMServiceResult`.
- **UI Mounting**: Mount `#activation-inspection-container` inside the inspection panel layout in `layout.py` alongside the existing TJL and ISS containers.

### 6.3 Public Field Availability Audit
All required display fields are **already fully present** on public dataclasses:
- `ActivationSnapshot`: `engine_id`, `symbol`, `source_timeframe`, `confirmation_timeframe`, `sequence_domain`, `active_activations`, `terminal_activations`, `coverage_status`, `last_processed_sequence`, `last_processed_timestamp`, `current_members`, `rearm_controllers`.
- `ActivationRecord`: `activation_id`, `state`, `generation_seq`, `first_touch_time`, `first_touch_price`, `trigger_observation_id`, `prior_activation_id`, `usage_evidence_status`, `blocked_reason`, `cancellation_reason`, `cancellation_time`, `cancellation_sequence_ref`.
- `RearmController`: `member_key`, `prior_activation_id`, `generation_seq`, `state`, `rearm_armed`, `last_observed_position`, `cancellation_time`, `cancellation_sequence_ref`.

**Smallest Proposed Observational Additions**:
No new engine fields or private dictionary exposures are required. The existing public output contract is 100% sufficient for all 8 display groups and all 16 acceptance scenarios.

---

## 7. Review and Acceptance Criteria

For HANDOFF-062 acceptance:
1. Complete requirements specification in `docs/requirements/activation-dashboard-acceptance.md`.
2. Standardized acceptance fixtures in `tests/fixtures/activation_dashboard_acceptance.json` covering all 16 scenarios with explicit evidence categories.
3. Automated fixture integrity test in `tests/test_activation_dashboard_fixture_integrity.py` passing cleanly offline.
4. Full offline repository test suite passing (509 tests).
5. Zero runtime code modifications in this phase.
