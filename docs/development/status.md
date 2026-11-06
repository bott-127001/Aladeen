# Development & Review Status — Aladeen / TopG

Last Updated: 2026-11-05 (MSM Dashboard Milestone Accepted — Transition to CHOCH Specification)

---

## 1. Readiness Checkpoints

| # | Checkpoint | Status | Details |
|---|---|---|---|
| 1 | **Workflow documentation prepared** | **COMPLETE** | `AGENTS.md`, `autonomous-workflow.md`, `status.md`, `README.md` defined, committed, and pushed. |
| 2 | **Browser control verified** | **COMPLETE** | Dedicated Comet instance running on isolated profile (`C:\Users\samar\.comet-automation-profile`), listener loopback-only (`127.0.0.1:9223`). Attached via Playwright CDP. |
| 3 | **Authentication completed** | **COMPLETE** | User signed into Perplexity in dedicated Comet profile. |
| 4 | **Conversation handoff verified** | **COMPLETE** | Active conversation at `/search/b501f216-c18a-4ce9-b16b-4f4ec06aca28`. Automated handoffs completed through HANDOFF-016. |
| 5 | **Autonomous operation approved** | **COMPLETE** | Standing authorization active for Perplexity-led development across agreed dashboard and strategy modules. |

---

## 2. Milestone Acceptance: MSM Dashboard Integration
- **Accepted Milestone**: Market Structure Marking (MSM) Read-Only Dashboard Integration.
- **Accepted Commit Hash**: `133a76f1663bf0a940cc6ac2972a7bb86151832d` (`fix(strategy): bundle candidate envelope, preserve shared session, and verify browser races (HANDOFF-016)`)
- **Reviewer Status**: **ACCEPTED** by Perplexity for the bounded MSM dashboard scope, with recorded verification boundaries.
- **Accepted Implementations**:
  1. Synchronous browser-side request issuance (`CLIENTSIDE_REQUEST_ISSUANCE_JS`) generating unique request tokens and context before dispatch.
  2. Single candidate result envelope (`market-candidate-envelope-store`) bundling `{request_token, snapshot, connection_event}` atomically.
  3. Strict client-side acceptance gate (`CLIENTSIDE_ACCEPTANCE_GATE_JS`) enforcing token and context invariants prior to publication in `market-data-store`.
  4. Isolation of adapter lifecycle: removed request-local `adapter.disconnect()` from stale-capable fetch error paths, preserving active shared MT5 sessions.
  5. 1-based structural numbering (`H1`, `L1`), explicit support/resistance lines, and strict manual direction/start validation.

### Recorded Verification Boundaries:
- **Browser Race Testing Characterization**: The browser tests in `tests/test_browser_race_controlled.py` are **stale-envelope injection tests** using `window.dash_clientside.set_props()` into `market-candidate-envelope-store` after newer data has been accepted. They verify that `CLIENTSIDE_ACCEPTANCE_GATE_JS` executes in the browser, rejects stale tokens, and preserves accepted stores. They do **not** claim proof of concurrent network-level overlapping HTTP fetch resolution in the browser.
- **Browser Error Evidence**: The controlled race tests verify zero uncaught browser page errors (`page.on('pageerror')`). The separate live terminal workflow (`tests/browser_check.py`) verified 0 browser console errors across all 8 flows.
- **Store Observation Boundary**: The test verifies that `connection-loss-trigger` is not updated; because that store is memory-backed, direct inspection in the browser is constrained to React state and absence of UI error banners/badge changes.

---

## 3. Milestone Acceptance: CHOCH Requirements & Acceptance Specification
- **Accepted Milestone**: Change of Character (CHOCH) Acceptance Specification & Fixture Validation.
- **Accepted Commit Hash**: `7d5e3aedeff3548b2cf35fa41833f6948ad8d82f` (HANDOFF-019)
- **Reviewer Status**: **ACCEPTED** by Perplexity as the source-settled CHOCH requirements baseline, with the Point-3 identification-close question ($c_1 == p_2$) explicitly isolated as unresolved pending source reconciliation.
- **Key Baseline Requirements**:
  1. Two consecutive completed closes strictly beyond confirmed level (`close < last_support` for Bearish, `close > last_resistance` for Bullish).
  2. Strict closing price comparison: exact equality touch fails closed; wick pierces without closing break fail closed.
  3. Candle color independence: closing price rule is independent of red/green candle colors.
  4. Active tentative Point 3 required: Point 3 anchored to identified swing candle; continuation break resets tentative status.
  5. Isolated same-close interpretation ($c_1 == p_2$): strictly before identification ($< p_2$) is ineligible; strictly after ($c_1 \ge p_2 + 1$) is source-settled; simultaneous close ($c_1 == p_2$) emits an unresolved diagnostic without forced boolean outcome.
  6. Three original-candle zones: SBR (`[low, LB]`), RBS (`[UB, high]`), QML / A+ (`[UB, high]` for upward, `[low, LB]` for downward), Double Top/Bottom.
  7. Zero-wick zones preserved as thickness-0 horizontal price lines (`is_line = true`).
  8. Cycle termination and restart: prior cycle ends; direction reverses; restart reference is Point 3 original candle; first pullback in new direction must occur strictly after confirmation bar ($p_1 \ge c_2 + 1$).
  9. Pre-CHOCH MSM prerequisites independently verified via `test_end_to_end_msm_prerequisites_match_msm_engine`.

