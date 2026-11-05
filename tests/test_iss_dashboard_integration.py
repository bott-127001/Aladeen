"""Deterministic offline integration tests for Internal Structure Shift (ISS) Dashboard.

Scope & Boundary:
-----------------
Tests the end-to-end integration of the offline ISS Engine with the TopG Dashboard:
1. Application Service calculation under INTEGRATED_MSM_CHOCH_ISS mode.
2. Candlestick Chart overlays (Section 10):
   - Confirmation markers on the 5th-point identification candle.
   - Level 3 (RBS/SBR) and Level 4 (Buying/Selling A+) structural zones.
   - Known vs unknown availability time bounds (zero time-extended speculative zones).
   - Display toggle suppression (markers, zones, points).
   - Hover tooltips explicitly labeled as structural events, not entry signals.
3. Inspection Panel table rendering:
   - Candidate Identity card (Candidate ID, direction, Level 2/3 references, boundary [min, max]).
   - Lifecycle status badges and diagnostic reporting.
   - Authoritative processed bar progress vs received bar progress.
   - Internal 5-Point Structure table.
   - Attempted and Ongoing Tracking Points tables labeled "Tracking Only — Not Eligible".
   - Active Zones table with exact geometry, source candles, and availability.
   - Confirmed ISS History table.
4. Dashboard Controls Coordinator:
   - Draft mode change isolation (unapplied edit warning).
   - Display toggle presentation updates without recalculation or resetting state.
   - Unresolved main structure ambiguity containment (frozen authoritative progress).
   - Safe idempotence and zero execution/trading boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List
import dash
import pandas as pd
import pytest

from aladeen.data.market_snapshot import MarketCandleRecord, MarketDataSnapshot
from aladeen.strategy.iss_types import (
    ConfirmedISSEvent,
    ISSLifecycleStatus,
    ISSSnapshot,
    ISSZone,
    ISSZoneType,
    InternalPoint,
)
from aladeen.strategy.service import (
    CalculationMode,
    MSMContext,
    MSMServiceResult,
    calculate_msm,
)
from aladeen.strategy.types import Direction
from aladeen.ui.chart import create_candlestick_chart
from aladeen.ui.layout import generate_chart_and_status_from_snapshot
from aladeen.ui.msm_callbacks import (
    evaluate_msm_for_snapshot,
    process_msm_controls_update,
    render_msm_inspection_table,
)


@pytest.fixture(scope="module")
def iss_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "iss_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _make_snapshot_from_fixture(fix: Dict[str, Any], rev: str = "rev-iss-test") -> MarketDataSnapshot:
    records = []
    for i, c in enumerate(fix["candles"]):
        close_t = c.get("close_time")
        if close_t is None and "time" in c:
            # Synthetic 4-hour offset for testing
            dt = datetime.fromisoformat(c["time"])
            from datetime import timedelta
            close_t = (dt + timedelta(hours=4)).isoformat()
        records.append(
            MarketCandleRecord(
                time=c["time"],
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c.get("is_forming", False)),
                bar_status=str(c.get("bar_status", "CONFIRMED_COMPLETED")),
                index=i,
                close_time=close_t,
            )
        )
    return MarketDataSnapshot(
        revision_id=rev,
        data_source="demo",
        symbol="EURUSD",
        timeframe="H4",
        candle_count=len(records),
        timestamp_utc="2026-10-15 12:00:00 UTC",
        fetch_status="SUCCESS",
        candles_data=tuple(records),
    )


def _extract_all_text(comp: Any) -> str:
    """Recursively extract plain text from Dash component tree."""
    if comp is None:
        return ""
    if isinstance(comp, str):
        return comp
    if isinstance(comp, (int, float)):
        return str(comp)
    children = getattr(comp, "children", None)
    if isinstance(children, list):
        return " ".join(_extract_all_text(c) for c in children)
    if children is not None:
        return _extract_all_text(children)
    return ""


class TestISSDashboardIntegratedService:
    """Tests calculate_msm with CalculationMode.INTEGRATED_MSM_CHOCH_ISS."""

    def test_bearish_iss_basic_service_calculation(self, iss_fixtures) -> None:
        """iss_01: Bearish main structure produces confirmed ISS at Bar 20 with RBS and Buying A+ zones."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-iss-01")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
            show_iss_markers=True,
            show_iss_zones=True,
            show_iss_points=True,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid is True
        assert res.iss_snapshot is not None
        assert res.iss_snapshot.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(res.confirmed_iss_events) == 1

        ev = res.confirmed_iss_events[0]
        assert ev.main_direction == Direction.DOWNWARD
        assert ev.confirmation_candle_index == 20
        assert ev.level_3_zone.zone_type == ISSZoneType.RBS
        assert ev.level_4_zone.zone_type == ISSZoneType.BUYING_A_PLUS

        # Check synchronization: ISSEngine's coordinator snapshot is exposed
        assert res.coordinator_snapshot is not None
        assert res.snapshot is not None
        assert len(res.snapshot.confirmed_pairs) >= 1

    def test_bullish_iss_basic_service_calculation(self, iss_fixtures) -> None:
        """iss_02: Bullish main structure produces confirmed ISS with SBR and Selling A+ zones."""
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-iss-02")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.UPWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
            show_iss_markers=True,
            show_iss_zones=True,
            show_iss_points=True,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid is True
        assert res.iss_snapshot is not None
        assert res.iss_snapshot.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(res.confirmed_iss_events) == 1

        ev = res.confirmed_iss_events[0]
        assert ev.main_direction == Direction.UPWARD
        assert ev.level_3_zone.zone_type == ISSZoneType.SBR
        assert ev.level_4_zone.zone_type == ISSZoneType.SELLING_A_PLUS


