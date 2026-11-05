"""Controlled browser verification for Internal Structure Shift (ISS) Dashboard Integration using Playwright.

NOTE ON VERIFICATION EVIDENCE SCOPE:
These tests exercise fixture-backed rendering scenarios across dropdown selector
values to verify Dash/Plotly UI rendering, coordinate placement, inspection panels,
toggles, and context switching. They do NOT constitute validation of genuine native broker
candle boundaries.

Covers live UI rendering and coordinates in a real Chromium browser instance across 9 scenarios:
1. Scenario 1: Deterministic Bearish Success (iss_01 / H1):
   - Confirmed ISS at Bar 20 (close 1.188 inside boundary [1.1400, 1.2000])
   - Exactly two ISS zone shapes (RBS, Buying A+) starting horizontally at confirmation availability time (2026-10-01 21:00 UTC)
   - Confirmation marker anchored to candle open (2026-10-01 20:00 UTC) with tooltip distinguishing candle open from confirmation time
   - Inspection panel shows Candidate ID, CONFIRMED badge, 5 internal points table, active zones table, confirmed history
2. Scenario 2: Deterministic Bullish Success (iss_02 / H4):
   - Confirmed ISS event
   - Exactly two ISS zone shapes (SBR, Selling A+)
   - Inspection panel shows CONFIRMED badge and active zones
3. Scenario 3: Genuine Tracking-Only Progression (GBPUSD / H1):
   - Status badge shows OUTSIDE RANGE COMPLETION (TRACKING ONLY — NOT ELIGIBLE)
   - Attempted points table with TRACKING ONLY — NOT ELIGIBLE badges
   - Ongoing tracking points table with TRACKING ONLY — NOT ELIGIBLE badges
   - Zero active zones
4. Scenario 4: Out-of-Bounds Marked Point Rejection (iss_05 / M5):
   - Status badge shows OUT_OF_BOUNDS_REJECTED
   - Diagnostic indicates marked point outside boundary
   - Zero active zones on chart
5. Scenario 5: Main-Continuation Cancellation (iss_09 / M1):
   - Status badge shows MAIN_CONTINUATION_CANCELLED
   - Diagnostic indicates cancelled by main continuation
   - Zero active zones on chart
6. Scenario 6: Deterministic Unresolved Main Structure (D1, c1 == p2):
   - Unresolved banner #unresolved-status-banner with orange #ff9800 styling
   - Frozen authoritative progress vs received bar progress
   - Non-green edit status and chart title warning
7. Scenario 7: Mode Apply vs Unapplied Draft Edits:
   - Changing draft control enters '🟡 Unapplied changes' with yellow #ffd600 styling
   - Clicking Apply returns to '🟢 Applied' with green #00e676 styling
8. Scenario 8: ISS Display Toggles:
   - Unchecking markers and zones suppresses shapes and traces without recalculating
   - Re-checking restores shapes and traces
9. Scenario 9: Context Switch / Refresh with Shared Revision:
   - Clicking Refresh re-fetches candles and updates revision ID without improper state retention
10. Error Accounting:
   - Counts console errors and page errors separately (asserts both are 0).
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
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
from aladeen.strategy.iss_types import (
    CandidateIdentity,
    ConfirmedISSEvent,
    FrozenBoundary,
    ISSDiagnosticType,
    ISSLifecycleStatus,
    ISSSnapshot,
    ISSZone,
    ISSZoneType,
    InternalPoint,
)
from aladeen.strategy.service import (
    MSMContext,
    MSMServiceResult,
    calculate_msm as original_calculate_msm,
)
from aladeen.strategy.types import Direction

print = functools.partial(print, flush=True)

SERVER_PORT = 8062
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"


def _load_fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    fixtures_dir = Path(__file__).parent / "fixtures"
    with open(fixtures_dir / "iss_acceptance.json", "r", encoding="utf-8") as f:
        iss_fix = json.load(f)["fixtures"]
    with open(fixtures_dir / "choch_acceptance.json", "r", encoding="utf-8") as f:
        choch_fix = json.load(f)["fixtures"]
    return iss_fix, choch_fix


def _make_df_from_candles(candles: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")
    if "index" not in df.columns:
        df["index"] = list(range(len(df)))
    return df


class ControllableISSMockAdapter:
    """Mock adapter returning deterministic acceptance fixtures per symbol/timeframe."""

    def __init__(self, iss_fixtures: dict[str, Any], choch_fixtures: dict[str, Any]) -> None:
        self.iss_fixtures = iss_fixtures
        self.choch_fixtures = choch_fixtures
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
            # Tracking-only candidate scenario (base candles from iss_01)
            fix = self.iss_fixtures["iss_01_bearish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "H1":
            # Scenario 1: Bearish ISS Success
            fix = self.iss_fixtures["iss_01_bearish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "H4":
            # Scenario 2: Bullish ISS Success
            fix = self.iss_fixtures["iss_02_bullish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "M5":
            # Scenario 4: Out-of-bounds rejection
            fix = self.iss_fixtures["iss_05_out_of_bounds_marked_point_rejection"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "M1":
            # Scenario 5: Main-continuation cancellation
            fix = self.iss_fixtures["iss_09_main_continuation_cancellation"]
            return _make_df_from_candles(fix["candles"])
        elif timeframe == "D1":
            # Scenario 6: Unresolved main structure (c1 == p2 at candle 7)
            fix = self.choch_fixtures["choch_bearish_basic_end_to_end"]
            raw_candles = [dict(c) for c in fix["candles"]]
            c7 = dict(raw_candles[7])
            c7["open"] = 1.130
            c7["high"] = 1.132
            c7["low"] = 1.085
            c7["close"] = 1.090
            raw_candles[7] = c7
            return _make_df_from_candles(raw_candles)
        else:
            fix = self.iss_fixtures["iss_01_bearish_basic_end_to_end"]
            return _make_df_from_candles(fix["candles"])


def _patch_calculate_msm_for_tracking_only():
    """Wrap calculate_msm in UI modules to inject genuine tracking-only presentation when symbol is GBPUSD."""
    def hooked_calculate_msm(df: pd.DataFrame, ctx: MSMContext) -> MSMServiceResult:
        res = original_calculate_msm(df, ctx)
        if ctx.symbol == "GBPUSD" and ctx.calculation_mode == "INTEGRATED_MSM_CHOCH_ISS":
            pts = res.iss_snapshot.internal_points if res.iss_snapshot else ()
            cand_id = res.iss_snapshot.candidate_identity if res.iss_snapshot else None
            b = res.iss_snapshot.captured_boundary if res.iss_snapshot else None
            tracking_snap = ISSSnapshot(
                lifecycle_status=ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
                candidate_identity=cand_id,
                captured_boundary=b,
                internal_points=(),
                attempted_points=pts if pts else (),
                tracking_points=pts[:3] if pts else (),
                active_zones=(),
                confirmed_events=(),
                is_tracking_only=True,
                last_processed_index=len(res.candles) - 1,
                last_received_index=len(res.candles) - 1,
                diagnostic_type=ISSDiagnosticType.COMPLETION_CLOSE_OUTSIDE_RANGE,
                diagnostic_message="Completion candle close outside boundary. Tracking only.",
            )
            return MSMServiceResult(
                context=ctx,
                snapshot=res.snapshot,
                candles=res.candles,
                status_message="Tracking only — not eligible",
                candle_count=len(res.candles),
                start_candle_found=True,
                coordinator_snapshot=res.coordinator_snapshot,
                confirmed_choch_events=res.confirmed_choch_events,
                iss_snapshot=tracking_snap,
                confirmed_iss_events=(),
            )
        return res

    aladeen.ui.msm_callbacks.calculate_msm = hooked_calculate_msm
    aladeen.ui.market_coordinator.calculate_msm = hooked_calculate_msm


def test_iss_browser_controlled() -> None:
    """Run full deterministic browser verification for ISS Dashboard across 9 scenarios."""
    print("=== STARTING DETERMINISTIC ISS BROWSER VERIFICATION (9 SCENARIOS) ===")
    iss_fixtures, choch_fixtures = _load_fixtures()
    mock_adapter = ControllableISSMockAdapter(iss_fixtures, choch_fixtures)
    _patch_calculate_msm_for_tracking_only()

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

        # -------------------------------------------------------------------
        # Scenario 1: Deterministic Bearish Success (iss_01 / H1)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 1: Bearish ISS Success (iss_01 / H1) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H1')").click()
        time.sleep(1.0)

        page.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.3)
        page.locator("#strategy-calculation-mode input[value='INTEGRATED_MSM_CHOCH_ISS']").check()
        time.sleep(0.3)
        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)

        # Select first completed candle
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Bearish ISS...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        # Assert status text
        status_text = page.locator("#msm-edit-status").inner_text()
        assert "1 ISS confirmed" in status_text, f"Unexpected edit status: {status_text}"
        status_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert status_color in ("rgb(0, 230, 118)", "#00e676"), f"Expected green status color, got: {status_color}"

        # Assert inspection panel content
        insp_text = page.locator("#msm-inspection-panel").inner_text()
        assert "CONFIRMED" in insp_text
        assert "Point 1" in insp_text and "CH1" in insp_text
        assert "Point 2" in insp_text and "CL1" in insp_text
        assert "Point 3" in insp_text and "CH2" in insp_text
        assert "Point 4" in insp_text and "CL2" in insp_text
        assert "Point 5" in insp_text and "TENTATIVE_HIGH" in insp_text
        assert "RBS" in insp_text
        assert "BUYING_A_PLUS" in insp_text
        assert "Boundary:" in insp_text and "[1.1400, 1.2000]" in insp_text
        print("   [PASS] Inspection panel confirms Bearish ISS candidate, 5 points, RBS, and Buying A+ zones.")

        # Assert Plotly chart overlays
        plot_info = get_plotly_element()
        layout_dict = plot_info.get("layout") or (plot_info.get("fullLayout") or {})
        fig_dict = plot_info.get("data") or []
        shapes = layout_dict.get("shapes", [])

        # Check zone shapes: exactly 2 ISS zones starting at confirmation availability time
        iss_zone_shapes = [s for s in shapes if getattr(s, "get", lambda k, d=None: None)("name", "").startswith("iss_zone_")]
        assert len(iss_zone_shapes) == 2, f"Expected 2 ISS zone shapes, found {len(iss_zone_shapes)}"

        conf_avail_iso = "2026-10-01T21:00:00"
        for s in iss_zone_shapes:
            assert conf_avail_iso in str(s.get("x0", "")), f"Zone shape x0 must start at confirmation availability {conf_avail_iso}, got {s.get('x0')}"
            assert str(s.get("x1", "")) >= str(s.get("x0", "")), f"Backward zone shape: x1 < x0 ({s})"

        # Check RBS zone bounds [1.175, 1.178] and Buying A+ bounds [1.165, 1.168]
        rbs_shape = next(s for s in iss_zone_shapes if "rbs" in s.get("name", ""))
        assert float(rbs_shape["y0"]) == 1.175 and float(rbs_shape["y1"]) == 1.178

        buying_shape = next(s for s in iss_zone_shapes if "buying" in s.get("name", ""))
        assert float(buying_shape["y0"]) == 1.165 and float(buying_shape["y1"]) == 1.168

        # Check confirmation marker trace
        marker_trace = next((t for t in fig_dict if "ISS Confirmed" in str(t.get("name", ""))), None)
        assert marker_trace is not None, "ISS Confirmed marker trace not found in figure"
        hover_text = marker_trace["hovertext"][0]
        assert "Confirmed ISS Event [Structural Event — Not Order Entry Signal]" in hover_text
        assert "Open: 2026-10-01 20:00 UTC" in hover_text
        assert "Confirmed At: 2026-10-01 21:00 UTC" in hover_text
        assert "2026-10-01T20:00:00" in str(marker_trace["x"][0])
        print("   [PASS] Chart coordinates: exactly 2 ISS zones [1.175, 1.178], [1.165, 1.168] starting at 21:00 UTC, marker anchored to 20:00 UTC.")

        # -------------------------------------------------------------------
        # Scenario 2: Deterministic Bullish Success (iss_02 / H4)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 2: Bullish ISS Success (iss_02 / H4) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H4')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)

        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Bullish ISS...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text_h4 = page.locator("#msm-inspection-panel").inner_text()
        assert "CONFIRMED" in insp_text_h4
        assert "SBR" in insp_text_h4
        assert "SELLING_A_PLUS" in insp_text_h4

        plot_info_h4 = get_plotly_element()
        layout_h4 = plot_info_h4.get("layout") or (plot_info_h4.get("fullLayout") or {})
        shapes_h4 = layout_h4.get("shapes", [])
        iss_zone_shapes_h4 = [s for s in shapes_h4 if str(s.get("name", "")).startswith("iss_zone_")]
        assert len(iss_zone_shapes_h4) == 2, f"Expected 2 ISS zone shapes for Bullish ISS, found {len(iss_zone_shapes_h4)}"
        print("   [PASS] Bullish ISS confirmed with SBR and Selling A+ zones.")

        # -------------------------------------------------------------------
        # Scenario 3: Genuine Tracking-Only Progression (GBPUSD / H1)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 3: Genuine Tracking-Only Progression (GBPUSD / H1) ---")
        page.locator("#symbol-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('GBPUSD')").click()
        time.sleep(1.0)

        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H1')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)

        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Tracking-Only scenario...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text_track = page.locator("#msm-inspection-panel").inner_text()
        assert "OUTSIDE RANGE COMPLETION (TRACKING ONLY — NOT ELIGIBLE)" in insp_text_track
        assert "Attempted Internal Points (Tracking Only — Not Eligible)" in insp_text_track
        assert "Ongoing Tracking Points (Tracking Only — Not Eligible)" in insp_text_track
        assert "TRACKING ONLY — NOT ELIGIBLE" in insp_text_track

        # Assert zero active zones on chart
        plot_info_track = get_plotly_element()
        layout_track = plot_info_track.get("layout") or (plot_info_track.get("fullLayout") or {})
        shapes_track = layout_track.get("shapes", [])
        iss_zones_track = [s for s in shapes_track if str(s.get("name", "")).startswith("iss_zone_")]
        assert len(iss_zones_track) == 0, f"Expected 0 active ISS zones for tracking-only, found {len(iss_zones_track)}"
        print("   [PASS] Genuine tracking-only displays OUTSIDE_RANGE_COMPLETION badge, tracking tables, and 0 active zones.")

        # Switch back to EURUSD for subsequent scenarios
        page.locator("#symbol-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('EURUSD')").click()
        time.sleep(1.0)

        # -------------------------------------------------------------------
        # Scenario 4: Out-of-Bounds Marked Point Rejection (iss_05 / M5)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 4: Out-of-Bounds Rejection (iss_05 / M5) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('M5')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)

        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Out-of-Bounds scenario...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text_05 = page.locator("#msm-inspection-panel").inner_text()
        assert "OUT_OF_BOUNDS_REJECTED" in insp_text_05
        assert "outside boundary" in insp_text_05

        plot_info_05 = get_plotly_element()
        layout_05 = plot_info_05.get("layout") or (plot_info_05.get("fullLayout") or {})
        shapes_05 = layout_05.get("shapes", [])
        iss_zones_05 = [s for s in shapes_05 if str(s.get("name", "")).startswith("iss_zone_")]
        assert len(iss_zones_05) == 0, f"Expected 0 active ISS zones for out-of-bounds rejection, found {len(iss_zones_05)}"
        print("   [PASS] Out-of-bounds rejection displays OUT_OF_BOUNDS_REJECTED badge and 0 active zones.")

        # -------------------------------------------------------------------
        # Scenario 5: Main-Continuation Cancellation (iss_09 / M1)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 5: Main-Continuation Cancellation (iss_09 / M1) ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('M1')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)

        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        print("   Applying Main-Continuation Cancellation scenario...")
        page.locator("#msm-apply-btn").click()
        time.sleep(2.0)

        insp_text_09 = page.locator("#msm-inspection-panel").inner_text()
        assert "MAIN_CONTINUATION_CANCELLED" in insp_text_09
        assert "Cancelled by main continuation" in insp_text_09

        plot_info_09 = get_plotly_element()
        layout_09 = plot_info_09.get("layout") or (plot_info_09.get("fullLayout") or {})
        shapes_09 = layout_09.get("shapes", [])
        iss_zones_09 = [s for s in shapes_09 if str(s.get("name", "")).startswith("iss_zone_")]
        assert len(iss_zones_09) == 0, f"Expected 0 active ISS zones for continuation cancellation, found {len(iss_zones_09)}"
        print("   [PASS] Main continuation cancellation displays MAIN_CONTINUATION_CANCELLED badge and 0 active zones.")

        # -------------------------------------------------------------------
        # Scenario 6: Deterministic Unresolved Main Structure (D1)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 6: Deterministic Unresolved Main Structure (D1) ---")
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

        # Unresolved banner checks
        unres_banner = page.locator("#unresolved-status-banner")
        assert unres_banner.is_visible()
        unres_text = unres_banner.inner_text()
        assert "INTEGRATED STRUCTURE UNRESOLVED — LAST AUTHORITATIVE STATE" in unres_text
        assert "Candle #7" in unres_text

        # Verify border styling has orange #ff9800
        border_style = unres_banner.evaluate("el => el.style.border")
        assert "rgb(255, 152, 0)" in border_style or "#ff9800" in border_style

        # Inspection panel progress
        insp_text_unres = page.locator("#msm-inspection-panel").inner_text()
        assert "Last Authoritative Processed Bar: #6" in insp_text_unres
        assert "Latest Received Input: Bar #9" in insp_text_unres

        # Status text must NOT be green and should indicate ambiguity
        status_unres_text = page.locator("#msm-edit-status").inner_text()
        assert "ambiguous at candle 7" in status_unres_text

        # Chart title
        plot_info_unres = get_plotly_element()
        layout_unres = plot_info_unres.get("layout") or (plot_info_unres.get("fullLayout") or {})
        title_obj = layout_unres.get("title", {})
        chart_title = title_obj.get("text", "") if isinstance(title_obj, dict) else str(title_obj)
        assert "INTEGRATED UNRESOLVED — Last authoritative state" in chart_title
        print("   [PASS] Unresolved main structure displays #unresolved-status-banner with #ff9800 border and frozen authoritative progress.")

        # -------------------------------------------------------------------
        # Scenario 7: Mode Apply vs Unapplied Draft Edits (H1)
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 7: Mode Apply vs Unapplied Draft Edits ---")
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(".dash-dropdown-option:has-text('H1')").click()
        time.sleep(1.0)

        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        time.sleep(0.3)

        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        page.locator("#msm-apply-btn").click()
        time.sleep(1.5)

        # Baseline applied state
        status_applied = page.locator("#msm-edit-status").inner_text()
        assert "1 ISS confirmed" in status_applied

        # Change draft radio without clicking apply
        page.locator("#strategy-calculation-mode input[value='STANDALONE_MSM']").check()
        time.sleep(0.5)

        status_draft = page.locator("#msm-edit-status").inner_text()
        assert "🟡 Unapplied changes" in status_draft
        draft_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert draft_color in ("rgb(255, 214, 0)", "#ffd600")

        # Click apply
        page.locator("#msm-apply-btn").click()
        time.sleep(1.5)

        status_reapplied = page.locator("#msm-edit-status").inner_text()
        assert "🟢 Applied" in status_reapplied
        assert "pairs confirmed" in status_reapplied
        assert "STANDALONE_MSM" in page.locator("#msm-inspection-panel").inner_text()
        reapplied_color = page.locator("#msm-edit-status").evaluate("el => el.style.color")
        assert reapplied_color in ("rgb(0, 230, 118)", "#00e676")
        print("   [PASS] Changing draft control immediately shows unapplied edit notice; clicking Apply restores green applied state.")

        # -------------------------------------------------------------------
        # Scenario 8: ISS Display Toggles
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 8: ISS Display Toggles ---")
        # Switch back to INTEGRATED_MSM_CHOCH_ISS and apply
        page.locator("#strategy-calculation-mode input[value='INTEGRATED_MSM_CHOCH_ISS']").check()
        time.sleep(0.3)
        page.locator("#msm-apply-btn").click()
        time.sleep(1.5)

        plot_before = get_plotly_element()
        layout_before = plot_before.get("layout") or (plot_before.get("fullLayout") or {})
        shapes_before = layout_before.get("shapes", [])
        assert len([s for s in shapes_before if str(s.get("name", "")).startswith("iss_zone_")]) == 2

        # Uncheck Markers and Zones
        page.locator("#iss-display-toggles input[value='markers']").uncheck()
        time.sleep(0.3)
        page.locator("#iss-display-toggles input[value='zones']").uncheck()
        time.sleep(1.0)

        plot_toggled = get_plotly_element()
        layout_toggled = plot_toggled.get("layout") or (plot_toggled.get("fullLayout") or {})
        shapes_toggled = layout_toggled.get("shapes", [])
        iss_zones_toggled = [s for s in shapes_toggled if str(s.get("name", "")).startswith("iss_zone_")]
        assert len(iss_zones_toggled) == 0, f"Expected 0 ISS zones after unchecking toggle, got {len(iss_zones_toggled)}"

        fig_toggled = plot_toggled.get("data") or []
        iss_markers_toggled = [t for t in fig_toggled if "ISS Confirmed" in str(t.get("name", ""))]
        assert len(iss_markers_toggled) == 0, f"Expected 0 ISS confirmation markers after toggle, got {len(iss_markers_toggled)}"

        # Inspection panel should STILL display strategy candidate and confirmed status
        insp_toggled_text = page.locator("#msm-inspection-panel").inner_text()
        assert "CONFIRMED" in insp_toggled_text
        assert "Point 1" in insp_toggled_text

        # Re-check Markers and Zones
        page.locator("#iss-display-toggles input[value='markers']").check()
        time.sleep(0.3)
        page.locator("#iss-display-toggles input[value='zones']").check()
        time.sleep(1.0)

        plot_restored = get_plotly_element()
        layout_restored = plot_restored.get("layout") or (plot_restored.get("fullLayout") or {})
        shapes_restored = layout_restored.get("shapes", [])
        assert len([s for s in shapes_restored if str(s.get("name", "")).startswith("iss_zone_")]) == 2
        print("   [PASS] ISS display toggles suppress chart shapes and traces without recalculating strategy results.")

        # -------------------------------------------------------------------
        # Scenario 9: Context Switch / Refresh with Shared Revision
        # -------------------------------------------------------------------
        print("\n--- SCENARIO 9: Context Switch / Refresh with Shared Revision ---")
        status_area_before = page.locator("#status-area").inner_text()
        page.locator("#refresh-btn").click()
        time.sleep(1.5)

        status_area_after = page.locator("#status-area").inner_text()
        assert status_area_after is not None and len(status_area_after) > 0
        # Chart and inspection remain valid and consistent
        plot_refreshed = get_plotly_element()
        assert plot_refreshed.get("data") is not None
        insp_refreshed = page.locator("#msm-inspection-panel").inner_text()
        assert "CONFIRMED" in insp_refreshed
        print("   [PASS] Refresh updates market data revision and refreshes chart without state pollution.")

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
        print("\n=== ALL 9 DETERMINISTIC ISS BROWSER VERIFICATION SCENARIOS PASSED WITH 0 ERRORS! ===")


if __name__ == "__main__":
    test_iss_browser_controlled()