---

## 4. Milestone Acceptance: CHOCH Strategy Engine Implementation & Lifecycle Hardening
- **Accepted Milestone**: Pure Offline CHOCH Strategy Engine Implementation.
- **Accepted Commit Hash**: `86b247f9` (HANDOFF-023)
- **Reviewer Status**: **ACCEPTED** by Perplexity with standing authorization for ISS requirements phase.

---

## 5. Milestone Acceptance: ISS Requirements & Acceptance Specification
- **Accepted Milestone**: Internal Structure Shift (ISS) Acceptance Specification & Boundary Hardening.
- **Accepted Commit Hash**: `c6e58a26ef7d813e8bc884bbb8ac285440e9649d` (HANDOFF-027)
- **Reviewer Status**: **ACCEPTED** by Perplexity as bounded ISS requirements baseline.

---

## 6. Milestone Acceptance: Pure Offline ISS Strategy Engine Implementation
- **Accepted Milestone**: Pure Offline ISS Strategy Engine Implementation (`HANDOFF-030`).
- **Accepted Commit Hash**: `4948ea5c326f65cc4d58b95c196801408f7dd7ef`
- **Reviewer Status**: **ACCEPTED** by Perplexity with instruction to proceed directly to offline and dashboard integration.
- **Accepted Implementations**:
  1. Terminal precedence (R29.1): main continuation break taking place on the 5th-point candle takes precedence over ISS confirmation.
  2. Clean cancellation cleanup (R29.2): zero residual markings or zones on cancelled/rejected candidates.
  3. Unresolved progress reporting (R29.3): frozen authoritative `last_processed_index` alongside advancing `last_received_index`.
  4. Modular tracking extraction (`src/aladeen/strategy/iss_tracking.py`).

---

## 7. Current Milestone: ISS Dashboard Integration (HANDOFF-031 & HANDOFF-032)
- **Active Branch**: `feature/iss-dashboard`
- **Objective**: Integrate the accepted offline ISS Engine into the Aladeen / TopG read-only dashboard with deterministic browser verification.
- **Scope Boundary**: Pure offline strategy calculation and read-only dashboard presentation. **Strictly zero UI order execution, zero MT5 trading calls, zero TJL, zero zone activations, zero trade entry signals, zero automated trading, and zero merging to `main`**.
- **Completed Deliverables (HANDOFF-031 & HANDOFF-032)**:
  1. `src/aladeen/strategy/iss_types.py` & `src/aladeen/strategy/iss_engine.py`:
     - Added public `ISSCombinedResult` container bundling `(iss_snapshot, main_coordinator_snapshot, confirmed_iss_events)`.
     - Added public `ISSEngine.get_combined_result()` and `ISSEngine.get_main_coordinator_snapshot()`.
     - Zero private attribute access (`_main_coordinator`) from application service layer.
  2. `src/aladeen/strategy/service.py`:
     - Added `CalculationMode.INTEGRATED_MSM_CHOCH_ISS = "INTEGRATED_MSM_CHOCH_ISS"`.
     - Added `show_iss_markers`, `show_iss_zones`, `show_iss_points` to `MSMContext`.
     - Integrated `ISSEngine` via public `get_combined_result()`.
  3. `src/aladeen/ui/chart.py`:
     - Stamped zone shapes with stable identifiers `name=f"iss_zone_{z_type_str.lower()}"` and `name=f"choch_zone_{z_type_str.lower()}"`.
     - Exactly two ISS zones rendered for confirmed event (Level 3 RBS/SBR and Level 4 Buying/Selling A+) starting horizontally strictly at `confirmation_availability_time`.
     - Unknown availability creates 0 zone shapes (zero speculative extension).
     - Zero-width zones rendered as horizontal lines (`y0 == y1`).
     - Markers anchored to candle open with tooltip distinguishing open anchor from confirmation close.
     - Tooltips explicitly labeled as structural events, not order entry signals.
  4. `src/aladeen/ui/msm_callbacks.py`:
     - Normalized dropdown ISO strings and UTC datetimes to prevent false unapplied draft warnings.
     - Rendered Candidate Identity card, 5-point structure table, Attempted/Tracking tables, Active Zones table, and Confirmed History table.
  5. `tests/test_iss_dashboard_integration.py`:
     - Cleaned `_make_snapshot_from_fixture` to preserve exact fixture timestamps without synthetic offsets.
     - Separated `test_continuation_cancellation_presentation` (exact `MAIN_CONTINUATION_CANCELLED`) and `test_genuine_tracking_only_presentation` (exact `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY`).
     - 15/15 offline integration tests pass in 1.61s.
  6. `tests/test_iss_browser_controlled.py`:
     - Deterministic Playwright verification across 9 scenarios using `ControllableISSMockAdapter` on port 8062:
       1. Bearish success (`iss_01`): chart coordinates, markers, zones, inspection text, CONFIRMED badge.
       2. Bullish success (`iss_02`): SBR & Selling A+ zones, CONFIRMED badge.
       3. Genuine tracking-only progression: `OUTSIDE RANGE COMPLETION (TRACKING ONLY — NOT ELIGIBLE)` badge, attempted & tracking points tables.
       4. Out-of-bounds rejection (`iss_05`): `OUT_OF_BOUNDS_REJECTED` badge, 0 active zones.
       5. Main-continuation cancellation (`iss_09`): `MAIN_CONTINUATION_CANCELLED` badge, 0 active zones.
       6. Unresolved-main presentation: `#unresolved-status-banner` with orange `#ff9800` border and frozen authoritative bar.
       7. Mode Apply vs unapplied draft edits: `"🟡 Unapplied changes"` vs `"🟢 Applied"`.
       8. ISS display toggles: unchecking markers/zones updates presentation without recalculation.
       9. Context switch / Refresh with shared revision: revision updates without improper retention.
       10. Error Accounting: 0 console errors, 0 page errors.
  7. Verification Summary:
     - 328 unit/integration tests pass in 9.77s.
     - 1 browser controlled test suite (9 scenarios) passes in 52.48s.
     - Total: 329 tests passing with 0 failures.
     - Rendered Candidate Identity card, Lifecycle Status badge, 5-Point Structure table, Tracking Points table, Active Zones table, and Confirmed ISS History table.
     - Unapplied draft edits isolation and unresolved ambiguity containment.
  5. `tests/test_iss_dashboard_integration.py`:
     - 13 comprehensive, deterministic offline integration tests covering service calculations, chart overlays, inspection panel tables, display toggle invariance, draft isolation, and unresolved state presentation.
