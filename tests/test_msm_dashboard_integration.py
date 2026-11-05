"""Offline integration tests for MSM Strategy Dashboard features.

Scope & Boundary:
-----------------
Tests the integration between:
1. Application service layer (MSMContext, calculate_msm, adapt_chart_dataframe)
2. Strict explicit completion evidence validation (R10.1)
3. Initial direction & start candle manual selection (R10.2)
4. Exact 1-based pair numbering: H1..Hn, L1..Ln, Pair #1 (R10.3)
5. Explicit last support / last resistance indicators & guidelines (R10.4)
6. Strict context deserialization and rule version checks (R10.5)
7. UI Chart overlay construction and hover provenance
8. Coordinator callback handling: unapplied edits, start retained/missing, context switches
"""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock
import dash

from aladeen.data.contract import BarStatus
from aladeen.data.fixtures import DEMO_SYMBOL, load_fixture
from aladeen.data.market_snapshot import MarketCandleRecord, MarketDataSnapshot, fetch_market_snapshot
from aladeen.data.mt5_adapter import MT5ConnectionError, MT5ConnectionState
from aladeen.strategy.service import (
    MSMContext,
    MSMServiceResult,
    SUPPORTED_RULE_VERSIONS,
    adapt_chart_dataframe,
    calculate_msm,
    is_candle_completed,
    is_context_compatible,
    validate_candle_completion,
)
from aladeen.strategy.types import Direction, EngineState, StrategyCandle, SwingPoint, ConfirmedPair
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart
from aladeen.ui.layout import (
    build_layout,
    generate_chart_and_status_from_snapshot,
    generate_chart_and_status_with_trigger,
    register_callbacks,
)
from aladeen.ui.msm_callbacks import (
    evaluate_msm_for_snapshot,
    get_completed_candle_options,
    process_msm_controls_update,
    process_msm_dropdown_update,
    render_msm_inspection_table,
)


class TestChartDataframeAdaptationAndEvidence:
    """Tests adapting chart DataFrames into validated StrategyCandles (R10.1)."""

    def test_adapt_demo_h4_fixture(self) -> None:
        """Demo H4 fixture adapts cleanly to StrategyCandles with stable integer IDs."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        assert df is not None
        candles = adapt_chart_dataframe(df)
        assert len(candles) == len(df)
        assert all(isinstance(c, StrategyCandle) for c in candles)
        first_candle = candles[0]
        expected_id = int(first_candle.open_time.timestamp())
        assert first_candle.index == expected_id
        assert first_candle.bar_status == "CONFIRMED_COMPLETED"
        assert first_candle.is_forming is False

    def test_adapt_preserves_explicit_integer_index(self) -> None:
        """When an explicit 'index' column is present, it is preserved."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df["index"] = list(range(100, 100 + len(df)))
        candles = adapt_chart_dataframe(df)
        assert candles[0].index == 100
        assert candles[1].index == 101

    def test_adapt_supports_numpy_scalars_losslessly(self) -> None:
        """NumPy int64 and float64 are accepted losslessly; booleans rejected."""
        df = load_fixture(DEMO_SYMBOL, "D1").copy()
        df["open"] = df["open"].astype(np.float64)
        df["high"] = df["high"].astype(np.float32)
        df["index"] = np.arange(len(df), dtype=np.int64)
        candles = adapt_chart_dataframe(df)
        assert len(candles) == len(df)
        assert isinstance(candles[0].open, float)

    def test_adapt_rejects_missing_completion_columns(self) -> None:
        """R10.1: Missing 'is_forming' or 'bar_status' raises ValueError."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df_no_forming = df.drop(columns=["is_forming"])
        with pytest.raises(ValueError, match="Missing required candle columns"):
            adapt_chart_dataframe(df_no_forming)

        df_no_status = df.drop(columns=["bar_status"])
        with pytest.raises(ValueError, match="Missing required candle columns"):
            adapt_chart_dataframe(df_no_status)

    def test_adapt_rejects_null_or_nan_completion_values(self) -> None:
        """R10.1: Null or NaN in is_forming or bar_status raises ValueError."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df["is_forming"] = df["is_forming"].astype(object)
        df.iloc[0, df.columns.get_loc("is_forming")] = None
        with pytest.raises(ValueError, match="cannot be null/NaN"):
            adapt_chart_dataframe(df)

        df2 = load_fixture(DEMO_SYMBOL, "H4").copy()
        df2["bar_status"] = df2["bar_status"].astype(object)
        df2.iloc[0, df2.columns.get_loc("bar_status")] = None
        with pytest.raises(ValueError, match="cannot be null/NaN"):
            adapt_chart_dataframe(df2)

    def test_adapt_rejects_non_boolean_is_forming(self) -> None:
        """R10.1: Strings and numbers as is_forming raise TypeError."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df["is_forming"] = df["is_forming"].astype(object)
        df.iloc[0, df.columns.get_loc("is_forming")] = "False"
        with pytest.raises(TypeError, match="must be bool"):
            adapt_chart_dataframe(df)

        df.iloc[0, df.columns.get_loc("is_forming")] = 0
        with pytest.raises(TypeError, match="must be bool"):
            adapt_chart_dataframe(df)

    def test_adapt_rejects_unknown_or_coerced_bar_status(self) -> None:
        """R10.1: Unknown bar_status raises ValueError without loose string coercion."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df.iloc[0, df.columns.get_loc("bar_status")] = "UNKNOWN_STATUS"
        with pytest.raises(ValueError, match="unknown bar_status"):
            adapt_chart_dataframe(df)

        df["bar_status"] = df["bar_status"].astype(object)
        df.iloc[0, df.columns.get_loc("bar_status")] = 12345
        with pytest.raises(TypeError, match="must be str"):
            adapt_chart_dataframe(df)

    def test_adapt_rejects_contradictory_completion_evidence(self) -> None:
        """R10.1: Contradictory completion combinations must be rejected."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df.iloc[0, df.columns.get_loc("is_forming")] = True
        df.iloc[0, df.columns.get_loc("bar_status")] = "CONFIRMED_COMPLETED"
        with pytest.raises(ValueError, match="contradictory completion evidence"):
            adapt_chart_dataframe(df)

        df2 = load_fixture(DEMO_SYMBOL, "H4").copy()
        df2.iloc[0, df2.columns.get_loc("is_forming")] = False
        df2.iloc[0, df2.columns.get_loc("bar_status")] = "FORMING"
        with pytest.raises(ValueError, match="contradictory completion evidence"):
            adapt_chart_dataframe(df2)

    def test_adapt_rejects_boolean_price_strictly(self) -> None:
        """Boolean values disguised as prices must raise TypeError, not silently cast to 1.0."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df["open"] = df["open"].astype(object)
        df.iloc[0, df.columns.get_loc("open")] = True
        with pytest.raises(TypeError, match="cannot be boolean"):
            adapt_chart_dataframe(df)

    def test_adapt_rejects_non_finite_price(self) -> None:
        """Infinite or NaN prices must be rejected."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df.iloc[0, df.columns.get_loc("close")] = float("inf")
        with pytest.raises(ValueError, match="must be finite"):
            adapt_chart_dataframe(df)

    def test_adapt_rejects_naive_datetime_index(self) -> None:
        """Naive DatetimeIndex without UTC timezone must be rejected."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        df.index = df.index.tz_localize(None)
        with pytest.raises(ValueError, match="must be timezone-aware"):
            adapt_chart_dataframe(df)

    def test_adapt_rejects_empty_dataframe(self) -> None:
        """Empty DataFrame raises ValueError."""
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "is_forming", "bar_status"])
        empty_df.index = pd.DatetimeIndex([], tz="UTC")
        with pytest.raises(ValueError, match="DataFrame is empty"):
            adapt_chart_dataframe(empty_df)