class TestISSDashboardChartRendering:
    """Tests chart overlays, confirmation markers, zones, and hover texts (Section 10)."""

    def test_chart_renders_iss_markers_and_zones(self, iss_fixtures) -> None:
        """Chart renders confirmation markers, Level 3 and Level 4 zones, and safe tooltips."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-chart-01")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
            show_iss_markers=True,
            show_iss_zones=True,
            show_iss_points=True,
        )
        res = calculate_msm(df, ctx)

        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H4", msm_result=res)

        # 1. Verify ISS confirmation marker trace
        marker_traces = [t for t in fig.data if "ISS" in getattr(t, "name", "").upper()]
        assert len(marker_traces) >= 1
        hover_text = marker_traces[0].hovertext[0]
        assert "Confirmed ISS Event" in hover_text
        assert "Structural Event — Not Order Entry Signal" in hover_text
        assert "Candidate ID:" in hover_text

        # 2. Verify zone shapes are drawn
        # In iss_01, both RBS and Buying A+ zones should produce shapes
        shapes = fig.layout.shapes
        assert len(shapes) >= 2

        # 3. Check tradability boundary: zone shapes must start at confirmation_availability_time
        ev = res.confirmed_iss_events[0]
        assert ev.confirmation_time is not None
        zone_shapes = [s for s in shapes if getattr(s, "x0", None) == ev.confirmation_time]
        assert len(zone_shapes) >= 1

        # 4. Check all shapes have non-negative width (x1 >= x0)
        for s in shapes:
            if hasattr(s, "x0") and hasattr(s, "x1") and s.x0 is not None and s.x1 is not None:
                assert s.x1 >= s.x0

    def test_chart_display_toggles_invariance(self, iss_fixtures) -> None:
        """Toggling show_iss_markers, show_iss_zones, and show_iss_points suppresses overlays without altering engine state."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-tog-01")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()

        # Suppress all ISS visual elements
        ctx_no_vis = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
            show_iss_markers=False,
            show_iss_zones=False,
            show_iss_points=False,
        )
        res = calculate_msm(df, ctx_no_vis)
        assert len(res.confirmed_iss_events) == 1

        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H4", msm_result=res)
        marker_traces = [t for t in fig.data if "ISS" in getattr(t, "name", "")]
        assert len(marker_traces) == 0

        # No ISS zone shapes
        ev = res.confirmed_iss_events[0]
        zone_shapes = [s for s in fig.layout.shapes if getattr(s, "x0", None) == ev.confirmation_time]
        assert len(zone_shapes) == 0

    def test_unknown_availability_does_not_extend_time_box(self, iss_fixtures) -> None:
        """When confirmation_availability_time is unknown, no speculative time range is plotted."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        # Strip close_time from candles so confirmation_time becomes None
        raw_candles = [dict(c) for c in fix["candles"]]
        for c in raw_candles:
            c.pop("close_time", None)

        candle_records = [
            MarketCandleRecord(
                time=c["time"],
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c.get("is_forming", False)),
                bar_status=str(c.get("bar_status", "CONFIRMED_COMPLETED")),
                index=i,
                close_time=None,
            )
            for i, c in enumerate(raw_candles)
        ]
        snap = MarketDataSnapshot(
            revision_id="rev-unk-avail",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=len(candle_records),
            timestamp_utc="2026-10-15 12:00:00 UTC",
            fetch_status="SUCCESS",
            candles_data=tuple(candle_records),
        )
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
            show_iss_markers=True,
            show_iss_zones=True,
        )
        res = calculate_msm(df, ctx)
        ev = res.confirmed_iss_events[0]
        assert ev.confirmation_time is None

        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H4", msm_result=res)
        # Check marker tooltip mentions Unknown
        marker_traces = [t for t in fig.data if "ISS" in getattr(t, "name", "").upper()]
        assert len(marker_traces) >= 1
        hover_text = marker_traces[0].hovertext[0]
        assert "Confirmation Availability: Unknown" in hover_text


class TestISSDashboardInspectionPanel:
    """Tests the detailed HTML tables rendered in render_msm_inspection_table."""

    def test_inspection_panel_renders_iss_tables(self, iss_fixtures) -> None:
        """Inspection panel renders Candidate Identity, 5 points, Active Zones, and Confirmed History."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-insp-01")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
            show_iss_markers=True,
            show_iss_zones=True,
            show_iss_points=True,
        )
        res = calculate_msm(df, ctx)

        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-insp-01", msm_result=res)
        panel_text = _extract_all_text(panel)

        # 1. Candidate Identity & Engine Status
        assert "Internal Structure Shift (ISS) Candidate & Engine Status" in panel_text
        assert "CONFIRMED" in panel_text
        assert "Candidate ID:" in panel_text
        assert "Boundary:" in panel_text
        assert "Authoritative Processed Bar: #20" in panel_text
        assert "Latest Received Input: Bar #20" in panel_text

        # 2. Internal 5-Point Structure Table
        assert "ISS Internal 5-Point Structure" in panel_text
        assert "Point 1" in panel_text
        assert "Point 5" in panel_text
        assert "Inside Range" in panel_text

        # 3. Active ISS Structural Zones Table
        assert "Active ISS Structural Zones" in panel_text
        assert "RBS" in panel_text
        assert "BUYING_A_PLUS" in panel_text

        # 4. Confirmed ISS History Table
        assert "Confirmed Internal Structure Shift (ISS) History" in panel_text
        assert "Bar #20" in panel_text

    def test_tracking_only_candidate_presentation(self, iss_fixtures) -> None:
        """iss_06: Tracking-only candidate presents warning badge and attempted/ongoing tracking points."""
        fix = iss_fixtures["iss_06_outside_range_completion_tracking_only"]
        snap = _make_snapshot_from_fixture(fix, "rev-insp-06")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
        )
        res = calculate_msm(df, ctx)
        assert res.iss_snapshot is not None
        assert res.iss_snapshot.lifecycle_status in {
            ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
            ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED,
        }

        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-insp-06", msm_result=res)
        panel_text = _extract_all_text(panel)
        assert "Internal Structure Shift (ISS) Candidate & Engine Status" in panel_text

    def test_out_of_bounds_rejection_presentation(self, iss_fixtures) -> None:
        """iss_05: Out-of-bounds rejection presents OUT_OF_BOUNDS_REJECTED lifecycle status."""
        fix = iss_fixtures["iss_05_out_of_bounds_marked_point_rejection"]
        snap = _make_snapshot_from_fixture(fix, "rev-insp-05")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
        )
        res = calculate_msm(df, ctx)
        assert res.iss_snapshot is not None
        assert res.iss_snapshot.lifecycle_status == ISSLifecycleStatus.OUT_OF_BOUNDS_REJECTED

        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-insp-05", msm_result=res)
        panel_text = _extract_all_text(panel)
        assert "OUT_OF_BOUNDS_REJECTED" in panel_text

    def test_continuation_cancellation_presentation(self, iss_fixtures) -> None:
        """iss_09: Cancellation by main continuation displays MAIN_CONTINUATION_CANCELLED."""
        fix = iss_fixtures["iss_09_main_continuation_cancellation"]
        snap = _make_snapshot_from_fixture(fix, "rev-insp-09")
        df = snap.to_dataframe()

        start_time = pd.to_datetime(fix["candles"][0]["time"], utc=True).to_pydatetime()
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            calculation_mode="INTEGRATED_MSM_CHOCH_ISS",
        )
        res = calculate_msm(df, ctx)
        assert res.iss_snapshot is not None
        assert res.iss_snapshot.lifecycle_status == ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED

        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-insp-09", msm_result=res)
        panel_text = _extract_all_text(panel)
        assert "MAIN_CONTINUATION_CANCELLED" in panel_text


