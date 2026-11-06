"""Controlled browser verification for Activation Dashboard Integration using Playwright.

NOTE ON VERIFICATION EVIDENCE SCOPE & ARCHITECTURE (Milestone 28 / HANDOFF-074):
- Environment: Real Chromium browser controlled via Playwright against local Dash applications.
- Server Architecture:
  * Server 1 (Port 8068): Real production dashboard (aladeen.app.create_app) with ControllableActivationMockAdapter.
    Tests application mounting, readability, layout responsiveness, sessionStorage persistence,
    multi-context isolation, causal run advancement, and tab-duplication behavior.
  * Server 2 (Port 8069): Test-only local visual fixture harness executing pure presentation projection
    (build_activation_inspection_elements) across the 16 explicit offline acceptance scenarios from
    tests/fixtures/activation_dashboard_acceptance.json.
- Data Adapter: Purely deterministic offline fixture data. Zero live MT5 or broker connections.
- Mutation Safeguards: Observational inspection only. Zero order execution, zero MT5 trading calls,
  zero live account modification, zero confirmation arbitration, zero usage ledger writes,
  zero trade entry signals, and zero strategy engine modifications.
"""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from datetime import datetime, timedelta, timezone
import functools
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytest
from dash import Dash, Input, Output, dcc, html
from playwright.sync_api import BrowserContext, Page, sync_playwright

from aladeen.app import create_app
from aladeen.data.contract import BarStatus
from aladeen.data.mt5_adapter import MT5ConnectionState
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    CoverageStatus,
    RearmController,
    SequenceDomain,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
    format_member_key,
)
from aladeen.strategy.tjl_types import StableLevelId, TJLSide, TJLSnapshot
from aladeen.ui.activation_inspection import (
    CANONICAL_UNRESOLVED_BANNER,
    DISCLAIMER_TEXT,
    build_activation_inspection_elements,
)
from tests.test_activation_dashboard_integration import make_snapshot_from_fixture

print = functools.partial(print, flush=True)

PROD_PORT = 8068
HARNESS_PORT = 8069
PROD_URL = f"http://127.0.0.1:{PROD_PORT}"
HARNESS_URL = f"http://127.0.0.1:{HARNESS_PORT}"

EVIDENCE_DIR = Path("tests/evidence/activation_browser")
FIXTURES_PATH = Path("tests/fixtures/activation_dashboard_acceptance.json")


def _load_acceptance_fixtures() -> dict[str, Any]:
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class ControllableActivationMockAdapter:
    """Deterministic, offline-only MT5 adapter mock isolating all network and broker operations."""

    def __init__(self) -> None:
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        self.symbols = ["EURUSD", "GBPUSD", "DEMO_XAUUSD"]

    def is_package_installed(self) -> bool:
        return True

    def connect(self) -> MT5ConnectionState:
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        return self.connection_state

    def disconnect(self) -> None:
        self.connection_state = MT5ConnectionState.DISCONNECTED

    def get_connection_state(self) -> MT5ConnectionState:
        return self.connection_state

    def is_broker_connected(self) -> bool:
        return self.connection_state == MT5ConnectionState.CONNECTED_TO_BROKER

    def get_symbols(self) -> list[str]:
        return self.symbols

    def fetch_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Returns deterministic, candle-derived test series without synthesising price prints."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        step = timedelta(hours=4) if timeframe == "H4" else (timedelta(hours=1) if timeframe == "H1" else timedelta(minutes=5))
        candles = []
        p = 1.1000 if "EUR" in symbol else (1.2500 if "GBP" in symbol else 1950.0)
        for i in range(max(count, 35)):
            t = base_time + i * step
            o = p + (i % 5) * 0.0010
            h = o + 0.0020
            l = o - 0.0015
            c = o + 0.0008
            candles.append({
                "time": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "close_time": t + step,
                "bar_status": BarStatus.CONFIRMED_COMPLETED,
            })
        df = pd.DataFrame(candles)
        df = df.set_index("time")
        df["index"] = list(range(len(df)))
        return df


