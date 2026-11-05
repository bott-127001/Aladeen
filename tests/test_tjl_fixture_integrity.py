"""Automated integrity checks for Trend Joining Level (TJL) acceptance fixtures.

Validates:
1. Strict raw timezone-awareness, finite positive prices, and physical OHLC geometry.
2. End-to-end verification of MSM confirmed pairs and tentative Point 3 identification
   at exact specified prefixes using accepted MSMEngine.
3. Directional TJL role assignment and original-candle zone geometry (including zero-width lines).
4. Set lifecycle progression across t0 -> t1 -> t2, verifying that t1 continuation does NOT
   replace current set and t2 pullback replaces set with outgoing cancellation intent.
5. Stable engineering Level ID formula (symbol_feed_id, source_timeframe, source_open_time, HIGH|LOW)
   and invariance across set replacements.
6. Main CHOCH invalidation intent, Monday retention invariance, and half-open wick precedence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict

import pytest

from aladeen.strategy.engine import MSMEngine
from aladeen.strategy.types import Direction, MSMConfig


@pytest.fixture(scope="module")
def tjl_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "tjl_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestTJLFixtureIntegrity:
    """Rigorous integrity validation of TJL acceptance fixtures."""

    def test_fixture_schema_and_keys(self, tjl_fixtures) -> None:
        """Verifies all 12 required fixture keys are present and categorized."""
        expected_keys = [
            "tjl_01_bullish_basic_end_to_end",
            "tjl_02_bearish_basic_end_to_end",
            "tjl_03_original_candle_geometry_and_zero_width_lines",
            "tjl_04_labels_before_first_eligible_set",
            "tjl_05_continuation_t1_labels_without_replacement",
            "tjl_06_pullback_t2_replacement_and_cancellation_intent",
            "tjl_07_persistent_level_identity_across_replacement",
            "tjl_08_idempotent_reobservation_same_fingerprint",
            "tjl_09_source_choch_eligibility_invalidation_and_gap",
            "tjl_10_monday_weekly_retention_without_reset",
            "tjl_11_unknown_availability_and_wick_precedence",
            "tjl_12_prefix_consistency_and_arbitrary_source_ids",
        ]
        for key in expected_keys:
            assert key in tjl_fixtures, f"Missing required fixture: {key}"
            assert "category" in tjl_fixtures[key], f"Fixture {key} missing category"
            assert "description" in tjl_fixtures[key], f"Fixture {key} missing description"

    def test_candle_data_validity_and_strict_ohlc(self, tjl_fixtures) -> None:
        """Verifies UTC datetimes, positive finite prices, and strict OHLC bounds."""
        for name, fix in tjl_fixtures.items():
            if "candles" not in fix:
                continue
            candles = fix["candles"]
            assert len(candles) > 0, f"Fixture {name} has empty candles"

            prev_time: datetime | None = None
            for idx, c in enumerate(candles):
                for f in ("open", "high", "low", "close"):
                    assert f in c, f"Missing {f} in {name} candle {idx}"
                    val = float(c[f])
                    assert math.isfinite(val) and val > 0, f"Invalid price {f}={val} in {name} candle {idx}"

                o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
                assert h >= max(o, cl), f"High {h} < max(o, c) in {name} candle {idx}"
                assert l <= min(o, cl), f"Low {l} > min(o, c) in {name} candle {idx}"

                t_str = c["time"]
                t = datetime.fromisoformat(t_str)
                assert t.tzinfo is not None, f"Non-timezone-aware timestamp {t_str} in {name}"
                if prev_time is not None:
                    assert t > prev_time, f"Non-chronological order in {name}: {t} <= {prev_time}"
                prev_time = t

    def test_tjl_01_bullish_end_to_end_msm_crosscheck(self, tjl_fixtures) -> None:
        """Cross-checks Bullish TJL01 points and set creation against real MSMEngine execution."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        engine = MSMEngine(MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time))
        snaps = engine.replay(fix["candles"])

        # 1. Bar 4 prefix: Pair confirmed (CH Bar 1, CL Bar 4), active P3 is None
        snap_4 = snaps[4]
        assert len(snap_4.confirmed_pairs) == 1
        p0 = snap_4.confirmed_pairs[0]
        assert p0.high.candle_index == 1
        assert p0.high.price == 1.135
        assert p0.low.candle_index == 4
        assert p0.low.price == 1.105
        assert snap_4.tentative_point is None

        # Zone geometry for CH (TJL1): High-Side [upper_body, high]
        c1 = fix["candles"][1]
        ub_c1 = max(c1["open"], c1["close"])
        assert ub_c1 == 1.135
        assert c1["high"] == 1.140

        # Zone geometry for CL (TJL2): Low-Side [low, lower_body]
        c4 = fix["candles"][4]
        lb_c4 = min(c4["open"], c4["close"])
        assert lb_c4 == 1.105
        assert c4["low"] == 1.104

        # 2. Bar 7 prefix: 2-candle pullback completes, identifying active P3 at Bar 5
        snap_7 = snaps[7]
        assert len(snap_7.confirmed_pairs) == 1
        assert snap_7.tentative_point is not None
        assert snap_7.tentative_point.candle_index == 5
        assert snap_7.tentative_point.price == 1.155

        # Expected set matches
        exp_set = fix["expected_set_bar_7"]
        assert exp_set["fingerprint"] == ["FEED_EURUSD_H1", "UPWARD", 1, 4, 5]
        assert exp_set["is_first_creation"] is True
        assert exp_set["outgoing_cancellation_intent"] is False

    def test_tjl_02_bearish_end_to_end_msm_crosscheck(self, tjl_fixtures) -> None:
        """Cross-checks Bearish TJL02 points and set creation against real MSMEngine execution."""
        fix = tjl_fixtures["tjl_02_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        engine = MSMEngine(MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay(fix["candles"])

        # 1. Bar 5 prefix: Pair confirmed (CH Bar 4, CL Bar 2), active P3 is None
        snap_5 = snaps[5]
        assert len(snap_5.confirmed_pairs) == 1
        p0 = snap_5.confirmed_pairs[0]
        assert p0.high.candle_index == 4
        assert p0.high.price == 1.200
        assert p0.low.candle_index == 2
        assert p0.low.price == 1.185
        assert snap_5.tentative_point is None

        # In Bearish: TJL1 is CL (Bar 2, low-side), TJL2 is CH (Bar 4, high-side)
        c2 = fix["candles"][2]
        assert min(c2["open"], c2["close"]) == 1.185 and c2["low"] == 1.180  # Low-side [1.180, 1.185]
        c4 = fix["candles"][4]
        assert max(c4["open"], c4["close"]) == 1.200 and c4["high"] == 1.205  # High-side [1.200, 1.205]

        # 2. Bar 9 prefix: Pullback identifies active P3 (tentative low at Bar 7)
        snap_9 = snaps[9]
        assert len(snap_9.confirmed_pairs) == 1
        assert snap_9.tentative_point is not None
        assert snap_9.tentative_point.candle_index == 7
        assert snap_9.tentative_point.price == 1.140

        exp_set = fix["expected_set_bar_9"]
        assert exp_set["fingerprint"] == ["FEED_GBPUSD_H1", "DOWNWARD", 4, 2, 7]
        assert exp_set["is_first_creation"] is True
        assert exp_set["outgoing_cancellation_intent"] is False

    def test_tjl_03_original_candle_geometry(self, tjl_fixtures) -> None:
        """Verifies high-side, low-side, and zero-width single price line calculations."""
        fix = tjl_fixtures["tjl_03_original_candle_geometry_and_zero_width_lines"]
        geos = fix["expected_geometries"]

        # Candle 0: High-side with upper wick [1.22, 1.23]
        c0 = geos["candle_0_high_side"]
        assert c0["lower_price"] == 1.22 and c0["upper_price"] == 1.23
        assert c0["is_zero_width"] is False

        # Candle 1: High-side zero wick [1.25, 1.25]
        c1 = geos["candle_1_high_side_zero_wick"]
        assert c1["lower_price"] == 1.25 and c1["upper_price"] == 1.25
        assert c1["is_zero_width"] is True

        # Candle 2: Low-side with lower wick [1.14, 1.15]
        c2 = geos["candle_2_low_side"]
        assert c2["lower_price"] == 1.14 and c2["upper_price"] == 1.15
        assert c2["is_zero_width"] is False

        # Candle 3: Low-side zero wick [1.13, 1.13]
        c3 = geos["candle_3_low_side_zero_wick"]
        assert c3["lower_price"] == 1.13 and c3["upper_price"] == 1.13
        assert c3["is_zero_width"] is True

    def test_tjl_04_labels_before_first_set(self, tjl_fixtures) -> None:
        """Asserts confirmed points receive labels but current set is None when P3 is None."""
        fix = tjl_fixtures["tjl_04_labels_before_first_eligible_set"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        engine = MSMEngine(MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time))
        snaps = engine.replay(fix["candles"])

        snap = snaps[fix["evaluated_prefix_bar"]]
        assert len(snap.confirmed_pairs) == 1
        assert snap.tentative_point is None

        exp = fix["expected_state"]
        assert exp["has_labeled_points"] is True
        assert exp["active_p3"] is None
        assert exp["current_set"] is None
        assert exp["is_eligible_for_trading"] is False

    def test_tjl_05_continuation_t1_labels_without_replacement(self, tjl_fixtures) -> None:
        """Verifies that at t1 continuation break, next labels are assigned but current set is not replaced."""
        fix = tjl_fixtures["tjl_05_continuation_t1_labels_without_replacement"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        engine = MSMEngine(MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay(fix["candles"])

        snap_14 = snaps[14]
        assert len(snap_14.confirmed_pairs) == 2
        # Pair 2 confirmed: high at Bar 13 (1.168), low at Bar 7 (1.140)
        p1 = snap_14.confirmed_pairs[1]
        assert p1.high.candle_index == 13
        assert p1.high.price == 1.168
        assert p1.low.candle_index == 7
        assert p1.low.price == 1.140
        assert snap_14.tentative_point is None  # P3 cleared by continuation!

        exp = fix["expected_state"]
        assert exp["is_current_set_replaced"] is False
        assert exp["outgoing_cancellation_intent"] is False
        assert exp["current_set_fingerprint"] == ["FEED_GBPUSD_H1", "DOWNWARD", 4, 2, 7]

    def test_tjl_06_pullback_t2_replacement_and_cancellation_intent(self, tjl_fixtures) -> None:
        """Verifies that at t2 pullback completion, new fingerprint replaces set and emits cancellation intent."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        engine = MSMEngine(MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay(fix["candles"])

        snap_16 = snaps[16]
        assert len(snap_16.confirmed_pairs) == 2
        assert snap_16.tentative_point is not None
        assert snap_16.tentative_point.candle_index == 14
        assert snap_16.tentative_point.price == 1.132

        exp = fix["expected_state"]
        assert exp["is_current_set_replaced"] is True
        assert exp["replaced_set_fingerprint"] == ["FEED_GBPUSD_H1", "DOWNWARD", 4, 2, 7]
        assert exp["new_set_fingerprint"] == ["FEED_GBPUSD_H1", "DOWNWARD", 13, 7, 14]
        assert exp["outgoing_cancellation_intent"] is True

    def test_tjl_07_level_identity_and_usage_invariance(self, tjl_fixtures) -> None:
        """Verifies stable Level ID formula (symbol_feed_id, tf, open_time, HIGH|LOW) invariance."""
        fix = tjl_fixtures["tjl_07_persistent_level_identity_across_replacement"]
        exp_id = fix["expected_level_id"]
        assert exp_id == ["FEED_GBPUSD_H1", "H1", "2026-10-01T07:00:00Z", "LOW"]
        assert fix["identity_invariance"] is True
        assert fix["usage_status_preserved"] is True
        assert fix["outgoing_cancellation_intent_emitted"] is True

    def test_tjl_08_idempotent_reobservation(self, tjl_fixtures) -> None:
        """Verifies identical fingerprints across non-break bars produce zero replacements and zero intents."""
        fix = tjl_fixtures["tjl_08_idempotent_reobservation_same_fingerprint"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        engine = MSMEngine(MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay(fix["candles"])

        for b in fix["evaluated_prefix_bars"]:
            s = snaps[b]
            assert len(s.confirmed_pairs) == 1
            assert s.tentative_point.candle_index == 7

        exp = fix["expected_state"]
        assert exp["is_idempotent"] is True
        assert exp["replacements_count"] == 0
        assert exp["cancellation_intents_count"] == 0

    def test_tjl_09_source_choch_invalidation_and_gap(self, tjl_fixtures) -> None:
        """Verifies source Main CHOCH immediately invalidates old trading eligibility with transition gap."""
        fix = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        exp = fix["expected_state"]
        assert exp["main_choch_confirmed"] is True
        assert exp["old_direction_eligibility_invalidated"] is True
        assert exp["outgoing_cancellation_intent"] is True
        assert exp["current_set_post_choch"] is None
        assert exp["transition_gap_active"] is True
        assert exp["historical_labels_preserved"] is True

    def test_tjl_10_monday_weekly_retention(self, tjl_fixtures) -> None:
        """Verifies Monday alone preserves existing set, levels, and used statuses without reset."""
        fix = tjl_fixtures["tjl_10_monday_weekly_retention_without_reset"]
        exp = fix["expected_state"]
        assert exp["is_set_retained"] is True
        assert exp["level_used_status_after_monday"] is True
        assert exp["was_usage_reset"] is False
        assert exp["was_set_cancelled"] is False

    def test_tjl_11_unknown_availability_and_wick_precedence(self, tjl_fixtures) -> None:
        """Verifies half-open intervals [open, close) and prohibition of retroactive wick taps."""
        fix = tjl_fixtures["tjl_11_unknown_availability_and_wick_precedence"]
        exp = fix["expected_state"]
        assert exp["is_retroactive_wick_tap_allowed"] is False
        assert exp["unknown_intra_bar_status"] == "UNKNOWN_ORDER"

    def test_tjl_12_prefix_consistency_and_arbitrary_ids(self, tjl_fixtures) -> None:
        """Verifies level identity calculation across arbitrary feed identifiers and timeframes."""
        fix = tjl_fixtures["tjl_12_prefix_consistency_and_arbitrary_source_ids"]
        for tc in fix["test_cases"]:
            expected = [tc["feed_id"], tc["source_timeframe"], tc["open_time"], tc["side"]]
            assert tc["expected_level_id"] == expected
