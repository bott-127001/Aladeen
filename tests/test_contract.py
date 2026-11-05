"""Tests for the Shared Candle Data Contract."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aladeen.data.contract import (
    CandleValidationError,
    validate_candle_data,
)


def _make_valid_df(n: int = 10, *, forming_last: bool = True) -> pd.DataFrame:
    """Helper to generate a valid DataFrame complying with the contract."""
    times = pd.date_range("2026-10-01", periods=n, freq="4h", tz="UTC")
    data = {
        "open": [100.0 + i for i in range(n)],
        "high": [105.0 + i for i in range(n)],
        "low": [98.0 + i for i in range(n)],
        "close": [102.0 + i for i in range(n)],
        "is_forming": [False] * (n - 1) + [forming_last] if n > 0 else [],
    }
    return pd.DataFrame(data, index=times)


class TestCandleDataContract:
    """Verify validation rules of the candle data contract."""

    def test_valid_dataframe_passes(self) -> None:
        df = _make_valid_df(10)
        validated = validate_candle_data(df)
        assert validated is not None
        assert len(validated) == 10

    def test_none_or_empty_rejected(self) -> None:
        with pytest.raises(CandleValidationError, match="cannot be None"):
            validate_candle_data(None)  # type: ignore

        empty_df = pd.DataFrame()
        with pytest.raises(CandleValidationError, match="DataFrame is empty"):
            validate_candle_data(empty_df)

    def test_non_dataframe_rejected(self) -> None:
        with pytest.raises(CandleValidationError, match="Expected pandas DataFrame"):
            validate_candle_data([1, 2, 3])  # type: ignore

    def test_non_datetime_index_rejected(self) -> None:
        df = _make_valid_df(5).reset_index(drop=True)
        with pytest.raises(CandleValidationError, match="must be a DatetimeIndex"):
            validate_candle_data(df)

    def test_timezone_naive_rejected(self) -> None:
        df = _make_valid_df(5)
        df.index = df.index.tz_localize(None)
        with pytest.raises(CandleValidationError, match="must be timezone-aware"):
            validate_candle_data(df)

    def test_non_utc_timezone_normalized_to_utc(self) -> None:
        """Timezone-aware timestamps in non-UTC timezones are normalized to UTC."""
        df = _make_valid_df(5)
        df.index = df.index.tz_convert("US/Eastern")
        validated = validate_candle_data(df)
        assert str(validated.index.tz) == "UTC"
        assert len(validated) == 5

    def test_nat_timestamp_rejected(self) -> None:
        """NaT (Not-a-Time) timestamps in index must be rejected with CandleValidationError."""
        df = _make_valid_df(5)
        times = list(df.index)
        times[1] = pd.NaT
        df.index = pd.DatetimeIndex(times)
        with pytest.raises(CandleValidationError, match="NaT \\(Not-a-Time\\)"):
            validate_candle_data(df)

    def test_non_chronological_rejected(self) -> None:
        df = _make_valid_df(5)
        df = df.iloc[::-1]
        with pytest.raises(CandleValidationError, match="strictly ascending chronological order"):
            validate_candle_data(df)

    def test_duplicate_timestamps_rejected(self) -> None:
        df = _make_valid_df(5)
        times = list(df.index)
        times[1] = times[0]  # Duplicate
        df.index = pd.DatetimeIndex(times)
        with pytest.raises(CandleValidationError, match="Duplicate candle timestamps"):
            validate_candle_data(df)

    def test_missing_required_column_rejected(self) -> None:
        for col in ("open", "high", "low", "close"):
            df = _make_valid_df(5).drop(columns=[col])
            with pytest.raises(CandleValidationError, match=f"Missing required OHLC column: '{col}'"):
                validate_candle_data(df)

    def test_string_in_ohlc_rejected_with_candle_validation_error(self) -> None:
        """Strings in OHLC columns must raise CandleValidationError, not raw TypeError."""
        df = _make_valid_df(5)
        df["open"] = ["100.0", "101.0", "102.0", "103.0", "104.0"]
        with pytest.raises(CandleValidationError, match="must be numeric"):
            validate_candle_data(df)

    def test_boolean_in_ohlc_rejected(self) -> None:
        """Booleans in OHLC columns must raise CandleValidationError."""
        df = _make_valid_df(5)
        df["close"] = True
        with pytest.raises(CandleValidationError, match="must be numeric"):
            validate_candle_data(df)

    def test_positive_and_negative_infinity_rejected(self) -> None:
        """Infinite (+/- inf) values must raise CandleValidationError."""
        df1 = _make_valid_df(5)
        df1.loc[df1.index[2], "high"] = float("inf")
        with pytest.raises(CandleValidationError, match="infinite values"):
            validate_candle_data(df1)

        df2 = _make_valid_df(5)
        df2.loc[df2.index[2], "low"] = float("-inf")
        with pytest.raises(CandleValidationError, match="infinite values"):
            validate_candle_data(df2)

    def test_null_or_nan_rejected(self) -> None:
        for col in ("open", "high", "low", "close"):
            df = _make_valid_df(5)
            df.loc[df.index[2], col] = np.nan
            with pytest.raises(CandleValidationError, match="contains 1 null/NaN values"):
                validate_candle_data(df)

    def test_non_positive_price_rejected(self) -> None:
        df = _make_valid_df(5)
        df.loc[df.index[1], "low"] = 0.0
        with pytest.raises(CandleValidationError, match="contains non-positive values"):
            validate_candle_data(df)

    def test_high_less_than_low_rejected(self) -> None:
        df = _make_valid_df(5)
        df.loc[df.index[1], "high"] = 90.0  # low is 99.0
        with pytest.raises(CandleValidationError, match="High price < Low price"):
            validate_candle_data(df)

    def test_high_less_than_open_close_rejected(self) -> None:
        df1 = _make_valid_df(5)
        df1.loc[df1.index[0], "high"] = 99.0  # open is 100.0
        with pytest.raises(CandleValidationError, match="High price < Open price"):
            validate_candle_data(df1)

        df2 = _make_valid_df(5)
        df2.loc[df2.index[0], "high"] = 101.0  # close is 102.0
        with pytest.raises(CandleValidationError, match="High price < Close price"):
            validate_candle_data(df2)

    def test_low_greater_than_open_close_rejected(self) -> None:
        df1 = _make_valid_df(5)
        df1.loc[df1.index[0], "low"] = 101.0  # open is 100.0
        with pytest.raises(CandleValidationError, match="Low price > Open price"):
            validate_candle_data(df1)

        df2 = _make_valid_df(5)
        df2.loc[df2.index[0], "open"] = 105.0
        df2.loc[df2.index[0], "high"] = 106.0
        df2.loc[df2.index[0], "close"] = 102.0
        df2.loc[df2.index[0], "low"] = 103.0
        with pytest.raises(CandleValidationError, match="Low price > Close price"):
            validate_candle_data(df2)

    def test_missing_forming_flag_rejected(self) -> None:
        df = _make_valid_df(5).drop(columns=["is_forming"])
        with pytest.raises(CandleValidationError, match="Missing 'is_forming'"):
            validate_candle_data(df)

    def test_historical_forming_candle_rejected(self) -> None:
        df = _make_valid_df(5)
        df.loc[df.index[1], "is_forming"] = True  # Historical candle marked forming
        with pytest.raises(CandleValidationError, match="Historical candles prior to the latest candle cannot have is_forming=True"):
            validate_candle_data(df)

    def test_stale_and_market_closed_snapshot_valid(self) -> None:
        """A snapshot from a closed market (e.g. weekend bar 48 hours ago) is valid without clock bias."""
        times = pd.date_range("2026-10-02 12:00", periods=5, freq="4h", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [1.100, 1.102, 1.101, 1.105, 1.104],
                "high": [1.105, 1.106, 1.107, 1.109, 1.108],
                "low": [1.098, 1.100, 1.099, 1.103, 1.102],
                "close": [1.103, 1.101, 1.106, 1.104, 1.107],
                "is_forming": [False, False, False, False, True],
            },
            index=times,
        )
        validated = validate_candle_data(df)
        assert len(validated) == 5
        assert bool(validated["is_forming"].iloc[-1]) is True