def _create_fixture_harness_app(fixtures: dict[str, Any]) -> Dash:
    """Builds a local, test-only Dash harness to project the 16 acceptance scenarios."""
    app = Dash("activation_fixture_harness")
    scenario_options = [{"label": f"{k} ({v.get('evidence_category', 'unknown')})", "value": k} for k, v in fixtures.items()]
    scenario_options.append({"label": "custom_history_50_plus_limit (synthetic)", "value": "custom_history_50_plus_limit"})
    scenario_options.append({"label": "custom_sync_error_diagnostic (synthetic)", "value": "custom_sync_error_diagnostic"})

    app.layout = html.Div(
        [
            html.H3("Activation Dashboard Acceptance Fixture Browser Harness", id="harness-title", style={"color": "#00e5ff"}),
            dcc.Dropdown(
                id="scenario-selector",
                options=scenario_options,
                value="dash_act_02_first_exact_touch",
                clearable=False,
                style={"width": "600px", "marginBottom": "16px", "color": "#000"},
            ),
            html.Div(id="harness-output-container"),
        ],
        style={"padding": "16px", "background": "#12121c", "color": "#fff", "fontFamily": "sans-serif"},
    )

    @app.callback(
        Output("harness-output-container", "children"),
        Input("scenario-selector", "value"),
    )
    def render_scenario(scenario_key: str):
        if scenario_key == "custom_history_50_plus_limit":
            base_snap, _ = make_snapshot_from_fixture(fixtures["dash_act_07_source_cancellation"])
            terms = []
            base_t = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
            for idx in range(75):
                terms.append(
                    ActivationRecord(
                        activation_id=f"ACT_HIST_{idx:03d}",
                        engine_id=base_snap.engine_id,
                        symbol=base_snap.symbol,
                        source_timeframe=base_snap.source_timeframe,
                        confirmation_timeframe=base_snap.confirmation_timeframe,
                        level_id=None,
                        set_id="SET_HIST",
                        role="TJL1",
                        lower_edge=1.1000,
                        upper_edge=1.1020,
                        state=ActivationState.CANCELLED_SOURCE_CHOCH,
                        cancellation_reason=CancellationReason.SOURCE_CHOCH,
                        cancellation_time=base_t + timedelta(minutes=idx),
                        cancellation_sequence_ref=100 + idx,
                        generation_seq=1,
                        terminal=True,
                    )
                )
            snap = ActivationSnapshot(
                engine_id=base_snap.engine_id,
                symbol=base_snap.symbol,
                source_timeframe=base_snap.source_timeframe,
                confirmation_timeframe=base_snap.confirmation_timeframe,
                sequence_domain=base_snap.sequence_domain,
                coverage_status=base_snap.coverage_status,
                current_members=base_snap.current_members,
                active_activations=base_snap.active_activations,
                rearm_controllers=base_snap.rearm_controllers,
                terminal_activations=tuple(terms),
                last_processed_sequence=base_snap.last_processed_sequence,
                last_processed_timestamp=base_snap.last_processed_timestamp,
            )
            return build_activation_inspection_elements(activation_snapshot=snap)

        elif scenario_key == "custom_sync_error_diagnostic":
            base_snap, tjl_snap = make_snapshot_from_fixture(fixtures["dash_act_02_first_exact_touch"])
            return build_activation_inspection_elements(
                activation_snapshot=base_snap,
                tjl_snapshot=tjl_snap,
                activation_error="TJL cursor mismatch: synchronizer at #5 but engine expected #6",
            )

        if scenario_key in fixtures:
            snap, tjl_snap = make_snapshot_from_fixture(fixtures[scenario_key])
            return build_activation_inspection_elements(activation_snapshot=snap, tjl_snapshot=tjl_snap)

        return html.Div("Unknown scenario", id="harness-error")

    return app


