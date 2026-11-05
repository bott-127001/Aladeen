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