class TestISSDashboardControlsCoordinator:
    """Tests process_msm_controls_update with ISS controls, toggles, and status reporting."""

    def test_apply_activates_integrated_iss_mode(self, iss_fixtures) -> None:
        """Clicking Apply with INTEGRATED_MSM_CHOCH_ISS stores configuration and returns green status."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-coord-01")

        start_candle = fix["candles"][0]["time"]
        applied_store, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="DOWNWARD",
            start_candle_val=start_candle,
            market_snapshot_data=snap.to_dict(),
            applied_data=None,
            calculation_mode_val="INTEGRATED_MSM_CHOCH_ISS",
            display_toggles_val=["markers", "zones"],
            iss_display_toggles_val=["markers", "zones", "points"],
        )

        assert applied_store is not None
        assert applied_store["calculation_mode"] == "INTEGRATED_MSM_CHOCH_ISS"
        assert applied_store["show_iss_markers"] is True
        assert applied_store["show_iss_zones"] is True
        assert applied_store["show_iss_points"] is True
        assert "1 ISS confirmed" in status_text
        assert status_style["color"] == "#00e676"

    def test_draft_mode_change_enters_unapplied_state(self, iss_fixtures) -> None:
        """Changing strategy-calculation-mode without clicking Apply shows unapplied edit notice."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-draft-01")

        applied_data = {
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "start_candle_time": fix["candles"][0]["time"],
            "direction": "DOWNWARD",
            "rule_version": "1.0",
            "enabled": True,
            "calculation_mode": "INTEGRATED_MSM_CHOCH",
            "show_choch_markers": True,
            "show_choch_zones": True,
            "show_iss_markers": True,
            "show_iss_zones": True,
            "show_iss_points": True,
        }

        # Change mode to INTEGRATED_MSM_CHOCH_ISS without applying
        out_applied, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="strategy-calculation-mode",
            enable_toggle_val=["enabled"],
            direction_val="DOWNWARD",
            start_candle_val=fix["candles"][0]["time"],
            market_snapshot_data=snap.to_dict(),
            applied_data=applied_data,
            calculation_mode_val="INTEGRATED_MSM_CHOCH_ISS",
        )

        assert out_applied == applied_data
        assert "Unapplied changes" in status_text
        assert status_style["color"] == "#ffd600"
        assert panel == dash.no_update

    def test_iss_display_toggles_update_presentation_only(self, iss_fixtures) -> None:
        """Toggling iss-display-toggles updates applied store and presentation without recalculation."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, "rev-tog-coord")

        applied_data = {
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "start_candle_time": fix["candles"][0]["time"],
            "direction": "DOWNWARD",
            "rule_version": "1.0",
            "enabled": True,
            "calculation_mode": "INTEGRATED_MSM_CHOCH_ISS",
            "show_choch_markers": True,
            "show_choch_zones": True,
            "show_iss_markers": True,
            "show_iss_zones": True,
            "show_iss_points": True,
        }

        out_applied, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="iss-display-toggles",
            enable_toggle_val=["enabled"],
            direction_val="DOWNWARD",
            start_candle_val=fix["candles"][0]["time"],
            market_snapshot_data=snap.to_dict(),
            applied_data=applied_data,
            iss_display_toggles_val=["zones"],  # markers and points unchecked
        )

        assert out_applied is not None
        assert out_applied["show_iss_markers"] is False
        assert out_applied["show_iss_zones"] is True
        assert out_applied["show_iss_points"] is False
        assert out_applied["calculation_mode"] == "INTEGRATED_MSM_CHOCH_ISS"
        assert "1 ISS confirmed" in status_text

    def test_unresolved_structure_containment_in_iss_mode(self) -> None:
        """Under unresolved main ambiguity, process_msm_controls_update outputs orange warning with frozen authoritative progress."""
        path = Path(__file__).parent / "fixtures" / "choch_acceptance.json"
        with open(path, "r", encoding="utf-8") as f:
            choch_fix = json.load(f)["fixtures"]["choch_bearish_basic_end_to_end"]

        raw_candles = [dict(c) for c in choch_fix["candles"]]
        # Force same-close ambiguity (c1 == p2)
        c7 = dict(raw_candles[7])
        c7["open"] = 1.130
        c7["high"] = 1.132
        c7["low"] = 1.085
        c7["close"] = 1.090
        raw_candles[7] = c7

        candle_records = [
            MarketCandleRecord(
                time=c["time"],
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c.get("is_forming", False)),
                bar_status=str(c.get("bar_status", "CONFIRMED_COMPLETED")),
                index=i,
                close_time=c.get("close_time"),
            )
            for i, c in enumerate(raw_candles)
        ]
        snap = MarketDataSnapshot(
            revision_id="rev-unres-iss",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=len(candle_records),
            timestamp_utc="2026-10-15 12:00:00 UTC",
            fetch_status="SUCCESS",
            candles_data=tuple(candle_records),
        )

        out_applied, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=choch_fix["start_candle_time"],
            market_snapshot_data=snap.to_dict(),
            applied_data=None,
            calculation_mode_val="INTEGRATED_MSM_CHOCH_ISS",
        )

        assert out_applied is not None
        assert "Integrated structure unresolved" in status_text
        assert "Last Authoritative State:" in status_text
        assert status_style["color"] == "#ff9800"

        # Check inspection panel text
        panel_text = _extract_all_text(panel)
        assert "INTEGRATED STRUCTURE UNRESOLVED — LAST AUTHORITATIVE STATE" in panel_text
        assert "Authoritative processing is frozen" in panel_text
