"""Offline integration tests for MSM Strategy Dashboard features.

Scope & Boundary:
-----------------
Tests the integration between:
1. Application service layer (MSMContext, calculate_msm, adapt_chart_dataframe)
2. UI Chart overlay construction (create_candlestick_chart with MSM traces)
3. UI Layout and callback coordination (MSM controls, start candle filtering, inspection table)
4. Context isolation across source / symbol / timeframe changes
5. Resilience against window shifts and missing start candles
"""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from aladeen.data.contract import BarStatus
from aladeen.data.fixtures import DEMO_SYMBOL, load_fixture
from aladeen.strategy.service import (
    MSMContext,
    MSMServiceResult,
    adapt_chart_dataframe,
    calculate_msm,
    is_context_compatible,
)
from aladeen.strategy.types import Direction, EngineState, StrategyCandle, SwingPoint, ConfirmedPair
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart
from aladeen.ui.layout import (
    get_completed_candle_options,
    generate_chart_and_status_with_trigger,
    render_msm_inspection_table,
)


class TestChartDataframeAdaptation:
    """Tests adapting chart DataFrames into validated StrategyCandles."""

    def test_adapt_demo_h4_fixture(self) -> None:
        """Demo H4 fixture adapts cleanly to StrategyCandles with stable integer IDs."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        assert df is not None
        candles = adapt_chart_dataframe(df)
        assert len(candles) == len(df)
        assert all(isinstance(c, StrategyCandle) for c in candles)
        # Check stable timestamp-derived index
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
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close"])
        empty_df.index = pd.DatetimeIndex([], tz="UTC")
        with pytest.raises(ValueError, match="DataFrame is empty"):
            adapt_chart_dataframe(empty_df)


class TestContextCompatibility:
    """Tests context isolation across symbols, timeframes, and sources."""

    def test_matching_context_is_compatible(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            enabled=True,
        )
        assert is_context_compatible(ctx, "demo", DEMO_SYMBOL, "H4") is True

    def test_symbol_mismatch_is_incompatible(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            enabled=True,
        )
        assert is_context_compatible(ctx, "demo", "EURUSD", "H4") is False

    def test_timeframe_mismatch_is_incompatible(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            enabled=True,
        )
        assert is_context_compatible(ctx, "demo", DEMO_SYMBOL, "D1") is False

    def test_data_source_mismatch_is_incompatible(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol="EURUSD",
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            enabled=True,
        )
        assert is_context_compatible(ctx, "mt5", "EURUSD", "H4") is False

    def test_disabled_context_is_incompatible(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            enabled=False,
        )
        assert is_context_compatible(ctx, "demo", DEMO_SYMBOL, "H4") is False

    def test_dict_serialization_compatibility(self) -> None:
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            enabled=True,
        )
        d = ctx.to_dict()
        assert is_context_compatible(d, "demo", DEMO_SYMBOL, "H4") is True


class TestMSMCalculationService:
    """Tests execution of MSM calculations through the service layer."""

    def test_calculate_msm_on_h4_demo_fixture(self) -> None:
        """MSM calculates cleanly on H4 demo fixture with start at 2026-10-01 00:00."""
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
        result = calculate_msm(df, ctx)
        assert result.is_valid is True
        assert result.error is None
        assert result.snapshot is not None
        assert result.start_candle_found is True
        assert result.candle_count == len(df)
        assert result.snapshot.trend_status is not None

    def test_calculate_msm_missing_start_candle_fails_closed(self) -> None:
        """When starting candle is not in history window, fails closed with clear diagnostic."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        # Time outside the fixture window
        outside_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=outside_time,
            direction=Direction.UPWARD,
            enabled=True,
        )
        result = calculate_msm(df, ctx)
        assert result.is_valid is False
        assert result.snapshot is None
        assert result.start_candle_found is False
        assert "not found in loaded chart data" in result.status_message

    def test_calculate_msm_rejects_forming_start_candle(self) -> None:
        """Starting candle marked as forming must be rejected."""
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        target_time = df.index[3]
        df.loc[target_time, "is_forming"] = True
        df.loc[target_time, "bar_status"] = "FORMING"

        ctx = MSMContext(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            start_candle_time=target_time,
            direction=Direction.UPWARD,
            enabled=True,
        )
        result = calculate_msm(df, ctx)
        assert result.is_valid is False
        assert "still forming" in result.error