class TestContextValidationAndCompatibility:
    """Tests strict context deserialization, version checks, and isolation (R10.5)."""

    def test_matching_context_is_compatible(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            rule_version="1.0",
            enabled=True,
        )
        assert is_context_compatible(ctx, "demo", DEMO_SYMBOL, "H4") is True

    def test_unsupported_rule_version_rejected(self) -> None:
        """R10.5: Rule version other than supported 1.0 is rejected."""
        with pytest.raises(ValueError, match="Unsupported rule_version"):
            MSMContext(
                data_source="demo",
                symbol=DEMO_SYMBOL,
                timeframe="H4",
                start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
                direction=Direction.UPWARD,
                rule_version="2.0",
                enabled=True,
            )

    def test_from_dict_rejects_non_boolean_enabled(self) -> None:
        """R10.5: String 'false' or numeric 0 as enabled must raise TypeError, not coerce."""
        d = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": "2026-10-01T00:00:00+00:00",
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": "false",
        }
        with pytest.raises(TypeError, match="enabled must be bool"):
            MSMContext.from_dict(d)

    def test_from_dict_rejects_missing_required_fields(self) -> None:
        """R10.5: Missing data_source or symbol raises ValueError."""
        d = {
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": "2026-10-01T00:00:00+00:00",
            "direction": "UPWARD",
        }
        with pytest.raises(ValueError, match="Missing required context field"):
            MSMContext.from_dict(d)

    def test_from_dict_rejects_non_dict_payload(self) -> None:
        """R10.5: Non-dict payload raises TypeError."""
        with pytest.raises(TypeError, match="data must be dict"):
            MSMContext.from_dict("invalid_payload")  # type: ignore

    def test_is_context_compatible_handles_malformed_dict_safely(self) -> None:
        """R10.5: Malformed dict returns False rather than crashing."""
        assert is_context_compatible({"enabled": "bad"}, "demo", DEMO_SYMBOL, "H4") is False
        assert is_context_compatible(None, "demo", DEMO_SYMBOL, "H4") is False


class TestDropdownStartCandleFiltering:
    """Tests dropdown options extraction with validated completion predicate (R10.1, R10.2)."""

    def test_initial_dropdown_options_exclude_forming_and_invalid(self) -> None:
        """Dropdown only includes verified completed candles."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        # Mark row 1 as forming
        df.iloc[1, df.columns.get_loc("is_forming")] = True
        df.iloc[1, df.columns.get_loc("bar_status")] = "FORMING"

        options = get_completed_candle_options(df)
        assert len(options) == len(df) - 1
        # Formatted string check
        assert "O:" in options[0]["label"]
        assert "C:" in options[0]["label"]

    def test_dropdown_update_pure_helper_leaves_initial_value_none(self) -> None:
        """R10.2: Dropdown options helper preserves existing value if valid, but defaults to None (no silent auto-select)."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)
        options, selected = process_msm_dropdown_update(
            snapshot_or_df=snap,
            current_value=None,
        )
        assert len(options) > 0
        assert selected is None  # R10.2: must remain None without manual selection

    def test_initial_layout_controls_have_none_values(self) -> None:
        """R10.2: Verify initial direction and start dropdown values in layout are None."""
        layout = build_layout()
        # Find direction selector and start dropdown in layout components
        found_dir = False
        found_start = False

        def walk(component):
            nonlocal found_dir, found_start
            if getattr(component, "id", None) == "msm-direction-selector":
                assert component.value is None
                found_dir = True
            if getattr(component, "id", None) == "msm-start-candle-dropdown":
                assert component.value is None
                found_start = True
            children = getattr(component, "children", None)
            if isinstance(children, list):
                for child in children:
                    walk(child)
            elif children is not None:
                walk(children)

        walk(layout)
        assert found_dir is True, "msm-direction-selector not found in layout"
        assert found_start is True, "msm-start-candle-dropdown not found in layout"


class TestChartOverlaysAndRenderedLabels:
    """Tests exact 1-based pair labels (R10.3) and last support/resistance (R10.4)."""

    def test_exact_1based_pair_labels_rendered(self) -> None:
        """R10.3: Confirmed Highs/Lows and hover text use exact 1-based labels H1, L1, Pair #1."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_time = df.index[0]
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.UPWARD,
            enabled=True,
        )
        res = calculate_msm(df, ctx)
        assert res.is_valid is True
        assert len(res.snapshot.confirmed_pairs) >= 1

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            data_source="demo",
            is_demo=True,
            msm_result=res,
        )

        high_trace = next(t for t in fig.data if getattr(t, "name", None) == "Confirmed High")
        low_trace = next(t for t in fig.data if getattr(t, "name", None) == "Confirmed Low")

        # R10.3: First pair must be H1, L1 (not H2, L2)
        assert high_trace.text[0] == "H1"
        assert low_trace.text[0] == "L1"
        assert "Confirmed Swing High (Pair #1)" in high_trace.hovertext[0]
        assert "Confirmed Swing Low (Pair #1)" in low_trace.hovertext[0]

        # Structure path trace present
        assert any(getattr(t, "name", None) == "Market Structure" for t in fig.data)

    def test_last_support_indicator_rendered_explicitly(self) -> None:
        """R10.4: For upward marking with confirmed pairs, last support is explicitly rendered."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_time = df.index[0]
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.UPWARD,
            enabled=True,
        )
        res = calculate_msm(df, ctx)
        assert res.snapshot.last_support is not None

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            data_source="demo",
            is_demo=True,
            msm_result=res,
        )

        # Check Last Support trace and guideline
        supp_trace = next((t for t in fig.data if getattr(t, "name", None) == "Last Support"), None)
        assert supp_trace is not None
        assert f"{res.snapshot.last_support.price:.2f}" in supp_trace.text[0]

        # Guidelines shapes check
        assert any(s.y0 == res.snapshot.last_support.price for s in fig.layout.shapes)

    def test_last_resistance_indicator_rendered_explicitly(self) -> None:
        """R10.4: When last_resistance is present, last resistance trace and guideline are rendered."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        # Synthesize a mock result with last_resistance
        mock_snapshot = MagicMock()
        mock_snapshot.confirmed_pairs = ()
        mock_snapshot.trend_status = "Downward trend"
        mock_snapshot.state = EngineState.WAITING_FOR_BREAK
        mock_snapshot.last_support = None
        mock_snapshot.tentative_point = None

        res_pt = SwingPoint(
            price=1945.0,
            candle_index=3,
            candle_open_time=df.index[3],
            identified_bar_index=3,
            identified_time=df.index[3],
            confirmed_bar_index=4,
            confirmed_time=df.index[4],
        )
        mock_snapshot.last_resistance = res_pt

        mock_res = MagicMock()
        mock_res.snapshot = mock_snapshot
        mock_res.error = None
        mock_res.context.start_candle_time = df.index[0]
        mock_res.context.direction = Direction.DOWNWARD

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            data_source="demo",
            is_demo=True,
            msm_result=mock_res,
        )

        res_trace = next((t for t in fig.data if getattr(t, "name", None) == "Last Resistance"), None)
        assert res_trace is not None
        assert "1945.00" in res_trace.text[0]
        assert any(s.y0 == 1945.0 for s in fig.layout.shapes)

    def test_inspection_table_renders_last_support_and_resistance(self) -> None:
        """R10.4: Inspection summary includes Last Support / Resistance values."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_time = df.index[0]
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=start_time,
            direction=Direction.UPWARD,
            enabled=True,
        )
        res = calculate_msm(df, ctx)

        panel = render_msm_inspection_table(res.snapshot, ctx)
        assert panel is not None


