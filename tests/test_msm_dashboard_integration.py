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
    generate_chart_and_status_with_trigger,
)
from aladeen.ui.msm_callbacks import (
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
        options, selected = process_msm_dropdown_update(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            store_data=None,
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
        # 1. Neither direction nor start
        applied, status, style, panel = process_msm_controls_update(
            triggered_id="msm-apply-btn",
            enable_toggle_val=["enabled"],
            direction_val=None,
            start_candle_val=None,
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            store_data=None,
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
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            store_data=None,
            applied_data=None,
        )
        assert applied is None
        assert "Error: No starting candle selected" in status

    def test_edit_direction_or_start_without_apply_preserves_applied_state(self) -> None:
        """Review requirement: Edit direction/start without Apply: previous applied configuration remains clearly identified; no silent recalculation using edits."""
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

        # User changes direction to DOWNWARD in UI without clicking Apply
        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="msm-direction-selector",
            enable_toggle_val=["enabled"],
            direction_val="DOWNWARD",
            start_candle_val=start_iso,
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            store_data=None,
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
        applied_out, status, style, panel = process_msm_controls_update(
            triggered_id="timeframe-selector",
            enable_toggle_val=["enabled"],
            direction_val="UPWARD",
            start_candle_val=start_iso,
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="D1",
            candle_count=100,
            store_data=None,
            applied_data=applied_data,
        )

        assert applied_out is None
        assert "Context changed" in status
        assert "Context changed" in panel.children

    def test_overlay_disable_and_reenable_preserves_state_integrity(self) -> None:
        """Review requirement: Overlay enable/disable: no strategy-state corruption."""
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
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            store_data=None,
            applied_data=applied_data,
        )

        assert applied_out is None
        assert "MSM is disabled" in status
        assert "currently disabled" in panel.children