- **Verification**: Full suite of 329 tests passing in 6.19s, browser controlled tests passing with 0 errors across all 9 scenarios.

### HANDOFF-033: Authentic Tracking-Only Progression & Mock Elimination
- **Context & Motivation**:
  - Per review feedback for HANDOFF-032, eliminated `_patch_calculate_msm_for_tracking_only()` in `tests/test_iss_browser_controlled.py`.
  - Reconciled strategy semantics and candidate completion on the Level 2 side versus Level 3 side:
    - **Level 3 Side**: In Bearish Main (`boundary = [1.1400, 1.2000]`), closing below 1.1400 definitionally breaks Main Level 3 (Tentative Low). Main MSM confirms continuation and clears the tentative point, so the main structure does NOT remain active at that prefix (tested in `iss_06`, producing `MAIN_CONTINUATION_CANCELLED`).
    - **Level 2 Side**: Closing above 1.2000 violates the captured boundary without breaking Main Level 3 (1.2000 does not close below 1.1400). Main Level 3 remains 100% active at that prefix.
  - Hardened `src/aladeen/strategy/iss_engine.py`:
    - Differentiated Main Continuation cancellation from Main CHOCH coordination during outside-range completion evaluation (`msm_tentative is None and len(main_coord_copy.confirmed_choch_events) == prev_choch_count`).
    - Introduced `candidate_completed_outside_this_bar` to protect candidates that just entered `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY` from same-bar cancellation by subsequent coordination checks.
    - Updated `InternalPoint` in `src/aladeen/strategy/iss_types.py` to allow `point_number >= 1`, accommodating ongoing tracking swings.
  - Constructed authentic candle sequence in `ControllableISSMockAdapter.fetch_candles` (`symbol == "GBPUSD"`):
    - Genuine candles 19 ($p_1$) and 20 ($p_2$) complete Point 5 with completion close > 1.2000.
    - Naturally produces genuine `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY` status through real unpatched `calculate_msm` service and `ISSEngine`.
    - Produces 5 attempted points, 5 tracking points, 0 active zones, and 0 confirmed events.
  - **Verification**:
    - `pytest tests/test_iss_engine.py`: 34/34 passed in 1.12s (including new `test_authentic_candle_sequence_produces_genuine_tracking_only`).
    - `pytest tests/test_iss_dashboard_integration.py`: 15/15 passed in 3.30s.
    - `python tests/test_iss_browser_controlled.py`: All 9 scenarios passed with 0 console errors and 0 page errors.
    - Full offline test suite (`pytest -m "not slow" -k "not browser"`): 329 passed, 1 deselected in 6.19s.

