# Development & Review Status — Aladeen / TopG

Last Updated: 2026-11-06 (Activation Engine Pure Offline Milestone Accepted — HANDOFF-061 Baseline)

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
- **Reviewer Status**: **ACCEPTED** by Perplexity for the bounded offline TJL strategy engine milestone.
- **Accepted Commit Hash**: `5b46185853075b45f18d618dd385ce853dddcfc8`
- **Recorded Evidence Boundaries & Qualifications**:
  1. *Provenance Trust Boundary*: Standalone reducer validates internal consistency of supplied metadata (strictly increasing event positions, structural epoch match, horizon limits, exact body edges); candle coordinator derives authoritative event positions directly from underlying completed candle and MSM/CHOCH event history.
  2. *Specification vs Implementation Evidence*: Monday / weekly fixture assertions remain specification-level validation; no live calendar or external usage ledger subsystem is implemented in this phase.
  3. *Batch Failure Scope*: Fresh-batch test verifies preservation of the exposed TJL snapshot upon invalid input without corrupting prior state.
  4. *Unresolved Receipt Semantics*: Unresolved receipts leave authoritative calculation state frozen, but update received-position metadata and diagnostics.
  5. *Strategy Limitations*: Existing CHOCH identification-close ($c_1 == p_2$) and ISS reconciliation limitations remain unchanged.
- **Scope Compliance**: Pure offline TJL calculations. Strictly zero UI, zero chart overlays, zero taps, zero activation engine, zero usage ledger, zero signals, zero order execution, and zero merging to `main`.

---