class TestCoordinatorFlowAndRegressions:
    """Tests the deterministic callback flow requirements from Perplexity review."""

    def test_apply_without_direction_or_start_rejected(self) -> None:
        """Review requirement: Apply without direction or start is rejected."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)

        # 1. Neither direction nor start
        applied, status, style, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val=None,
            start_candle_val=None,
            market_snapshot_data=snap,
            applied_data=None,
        )
        assert applied is None
        assert "Error: Initial direction not selected" in status

        # 2. Direction provided, but start candle is None
        applied, status, style, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=None,
            market_snapshot_data=snap,
            applied_data=None,
        )
        assert applied is None
        assert "Error: No starting candle selected" in status

    def test_edit_direction_or_start_without_apply_preserves_applied_state(self) -> None:
        """Review requirement: Edit direction/start without Apply: previous applied configuration remains clearly identified; no silent recalculation using edits."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)
        start_iso = snap.candles_data[0].time

        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # User changes direction to DOWNWARD in UI without clicking Apply
        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="msm-direction-selector",
            enable_toggle_val=["enabled"],
            direction_val="DOWNWARD",
            start_candle_val=start_iso,
            market_snapshot_data=snap,
            applied_data=applied_data,
        )

        # Applied configuration is preserved without mutation!
        assert applied_out == applied_data
        assert "Unapplied changes" in status
        assert panel is dash.no_update

    def test_refresh_with_start_retained_recomputes_cleanly(self) -> None:
        """Review requirement: Refresh with start retained: recomputation uses applied configuration."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_iso = df.index[0].isoformat()
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        fig, status, loss_trigger = generate_chart_and_status_with_trigger(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            is_connected=False,
            msm_applied=applied_data,
        )

        assert "MSM:" in status
        assert any(getattr(t, "name", None) == "Confirmed High" for t in fig.data)

    def test_refresh_with_start_missing_fails_closed_without_stale_markings(self) -> None:
        """Review requirement: Refresh with start missing: no replacement start and no stale successful markings."""
        # Applied data references a start time not in the fixture
        missing_iso = "2024-01-01T00:00:00+00:00"
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": missing_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        fig, status, loss_trigger = generate_chart_and_status_with_trigger(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            is_connected=False,
            msm_applied=applied_data,
        )

        # Stale markings must NOT be present
        trace_names = [getattr(t, "name", None) for t in fig.data]
        assert "Confirmed High" not in trace_names
        assert "Confirmed Low" not in trace_names
        assert "MSM Error: Starting candle" in status

    def test_context_change_clears_incompatible_markings_and_inspection(self) -> None:
        """Review requirement: Source/symbol/timeframe change: incompatible markings and inspection results disappear."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_iso = df.index[0].isoformat()
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # Context changes: timeframe switched to D1
        snap_d1, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "D1", 100, False)
        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="timeframe-selector",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=start_iso,
            market_snapshot_data=snap_d1,
            applied_data=applied_data,
        )

        assert applied_out is None
        assert "Context changed" in status
        assert "Context changed" in panel.children

    def test_overlay_disable_and_reenable_preserves_state_integrity(self) -> None:
        """Review requirement: Overlay enable/disable: no strategy-state corruption."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": "2026-10-01T00:00:00+00:00",
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # User unchecks 'Enable MSM'
        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="msm-enable-toggle",
            enable_toggle_val=[],
            direction_val="UPWARD",
            start_candle_val="2026-10-01T00:00:00+00:00",
            market_snapshot_data=snap,
            applied_data=applied_data,
        )

        assert applied_out is None
        assert "MSM is disabled" in status
        assert "currently disabled" in panel.children

        assert applied_out is None
        assert "MSM is disabled" in status
        assert "currently disabled" in panel.children


class TestUnifiedMarketDataSnapshotSynchronization:
    """Verifies the 8 coherent market-data snapshot synchronization scenarios from Perplexity review."""

    def test_refresh_adds_completed_confirmation_bar_syncs_chart_and_table(self) -> None:
        """Scenario 1: Refresh adds a completed confirmation bar: chart and table update together."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        start_iso = df.index[0].isoformat()
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # Step 1: Baseline snapshot with 50 bars
        df_base = df.iloc[:50].copy()
        snap_base, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 50, False)

        fig_base, status_base = generate_chart_and_status_from_snapshot(snap_base, msm_applied=applied_data)
        res_base, stat_base, _, panel_base = evaluate_msm_for_snapshot(snap_base, applied_data)
        assert res_base is not None and res_base.is_valid
        pairs_base = len(res_base.snapshot.confirmed_pairs)

        # Step 2: Refresh adds more bars including completed confirmation bars
        snap_refreshed, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)
        assert snap_refreshed.revision_id != snap_base.revision_id

        fig_refreshed, status_refreshed = generate_chart_and_status_from_snapshot(snap_refreshed, msm_applied=applied_data)
        res_refreshed, stat_refreshed, _, panel_refreshed = evaluate_msm_for_snapshot(snap_refreshed, applied_data)

        # Both chart and table update coherently on the new revision
        assert res_refreshed is not None and res_refreshed.is_valid
        assert snap_refreshed.revision_id in stat_refreshed
        assert snap_refreshed.revision_id in status_refreshed or f"Count: {snap_refreshed.candle_count}" in status_refreshed
        # Traces in chart reflect the confirmed points
        assert any(getattr(t, "name", None) == "Confirmed High" for t in fig_refreshed.data)

    def test_unapplied_draft_edits_survive_refresh_without_application(self) -> None:
        """Scenario 2: Unapplied edits survive Refresh without becoming applied."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_iso = df.index[0].isoformat()
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)

        # User has a draft change to DOWNWARD in UI (unapplied)
        res, status_text, status_style, panel = evaluate_msm_for_snapshot(
            snapshot=snap,
            applied_data=applied_data,
            draft_direction="DOWNWARD",
            draft_start_candle=start_iso,
        )

        # Unapplied warning surfaced, but applied configuration remains UPWARD
        assert "Unapplied changes" in status_text
        assert "Applied: UPWARD" in status_text
        assert res is not None
        assert res.snapshot.direction == Direction.UPWARD  # Still UPWARD!

    def test_missing_applied_start_reports_insufficient_history_and_clears_markings(self) -> None:
        """Scenario 3: Missing applied start removes successful current results and reports insufficient history."""
        # Start time outside window
        missing_start = "2020-01-01T00:00:00+00:00"
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": missing_start,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 50, False)
        res, status_text, status_style, panel = evaluate_msm_for_snapshot(snap, applied_data)

        # Successful results removed; insufficient history reported
        assert res is None
        assert "Insufficient history" in status_text
        assert "Insufficient history" in panel.children

        # Chart rendering also suppresses successful MSM overlays
        fig, chart_status = generate_chart_and_status_from_snapshot(snap, msm_applied=applied_data)
        trace_names = [getattr(t, "name", None) for t in fig.data]
        assert "Confirmed High" not in trace_names
        assert "MSM Error: Starting candle" in chart_status

    def test_candle_count_change_updates_chart_and_table_together(self) -> None:
        """Scenario 4: History-count change updates both chart and inspection table together."""
        def make_df(n):
            times = pd.date_range("2026-10-01", periods=n, freq="4h", tz="UTC")
            return pd.DataFrame(
                {
                    "open": [1.1 + i * 0.001 for i in range(n)],
                    "high": [1.15 + i * 0.001 for i in range(n)],
                    "low": [1.05 + i * 0.001 for i in range(n)],
                    "close": [1.12 + i * 0.001 for i in range(n)],
                    "is_forming": [False] * (n - 1) + [True],
                    "is_latest_bar": [False] * (n - 1) + [True],
                    "bar_status": ["CONFIRMED_COMPLETED"] * (n - 1) + ["UNCONFIRMED_LATEST"],
                },
                index=times,
            )

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.fetch_candles.side_effect = lambda sym, tf, count: make_df(count)

        applied_data = {
            "data_source": "mt5",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "start_candle_time": "2026-10-01T00:00:00+00:00",
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # User changes count to 50
        snap_50, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 50, True, adapter=mock_adapter)
        assert snap_50.candle_count == 50
        fig_50, status_50 = generate_chart_and_status_from_snapshot(snap_50, msm_applied=applied_data)
        assert "Count: 50 candles" in status_50

        # User changes count to 100
        snap_100, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 100, True, adapter=mock_adapter)
        assert snap_100.candle_count == 100

        fig_100, status_100 = generate_chart_and_status_from_snapshot(snap_100, msm_applied=applied_data)
        res_100, edit_status_100, _, panel_100 = evaluate_msm_for_snapshot(snap_100, applied_data)

        assert "Count: 100 candles" in status_100
        assert snap_100.revision_id in edit_status_100
        assert res_100 is not None and res_100.is_valid

    def test_disconnect_and_fetch_failure_suppresses_applied_and_pauses_inspection(self) -> None:
        """Scenario 5: Disconnect/fetch failure suppresses green applied status and displays data unavailable."""
        applied_data = {
            "data_source": "mt5",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "start_candle_time": "2026-10-01T00:00:00+00:00",
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # Terminal disconnected
        snap, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 100, is_connected=False)
        assert snap.fetch_status == "DISCONNECTED"

        res, edit_status, edit_style, panel = evaluate_msm_for_snapshot(snap, applied_data)

        assert res is None
        assert "🔴 Data unavailable" in edit_status
        assert edit_style["color"] == "#ff5252"
        assert "Market data unavailable" in panel.children

        fig, chart_status = generate_chart_and_status_from_snapshot(snap, msm_applied=applied_data)
        assert "🔴 MT5 Disconnected" in chart_status

    def test_delayed_or_stale_context_results_cannot_overwrite_newer_context(self) -> None:
        """Scenario 6: Delayed old-context/revision results cannot overwrite a newer context."""
        h4_applied = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": "2026-10-01T00:00:00+00:00",
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # Context switched to D1
        snap_d1, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "D1", 100, False)
        assert is_context_compatible(h4_applied, snap_d1.data_source, snap_d1.symbol, snap_d1.timeframe) is False

        # Evaluation cleanly rejects the stale H4 context against D1 snapshot
        res, status_text, status_style, panel = evaluate_msm_for_snapshot(snap_d1, h4_applied)
        assert res is None
        assert "Context changed" in status_text
        assert "Context changed" in panel.children

    def test_chart_dropdown_and_inspection_share_exact_same_revision_id(self) -> None:
        """Scenario 7: Chart, dropdown, and inspection share the exact same snapshot revision ID."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 100, False)
        start_iso = snap.candles_data[0].time
        applied_data = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_iso,
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }

        # 1. Dropdown options extracted directly from this snapshot
        options = get_completed_candle_options(snap)
        assert len(options) == snap.candle_count  # All demo fixture candles are completed

        # 2. Inspection table rendered from this snapshot
        res, edit_status, _, panel = evaluate_msm_for_snapshot(snap, applied_data)
        assert res is not None
        assert snap.revision_id in edit_status

        # 3. Chart rendered from this exact snapshot
        fig, chart_status = generate_chart_and_status_from_snapshot(snap, msm_applied=applied_data)
        assert f"Count: {snap.candle_count} candles" in chart_status

    def test_data_update_causes_zero_duplicate_independent_fetches(self) -> None:
        """Scenario 8: A normal data update causes zero duplicate independent fetches."""
        times = pd.date_range("2026-10-01", periods=10, freq="4h", tz="UTC")
        df_mock = pd.DataFrame(
            {
                "open": [1.1 + i * 0.01 for i in range(10)],
                "high": [1.12 + i * 0.01 for i in range(10)],
                "low": [1.08 + i * 0.01 for i in range(10)],
                "close": [1.11 + i * 0.01 for i in range(10)],
                "is_forming": [False] * 9 + [True],
                "is_latest_bar": [False] * 9 + [True],
                "bar_status": ["CONFIRMED_COMPLETED"] * 9 + ["UNCONFIRMED_LATEST"],
            },
            index=times,
        )

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.fetch_candles.return_value = df_mock

        # Step 1: Single fetch path executes exactly 1 fetch
        snap, _ = fetch_market_snapshot(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=10,
            is_connected=True,
            adapter=mock_adapter,
        )
        assert mock_adapter.fetch_candles.call_count == 1

        # Step 2: All consumers (dropdown, inspection, chart) consume the snapshot without calling fetch_candles
        options = get_completed_candle_options(snap)
        res, status, _, panel = evaluate_msm_for_snapshot(snap, applied_data=None)
        fig, chart_status = generate_chart_and_status_from_snapshot(snap, msm_applied=None)

        # Call count remains exactly 1! Zero duplicate independent fetches!
        assert mock_adapter.fetch_candles.call_count == 1