### HANDOFF-034: Restored Source Cancellation & Central Tracking Fixture Exploration
- **Context & Motivation**:
  - Per review feedback for HANDOFF-033, removed the `candidate_completed_outside_this_bar` exemption from `src/aladeen/strategy/iss_engine.py`. A confirmed Main CHOCH unconditionally cancels unfinished ISS search or tracking-only processes (`if len(main_coord_copy.confirmed_choch_events) > prev_choch_count:`).
  - Main continuation cancellation remains strictly distinguished from Main CHOCH (`msm_tentative is None and len(main_coord_copy.confirmed_choch_events) == prev_choch_count`).
  - Corrected the Candle 19/20 fixture unit test (`test_candle_19_20_both_closing_above_level_2_confirms_main_choch_and_cancels_candidate` in `tests/test_iss_engine.py`) to assert that when Candle 19 (1.205) and Candle 20 (1.201) both close strictly above Last Resistance (1.200), Candle 20 confirms Main Bullish CHOCH and cancels the candidate with `MAIN_CHOCH_CANCELLED`, 0 tracking points, 0 active zones, and 0 events.
  - Explored the geometric feasibility of an outside-range completion on the Level-2 side where the preceding candle does NOT qualify as a Main CHOCH first close:
    - **Mathematical Proof**: In any valid 2-candle pullback $(p_1, p_2)$ for an upward internal structure, $p_1$ is RED ($C_1 < O_1$), $p_2$ is RED ($C_2 < O_2$), and strict wick-break requires $C_2 < L_1$. By definition of candlestick low, $L_1 \le C_1$. Thus $C_2 < L_1 \le C_1 \implies C_2 < C_1$.
    - Because this inequality is invariant to $O_1$ and $O_2$, no price gap between $C_1$ and $O_2$ can violate $C_2 < C_1$.
    - Therefore, whenever the completion candle closes strictly above Level 2 ($C_2 > 1.2000$), $C_1 > C_2 > 1.2000$, so the preceding candle $p_1$ MUST also close strictly above Level 2.
    - Consequently, under complete provenance, Candle 20 unconditionally confirms Main Bullish CHOCH and cancels tracking.
  - Created centralized fixture module `tests/fixtures/iss_fixtures.py`:
    - `get_candle_19_20_cancellation_fixture()`: standard 21-candle sequence demonstrating Main CHOCH cancellation.
    - `get_tracking_only_fixture()`: genuine tracking-only fixture demonstrating exact `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY` when Main CHOCH is withheld (count == 0), extended through Candles 21–22 advancing tracking points without revival, and cancelled by subsequent Candles 23–24.
  - Browser Automation Verification:
    - Updated `tests/test_iss_browser_controlled.py` to consume centralized fixture through `ControllableISSMockAdapter`.
    - Real production `calculate_msm` service execution in Chromium browser (zero monkey-patching).
  - **Verification**:
    - `pytest tests/test_iss_engine.py`: 35/35 passed in 1.09s.
    - `python tests/test_iss_browser_controlled.py`: All 9 scenarios passed with 0 console errors and 0 page errors.
    - Full offline test suite (`pytest -m "not slow" -k "not browser"`): 330 passed, 1 deselected in 4.56s.

### HANDOFF-035: Honest ISS Verification Closure, Reachability Limitation & Provenance Audit
- **Context & Motivation**:
  - Per review feedback for HANDOFF-034, verified production cancellation patch, formally audited all tracking-only tests, recorded the mathematical reachability limitation, and closed ISS verification honestly without modifying strategy rules.
- **1. Verified Production Cancellation Patch**:
  - In `src/aladeen/strategy/iss_engine.py`, completely excised the `candidate_completed_outside_this_bar` exemption.
  - When Main CHOCH confirms on any bar (including an outside-completion bar), `if len(main_coord_copy.confirmed_choch_events) > prev_choch_count:` unconditionally transitions the candidate to `MAIN_CHOCH_CANCELLED`, clearing attempted points, tracking points, active zones, and active candidate data.
  - The distinction between Main Continuation cancellation (`msm_tentative is None and len(main_coord_copy.confirmed_choch_events) == prev_choch_count`) and Main CHOCH cancellation (`len(main_coord_copy.confirmed_choch_events) > prev_choch_count`) is preserved.
- **2. Mathematical Pullback Inequalities & Reachability Limitation**:
  - **Upward Internal Marking (Bearish Main)**:
    - In any valid 2-candle pullback $(p_1, p_2)$, $p_1$ is RED ($C_1 < O_1$), $p_2$ is RED ($C_2 < O_2$), and strict wick-break requires $C_2 < L_1$.
    - By definition of candlestick low, $L_1 = \min(O_1, H_1, L_1, C_1) \le C_1$.
    - Transitivity dictates:
      $$C_2 < L_1 \le C_1 \implies C_2 < C_1$$
    - Invariance to Price Gaps: A gap between $C_1$ and $O_2$ only bounds $C_2 < O_2$ from above; it cannot overturn $C_2 < L_1 \le C_1$.
    - If completion close $C_2 > 1.2000$ (Level 2 Last Resistance), then $C_1 > C_2 > 1.2000$.
    - Consequently, both pullback candles necessarily close above Level 2, qualifying as the two consecutive closes for Main Bullish CHOCH.
  - **Mirrored Downward Internal Marking (Bullish Main)**:
    - In any valid 2-candle pullback $(p_1, p_2)$, $p_1$ is GREEN ($C_1 > O_1$), $p_2$ is GREEN ($C_2 > O_2$), and strict wick-break requires $C_2 > H_1$.
    - By definition of candlestick high, $H_1 = \max(O_1, H_1, L_1, C_1) \ge C_1$.
    - Transitivity dictates:
      $$C_2 > H_1 \ge C_1 \implies C_2 > C_1$$
    - Invariance to Price Gaps: A gap between $C_1$ and $O_2$ only bounds $C_2 > O_2$ from below; it cannot overturn $C_2 > H_1 \ge C_1$.
    - If completion close $C_2 < 1.1000$ (Level 2 Last Support), then $C_1 < C_2 < 1.1000$.
    - Consequently, both pullback candles necessarily close below Level 2, qualifying as the two consecutive closes for Main Bearish CHOCH.
  - **Prerequisites for Complete-State Reachability**:
    - Under complete provenance (source candles for resistance/support, tentative point 3, and confirmed low/high all exist in history) and active Main Point 3, two adjacent closes outside Level 2 necessarily confirm Main CHOCH.
    - Because confirmed Main CHOCH unconditionally cancels any active candidate, the source-defined `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY` lifecycle state is **unreachable in an integrated complete-state run with complete provenance**.
  - **Non-Invention & Strategy Authority**:
    - This deduction establishes non-reachability under existing rules; it is NOT a new approved strategy rule.
    - The source-defined tracking-only branch remains fully implemented and preserved in `ISSEngine`. Reconciliation of this branch with integrated complete-state reachability is formally recorded as a known limitation.