## 14. Milestone Implementation & Verification: Read-Only TJL Dashboard Integration Hardening (HANDOFF-046)
- **Active Branch**: `feature/tjl-dashboard`
- **Parent Commit**: `3c31e9584d3ec572afa884f0a42a0e37f8c6c363` (HANDOFF-045)
- **Objective**: Harden read-only TJL dashboard historical set presentation, chart boundary semantics under unresolved ambiguity, same-run CHOCH recovery, and executed unresolved browser verification addressing all review directives from HANDOFF-045.
- **Scope Boundary**: Pure read-only dashboard presentation. Strictly zero UI order execution, zero MT5 trading calls, zero zone activations, zero usage ledger, zero tap tracking, zero trade entry signals, zero automated trading, and zero merging into `main`.
- **Delivered Implementations (Per Review Directives)**:
  1. **Historical Sets Filtering & Presentation (`src/aladeen/ui/tjl_chart.py`)**:
     - *Exclusion of Active Set*: Current eligible set is strictly excluded by identity (`curr_set is not None and h_set.set_id == curr_set.set_id`), preventing duplicate shapes/markers.
     - *Lifecycle Termination Filtering*: Only sets with an actual outgoing replacement or CHOCH invalidation record (`outgoing_cancelled_set_id == h_set.set_id`) are rendered as historical.
     - *Unknown Termination Handling*: If termination timestamp is `None`, never falls back to chart end as eligibility interval; omits time-extended shape and renders compact source-reference marker labeled `[Historical Structural Set — Superseded by Replacement — Termination Timestamp Unknown]`.
  2. **Unresolved Chart Boundaries (`src/aladeen/ui/tjl_chart.py`, `src/aladeen/ui/chart.py`)**:
     - When `tjl_snap.is_unresolved` is True, current set eligibility shape `x1` is bounded at `df.index[tjl_snap.last_processed_index]`, never extending across unresolved receipts to `last_chart_time`.
     - Hover tooltips and traces prominently labeled `[Last Authoritative Evidence — Frozen Pending Resolution]`.
     - Hardened `chart.py` and callbacks to safely handle diagnostic objects or strings.
  3. **Coordinator Observation Event Position Monotonicity (`src/aladeen/strategy/tjl_coordinator.py`)**:
     - Corrected observation event position calculation in `TJLCoordinator` to use `len(candle_lookup_copy) - 1`, ensuring strictly increasing observation event positions across all ingested completed candles even when underlying MSM/CHOCH coordinator freezes authoritative progress during an unresolved ambiguity.
  4. **Focused Presentation Regressions Added (`tests/test_tjl_dashboard_integration.py`)**:
     - `test_one_current_set_produces_no_historical_duplicate`: Asserts 0 historical shapes or traces when only SET_1 is active.
     - `test_after_replacement_only_outgoing_set1_is_historical`: Asserts only outgoing SET_1 receives historical shapes/traces; SET_2 is strictly current.
     - `test_current_off_historical_on_hides_current_set2`: Asserts toggling current set OFF and historical ON renders SET_1 while suppressing SET_2.
     - `test_known_start_unknown_cancellation_produces_no_misleading_interval`: Asserts unknown cancellation timestamp omits time-extended historical shape.
     - `test_unresolved_retained_set_not_displayed_as_fresh_current_eligibility`: Asserts unresolved current set shape bounds at `last_processed_index` (#8) rather than latest chart time (#9) and carries freeze warning tooltip.
     - **Result**: 25/25 passed in 1.48s.
  5. **Deterministic Browser Controlled Verification Suite (`tests/test_tjl_browser_controlled.py`)**:
     - Expanded to 11 deterministic scenarios in real Chromium via Playwright:
       - Scenario 1: Bullish First Set Creation (`EURUSD / H1`).
       - Scenario 2: Continuation t1 Retention (`EURUSD / M1`).
       - Scenario 3: Pullback t2 Replacement (`GBPUSD / H1`).
       - Scenario 4: **Same-Run CHOCH Invalidation & Recovery (`EURUSD / H4`, 17 candles)**:
         - Same fixture history running through CHOCH and recovery.
         - `SET_1` invalidated via `CHOCH_INVALIDATION`, gap passed, direction reverses to `DOWNWARD` (Epoch 1), and new `SET_2` is qualified.
         - Verified `SET_2` active shapes and bounded `SET_1` historical shapes on Plotly chart.
       - Scenario 5: Standalone Bearish First Creation (`GBPUSD / H4`).
       - Scenario 6: Unknown Availability (`GBPUSD / M5`, stripped close times) -> updated wording `"Unknown (Availability timestamp unknown — no retroactive eligible interval plotted)"`.
       - Scenario 7: Labels-Only Prefix (`EURUSD / M5`).
       - Scenario 8: Unapplied Draft Edits Guard.
       - Scenario 9: Display Toggles Independence.
       - Scenario 10: **Executed Unresolved Ambiguity (`EURUSD / D1`, $c_1 == p_2$ boundary)**:
         - Simultaneous close freezes authoritative state at bar #6 while input is received through bar #9.
         - Prominent status badge: `UNRESOLVED AMBIGUITY (LAST AUTHORITATIVE EVIDENCE)`.
         - Non-green edit status and chart title warning banner.
       - Scenario 11: Comprehensive Error Accounting:
         - Total raw console messages logged: 32.
         - Total console error-level messages: 0.
         - Itemized environmental exclusions (favicon 404): 0.
         - Total actionable console errors: 0.
         - Total page errors (uncaught JS exceptions): 0.
     - **Result**: 1/1 passed in 63.79s with **0 actionable console errors and 0 page errors**.
- **Verification Summary**:
  - Full TJL dashboard integration suite: 25/25 passed in 1.48s (`pytest tests/test_tjl_dashboard_integration.py -v`).
  - Controlled browser verification suite: 1/1 passed in 63.79s (`pytest tests/test_tjl_browser_controlled.py -s -v`).
  - Full offline repository test suite: 413/413 passed in 10.75s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Recorded Evidence Boundaries**:
  1. *Presentation Only*: Pure read-only dashboard presentation. Zero UI order execution, zero MT5 trading calls, zero account modification.
  2. *Non-Execution Invariant*: All hover tooltips, status banners, and inspection tables explicitly display `[Structural Set Only — Downstream activation/ledger not present]`.
  3. *Downstream Engine Absence*: Zero zone activation logic, zero usage accounting/ledger, zero tap tracking, zero trade entry signals.
  4. *Adapter Disclosure*: Deterministic mock adapter clearly documented as simulating broker-connected state.
  5. *Branch Boundary*: All work committed strictly on `feature/tjl-dashboard`. No merging into `main`.


---

## 15. Milestone Implementation & Verification: TJL Endpoint Resolution, Lifecycle Classification & Focused Presentation Regressions (HANDOFF-047)
- **Active Branch**: `feature/tjl-dashboard`
- **Reviewer Status**: **ACCEPTED** by Perplexity for the bounded read-only TJL dashboard milestone at commit `535af1434ed9a6b93328202039db7f1d4f4be410`.
- **Recorded Acceptance Boundaries & Evidence Qualifications**:
  1. *Isolated Presentation Regressions*: Several unresolved-coordinate tests use `dataclasses.replace()` to inject unresolved snapshot fields; they are isolated presentation regressions built on production-calculated data, not candle-driven demonstrations of the unresolved lifecycle.
  2. *Windowed Chart Boundary*: The windowed-chart test directly verifies endpoint resolution across excluded rows; it is not a complete windowed-rendering lifecycle test.
  3. *Adapter Characterization*: Browser verification uses a deterministic mock data adapter and real browser/application calculations; it does not establish native MT5 calendar or live-feed correctness.
  4. *Browser Test Structure*: Reported as 1 pytest test containing 11 scenario sections.
  5. *Unresolved Core Limitations*: Existing CHOCH identification-close ($c_1 == p_2$) and ISS reconciliation limitations remain unresolved; dashboard acceptance does not settle them.
  6. *Engine / Dashboard Stability*: No further TJL engine or dashboard rewrite is requested.
- **Parent Commit**: `bab21d8b2f944d50a68b6af646fec8c7b5489600` (HANDOFF-046)
- **Objective**: Harden authoritative endpoint resolution via explicit source ID mapping, decouple lifecycle classification from visibility toggles, preserve contextual roles across transitions, and add comprehensive presentation regression tests.
- **Commit Provenance Clarification**: The commit hash submitted for HANDOFF-046 in the submission text contained a string typo (`bab21d8b671a53b516dae9dfdb34570d5eb645ef`), which failed remote resolution. The actual verified git commit on `origin/feature/tjl-dashboard` is `bab21d8b2f944d50a68b6af646fec8c7b5489600`.
- **Scope Boundary**: Pure read-only dashboard presentation. Strictly zero UI order execution, zero MT5 trading calls, zero zone activations, zero usage ledger, zero tap tracking, zero trade entry signals, zero automated trading, and zero merging into `main`.
- **Delivered Implementations (Per Review Directives)**:
  1. **Authoritative Endpoint Resolution via Explicit Source ID Mapping (`src/aladeen/ui/tjl_chart.py`, `src/aladeen/ui/chart.py`)**:
     - Excised all usage of `df.index[last_processed_index]`. `last_processed_index` is treated strictly as an external source candle identifier, not a DataFrame row offset.
     - Implemented `resolve_authoritative_endpoint(df, msm_result, last_processed_index)`:
       - First inspects calculation output `msm_result.candles` by explicit candle `index` equality.
       - Falls back to `df['index'] == last_processed_index` in DataFrame view.
       - Correctly extracts `open_time` and `close_time` without IndexError or row mismatch across arbitrary, sparse, or decreasing source IDs.
     - Handles windowed DataFrame subsets where the authoritative source candle is excluded from the visible chart slice.
     - If the authoritative temporal endpoint cannot be established or is invalid/missing (`last_processed_index < 0` or unresolvable ID), time-extended shapes are omitted and a compact source reference marker is rendered at `source_candle_open_time` labeled `[Authoritative Endpoint Unavailable]`. It never fabricates an interval or defaults to `last_chart_time`.
  2. **Unconditional Lifecycle Classification Decoupled from Display Toggles (`src/aladeen/ui/tjl_chart.py`)**:
     - Pre-computes `curr_role_level_ids`, `hist_role_level_ids`, `historical_entries`, and `labels_only_zones` unconditionally before gating by display toggles (`show_tjl_zones`, `show_tjl_current_set`, `show_tjl_historical_sets`, `show_tjl_labels`).
     - Display toggles strictly suppress traces/shapes from the layout without reclassifying underlying data or mutating state.
     - Setting `show_tjl_historical_sets=False` does not resurrect cancelled historical levels as amber "Awaiting Set Formation" labels.
     - Contextual role distinctions `(level_id, label)` are preserved so physical identity alone does not erase a legitimate new role or mark an old role as current.
  3. **7 Focused Presentation Regression Tests (`tests/test_tjl_dashboard_integration.py`)**:
     - `test_unresolved_retained_set_decreasing_source_ids`: Decreasing source IDs (950 down to 880) resolve via explicit candle ID, never `df.index[id]`, with exact coordinate assertions.
     - `test_unresolved_retained_set_sparse_ids_matching_dataframe_positions`: Sparse source IDs (0, 10, ..., 80) resolve by ID (70), not row position (70 vs 7).
     - `test_chart_window_excluding_authoritative_source_candle`: Windowed display excluding source candle resolves via `msm_result.candles`.
     - `test_missing_authoritative_endpoint_produces_source_reference_not_fabricated_interval`: Invalid ID (9999) produces source-reference presentation, not fabricated interval.
     - `test_historical_off_labels_on_does_not_resurrect_cancelled_levels`: Historical OFF + Labels ON does not resurrect cancelled levels.
     - `test_current_off_historical_on_does_not_reveal_active_set`: Current OFF + Historical ON suppresses active SET_2 without leaking it into historical traces.
     - `test_cross_direction_contextual_roles_correctly_classified`: Contextual roles across directions/epochs are classified independently without physical identity collision.
  4. **Preserved 11 Deterministic Controlled Browser Scenarios (`tests/test_tjl_browser_controlled.py`)**:
     - Preserved all 11 scenarios in Chromium via Playwright, including Scenario 4 (same-run CHOCH invalidation and recovery), Scenario 10 (executed unresolved ambiguity $c_1 == p_2$ boundary), and Scenario 11 (comprehensive error accounting).
     - **Result**: 11/11 passed in 63.36s with **0 actionable console errors and 0 page errors**.
- **Verification Summary**:
  - Full TJL dashboard integration suite: 32/32 passed in 2.90s (`pytest tests/test_tjl_dashboard_integration.py -v`).
  - Controlled browser verification suite: 1/1 passed in 63.36s (`pytest tests/test_tjl_browser_controlled.py -s -v`).
  - Full offline repository test suite: 420/420 passed in 12.20s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Recorded Evidence Boundaries**:
  1. *Presentation Only*: Pure read-only dashboard presentation. Zero UI order execution, zero MT5 trading calls, zero account modification.
  2. *Non-Execution Invariant*: All hover tooltips, status banners, and inspection tables explicitly display `[Structural Set Only — Downstream activation/ledger not present]`.
  3. *Downstream Engine Absence*: Zero zone activation logic, zero usage accounting/ledger, zero tap tracking, zero trade entry signals.
  4. *Adapter Disclosure*: Deterministic mock adapter clearly documented as simulating broker-connected state.
  5. *Branch Boundary*: All work committed strictly on `feature/tjl-dashboard`. No merging into `main`.


---

## 16. Milestone Acceptance: Tap / Activation Acceptance Requirements & Deterministic Acceptance Fixtures (HANDOFF-048, HANDOFF-049, & HANDOFF-050)
- **Accepted Milestone**: Tap and Zone Activation Acceptance Requirements & Machine-Readable Acceptance Fixtures.
- **Accepted Commit Hash**: `447242983fc3e8589bd9d0575676de92d2d61493`
- **Reviewer Status**: **ACCEPTED** by Perplexity as the bounded activation requirements baseline for an exact-observed-print engine.
- **Accepted Baseline Specifications & Fixtures**:
  1. **Acceptance Specification (`docs/requirements/activation-acceptance.md`)**:
     - Cites exact authoritative source sections (`MTF-Analysis.pdf` §3, §5, §6, §8, §9, §10, §12) and user approvals (`OPEN-03`, `OPEN-04`, `OPEN-05`, `OPEN-06`, `OPEN-08`, `OPEN-09`, `OPEN-10`, `OPEN-12`) from [`docs/requirements/approved-clarifications.md`](../requirements/approved-clarifications.md).
     - Excised range-overlap-as-touch predicate; requires an actual observed price print $p$ satisfying $\text{lower} \le p \le \text{upper}$ on the single configured price basis (`OPEN-06`). Documents what OHLC proves, what it does not prove, and blocked evidence categories (`NO_OBSERVED_TOUCH`, `UNKNOWN_ORDER`, `UNKNOWN_COVERAGE`).
     - Hardened OHLC temporal semantics (`OPEN-04`): Candle interval is strictly half-open $[t_{\text{open}}, t_{\text{close}})$, where $t_{\text{close}}$ is the record availability boundary. A candle's close price belongs to the completed candle interval; it does not prove a print at $t_{\text{close}}$. A level becoming available at $t_{\text{close}}$ cannot claim the preceding candle's close price as a post-availability touch. Independent post-availability evidence is required.
     - Formal discrete evidence schema: defines typed machine schemas for `ExactPricePrint`, `IntervalBoundedCandleEvidence`, and `CommitOrCancellationEvent`.
     - Corrected rearming semantics (`OPEN-05`): specifies both Path A (cancelled while inside: requires subsequent outside print $p < L$ or $p > U$ followed by fresh touch) and Path B (cancelled while already outside: arms immediately for next touch without requiring extra departure). Within-bar departure and retouch requires proven causal sequence index; otherwise blocked as `UNKNOWN_ORDER`. Lingering inside strictly blocks rearming.
     - Separated terminal activation identity from persistent physical level identity: an outgoing activation is terminal and cannot revive; but an unused physical level surviving into a replacement set (t2) retains its `StableLevelId` and requires an independent fresh touch under the new set (zero activation inheritance).
     - Scoped arbitration tie-breakers: TJL2 / A+ precedence applies strictly between competing levels from the same source timeframe.
     - Permitted independent concurrent pending activations for both `tjl1_zone` and `tjl2_zone` on an active set.
     - Clarified that at continuation t1, the existing current set remains eligible while next labels in `all_labeled_zones` are ineligible.
     - Event sequencing at coarse timestamp $T$ (`OPEN-12`): winning commit finalizes first (`seq(commit) < seq(rearm)`). Recycled evidence strictly rejected. Distinct simultaneous reactivations receive distinct deterministic IDs.
  2. **Expanded Machine-Readable Acceptance Fixtures (`tests/fixtures/activation_acceptance.json`)**:
     - 26 deterministic fixture categories covering all approved rules and edge boundaries:
       - `act_01_known_availability_first_touch`: Valid discrete print in $[L, U]$ at $t \ge t_{\text{avail}}$ transitions level to `PENDING_ACTIVATION` and maps confirmation timeframe (H1 -> M1).
       - `act_01b_both_tjl1_and_tjl2_pending_independently`: Both members of active current set hold pending activations concurrently.
       - `act_01c_all_three_timeframe_mappings`: Verifies D1 -> H1, H4 -> M5, and H1 -> M1 mappings.
       - `act_01d_t1_retention_current_set_eligible_labels_ineligible`: At t1, old current set remains eligible; next labels are ineligible.
       - `act_02_unknown_availability_blocks_activation`: Null availability blocks activation evidence while preserving structural membership.
       - `act_02b_unknown_usage_evidence_blocks`: Uncertain usage evidence blocks activation (fail-closed).
       - `act_03_no_retroactive_wick_claim`: Pre-availability wick touch in $[open, avail)$ rejected; only post-availability touch activates (`OPEN-04`).
       - `act_03b_intra_candle_availability_known_vs_unknown`: Known sub-bar ordering activates; unknown intra-bar ordering blocks as `UNKNOWN_ORDER`.
       - `act_03c_level_available_at_close_prior_close_cannot_activate`: Level available at candle close boundary $T_{\text{close}}$; preceding candle close price inside zone does NOT prove print at boundary; independent post-availability print required (`OPEN-04`).
       - `act_03d_independent_print_at_availability_activates`: Independent discrete print observed at or after availability timestamp cleanly activates (`OPEN-04`, `OPEN-06`).
       - `act_03e_inside_candle_availability_unknown_sequence_blocks`: Availability begins intra-candle; unknown sequence relative to completed candle close blocks as `UNKNOWN_ORDER` (`OPEN-04`).
       - `act_04_straddling_range_without_observed_print`: Range straddling zone without discrete print inside rejected as `NO_OBSERVED_TOUCH` (zero path interpolation, `OPEN-06`).
       - `act_04b_inclusive_boundary_and_zero_width_line`: Exact boundary touches and zero-width lines successfully activate.
       - `act_05_repeated_observations_no_reset`: Secondary/tertiary touches while pending do not reset `first_touch_time` or restart search.
       - `act_06_source_choch_cancellation`: Source main CHOCH immediately cancels pending activation with `rearm_eligible = False`.
       - `act_07_source_t2_replacement_cancellation`: Pullback t2 replacement cancels SET_1 activation; new SET_2 requires independent touch.
       - `act_07b_persistent_member_survives_into_replacement_set`: Persistent physical level survives into SET_2; no activation inheritance; requires fresh touch.
       - `act_08a_already_outside_cancellation_rearm`: Price observed outside at cancellation arms immediately; next touch rearms (OPEN-05 Path B).
       - `act_08b_lingering_inside_blocks_rearm`: Lingering inside without departure blocks rearming (OPEN-05 Path A).
       - `act_08c_outside_print_then_inside_print_within_candle_known_sequence`: Within-candle departure then retouch with known causal sequence permits rearming (`OPEN-05`).
       - `act_08d_outside_and_inside_prices_within_candle_unknown_sequence`: Outside and inside prices within candle with unknown sequence blocks rearming (`OPEN-05`).
       - `act_09a_coarse_timestamp_rearm_after_commit`: Later event at coarse timestamp $T$ rearms only *after* winning commit finalizes (OPEN-12).
       - `act_09b_pre_commit_event_recycled_tap_rejected`: Pre-commit event and recycled tap rejected (OPEN-12).
       - `act_09c_incomplete_batch_unknown_coverage_blocks`: Incomplete batch or unknown coverage blocks activation transitions.
       - `act_09d_two_reactivations_at_same_coarse_timestamp`: Two distinct reactivations at same coarse timestamp receive distinct IDs and use zero recycled evidence (`OPEN-12`).
       - `act_10_run_isolation_and_replay_idempotence`: Engine configuration isolation (`OPEN-08`) and idempotent replay consistency (`OPEN-09`).
  3. **Automated Fixture Integrity Suite (`tests/test_activation_fixture_integrity.py`)**:
     - 28 comprehensive unit tests independently validating timestamps, finite positive prices, geometric bounds, half-open intervals, discrete observed prints, cancellation rules, rearming paths, coarse timestamp sequencing, and replay determinism.
- **Verification Summary**:
  - Activation fixture integrity suite: 28/28 passed in 0.63s (`pytest tests/test_activation_fixture_integrity.py -v`).
  - Full offline repository test suite: 448/448 passed in 12.30s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Requirements Only*: Zero activation engine, zero usage ledger, zero arbitration logic, zero trade entry signals, zero order execution.
  2. *No Price-Path Invention*: Discrete candle wicks evaluated strictly within declared timestamps; no speculative tick paths inferred.
  3. *Unresolved Core Ambiguities*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `requirements/activation-acceptance`. No merging into `main`.

---

## 18. Milestone Implementation Hardening: Pure Offline Activation Lifecycle Engine (HANDOFF-053)
- **Active Branch**: `feature/activation-engine`
- **Parent Commit**: `cb8d250816674ae375742e80e04f9cc9fd58cc55` (HANDOFF-052)
- **Objective**: Complete transaction safety, history continuity, single-event envelope preservation, member immutability, and rearm controller separation per Perplexity HANDOFF-052 review.
- **Scope Boundary**: Pure offline strategy calculation. **Strictly zero UI order execution, zero MT5 trading calls, zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals, zero automated trading, and zero merging to `main`**.
- **Completed Hardening Deliverables**:
  1. **Transactional TJL Synchronization**:
     - `TJLSynchronizer.sync()` now executes as a staged transaction spanning: engine state, explicit cursor, usage cache, and consumed transition fingerprints.
     - Captures pre-sync checkpoints of all 4 state components.
     - Commits only after the entire synchronization (cancellations and member registrations) succeeds completely.
     - Full rollback across all 4 components if any step fails (e.g. member validation failure), verified by failure injection.
  2. **Source Context Binding & Consumed History Continuity**:
     - `TJLSynchronizer` binds strictly to its source engine (`source_engine_id`), symbol (`symbol_feed_id`), and timeframe (`source_timeframe`). Cross-engine, cross-symbol, and cross-timeframe snapshots are strictly rejected before any state mutation.
     - Validates that the already-consumed prefix in `snapshot.transition_history` matches `_consumed_transition_fingerprints` bit-for-bit. Rewritten histories or cross-run snapshots are strictly rejected (`InvalidEvidenceError`).
     - Repeated synchronization is idempotent and preserves cursor and snapshots without redundant execution.
  3. **Transactional Single-Event Processing (Unconsumed Envelope on Failure)**:
     - `ActivationEngine.process_event` executes under an engine checkpoint.
     - If event processing fails (e.g. member context or geometry validation failure in `_process_register_members_event`), the engine state is 100% restored.
     - The event envelope, event ID, sequence number, and timestamp are left completely unconsumed.
     - A corrected retry at the same sequence succeeds cleanly and matches an independent fresh reference engine.
  4. **Immutable Member Bounds & Conflicting Registration Rejection**:
     - In `register_source_members`, registration validates existing member keys against incoming definitions.
     - Distinguishes: idempotent re-observation (identical), explicit usage evidence updates (validated without changing bounds), and conflicting registrations (differing geometry, role, side, direction, or availability).
     - Conflicting registrations strictly raise `InvalidEvidenceError` without mutating existing member bounds or in-flight activation records.
  5. **Decoupled Rearm Controller & Unique Terminal Activation Identifiers**:
     - Introduced `RearmController` dataclass strictly separate from immutable `ActivationRecord`s.
     - When an activation is cancelled by an external commit:
       - The active record is terminalized, appended once to `_terminal_activations`, and removed from `_active_activations`.
       - A `RearmController` is created with `prior_activation_id = rec.activation_id` and `generation_seq = rec.generation_seq + 1`.
       - If subsequent source invalidation occurs, the controller is disabled; no duplicate terminal record is created for the old activation ID.
       - Terminal activation IDs are guaranteed globally unique.
       - When a fresh retouch occurs after confirmed outside departure, a brand-new activation record is created (`ACT::...::02`) with state `REARMED_PENDING` linked to `prior_activation_id`.
  6. **Comprehensive Test Suite & Replay Determinism**:
     - 30 execution tests in `tests/test_activation_engine.py` covering all 6 review directives:
       - Synchronization failure rollback and valid retry comparison.
       - Changed consumed history prefix rejection.
       - Cross-context snapshot rejection before mutation.
       - Repeated synchronization idempotence.
       - Single-event failure leaving envelope unconsumed.
       - Conflicting member registration rejection.
       - Unique terminal activation IDs.
       - Linked new-generation activation via rearm controller.
       - Full multi-phase lifecycle replay matching sequential execution across every prefix bit-for-bit.
- **Verification Summary**:
  - Activation engine execution suite: 30/30 passed in 0.71s (`pytest tests/test_activation_engine.py -v`).
  - Activation fixture integrity suite: 28/28 passed in 0.59s (`pytest tests/test_activation_fixture_integrity.py -v`).
  - Full offline repository test suite: 478/478 passed in 8.53s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.


### Milestone 17 (Activation Engine): Invariant & Adapter Hardening (HANDOFF-054)
- **Active Branch**: eature/activation-engine
- **Parent Commit**: 6a34bdc48be632ac554fe41104056c10c92017c9 (HANDOFF-053)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Complete adapter state-integrity hardening, full semantic transition history validation, transactional context binding, lagged cancellation processing for unresolved snapshots, and caller-retained public synchronization API.
- **Completed Deliverables**:
  1. **Complete Semantic Transition History Verification**:
     - TJLSynchronizer validates consumed transition prefix using complete TJLTransitionRecord value equality.
     - Detects and rejects altered transition timestamps, altered resulting set geometry, altered fingerprints, or altered cancellation intent with InvalidEvidenceError before any state mutation.
  2. **Caller-Retained Synchronization API**:
     - sync_tjl_snapshot_to_activation_engine strictly requires a persistent TJLSynchronizer instance. Passing a bare ActivationEngine raises a descriptive TypeError.
     - Preserves continuous transition cursors and prefix history across successive invocations.
  3. **Transactional Context Binding**:
     - Context binding (_bound_engine_id, _bound_symbol_feed_id, _bound_source_timeframe) is staged inside the transaction.
     - A failing first sync completely rolls back and leaves all binding fields None.
  4. **Unresolved Snapshot Cancellation Processing**:
     - Authoritative cancellation history is processed and applied to the engine even when snapshot.is_unresolved is True.
     - Prevents lingering active memberships from surviving when an engine consumer lags behind a finalized cancellation.
     - Fresh eligibility registration is cleanly suppressed for unresolved snapshots.
  5. **Focused Adapter Regressions**:
     - 	est_tjl_synchronizer_rejects_altered_transition_timestamp: rejects altered transition time.
     - 	est_tjl_synchronizer_rejects_altered_resulting_set_geometry: rejects altered zone prices in resulting set.
     - 	est_tjl_synchronizer_failed_first_sync_leaves_binding_unmutated: asserts pristine state on first sync failure.
     - 	est_tjl_synchronizer_processes_cancellation_from_unresolved_snapshot: validates lagged cancellation applied and fresh eligibility suppressed.
     - 	est_sync_tjl_snapshot_to_activation_engine_requires_retained_synchronizer: enforces retained synchronizer requirement.
- **Verification Summary**:
  - Activation engine execution suite: 35/35 passed in 1.69s (pytest tests/test_activation_engine.py -v).
  - Activation fixture integrity suite: 28/28 passed in 0.69s (pytest tests/test_activation_fixture_integrity.py -v).
  - Full offline repository test suite: 483/483 passed in 21.05s (pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream  == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on eature/activation-engine. No merging into main.


### Milestone 18 (Activation Engine): Receipt Diagnostic Disambiguation, Test Modularization & Engine Evidence Hardening (HANDOFF-055)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: 65f7ba0b984f919ad535eb59866f9bd705e7bedb (HANDOFF-054)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-054: distinguish receipt diagnostics from authoritative transition history, add real TJLReducer unresolved-snapshot regression, modularize adapter tests into 	ests/test_activation_adapter.py, and add all 5 requested direct engine evidence tests.
- **Completed Deliverables**:
  1. **Receipt Diagnostic vs. Authoritative History Disambiguation**:
     - In src/aladeen/strategy/activation_adapter.py, TJLSynchronizer recognizes that for unresolved snapshots, snapshot.last_transition represents a receipt diagnostic (BLOCKED_UNRESOLVED) rather than an authoritative transition appended to snapshot.transition_history.
     - Resolved snapshots continue to strictly enforce snapshot.last_transition == history[-1].
  2. **Real TJLReducer Unresolved Snapshot Contract Regression**:
     - 	est_tjl_reducer_unresolved_snapshot_with_lagged_cancellation verifies end-to-end that real TJLReducer emits last_transition as BLOCKED_UNRESOLVED while 	ransition_history tail holds authoritative CHOCH_INVALIDATION, and that a lagged TJLSynchronizer cleanly consumes the cancellation and suppresses fresh registration.
  3. **Dedicated Adapter Test Modularization**:
     - Separated 13 adapter tests from 	ests/test_activation_engine.py into 	ests/test_activation_adapter.py to maintain compact reviewable module sizes.
  4. **Direct ActivationEngine Evidence Gaps Closed**:
     - 	est_exact_price_print_before_vs_at_availability: verifies pre-availability print produces zero activation, while print exactly at availability time transitions cleanly to PENDING_ACTIVATION.
     - 	est_exact_price_print_boundaries_and_zero_width: verifies exact lower edge touch, exact upper edge touch, zero-width line equality, and outside prints.
     - 	est_prior_candle_close_and_range_only_evidence_produces_zero_activation: verifies prior candle close and intra-candle range straddle without discrete print produce zero activation.
     - 	est_unknown_interval_order_fresh_vs_pending_members: verifies that unknown sub-bar order preserves existing PENDING_ACTIVATION on touched members while fresh members fail closed to BLOCKED_UNKNOWN_ORDER.
     - 	est_two_reactivations_at_same_coarse_timestamp_with_distinct_sequence_refs: verifies that distinct reactivations sharing coarse timestamp $ generate distinct linked new generation IDs ordered by sequence reference.
- **Verification Summary**:
  - Activation engine execution suite: 32/32 passed in 1.15s (pytest tests/test_activation_engine.py -v).
  - Activation adapter suite: 13/13 passed in 0.95s (pytest tests/test_activation_adapter.py -v).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (pytest tests/test_activation_fixture_integrity.py -v).
  - Total activation tests: 73/73 passed.
  - Full offline repository test suite: 493/493 passed in 17.08s (pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream  == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on eature/activation-engine. No merging into main.


### Milestone 19 (Activation Engine): Rearm Gating, Canonical Length-Prefixed Identities, and Batch Validation (HANDOFF-056)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: 5bebbabf0d65e27c6dd9cd566d656c6f1e5e3dfd (HANDOFF-055)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-055: gate rearm departure and retouch transitions on coverage, usage, and availability; implement canonical length-prefixed identifier encodings; validate supported roles; prevalidate intra-batch conflicts in member registration; and narrow receipt-diagnostic validation to supported combinations.
- **Completed Deliverables**:
  1. **Rearm Controller Evidence Gating**:
     - In `src/aladeen/strategy/activation_engine.py`, gated both rearm controller transitions (`AWAITING_DEPARTURE -> OUT_OF_ZONE_ARMED` and `OUT_OF_ZONE_ARMED -> REARMED_PENDING`) on complete coverage (`self._coverage_status == CoverageStatus.COMPLETE`), unused usage evidence (`member.usage_evidence_status == UsageEvidenceStatus.UNUSED`), and valid availability timing (`event.timestamp >= member.eligibility_available_time`).
     - Terminal activations and controllers remain preserved without mutating or consuming invalid observations.
  2. **Canonical Length-Prefixed Unambiguous Encodings**:
     - Implemented `format_activation_id()` and `format_member_key()` in `src/aladeen/strategy/activation_types.py` using canonical length-prefixing (`[len:string]`), mathematically guaranteeing collision resistance against arbitrary delimiter-containing inputs.
     - Defined `SUPPORTED_SOURCE_ROLES = frozenset({"TJL1", "TJL2_A_PLUS"})` and enforced role validation in `SourceMemberReference.__post_init__()`.
  3. **Intra-Batch Conflict Prevalidation in Registration**:
     - In `ActivationEngine.register_source_members()`, staged candidates into a map during prevalidation. Identical duplicates within the batch are coalesced cleanly; conflicting duplicates reject the entire batch with `InvalidEvidenceError` before any state mutation.
  4. **Strict Receipt-Diagnostic Combination Validation**:
     - In `src/aladeen/strategy/activation_adapter.py`, resolved snapshots carrying `BLOCKED_UNRESOLVED` or mismatched tails are strictly rejected, while unresolved snapshots carrying non-diagnostic last transitions are also rejected. Compatibility with real reducer-produced unresolved snapshots is fully preserved.
  5. **Focused Regressions Added**:
     - `test_rearm_controller_inside_at_cancel_incomplete_coverage_departure_blocks_rearm`
     - `test_rearm_controller_already_armed_incomplete_coverage_retouch_blocks_rearm`
     - `test_rearm_controller_with_unknown_or_used_usage_blocks_rearm`
     - `test_rearm_controller_valid_later_evidence_activates_cleanly_without_recycled_blocked_evidence`
     - `test_canonical_unambiguous_identifiers_with_adversarial_delimiters`
     - `test_supported_roles_validation`
     - `test_conflicting_duplicate_members_in_same_batch_rejected_before_mutation`
     - `test_identical_duplicate_members_in_same_batch_coalesced`
     - `test_tjl_synchronizer_rejects_inconsistent_receipt_diagnostic_combinations`
- **Verification Summary**:
  - Activation engine execution suite: 40/40 passed in 0.63s (`pytest tests/test_activation_engine.py -v`).
  - Activation adapter suite: 14/14 passed in 0.61s (`pytest tests/test_activation_adapter.py -v`).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (`pytest tests/test_activation_fixture_integrity.py -v`).
  - Total activation tests: 82/82 passed.
  - Full offline repository test suite: 502/502 passed in 19.55s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.


### Milestone 20 (Activation Engine): Full Adversarial Lifecycle Regression, State Extraction, and Acceptance Closeout (HANDOFF-057)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: ac8ea186a23862237a17f118dcb8f1d6b1d72fc5 (HANDOFF-056)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-056: extend adversarial-identifier test across the full lifecycle (`first activation -> external cancellation -> departure -> linked reactivation -> source invalidation -> replay`); modularize internal state container into `src/aladeen/strategy/activation_state.py` to prevent review truncation; add coverage scope filtering and recovery from `BLOCKED_UNKNOWN_ORDER`; and provide explicit finding-to-test mapping for acceptance closeout.
- **Completed Deliverables**:
  1. **Full Adversarial Delimiter Lifecycle Regression**:
     - Extended `test_canonical_unambiguous_identifiers_with_adversarial_delimiters` across all lifecycle stages:
       - Initial registration of adversarial members with delimiters (`set_id="SET::1"` vs `set_id="SET"`).
       - First activation touches creating distinct generation 1 IDs.
       - External cancellation creating separate `RearmController` instances with distinct prior activation IDs.
       - Confirmed outside departure arming controllers to `OUT_OF_ZONE_ARMED`.
       - Retouch prints creating distinct generation 2 `REARMED_PENDING` activations linked to generation 1 parents.
       - Targeted source replacement invalidating `SET::1` while preserving `SET`.
       - Subsequent source CHOCH invalidating `SET`.
       - 100% bit-for-bit replay equivalence from scratch across every prefix.
  2. **Modular State Container (`activation_state.py`)**:
     - Extracted `ActivationEngineState` into [`src/aladeen/strategy/activation_state.py`](file:///src/aladeen/strategy/activation_state.py) (90 lines), keeping all strategy modules well under 400 lines so no files truncate during review retrieval.
  3. **Coverage Scope Filtering & Stale Rejection**:
     - `_process_coverage_evidence` enforces scope matching (`self.symbol`, `self.engine_id`, `ALL`, `GLOBAL`). Unrelated scopes are cleanly ignored.
     - Out-of-order sequence references strictly raise `SequenceOrderError`.
     - Ordered restoration from `INCOMPLETE` to `COMPLETE` restores activation gating.
  4. **Unknown-Order Recovery via Authoritative Prints**:
     - `_process_exact_price_print` allows members placed in `BLOCKED_UNKNOWN_ORDER` by uncertain candle evidence to recover cleanly to `PENDING_ACTIVATION` upon arrival of subsequent discrete price prints at or after availability.
  5. **Direct Test Assertions Added**:
     - `test_coverage_evidence_scope_and_stale_rejection`
     - `test_unknown_order_recovery_with_subsequent_exact_print`
- **Verification Summary**:
  - Activation engine execution suite: 42/42 passed in 0.90s (`pytest tests/test_activation_engine.py -v`).
  - Activation adapter suite: 14/14 passed in 0.61s (`pytest tests/test_activation_adapter.py -v`).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (`pytest tests/test_activation_fixture_integrity.py -v`).
  - Total activation tests: 84/84 passed.
  - Full offline repository test suite: 504/504 passed in 16.49s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.


### Milestone 21 (Activation Engine): Honest Runtime Extraction, Retrievable Modules, and Every-Prefix Full-State Replay Equivalence (HANDOFF-058)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: e479546dfd4513b4f41bc69173be45ade6a7a6f1 (HANDOFF-057)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-057:
  1. Complete runtime extraction honestly: genuinely integrate `ActivationEngineState` into `ActivationEngine`, eliminating duplicate mutable dictionaries and redundant in-file reducer logic; provide retrievable, isolated modules for evidence, prints/registration, state, and engine façade (all strictly <380 lines to prevent review retrieval truncation).
  2. Correct adversarial replay regression: record sequential snapshots and canonical full-state checkpoints after each event; assert bit-for-bit equality for every intermediate replay prefix across both snapshots and full future-behavior checkpoints (processed events, observation associations, consumed observations, generation counts, controllers, sequence, and coverage); assert replay leaves invoking engine unmutated.
  3. Preserve expanded adversarial lifecycle assertions, coverage-scope filtering, unknown-order recovery, and prior regressions.
- **Completed Deliverables**:
  1. **Honest Runtime State Integration & Zero Duplicate Code**:
     - `ActivationEngine` in [`src/aladeen/strategy/activation_engine.py`](file:///src/aladeen/strategy/activation_engine.py) (199 lines) now exclusively instantiates and delegates to `self._state = ActivationEngineState(...)`.
     - Zero parallel state containers; snapshot projection, state inspection, and checkpoint creation/restoration delegate directly to `ActivationEngineState`.
  2. **Modular, Fully Retrievable Runtime Modules (<380 lines each)**:
     - [`src/aladeen/strategy/activation_state.py`](file:///src/aladeen/strategy/activation_state.py) (102 lines): Authoritative mutable state container `ActivationEngineState`, complete checkpoint creation/restoration for transactional atomicity, `get_snapshot()`, and `reset()`.
     - [`src/aladeen/strategy/activation_evidence.py`](file:///src/aladeen/strategy/activation_evidence.py) (181 lines): Isolated handlers for `process_cancellation_event` (CHOCH and Replacement), `process_external_commit_event` (winner exclusion & rearm controller instantiation), `process_candle_evidence` (interval bounds & intra-candle availability fail-closed), and `process_coverage_evidence` (scoped context validation).
     - [`src/aladeen/strategy/activation_handlers.py`](file:///src/aladeen/strategy/activation_handlers.py) (370 lines): Authoritative implementations for `validate_sequence_and_domain` (monotonicity, idempotence, conflict detection), `register_source_members` (intra-batch duplicate coalescing & immutable geometry/identity), `process_register_members_event`, and `process_exact_price_print` (touch observation, BLOCKED_UNKNOWN_ORDER recovery, decoupled rearm controller evaluation).
     - [`src/aladeen/strategy/activation_engine.py`](file:///src/aladeen/strategy/activation_engine.py) (199 lines): Compact façade coordinating config, registration, event dispatch, atomic batch processing, isolated replay, and backwards-compatible property access.
  3. **Every-Prefix Snapshot & Full-State Checkpoint Replay Assertions**:
     - In `tests/test_activation_engine.py` (`test_canonical_unambiguous_identifiers_with_adversarial_delimiters`):
       - Captured sequential `seq_snapshots` and `seq_checkpoints` after each of the 9 events.
       - Asserted full `.replay()` returns all prefix snapshots matching `seq_snapshots` bit-for-bit.
       - Replayed every prefix $k \in [1, 9]$ on an isolated engine, asserting both snapshot equality AND bit-for-bit full checkpoint equality (`processed_events`, `observation_associations`, `member_consumed_observations`, `generation_counts`, `current_members`, `active_activations`, `terminal_activations`, `rearm_controllers`, `last_processed_sequence`, `last_processed_timestamp`, `coverage_status`).
       - Asserted calling `.replay()` on an existing engine does not mutate the invoking engine's state or checkpoint.
- **Verification Summary**:
  - Activation engine execution suite: 42/42 passed in 0.69s (`pytest tests/test_activation_engine.py -q`).
  - Activation adapter suite: 14/14 passed in 0.61s (`pytest tests/test_activation_adapter.py -q`).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (`pytest tests/test_activation_fixture_integrity.py -q`).
  - Total activation tests: 84/84 passed.
  - Full offline repository test suite: 504/504 passed in 17.21s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.


### Milestone 22 (Activation Engine): External-Commit Scope Enforcement, Explicit Source-Cancellation Targeting, and Isolated Replay Test Module (HANDOFF-059)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: dd2d73f0cd313e927d1834cb618642fe5a965545 (HANDOFF-058)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-058:
  1. Enforce external-commit scope: define `SUPPORTED_COMMIT_SCOPES = frozenset({"SAME_SOURCE_TIMEFRAME", "ENGINE_LOCAL"})`, validate scope before sequence/domain consumption, fail closed with `InvalidEvidenceError` on unsupported scopes leaving checkpoint untouched and sequence unconsumed; allow valid retry at unconsumed sequence; preserve external winner exclusion without arbitration.
  2. Make source-cancellation targeting explicit: reject `target_role is not None` with `InvalidEvidenceError` (partial-role cancellation not supported; cancellations operate at full set/direction level); enforce `target_set_id` for `SOURCE_REPLACEMENT`; enforce `target_set_id` and/or `affected_direction` for `SOURCE_CHOCH`; reject contradictory targeting combinations before mutation; ensure targeted cancellations cannot affect unrelated sets.
  3. Relocate every-prefix snapshot/checkpoint replay test to standalone retrievable module `tests/test_activation_replay.py` (174 lines) to prevent review truncation.
- **Completed Deliverables**:
  1. **External-Commit Scope Contract Enforcement**:
     - Defined `SUPPORTED_COMMIT_SCOPES` in `src/aladeen/strategy/activation_types.py`.
     - In `process_external_commit_event()` ([`src/aladeen/strategy/activation_evidence.py`](file:///src/aladeen/strategy/activation_evidence.py)), validate `event.cancelled_competing_scope in SUPPORTED_COMMIT_SCOPES` before sequence and domain validation.
     - Unsupported scopes fail closed with `InvalidEvidenceError` without recording processed event or advancing sequence.
     - Valid retry at the unconsumed sequence succeeds cleanly. Winner exclusion preserved.
  2. **Explicit Source-Cancellation Targeting & Contradiction Rejection**:
     - In `process_cancellation_event()` ([`src/aladeen/strategy/activation_evidence.py`](file:///src/aladeen/strategy/activation_evidence.py)), reject `target_role is not None` with `InvalidEvidenceError`.
     - Enforce required targets per reason (`target_set_id` for replacement; `target_set_id` or `affected_direction` for CHOCH).
     - Cross-validate `target_set_id` against `affected_direction` on existing members; contradictory combinations reject before mutation.
     - Members to cancel are identified strictly by declared targets; unrelated sets are completely untouched.
  3. **Standalone, Retrievable Replay Module (`tests/test_activation_replay.py`)**:
     - Relocated full adversarial delimiter lifecycle and every-prefix snapshot/checkpoint comparison to [`tests/test_activation_replay.py`](file:///tests/test_activation_replay.py) (174 lines).
     - Completely eliminated review truncation on replay test assertions.
  4. **Decisive Regressions Added**:
     - `test_external_commit_unsupported_scope_fails_closed_and_retry_succeeds`
     - `test_source_cancellation_unsupported_role_and_contradictory_targets_rejected`
     - `test_targeted_source_cancellation_cannot_affect_unrelated_set`
     - `test_canonical_unambiguous_identifiers_with_adversarial_delimiters_and_every_prefix_replay`
- **Verification Summary**:
  - Activation engine execution suite: 44/44 passed in 0.69s (`pytest tests/test_activation_engine.py -q`).
  - Activation replay execution suite: 1/1 passed in 0.60s (`pytest tests/test_activation_replay.py -q`).
  - Activation adapter suite: 14/14 passed in 0.61s (`pytest tests/test_activation_adapter.py -q`).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (`pytest tests/test_activation_fixture_integrity.py -q`).
  - Total activation tests: 87/87 passed.
  - Full offline repository test suite: 507/507 passed in 13.99s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.


### Milestone 23 (Activation Engine): Source Cancellation Reason Restrictions, Empty-Target Rejection, and Authoritative Commit-Routing Validation (HANDOFF-060)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: c9e86c208020a90b3566b512d4e4ac64923eb567 (HANDOFF-059)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-059:
  1. Restrict source cancellation reasons in `process_cancellation_event()` strictly to `SOURCE_CHOCH` and `SOURCE_REPLACEMENT` before envelope consumption; fail closed with `InvalidEvidenceError` if `EXTERNAL_ENTRY` is submitted to the source handler.
  2. Reject empty or whitespace `target_set_id` consistently while preserving valid directional-only CHOCH cancellation.
  3. Complete external-commit receiving-context validation: require authoritative `target_symbol` and `target_source_timeframe` for `SAME_SOURCE_TIMEFRAME`, and `target_engine_id` for `ENGINE_LOCAL`. Missing routing evidence fails closed without cancelling activations or consuming sequence. Correctly addressed commits for unrelated contexts cleanly ignore.
  4. Update all commit fixtures (including `test_activation_replay.py`) to supply explicit routing evidence.
- **Completed Deliverables**:
  1. **Strict Cancellation Reason & Non-Empty Target Enforcement**:
     - In `process_cancellation_event()` ([`src/aladeen/strategy/activation_evidence.py`](file:///src/aladeen/strategy/activation_evidence.py)), reject any reason other than `SOURCE_CHOCH` and `SOURCE_REPLACEMENT` before sequence validation.
     - Reject empty or whitespace `target_set_id` with `InvalidEvidenceError`.
     - Directional-only CHOCH cancellation is preserved and operates cleanly.
  2. **Mandatory External-Commit Routing Evidence Contract**:
     - In `process_external_commit_event()` ([`src/aladeen/strategy/activation_evidence.py`](file:///src/aladeen/strategy/activation_evidence.py)), enforce mandatory routing fields before sequence consumption:
       - `SAME_SOURCE_TIMEFRAME` requires non-empty `target_symbol` and `target_source_timeframe`.
       - `ENGINE_LOCAL` requires non-empty `target_engine_id`.
     - Missing routing evidence strictly fails closed with `InvalidEvidenceError` leaving checkpoint untouched and sequence unconsumed.
     - Commits addressed to unrelated contexts return `state.get_snapshot()` without affecting this engine.
  3. **Updated Fixtures & Non-Truncating Retrievable Modules**:
     - Updated all commit fixtures across `test_activation_engine.py` and `test_activation_replay.py` to supply authoritative routing evidence.
     - All strategy runtime files and test modules remain strictly under 380 lines.
  4. **Decisive Regressions Added**:
     - `EXTERNAL_ENTRY` submitted as `SourceCancellationEvent` rejected with checkpoint unchanged and sequence unconsumed.
     - Empty/whitespace CHOCH set target rejected.
     - Valid event retry at unconsumed sequence succeeds.
     - Missing commit-routing evidence fails closed.
     - Wrong-context commit cannot affect this engine.
     - Valid scoped commit preserves winner and cancels competitors.
- **Verification Summary**:
  - Activation engine execution suite: 44/44 passed in 0.81s (`pytest tests/test_activation_engine.py -q`).
  - Activation replay execution suite: 1/1 passed in 1.48s (`pytest tests/test_activation_replay.py -q`).
  - Activation adapter suite: 14/14 passed in 0.61s (`pytest tests/test_activation_adapter.py -q`).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (`pytest tests/test_activation_fixture_integrity.py -q`).
  - Total activation tests: 87/87 passed.
  - Full offline repository test suite: 507/507 passed in 14.16s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.


### Milestone 24 (Activation Engine): Cancelled Membership Invalidation Continuity and Pending Activation Provenance Preservation (HANDOFF-061)
- **Active Branch**: feature/activation-engine
- **Parent Commit**: 952c13996ca4ab36e6aceecef79196cce7521fa5 (HANDOFF-060)
- **Root Baseline Commit**: 535af1434ed9a6b93328202039db7f1d4f4be410 (Accepted TJL Dashboard Integration)
- **Objective**: Address Perplexity's review of HANDOFF-060:
  1. **Cancelled Membership Invalidation Continuity**: Ensure outgoing source set identities cancelled via `SOURCE_CHOCH` or `SOURCE_REPLACEMENT` cannot be re-registered within the same run. Distinct successor sets (`SET_SUCCESSOR_02`) containing the same physical level must register cleanly.
  2. **Pending Activation Provenance Preservation Across Usage Uncertainty**: Ensure active touch provenance (`first_touch_time`, `first_touch_price`, `activation_id`, `generation_seq`) is strictly preserved across temporary `UNKNOWN` usage evidence fluctuations, rather than resetting to generation zero on recovery.
  3. Ensure all strategy runtime modules and test files strictly respect the 380-line boundary.
- **Completed Deliverables**:
  1. **Authoritative Invalidation Tracking**:
     - Added `invalidated_member_keys: Set[str]` and `invalidated_set_ids: Set[str]` to `ActivationEngineState` in [`src/aladeen/strategy/activation_state.py`](file:///src/aladeen/strategy/activation_state.py).
     - Recorded cancelled `member_key`s and `set_id`s in `process_cancellation_event()` in [`src/aladeen/strategy/activation_evidence.py`](file:///src/aladeen/strategy/activation_evidence.py).
     - Enforced rejection in `register_source_members()` in [`src/aladeen/strategy/activation_handlers.py`](file:///src/aladeen/strategy/activation_handlers.py) with `InvalidEvidenceError` prior to batch staging or mutation.
     - Preserved in `create_checkpoint()`, `restore_checkpoint()`, and `reset()`.
     - Distinct successor set identities containing identical physical levels register cleanly as generation 0 inactive-eligible slots.
  2. **Touch Provenance Preservation Across Evidence Gating**:
     - In `register_source_members()` in [`src/aladeen/strategy/activation_handlers.py`](file:///src/aladeen/strategy/activation_handlers.py), if an existing member record already has touch provenance (`first_touch_time is not None` or active state), evidence updates to `UNKNOWN` update `usage_evidence_status` and apply `blocked_reason="USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"` without wiping or resetting `activation_id`, `first_touch_time`, `first_touch_price`, or `generation_seq`.
     - When evidence recovers to `UNUSED`, `blocked_reason` clears to `None` while fully maintaining original activation provenance and state.
  3. **Module Line Count Verification**:
     - `activation_adapter.py`: 258 lines
     - `activation_engine.py`: 199 lines
     - `activation_evidence.py`: 252 lines
     - `activation_handlers.py`: 379 lines
     - `activation_state.py`: 111 lines
     - `activation_types.py`: 335 lines
     - `test_activation_replay.py`: 179 lines
     - All runtime files strictly under 380 lines.
  4. **Decisive Regressions Added**:
     - `test_invalidated_membership_reregistration_rejected_and_successor_set_allowed`
     - `test_pending_activation_provenance_preserved_across_usage_uncertainty`
- **Verification Summary**:
  - Activation engine execution suite: 46/46 passed in 0.95s (`pytest tests/test_activation_engine.py -q`).
  - Activation replay execution suite: 1/1 passed in 1.48s (`pytest tests/test_activation_replay.py -q`).
  - Activation adapter suite: 14/14 passed in 0.61s (`pytest tests/test_activation_adapter.py -q`).
  - Activation fixture integrity suite: 28/28 passed in 0.60s (`pytest tests/test_activation_fixture_integrity.py -q`).
  - Total activation tests: 89/89 passed.
  - Full offline repository test suite: 509/509 passed in 13.56s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  3. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  4. *Branch Boundary*: Committed and pushed strictly on `feature/activation-engine`. No merging into `main`.

## 25. Milestone Acceptance: Pure Offline Activation Engine Implementation (HANDOFF-061)
- **Accepted Milestone**: Pure Offline Activation Engine Lifecycle Reducer & TJL Adapter (`HANDOFF-061`).
- **Accepted Commit Hash**: `0867c740352297fb43e781fb654706218771d533`
- **Active Branch**: `feature/activation-engine`
- **Reviewer Status**: **ACCEPTED** by Perplexity as the bounded offline Activation Engine baseline.
- **Accepted Scope**:
  1. Exact-observation activation and fail-closed evidence gating.
  2. Source cancellation and outgoing-identity permanent retirement within the run.
  3. Externally supplied commit cancellation, commit routing, and winner exclusion.
  4. Separate rearm controllers and linked activation generations.
  5. Transactional processing, atomic rollbacks, and snapshot synchronization.
  6. Canonical unambiguous identifiers and verified every-prefix replay.
  7. Successor-set registration of persistent physical levels under distinct set identities.
  8. Activation provenance preservation across temporary `UNKNOWN` usage evidence fluctuations.
- **Recorded Review Verification Boundaries & Exclusions**:
  1. *Source Diff Inspection*: Perplexity independently inspected full source diffs of `activation_evidence.py`, `activation_handlers.py`, `activation_state.py`, and both added regression tests.
  2. *Evidence Classification*: 509 passing offline repository tests and 26 acceptance fixtures are implementation-reported evidence, not rerun independently in Perplexity's review.
  3. *Actionability Distinction*: Temporary gating and lifecycle history remain strictly distinct: downstream consumers must not treat a pending record with uncertain usage or a blocked reason as actionable.
  4. *Standing Exclusions Preserved*: Acceptance does not resolve upstream $c_1 == p_2$ ambiguity or ISS multi-candle pullbacks. It does not authorize UI integration, ingestion, confirmation selection, arbitration, usage-ledger commits, signals, broker operations, or execution.
  5. *Branch Boundary*: No merge into `main`. The next milestone requires an explicit scope and acceptance contract before implementation begins.

## 26. Milestone Requirements: Read-Only Activation Dashboard Integration (HANDOFF-062)
- **Active Branch**: `requirements/activation-dashboard-acceptance`
- **Immediate Parent Commit**: `3aed45bb9e0e3b9f61bb8d02cd40cff39a5f5bae` (Status update recording Milestone 25 acceptance)
- **Root Baseline Engine Commit**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)
- **Objective**: Deliver comprehensive requirements specification, acceptance fixture catalog, fixture integrity test suite, and integration-gap assessment for the read-only Activation Dashboard integration.
- **Scope Boundary**: Pure requirements specification and fixture integrity validation. **Strictly zero UI order execution, zero MT5 trading calls, zero live account modification, zero confirmation arbitration, zero usage-ledger commits, zero trade entry signals, zero automated trading, zero runtime implementation modifications in this phase, and zero merging to `main`**.
- **Completed Deliverables**:
  1. [`docs/requirements/activation-dashboard-acceptance.md`](file:///docs/requirements/activation-dashboard-acceptance.md):
     - Comprehensive bounded scope and strict exclusions (no execution, no confirmation selection, no arbitration, no usage-ledger writes).
     - Non-negotiable presentation semantics (Pending != Actionable, History != Current Eligibility, Unknown stays Unknown, Unresolved stays visible).
     - Specification of 8 required display groups: Context (G1), Membership (G2), Activation (G3), Evidence Gating (G4), Cancellation (G5), Rearm Controller (G6), Terminal History (G7), and Synchronization (G8).
     - Architecture contract: pure presentation projection, single retained `TJLSynchronizer` owned by service layer, zero reducer mutation, deterministic sorting, explicit missing-data display, and bounded history presentation policy.
     - 16 acceptance scenarios with exact expected views, disclaimers, and assertions.
     - Integration-gap assessment: inspected `tjl_inspection.py`, `msm_callbacks.py`, `layout.py`, `service.py`, `activation_types.py`, and `activation_adapter.py`. Confirmed all required display fields are already present on public dataclasses; zero private dictionary exposure or engine changes required.
  2. [`tests/fixtures/activation_dashboard_acceptance.json`](file:///tests/fixtures/activation_dashboard_acceptance.json):
     - Standardized acceptance fixture catalog covering all 16 scenarios.
     - Explicit evidence categories assigned (`synthetic`, `engine-derived`, `candle-pipeline-derived`).
     - Includes explicit non-execution disclaimer distinguishing fixture data integrity from claimed executable UI integration.
  3. [`tests/test_activation_dashboard_fixture_integrity.py`](file:///tests/test_activation_dashboard_fixture_integrity.py) (207 lines):
     - 8 automated integrity tests validating schema, scenario completeness, evidence category compliance, display group completeness, strict `is_actionable == False` invariant, timestamp normalization, and scenario-specific assertion contracts.
- **Verification Summary**:
  - Activation dashboard fixture integrity suite: **8 / 8 passed** in 4.22s (`pytest tests/test_activation_dashboard_fixture_integrity.py -q`).
  - Full offline repository test suite: **517 / 517 passed** in 14.47s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
- **Scope Compliance & Standing Invariants**:
  1. *Requirements Phase Only*: Zero runtime modifications to strategy engine, adapter, or UI files.
  2. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  3. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  4. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  5. *Branch Boundary*: Committed and pushed strictly on `requirements/activation-dashboard-acceptance`. No merging into `main`.

### HANDOFF-063: Domain Vocabulary Realignment, Public Input Provenance Matrix, and Offline Evidence Boundary Hardening
- **Active Branch**: `requirements/activation-dashboard-acceptance`
- **Immediate Parent Commit**: `1cc64c489cbe97f56f4dca671759ea4be23267d3` (HANDOFF-062)
- **Root Baseline Engine Commit**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)
- **Objective**: Address Perplexity's review of HANDOFF-062:
  1. Realine activation and coverage vocabulary: exact observed price evidence alone establishes touch (rejecting candle interval or OHLC overlap claims); enforce valid domain `CoverageStatus` enum values (`COMPLETE`, `INCOMPLETE`, `UNCERTAIN`).
  2. Provide comprehensive field-by-field public input and provenance matrix across all 8 display groups G1-G8 (source object, public attribute, availability, missing-value presentation, join keys).
  3. Formulate offline service evidence boundary and context lifecycle (exact prints from offline streams, usage defaults to UNKNOWN fail-closed, session discard on symbol/TF changes).
  4. Separate planned category, construction procedure, and execution status (`"specified; not yet executed through the presentation implementation"`).
  5. Enforce canonical unresolved banner string (`"LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"`), dedicated cancellation timestamp (`"Unknown"`) vs sequence (`"#<seq>"`) columns, and deterministic multi-tier sorting.
- **Completed Deliverables**:
  1. [`docs/requirements/activation-dashboard-acceptance.md`](file:///docs/requirements/activation-dashboard-acceptance.md):
     - Corrected exact-observation and coverage semantics in §§1.2, 2.1, and Scenario 5.
     - Section 3: Comprehensive 40-row public input and provenance matrix across G1-G8.
     - Section 4: Defined offline service evidence boundary and session isolation lifecycle across context changes.
     - Section 5: Updated 16 acceptance scenarios with explicit construction procedures and `"specified; not yet executed through the presentation implementation"` status.
     - Section 6: Grounded integration-gap assessment showing dataclass sufficiency without event-target reconstruction.
  2. [`tests/fixtures/activation_dashboard_acceptance.json`](file:///tests/fixtures/activation_dashboard_acceptance.json):
     - Version 1.1 with valid `CoverageStatus` domain enum values (`INCOMPLETE`, `UNCERTAIN`).
     - Construction procedure and execution status fields on all 16 scenarios.
     - Dedicated timestamp (`"Unknown"`) and sequence (`"#125"`) assertions for Scenario 8.
     - Canonical unresolved banner string on Scenario 13.
     - Testable component tree and state immutability assertions on Scenario 16.
  3. [`tests/test_activation_dashboard_fixture_integrity.py`](file:///tests/test_activation_dashboard_fixture_integrity.py) (215 lines):
     - 8 automated integrity checks validating schema, execution status, domain coverage enum, canonical banner, timestamp/sequence separation, and component tree immutability assertions.
- **Verification Summary**:
  - Activation dashboard fixture integrity suite: **8 / 8 passed** in 4.09s (`pytest tests/test_activation_dashboard_fixture_integrity.py -q`).
  - Full offline repository test suite: **517 / 517 passed** in 17.38s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
  - Runtime modification audit: Exactly zero runtime files modified (`git diff src/` is empty).
- **Scope Compliance & Standing Invariants**:
  1. *Requirements Phase Only*: Zero runtime modifications to strategy engine, adapter, or UI files.
  2. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  3. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  4. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  5. *Branch Boundary*: Committed and pushed strictly on `requirements/activation-dashboard-acceptance`. No merging into `main`.

### HANDOFF-064: Domain Mapping Alignment, Provenance Preservation Invariants, and Non-Truncating Requirements Baseline
- **Active Branch**: `requirements/activation-dashboard-acceptance`
- **Immediate Parent Commit**: `eabb813738b77d612e34fa5ef59f23788eb59c03` (HANDOFF-063)
- **Root Baseline Engine Commit**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)
- **Objective**: Address Perplexity's review of HANDOFF-063:
  1. Replace non-domain `sequence_domain.domain_id` with explicit domain attributes `feed_id` and `run_id` across matrix, fixtures, and tests.
  2. Correct Scenario 4 construction and assertions: `UNUSED -> exact touch -> UNKNOWN` preserves pending activation provenance while applying fail-closed gating; add separate assertion proving initial `UNKNOWN` usage blocks touch from creating activations.
  3. Align Scenario 6 with the raw domain blocked reason `UNKNOWN_AVAILABILITY_TIMING` while separating friendly presentation text (`"Unknown Availability Timing"`).
  4. Separate missing activation context (`"Awaiting activation context"`), valid context without observations (`"No intraday observations processed for this session"`), and existing evidence with no newly supplied observations. Untouched member with default missing usage defaults to `INACTIVE_INELIGIBLE` (`USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`).
  5. Replace fabricated `"0.0"` numeric missing bounds with `"Unknown"` or `"—"`; define precision-preserving price formatting.
  6. Restructure requirements document into a concise, non-truncating format (119 lines) ensuring complete retrieval across all connectors.
- **Completed Deliverables**:
  1. [`docs/requirements/activation-dashboard-acceptance.md`](file:///docs/requirements/activation-dashboard-acceptance.md) (119 lines):
     - Exact domain sequence domain attributes (`feed_id`, `run_id`).
     - Aligned raw domain blocked reason `UNKNOWN_AVAILABILITY_TIMING` and friendly presentation label.
     - Delineated context fallback, zero-observations notice, and existing evidence preservation.
     - Precision-preserving price formatting without fabricated `"0.0"` defaults.
     - Compact table format covering all 16 scenarios without truncation.
  2. [`tests/fixtures/activation_dashboard_acceptance.json`](file:///tests/fixtures/activation_dashboard_acceptance.json):
     - Version 1.2 with explicit `feed_id` and `run_id` in sequence domain.
     - Corrected Scenario 4 construction and preserved pending provenance assertions.
     - Raw blocked reason `UNKNOWN_AVAILABILITY_TIMING` in Scenario 6.
  3. [`tests/test_activation_dashboard_fixture_integrity.py`](file:///tests/test_activation_dashboard_fixture_integrity.py) (215 lines):
     - 8 automated integrity tests validating schema, domain feed/run IDs, execution status, domain coverage enum, canonical banner, timestamp/sequence separation, and immutability assertions.
- **Verification Summary**:
  - Activation dashboard fixture integrity suite: **8 / 8 passed** in 0.52s (`pytest tests/test_activation_dashboard_fixture_integrity.py -q`).
  - Full offline repository test suite: **517 / 517 passed** in 19.26s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
  - Runtime modification audit: Exactly zero runtime files modified (`git diff src/` is empty).
- **Scope Compliance & Standing Invariants**:
  1. *Requirements Phase Only*: Zero runtime modifications to strategy engine, adapter, or UI files.
  2. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  3. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  4. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  5. *Branch Boundary*: Committed and pushed strictly on `requirements/activation-dashboard-acceptance`. No merging into `main`.

### HANDOFF-065: Service Diagnostic Notice Delineation, Canonical Activation ID Formatting, and Enforceable Architecture Safeguards
- **Active Branch**: `requirements/activation-dashboard-acceptance`
- **Immediate Parent Commit**: `77645ca3d7e20e82a28e12ecc71bc98066e17e7f` (HANDOFF-064)
- **Root Baseline Engine Commit**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)
- **Objective**: Address Perplexity's review of HANDOFF-064:
  1. *Observation vs. Cursor Delineation*: Clarify that `ActivationSnapshot.last_processed_sequence` is an engine cursor advancing for all events (registrations, coverage, cancellations), not an observation counter. Omit unverified observation-count claims unless explicit service diagnostic `exact_observation_count` is supplied. Delineate observation lifecycle cases.
  2. *Canonical Activation ID Formatting*: Replace synthetic activation IDs (`ACT_EURUSD_H1_SET_1_TJL1_GEN1`) with canonical length-prefixed IDs generated via `format_activation_id()` across Scenario 11, fixtures catalog, and integrity tests.
  3. *Architecture Safeguards*: Codify enforceable architecture safeguards in requirements: pure functional presentation projection (zero reducer/synchronizer calls), internal state preservation (checkpoints, cursor, usage cache unmutated), bounded DOM pagination without underlying sequence pruning, and clean fallback components.
  4. *Scenario 13 Status*: Explicitly mark Scenario 13 candle-derived construction procedure as `planned/unverified`.
  5. *Domain Consistency Validation*: Add automated requirements-side domain consistency checks using accepted public engine types without claiming UI execution.
- **Completed Deliverables**:
  1. [`docs/requirements/activation-dashboard-acceptance.md`](file:///docs/requirements/activation-dashboard-acceptance.md) (146 lines):
     - Section 4.1: Clarified engine cursor semantics vs observation counter; documented the 3 observation lifecycle cases; specified optional service diagnostic `exact_observation_count`.
     - Section 4.2: Formalized 5 enforceable architecture safeguards (rendering purity, state preservation, bounded history display, diagnostic error presentation, deterministic sorting).
     - Section 5: Updated Scenario 11 to canonical activation ID format; updated Scenario 13 construction procedure to `planned/unverified`.
  2. [`tests/fixtures/activation_dashboard_acceptance.json`](file:///tests/fixtures/activation_dashboard_acceptance.json):
     - Version 1.3 with canonical `format_activation_id()` outputs across Scenario 11, prior activation links, and terminal history records.
     - Scenario 13 construction procedure marked as `planned/unverified`.
  3. [`tests/test_activation_dashboard_fixture_integrity.py`](file:///tests/test_activation_dashboard_fixture_integrity.py) (397 lines):
     - Updated fixture version assertion to 1.3.
     - Scenario 11 assertions verifying canonical `format_activation_id()` output and provenance linkage.
     - Added `test_requirements_domain_consistency_against_engine_types` validating default usage gating (`INACTIVE_INELIGIBLE` / `USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED`), price print gating under unknown usage, pending provenance preservation under subsequent usage uncertainty, and canonical reactivation ID format matching.
- **Verification Summary**:
  - Activation dashboard fixture integrity suite: **9 / 9 passed** in 0.69s (`pytest tests/test_activation_dashboard_fixture_integrity.py -q`).
  - Full offline repository test suite: **518 / 518 passed** in 15.96s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
  - Runtime modification audit: Exactly zero runtime files modified (`git diff 3aed45bb9e0e3b9f61bb8d02cd40cff39a5f5bae..HEAD src/` is empty).
- **Scope Compliance & Standing Invariants**:
  1. *Requirements Phase Only*: Zero runtime modifications to strategy engine, adapter, or UI files.
  2. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  3. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  4. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  5. *Branch Boundary*: Committed and pushed strictly on `requirements/activation-dashboard-acceptance`. No merging into `main`.

### HANDOFF-066: Offline Evidence Boundary Restoration, Canonical Member Keys, and Executed Lifecycle Reactivation
- **Active Branch**: `requirements/activation-dashboard-acceptance`
- **Immediate Parent Commit**: `213137d00d03f91b1edcbccf677344197f31082b` (HANDOFF-065)
- **Root Baseline Engine Commit**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)
- **Objective**: Address Perplexity's review of HANDOFF-065:
  1. *Restore Explicit Offline Evidence-Source Boundary (§4.1)*: Re-codified explicit input boundary clauses: (a) zero synthesis/interpolation of candle OHLC into prints; (b) fail-closed usage default to `UNKNOWN` rendering untouched members `INACTIVE_INELIGIBLE`; (c) coverage derived exclusively from supplied batch coverage declarations; (d) external commit events supplied strictly through offline test inputs.
  2. *Canonical Member Key Enforcement*: Formatted every member key across fixtures catalog (v1.4) and integrity tests using canonical length-prefixed `format_member_key(set_id, role)` (`MK[5:SET_1][4:TJL1]`, `MK[5:SET_1][11:TJL2_A_PLUS]`, `MK[5:SET_2][4:TJL1]`), verifying joins across membership, active activations, controllers, and history.
  3. *Controller Next-Generation Values*: Corrected rearm controller generation sequences in Scenarios 9 and 10 to `generation_seq = 2` (`cancelled_record.generation_seq + 1`), adding consistency assertions against linked terminal generation.
  4. *Executed Engine Lifecycle Reactivation*: Separated formatter validation (`test_canonical_identifier_and_key_formatters`) from real executed engine lifecycle (`test_requirements_domain_consistency_against_engine_types`), executing full sequence through `ActivationEngine`: untouched default gating -> in-zone print fails closed -> register UNUSED -> in-zone touch to gen 1 -> external commit cancels to terminal history and initializes `RearmController(generation_seq=2)` -> outside departure print arms controller -> in-zone retouch executes reactivation into generation 2 (`REARMED_PENDING`, `prior_activation_id = gen1_id`).
  5. *Corrected Lineage Metadata*: Corrected HANDOFF-065 parent hash in development status to `77645ca3d7e20e82a28e12ecc71bc98066e17e7f`.
- **Completed Deliverables**:
  1. [`docs/requirements/activation-dashboard-acceptance.md`](file:///docs/requirements/activation-dashboard-acceptance.md) (157 lines):
     - Section 4.1: Restored explicit 4-point offline evidence-source and injection boundaries alongside observation lifecycle rules.
     - Section 5: Updated Scenarios 9 & 10 controller generation sequence (`generation_seq = 2`) and consistency assertions.
  2. [`tests/fixtures/activation_dashboard_acceptance.json`](file:///tests/fixtures/activation_dashboard_acceptance.json):
     - Version 1.4 with canonical `format_member_key()` outputs across all 16 scenarios, membership, active records, rearm controllers, and terminal history.
     - Scenarios 9 & 10 rearm controllers updated to `generation_seq = 2`.
  3. [`tests/test_activation_dashboard_fixture_integrity.py`](file:///tests/test_activation_dashboard_fixture_integrity.py) (430+ lines):
     - Updated fixture catalog version assertion to 1.4.
     - Added `test_all_fixture_member_keys_canonical_format` verifying `MK[...]` format and join consistency across all display groups.
     - Updated Scenario 9 and 10 assertions for controller next-generation consistency (`controller.generation_seq == term_rec.generation_seq + 1`).
     - Added dedicated `test_canonical_identifier_and_key_formatters` validating pure formatters.
     - Executed full reactivation lifecycle through accepted engine in `test_requirements_domain_consistency_against_engine_types`.
- **Verification Summary**:
  - Activation dashboard fixture integrity suite: **11 / 11 passed** in 0.91s (`pytest tests/test_activation_dashboard_fixture_integrity.py -q`).
  - Full offline repository test suite: **519 / 519 passed** in 16.05s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
  - Runtime modification audit: Exactly zero runtime files modified (`git diff 3aed45bb9e0e3b9f61bb8d02cd40cff39a5f5bae HEAD -- src/` is empty).
- **Scope Compliance & Standing Invariants**:
  1. *Requirements Phase Only*: Zero runtime modifications to strategy engine, adapter, or UI files.
  2. *Offline Only*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  3. *Downstream Invariant*: Strictly zero usage ledger implementation, zero confirmation arbitration, zero trade entry signals.
  4. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  5. *Branch Boundary*: Committed and pushed strictly on `requirements/activation-dashboard-acceptance`. No merging into `main`.

### HANDOFF-067: Read-Only Activation Dashboard Implementation, Pure Functional Presentation, and Engine Lifecycle Invariance
- **Active Branch**: `feature/activation-dashboard`
- **Immediate Parent Commit**: `3f6689c194c95ca3761833f8831bb8a3f5b4740d` (HANDOFF-066)
- **Root Baseline Engine Commit**: `0867c740352297fb43e781fb654706218771d533` (Milestone 25 / HANDOFF-061)
- **Objective**: Implement Milestone 27 read-only activation inspection dashboard panel based on the formally accepted requirements contract (Milestone 26 / HANDOFF-066):
  1. *Pure Functional Presentation*: Implement `src/aladeen/ui/activation_inspection.py` (`build_activation_inspection_elements`) projecting immutable `ActivationSnapshot` and `TJLSnapshot` state without invoking any mutating engine or synchronizer methods (`process_event()`, `register_source_members()`, `reset()`, `sync()`).
  2. *Architecture Safeguards Verified*:
     - Mandatory non-execution disclaimer banner: `LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL` with distinct visual styling.
     - Canonical unresolved diagnostic banner: `LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED` when source TJL snapshot is unresolved.
     - Coverage & observation gating summary: renders `CoverageStatus` enum and authoritative `exact_observation_count` diagnostic without synthetic observation counter fallback.
     - Active Members & Activations table: renders state badges (`INACTIVE_ELIGIBLE`, `PENDING_ACTIVATION`, `REARMED_PENDING`, `INACTIVE_INELIGIBLE`), generation sequence, and fail-closed blocked reason labels.
     - Rearm Controllers table: renders active controller state (`CANCELLED_EXTERNAL_ENTRY`, `OUT_OF_ZONE_ARMED`), next generation (`generation_seq = 2`), and departure status.
     - Bounded Terminal Activation History table: displays up to 10 most recent records with deterministic multi-tier sorting (cancellation sequence desc, cancellation time desc, activation ID asc) and prominent total record count indicator.
     - Dedicated cancellation timestamp column vs sequence ref column (`#<seq>` vs `Unknown`).
  3. *Service Bridge*: Added optional bridge fields on `MSMServiceResult` (`activation_snapshot`, `last_synced_transition_index`, `exact_observation_count`) without altering core engine signatures.
  4. *UI Mounting*: Mounted `build_activation_inspection_elements` in `src/aladeen/ui/msm_callbacks.py` (`render_msm_inspection_table`) and exported from `src/aladeen/ui/__init__.py`.
  5. *Integration Test Suite*: Created `tests/test_activation_dashboard_integration.py` covering all 16 acceptance scenarios, repeated rendering invariance, engine purity/state preservation, missing context fallback, bounded history, and service result bridge mounting.
- **Completed Deliverables**:
  1. [`src/aladeen/ui/activation_inspection.py`](file:///src/aladeen/ui/activation_inspection.py) (584 lines): Pure functional presentation builder.
  2. [`src/aladeen/strategy/service.py`](file:///src/aladeen/strategy/service.py): 3 optional diagnostic/snapshot bridge fields on `MSMServiceResult`.
  3. [`src/aladeen/ui/msm_callbacks.py`](file:///src/aladeen/ui/msm_callbacks.py): Mounted activation inspection panel.
  4. [`src/aladeen/ui/__init__.py`](file:///src/aladeen/ui/__init__.py): Exported `build_activation_inspection_elements`.
  5. [`tests/test_activation_dashboard_integration.py`](file:///tests/test_activation_dashboard_integration.py) (544 lines): Comprehensive integration suite.
- **Verification Summary**:
  - Activation dashboard integration suite: **7 / 7 passed** in 0.76s (`pytest tests/test_activation_dashboard_integration.py -q`).
  - Activation dashboard fixture integrity suite: **11 / 11 passed** in 0.62s (`pytest tests/test_activation_dashboard_fixture_integrity.py -q`).
  - Full offline repository test suite: **527 / 527 passed** in 19.71s (`pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py`).
  - Reconciled Test Inventory: 519 baseline tests + 7 dashboard integration tests + 1 canonical key formatter test = 527 tests total.
  - Visual Limitation: Offline test suite verifies HTML DOM component tree structure and CSS styles; visual browser appearance in live Dash runtime remains unverified until live browser testing.
- **Scope Compliance & Standing Invariants**:
  1. *Pure Read-Only Presentation*: Strictly zero UI order execution, zero MT5 trading calls, zero live account modification.
  2. *Downstream Invariant*: Strictly zero confirmation arbitration/selection, zero usage ledger writes, zero trade entry signals.
  3. *Engine Integrity*: Strictly zero modification to accepted strategy engines (`msm_engine`, `choch_engine`, `iss_engine`, `tjl_coordinator`, `activation_engine`).
  4. *Core Ambiguities Preserved*: Upstream $c_1 == p_2$ boundary and ISS multi-candle pullbacks remain isolated and unresolved.
  5. *Branch Boundary*: Committed and pushed strictly on `feature/activation-dashboard`. No merging into `main`.