class TestCompletedCandleDropdownFiltering:
    """Tests start candle selector option extraction."""

    def test_completed_candles_extracted_cleanly(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4")
        options = get_completed_candle_options(df)
        assert len(options) == len(df)
        assert "O:" in options[0]["label"]
        assert "C:" in options[0]["label"]

    def test_forming_candles_strictly_excluded(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4").copy()
        # Mark the last 2 candles as forming
        df.iloc[-1, df.columns.get_loc("is_forming")] = True
        df.iloc[-2, df.columns.get_loc("is_forming")] = True

        options = get_completed_candle_options(df)
        assert len(options) == len(df) - 2

    def test_empty_or_none_returns_empty_list(self) -> None:
        assert get_completed_candle_options(None) == []
        assert get_completed_candle_options(pd.DataFrame()) == []


class TestChartMSMOverlayRendering:
    """Tests Plotly figure construction with MSM traces and annotations."""

    def test_chart_renders_confirmed_highs_and_lows_and_path(self) -> None:
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
        msm_res = calculate_msm(df, ctx)

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            data_source="demo",
            is_demo=True,
            msm_result=msm_res,
        )

        trace_names = [t.name for t in fig.data if hasattr(t, "name")]
        assert "OHLC" in trace_names

        # If confirmed pairs exist, Confirmed High / Low / Market Structure should be in traces
        if msm_res.snapshot and msm_res.snapshot.confirmed_pairs:
            assert "Confirmed High" in trace_names
            assert "Confirmed Low" in trace_names
            assert "Market Structure" in trace_names

        # Title should contain MSM status
        assert "MSM:" in fig.layout.title.text

        # Annotations should include start candle annotation
        annot_texts = [a.text for a in fig.layout.annotations if hasattr(a, "text")]
        assert any("MSM Start (UPWARD)" in t for t in annot_texts)

    def test_chart_renders_tentative_level_when_present(self) -> None:
        """When snapshot has a tentative point, diamond marker and guideline are added."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        # Synthesize a mock result with a tentative point
        mock_snapshot = MagicMock()
        mock_snapshot.confirmed_pairs = ()
        mock_snapshot.trend_status = "Marking upward structure"
        mock_snapshot.state = EngineState.WAITING_FOR_BREAK

        tent_time = df.index[5]
        tent_pt = SwingPoint(
            price=1935.0,
            candle_index=5,
            candle_open_time=tent_time,
            identified_bar_index=5,
            identified_time=tent_time,
            confirmed_bar_index=None,
            confirmed_time=None,
        )
        mock_snapshot.tentative_point = tent_pt

        mock_res = MagicMock()
        mock_res.snapshot = mock_snapshot
        mock_res.error = None
        mock_res.context.start_candle_time = df.index[0]
        mock_res.context.direction = Direction.UPWARD

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            data_source="demo",
            is_demo=True,
            msm_result=mock_res,
        )

        trace_names = [t.name for t in fig.data if hasattr(t, "name")]
        assert "Tentative Level" in trace_names
        # Should have a guideline shape
        assert len(fig.layout.shapes) >= 1
        shape = fig.layout.shapes[0]
        assert shape.y0 == 1935.0
        assert shape.y1 == 1935.0

    def test_chart_with_msm_error_displays_diagnostic(self) -> None:
        """When msm_result has an error, title displays error without crashing."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        mock_res = MagicMock()
        mock_res.snapshot = None
        mock_res.error = "Selected starting candle fell outside history window."

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            data_source="demo",
            is_demo=True,
            msm_result=mock_res,
        )

        assert "MSM: Selected starting candle fell outside history window." in fig.layout.title.text


class TestMSMInspectionPanel:
    """Tests the MSM Inspection Table HTML rendering."""

    def test_render_inspection_table_with_confirmed_pairs(self) -> None:
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
        result = calculate_msm(df, ctx)
        assert result.snapshot is not None

        table_div = render_msm_inspection_table(result.snapshot, ctx)
        assert table_div is not None


class TestDashboardMSMWorkflow:
    """Tests full coordinator flow with MSM applied."""

    def test_generate_chart_with_compatible_msm_applied(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_time = df.index[0]
        msm_dict = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_time.isoformat(),
            "direction": "UPWARD",
            "enabled": True,
        }

        fig, status, loss_trigger = generate_chart_and_status_with_trigger(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            is_connected=False,
            msm_applied=msm_dict,
        )

        assert loss_trigger is None
        assert "MSM:" in status
        assert "MSM:" in fig.layout.title.text

    def test_context_mismatch_suppresses_msm_overlays(self) -> None:
        """If user switches timeframe to D1 while H4 MSM is applied, overlays are suppressed."""
        df = load_fixture(DEMO_SYMBOL, "H4")
        start_time = df.index[0]
        h4_msm_dict = {
            "data_source": "demo",
            "symbol": DEMO_SYMBOL,
            "timeframe": "H4",
            "start_candle_time": start_time.isoformat(),
            "direction": "UPWARD",
            "enabled": True,
        }

        # Request D1 chart with H4 MSM applied
        fig, status, _ = generate_chart_and_status_with_trigger(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="D1",
            candle_count=100,
            is_connected=False,
            msm_applied=h4_msm_dict,
        )

        # Overlays must NOT be rendered on D1
        assert "MSM:" not in status
        assert "MSM:" not in fig.layout.title.text
