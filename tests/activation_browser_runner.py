"""Master runner orchestration for Milestone 28 controlled activation browser validation.

Provides a compact, verifiable entry point demonstrating:
1. Server lifecycle and failure injection (startup collision, failure inside managed body).
2. Negative controls for isolation guards (firewall rejection, socket guard block, guard restoration).
3. Complete server startup, browser execution, full callback accounting, and clean teardown.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from playwright.sync_api import sync_playwright

from aladeen.app import create_app
from tests.activation_browser_harness import (
    ALLOWED_ORIGINS,
    HARNESS_PORT,
    PROD_PORT,
    BrowserAuditWatcher,
    ContextSecurityFirewall,
    ControlledServerHandle,
    ControllableActivationMockAdapter,
    install_server_socket_guard,
    managed_servers,
    verify_isolation_guards_negative_controls,
    verify_server_lifecycle_failure_injection,
    _create_fixture_harness_app,
)
from tests.test_activation_browser_controlled import (
    verify_section_a_mounting_and_viewport,
    verify_section_b_session_isolation,
    verify_section_c_lifecycle_scenarios,
)

logger = logging.getLogger("activation_browser_runner")


def run_activation_browser_validation() -> None:
    """Master entry point coordinating controlled browser validation under strict isolation."""
    print("=" * 80)
    print("STARTING CONTROLLED OFFLINE BROWSER VALIDATION — MILESTONE 28 (HANDOFF-077)")
    print("=" * 80)

    # 1. Server lifecycle failure injection (single server, startup collision, body exception)
    verify_server_lifecycle_failure_injection()

    # 2. Browser negative controls for ContextSecurityFirewall & install_server_socket_guard
    with sync_playwright() as playwright:
        browser_pre = playwright.chromium.launch(headless=True)
        verify_isolation_guards_negative_controls(browser_pre)
        browser_pre.close()

    # 3. Load acceptance fixtures
    fixtures_path = repo_root / "tests" / "fixtures" / "activation_dashboard_acceptance.json"
    with open(fixtures_path, encoding="utf-8") as f:
        fixtures_data = json.load(f)
    fixtures = fixtures_data["fixtures"]

    # 4. Instantiate servers with controllable offline mock adapter
    mock_adapter = ControllableActivationMockAdapter()
    prod_app = create_app(adapter=mock_adapter)
    harness_app = _create_fixture_harness_app(fixtures=fixtures)

    prod_server = ControlledServerHandle(prod_app, "127.0.0.1", PROD_PORT, "Prod App Server")
    harness_server = ControlledServerHandle(harness_app, "127.0.0.1", HARNESS_PORT, "Harness Server")

    firewall = ContextSecurityFirewall(ALLOWED_ORIGINS)
    watcher = BrowserAuditWatcher()

    # 5. Managed execution with server socket guard, managed servers, and context firewall
    with install_server_socket_guard({"127.0.0.1", "localhost"}) as socket_violations:
        with managed_servers(prod_server, harness_server):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                browser_version = f"Chromium {browser.version}"
                print(f"Browser launched: {browser_version}")

                # Context A setup with exact-origin firewall and context-level audit auto-attachment
                ctx_a = browser.new_context(viewport={"width": 1280, "height": 800})
                firewall.attach(ctx_a)
                watcher.attach_context(ctx_a, "Context A")
                page_a = ctx_a.new_page()
                watcher.attach(page_a, "Context A (Main)")

                # Execute Section A: Application Mounting, Viewport Usability, Typography
                verify_section_a_mounting_and_viewport(page_a, watcher)

                # Execute Section B: Session & Tab Isolation (SID, run advancement, window.open cloning)
                verify_section_b_session_isolation(page_a, ctx_a, browser, firewall, watcher)

                # Execute Section C: 15 Lifecycle Scenarios on Harness Page
                harness_page = ctx_a.new_page()
                watcher.attach(harness_page, "Harness Page")
                verify_section_c_lifecycle_scenarios(harness_page)

                # Clean browser closure
                browser.close()

    # 6. Final Security & Integrity Audits
    print("\n--- FINAL AUDITS: Error Watcher, Network Firewall & Mock Spy Verification ---")
    watcher.assert_clean()
    print("   ✓ Zero console errors, zero uncaught page errors, zero failed callbacks (response or request) across entire session.")

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
    run_activation_browser_validation()