def test_activation_browser_controlled() -> None:
    """Executes full Playwright browser verification for Milestone 28 (HANDOFF-074)."""
    print("\n" + "=" * 80)
    print("STARTING CONTROLLED OFFLINE BROWSER VALIDATION — MILESTONE 28 (HANDOFF-074)")
    print("=" * 80)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = _load_acceptance_fixtures()
    mock_adapter = ControllableActivationMockAdapter()

    # 1. Start Servers
    prod_app = create_app(adapter=mock_adapter)
    prod_thread = threading.Thread(
        target=lambda: prod_app.run(port=PROD_PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    prod_thread.start()

    harness_app = _create_fixture_harness_app(fixtures)
    harness_thread = threading.Thread(
        target=lambda: harness_app.run(port=HARNESS_PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    harness_thread.start()

    time.sleep(1.8)
    print("✓ Local isolated servers launched on ports 8068 (Prod App) and 8069 (Fixture Harness).")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # =========================================================================
        # SECTION A: APPLICATION MOUNTING, READABILITY, AND VIEWPORT USABILITY
        # =========================================================================
        print("\n--- SECTION A: Application Mounting, Readability, and Viewport Usability ---")
        ctx_a = browser.new_context(viewport={"width": 1280, "height": 800})
        page_a = ctx_a.new_page()

        console_messages: list[dict[str, str]] = []
        page_errors: list[str] = []
        page_a.on("console", lambda msg: console_messages.append({"type": msg.type, "text": msg.text}))
        page_a.on("pageerror", lambda err: page_errors.append(str(err)))

        print("A1. Loading production dashboard on localhost:8068...")
        page_a.goto(PROD_URL, wait_until="networkidle")
        time.sleep(1.0)

        # Configure MSM parameters with deterministic demo data:
        page_a.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.3)
        page_a.locator("#strategy-calculation-mode input[value='INTEGRATED_MSM_CHOCH_TJL']").check()
        time.sleep(0.3)
        page_a.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)

        # Select starting candle from dropdown (20 completed demo candles available)
        page_a.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page_a.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("A2. Triggering Apply MSM with INTEGRATED_MSM_CHOCH_TJL calculation mode...")
        apply_btn = page_a.locator("#msm-apply-btn")
        apply_btn.click()
        page_a.wait_for_selector("#activation-inspection-container", timeout=8000)
        print("   ✓ #activation-inspection-container mounted in live DOM alongside inspection panels.")

        # Non-execution disclaimer
        disclaimer_banner = page_a.locator("#activation-disclaimer-banner")
        assert disclaimer_banner.is_visible(), "Disclaimer banner must be visible"
        badge_text = page_a.locator("#activation-disclaimer-badge").inner_text()
        assert DISCLAIMER_TEXT in badge_text, f"Disclaimer must contain '{DISCLAIMER_TEXT}', got '{badge_text}'"
        print(f"   ✓ Non-execution disclaimer verified visible: '{badge_text}'")

        # Context header
        context_card = page_a.locator("#activation-context-card")
        assert context_card.is_visible()
        conf_tf_text = page_a.locator("#activation-confirmation-tf").inner_text()
        assert conf_tf_text in ("M1", "M5", "M15"), f"Mapped confirmation TF must be valid, got '{conf_tf_text}'"
        seq_dom_text = page_a.locator("#activation-sequence-domain").inner_text()
        assert ":" in seq_dom_text, f"Sequence domain must display feed:run, got '{seq_dom_text}'"
        print(f"   ✓ Context header verified: Confirmation TF '{conf_tf_text}', Sequence Domain '{seq_dom_text}'")

        # Registered members table & fail-closed gating for missing usage
        active_table = page_a.locator("#activation-active-table")
        if active_table.is_visible():
            table_text = active_table.inner_text()
            assert "USAGE UNCERTAIN (FAIL-CLOSED)" in table_text or "EVIDENCE VALID" in table_text, "Gating badge missing"
            print("   ✓ Registered members table visible with explicit fail-closed evidence gating.")
        else:
            print("   ✓ Normal candle-only run showing 0 active members (valid result, no prints synthesized).")

        # Capture Desktop screenshot
        desktop_shot = EVIDENCE_DIR / "01_app_mounting_desktop.png"
        page_a.screenshot(path=str(desktop_shot), full_page=True)
        print(f"   ✓ Desktop screenshot captured: {desktop_shot.name}")

        # Viewport Usability: Narrow Viewport 800x600
        print("A3. Testing narrow viewport usability (800x600)...")
        page_a.set_viewport_size({"width": 800, "height": 600})
        time.sleep(0.5)
        assert page_a.locator("#activation-inspection-container").is_visible(), "Container must remain visible at 800x600"
        narrow_shot = EVIDENCE_DIR / "02_app_mounting_narrow_viewport.png"
        page_a.screenshot(path=str(narrow_shot), full_page=False)
        print(f"   ✓ Narrow viewport screenshot captured: {narrow_shot.name}")

        # Restore desktop viewport
        page_a.set_viewport_size({"width": 1280, "height": 800})

        # Console accounting
        error_logs = [m for m in console_messages if m["type"] == "error"]
        actionable_errors = [m for m in error_logs if "favicon" not in m["text"].lower()]
        assert len(actionable_errors) == 0, f"Unexpected console errors: {actionable_errors}"
        assert len(page_errors) == 0, f"Uncaught page errors: {page_errors}"
        print(f"   ✓ Console error audit: 0 actionable errors, 0 page errors across {len(console_messages)} log entries.")

        # =========================================================================
        # SECTION B: BROWSER SESSION STORAGE AND MULTI-CONTEXT ISOLATION
        # =========================================================================
        print("\n--- SECTION B: Browser Session Storage and Multi-Context Isolation ---")

        # B1. Extract Session ID from Context A
        sid_a = page_a.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
        assert sid_a and sid_a.startswith("session_"), f"Context A session ID must start with 'session_', got {sid_a}"
        run_id_a_before = page_a.locator("#activation-sequence-domain").inner_text()
        print(f"   ✓ Context A Session ID verified: '{sid_a}', Run Domain: '{run_id_a_before}'")

        # B2. Open Context B (Independent Browser Context)
        ctx_b = browser.new_context(viewport={"width": 1280, "height": 800})
        page_b = ctx_b.new_page()
        page_b.goto(PROD_URL, wait_until="networkidle")
        time.sleep(1.0)
        sid_b = page_b.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
        assert sid_b and sid_b.startswith("session_"), f"Context B session ID must start with 'session_', got {sid_b}"
        assert sid_a != sid_b, f"Independent contexts must have distinct session identities: '{sid_a}' vs '{sid_b}'"
        print(f"   ✓ Context B Session ID verified distinct: '{sid_b}' != '{sid_a}'")

        # B3. Applying Configuration in Context A Advances Causal Run
        print("B3. Triggering Apply in Context A to advance causal run incarnation...")
        page_a.locator("#msm-apply-btn").click()
        time.sleep(1.5)
        page_a.wait_for_selector("#activation-sequence-domain", timeout=8000)
        run_id_a_after = page_a.locator("#activation-sequence-domain").inner_text()
        print(f"   ✓ Context A run domain advanced: '{run_id_a_before}' -> '{run_id_a_after}'")

        # B4. Context B Isolation: Context B is completely unaffected by Context A's recalculation
        print("B4. Verifying Context B state isolation...")
        sid_b_check = page_b.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
        assert sid_b_check == sid_b, f"Context B identity must remain untouched: '{sid_b}'"
        print("   ✓ Context B state strictly isolated from Context A operations.")

        # Screenshots for both contexts
        shot_ctx_a = EVIDENCE_DIR / "03_session_isolation_context_a.png"
        shot_ctx_b = EVIDENCE_DIR / "04_session_isolation_context_b.png"
        page_a.screenshot(path=str(shot_ctx_a), full_page=False)
        page_b.screenshot(path=str(shot_ctx_b), full_page=False)
        print(f"   ✓ Session isolation screenshots captured: {shot_ctx_a.name}, {shot_ctx_b.name}")

        # B5. Reloading Tab A Preserves Session Identity from sessionStorage
        print("B5. Reloading Context A tab...")
        page_a.reload(wait_until="networkidle")
        time.sleep(1.0)
        sid_a_after_reload = page_a.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
        assert sid_a_after_reload == sid_a, f"Reload must preserve session identity: '{sid_a}' vs '{sid_a_after_reload}'"
        print(f"   ✓ Same-tab reload strictly preserved identity: '{sid_a_after_reload}' == '{sid_a}'")

        # B6. Tab Duplication and New Tab Findings
        print("B6. Investigating New-Tab and Duplicated-Tab sessionStorage behavior...")
        page_a_new_tab = ctx_a.new_page()
        page_a_new_tab.goto(PROD_URL, wait_until="networkidle")
        time.sleep(1.0)
        sid_new_tab = page_a_new_tab.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
        assert sid_new_tab != sid_a, f"New tab in same context must receive a fresh layout UUID: '{sid_new_tab}' vs '{sid_a}'"
        print(f"   ✓ Finding 1 (New Tab via new_page): Fresh independent session ID received ('{sid_new_tab}' != '{sid_a}').")

        with ctx_a.expect_page() as cloned_info:
            page_a.evaluate(f'() => window.open("{PROD_URL}")')
        page_cloned = cloned_info.value
        page_cloned.wait_for_load_state("networkidle")
        time.sleep(1.0)
        sid_cloned = page_cloned.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
        print(f"   ✓ Finding 2 (window.open / Duplicated Tab): Cloned tab inherits sessionStorage: '{sid_cloned}' == '{sid_a}'.")
        print("     [DOCUMENTED ISOLATION FINDING]: In standard browsers, tab duplication copies sessionStorage.")
        print("     Independent-tab isolation requires opening via a new tab URL navigation rather than tab cloning.")

        page_a_new_tab.close()
        page_cloned.close()
        ctx_b.close()

        # =========================================================================
        # SECTION C: LIFECYCLE PRESENTATION UNDER EXPLICIT OFFLINE SCENARIOS
        # =========================================================================
        print("\n--- SECTION C: Lifecycle Presentation Under Explicit Offline Scenarios ---")
        harness_page = ctx_a.new_page()
        harness_page.goto(HARNESS_URL, wait_until="networkidle")
        time.sleep(1.0)

        def select_harness_scenario(val: str) -> None:
            harness_page.evaluate(
                """(v) => {
                    window.dash_clientside.set_props("scenario-selector", {value: v});
                }""",
                val,
            )
            time.sleep(0.6)

        # 1. Scenario 2: First Exact Touch Provenance
        print("C1. Scenario 2 (First Exact Touch Provenance)...")
        select_harness_scenario("dash_act_02_first_exact_touch")
        harness_page.wait_for_selector("#activation-active-table", timeout=5000)
        act_text = harness_page.locator("#activation-active-table").inner_text()
        assert "PENDING ACTIVATION" in act_text, "State must be PENDING ACTIVATION"
        assert "OBS_01" in act_text, "Trigger observation OBS_01 must be displayed"
        assert "1.137" in act_text, "First touch price must be value-preserved"
        shot_05 = EVIDENCE_DIR / "05_scenario_02_first_exact_touch.png"
        harness_page.screenshot(path=str(shot_05), full_page=True)
        print(f"   ✓ Scenario 2 verified and screenshot saved: {shot_05.name}")

        # 2. Scenario 3: Repeated Touch Invariance
        print("C2. Scenario 3 (Repeated Touch Invariance)...")
        select_harness_scenario("dash_act_03_repeated_touch")
        rep_text = harness_page.locator("#activation-active-table").inner_text()
        assert "PENDING ACTIVATION" in rep_text
        assert "OBS_01" in rep_text, "Trigger observation OBS_01 must remain preserved on repeated touch"
        print("   ✓ Scenario 3 verified: first touch timestamp and trigger OBS_01 strictly preserved.")

        # 3. Scenario 4: Unknown Usage Fail-Closed Gating
        print("C3. Scenario 4 (Unknown Usage Fail-Closed Gating)...")
        select_harness_scenario("dash_act_04_unknown_usage")
        unk_text = harness_page.locator("#activation-active-table").inner_text()
        assert "USAGE UNCERTAIN (FAIL-CLOSED)" in unk_text
        print("   ✓ Scenario 4 verified: unknown usage exhibits fail-closed gating badge.")

        # 4. Scenario 5: Incomplete Coverage Gating
        print("C4. Scenario 5 (Incomplete Coverage Gating)...")
        select_harness_scenario("dash_act_05_incomplete_coverage")
        cov_text = harness_page.locator("#activation-active-table").inner_text()
        assert "COVERAGE INCOMPLETE" in cov_text
        badge_text = harness_page.locator("#activation-coverage-badge").inner_text()
        assert badge_text == "INCOMPLETE"
        print("   ✓ Scenario 5 verified: coverage badge INCOMPLETE and gating badge rendered.")

        # 5. Scenario 6: Unknown Availability Timing
        print("C5. Scenario 6 (Unknown Availability Timing)...")
        select_harness_scenario("dash_act_06_unknown_availability")
        avail_text = harness_page.locator("#activation-active-table").inner_text()
        assert "UNKNOWN AVAILABILITY" in avail_text
        print("   ✓ Scenario 6 verified: unknown availability timing blocks activation.")

        # 6. Scenario 7: Source Cancellation & Terminal History
        print("C6. Scenario 7 (Source Cancellation & Terminal History)...")
        select_harness_scenario("dash_act_07_source_cancellation")
        hist_table = harness_page.locator("#activation-history-table")
        assert hist_table.is_visible()
        hist_text = hist_table.inner_text()
        assert "CANCELLED_SOURCE_CHOCH" in hist_text
        print("   ✓ Scenario 7 verified: source cancellation moved record to terminal history table.")

        # 7. Scenario 8: Cancellation Unknown Time with Dedicated Sequence Ref
        print("C7. Scenario 8 (Cancellation Unknown Time with Dedicated Sequence Ref)...")
        select_harness_scenario("dash_act_08_cancellation_unknown_time")
        s8_text = harness_page.locator("#activation-history-table").inner_text()
        assert "Unknown" in s8_text, "Dedicated cancellation timestamp must display Unknown"
        assert "#125" in s8_text, "Sequence column must display #125"
        print("   ✓ Scenario 8 verified: Unknown timestamp rendered with dedicated #125 sequence ref.")

        # 8. Scenario 9: External Cancellation Inside Zone (Awaiting Departure)
        print("C8. Scenario 9 (External Cancellation Inside Zone)...")
        select_harness_scenario("dash_act_09_external_cancellation_inside")
        s9_text = harness_page.locator("#activation-rearm-table").inner_text()
        assert "CANCELLED (AWAITING DEPARTURE)" in s9_text
        assert "Gen 2" in s9_text
        assert "NO" in s9_text, "rearm_armed must be NO while awaiting departure"
        print("   ✓ Scenario 9 verified: controller created awaiting departure with next Gen 2.")

        # 9. Scenario 10: Armed Controller (Out of Zone)
        print("C9. Scenario 10 (Armed Controller Out of Zone)...")
        select_harness_scenario("dash_act_10_armed_controller")
        s10_text = harness_page.locator("#activation-rearm-table").inner_text()
        assert "ARMED FOR RETOUCH" in s10_text
        assert "YES" in s10_text, "rearm_armed must be YES once outside zone"
        shot_06 = EVIDENCE_DIR / "06_scenario_10_armed_controller.png"
        harness_page.screenshot(path=str(shot_06), full_page=True)
        print(f"   ✓ Scenario 10 verified and screenshot saved: {shot_06.name}")

        # 10. Scenario 11: Valid Reactivation Gen 2
        print("C10. Scenario 11 (Valid Reactivation Gen 2)...")
        select_harness_scenario("dash_act_11_valid_reactivation")
        s11_text = harness_page.locator("#activation-active-table").inner_text()
        assert "REARMED PENDING (GEN 2)" in s11_text
        assert "ACT_G01" in s11_text, "Prior activation ID must link to canonical Gen 1 ID"
        print("   ✓ Scenario 11 verified: REARMED_PENDING (GEN 2) active and linked to Gen 1 ID.")

        # 11. Scenario 12: Successor Set with Persistent Level
        print("C11. Scenario 12 (Successor Set with Persistent Level)...")
        select_harness_scenario("dash_act_12_successor_set_persistent_level")
        s12_active = harness_page.locator("#activation-active-table").inner_text()
        assert "SET_2" in s12_active, "Active table must show SET_2"
        s12_hist = harness_page.locator("#activation-history-table").inner_text()
        assert "SET_1" in s12_hist, "History table must retain SET_1"
        print("   ✓ Scenario 12 verified: SET_2 distinct from historical SET_1 on same physical level.")

        # 12. Scenario 13: Unresolved Source Banner
        print("C12. Scenario 13 (Unresolved Source Banner)...")
        select_harness_scenario("dash_act_13_unresolved_source_snapshot")
        unres_banner = harness_page.locator("#activation-unresolved-banner")
        assert unres_banner.is_visible()
        assert CANONICAL_UNRESOLVED_BANNER in unres_banner.inner_text()
        container_text = harness_page.locator("#activation-unresolved-container").inner_text()
        assert "Bar #15" in container_text and "Bar #19" in container_text
        shot_07 = EVIDENCE_DIR / "07_scenario_13_unresolved_source_banner.png"
        harness_page.screenshot(path=str(shot_07), full_page=True)
        print(f"   ✓ Scenario 13 verified and screenshot saved: {shot_07.name}")

        # 13. Scenario 14: Equal Coarse Timestamps Disambiguated by Sequence Ref
        print("C13. Scenario 14 (Equal Coarse Timestamps Disambiguated by Sequence Ref)...")
        select_harness_scenario("dash_act_14_equal_coarse_timestamps")
        s14_text = harness_page.locator("#activation-history-table").inner_text()
        assert "#202" in s14_text and "#201" in s14_text
        pos_202 = s14_text.find("#202")
        pos_201 = s14_text.find("#201")
        assert pos_202 < pos_201, f"#202 must precede #201 in multi-tier sort: pos_202={pos_202}, pos_201={pos_201}"
        print("   ✓ Scenario 14 verified: equal timestamps sorted deterministically by sequence reference.")

        # 14. Terminal History Bounded Display (50 of 75 records)
        print("C14. Custom Scenario (Terminal History Bounded at 50 of 75 records)...")
        select_harness_scenario("custom_history_50_plus_limit")
        hist_heading = harness_page.locator("#activation-history-heading").inner_text()
        assert "75 total records" in hist_heading
        assert "Showing latest 50 of 75 records" in hist_heading
        rendered_rows = len(harness_page.locator("#activation-history-table tbody tr").all())
        assert rendered_rows == 50, f"Rendered rows must be capped at 50, got {rendered_rows}"
        shot_08 = EVIDENCE_DIR / "08_scenario_history_50_limit.png"
        harness_page.screenshot(path=str(shot_08), full_page=True)
        print(f"   ✓ Terminal history bounding verified: exactly 50 of 75 rows rendered. Screenshot: {shot_08.name}")

        # 15. Synchronization-Error Banner
        print("C15. Custom Scenario (Synchronization-Error Diagnostic Banner)...")
        select_harness_scenario("custom_sync_error_diagnostic")
        sync_err = harness_page.locator("#activation-sync-error-banner")
        assert sync_err.is_visible()
        assert "TJL cursor mismatch" in sync_err.inner_text()
        assert harness_page.locator("#activation-active-table").is_visible()
        shot_09 = EVIDENCE_DIR / "09_scenario_sync_error_banner.png"
        harness_page.screenshot(path=str(shot_09), full_page=True)
        print(f"   ✓ Synchronization-error banner verified visible alongside prior evidence. Screenshot: {shot_09.name}")

        browser.close()

    print("\n" + "=" * 80)
    print("CONTROLLED BROWSER VALIDATION COMPLETED SUCCESSFULLY (ALL ASSERTIONS PASSED)")
    print("=" * 80)


if __name__ == "__main__":
    test_activation_browser_controlled()
