"""Deterministic offline integration tests for Trend Joining Level (TJL) Dashboard.

Scope & Boundary:
-----------------
Tests the end-to-end integration of the pure offline TJL Engine with the TopG Dashboard:
1. Application Service calculation under INTEGRATED_MSM_CHOCH_TJL mode.
2. Candlestick Chart overlays:
   - Current Eligible Set zones (tjl1_zone and tjl2_zone) with distinct styling and shape names.
   - Exact geometry: High-side [UB, H], Low-side [L, LB], zero-width line (type='line', y0 == y1).
   - Horizontal availability starting at eligibility_available_time (or Unknown).
   - Confirmed labels-only zones (amber/dashed) when set is not active.
   - Historical set zones (slate/dotted) across lifecycle transitions.
   - Zero artificial widening on line zones.
   - Honest tooltips carrying non-execution disclaimer:
     '[Structural Set Only — Downstream activation/ledger not present]'.
   - Display toggle suppression (zones, current_set, historical, labels) leaving calculations unchanged.
3. Inspection Panel table rendering:
   - Engine Status card (Engine ID, Feed, TF, Direction, Epoch, Set ID, Outgoing Cancel Intent).
   - Lifecycle status badge (ELIGIBLE SET ACTIVE, LABELS ONLY, UNRESOLVED AMBIGUITY, AWAITING STRUCTURE).
   - Authoritative processed bar progress vs received bar progress.
   - Current Eligible Set table with TJL1 and TJL2 roles, bounds, stable level IDs, and P3 anchor.
   - All Labeled Zones table with set membership status.
   - Lifecycle Transition History table with outgoing cancelled set ID and diagnostics.
   - Scope boundary disclaimer.
4. Dashboard Controls Coordinator:
   - Draft mode change isolation (unapplied edit warning).
   - Display toggle presentation updates without recalculation or resetting state.
   - Unresolved structure ambiguity containment (frozen authoritative progress).
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
from aladeen.strategy.service import (
    CalculationMode,
    MSMContext,
    MSMServiceResult,
    calculate_msm,
)
from aladeen.strategy.tjl_types import (
    CurrentEligibleSet,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLSnapshot,
    TJLTransitionType,
    TJLZone,
)
from aladeen.strategy.types import Direction
from aladeen.ui.chart import create_candlestick_chart
from aladeen.ui.market_coordinator import generate_chart_and_status_from_snapshot
from aladeen.ui.msm_callbacks import (
    evaluate_msm_for_snapshot,
    process_msm_controls_update,
    render_msm_inspection_table,
)


@pytest.fixture(scope="module")
def tjl_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "tjl_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _make_snapshot_from_fixture(fix: Dict[str, Any], candle_slice: int | None = None, rev: str = "rev-tjl-test") -> MarketDataSnapshot:
    """Construct MarketDataSnapshot strictly preserving fixture timestamps."""
    candles = fix["candles"][:candle_slice] if candle_slice is not None else fix["candles"]
    records = []
    for i, c in enumerate(candles):
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
                close_time=c.get("close_time"),
            )
        )
    return MarketDataSnapshot(
        revision_id=rev,
        data_source="demo",
        symbol="EURUSD",
        timeframe="H1",
        candle_count=len(records),
        fetch_status="SUCCESS",
        timestamp_utc=records[-1].time if records else "2024-01-01T00:00:00Z",
        candles_data=records,
    )


class TestTJLApplicationService:
    """Tests calculate_msm with CalculationMode.INTEGRATED_MSM_CHOCH_TJL."""

    def test_bullish_first_set_creation(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        # Use first 8 bars (0..7) before candle 9 CHOCH
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)
        df = snap.to_dataframe()

        start_time = fix["start_candle_time"]
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=start_time,
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid
        assert res.snapshot is not None
        assert res.tjl_snapshot is not None
        assert not res.is_unresolved

        tjl_snap = res.tjl_snapshot
        assert tjl_snap.direction == Direction.UPWARD
        assert tjl_snap.current_eligible_set is not None
        curr_set = tjl_snap.current_eligible_set
        assert curr_set.set_id == "SET_1"
        assert curr_set.direction == Direction.UPWARD
        assert curr_set.tjl1_zone.label == TJLLabel.TJL1
        assert curr_set.tjl1_zone.level_id.side == TJLSide.HIGH
        assert curr_set.tjl2_zone.label == TJLLabel.TJL2_A_PLUS
        assert curr_set.tjl2_zone.level_id.side == TJLSide.LOW
        assert "Eligible Set: SET_1" in res.status_message

    def test_bearish_first_set_creation(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_02_bearish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        start_time = fix["start_candle_time"]
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid
        assert res.snapshot is not None
        assert res.tjl_snapshot is not None

        tjl_snap = res.tjl_snapshot
        assert tjl_snap.direction == Direction.DOWNWARD
        assert tjl_snap.current_eligible_set is not None
        curr_set = tjl_snap.current_eligible_set
        assert curr_set.set_id == "SET_1"
        assert curr_set.tjl1_zone.label == TJLLabel.TJL1
        assert curr_set.tjl1_zone.level_id.side == TJLSide.LOW
        assert curr_set.tjl2_zone.label == TJLLabel.TJL2_A_PLUS
        assert curr_set.tjl2_zone.level_id.side == TJLSide.HIGH

    def test_labels_only_prefix(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_04_labels_before_first_eligible_set"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        start_time = fix["start_candle_time"]
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=start_time,
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid
        tjl_snap = res.tjl_snapshot
        assert tjl_snap is not None
        # In labels-only prefix, Point 3 is not yet identified so current_eligible_set is None
        assert tjl_snap.current_eligible_set is None
        assert len(tjl_snap.all_labeled_zones) >= 2
        assert "Eligible Set: None" in res.status_message

    def test_continuation_t1_retains_old_set_plus_labels(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_05_continuation_t1_labels_without_replacement"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        start_time = fix["start_candle_time"]
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid
        tjl_snap = res.tjl_snapshot
        assert tjl_snap is not None
        assert tjl_snap.current_eligible_set is not None
        assert tjl_snap.current_eligible_set.set_id == "SET_1"
        # Should have newly labeled zones beyond Set 1's zones
        assert len(tjl_snap.all_labeled_zones) > 2
        assert not tjl_snap.outgoing_cancellation_intent

    def test_pullback_t2_replacement_and_cancellation_intent(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        start_time = fix["start_candle_time"]
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=start_time,
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        res = calculate_msm(df, ctx)
        assert res.is_valid
        tjl_snap = res.tjl_snapshot
        assert tjl_snap is not None
        assert tjl_snap.current_eligible_set is not None
        assert tjl_snap.current_eligible_set.set_id == "SET_2"
        assert tjl_snap.outgoing_cancellation_intent is True
        assert len(tjl_snap.historical_sets) >= 1
        assert any(s.set_id == "SET_1" for s in tjl_snap.historical_sets)


class TestTJLCandlestickChartOverlays:
    """Tests create_candlestick_chart TJL shapes, styling, geometry, and hover metadata."""

    def test_current_set_shapes_and_geometry(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res)

        # Inspect layout shapes
        shapes = fig.layout.shapes
        tjl_shapes = [s for s in shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_")]
        assert len(tjl_shapes) >= 2

        tjl1_shape = next(s for s in tjl_shapes if s.name == "tjl_zone_current_tjl1")
        tjl2_shape = next(s for s in tjl_shapes if s.name == "tjl_zone_current_tjl2_a_plus")

        # Bullish set: TJL1 is HIGH side (rect or line), TJL2 is LOW side
        assert tjl1_shape.line.color == "#00e676"
        assert tjl2_shape.line.color == "#ab47bc"

        # Verify hover trace exists with disclaimer
        traces = [t for t in fig.data if t.name and "Current TJL Set" in t.name]
        assert len(traces) == 2
        for tr in traces:
            hover = tr.hovertext[0]
            assert "[Structural Set Only — Downstream activation/ledger not present]" in hover
            assert "EURUSD" in hover
            assert "H1" in hover

    def test_zero_width_geometry_rendered_as_line(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res)

        # Verify any line shape has y0 == y1
        tjl_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_")]
        for s in tjl_shapes:
            if s.type == "line":
                assert s.y0 == s.y1

    def test_display_toggles_suppress_shapes_without_changing_calculation(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        # All toggles enabled
        ctx_all = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )
        res_all = calculate_msm(df, ctx_all)
        fig_all = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res_all)
        all_shapes = [s for s in fig_all.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_")]
        assert len(all_shapes) > 0

        # Master zones toggle False
        ctx_no_zones = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
            show_tjl_zones=False,
        )
        res_no_zones = calculate_msm(df, ctx_no_zones)
        # Calculation results must be identical
        assert res_no_zones.tjl_snapshot.current_eligible_set == res_all.tjl_snapshot.current_eligible_set
        fig_no_zones = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res_no_zones)
        no_shapes = [s for s in fig_no_zones.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_")]
        assert len(no_shapes) == 0

        # Suppress historical only
        ctx_no_hist = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=False,
            show_tjl_labels=True,
        )
        res_no_hist = calculate_msm(df, ctx_no_hist)
        fig_no_hist = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res_no_hist)
        hist_shapes = [s for s in fig_no_hist.layout.shapes if getattr(s, "name", None) and "historical" in s.name]
        assert len(hist_shapes) == 0


class TestTJLInspectionPanelRendering:
    """Tests render_msm_inspection_table rendering for TJL status, set table, and transition history."""

    def test_inspection_panel_active_set(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-test-1", msm_result=res)

        panel_str = str(panel)
        assert "Trend Joining Level (TJL) Status & Eligible Set" in panel_str
        assert "ELIGIBLE SET ACTIVE (SET_1)" in panel_str
        assert "Current Eligible TJL Set: SET_1" in panel_str
        assert "TJL1" in panel_str
        assert "TJL2_A_PLUS" in panel_str
        assert "TJL Lifecycle Transition History" in panel_str
        assert "FIRST_CREATION" in panel_str
        assert "STRUCTURAL SET ONLY — NOT ORDER EXECUTION" in panel_str
        assert "Authoritative Processed Bar:" in panel_str
        assert "Latest Received Input: Bar #" in panel_str

    def test_inspection_panel_labels_only(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_04_labels_before_first_eligible_set"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-test-2", msm_result=res)

        panel_str = str(panel)
        assert "LABELS ONLY" in panel_str
        assert "Current Eligible Set: None" in panel_str
        assert "All Labeled TJL Zones (Structural Provenance)" in panel_str

    def test_inspection_panel_transition_history_with_outgoing_cancellation(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-test-3", msm_result=res)

        panel_str = str(panel)
        assert "SET_REPLACEMENT" in panel_str
        assert "CANCEL SET_1" in panel_str
        assert "SET_2" in panel_str


class TestTJLControlsCoordinator:
    """Tests evaluate_msm_for_snapshot and process_msm_controls_update."""

    def test_evaluate_msm_for_snapshot_success(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)

        applied = {
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start_candle_time": fix["start_candle_time"],
            "direction": "UPWARD",
            "enabled": True,
            "calculation_mode": "INTEGRATED_MSM_CHOCH_TJL",
        }

        res, status_text, status_style, panel = evaluate_msm_for_snapshot(snap, applied)
        assert res is not None
        assert res.is_valid
        assert res.tjl_snapshot is not None
        assert "Set: SET_1" in status_text
        assert status_style["color"] == "#00e676"

    def test_process_controls_display_toggle_update_without_recalculation(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)

        applied = {
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start_candle_time": fix["start_candle_time"],
            "direction": "UPWARD",
            "enabled": True,
            "calculation_mode": "INTEGRATED_MSM_CHOCH_TJL",
            "show_tjl_zones": True,
            "show_tjl_current_set": True,
            "show_tjl_historical_sets": True,
            "show_tjl_labels": True,
        }

        # Toggle off current_set in UI
        new_applied, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="tjl-display-toggles",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=fix["start_candle_time"],
            market_snapshot_data=snap,
            applied_data=applied,
            tjl_display_toggles_val=["zones", "historical"],
        )

        assert new_applied is not None
        assert new_applied["show_tjl_zones"] is True
        assert new_applied["show_tjl_current_set"] is False
        assert new_applied["show_tjl_historical_sets"] is True
        assert new_applied["show_tjl_labels"] is False

    def test_unapplied_mode_edit_warning(self, tjl_fixtures: Dict[str, Any]) -> None:
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)

        applied = {
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start_candle_time": fix["start_candle_time"],
            "direction": "UPWARD",
            "enabled": True,
            "calculation_mode": "STANDALONE_MSM",
        }

        # User changes radio item to INTEGRATED_MSM_CHOCH_TJL but has not clicked Apply
        ret_applied, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="strategy-calculation-mode",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=fix["start_candle_time"],
            market_snapshot_data=snap,
            applied_data=applied,
            calculation_mode_val="INTEGRATED_MSM_CHOCH_TJL",
        )

        assert "Unapplied changes" in status_text
        assert ret_applied["calculation_mode"] == "STANDALONE_MSM"
        assert panel == dash.no_update


class TestTJLProductionServiceLifecycleAndPresentation:
    """Rigorous tests covering production calculation service presentation across the full lifecycle matrix."""

    def test_production_service_t1_retention_and_next_labels(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 3.1: t1 continuation retains old set while rendering next-set labels with distinct styling."""
        fix = tjl_fixtures["tjl_05_continuation_t1_labels_without_replacement"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid
        assert res.tjl_snapshot is not None
        assert res.tjl_snapshot.current_eligible_set is not None
        assert res.tjl_snapshot.current_eligible_set.set_id == "SET_1"

        # Check transition history for t1 retention
        tr_types = [tr.transition_type for tr in res.tjl_snapshot.transition_history]
        assert TJLTransitionType.CONTINUATION_RETAINED in tr_types

        # Verify chart rendering
        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res)
        shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_")]

        # Current set shapes (green/purple) must exist
        curr_shapes = [s for s in shapes if s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 2
        for s in curr_shapes:
            assert s.line.color in ("#00e676", "#ab47bc")

        # Next-set labels must exist and have amber dashed styling (distinct from current set)
        label_shapes = [s for s in shapes if s.name.startswith("tjl_zone_label_")]
        assert len(label_shapes) >= 1
        for s in label_shapes:
            assert s.line.color == "#ffb74d"
            assert s.line.dash == "dash"

    def test_production_service_t2_replacement_and_outgoing_cancelled_identity(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 3.2: t2 replacement creates new set, terminates historical interval, and records cancel intent."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid
        tjl_snap = res.tjl_snapshot
        assert tjl_snap.current_eligible_set is not None
        assert tjl_snap.current_eligible_set.set_id == "SET_2"
        assert len(tjl_snap.historical_sets) >= 1
        assert any(h.set_id == "SET_1" for h in tjl_snap.historical_sets)

        # Verify transition record explicitly records outgoing cancelled set ID
        repl_tr = next(tr for tr in tjl_snap.transition_history if tr.transition_type == TJLTransitionType.SET_REPLACEMENT)
        assert repl_tr.outgoing_cancelled_set_id == "SET_1"
        assert repl_tr.outgoing_cancellation_intent is True
        assert repl_tr.transition_time is not None

        # Verify chart rendering: historical set interval does not extend past replacement time
        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res)
        hist_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_historical_")]
        assert len(hist_shapes) >= 2
        for s in hist_shapes:
            assert s.line.color == "#78909c"
            assert s.line.dash == "dot"
            # Invariant: Historical interval x1 <= replacement transition time
            assert s.x1 <= repl_tr.transition_time

    def test_production_service_choch_invalidation_and_gap(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 3.3: CHOCH invalidates active set, records cancel intent, and renders empty current set in gap."""
        fix = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid
        tjl_snap = res.tjl_snapshot

        # Post-CHOCH: no eligible set active in gap
        assert tjl_snap.current_eligible_set is None

        # Transition history records CHOCH_INVALIDATION with cancelled SET_1
        choch_tr = next(tr for tr in tjl_snap.transition_history if tr.transition_type == TJLTransitionType.CHOCH_INVALIDATION)
        assert choch_tr.outgoing_cancelled_set_id == "SET_1"
        assert choch_tr.outgoing_cancellation_intent is True

        # Chart overlay: zero current set shapes rendered
        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res)
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 0

        # Inspection panel: shows Current Eligible Set: None
        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-choch-gap", msm_result=res)
        panel_str = str(panel)
        assert "Current Eligible Set: None" in panel_str

    def test_unknown_availability_omits_retroactive_eligible_shape(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 1 & 3.4: Unknown set availability omits time-extended shape and hover line while remaining inspectable."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        # Strip close_time from all candle records to force unknown availability
        candles = fix["candles"][:8]
        records = []
        for i, c in enumerate(candles):
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
                    close_time=None,  # Unknown close time!
                )
            )
        snap = MarketDataSnapshot(
            revision_id="rev-unknown-avail",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            candle_count=len(records),
            fetch_status="SUCCESS",
            timestamp_utc=records[-1].time if records else "2024-01-01T00:00:00Z",
            candles_data=records,
        )
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid
        curr_set = res.tjl_snapshot.current_eligible_set
        assert curr_set is not None
        assert curr_set.eligibility_available_time is None

        # Build chart: must omit time-extended eligible-set shapes!
        fig = create_candlestick_chart(df, symbol="EURUSD", timeframe="H1", msm_result=res)
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 0, "Unknown availability must omit time-extended eligible-set shapes"

        # Midline hover line traces must also be omitted
        midline_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL Set" in t.name]
        assert len(midline_traces) == 0, "Unknown availability must omit midline hover traces"

        # Instead, compact source reference marker at source candle is rendered
        source_ref_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL Source:" in t.name]
        assert len(source_ref_traces) == 2

        # Inspection panel remains inspectable and explicitly reports Unknown availability
        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-unknown-avail", msm_result=res)
        panel_str = str(panel)
        assert "Unknown (Availability timestamp unknown — no retroactive eligible interval plotted)" in panel_str

    def test_unresolved_last_authoritative_presentation(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 3.5 & 4: Unresolved ambiguity is prominently labeled as last authoritative evidence."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        # Synthesize unresolved condition on top of valid result
        synth_snap = replace(res.tjl_snapshot, is_unresolved=True, unresolved_diagnostic="Simultaneous c1 == p2 close detected")
        res_unres = replace(
            res,
            tjl_snapshot=synth_snap,
            is_unresolved=True,
            unresolved_diagnostic="Simultaneous c1 == p2 close detected",
            last_processed_index=synth_snap.last_processed_index,
            last_received_index=synth_snap.last_received_index,
        )

        panel = render_msm_inspection_table(res.snapshot, ctx, "rev-unres-test", msm_result=res_unres)
        panel_str = str(panel)
        assert "UNRESOLVED AMBIGUITY (LAST AUTHORITATIVE EVIDENCE)" in panel_str
        assert "Last Authoritative Evidence Retained" in panel_str
        assert "Authoritative Processed Bar: #" in panel_str
        assert "Latest Received Input: Bar #" in panel_str

    def test_revision_id_isolation_and_render_only_toggle_independence(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 3.7 & 5: Display toggles do not alter underlying calculation or snapshot revision."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix, rev="rev-immutable-999")
        df = snap.to_dataframe()

        ctx_base = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res_base = calculate_msm(df, ctx_base)

        applied = {
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start_candle_time": fix["start_candle_time"],
            "direction": "DOWNWARD",
            "enabled": True,
            "calculation_mode": "INTEGRATED_MSM_CHOCH_TJL",
            "show_tjl_zones": True,
            "show_tjl_current_set": True,
            "show_tjl_historical_sets": True,
            "show_tjl_labels": True,
        }

        # Modify toggles
        new_applied, status_text, status_style, panel = process_msm_controls_update(
            triggered_id="tjl-display-toggles",
            enable_toggle_val=["enabled"],
            direction_val="DOWNWARD",
            start_candle_val=fix["start_candle_time"],
            market_snapshot_data=snap,
            applied_data=applied,
            tjl_display_toggles_val=["zones"],
        )

        # Snapshot and calculation invariant
        assert snap.revision_id == "rev-immutable-999"
        assert new_applied["calculation_mode"] == "INTEGRATED_MSM_CHOCH_TJL"
        assert new_applied["show_tjl_current_set"] is False

    def test_one_current_set_produces_no_historical_duplicate(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 2.1: Initial single set creation produces no duplicate historical shapes or markers."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=8)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid
        assert res.tjl_snapshot is not None
        assert res.tjl_snapshot.current_eligible_set is not None
        assert res.tjl_snapshot.current_eligible_set.set_id == "SET_1"

        # Render chart with ALL toggles ON (including historical sets)
        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        hist_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_historical_")]
        assert len(hist_shapes) == 0, "Current Set 1 must not be duplicated into historical shapes"

        hist_traces = [t for t in fig.data if getattr(t, "name", None) and "Historical TJL" in t.name]
        assert len(hist_traces) == 0, "Current Set 1 must not be duplicated into historical traces"

    def test_after_replacement_only_outgoing_set1_is_historical(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 2.2: After replacement, only Set 1 receives historical shapes; Set 2 is strictly current."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid
        assert res.tjl_snapshot.current_eligible_set.set_id == "SET_2"

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        # Historical shapes exist and traces belong only to SET_1
        hist_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_historical_")]
        assert len(hist_shapes) == 2

        hist_traces = [t for t in fig.data if getattr(t, "name", None) and "Historical TJL:" in t.name]
        assert len(hist_traces) == 2
        for t in hist_traces:
            assert "SET_1" in t.name
            assert "SET_2" not in t.name
            assert "SET_1" in t.hovertext[0]
            assert "SET_2" not in t.hovertext[0]

        # Current shapes exist and traces belong only to SET_2
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 2

        curr_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL Set" in t.name]
        assert len(curr_traces) == 2
        for t in curr_traces:
            assert "SET_2" in t.name
            assert "SET_1" not in t.name
            assert "SET_2" in t.hovertext[0]
            assert "SET_1" not in t.hovertext[0]

    def test_current_off_historical_on_hides_current_set2(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 2.3: Current OFF and Historical ON renders historical Set 1 while suppressing current Set 2."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res,
            show_tjl_zones=True,
            show_tjl_current_set=False,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 0, "Current set must be hidden when show_tjl_current_set is False"

        hist_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_historical_")]
        assert len(hist_shapes) == 2, "Historical Set 1 shapes must still be displayed"

    def test_known_start_unknown_cancellation_produces_no_misleading_interval(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 2.4: Known start but unknown cancellation timestamp omits time-extended interval shape."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        tjl_snap = res.tjl_snapshot

        # Synthesize a transition history where replacement transition_time is None
        new_transitions = []
        for tr in tjl_snap.transition_history:
            if tr.outgoing_cancelled_set_id == "SET_1":
                new_transitions.append(replace(tr, transition_time=None))
            else:
                new_transitions.append(tr)

        synth_snap = replace(tjl_snap, transition_history=tuple(new_transitions))
        res_synth = replace(res, tjl_snapshot=synth_snap)

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res_synth,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        # Historical interval shapes must be omitted
        hist_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_historical_")]
        assert len(hist_shapes) == 0, "Unknown termination timestamp must omit time-extended historical shapes"

        # Rendered as compact source reference marker instead
        hist_traces = [t for t in fig.data if getattr(t, "name", None) and "Historical TJL Source:" in t.name]
        assert len(hist_traces) == 2
        for t in hist_traces:
            assert "Termination Timestamp Unknown" in t.hovertext[0]
            # Must NOT span across time
            assert len(t.x) == 1

    def test_unresolved_retained_set_not_displayed_as_fresh_current_eligibility(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 2.5: Unresolved ambiguity freezes chart boundary at processed index and labels hover with warning."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        candles = list(fix["candles"][:9])
        # Append a 10th candle at index 9 that continues without triggering CHOCH
        candles.append({
            "time": "2026-10-02T12:00:00Z",
            "open": 1.152,
            "high": 1.156,
            "low": 1.150,
            "close": 1.153,
            "is_forming": False,
            "bar_status": "CONFIRMED_COMPLETED",
            "close_time": "2026-10-02T16:00:00Z",
        })
        records = [
            MarketCandleRecord(
                time=c["time"],
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=c.get("is_forming", False),
                bar_status=c.get("bar_status", "CONFIRMED_COMPLETED"),
                index=i,
                close_time=c.get("close_time"),
            )
            for i, c in enumerate(candles)
        ]
        snap = MarketDataSnapshot(
            revision_id="rev-unres-test-bounds",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            candle_count=len(records),
            fetch_status="SUCCESS",
            timestamp_utc=records[-1].time,
            candles_data=records,
        )
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)

        # Synthesize unresolved condition at bar index 8 while input received index is 9
        synth_snap = replace(
            res.tjl_snapshot,
            is_unresolved=True,
            unresolved_diagnostic="Simultaneous c1 == p2 close detected",
            last_processed_index=8,
            last_received_index=9,
        )
        res_unres = replace(
            res,
            tjl_snapshot=synth_snap,
            is_unresolved=True,
            unresolved_diagnostic="Simultaneous c1 == p2 close detected",
            last_processed_index=8,
            last_received_index=9,
        )

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res_unres,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        # Check current set shapes: x1 must be frozen at processed bar index 8 close, NOT last chart time (bar index 9 close)
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 2
        processed_bar_close = res_unres.candles[8].close_time
        latest_bar_close = res_unres.candles[9].close_time
        assert processed_bar_close < latest_bar_close

        for s in curr_shapes:
            assert s.x1 == processed_bar_close, "Frozen unresolved set boundary must bound at last_processed_index close"

        # Check hover text in traces: contains freeze warning
        curr_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL Set" in t.name]
        assert len(curr_traces) == 2
        for t in curr_traces:
            assert "[Last Authoritative Evidence — Frozen Pending Resolution]" in t.hovertext[0]
            assert "Availability: Frozen at Bar #8" in t.hovertext[0]

    def test_unresolved_retained_set_decreasing_source_ids(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.1: Decreasing source IDs resolve via explicit candle ID, never df.index[last_processed_index]."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        # Use first 9 candles, but assign decreasing source indices: 950, 940, 930, ..., 870
        candles = list(fix["candles"][:9])
        records = []
        for i, c in enumerate(candles):
            source_id = 950 - (i * 10)
            records.append(
                MarketCandleRecord(
                    time=c["time"],
                    open=float(c["open"]),
                    high=float(c["high"]),
                    low=float(c["low"]),
                    close=float(c["close"]),
                    is_forming=c.get("is_forming", False),
                    bar_status=c.get("bar_status", "CONFIRMED_COMPLETED"),
                    index=source_id,
                    close_time=c.get("close_time"),
                )
            )
        snap = MarketDataSnapshot(
            revision_id="rev-unres-decreasing-ids",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            candle_count=len(records),
            fetch_status="SUCCESS",
            timestamp_utc=records[-1].time,
            candles_data=records,
        )
        df = snap.to_dataframe()
        assert len(df) == 9

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)

        # Authoritative candle is the 8th candle (i=7), source_id = 950 - 70 = 880
        # Notice: 880 is far beyond len(df) == 9! df.index[880] would raise IndexError.
        auth_source_id = 880
        auth_candle = res.candles[7]
        auth_close_time = auth_candle.close_time or auth_candle.open_time

        synth_snap = replace(
            res.tjl_snapshot,
            is_unresolved=True,
            unresolved_diagnostic="Decreasing source ID boundary ambiguity",
            last_processed_index=auth_source_id,
            last_received_index=870,
        )
        res_unres = replace(
            res,
            tjl_snapshot=synth_snap,
            is_unresolved=True,
            unresolved_diagnostic="Decreasing source ID boundary ambiguity",
            last_processed_index=auth_source_id,
            last_received_index=870,
        )

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res_unres,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        # Shapes must bound at auth_close_time with exact coordinates, NOT crash with IndexError
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 2
        for s in curr_shapes:
            assert s.x1 == auth_close_time
            assert s.x0 == res.tjl_snapshot.current_eligible_set.eligibility_available_time

        # Traces must show freeze hovertext with exact source ID
        curr_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL Set" in t.name]
        assert len(curr_traces) == 2
        for t in curr_traces:
            assert f"Availability: Frozen at Bar #{auth_source_id}" in t.hovertext[0]

    def test_unresolved_retained_set_sparse_ids_matching_dataframe_positions(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.2: Sparse source IDs matching valid DataFrame row positions resolve by ID, not position."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        # df has 9 rows: source IDs are 0, 10, 20, 30, 40, 50, 60, 70, 80
        candles = list(fix["candles"][:9])
        records = []
        for i, c in enumerate(candles):
            source_id = i * 10
            records.append(
                MarketCandleRecord(
                    time=c["time"],
                    open=float(c["open"]),
                    high=float(c["high"]),
                    low=float(c["low"]),
                    close=float(c["close"]),
                    is_forming=c.get("is_forming", False),
                    bar_status=c.get("bar_status", "CONFIRMED_COMPLETED"),
                    index=source_id,
                    close_time=c.get("close_time"),
                )
            )
        snap = MarketDataSnapshot(
            revision_id="rev-unres-sparse-ids",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            candle_count=len(records),
            fetch_status="SUCCESS",
            timestamp_utc=records[-1].time,
            candles_data=records,
        )
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)

        # Set last_processed_index to 70 (which corresponds to row 7, NOT row 70)
        auth_source_id = 70
        auth_candle = res.candles[7]
        expected_close = auth_candle.close_time or auth_candle.open_time

        synth_snap = replace(
            res.tjl_snapshot,
            is_unresolved=True,
            unresolved_diagnostic="Sparse ID test",
            last_processed_index=auth_source_id,
            last_received_index=80,
        )
        res_unres = replace(
            res,
            tjl_snapshot=synth_snap,
            is_unresolved=True,
            unresolved_diagnostic="Sparse ID test",
            last_processed_index=auth_source_id,
            last_received_index=80,
        )

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res_unres,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 2
        for s in curr_shapes:
            assert s.x1 == expected_close

    def test_chart_window_excluding_authoritative_source_candle(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.3: Chart window excluding authoritative source candle resolves via msm_result.candles."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=9)
        df_full = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df_full, ctx)

        # Slice DataFrame to display only the last 3 candles (indices 6, 7, 8)
        # Authoritative processed candle is bar 4 (which is EXCLUDED from df_window)
        df_window = df_full.iloc[6:].copy()
        assert len(df_window) == 3
        assert 4 not in df_window["index"].values

        auth_candle = res.candles[4]

        # Verify that resolve_authoritative_endpoint successfully found auth_time from res.candles
        from aladeen.ui.tjl_chart import resolve_authoritative_endpoint
        open_t, close_t = resolve_authoritative_endpoint(df_window, res, 4)
        assert open_t == auth_candle.open_time
        assert close_t == auth_candle.close_time

    def test_missing_authoritative_endpoint_produces_source_reference_not_fabricated_interval(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.4: Missing or invalid authoritative endpoint produces source-reference presentation, not a fabricated interval."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=9)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)

        # Supply an unresolvable ID (9999)
        synth_snap = replace(
            res.tjl_snapshot,
            is_unresolved=True,
            unresolved_diagnostic="Unresolvable authoritative endpoint",
            last_processed_index=9999,
            last_received_index=8,
        )
        res_unres = replace(
            res,
            tjl_snapshot=synth_snap,
            is_unresolved=True,
            unresolved_diagnostic="Unresolvable authoritative endpoint",
            last_processed_index=9999,
            last_received_index=8,
        )

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res_unres,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        # No time-extended rectangular shapes must be added
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 0, "Missing authoritative endpoint must omit time-extended shapes (never fabricate interval)"

        # Must render compact source-reference markers instead
        curr_source_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL Source:" in t.name]
        assert len(curr_source_traces) == 2
        for t in curr_source_traces:
            assert "Authoritative Endpoint Unavailable" in t.hovertext[0]
            assert "Availability: Authoritative endpoint unavailable (no retroactive or extended eligible interval plotted)" in t.hovertext[0]
            assert len(t.x) == 1

    def test_historical_off_labels_on_does_not_resurrect_cancelled_levels(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.5: Historical OFF + Labels ON does not resurrect cancelled historical levels as amber labels."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        tjl_snap = res.tjl_snapshot

        # Verify fixture precondition: SET_1 is in historical_sets
        assert any(h.set_id == "SET_1" for h in tjl_snap.historical_sets)
        hist_set_1 = next(h for h in tjl_snap.historical_sets if h.set_id == "SET_1")
        hist_1_level_ids = {hist_set_1.tjl1_zone.level_id, hist_set_1.tjl2_zone.level_id}

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=False,  # Historical OFF
            show_tjl_labels=True,           # Labels ON
        )

        # Historical shapes must be hidden
        hist_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_historical_")]
        assert len(hist_shapes) == 0

        # Labeled zone traces (amber dashed) must NOT contain the cancelled levels of SET_1
        label_traces = [t for t in fig.data if getattr(t, "name", None) and "TJL Label:" in t.name]
        for t in label_traces:
            for lvl_id in hist_1_level_ids:
                assert str(lvl_id.to_tuple()) not in t.hovertext[0], (
                    f"Cancelled level {lvl_id} must not resurrect as amber label when Historical is OFF"
                )

    def test_current_off_historical_on_does_not_reveal_active_set(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.6: Current OFF + Historical ON does not reveal or misclassify active SET_2."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        snap = _make_snapshot_from_fixture(fix)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.DOWNWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        assert res.tjl_snapshot.current_eligible_set is not None
        assert res.tjl_snapshot.current_eligible_set.set_id == "SET_2"

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res,
            show_tjl_zones=True,
            show_tjl_current_set=False,     # Current OFF
            show_tjl_historical_sets=True,  # Historical ON
            show_tjl_labels=True,
        )

        # Current set shapes must be completely absent
        curr_shapes = [s for s in fig.layout.shapes if getattr(s, "name", None) and s.name.startswith("tjl_zone_current_")]
        assert len(curr_shapes) == 0

        # Current set traces must be absent
        curr_traces = [t for t in fig.data if getattr(t, "name", None) and "Current TJL" in t.name]
        assert len(curr_traces) == 0

        # Historical set shapes must ONLY be for SET_1, never SET_2
        hist_traces = [t for t in fig.data if getattr(t, "name", None) and "Historical TJL:" in t.name]
        assert len(hist_traces) == 2
        for t in hist_traces:
            assert "SET_1" in t.hovertext[0]
            assert "SET_2" not in t.hovertext[0]

    def test_cross_direction_contextual_roles_correctly_classified(self, tjl_fixtures: Dict[str, Any]) -> None:
        """Directive 4.7: Contextual roles across directions/epochs are classified independently without physical identity collision."""
        from dataclasses import replace
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        snap = _make_snapshot_from_fixture(fix, candle_slice=9)
        df = snap.to_dataframe()

        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=fix["start_candle_time"],
            direction=Direction.UPWARD,
            enabled=True,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res = calculate_msm(df, ctx)
        curr_set = res.tjl_snapshot.current_eligible_set
        assert curr_set is not None

        # Suppose a level with the SAME StableLevelId as curr_set.tjl1_zone was previously
        # evaluated with role TJL2_A_PLUS (or a different role) and is currently waiting
        # in all_labeled_zones with that different contextual role.
        shared_level_id = curr_set.tjl1_zone.level_id
        cross_role_zone = replace(
            curr_set.tjl1_zone,
            label=TJLLabel.TJL2_A_PLUS,  # distinct contextual role
        )

        synth_snap = replace(
            res.tjl_snapshot,
            all_labeled_zones=res.tjl_snapshot.all_labeled_zones + (cross_role_zone,),
        )
        res_synth = replace(res, tjl_snapshot=synth_snap)

        fig = create_candlestick_chart(
            df,
            symbol="EURUSD",
            timeframe="H1",
            msm_result=res_synth,
            show_tjl_zones=True,
            show_tjl_current_set=True,
            show_tjl_historical_sets=True,
            show_tjl_labels=True,
        )

        # Classification by contextual role (level_id, label) means the distinct contextual role
        # is preserved and rendered as an amber label trace, rather than being erased by physical identity alone.
        cross_label_traces = [
            t for t in fig.data
            if getattr(t, "name", None) == "TJL Label: TJL2_A_PLUS"
            and str(shared_level_id.to_tuple()) in t.hovertext[0]
        ]
        assert len(cross_label_traces) == 1, (
            "Distinct contextual role on shared physical level must be preserved and classified as awaiting formation"
        )