- **3. Test-Provenance Audit**:
  - Formally categorized all tracking-only tests across the test suite:
    - `test_tracking_points_continue_independently_of_attempted_points` (`tests/test_iss_engine.py`): `[Isolated Lifecycle Test - Private State Mutation]`
    - `test_tracking_only_candidate_followed_by_main_continuation_cancels` (`tests/test_iss_engine.py`): `[Isolated Lifecycle Test - Private State Mutation]`
    - `test_tracking_only_candidate_followed_by_main_choch_cancels` (`tests/test_iss_engine.py`): `[Isolated Lifecycle Test - Private State Mutation]`
    - `test_isolated_tracking_only_distinct_from_continuation_cancellation` (`tests/test_iss_engine.py`): `[Isolated Lifecycle Test - Private State Mutation]`
    - `test_synthetic_missing_evidence_isolated_tracking_progression_and_cancellation` (`tests/test_iss_engine.py`): `[Isolated Lifecycle Test - Scoped Prerequisite Modification]` (withholds `low_candle` lookup entry `2` to isolate the engine's tracking-only progression, verifying clean cancellation when restored).
    - `test_isolated_tracking_only_presentation` (`tests/test_iss_dashboard_integration.py`): `[Isolated Presentation Test - Injected Snapshot]`.
  - Disclaimed Evidence: None of the above isolated tests are counted as complete engine-to-browser candle-driven lifecycle evidence.
- **4. Browser Acceptance & Error Accounting**:
  - `tests/test_iss_browser_controlled.py`:
    - Scenario 1: Bearish ISS Success (`iss_01` / H1) — genuine candle-driven.
    - Scenario 2: Bullish ISS Success (`iss_02` / H4) — genuine candle-driven.
    - Scenario 3: Outside-Range Completion Cancelled by Main CHOCH (`GBPUSD` / H1) — genuine candle-driven complete-state fixture (`get_candle_19_20_cancellation_fixture()`). Asserts `MAIN_CHOCH_CANCELLED`, `Cancelled by main CHOCH confirmation.`, `BULLISH_CHOCH` event, and 0 active ISS zones.
    - Scenario 4: Out-of-Bounds Rejection (`iss_05` / M5) — genuine candle-driven.
    - Scenario 5: Main-Continuation Cancellation (`iss_09` / M1) — genuine candle-driven.
    - Scenario 6: Unresolved Main Structure (`D1`, `c1 == p2`) — genuine candle-driven unresolved dependency presentation.
    - Scenario 7: Mode Apply vs Unapplied Draft Edits — interactive UI state.
    - Scenario 8: ISS Display Toggles — interactive UI state.
    - Scenario 9: Context Switch / Refresh with Shared Revision — interactive UI state.
  - Console Errors: 0
  - Page Errors: 0
- **5. Test Verification Summary**:
  - `pytest tests/test_iss_engine.py`: 35 passed in 1.08s.
  - `pytest tests/test_iss_dashboard_integration.py`: 15 passed in 1.15s.
  - `python tests/test_iss_browser_controlled.py`: All 9 scenarios passed.
  - Full offline suite (`pytest -m "not slow" -k "not browser"`): 330 passed, 1 deselected in 4.56s.

### ISS Milestone Acceptance Checkpoint (Accepted in HANDOFF-035 Review)
- **Status**: Formally ACCEPTED by Perplexity on 2026-11-05 for the bounded ISS dashboard scope.
- **Acceptance Scope & Evidence Boundaries**:
  1. Complete-state candle-driven integration verified across Scenarios 1–6 in Chromium browser with 0 console and 0 page errors.
  2. Isolated lifecycle tests (private-state mutation, scoped prerequisite withholding, injected presentation snapshots) are explicitly disclaimed as isolated tests—not complete-state candle-driven evidence.
  3. Non-reachability of `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY` in complete-state integration applies under the proven pullback inequalities ($C_2 < L_1 \le C_1$ for upward, $C_2 > H_1 \ge C_1$ for downward) with active Point 3 and complete provenance. The source-defined branch remains preserved in the codebase as a documented strategy limitation.
  4. CHOCH timing / identification-close question (`c1 == p2`) remains contained and unresolved.
  5. Missing-provenance execution is documented as blocked/unresolved and remains explicitly unsupported for authoritative integrated progression until a dedicated production guard is execution-tested.
- **Transition**: Proceed to TJL requirements and lifecycle acceptance on branch `requirements/tjl-acceptance` (strictly no activation, taps, or trade execution).

---

## 8. Milestone Acceptance: TJL Requirements & Acceptance Specifications (HANDOFF-037)
- **Accepted Milestone**: Trend Joining Level (TJL) Acceptance Specification & Fixture Validation (`HANDOFF-037`).
- **Accepted Commit Hash**: `859cf12ae11b2198a6306a183364860e84b82724`
- **Reviewer Status**: **ACCEPTED** by Perplexity on 2026-11-06 as the bounded TJL requirements baseline.
- **Key Baseline Requirements & Timing Precision**:
  1. **Timing Separation for Promoted Points**:
     - At $t_1$ (confirmation): point receives its TJL label and original-candle zone.
     - At $t_2$ (replacement): that point becomes a member of the new current eligible set.
     - A newly confirmed label must not bypass the $t_1 / t_2$ lifecycle.
  2. **Three Distinct Persistence & Provenance Cases**:
     - **Case A (Point Provenance Promotion)**: P3 promoted to a confirmed TJL point preserving point provenance (`tjl_07a`).
     - **Case B (Confirmed Member Persisting Across Replacement)**: Shared confirmed level ID preserved across set replacement (`tjl_07b`).
     - **Case C (Outgoing Cancellation Intent Applies to Outgoing Set)**: Outgoing cancellation intent applies to the entire outgoing set despite surviving member identity.
  3. **Usage Contracts Distinct from Implemented Behavior**:
     - Future usage preservation remains an external ledger contract. No usage ledger code exists or is claimed as implemented in this phase.
  4. **Historical Records vs. Epoch Eligibility**:
     - Retained `confirmed_pairs` are historical records. After CHOCH, the historical list is not cleared, but current-direction eligibility is determined strictly from the new structural epoch and its fresh prerequisites.
  5. **Stable Level ID Formula**:
     `(symbol_feed_id, source_timeframe, source_open_time, HIGH|LOW)`.
  6. **Independent Timelines**:
     - Bullish First Set Creation: `ENGINE_EURUSD_H1` (Bars 0–7).
     - Bearish Lifecycle ($t_0 \to t_1 \to t_2$): `ENGINE_GBPUSD_H1` (Bars 0–16).
- **Current Milestone**: Pure offline TJL labeling, geometry, and current-set lifecycle engine.
- **Active Branch**: `feature/tjl-engine` created from `859cf12ae11b2198a6306a183364860e84b82724`.
- **Scope Boundaries**: Strictly zero UI, taps, activation engine, usage ledger, arbitration, entry signals, or order execution. Zero merging into `main`.

---

## 9. Trend Joining Level (TJL) Pure Offline Engine Implementation (HANDOFF-040)
- **Implemented Subsystem**: Pure offline TJL labeling, geometry calculation, and current-set lifecycle engine (`src/aladeen/strategy/tjl_types.py`, `src/aladeen/strategy/tjl_reducer.py`, `src/aladeen/strategy/tjl_coordinator.py`, `docs/architecture/tjl-engine.md`).
- **Core Architecture & Review Hardening**:
  1. **Source-ID and Epoch Independence**:
     - Removed all numeric bar-index ordering/inequality assumptions (`<= _last_choch_bar_index`).
     - Structural epochs are explicitly tracked via `structural_epoch: int` and chronological UTC confirmation timestamps (`confirmed_time > _last_choch_time` / `conf_time > last_choch_open_time`).
     - Arbitrary string or strictly decreasing numeric IDs (`500 -> 400 -> 300 -> 200` and `900 -> 890 -> 880...`) verified end-to-end.
  2. **Actual Post-CHOCH Recovery Evidence**:
     - Verified pure candle-driven recovery: `Set 1 (Bullish) -> CHOCH Invalidation (epoch 0 to 1, Set 1 cancelled, post-CHOCH gap with 0 active sets) -> Bearish Pair Confirmed (Bar 14) -> Set 2 First Creation (Bar 16)`.
     - 2 historical sets preserved in audit log with distinct epoch provenance.
  3. **Atomic Transaction Staging & Failure Rollback**:
     - All sequential candle processing stages state changes across local copies of the underlying `MSMChochCoordinator`, `TJLReducer`, and candle lookup dictionary.
     - Failure injection between coordinator advance and reducer commit leaves coordinator and reducer completely unmutated; immediate valid retry succeeds cleanly.
  4. **Physical Level vs Contextual Role Separation**:
     - `PhysicalLevel`: immutable physical boundary geometry keyed by `StableLevelId`.
     - `TJLZone`: contextual directional role assignment (`TJL1`, `TJL2_A_PLUS`). Conflicting physical geometries for identical level IDs are rejected fail-closed.
  5. **Exact Zero-Width Lines & Availability Preservation**:
     - Zero-width lines require exact price equality (`lower_price == upper_price`), rejecting tolerances or `math.isclose`.
     - Missing candle close times strictly preserve `availability_time = None`, never substituted by `open_time`.
  6. **Clean Cancellation Containment**:
     - `outgoing_cancelled_set_id` and `outgoing_cancelled_fingerprint` explicitly identify cancelled sets.
     - Unresolved and idempotent no-op receipts do NOT leak or re-emit stale cancellation intent.
- **Verification Summary**:
  - Full TJL suite: 43/43 tests passing in 0.70s.
  - Full repository offline suite: 373/373 tests passing in 14.35s (0 failures, 1 deselected).
- **Scope Compliance**: Strictly offline calculations. Zero UI, zero tap tracking, zero activation engine, zero usage ledger, zero order execution, and zero merging to `main`.

---

## 10. Authoritative Epoch Provenance & Test Verification Hardening (HANDOFF-041)
- **Repository Provenance Clarification**:
  - **Immediate Git Parent**: `a44682a09c3fbf343c82dbabcc7e6287821b7049` (HANDOFF-040 commit on `feature/tjl-engine`).
  - **Accepted Requirements Baseline**: `859cf12ae11b2198a6306a183364860e84b82724` (`HANDOFF-037`).
- **Core Hardening Implementation**:
  1. **Authoritative Event/Epoch Provenance (Directive 1)**:
     - Replaced timestamp fallback inference with strictly monotonic chronological event positions in completed candles sequence (`pair_conf_pos > latest_choch.c2_chronological_pos`).
     - Zero reliance on numeric source ID order, zero dependence on `close_time`, and zero conflation between `open_time` and `close_time`.
     - Explicit `structural_epoch: int` passed in `TJLStructuralObservation` and verified fail-closed in `TJLReducer`.
     - Permitted legitimate pre-CHOCH source origins in new-epoch points (e.g. restart reference candle 5) while enforcing that the pair confirmation event postdates CHOCH.
  2. **Complete Point Validation (Directive 2)**:
     - Replaced `math.isclose` with strict price equality (`point.price == expected_body_edge`).
     - Required confirmed status on `ch_point` and `cl_point`, tentative status on `tentative_p3`.
     - Validated lookup key matching contained candle index, structural price hierarchy (`ch_point.price > cl_point.price`), and rejected any future provenance relative to observation horizon.
  3. **Full Prefix Assertions on Actual CHOCH Recovery (Directive 3)**:
     - Asserted every significant prefix (0–16): Bullish Set 1 creation at 7, retention at 8, CHOCH invalidation and explicit outgoing Set 1 at 9, gap periods at 10–13 with no active set, labels only at 14, idempotent no-op at 15, and Bearish Set 2 first creation at 16.
  4. **Decreasing Unique Source IDs for Full Sequence (Directive 4)**:
     - Verified complete 17-candle recovery sequence with strictly decreasing IDs (`900, 890, 880... 740`).
     - Semantic equivalence proven via source-time mapping.
  5. **Full Prefix Consistency Across APIs (Directive 5)**:
     - Verified identical snapshots across `process_candles` (fresh batch), `process_candle` (sequential), and `replay_candles` at every prefix $k \in [0..N]$ across continuation replacement (`tjl_06`) and CHOCH recovery (`tjl_09`), under both known and unknown close availability (`close_time=None`).
  6. **Complete-State Failure Injection Comparison (Directive 6)**:
     - Compared complete underlying coordinator snapshot, reducer snapshot, candle lookup, CHOCH count, and epoch state before vs after failed injection.
     - Verified recovered coordinator matches an independent clean reference run identically.
- **Verification Summary**:
  - Full TJL suite: 44/44 tests passing in 0.82s.
  - Full repository offline suite: 374/374 tests passing in 5.77s (0 failures, 1 deselected).
- **Scope Compliance**: Strictly offline calculations. Zero UI, zero tap tracking, zero activation engine, zero usage ledger, zero order execution, and zero merging to `main`.

---

## 11. Reducer Event-Provenance Contract & Targeted Regressions (HANDOFF-042)
- **Repository Provenance**:
  - **Branch**: `feature/tjl-engine`
  - **Immediate Git Parent**: `fb8db8382365ab159ceed8f7a42f013ef9056015` (HANDOFF-041)
  - **Accepted Requirements Baseline**: `859cf12ae11b2198a6306a183364860e84b82724` (`HANDOFF-037`)
- **Core Hardening Implementation**:
  1. **Public Reducer Event-Provenance Contract (Directive 1)**:
     - Extended `TJLStructuralObservation` with explicit monotonic event positions:
       - `observation_event_pos: int = 0`
       - `epoch_choch_event_pos: Optional[int] = None`
       - `pair_confirmation_event_pos: Optional[int] = None`
       - `p3_identification_event_pos: Optional[int] = None`
     - Validated fail-closed in `TJLReducer.reduce()`:
       - Confirmed points require explicit `pair_confirmation_event_pos <= observation_event_pos`.
       - Tentative P3 requires explicit `p3_identification_event_pos <= observation_event_pos`.
       - In post-CHOCH epochs (`structural_epoch > 0`), requires explicit `epoch_choch_event_pos == self._epoch_choch_event_pos`.
       - Rejects stale points (`pair_confirmation_event_pos <= epoch_choch_event_pos`) and stale P3 (`p3_identification_event_pos <= epoch_choch_event_pos`) fail-closed without mutating state, regardless of timestamp presence.
     - Preserved separation between event ordering and close availability (unknown availability preserved as `None`).
     - Removed `availability_time -> candle_open_time` fallback from CHOCH event timestamp recording.
  2. **Coordinator Integration (Directive 2)**:
     - `TJLCoordinator` populates all 4 event positions directly from accepted completed candle indexes and confirmed CHOCH / MSM event history.
     - Preserves legitimate pre-CHOCH source candles (e.g. restart reference candle 5) when their confirmation event postdates CHOCH.
  3. **Targeted Reducer Regressions (Directive 3 — 6/6 passing)**:
     - `test_current_epoch_envelope_stale_points_confirmed_time_none_rejected`: Stale points with `confirmed_time=None` rejected without mutation.
     - `test_current_epoch_envelope_stale_p3_identification_rejected`: Stale P3 identification rejected without mutation.
     - `test_event_positions_beyond_observation_rejected`: Event positions in future relative to observation rejected without mutation.
     - `test_valid_new_epoch_confirmation_of_pre_choch_source_candle_accepted`: Accepted cleanly with correct geometry and zone roles.
     - `test_valid_event_ordering_with_all_close_availability_unknown_accepted`: Accepted cleanly; preserves `eligibility_available_time=None`.
     - `test_decreasing_unique_source_ids_with_unknown_availability_and_pre_choch_source`: Decreasing source IDs (`900, 800... 100`) verified with unknown availability.
  4. **Scope & Model Hierarchy Corrections (Directive 4)**:
     - Removed unauthorized unconditional `ch_point.price > cl_point.price` check from `TJLStructuralObservation.__post_init__`.
     - Clarified docstrings that `SwingPoint` carries no internal point-kind enum; CH/CL slots are validated against exact candle body edges and confirmation status.
  5. **Evidence Categorization & Limitations (Directive 6)**:
     - *Batch/Sequential/Replay Consistency*: Validated for continuation replacement (`tjl_06`) and CHOCH recovery (`tjl_09`) under known and unknown availability across all prefixes.
     - *Monday / Weekly Fixtures*: Marked as specification-level assertions; external usage ledger is not claimed as implemented in this phase.
     - *Rollback Coverage*: Complete internal state rollback verified for post-coordinator-advance failure injection.
- **Verification Summary**:
  - Full TJL suite: 50/50 tests passing in 0.80s.
  - Full repository offline suite: 380/380 tests passing in 5.84s (0 failures, 1 deselected).
- **Scope Compliance**: Pure offline TJL calculation. Strictly zero UI, zero chart overlays, zero taps, zero activation engine, zero usage ledger, zero signals, zero order execution, and zero merging to `main`.

---

## 12. Monotonic Observation Positions, Reset Provenance & State Invariants (HANDOFF-043)
- **Repository Provenance**:
  - **Branch**: `feature/tjl-engine`
  - **Immediate Git Parent**: `21b431a832acd0cdaf15bccc39c7c2bdf44ccc9c` (HANDOFF-042)
  - **Accepted Requirements Baseline**: `859cf12ae11b2198a6306a183364860e84b82724` (`HANDOFF-037`)
- **Core Hardening Implementation**:
  1. **Strictly Increasing Observation Positions (Directive 1)**:
     - Added `self._last_received_event_pos: Optional[int] = None` to `TJLReducer`.
     - In `TJLReducer.reduce()`, strictly enforces `observation.observation_event_pos > self._last_received_event_pos` fail-closed.
     - Rejects repeated and decreasing event positions even when `candle_open_time` increases.
     - Allows gaps without requiring strictly consecutive integers or increasing source candle IDs.
     - Unresolved receipts advance `_last_received_event_pos` alongside receipt index and timestamp without mutating live state.
     - Rejection occurs before any mutation, preserving position, timestamp, and structural epoch state.
  2. **Complete Event-Provenance Reset (Directive 2)**:
     - In `TJLReducer.reset()`, comprehensively clears all provenance state: `_epoch_choch_event_pos = None`, `_last_received_event_pos = None`, `_last_choch_time = None`, `_last_choch_c2_index = None`, `_last_choch_event_time = None`, `_structural_epoch = 0`.
     - Reused reducer matches a brand-new instance identically.
  3. **Focused Ordering & State Regressions (Directive 3 — 8/8 passing)**:
     - `test_repeated_observation_event_pos_rejected_with_later_timestamp`: Repeated position rejected fail-closed without mutation.
     - `test_decreasing_observation_event_pos_rejected_with_later_timestamp`: Decreasing position rejected fail-closed without mutation.
     - `test_backward_position_choch_rejected_without_epoch_boundary_mutation`: Backward-position CHOCH rejected without moving epoch boundary or incrementing epoch.
     - `test_valid_observation_event_pos_gaps_accepted`: Gaps in positions accepted cleanly when strictly increasing.
     - `test_unresolved_receipt_advances_received_order_metadata_only`: Advances received-order metadata only; preserves `last_processed_index`.
     - `test_reset_clears_all_provenance_and_matches_fresh_reference`: Fully clears state and matches fresh reference on reuse.
     - `test_forming_bar_leaves_completed_candle_state_unchanged`: Coordinator preserves completed-candle snapshot 100% on forming bar delivery.
     - `test_fresh_batch_failure_preserves_previous_live_state`: Process-candles fresh batch failure preserves live state 100% untouched.
  4. **Trust Boundary Documentation (Directive 4)**:
     - Documented in `TJLReducer` class docstrings and architecture notes: Explicit event positions in `TJLStructuralObservation` are validated input parameters. The candle coordinator derives them directly from authoritative MSM/CHOCH event history; the standalone reducer enforces internal consistency rules, not cryptographic proof against fabricated-yet-consistent synthetic metadata.
- **Verification Summary**:
  - Full TJL suite: 58/58 tests passing in 0.82s.
  - Full repository offline suite: 388/388 tests passing in 5.90s (0 failures, 1 deselected).
- **Scope Compliance**: Pure offline TJL calculations. Strictly zero UI, zero chart overlays, zero taps, zero activation engine, zero usage ledger, zero signals, zero order execution, and zero merging to `main`.

