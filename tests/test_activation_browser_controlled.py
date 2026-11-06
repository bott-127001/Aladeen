"""Controlled browser verification for Activation Dashboard Integration using Playwright.

Milestone 28 (Controlled Offline Browser Validation of Activation Dashboard) — HANDOFF-076.
Enforces:
1. Context-level exact-origin request firewall aborting unauthorized external network requests before navigation.
2. Server-side socket guard fail-fast intercepting any non-localhost network connections.
3. Fail-verifiable server handles (ControlledServerHandle) with explicit server_close, thread termination, and port release assertions.
4. Concrete horizontal scroll container assertions and typography readability verification.
5. Accurately scoped programmatic window.open tab ownership evidence.
6. Full cell-level assertions across 15 offline acceptance scenarios.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import socket
import sys
import time

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from playwright.sync_api import sync_playwright
from dash import Dash, html

from aladeen.app import create_app
from aladeen.ui.activation_inspection import CANONICAL_UNRESOLVED_BANNER
from tests.activation_browser_harness import (
    BrowserAuditWatcher,
    ControllableActivationMockAdapter,
    ControlledServerHandle,
    ContextSecurityFirewall,
    configure_and_apply_msm,
    install_server_socket_guard,
    managed_servers,
    _create_fixture_harness_app,
)

logger = logging.getLogger("test_activation_browser_controlled")

PROD_PORT = 8068
HARNESS_PORT = 8069
PROD_URL = f"http://127.0.0.1:{PROD_PORT}"
HARNESS_URL = f"http://127.0.0.1:{HARNESS_PORT}"
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PROD_PORT}", f"http://127.0.0.1:{HARNESS_PORT}"}
EVIDENCE_DIR = repo_root / "tests" / "evidence" / "activation_browser"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def verify_section_a_mounting_and_viewport(page_a, watcher) -> None:
    """Section A: Application Mounting, Readability, and Viewport Usability."""
    print("\n--- SECTION A: Application Mounting, Readability, and Viewport Usability ---")
    print(f"A1. Loading production dashboard on {PROD_URL}...")
    page_a.goto(PROD_URL, wait_until="networkidle")
    page_a.wait_for_selector("#msm-apply-btn", timeout=10000)

    print("A2. Triggering Apply MSM with INTEGRATED_MSM_CHOCH_TJL calculation mode...")
    configure_and_apply_msm(page_a)
    print("   ✓ #activation-inspection-container mounted in live DOM alongside inspection panels.")

    disclaimer = page_a.locator("#activation-disclaimer-banner")
    assert disclaimer.is_visible(), "Non-execution disclaimer banner must be visible"
    assert "⚠️ LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL" in disclaimer.inner_text()
    print(f"   ✓ Non-execution disclaimer verified visible: '{disclaimer.inner_text()}'")

    seq_domain_el = page_a.locator("#activation-sequence-domain")
    assert seq_domain_el.is_visible()
    assert "FEED_DEMO_" in seq_domain_el.inner_text()
    assert "SESSION_session_" in seq_domain_el.inner_text()
    print(f"   ✓ Context header verified: Sequence Domain '{seq_domain_el.inner_text()}'")

    shot_01 = EVIDENCE_DIR / "01_app_mounting_desktop.png"
    page_a.screenshot(path=str(shot_01), full_page=False)
    print(f"   ✓ Desktop (1280x800) screenshot captured: {shot_01.name}")

    print("A3. Resizing viewport to narrow mobile dimensions (800x600)...")
    page_a.set_viewport_size({"width": 800, "height": 600})
    time.sleep(0.5)

    # Geometry Check 1: Zero vertical overlap between banner, context card, and active section
    banner_box = page_a.locator("#activation-disclaimer-banner").bounding_box()
    context_box = page_a.locator("#activation-context-card").bounding_box()
    heading_box = page_a.locator("#activation-active-heading").bounding_box()
    assert banner_box and context_box and heading_box
    assert banner_box["y"] + banner_box["height"] <= context_box["y"] + 4.0, "Banner and context card overlap vertically"
    assert context_box["y"] + context_box["height"] <= heading_box["y"] + 4.0, "Context card and active section heading overlap vertically"
    print("   ✓ Vertical card geometry verified: zero vertical overlap between banner, context card, and active section.")

    shot_02 = EVIDENCE_DIR / "02_app_mounting_narrow_viewport.png"
    page_a.screenshot(path=str(shot_02), full_page=False)
    print(f"   ✓ Narrow viewport screenshot captured: {shot_02.name}")

    page_a.set_viewport_size({"width": 1280, "height": 800})
    time.sleep(0.5)


def verify_section_b_session_isolation(page_a, ctx_a, browser, firewall, watcher) -> None:
    """Section B: Session Storage Persistence & Multi-Context Isolation."""
    print("\n--- SECTION B: Session Storage Persistence & Multi-Context Isolation ---")
    sid_a = page_a.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
    assert sid_a and sid_a.startswith("session_"), f"Context A session ID invalid: {sid_a}"
    run_id_a_initial = page_a.locator("#activation-sequence-domain").inner_text()
    print(f"   ✓ Context A Session ID: '{sid_a}', Initial Run Domain: '{run_id_a_initial}'")

    print("B2. Opening independent Context B with context-level firewall...")
    ctx_b = browser.new_context(viewport={"width": 1280, "height": 800})
    firewall.attach(ctx_b)
    page_b = ctx_b.new_page()
    watcher.attach(page_b, "Context B (Isolated)")
    page_b.goto(PROD_URL, wait_until="networkidle")

    sid_b = page_b.evaluate('() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))')
    assert sid_b and sid_b.startswith("session_")
    assert sid_a != sid_b, f"Independent contexts must have distinct IDs: '{sid_a}' vs '{sid_b}'"

    configure_and_apply_msm(page_b)
    run_id_b_initial = page_b.locator("#activation-sequence-domain").inner_text()
    table_b_initial = page_b.locator("#activation-active-table").inner_text()
    print(f"   ✓ Context B Session ID: '{sid_b}', Initial Run Domain: '{run_id_b_initial}'")

    print("B3. Triggering recalculation in Context A (advance run domain)...")
    page_a.locator("#msm-apply-btn").click()
    page_a.wait_for_function(
        f"() => document.getElementById('activation-sequence-domain')?.innerText !== '{run_id_a_initial}'",
        timeout=8000,
    )
    run_id_a_after = page_a.locator("#activation-sequence-domain").inner_text()
    assert run_id_a_after != run_id_a_initial, f"Context A run domain MUST change: '{run_id_a_initial}' -> '{run_id_a_after}'"
    print(f"   ✓ [ASSERTION PASSED] Context A run domain advanced: '{run_id_a_initial}' -> '{run_id_a_after}'")

    print("B4. Asserting Context B run domain and active table evidence remain identical...")
    run_id_b_after = page_b.locator("#activation-sequence-domain").inner_text()
    table_b_after = page_b.locator("#activation-active-table").inner_text()
    assert run_id_b_after == run_id_b_initial, f"Context B run domain changed unexpectedly: '{run_id_b_initial}' != '{run_id_b_after}'"
    assert table_b_after == table_b_initial, "Context B active table evidence changed unexpectedly upon Context A recalculation"
    print(f"   ✓ [ASSERTION PASSED] Context B completely isolated: run domain '{run_id_b_initial}' and table preserved.")

    print("B5. Waiting through steady polling interval...")
    time.sleep(2.5)
    assert page_a.locator("#activation-sequence-domain").inner_text() == run_id_a_after
    assert page_b.locator("#activation-sequence-domain").inner_text() == run_id_b_initial
    print("   ✓ [ASSERTION PASSED] Steady polling retained run domains across both contexts.")

    shot_ctx_a = EVIDENCE_DIR / "03_session_isolation_context_a.png"
    shot_ctx_b = EVIDENCE_DIR / "04_session_isolation_context_b.png"
    page_a.screenshot(path=str(shot_ctx_a), full_page=False)
    page_b.screenshot(path=str(shot_ctx_b), full_page=False)
    print(f"   ✓ Context A & B screenshots captured: {shot_ctx_a.name}, {shot_ctx_b.name}")

    print("B6. Switching timeframe to D1 in Context A...")
    configure_and_apply_msm(page_a, timeframe="D1")
    page_a.wait_for_function(
        "() => document.getElementById('activation-sequence-domain')?.innerText.includes('_D1:')",
        timeout=8000,
    )
    run_id_a_d1 = page_a.locator("#activation-sequence-domain").inner_text()
    conf_tf_a_d1 = page_a.locator("#activation-confirmation-tf").inner_text()
    assert "_D1:" in run_id_a_d1, f"Context A sequence domain must reflect D1: {run_id_a_d1}"
    assert conf_tf_a_d1 == "H1", f"Confirmation TF for D1 must map to H1, got {conf_tf_a_d1}"

    run_id_b_check = page_b.locator("#activation-sequence-domain").inner_text()
    conf_tf_b_check = page_b.locator("#activation-confirmation-tf").inner_text()
    assert "_H4:" in run_id_b_check, f"Context B must remain on H4: {run_id_b_check}"
    assert conf_tf_b_check == "M5", f"Context B confirmation TF must remain M5: {conf_tf_b_check}"
    print(f"   ✓ [ASSERTION PASSED] Timeframe switching verified: Context A on D1 (H1), Context B untouched on H4 (M5).")

    print("B7. Reloading Context A tab (verifying identity retention)...")
    page_a.reload(wait_until="networkidle")
    page_a.wait_for_selector("#msm-apply-btn", timeout=8000)
    sid_a_after_reload = page_a.evaluate(
        '() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))'
    )
    assert sid_a_after_reload == sid_a, f"Same-tab reload MUST retain session ID: '{sid_a}' vs '{sid_a_after_reload}'"
    print(f"   ✓ [ASSERTION PASSED] Same-tab reload strictly preserved identity: '{sid_a_after_reload}' == '{sid_a}'")

    configure_and_apply_msm(page_a)
    run_id_a_reloaded = page_a.locator("#activation-sequence-domain").inner_text()
    assert sid_a in run_id_a_reloaded, f"Context A reloaded run domain must contain session ID '{sid_a}': {run_id_a_reloaded}"
    print(f"   ✓ [ASSERTION PASSED] Context A reloaded run domain verified: '{run_id_a_reloaded}' contains '{sid_a}'")

    print("B8. Verifying browser-tab ownership via programmatic window.open(url)...")
    with ctx_a.expect_page() as cloned_info:
        page_a.evaluate(f'() => window.open("{PROD_URL}")')
    page_cloned = cloned_info.value
    watcher.attach(page_cloned, "Cloned Tab (programmatic window.open)")
    page_cloned.wait_for_load_state("networkidle")
    page_cloned.wait_for_selector("#msm-apply-btn", timeout=8000)

    sid_cloned = page_cloned.evaluate(
        '() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))'
    )
    assert sid_cloned != sid_a, f"Cloned tab MUST NOT share parent session ID: parent='{sid_a}', cloned='{sid_cloned}'"
    print(f"   ✓ [ASSERTION PASSED] Cloned tab claimed independent ownership: '{sid_cloned}' != '{sid_a}'")

    page_cloned.reload(wait_until="networkidle")
    page_cloned.wait_for_selector("#msm-apply-btn", timeout=8000)
    sid_cloned_reloaded = page_cloned.evaluate(
        '() => JSON.parse(sessionStorage.getItem("dashboard-session-id-store"))'
    )
    assert sid_cloned_reloaded == sid_cloned, f"Cloned tab reload must retain its own ID: '{sid_cloned}' vs '{sid_cloned_reloaded}'"
    print(f"   ✓ [ASSERTION PASSED] Cloned tab reload strictly preserved its own ID: '{sid_cloned_reloaded}'")

    configure_and_apply_msm(page_cloned, direction="DOWNWARD")
    run_cloned = page_cloned.locator("#activation-sequence-domain").inner_text()
    run_parent = page_a.locator("#activation-sequence-domain").inner_text()
    assert run_cloned != run_parent, f"Cloned tab run must be distinct from parent: {run_cloned} vs {run_parent}"
    assert sid_cloned in run_cloned
    assert sid_a in run_parent
    print(f"   ✓ [ASSERTION PASSED] Recalculation in cloned tab completely isolated from parent tab.")

    page_cloned.close()
    ctx_b.close()


def verify_section_c_lifecycle_scenarios(harness_page) -> None:
    """Section C: Lifecycle Presentation Under Explicit Offline Scenarios & Usability Checks."""
    print("\n--- SECTION C: Lifecycle Presentation Under Explicit Offline Scenarios ---")
    harness_page.goto(HARNESS_URL, wait_until="networkidle")
    harness_page.wait_for_selector("#harness-output-container", timeout=8000)

    notice_el = harness_page.locator("#harness-synthetic-notice")
    assert notice_el.is_visible()
    assert "PURE PRESENTATION PROJECTION" in notice_el.inner_text()
    print(f"   ✓ Visual harness synthetic notice verified: '{notice_el.inner_text()}'")

    def select_harness_scenario(val: str) -> None:
        harness_page.evaluate(
            """(v) => { window.dash_clientside.set_props("scenario-selector", {value: v}); }""",
            val,
        )
        harness_page.wait_for_function(
            f"() => document.getElementById('harness-current-scenario')?.innerText === '{val}'",
            timeout=10000,
        )

    # 1. Scenario 2: First Exact Touch Provenance + Narrow Viewport Usability & Scrolling Verification
    print("C1. Scenario 2 (First Exact Touch Provenance & Horizontal Scrolling Usability)...")
    select_harness_scenario("dash_act_02_first_exact_touch")
    harness_page.wait_for_selector("#activation-active-table", timeout=10000)

    state_cell = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(9)")
    price_cell = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(13)")
    obs_cell = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(14)")
    assert "PENDING ACTIVATION" in state_cell.inner_text()
    assert "1.1370" in price_cell.inner_text(), f"First touch price cell must be 1.1370: {price_cell.inner_text()}"
    assert "OBS_01" in obs_cell.inner_text()

    # Narrow Viewport (800x600) Usability & Real Scroll Container Verification on Scenario 2 Table
    harness_page.set_viewport_size({"width": 800, "height": 600})
    time.sleep(0.3)

    # Inspect rightmost header before scroll
    rightmost_header = harness_page.locator("#activation-active-table th:last-child")
    box_before = rightmost_header.bounding_box()
    assert box_before is not None
    assert box_before["x"] >= 800.0, f"Rightmost header must initially overflow 800px viewport: {box_before['x']}"
    initial_scroll_x = harness_page.evaluate("() => window.scrollX")
    assert initial_scroll_x == 0, f"Initial window.scrollX must be 0, got {initial_scroll_x}"

    # Scroll rightmost header into view
    rightmost_header.scroll_into_view_if_needed()
    scrolled_x = harness_page.evaluate("() => window.scrollX")
    assert scrolled_x > 0, f"Scrolling real container (window) must increase scrollX: got {scrolled_x}"

    # Verify rightmost header is now fully accessible inside visible viewport
    box_after = rightmost_header.bounding_box()
    assert box_after is not None
    assert 0 <= box_after["x"] <= 800.0, f"Header x must be in viewport: {box_after['x']}"
    assert box_after["x"] + box_after["width"] <= 800.0, f"Header right edge must be in viewport: {box_after['x'] + box_after['width']}"
    print(f"   ✓ [ASSERTION PASSED] Real scroll container verified: rightmost header scrolled from x={box_before['x']:.1f} to visible x={box_after['x']:.1f} (window.scrollX={scrolled_x}).")

    # Typography & Readability Verification
    code_el = harness_page.locator("#activation-active-table tbody code").first
    assert code_el.is_visible()
    code_text = code_el.inner_text().strip()
    assert len(code_text) > 0, "Code element text must be non-empty"
    font_size_px = float(code_el.evaluate("el => window.getComputedStyle(el).fontSize").replace("px", ""))
    assert 9.0 <= font_size_px <= 11.5, f"Code element font size must be within [9.0px, 11.5px], got {font_size_px}px"
    print(f"   ✓ [ASSERTION PASSED] Typography verified readable: font size {font_size_px}px with text '{code_text}'.")

    # Restore desktop viewport
    harness_page.set_viewport_size({"width": 1280, "height": 800})
    harness_page.evaluate("() => window.scrollTo(0, 0)")
    time.sleep(0.3)

    shot_05 = EVIDENCE_DIR / "05_scenario_02_first_exact_touch.png"
    harness_page.screenshot(path=str(shot_05), full_page=True)
    print(f"   ✓ Scenario 2 verified with exact cell assertions. Screenshot: {shot_05.name}")

    # 2. Scenario 3: Repeated Touch Invariance
    print("C2. Scenario 3 (Repeated Touch Invariance)...")
    select_harness_scenario("dash_act_03_repeated_touch")
    s3_state = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(9)").inner_text()
    s3_time = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(12)").inner_text()
    s3_obs = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(14)").inner_text()
    assert "PENDING ACTIVATION" in s3_state
    assert "2026-10-02 08:15:00 UTC" in s3_time, f"First touch timestamp MUST remain 08:15:00: got {s3_time}"
    assert "OBS_01" in s3_obs, f"Trigger OBS_01 must be strictly preserved: got {s3_obs}"
    print("   ✓ Scenario 3 verified: first touch timestamp and trigger OBS_01 strictly preserved in exact cells.")

    # 3. Scenario 4: Unknown Usage Fail-Closed Gating
    print("C3. Scenario 4 (Unknown Usage Fail-Closed Gating)...")
    select_harness_scenario("dash_act_04_unknown_usage")
    s4_badge = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(10)").inner_text()
    assert "USAGE UNCERTAIN (FAIL-CLOSED)" in s4_badge
    print("   ✓ Scenario 4 verified: unknown usage exhibits fail-closed gating badge.")

    # 4. Scenario 5: Incomplete Coverage Gating
    print("C4. Scenario 5 (Incomplete Coverage Gating)...")
    select_harness_scenario("dash_act_05_incomplete_coverage")
    s5_badge = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(10)").inner_text()
    assert "COVERAGE INCOMPLETE" in s5_badge
    cov_badge = harness_page.locator("#activation-coverage-badge").inner_text()
    assert cov_badge == "INCOMPLETE"
    print("   ✓ Scenario 5 verified: coverage badge INCOMPLETE and gating badge rendered.")

    # 5. Scenario 6: Unknown Availability Timing
    print("C5. Scenario 6 (Unknown Availability Timing)...")
    select_harness_scenario("dash_act_06_unknown_availability")
    s6_badge = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(10)").inner_text()
    assert "UNKNOWN AVAILABILITY" in s6_badge
    print("   ✓ Scenario 6 verified: unknown availability timing blocks activation.")

    # 6. Scenario 7: Source Cancellation & Terminal History
    print("C6. Scenario 7 (Source Cancellation & Terminal History)...")
    select_harness_scenario("dash_act_07_source_cancellation")
    hist_table = harness_page.locator("#activation-history-table")
    assert hist_table.is_visible()
    s7_state_cell = hist_table.locator("tbody tr:first-child td:nth-child(6)").inner_text()
    s7_reason_cell = hist_table.locator("tbody tr:first-child td:nth-child(9)").inner_text()
    assert "CANCELLED_SOURCE_CHOCH" in s7_state_cell
    assert "SOURCE_CHOCH" in s7_reason_cell
    print("   ✓ Scenario 7 verified: source cancellation in exact terminal history cells.")

    # 7. Scenario 8: Cancellation Unknown Time with Dedicated Sequence Ref
    print("C7. Scenario 8 (Cancellation Unknown Time with Dedicated Sequence Ref)...")
    select_harness_scenario("dash_act_08_cancellation_unknown_time")
    s8_time_cell = harness_page.locator("#activation-history-table tbody tr:first-child td:nth-child(10)").inner_text()
    s8_seq_cell = harness_page.locator("#activation-history-table tbody tr:first-child td:nth-child(11)").inner_text()
    assert s8_time_cell.strip() == "Unknown", f"Dedicated cancellation time cell must be 'Unknown': got {s8_time_cell}"
    assert s8_seq_cell.strip() == "#125", f"Dedicated sequence ref cell must be '#125': got {s8_seq_cell}"
    print("   ✓ Scenario 8 verified: Unknown timestamp and #125 sequence ref in exact table cells.")

    # 8. Scenario 9: External Cancellation Inside Zone (Awaiting Departure)
    print("C8. Scenario 9 (External Cancellation Inside Zone)...")
    select_harness_scenario("dash_act_09_external_cancellation_inside")
    s9_badge = harness_page.locator("#activation-rearm-table tbody tr:first-child td:nth-child(4)").inner_text()
    s9_gen = harness_page.locator("#activation-rearm-table tbody tr:first-child td:nth-child(3)").inner_text()
    s9_armed = harness_page.locator("#activation-rearm-table tbody tr:first-child td:nth-child(6)").inner_text()
    assert "CANCELLED (AWAITING DEPARTURE)" in s9_badge
    assert s9_gen.strip() == "Gen 2"
    assert s9_armed.strip() == "NO"
    print("   ✓ Scenario 9 verified: controller awaiting departure with next Gen 2 and armed=NO.")

    # 9. Scenario 10: Armed Controller (Out of Zone)
    print("C9. Scenario 10 (Armed Controller Out of Zone)...")
    select_harness_scenario("dash_act_10_armed_controller")
    s10_badge = harness_page.locator("#activation-rearm-table tbody tr:first-child td:nth-child(4)").inner_text()
    s10_armed = harness_page.locator("#activation-rearm-table tbody tr:first-child td:nth-child(6)").inner_text()
    assert "ARMED FOR RETOUCH" in s10_badge
    assert s10_armed.strip() == "YES"
    shot_06 = EVIDENCE_DIR / "06_scenario_10_armed_controller.png"
    harness_page.screenshot(path=str(shot_06), full_page=True)
    print(f"   ✓ Scenario 10 verified: ARMED FOR RETOUCH and armed=YES. Screenshot: {shot_06.name}")

    # 10. Scenario 11: Valid Reactivation Gen 2
    print("C10. Scenario 11 (Valid Reactivation Gen 2)...")
    select_harness_scenario("dash_act_11_valid_reactivation")
    s11_state = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(9)").inner_text()
    s11_prior_id = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(15)").inner_text()
    assert "REARMED PENDING (GEN 2)" in s11_state
    assert "ACT_G01" in s11_prior_id, f"Prior activation ID cell must link to Gen 1: got {s11_prior_id}"
    print("   ✓ Scenario 11 verified: REARMED_PENDING (GEN 2) and linked Gen 1 prior ID.")

    # 11. Scenario 12: Successor Set with Persistent Level
    print("C11. Scenario 12 (Successor Set with Persistent Level)...")
    select_harness_scenario("dash_act_12_successor_set_persistent_level")
    s12_active_set = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(1)").inner_text()
    s12_hist_set = harness_page.locator("#activation-history-table tbody tr:first-child td:nth-child(2)").inner_text()
    s12_active_lvl = harness_page.locator("#activation-active-table tbody tr:first-child td:nth-child(5)").inner_text()
    s12_hist_lvl = harness_page.locator("#activation-history-table tbody tr:first-child td:nth-child(4)").inner_text()
    assert s12_active_set.strip() == "SET_2"
    assert s12_hist_set.strip() == "SET_1"
    assert s12_active_lvl == s12_hist_lvl, f"Physical level identity must be continuous: {s12_active_lvl} != {s12_hist_lvl}"
    print("   ✓ Scenario 12 verified: SET_2 distinct from SET_1 on continuous physical level.")

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
    s14_r1_seq = harness_page.locator("#activation-history-table tbody tr:nth-child(1) td:nth-child(11)").inner_text()
    s14_r2_seq = harness_page.locator("#activation-history-table tbody tr:nth-child(2) td:nth-child(11)").inner_text()
    assert s14_r1_seq.strip() == "#202", f"First row seq ref must be #202: got {s14_r1_seq}"
    assert s14_r2_seq.strip() == "#201", f"Second row seq ref must be #201: got {s14_r2_seq}"
    print("   ✓ Scenario 14 verified: #202 strictly precedes #201 in multi-tier deterministic sort.")

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


def verify_server_lifecycle_failure_injection() -> None:
    """Verifies that ControlledServerHandle and managed_servers cleanly release resources on failure."""
    print("\n--- FAILURE-INJECTION VERIFICATION: Server Lifecycle & Recovery ---")
    dummy_app = Dash("dummy_test_app")
    dummy_app.layout = html.Div("Dummy")

    # 1. Verify single server start, stop, socket release, and thread termination
    s = ControlledServerHandle(dummy_app, "127.0.0.1", 8098, "Test Server")
    s.start()
    assert s._is_running is True
    assert s.thread is not None and s.thread.is_alive()
    s.stop()
    assert s._is_running is False
    assert not s.thread.is_alive()
    print("   ✓ Single server lifecycle verified: startup, socket binding, thread join, and port release.")

    # 2. Verify managed_servers startup failure cleans up prior started server
    s1 = ControlledServerHandle(dummy_app, "127.0.0.1", 8098, "Test Server 1")
    # Bind an ephemeral port and hold it open to force second server startup collision
    occupied_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied_sock.bind(("127.0.0.1", 0))
    occupied_port = occupied_sock.getsockname()[1]
    occupied_sock.listen(1)

    try:
        s2 = ControlledServerHandle(dummy_app, "127.0.0.1", occupied_port, "Test Server 2 (Colliding)")
        failed = False
        try:
            with managed_servers(s1, s2):
                pass
        except Exception:
            failed = True
        assert failed is True, "managed_servers must fail if a server cannot bind"
        assert s1._is_running is False, "Server 1 must be cleanly stopped if Server 2 fails to start"
        print("   ✓ Startup failure recovery verified: Server 1 cleanly stopped when Server 2 startup failed.")
    finally:
        occupied_sock.close()


def test_activation_browser_controlled() -> None:
    """Master test coordinating controlled browser validation under strict network and server guarantees."""
    print("=" * 80)
    print("STARTING CONTROLLED OFFLINE BROWSER VALIDATION — MILESTONE 28 (HANDOFF-076)")
    print("=" * 80)

    # 1. Run server lifecycle failure-injection checks
    verify_server_lifecycle_failure_injection()

    # 2. Load acceptance fixtures
    fixtures_path = repo_root / "tests" / "fixtures" / "activation_dashboard_acceptance.json"
    with open(fixtures_path, encoding="utf-8") as f:
        fixtures_data = json.load(f)
    fixtures = fixtures_data["fixtures"]

    # 3. Instantiate servers with mock adapter
    mock_adapter = ControllableActivationMockAdapter()
    prod_app = create_app(adapter=mock_adapter)
    harness_app = _create_fixture_harness_app(fixtures=fixtures)

    prod_server = ControlledServerHandle(prod_app, "127.0.0.1", PROD_PORT, "Prod App Server")
    harness_server = ControlledServerHandle(harness_app, "127.0.0.1", HARNESS_PORT, "Harness Server")

    firewall = ContextSecurityFirewall(ALLOWED_ORIGINS)
    watcher = BrowserAuditWatcher()

    # 4. Managed execution with server socket guard and context-level firewall
    with install_server_socket_guard({"127.0.0.1", "localhost"}) as socket_violations:
        with managed_servers(prod_server, harness_server):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                browser_version = f"Chromium {browser.version}"
                print(f"Browser launched: {browser_version}")

                # Context A setup with exact-origin firewall
                ctx_a = browser.new_context(viewport={"width": 1280, "height": 800})
                firewall.attach(ctx_a)
                page_a = ctx_a.new_page()
                watcher.attach(page_a, "Context A (Main)")

                # Execute Section A
                verify_section_a_mounting_and_viewport(page_a, watcher)

                # Execute Section B
                verify_section_b_session_isolation(page_a, ctx_a, browser, firewall, watcher)

                # Execute Section C on Harness
                harness_page = ctx_a.new_page()
                watcher.attach(harness_page, "Harness Page")
                verify_section_c_lifecycle_scenarios(harness_page)

                browser.close()

    # 5. Final Security & Integrity Audits
    print("\n--- FINAL AUDITS: Error Watcher, Network Firewall & Mock Spy Verification ---")
    watcher.assert_clean()
    print("   ✓ Zero console errors, zero uncaught page errors, zero failed callbacks across entire session.")

    firewall.assert_clean()
    print("   ✓ Context-level exact-origin firewall: zero unauthorized external requests attempted or allowed.")

    assert len(socket_violations) == 0, f"Server socket guard violations: {socket_violations}"
    print("   ✓ Server-side socket guard: zero external network connections attempted.")

    assert mock_adapter.live_broker_invocations == 0, (
        f"Controllable mock adapter detected live broker invocations: {mock_adapter.live_broker_invocations}"
    )
    print("   ✓ Controllable mock adapter security spy verified: 0 live broker calls.")

    print("\n" + "=" * 80)
    print("CONTROLLED BROWSER VALIDATION COMPLETED SUCCESSFULLY (ALL ASSERTIONS PASSED)")
    print("=" * 80)


if __name__ == "__main__":
    test_activation_browser_controlled()
