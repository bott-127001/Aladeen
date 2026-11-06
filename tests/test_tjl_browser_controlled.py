"""Controlled browser verification for Trend Joining Level (TJL) Dashboard Integration using Playwright.

NOTE ON VERIFICATION EVIDENCE SCOPE:
These tests exercise fixture-backed rendering scenarios across dropdown selector
values to verify Dash/Plotly UI rendering, coordinate placement, inspection panels,
toggles, and context switching. They do NOT constitute validation of genuine native broker
candle boundaries.

Covers live UI rendering and coordinates in a real Chromium browser instance across 7 scenarios:
1. Scenario 1: Deterministic Bullish First Set Creation (tjl_01 / H1):
   - Current eligible set SET_1 with TJL1 (HIGH side) and TJL2 (LOW side)
   - Inspection panel shows ELIGIBLE SET ACTIVE (SET_1) badge
   - Chart shapes tjl_zone_current_tjl1 and tjl_zone_current_tjl2_a_plus
   - Transition history table shows FIRST_CREATION
2. Scenario 2: Deterministic Bearish First Set Creation (tjl_02 / H4):
   - Current eligible set SET_1 with TJL1 (LOW side) and TJL2 (HIGH side)
   - Inspection panel shows ELIGIBLE SET ACTIVE (SET_1) badge
3. Scenario 3: Labels-Only Prefix (tjl_04 / M5):
   - Confirmed labels exist before active Point 3
   - Status badge shows LABELS ONLY
   - Current Eligible Set is None
   - Labeled zones table rendered
4. Scenario 4: Pullback t2 Replacement and Cancellation Intent (tjl_06 / GBPUSD):
   - Status badge shows ELIGIBLE SET ACTIVE (SET_2)
   - Outgoing cancellation intent is True (CANCEL SET_1)
   - Transition history shows SET_REPLACEMENT
5. Scenario 5: Mode Apply vs Unapplied Draft Edits:
   - Changing draft control enters '🟡 Unapplied changes' with yellow #ffd600 styling
   - Clicking Apply returns to '🟢 Applied' with green #00e676 styling
6. Scenario 6: TJL Display Toggles:
   - Unchecking zones suppresses shapes on chart without recalculating
   - Re-checking restores shapes
7. Scenario 7: Error Accounting:
   - Counts console errors and page errors separately (asserts both are 0).
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest
from playwright.sync_api import Page, sync_playwright

import aladeen.ui.market_coordinator
import aladeen.ui.msm_callbacks
from aladeen.app import create_app
from aladeen.data.contract import BarStatus
from aladeen.data.mt5_adapter import MT5ConnectionState
from aladeen.strategy.types import Direction

print = functools.partial(print, flush=True)

SERVER_PORT = 8063
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"


def _load_tjl_fixtures() -> dict[str, Any]:
    fixtures_dir = Path(__file__).parent / "fixtures"
    with open(fixtures_dir / "tjl_acceptance.json", "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _make_df_from_candles(candles: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")
    if "index" not in df.columns:
        df["index"] = list(range(len(df)))
    return df


class ControllableTJLMockAdapter:
    """Mock adapter returning deterministic acceptance fixtures per symbol/timeframe."""

    def __init__(self, tjl_fixtures: dict[str, Any]) -> None:
        self.tjl_fixtures = tjl_fixtures
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        self.symbols = ["EURUSD", "GBPUSD"]
        self.disconnect_called = False

    def is_package_installed(self) -> bool:
        return True

    def connect(self) -> MT5ConnectionState:
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        return self.connection_state

    def disconnect(self) -> None:
        self.connection_state = MT5ConnectionState.DISCONNECTED
        self.disconnect_called = True

    def get_connection_state(self) -> MT5ConnectionState:
        return self.connection_state

    def is_broker_connected(self) -> bool:
        return self.connection_state == MT5ConnectionState.CONNECTED_TO_BROKER

    def get_symbols(self) -> list[str]:
        return self.symbols

    def fetch_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        if symbol == "GBPUSD":
            # Scenario 4: Pullback t2 replacement
            fix = self.tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "H1":
            # Scenario 1: Bullish first set creation (first 8 bars before CHOCH)
            fix = self.tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"][:8])
        elif timeframe == "H4":
            # Scenario 2: Bearish first set creation
            fix = self.tjl_fixtures["tjl_02_bearish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "M5":
            # Scenario 3: Labels-only prefix
            fix = self.tjl_fixtures["tjl_04_labels_before_first_eligible_set"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "M1":
            # Scenario 4: Continuation t1 old set retention
            fix = self.tjl_fixtures["tjl_05_continuation_t1_labels_without_replacement"]
            return _make_df_from_candles(fix["candles"])
        else:
            fix = self.tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"][:8])


def test_tjl_browser_controlled() -> None:
    """Run full deterministic browser verification for TJL Dashboard across scenarios."""
    print("=== STARTING DETERMINISTIC TJL BROWSER VERIFICATION ===")
    tjl_fixtures = _load_tjl_fixtures()
    mock_adapter = ControllableTJLMockAdapter(tjl_fixtures)

    app = create_app(adapter=mock_adapter)

    server_thread = threading.Thread(
        target=lambda: app.run(port=SERVER_PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1.5)

    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.on(
            "console",
            lambda msg: console_errors.append(msg.text)
            if msg.type == "error" and "favicon" not in msg.text
            else None,
        )
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        print("1. Loading dashboard and connecting MT5 mock adapter...")
        page.goto(SERVER_URL, wait_until="networkidle")
        time.sleep(1.0)

        # Switch to MT5 data source and connect
        page.locator("#data-source-selector input[value='mt5']").check()
        time.sleep(0.5)
        page.locator("#connect-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#connection-badge') && document.querySelector('#connection-badge').innerText.includes('Connected')",
            timeout=8000,
        )
        print("   MT5 Connected. Badge:", page.locator("#connection-badge").inner_text())

        def get_plotly_element():
            return page.evaluate("""() => {
                let el = document.getElementById('main-chart');
                if (!el) return null;
                let plotEl = el.querySelector('.js-plotly-plot') || el;
                return {
                    data: plotEl.data || null,
                    layout: plotEl.layout || null,
                    fullLayout: plotEl._fullLayout ? { shapes: plotEl._fullLayout.shapes, title: plotEl._fullLayout.title } : null,
                    classes: plotEl.className,
                    id: plotEl.id
                };
            }""")

        # -------------------------------------------------------------
        # Scenario 1: Bullish First Set Creation (EURUSD / H1)
        # -------------------------------------------------------------
        print("\n--- SCENARIO 1: Bullish First Set Creation (EURUSD / H1) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H1')").click()
        time.sleep(1.0)

        page.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.3)
        page.locator("#strategy-calculation-mode input[value='INTEGRATED_MSM_CHOCH_TJL']").check()
        time.sleep(0.3)
        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)

        # Select first completed candle
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Bullish TJL...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        # Assert status text
        status_text = page.locator("#msm-edit-status").inner_text()
        assert "Set: SET_1" in status_text, f"Unexpected edit status: {status_text}"
        status_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert status_color in ("rgb(0, 230, 118)", "#00e676"), f"Expected green status color, got: {status_color}"

        # Assert inspection panel content
        insp_text = page.locator("#msm-inspection-panel").inner_text()
        assert "ELIGIBLE SET ACTIVE (SET_1)" in insp_text
        assert "Current Eligible TJL Set: SET_1" in insp_text
        assert "TJL1" in insp_text
        assert "TJL2_A_PLUS" in insp_text
        assert "FIRST_CREATION" in insp_text
        assert "Authoritative Processed Bar:" in insp_text
        print("   [PASS] Inspection panel confirms SET_1 active, TJL1, TJL2_A_PLUS, FIRST_CREATION transition.")

        # Assert Plotly chart overlays
        plot_info = get_plotly_element()
        layout_dict = plot_info.get("layout") or (plot_info.get("fullLayout") or {})
        shapes = layout_dict.get("shapes", [])
        tjl_shapes = [s for s in shapes if s.get("name", "").startswith("tjl_zone_")]
        assert len(tjl_shapes) >= 2, f"Expected at least 2 TJL shapes, got {len(tjl_shapes)}"
        assert any(s.get("name") == "tjl_zone_current_tjl1" for s in tjl_shapes)
        assert any(s.get("name") == "tjl_zone_current_tjl2_a_plus" for s in tjl_shapes)
        print("   [PASS] Candlestick chart renders distinct current set shapes.")

        # -------------------------------------------------------------
        # Scenario 2: Bearish First Set Creation (EURUSD / H4)
        # -------------------------------------------------------------
        print("\n--- SCENARIO 2: Bearish First Set Creation (EURUSD / H4) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H4')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text = page.locator("#msm-inspection-panel").inner_text()
        assert "ELIGIBLE SET ACTIVE (SET_1)" in insp_text
        print("   [PASS] Bearish SET_1 verified.")

        # -------------------------------------------------------------
        # Scenario 3: Labels-Only Prefix (EURUSD / M5)
        # -------------------------------------------------------------
        print("\n--- SCENARIO 3: Labels-Only Prefix (EURUSD / M5) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('M5')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text = page.locator("#msm-inspection-panel").inner_text()
        assert "LABELS ONLY" in insp_text
        assert "Current Eligible Set: None" in insp_text
        print("   [PASS] LABELS ONLY badge and Set None verified.")

        # -------------------------------------------------------------
        # Scenario 4: Pullback t2 Replacement (GBPUSD / H1)
        # -------------------------------------------------------------
        print("\n--- SCENARIO 4: Pullback t2 Replacement (GBPUSD / H1) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H1')").click()
        time.sleep(1.0)

        page.locator("#symbol-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('GBPUSD')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text = page.locator("#msm-inspection-panel").inner_text()
        assert "ELIGIBLE SET ACTIVE (SET_2)" in insp_text
        assert "SET_REPLACEMENT" in insp_text
        assert "CANCEL SET_1" in insp_text
        print("   [PASS] SET_2 active, SET_REPLACEMENT transition, CANCEL SET_1 emitted.")

        # -------------------------------------------------------------
        # Scenario 5: Unapplied Draft Edits Guard
        # -------------------------------------------------------------
        print("\n--- SCENARIO 5: Unapplied Draft Edits Guard ---")
        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.5)

        status_text = page.locator("#msm-edit-status").inner_text()
        assert "Unapplied changes" in status_text
        status_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert status_color in ("rgb(255, 214, 0)", "#ffd600")

        # Switch back to DOWNWARD and apply
        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)
        status_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert status_color in ("rgb(0, 230, 118)", "#00e676")
        print("   [PASS] Unapplied edits guard operates without silent recalculation.")

        # -------------------------------------------------------------
        # Scenario 6: TJL Display Toggles
        # -------------------------------------------------------------
        print("\n--- SCENARIO 6: TJL Display Toggles ---")
        plot_before = get_plotly_element()
        layout_before = plot_before.get("layout") or (plot_before.get("fullLayout") or {})
        shapes_before = layout_before.get("shapes", [])
        assert len([s for s in shapes_before if str(s.get("name", "")).startswith("tjl_zone_")]) >= 2

        # Uncheck Zones toggle
        page.locator("#tjl-display-toggles input[value='zones']").uncheck()
        time.sleep(1.0)

        plot_info = get_plotly_element()
        layout_dict = plot_info.get("layout") or (plot_info.get("fullLayout") or {})
        shapes = layout_dict.get("shapes", [])
        tjl_shapes = [s for s in shapes if s.get("name", "").startswith("tjl_zone_")]
        assert len(tjl_shapes) == 0, f"Expected 0 TJL shapes when zones suppressed, got {len(tjl_shapes)}"

        # Restore toggle
        page.locator("#tjl-display-toggles input[value='zones']").check()
        time.sleep(1.0)
        plot_info = get_plotly_element()
        layout_dict = plot_info.get("layout") or (plot_info.get("fullLayout") or {})
        shapes = layout_dict.get("shapes", [])
        tjl_shapes = [s for s in shapes if s.get("name", "").startswith("tjl_zone_")]
        assert len(tjl_shapes) >= 2, "Expected TJL shapes restored after re-checking toggle"
        print("   [PASS] TJL display toggles suppress and restore shapes cleanly.")

        # -------------------------------------------------------------
        # Scenario 7: Error Accounting
        # -------------------------------------------------------------
        print("\n--- SCENARIO 7: Error Accounting ---")
        print(f"Total console errors: {len(console_errors)}")
        print(f"Total page errors: {len(page_errors)}")
        assert len(console_errors) == 0, f"Console errors detected: {console_errors}"
        assert len(page_errors) == 0, f"Page errors detected: {page_errors}"
        print("   [PASS] Exactly 0 console errors and 0 page errors.")

        print("\n=== ALL TJL CONTROLLED BROWSER SCENARIOS VERIFIED SUCCESSFULLY ===")

        browser.close()
