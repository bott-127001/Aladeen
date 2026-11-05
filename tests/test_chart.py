"""Tests for chart construction."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from aladeen.ui.chart import create_candlestick_chart, create_empty_chart
from aladeen.data.fixtures import DEMO_SYMBOL, load_fixture


class TestCandlestickChart:
    """Verify chart creation from valid data."""

    def test_creates_figure_from_h4(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4")
        assert df is not None
        fig = create_candlestick_chart(df, DEMO_SYMBOL, "H4")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Candlestick)

    def test_demo_label_in_title(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4")
        assert df is not None
        fig = create_candlestick_chart(df, DEMO_SYMBOL, "H4", is_demo=True)
        assert "DEMO DATA" in fig.layout.title.text

    def test_no_demo_label_when_disabled(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4")
        assert df is not None
        fig = create_candlestick_chart(df, DEMO_SYMBOL, "H4", is_demo=False)
        assert "DEMO DATA" not in fig.layout.title.text

    def test_title_includes_symbol_and_timeframe(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "D1")
        assert df is not None
        fig = create_candlestick_chart(df, DEMO_SYMBOL, "D1")
        assert DEMO_SYMBOL in fig.layout.title.text
        assert "D1" in fig.layout.title.text

    def test_candlestick_data_count_matches(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "H4")
        assert df is not None
        fig = create_candlestick_chart(df, DEMO_SYMBOL, "H4")
        candle_trace = fig.data[0]
        assert len(candle_trace.open) == len(df)


class TestEmptyChart:
    """Verify empty-chart creation for error states."""

    def test_creates_figure(self) -> None:
        fig = create_empty_chart("No data available")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_message_in_annotation(self) -> None:
        msg = "Test message here"
        fig = create_empty_chart(msg)
        annotations = fig.layout.annotations
        assert len(annotations) == 1
        assert annotations[0].text == msg


class TestEdgeCases:
    """Verify chart handles edge-case data."""

    def test_single_candle(self) -> None:
        df = pd.DataFrame(
            [{"open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0}],
            index=pd.to_datetime(["2026-01-01"]),
        )
        fig = create_candlestick_chart(df, "TEST", "H4")
        assert isinstance(fig, go.Figure)
        assert len(fig.data[0].open) == 1

    def test_empty_dataframe(self) -> None:
        """An empty DataFrame should still produce a valid figure."""
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        df.index = pd.DatetimeIndex([], name="time")
        fig = create_candlestick_chart(df, "TEST", "H4")
        assert isinstance(fig, go.Figure)
