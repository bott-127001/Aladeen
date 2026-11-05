"""Tests for deterministic OHLC fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from aladeen.data.fixtures import (
    DEMO_SYMBOL,
    SUPPORTED_TIMEFRAMES,
    available_symbols,
    available_timeframes,
    load_fixture,
)


class TestFixtureLoading:
    """Verify fixture data returns and determinism."""

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_load_supported_timeframe(self, tf: str) -> None:
        """Supported timeframes return a non-empty DataFrame."""
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_load_unsupported_timeframe_returns_none(self) -> None:
        df = load_fixture(DEMO_SYMBOL, "M1")
        assert df is None

    def test_load_unknown_symbol_returns_none(self) -> None:
        df = load_fixture("UNKNOWN", "H4")
        assert df is None

    def test_deterministic_reload(self) -> None:
        """Two consecutive loads return identical data."""
        df1 = load_fixture(DEMO_SYMBOL, "H4")
        df2 = load_fixture(DEMO_SYMBOL, "H4")
        assert df1 is not None and df2 is not None
        pd.testing.assert_frame_equal(df1, df2)

    def test_available_symbols_includes_demo(self) -> None:
        assert DEMO_SYMBOL in available_symbols()

    def test_available_timeframes_includes_all_ui_options(self) -> None:
        tfs = available_timeframes()
        for expected in ["D1", "H4", "H1", "M5", "M1"]:
            assert expected in tfs


class TestOHLCValidity:
    """Verify OHLC data integrity for every supported fixture."""

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_required_columns(self, tf: str) -> None:
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        for col in ("open", "high", "low", "close"):
            assert col in df.columns

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_high_ge_low(self, tf: str) -> None:
        """High must be >= low for every candle."""
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        assert (df["high"] >= df["low"]).all()

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_high_ge_open_close(self, tf: str) -> None:
        """High must be >= both open and close."""
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        assert (df["high"] >= df["open"]).all()
        assert (df["high"] >= df["close"]).all()

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_low_le_open_close(self, tf: str) -> None:
        """Low must be <= both open and close."""
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        assert (df["low"] <= df["open"]).all()
        assert (df["low"] <= df["close"]).all()

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_chronological_ordering(self, tf: str) -> None:
        """Candles must be in strictly ascending time order."""
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        times = df.index.to_series()
        assert times.is_monotonic_increasing
        assert times.is_unique

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_no_nan_values(self, tf: str) -> None:
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        assert not df.isnull().any().any()

    @pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
    def test_positive_prices(self, tf: str) -> None:
        df = load_fixture(DEMO_SYMBOL, tf)
        assert df is not None
        assert (df[["open", "high", "low", "close"]] > 0).all().all()