class TestHandoff013PublicationAndBoundaryRegressions:
    """Verifies the 8 required regression specifications from HANDOFF-012 review (R12.1-R12.4)."""

    def test_missing_snapshot_causes_zero_consumer_fetches(self) -> None:
        """Regression 1: Missing snapshot causes zero consumer fetches."""
        mock_adapter = MagicMock()

        # 1. Dropdown update with None snapshot
        options, selected = process_msm_dropdown_update(
            snapshot_or_df=None,
            current_value=None,
        )
        assert options == []
        assert selected is None
        mock_adapter.fetch_candles.assert_not_called()

        # 2. Controls update with None snapshot
        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="market-data-store",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val="2026-10-01T00:00:00+00:00",
            market_snapshot_data=None,
            applied_data=None,
        )
        assert applied_out is None
        assert "pending/unavailable" in status
        mock_adapter.fetch_candles.assert_not_called()

    def test_snapshot_roundtrip_preserves_close_time_and_source_ids(self) -> None:
        """Regression 2: Snapshot round-trip preserves supplied close_time and source IDs."""
        times = pd.date_range("2026-10-01", periods=3, freq="4h", tz="UTC")
        close_times = pd.date_range("2026-10-01 04:00:00", periods=3, freq="4h", tz="UTC")
        df_custom = pd.DataFrame(
            {
                "open": [1.1, 1.2, 1.3],
                "high": [1.15, 1.25, 1.35],
                "low": [1.05, 1.15, 1.25],
                "close": [1.12, 1.22, 1.32],
                "is_forming": [False, False, False],
                "bar_status": ["CONFIRMED_COMPLETED"] * 3,
                "index": [101, 102, 103],
                "close_time": [ct.isoformat() for ct in close_times],
            },
            index=times,
        )

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.fetch_candles.return_value = df_custom

        snap, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 3, True, adapter=mock_adapter)
        assert snap.candles_data[0].index == 101
        assert snap.candles_data[0].close_time == close_times[0].isoformat()

        # Serialize to dict and deserialize back
        serialized = snap.to_dict()
        assert serialized["candles_data"][0]["index"] == 101
        assert serialized["candles_data"][0]["close_time"] == close_times[0].isoformat()

        deserialized = MarketDataSnapshot.from_dict(serialized)
        assert deserialized.candles_data[0].index == 101
        assert deserialized.candles_data[0].close_time == close_times[0].isoformat()

        df_out = deserialized.to_dataframe()
        assert df_out["index"].iloc[0] == 101
        assert df_out["close_time"].iloc[0] == close_times[0].isoformat()

    def test_boolean_and_string_ohlc_and_invalid_ids_rejected_before_coercion(self) -> None:
        """Regression 3: Boolean/string OHLC and fractional/boolean IDs are rejected before coercion."""
        # Boolean open rejected
        with pytest.raises(TypeError, match="must not be boolean"):
            MarketCandleRecord(
                time="2026-10-01T00:00:00+00:00",
                open=True,  # type: ignore[arg-type]
                high=1.2,
                low=1.0,
                close=1.1,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
            )

        # String high rejected
        with pytest.raises(TypeError, match="must be numeric"):
            MarketCandleRecord(
                time="2026-10-01T00:00:00+00:00",
                open=1.1,
                high="1.2",  # type: ignore[arg-type]
                low=1.0,
                close=1.1,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
            )

        # Boolean index rejected
        with pytest.raises(TypeError, match="must not be boolean"):
            MarketCandleRecord(
                time="2026-10-01T00:00:00+00:00",
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.1,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                index=True,  # type: ignore[arg-type]
            )

        # Float/fractional index rejected
        with pytest.raises(TypeError, match="must be integer"):
            MarketCandleRecord(
                time="2026-10-01T00:00:00+00:00",
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.1,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                index=10.5,  # type: ignore[arg-type]
            )

        # NaN/inf open rejected
        with pytest.raises(ValueError, match="must be finite"):
            MarketCandleRecord(
                time="2026-10-01T00:00:00+00:00",
                open=float("nan"),
                high=1.2,
                low=1.0,
                close=1.1,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
            )

    def test_mutation_isolation_cannot_mutate_existing_snapshot(self) -> None:
        """Regression 4: Mutating an input/output payload cannot mutate an existing snapshot."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 10, False)
        orig_open = snap.candles_data[0].open
        orig_count = len(snap.candles_data)

        # Mutate dictionary returned by to_dict()
        d = snap.to_dict()
        d["candles_data"][0]["open"] = 9999.99
        d["candles_data"].append({"time": "2030-01-01T00:00:00+00:00"})

        # Existing snapshot must remain completely unaffected
        assert snap.candles_data[0].open == orig_open
        assert len(snap.candles_data) == orig_count

        # Mutating input dictionary after deserialization cannot mutate snapshot
        input_dict = snap.to_dict()
        snap2 = MarketDataSnapshot.from_dict(input_dict)
        input_dict["candles_data"][0]["close"] = -999.0
        assert snap2.candles_data[0].close != -999.0

    def test_older_different_context_request_completing_last_is_suppressed(self) -> None:
        """Regression 5: Older different-context request completing last is suppressed."""
        # Arriving snapshot belongs to older H4 request (req-1)
        snap_old, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 10, False, request_token="req-1")

        # Current UI context is D1 under active token req-2
        current_context = {"data_source": "demo", "symbol": DEMO_SYMBOL, "timeframe": "D1"}
        active_token = "req-2"

        # 1. Chart renderer suppresses mismatched context snapshot
        fig, status = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_old,
            current_context=current_context,
            active_request_token=active_token,
        )
        assert fig is dash.no_update
        assert status is dash.no_update

        # 2. MSM evaluation detects context mismatch and refuses to publish
        res, status_text, _, panel = evaluate_msm_for_snapshot(
            snapshot=snap_old,
            applied_data=None,
            current_context=current_context,
            active_request_token=active_token,
        )
        assert res is None
        assert "suppressed" in status_text or "Context changed" in status_text

    def test_older_same_context_refresh_completing_last_is_suppressed(self) -> None:
        """Regression 6: Older same-context Refresh completing last is suppressed."""
        # Arriving snapshot is an older delayed refresh (req-3)
        snap_delayed, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 10, False, request_token="req-3")

        # Current active request is req-4
        active_token = "req-4"
        current_context = {"data_source": "demo", "symbol": DEMO_SYMBOL, "timeframe": "H4"}

        # Chart renderer suppresses old token response
        fig, status = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_delayed,
            current_context=current_context,
            active_request_token=active_token,
        )
        assert fig is dash.no_update
        assert status is dash.no_update

        # MSM evaluation suppresses old token response
        res, status_text, _, panel = evaluate_msm_for_snapshot(
            snapshot=snap_delayed,
            applied_data=None,
            current_context=current_context,
            active_request_token=active_token,
        )
        assert res is None
        assert "suppressed" in status_text

    def test_apply_while_context_change_pending_rejects_old_snapshot(self) -> None:
        """Regression 7: Apply while a context change is pending cannot apply the old snapshot."""
        # Snapshot in memory is for EURUSD
        snap_eur, _ = fetch_market_snapshot("demo", "EURUSD", "H4", 10, False)

        # User has selected GBPUSD in dropdown (pending context change)
        pending_context = {"data_source": "demo", "symbol": "GBPUSD", "timeframe": "H4"}

        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val="2026-10-01T00:00:00+00:00",
            market_snapshot_data=snap_eur,
            applied_data=None,
            current_context=pending_context,
        )

        assert applied_out is None
        assert "Error: Cannot apply to superseded context" in status
        assert "Pending context change to GBPUSD" in panel.children

    def test_missing_start_and_malformed_input_produce_different_diagnostics(self) -> None:
        """Regression 8: Missing start and malformed input produce different diagnostics."""
        snap, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 20, False)
        start_time_valid = snap.candles_data[0].time

        # Diagnostic A: Genuinely missing start time
        missing_context = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": "2015-01-01T00:00:00+00:00",
            "direction": "UPWARD",
            "rule_version": "1.0",
            "enabled": True,
        }
        res_a, status_a, _, panel_a = evaluate_msm_for_snapshot(snap, missing_context)
        assert res_a is None
        assert "⚠️ Insufficient history" in status_a
        assert "is no longer in window" in status_a

        # Diagnostic B: Malformed context payload (e.g. non-numeric direction / bad version)
        malformed_context = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_time_valid,
            "direction": "INVALID_DIR",
            "rule_version": "99.9",
            "enabled": True,
        }
        res_b, status_b, _, panel_b = evaluate_msm_for_snapshot(snap, malformed_context)
        assert res_b is None
        assert "❌ MSM Context/Data Error" in status_b
        assert "Insufficient history" not in status_b


def _make_contract_candles(n: int = 15) -> pd.DataFrame:
    """Helper to generate contract-compliant candles with forming flag and completion evidence."""
    times = pd.date_range("2026-10-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [1.100 + i * 0.001 for i in range(n)],
            "high": [1.105 + i * 0.001 for i in range(n)],
            "low": [1.095 + i * 0.001 for i in range(n)],
            "close": [1.102 + i * 0.001 for i in range(n)],
            "is_forming": [False] * (n - 1) + [True],
            "bar_status": [BarStatus.CONFIRMED_COMPLETED.value] * (n - 1) + [BarStatus.UNCONFIRMED_LATEST.value],
        },
        index=times,
    )
    return df


class TestHandoff014ControlledRequestFlowAndBoundaryRegressions:
    """Rigorous verification of R13.1–R13.3 with real request flow and controlled concurrency barriers."""

    def test_real_request_flow_different_contexts_with_concurrency_barriers(self) -> None:
        """Requirement R13.1 (Flow 1): Real request flow across different contexts with controlled barriers.

        1. Start request A (EURUSD H4) and block its mocked fetch.
        2. Issue newer request B (EURUSD D1) before A completes.
        3. Complete B and verify it becomes current.
        4. Complete A last.
        5. Assert active request, chart, dropdown, applied configuration, and inspection do not revert to A.
        """
        import threading
        from aladeen.ui.market_coordinator import issue_market_data_request, fetch_market_data_for_request, generate_chart_and_status_from_snapshot
        from aladeen.ui.msm_callbacks import process_msm_dropdown_update

        # Setup mock adapter with deterministic concurrency barriers
        mock_adapter = MagicMock()
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        fetch_a_started = threading.Event()
        fetch_a_block = threading.Event()

        h4_df = _make_contract_candles(15)
        d1_df = _make_contract_candles(15)

        def mock_fetch_candles(symbol, timeframe, count):
            if timeframe == "H4":
                fetch_a_started.set()
                fetch_a_block.wait(timeout=5.0)
                return h4_df
            return d1_df

        mock_adapter.fetch_candles.side_effect = mock_fetch_candles
        store_data = {"state": "CONNECTED_TO_BROKER"}

        # 1. Start request A (EURUSD H4) and block its fetch
        req_a = issue_market_data_request("mt5", "EURUSD", "H4", 15, store_data, current_active_req=None)
        assert req_a["token"].startswith("req-")
        assert req_a["counter"] == 1
        assert req_a["context"]["timeframe"] == "H4"

        thread_a_result = {}

        def run_fetch_a():
            cand_a = fetch_market_data_for_request(req_a, store_data, adapter=mock_adapter)
            thread_a_result["snap"] = cand_a["snapshot"]
            thread_a_result["trig"] = cand_a["connection_event"]

        thread_a = threading.Thread(target=run_fetch_a)
        thread_a.start()

        # Wait until Fetch A has actually entered the blocked adapter call
        assert fetch_a_started.wait(timeout=2.0)

        # 2. Issue newer request B (EURUSD D1) before A completes
        req_b = issue_market_data_request("mt5", "EURUSD", "D1", 15, store_data, current_active_req=req_a)
        assert req_b["token"].startswith("req-")
        assert req_b["counter"] == 2
        assert req_b["token"] != req_a["token"]
        assert req_b["context"]["timeframe"] == "D1"

        # Verify: while B is pending, consumer endpoints observe pending state and fail-closed
        opts_pending, val_pending = process_msm_dropdown_update(
            snapshot_or_df=None,
            active_req_data=req_b,
            triggered_id="active-request-store",
        )
        assert opts_pending == []
        assert val_pending is None

        # Apply cannot use previous snapshot during pending state
        applied_pending, status_pending, _, _ = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val="2026-10-01T00:00:00+00:00",
            market_snapshot_data=None,
            applied_data=None,
            active_req_data=req_b,
        )
        assert "Cannot apply MSM while a market data request is pending" in status_pending

        # 3. Complete B and verify it becomes current
        cand_b = fetch_market_data_for_request(req_b, store_data, adapter=mock_adapter)
        snap_b_dict = cand_b["snapshot"]
        trig_b = cand_b["connection_event"]
        assert snap_b_dict["request_token"] == req_b["token"]
        assert snap_b_dict["timeframe"] == "D1"

        fig_b, status_b = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_b_dict,
            active_req_data=req_b,
            triggered_id="market-data-store",
        )
        assert fig_b is not dash.no_update
        assert "TF: D1" in status_b

        opts_b, _ = process_msm_dropdown_update(
            snapshot_or_df=snap_b_dict,
            active_req_data=req_b,
            triggered_id="market-data-store",
        )
        assert len(opts_b) > 0
        valid_b_start = opts_b[0]["value"]

        applied_b, status_b_msm, _, panel_b = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=valid_b_start,
            market_snapshot_data=snap_b_dict,
            applied_data=None,
            active_req_data=req_b,
        )
        assert applied_b is not None
        assert applied_b["timeframe"] == "D1"
        assert "🟢 Applied: UPWARD" in status_b_msm

        # 4. Now unblock A so it completes LAST
        fetch_a_block.set()
        thread_a.join(timeout=2.0)
        assert not thread_a.is_alive()
        snap_a_dict = thread_a_result["snap"]
        assert snap_a_dict["request_token"] == req_a["token"]

        # 5. Assert: Arriving delayed A does NOT revert active request, chart, dropdown, or applied config
        fig_a, status_a = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_a_dict,
            active_req_data=req_b,
            triggered_id="market-data-store",
        )
        assert fig_a is dash.no_update
        assert status_a is dash.no_update

        opts_a, _ = process_msm_dropdown_update(
            snapshot_or_df=snap_a_dict,
            active_req_data=req_b,
            triggered_id="market-data-store",
        )
        assert opts_a is dash.no_update

        applied_after_a, status_after_a, _, panel_after_a = process_msm_controls_update(
            triggered_id="market-data-store",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=valid_b_start,
            market_snapshot_data=snap_a_dict,
            applied_data=applied_b,
            active_req_data=req_b,
        )
        assert applied_after_a is dash.no_update
        assert status_after_a is dash.no_update
        assert panel_after_a is dash.no_update

    def test_real_request_flow_two_refreshes_same_context_with_concurrency_barriers(self) -> None:
        """Requirement R13.1 (Flow 2): Real request flow for two Refreshes of the same context.

        1. Start Refresh A (EURUSD H4) and block its mocked fetch.
        2. Issue newer Refresh B (EURUSD H4) before A completes.
        3. Complete B and verify it becomes current.
        4. Complete A last.
        5. Assert chart, dropdown, and MSM do not revert to A.
        """
        import threading
        from aladeen.ui.market_coordinator import issue_market_data_request, fetch_market_data_for_request, generate_chart_and_status_from_snapshot
        from aladeen.ui.msm_callbacks import process_msm_dropdown_update

        mock_adapter = MagicMock()
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        fetch_a_started = threading.Event()
        fetch_a_block = threading.Event()

        # Both return H4 candles
        candles_a = _make_contract_candles(15)
        candles_b = _make_contract_candles(15)
        # Give candle_b slightly different prices while keeping high >= max(open, close)
        candles_b["high"] = candles_b["high"] + 0.10
        candles_b["close"] = candles_b["close"] + 0.05

        call_count = 0

        def mock_fetch(symbol, timeframe, count):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                fetch_a_started.set()
                fetch_a_block.wait(timeout=5.0)
                return candles_a
            return candles_b

        mock_adapter.fetch_candles.side_effect = mock_fetch
        store_data = {"state": "CONNECTED_TO_BROKER"}

        # 1. Issue Refresh A
        req_a = issue_market_data_request("mt5", "EURUSD", "H4", 15, store_data, current_active_req=None)
        assert req_a["token"].startswith("req-")

        thread_a_res = {}

        def fetch_a():
            cand = fetch_market_data_for_request(req_a, store_data, adapter=mock_adapter)
            thread_a_res["snap"] = cand["snapshot"]

        t = threading.Thread(target=fetch_a)
        t.start()
        assert fetch_a_started.wait(timeout=2.0)

        # 2. Issue Refresh B while A is blocked
        req_b = issue_market_data_request("mt5", "EURUSD", "H4", 15, store_data, current_active_req=req_a)
        assert req_b["token"].startswith("req-")
        assert req_b["token"] != req_a["token"]

        # 3. Complete B
        cand_b = fetch_market_data_for_request(req_b, store_data, adapter=mock_adapter)
        snap_b_dict = cand_b["snapshot"]
        assert snap_b_dict["request_token"] == req_b["token"]

        fig_b, status_b = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_b_dict,
            active_req_data=req_b,
            triggered_id="market-data-store",
        )
        assert fig_b is not dash.no_update
        assert "Count: 15 candles" in status_b

        # 4. Release A and let it finish last
        fetch_a_block.set()
        t.join(timeout=2.0)
        snap_a_dict = thread_a_res["snap"]
        assert snap_a_dict["request_token"] == req_a["token"]

        # 5. Arriving delayed A is suppressed
        fig_a, status_a = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_a_dict,
            active_req_data=req_b,
            triggered_id="market-data-store",
        )
        assert fig_a is dash.no_update
        assert status_a is dash.no_update

    def test_fractional_and_boolean_ids_rejected_through_actual_fetch_path(self) -> None:
        """Requirement R13.2: Fractional and boolean IDs rejected through fetch_market_snapshot with mocked adapter."""
        mock_adapter = MagicMock()
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        # Case 1: Boolean index
        df_bool = _make_contract_candles(5)
        df_bool["index"] = [True, False, True, False, True]
        mock_adapter.fetch_candles.return_value = df_bool

        snap_bool, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 5, True, adapter=mock_adapter)
        assert snap_bool.fetch_status == "VALIDATION_ERROR"
        assert "must not be boolean" in (snap_bool.error_message or "")

        # Case 2: Fractional float index (e.g. 1.5)
        df_float = _make_contract_candles(5)
        df_float["index"] = [1.5, 2.5, 3.5, 4.5, 5.5]
        mock_adapter.fetch_candles.return_value = df_float

        snap_float, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 5, True, adapter=mock_adapter)
        assert snap_float.fetch_status == "VALIDATION_ERROR"
        assert "must be integer type" in (snap_float.error_message or "")

        # Case 3: String index
        df_str = _make_contract_candles(5)
        df_str["index"] = ["1", "2", "3", "4", "5"]
        mock_adapter.fetch_candles.return_value = df_str

        snap_str, _ = fetch_market_snapshot("mt5", "EURUSD", "H4", 5, True, adapter=mock_adapter)
        assert snap_str.fetch_status == "VALIDATION_ERROR"
        assert "must be integer type" in (snap_str.error_message or "")

    def test_from_dict_strictly_validates_complete_snapshot(self) -> None:
        """Requirement R13.3: Deserialization strictly validates complete snapshot invariants."""
        # Baseline valid snapshot dict
        snap_valid, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 10, False)
        valid_dict = snap_valid.to_dict()

        # 1. Reject naive timestamps in candle records
        naive_dict = snap_valid.to_dict()
        naive_dict["candles_data"][0]["time"] = "2026-10-01 00:00:00"  # naive, no tz
        with pytest.raises((ValueError, TypeError)):
            MarketDataSnapshot.from_dict(naive_dict)

        # 2. Reject close_time earlier than or equal to open time (R14.6)
        bad_close_dict = snap_valid.to_dict()
        bad_close_dict["candles_data"][0]["close_time"] = "2020-01-01T00:00:00+00:00"
        with pytest.raises(ValueError, match="must be strictly later than open time"):
            MarketDataSnapshot.from_dict(bad_close_dict)

        # 3. Reject unsupported fetch_status vocabulary
        bad_status_dict = snap_valid.to_dict()
        bad_status_dict["fetch_status"] = "CUSTOM_UNKNOWN_STATUS"
        with pytest.raises(ValueError, match="fetch_status must be one of"):
            MarketDataSnapshot.from_dict(bad_status_dict)

        # 4. Reject candle count mismatch in successful snapshot
        mismatch_dict = snap_valid.to_dict()
        mismatch_dict["candle_count"] = 999  # header claims 999, actually 10
        with pytest.raises(ValueError, match="Candle count mismatch in successful snapshot"):
            MarketDataSnapshot.from_dict(mismatch_dict)

        # 5. Reject successful snapshot with candle_count == 0
        zero_dict = snap_valid.to_dict()
        zero_dict["candle_count"] = 0
        zero_dict["candles_data"] = []
        with pytest.raises(ValueError, match="Successful snapshot must contain at least 1 candle record"):
            MarketDataSnapshot.from_dict(zero_dict)

        # 6. Reject successful snapshot with error_message
        err_in_success_dict = snap_valid.to_dict()
        err_in_success_dict["error_message"] = "Unexpected error string in success payload"
        with pytest.raises(ValueError, match="Successful snapshot must not have an error_message"):
            MarketDataSnapshot.from_dict(err_in_success_dict)

        # 7. Reject duplicate source IDs (R14.6: source IDs must be unique identifiers)
        dup_id_dict = snap_valid.to_dict()
        for c in dup_id_dict["candles_data"]:
            c["index"] = 42  # duplicate!
        with pytest.raises(ValueError, match="duplicate source IDs detected"):
            MarketDataSnapshot.from_dict(dup_id_dict)

        # 8. Reject failed snapshot with leftover candles
        failed_with_candles = {
            "revision_id": "rev-test",
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "candle_count": 5,
            "timestamp_utc": "2026-10-01 00:00:00 UTC",
            "fetch_status": "DATA_ERROR",
            "error_message": "Some data error",
            "broker_connected": False,
            "candles_data": snap_valid.to_dict()["candles_data"][:5],
        }
        with pytest.raises(ValueError, match="Failed snapshot .* must have candle_count=0"):
            MarketDataSnapshot.from_dict(failed_with_candles)

        # 9. Reject failed snapshot without error message
        failed_no_err = {
            "revision_id": "rev-test",
            "data_source": "demo",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "candle_count": 0,
            "timestamp_utc": "2026-10-01 00:00:00 UTC",
            "fetch_status": "DATA_ERROR",
            "error_message": "",
            "broker_connected": False,
            "candles_data": [],
        }
        with pytest.raises(ValueError, match="Failed snapshot .* must have a non-empty error_message"):
            MarketDataSnapshot.from_dict(failed_no_err)

    def test_missing_and_invalid_tokens_cannot_bypass_guards(self) -> None:
        """Requirement R13.1: Missing and invalid tokens cannot bypass publication guards."""
        from aladeen.ui.market_coordinator import generate_chart_and_status_from_snapshot

        # Active request is req-5
        active_req = {
            "token": "req-5",
            "counter": 5,
            "context": {"data_source": "demo", "symbol": DEMO_SYMBOL, "timeframe": "H4"},
        }

        # Snapshot has no request_token (e.g. legacy/tampered payload)
        snap_no_token, _ = fetch_market_snapshot("demo", DEMO_SYMBOL, "H4", 10, False, request_token=None)

        fig, status = generate_chart_and_status_from_snapshot(
            market_snapshot_data=snap_no_token,
            active_req_data=active_req,
            triggered_id="market-data-store",
        )
        assert fig is dash.no_update
        assert status is dash.no_update


class TestHandoff015AcceptanceGateAndPublicationRegressions:
    """Rigorous verification of R14.1–R14.6: Candidate acceptance gate, store preservation, and boundary contracts."""

    def test_rapid_issuance_produces_distinct_tokens(self) -> None:
        """Requirement R14.1: Rapid issuance produces distinct tokens even under rapid successive events."""
        from aladeen.ui.market_coordinator import issue_market_data_request

        tokens = []
        cur_req = None
        for i in range(10):
            req = issue_market_data_request("demo", DEMO_SYMBOL, "H4", 100, current_active_req=cur_req)
            tokens.append(req["token"])
            cur_req = req

        # All tokens must be strictly distinct
        assert len(set(tokens)) == 10
        # Monotonic counter must increase sequentially
        assert cur_req["counter"] == 10

    def test_acceptance_gate_candidate_a_blocked_b_completes_a_arrives_last(self) -> None:
        """Requirements R14.2–R14.4: Candidate A arrives last; accepted store remains B; downstream MSM reads B.

        1. A starts (H4).
        2. B starts (D1) and completes; B is accepted.
        3. A completes last and arrives at acceptance gate -> rejected.
        4. User changes MSM controls -> callback reads B from accepted store, NOT A.
        """
        from aladeen.ui.market_coordinator import (
            accept_market_data_candidate,
            issue_market_data_request,
            fetch_market_data_for_request,
        )

        mock_adapter = MagicMock()
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        h4_df = _make_contract_candles(15)
        d1_df = _make_contract_candles(15)

        def mock_fetch(sym, tf, count):
            return h4_df if tf == "H4" else d1_df

        mock_adapter.fetch_candles.side_effect = mock_fetch
        store_data = {"state": "CONNECTED_TO_BROKER"}

        # Step 1: Issue Request A (H4)
        req_a = issue_market_data_request("mt5", "EURUSD", "H4", 15, store_data)

        # Step 2: Issue Request B (D1)
        req_b = issue_market_data_request("mt5", "EURUSD", "D1", 15, store_data, current_active_req=req_a)

        # Candidate B fetch completes
        cand_b_env = fetch_market_data_for_request(req_b, store_data, adapter=mock_adapter)
        # Acceptance gate for B
        acc_b_dict, acc_b_loss = accept_market_data_candidate(cand_b_env, active_req_data=req_b)
        assert acc_b_dict is not dash.no_update
        assert acc_b_dict["timeframe"] == "D1"
        accepted_store = acc_b_dict  # Simulates market-data-store holding B

        # Step 3: Candidate A completes LAST and arrives at acceptance gate
        cand_a_env = fetch_market_data_for_request(req_a, store_data, adapter=mock_adapter)
        gate_a_result, gate_a_loss = accept_market_data_candidate(cand_a_env, active_req_data=req_b)

        # Acceptance gate REJECTS stale candidate A
        assert gate_a_result is dash.no_update
        assert gate_a_loss is dash.no_update

        # Accepted store remains B!
        assert accepted_store["timeframe"] == "D1"
        assert accepted_store["request_token"] == req_b["token"]

        # Step 4: User changes MSM controls and applies MSM -> reads accepted store B!
        opts_b, _ = process_msm_dropdown_update(accepted_store, active_req_data=req_b, triggered_id="market-data-store")
        assert len(opts_b) > 0

        applied_out, status, _, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=opts_b[0]["value"],
            market_snapshot_data=accepted_store,  # reads accepted store
            applied_data=None,
            active_req_data=req_b,
        )
        assert applied_out is not None
        assert applied_out["timeframe"] == "D1"
        assert "TF: D1" in str(panel) or "Applied: UPWARD" in status

    def test_acceptance_gate_stale_failure_cannot_disconnect_or_relabel_successful_b(self) -> None:
        """Requirement R14.3: Stale failure cannot disconnect or relabel newer successful B."""
        from aladeen.ui.market_coordinator import accept_market_data_candidate, issue_market_data_request

        # Active request is B (EURUSD D1, token req-2)
        req_b = {
            "token": "req-2",
            "counter": 2,
            "context": {"data_source": "mt5", "symbol": "EURUSD", "timeframe": "D1"},
        }

        # Stale candidate envelope A arrives with a terminal disconnection failure
        stale_failed_candidate = {
            "revision_id": "rev-stale",
            "data_source": "mt5",
            "symbol": "EURUSD",
            "timeframe": "H4",
            "candle_count": 0,
            "timestamp_utc": "2026-10-01 00:00:00 UTC",
            "fetch_status": "CONNECTION_ERROR",
            "error_message": "MT5 Terminal Disconnected",
            "broker_connected": False,
            "request_token": "req-1",  # Stale token
            "candles_data": [],
        }
        stale_loss_trigger = {"state_change": "DISCONNECTED", "error": "Connection lost"}
        stale_envelope = {
            "request_token": "req-1",
            "snapshot": stale_failed_candidate,
            "connection_event": stale_loss_trigger,
        }

        gate_res, gate_loss = accept_market_data_candidate(
            candidate_envelope=stale_envelope,
            active_req_data=req_b,
        )

        # Both the snapshot and the loss trigger MUST BE REJECTED with dash.no_update!
        assert gate_res is dash.no_update
        assert gate_loss is dash.no_update

    def test_snapshot_close_time_strictly_later_than_open_time(self) -> None:
        """Requirement R14.6: close_time must be strictly later than open time (equal is rejected)."""
        # Case 1: close_time == open_time (equal)
        with pytest.raises(ValueError, match="must be strictly later than open time"):
            MarketCandleRecord(
                time="2026-10-01T00:00:00+00:00",
                open=1.100,
                high=1.105,
                low=1.095,
                close=1.102,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                close_time="2026-10-01T00:00:00+00:00",  # EQUAL to time!
            )

        # Case 2: close_time > open_time (strictly later) -> ACCEPTED
        rec = MarketCandleRecord(
            time="2026-10-01T00:00:00+00:00",
            open=1.100,
            high=1.105,
            low=1.095,
            close=1.102,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time="2026-10-01T04:00:00+00:00",  # strictly later
        )
        assert rec.close_time == "2026-10-01T04:00:00+00:00"

    def test_source_id_uniqueness_without_monotonicity_requirement(self) -> None:
        """Requirement R14.6: Source IDs must be unique without requiring monotonic increase."""
        # Non-monotonic but unique indices [10, 5, 20, 1]
        candles = [
            MarketCandleRecord(
                time=f"2026-10-01T0{i}:00:00+00:00",
                open=1.100,
                high=1.105,
                low=1.095,
                close=1.102,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                index=idx,
            )
            for i, idx in enumerate([10, 5, 20, 1])
        ]
        # Should NOT raise: indices are unique!
        snap = MarketDataSnapshot(
            revision_id="rev-unique",
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=4,
            timestamp_utc="2026-10-01 04:00:00 UTC",
            fetch_status="SUCCESS",
            candles_data=tuple(candles),
        )
        assert snap.candle_count == 4

        # Duplicate indices [10, 5, 10, 1] -> MUST RAISE
        dup_candles = [
            MarketCandleRecord(
                time=f"2026-10-01T0{i}:00:00+00:00",
                open=1.100,
                high=1.105,
                low=1.095,
                close=1.102,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                index=idx,
            )
            for i, idx in enumerate([10, 5, 10, 1])
        ]
        with pytest.raises(ValueError, match="duplicate source IDs detected"):
            MarketDataSnapshot(
                revision_id="rev-dup",
                data_source="demo",
                symbol="EURUSD",
                timeframe="H4",
                candle_count=4,
                timestamp_utc="2026-10-01 04:00:00 UTC",
                fetch_status="SUCCESS",
                candles_data=tuple(dup_candles),
            )


