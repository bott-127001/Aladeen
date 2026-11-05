"""Unit tests for Trend Joining Level (TJL) immutable domain types."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from aladeen.strategy.types import Direction, StrategyCandle
from aladeen.strategy.tjl_types import (
    CurrentEligibleSet,
    PhysicalLevel,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLSnapshot,
    TJLStructuralObservation,
    TJLTransitionRecord,
    TJLTransitionType,
    TJLZone,
)


class TestTJLTypes:
    """Rigorous unit testing for TJL domain types and value objects."""

    def test_stable_level_id_valid_and_normalized(self) -> None:
        """StableLevelId normalizes time to UTC, supports equality with sequences and tuples."""
        t_naive = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", t_naive, TJLSide.HIGH)

        assert lvl.symbol_feed_id == "FEED_EURUSD_H1"
        assert lvl.source_timeframe == "H1"
        assert lvl.side == TJLSide.HIGH
        assert lvl.to_tuple() == ("FEED_EURUSD_H1", "H1", "2026-10-01T04:00:00+00:00", "HIGH")
        assert lvl.to_list() == ["FEED_EURUSD_H1", "H1", "2026-10-01T04:00:00+00:00", "HIGH"]

        # Comparison with 4-element sequence
        assert lvl == ["FEED_EURUSD_H1", "H1", "2026-10-01T04:00:00+00:00", "HIGH"]
        assert lvl == ("FEED_EURUSD_H1", "H1", "2026-10-01T04:00:00Z", "HIGH")

    def test_stable_level_id_rejections(self) -> None:
        """StableLevelId rejects empty feed IDs, invalid sides, and naive datetimes."""
        with pytest.raises(ValueError, match="symbol_feed_id must be a non-empty string"):
            StableLevelId("", "H1", datetime.now(timezone.utc), TJLSide.HIGH)

        with pytest.raises(ValueError, match="source_timeframe must be a non-empty string"):
            StableLevelId("FEED_1", "  ", datetime.now(timezone.utc), TJLSide.HIGH)

        with pytest.raises(ValueError, match="must be timezone-aware"):
            StableLevelId("FEED_1", "H1", datetime(2026, 1, 1), TJLSide.HIGH)

        with pytest.raises(ValueError, match="Invalid side 'MID'"):
            StableLevelId("FEED_1", "H1", datetime.now(timezone.utc), "MID")

    def test_tjl_zone_from_candle_high_side_and_low_side(self) -> None:
        """TJLZone correctly computes [UB, High] for high-side and [Low, LB] for low-side."""
        t0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        c_green = StrategyCandle(
            index=1,
            open_time=t0,
            open=1.1300,
            high=1.1400,
            low=1.1290,
            close=1.1350,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
        )

        # High-side zone: lower_price = UB (1.1350), upper_price = High (1.1400)
        z_high = TJLZone.from_candle(
            candle=c_green,
            label=TJLLabel.TJL1,
            is_high_side=True,
            feed_id="FEED_EURUSD_H1",
            timeframe="H1",
            confirmed_candle_index=4,
        )
        assert z_high.label == TJLLabel.TJL1
        assert z_high.lower_price == 1.1350
        assert z_high.upper_price == 1.1400
        assert z_high.is_line is False
        assert z_high.level_id.side == TJLSide.HIGH

        # Low-side zone: lower_price = Low (1.1290), upper_price = LB (1.1300)
        z_low = TJLZone.from_candle(
            candle=c_green,
            label=TJLLabel.TJL2_A_PLUS,
            is_high_side=False,
            feed_id="FEED_EURUSD_H1",
            timeframe="H1",
            confirmed_candle_index=4,
        )
        assert z_low.label == TJLLabel.TJL2_A_PLUS
        assert z_low.lower_price == 1.1290
        assert z_low.upper_price == 1.1300
        assert z_low.is_line is False
        assert z_low.level_id.side == TJLSide.LOW

    def test_exact_zero_width_vs_tiny_nonzero_wick(self) -> None:
        """Exact zero-width wick marks is_line=True; tiny representable nonzero wick marks is_line=False."""
        t0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        # 1. Genuine zero-width candle (close == high)
        c_marubozu = StrategyCandle(
            index=2,
            open_time=t0,
            open=1.1300,
            high=1.1350,
            low=1.1290,
            close=1.1350,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
        )
        z_zero = TJLZone.from_candle(
            candle=c_marubozu,
            label=TJLLabel.TJL1,
            is_high_side=True,
            feed_id="FEED_EURUSD_H1",
            timeframe="H1",
            confirmed_candle_index=4,
        )
        assert z_zero.lower_price == 1.1350
        assert z_zero.upper_price == 1.1350
        assert z_zero.is_line is True

        # 2. Candle with a tiny nonzero wick (diff = 0.00001)
        c_tiny_wick = StrategyCandle(
            index=3,
            open_time=t0,
            open=1.1300,
            high=1.13501,  # 0.00001 above close!
            low=1.1290,
            close=1.13500,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
        )
        z_nonzero = TJLZone.from_candle(
            candle=c_tiny_wick,
            label=TJLLabel.TJL1,
            is_high_side=True,
            feed_id="FEED_EURUSD_H1",
            timeframe="H1",
            confirmed_candle_index=4,
        )
        assert z_nonzero.lower_price == 1.13500
        assert z_nonzero.upper_price == 1.13501
        assert z_nonzero.is_line is False  # Must NOT be classified as line!

    def test_tjl_fingerprint_equality_and_hashing(self) -> None:
        """TJLFingerprint supports comparisons with tuples and lists and maintains stable hashing."""
        fp = TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 1, 4, 5)
        assert fp == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)
        assert fp == ["ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5]
        assert fp.to_tuple() == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)
        assert hash(fp) == hash(("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5))

    def test_structural_observation_immutable_lookup(self) -> None:
        """TJLStructuralObservation protects source_candle_lookup against external mutation."""
        t0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        c1 = StrategyCandle(
            index=1,
            open_time=t0,
            open=1.130,
            high=1.140,
            low=1.129,
            close=1.135,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
        )
        lookup = {1: c1}
        obs = TJLStructuralObservation(
            source_engine_id="ENGINE_1",
            symbol_feed_id="FEED_1",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=1,
            candle_open_time=t0,
            availability_time=None,  # Unknown close time!
            source_candle_lookup=lookup,
        )
        assert obs.availability_time is None
        # Attempting to mutate mappingproxy raises TypeError
        with pytest.raises(TypeError):
            obs.source_candle_lookup[2] = c1  # type: ignore[index]
