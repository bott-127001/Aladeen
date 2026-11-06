"""Unit tests for Trend Joining Level (TJL) immutable domain types."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
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

    def test_current_eligible_set_invariants_and_rejections(self) -> None:
        """CurrentEligibleSet strictly validates cross-field consistency on direct construction."""
        t0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        c1 = StrategyCandle(index=1, open_time=t0, open=1.130, high=1.140, low=1.129, close=1.135, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c4 = StrategyCandle(index=4, open_time=t0, open=1.110, high=1.115, low=1.104, close=1.105, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        z1 = TJLZone.from_candle(c1, TJLLabel.TJL1, is_high_side=True, feed_id="FEED_1", timeframe="H1", confirmed_candle_index=4)
        z2 = TJLZone.from_candle(c4, TJLLabel.TJL2_A_PLUS, is_high_side=False, feed_id="FEED_1", timeframe="H1", confirmed_candle_index=4)
        fp_valid = TJLFingerprint("ENGINE_1", Direction.UPWARD, 1, 4, 5)

        # 1. Valid construction succeeds
        valid_set = CurrentEligibleSet(
            set_id="SET_1",
            fingerprint=fp_valid,
            direction=Direction.UPWARD,
            source_engine_id="ENGINE_1",
            symbol_feed_id="FEED_1",
            source_timeframe="H1",
            tjl1_zone=z1,
            tjl2_zone=z2,
            p3_source_index=5,
            p3_open_time=t0,
            p3_price=1.155,
            eligibility_available_time=t0,
            created_at_candle_index=7,
        )
        assert valid_set.set_id == "SET_1"

        # 2. Mismatched direction raises ValueError
        with pytest.raises(ValueError, match="differs from set direction"):
            CurrentEligibleSet(
                set_id="SET_1",
                fingerprint=TJLFingerprint("ENGINE_1", Direction.DOWNWARD, 1, 4, 5),
                direction=Direction.UPWARD,
                source_engine_id="ENGINE_1",
                symbol_feed_id="FEED_1",
                source_timeframe="H1",
                tjl1_zone=z1,
                tjl2_zone=z2,
                p3_source_index=5,
                p3_open_time=t0,
                p3_price=1.155,
                eligibility_available_time=t0,
                created_at_candle_index=7,
            )

        # 3. Mismatched zone roles raise ValueError
        with pytest.raises(ValueError, match="tjl1_zone must have label=TJL1"):
            CurrentEligibleSet(
                set_id="SET_1",
                fingerprint=fp_valid,
                direction=Direction.UPWARD,
                source_engine_id="ENGINE_1",
                symbol_feed_id="FEED_1",
                source_timeframe="H1",
                tjl1_zone=z2,  # Wrong zone!
                tjl2_zone=z1,
                p3_source_index=5,
                p3_open_time=t0,
                p3_price=1.155,
                eligibility_available_time=t0,
                created_at_candle_index=7,
            )

    def test_transition_record_cancellation_invariants(self) -> None:
        """TJLTransitionRecord requires outgoing cancelled set ID and fingerprint if and only if cancellation intent is True."""
        fp = TJLFingerprint("ENGINE_1", Direction.UPWARD, 1, 4, 5)
        # Cancellation intent True without outgoing set raises ValueError
        with pytest.raises(ValueError, match="requires explicit outgoing_cancelled_set_id"):
            TJLTransitionRecord(
                transition_type=TJLTransitionType.SET_REPLACEMENT,
                outgoing_cancellation_intent=True,
                current_set=None,
                newly_labeled_zones=(),
                transition_candle_index=7,
                transition_time=None,
                outgoing_cancelled_set_id=None,
                outgoing_cancelled_fingerprint=None,
            )

        # Cancellation intent False with outgoing set raises ValueError
        with pytest.raises(ValueError, match="cannot have outgoing_cancelled_set_id"):
            TJLTransitionRecord(
                transition_type=TJLTransitionType.FIRST_CREATION,
                outgoing_cancellation_intent=False,
                current_set=None,
                newly_labeled_zones=(),
                transition_candle_index=7,
                transition_time=None,
                outgoing_cancelled_set_id="SET_1",
                outgoing_cancelled_fingerprint=fp,
            )

    def test_observation_point_validation_and_exact_prices(self) -> None:
        """[Directive 2] TJLStructuralObservation strictly validates point kind, status, lookup keys, exact prices, and horizons."""
        from aladeen.strategy.types import SwingPoint
        t0 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
        c1 = StrategyCandle(index=1, open_time=t0, open=1.130, high=1.140, low=1.129, close=1.135, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c4 = StrategyCandle(index=4, open_time=t0, open=1.110, high=1.115, low=1.104, close=1.105, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c5 = StrategyCandle(index=5, open_time=t0, open=1.140, high=1.155, low=1.139, close=1.155, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        # 1. Exact price rejection (even 1e-9 off is strictly rejected)
        ch_bad_price = SwingPoint(price=1.135 + 1e-8, candle_index=1, candle_open_time=t0, identified_bar_index=1, confirmed_bar_index=4)
        with pytest.raises(ValueError, match="does not exactly match source candle upper body edge"):
            TJLStructuralObservation(
                source_engine_id="E", symbol_feed_id="F", source_timeframe="H1", direction=Direction.UPWARD,
                candle_index=7, candle_open_time=t0, ch_point=ch_bad_price,
                source_candle_lookup={1: c1},
            )

        # 2. Unconfirmed ch_point rejected
        ch_unconfirmed = SwingPoint(price=1.135, candle_index=1, candle_open_time=t0, identified_bar_index=1, confirmed_bar_index=None)
        with pytest.raises(ValueError, match="ch_point in observation must be confirmed"):
            TJLStructuralObservation(
                source_engine_id="E", symbol_feed_id="F", source_timeframe="H1", direction=Direction.UPWARD,
                candle_index=7, candle_open_time=t0, ch_point=ch_unconfirmed,
                source_candle_lookup={1: c1},
            )

        # 3. Already confirmed tentative_p3 rejected
        p3_confirmed = SwingPoint(price=1.155, candle_index=5, candle_open_time=t0, identified_bar_index=5, confirmed_bar_index=7)
        with pytest.raises(ValueError, match="tentative_p3 in observation cannot be already confirmed"):
            TJLStructuralObservation(
                source_engine_id="E", symbol_feed_id="F", source_timeframe="H1", direction=Direction.UPWARD,
                candle_index=7, candle_open_time=t0, tentative_p3=p3_confirmed,
                source_candle_lookup={5: c5},
            )

        # 4. Inverted CH/CL price hierarchy rejected
        ch_valid = SwingPoint(price=1.135, candle_index=1, candle_open_time=t0, identified_bar_index=1, confirmed_bar_index=4)
        cl_inverted = SwingPoint(price=1.135, candle_index=4, candle_open_time=t0, identified_bar_index=4, confirmed_bar_index=4)
        c4_inv = StrategyCandle(index=4, open_time=t0, open=1.135, high=1.140, low=1.130, close=1.135, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        with pytest.raises(ValueError, match="ch_point price .* must be strictly greater than cl_point price"):
            TJLStructuralObservation(
                source_engine_id="E", symbol_feed_id="F", source_timeframe="H1", direction=Direction.UPWARD,
                candle_index=7, candle_open_time=t0, ch_point=ch_valid, cl_point=cl_inverted,
                source_candle_lookup={1: c1, 4: c4_inv},
            )

        # 5. Future provenance rejected relative to observation horizon
        ch_future = SwingPoint(price=1.135, candle_index=1, candle_open_time=t0, identified_bar_index=1, confirmed_bar_index=4, confirmed_time=t0 + timedelta(hours=10))
        with pytest.raises(ValueError, match="lies in future relative to observation horizon"):
            TJLStructuralObservation(
                source_engine_id="E", symbol_feed_id="F", source_timeframe="H1", direction=Direction.UPWARD,
                candle_index=7, candle_open_time=t0, availability_time=t0 + timedelta(hours=8),
                ch_point=ch_future, source_candle_lookup={1: c1},
            )

        # 6. Negative structural epoch rejected
        with pytest.raises(ValueError, match="structural_epoch must be non-negative"):
            TJLStructuralObservation(
                source_engine_id="E", symbol_feed_id="F", source_timeframe="H1", direction=Direction.UPWARD,
                candle_index=7, candle_open_time=t0, structural_epoch=-1,
            )

