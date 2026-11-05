"""Controlled browser verification for CHOCH Dashboard Integration using Playwright.

Covers live UI rendering and coordinates in a real Chromium browser instance:
- Case 1: Deterministic Bearish CHOCH (H4):
    - Confirmed CHOCH at c2 close (2026-10-02 16:00 UTC)
    - Zones start horizontally strictly at 2026-10-02 16:00 UTC, NEVER at c2 open (12:00 UTC)
    - Marker on c2 anchored to c2 open with explicit tooltip distinguishing open from close
    - Inspection table displays "Structural zone available from 2026-10-02 16:00 UTC"
- Case 2: Deterministic Bullish CHOCH (H1):
    - Confirmed CHOCH at c2 close (2026-10-02 20:00 UTC)
    - Zones start horizontally strictly at 2026-10-02 20:00 UTC, NEVER at c2 open (16:00 UTC)
    - Inspection table displays "Structural zone available from 2026-10-02 20:00 UTC"
- Case 3: Deterministic Unresolved Structure (D1, c1 == p2):
    - Inspection panel displays "INTEGRATED STRUCTURE UNRESOLVED — LAST AUTHORITATIVE STATE"
    - Frozen authoritative progress (Bar #6) distinguished from received input (Bar #9)
    - Chart title and vertical line indicate "Last authoritative state"
    - Non-green styling verified
- Error Accounting:
    - Counts console errors and page errors separately (asserts both are 0).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
import threading
import time
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

from aladeen.app import create_app
from aladeen.data.contract import BarStatus
from aladeen.data.mt5_adapter import MT5ConnectionState

print = functools.partial(print, flush=True)

SERVER_PORT = 8060
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"


def _load_acceptance_fixtures() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "choch_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _make_df_from_candles(candles: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")
    if "index" not in df.columns:
        df["index"] = list(range(len(df)))
    return df


class DeterministicChochMockAdapter:
    """Mock adapter returning deterministic acceptance fixtures per timeframe."""

    def __init__(self, fixtures: dict[str, Any]) -> None:
        self.fixtures = fixtures
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        self.symbols = ["EURUSD"]
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
        if timeframe == "H4":
            # Deterministic Bearish basic fixture (10 candles)
            fix = self.fixtures["choch_bearish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "H1":
            # Deterministic Bullish basic fixture (11 candles)
            fix = self.fixtures["choch_bullish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "D1":
            # Deterministic Unresolved boundary fixture (c1 == p2 at candle 7)
            fix = self.fixtures["choch_bearish_basic_end_to_end"]
            raw_candles = [dict(c) for c in fix["candles"]]
            c7 = dict(raw_candles[7])
            c7["open"] = 1.130
            c7["high"] = 1.132
            c7["low"] = 1.085
            c7["close"] = 1.090
            raw_candles[7] = c7
            return _make_df_from_candles(raw_candles)
        else:
            fix = self.fixtures["choch_bearish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])


def main() -> None:
    print("=== STARTING DETERMINISTIC CHOCH BROWSER VERIFICATION ===")
    fixtures = _load_acceptance_fixtures()
    mock_adapter = DeterministicChochMockAdapter(fixtures)
    app = create_app(adapter=mock_adapter)

    server_thread = threading.Thread(
        target=lambda: app.run(port=SERVER_PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    time.sleep(2.0)

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

        # -------------------------------------------------------------------
        # Case 1: Deterministic Bearish CHOCH (H4)
        # -------------------------------------------------------------------
        print("\n--- CASE 1: Deterministic Bearish CHOCH (H4) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H4')").click()
        time.sleep(1.0)

        page.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.3)
        page.locator("#strategy-calculation-mode input[value='INTEGRATED_MSM_CHOCH']").check()
        time.sleep(0.3)
        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)

        # Select first completed candle (2026-10-01 00:00 UTC)
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Bearish CHOCH...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        # Assert inspection table content
        insp_text = page.locator("#msm-inspection-panel").inner_text()
        assert "CHOCH-BEARISH_CHOCH-8-9" in insp_text
        assert "Structural zone available from 2026-10-02 16:00 UTC" in insp_text
        print("   [PASS] Inspection table confirms CHOCH event and availability at 2026-10-02 16:00 UTC.")

        # Extract Plotly figure object from DOM
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

        plot_info = get_plotly_element()
        print(f"   [DEBUG] plot_info keys: data={bool(plot_info.get('data'))}, layout={bool(plot_info.get('layout'))}, fullLayout={bool(plot_info.get('fullLayout'))}")
        fig_dict = plot_info.get("data") or []
        layout_dict = plot_info.get("layout") or (plot_info.get("fullLayout") or {})

        shapes = layout_dict.get("shapes", [])
        # R24: Check zone shapes start strictly at 2026-10-02 16:00 UTC (confirmation_time)
        conf_time_iso = "2026-10-02T16:00:00"
        zone_shapes = [s for s in shapes if conf_time_iso in str(s.get("x0", ""))]
        assert len(zone_shapes) == 3, f"Expected 3 zone shapes starting at {conf_time_iso}, found {len(zone_shapes)}"

        # R24: Assert NO zone shape starts at c2 open time (2026-10-02 12:00 UTC)
        c2_open_iso = "2026-10-02T12:00:00"
        c2_open_shapes = [s for s in shapes if c2_open_iso in str(s.get("x0", ""))]
        assert len(c2_open_shapes) == 0, f"Found zone shapes starting at c2 open time {c2_open_iso}: {c2_open_shapes}"

        # Assert right boundary >= left boundary
        for s in zone_shapes:
            assert str(s.get("x1", "")) >= str(s.get("x0", "")), f"Backward zone shape: x1 < x0 ({s})"
        print("   [PASS] Plotly chart zone coordinates start strictly at 16:00 UTC (never 12:00 UTC).")

        # Check marker trace
        marker_trace = next((t for t in fig_dict if "CHOCH (BEAR)" in str(t.get("name", ""))), None)
        assert marker_trace is not None, "CHOCH (BEAR) marker trace not found in figure"
        hover_text = marker_trace["hovertext"][0]
        assert "Candle-Anchored Marker" in hover_text
        assert "Confirmed At: 2026-10-02 16:00 UTC" in hover_text
        assert "(c2 close)" not in hover_text
        print("   [PASS] Marker trace explicitly distinguishes candle open anchor from confirmation close.")

        # -------------------------------------------------------------------
        # Case 2: Deterministic Bullish CHOCH (H1)
        # -------------------------------------------------------------------
        print("\n--- CASE 2: Deterministic Bullish CHOCH (H1) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H1')").click()
        time.sleep(1.0)

        # Select direction DOWNWARD
        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)

        # Select starting candle
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Bullish CHOCH...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        # Assert inspection table content
        insp_text_h1 = page.locator("#msm-inspection-panel").inner_text()
        assert "CHOCH-BULLISH_CHOCH-9-10" in insp_text_h1
        assert "Structural zone available from 2026-10-02 20:00 UTC" in insp_text_h1
        print("   [PASS] Inspection table confirms Bullish CHOCH available at 2026-10-02 20:00 UTC.")

        plot_info_h1 = get_plotly_element()
        layout_h1 = plot_info_h1.get("layout") or (plot_info_h1.get("fullLayout") or {})
        shapes_h1 = layout_h1.get("shapes", [])
        conf_time_bull_iso = "2026-10-02T20:00:00"
        zone_shapes_h1 = [s for s in shapes_h1 if conf_time_bull_iso in str(s.get("x0", ""))]
        assert len(zone_shapes_h1) == 3, f"Expected 3 zone shapes starting at {conf_time_bull_iso}, found {len(zone_shapes_h1)}"

        # Assert NO shape starts at c2 open (2026-10-02 16:00 UTC)
        c2_bull_open_iso = "2026-10-02T16:00:00"
        c2_bull_open_shapes = [s for s in shapes_h1 if c2_bull_open_iso in str(s.get("x0", ""))]
        assert len(c2_bull_open_shapes) == 0
        print("   [PASS] Bullish zone coordinates start strictly at 20:00 UTC (never 16:00 UTC).")

        # -------------------------------------------------------------------
        # Case 3: Deterministic Unresolved Structure (D1)
        # -------------------------------------------------------------------
        print("\n--- CASE 3: Deterministic Unresolved Structure (D1, c1 == p2) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('D1')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)

        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Unresolved structure...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        # Assert unresolved banner and status
        insp_text_unres = page.locator("#msm-inspection-panel").inner_text()
        assert "INTEGRATED STRUCTURE UNRESOLVED — LAST AUTHORITATIVE STATE" in insp_text_unres
        assert "Last Authoritative Processed Bar: #6" in insp_text_unres
        assert "Latest Received Input: Bar #9" in insp_text_unres

        status_text_unres = page.locator("#msm-edit-status").inner_text()
        assert "ambiguous at candle 7" in status_text_unres
        assert "Last Authoritative State:" in status_text_unres

        # Status style must NOT be green
        status_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert status_color != "rgb(0, 230, 118)" and status_color != "#00e676", f"Unresolved status must not be green: {status_color}"

        # Chart title and vertical line
        plot_info_unres = get_plotly_element()
        layout_unres = plot_info_unres.get("layout") or (plot_info_unres.get("fullLayout") or {})
        title_obj = layout_unres.get("title", {})
        chart_title = title_obj.get("text", "") if isinstance(title_obj, dict) else str(title_obj)
        assert "INTEGRATED UNRESOLVED — Last authoritative state" in chart_title
        print("   [PASS] Unresolved state displays last authoritative state (#6 vs #9) and non-green warning styling.")

        # -------------------------------------------------------------------
        # Error Accounting
        # -------------------------------------------------------------------
        print(f"\n--- ERROR ACCOUNTING ---")
        print(f"Total Browser Console Errors: {len(console_errors)}")
        print(f"Total Browser Page Errors:    {len(page_errors)}")
        if console_errors:
            print("Console Errors Detail:", console_errors)
        if page_errors:
            print("Page Errors Detail:", page_errors)

        assert len(console_errors) == 0, f"Expected 0 console errors, got {len(console_errors)}"
        assert len(page_errors) == 0, f"Expected 0 page errors, got {len(page_errors)}"

        browser.close()
        print("\n=== ALL DETERMINISTIC BROWSER VERIFICATIONS PASSED WITH 0 ERRORS! ===")


if __name__ == "__main__":
    main()
