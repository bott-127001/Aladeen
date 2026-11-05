"""Automated integrity checks for Internal Structure Shift (ISS) acceptance fixtures.

Validates:
1. Strict raw timezone-awareness, finite positive prices, and physical OHLC geometry.
2. End-to-end verification of Main Level 2 (completed pair confirmation provenance)
   and Main Level 3 (tentative extreme identification) using the accepted MSMEngine.
3. Verification of all five internal swing points using MSMEngine with the mandatory
   forward-scan restriction (strictly after main pullback candle 2).
4. Exact zone provenance from internal points 3 and 4 and exact geometric bounds.
5. Specification-consistency assertions for boundary equality, wick excursions,
   out-of-bounds rejection, outside-range completion tracking-only, and cancellations.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import pytest

from aladeen.strategy.engine import MSMEngine
from aladeen.strategy.types import Direction, MSMConfig


@pytest.fixture(scope="module")
def iss_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "iss_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestISSFixtureIntegrity:
    """Rigorous integrity validation of ISS acceptance fixtures."""

    def test_fixture_schema_and_keys(self, iss_fixtures) -> None:
        """Verifies all 15 required fixture keys are present and categorized."""
        expected_keys = [
            "iss_01_bearish_basic_end_to_end",
            "iss_02_bullish_basic_end_to_end",
            "iss_03_boundary_equality",
            "iss_04_wick_excursion_allowed",
            "iss_05_out_of_bounds_marked_point_rejection",
            "iss_06_outside_range_completion_tracking_only",
            "iss_07_no_revival_under_same_main_level_3",
            "iss_08_fresh_search_on_new_main_level_3",
            "iss_09_main_continuation_cancellation",
            "iss_10_main_choch_cancellation",
            "iss_11_retained_history_preservation",
            "iss_12_zone_provenance_and_geometry",
            "iss_13_zero_width_zones",
            "iss_14_first_internal_pullback_timing_restriction",
            "iss_15_prefix_consistency_and_ids",
        ]
        synthetic_keys = {
            "iss_07_no_revival_under_same_main_level_3",
            "iss_08_fresh_search_on_new_main_level_3",
            "iss_11_retained_history_preservation",
        }
        for key in expected_keys:
            assert key in iss_fixtures, f"Missing fixture: {key}"
            fix = iss_fixtures[key]
            assert "category" in fix and len(fix["category"]) > 0
            assert "candles" in fix and len(fix["candles"]) > 0
            assert "expected_outcome" in fix

            if key in synthetic_keys:
                assert fix["category"] == ["synthetic_lifecycle_specification", "source_settled"], (
                    f"Fixture {key} must be honestly labeled as synthetic_lifecycle_specification"
                )
            else:
                assert fix["category"] == ["end_to_end_msm_derived", "source_settled"], (
                    f"Fixture {key} must be labeled as end_to_end_msm_derived"
                )

    def test_candles_raw_timezone_awareness_and_finite_ohlc(self, iss_fixtures) -> None:
        """Asserts raw string timezone-awareness, finite prices, and physical OHLC geometry."""
        for key, fix in iss_fixtures.items():
            candles = fix["candles"]
            prev_dt = None
            for idx, c in enumerate(candles):
                raw_time_str = c["time"]
                # Must parse directly as ISO without forced utc conversion to prove native awareness
                dt = datetime.fromisoformat(raw_time_str)
                assert dt.tzinfo is not None, f"Naive timestamp string in {key} bar {idx}: {raw_time_str}"
                assert dt.tzinfo.utcoffset(dt) is not None, f"Missing UTC offset in {key} bar {idx}: {raw_time_str}"
                assert dt.utcoffset().total_seconds() == 0, f"Non-UTC offset in {key} bar {idx}: {raw_time_str}"

                if prev_dt is not None:
                    assert dt > prev_dt, f"Non-monotonic timestamp in {key} bar {idx}: {dt} <= {prev_dt}"
                prev_dt = dt

                o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
                for p_name, p_val in [("open", o), ("high", h), ("low", l), ("close", cl)]:
                    assert math.isfinite(p_val), f"Non-finite price in {key} bar {idx} {p_name}: {p_val}"
                    assert p_val > 0, f"Non-positive price in {key} bar {idx} {p_name}: {p_val}"

                assert h >= max(o, cl), f"Invalid High in {key} bar {idx}: {h} < max({o}, {cl})"
                assert l <= min(o, cl), f"Invalid Low in {key} bar {idx}: {l} > min({o}, {cl})"

    def test_main_bearish_prerequisites_provenance_from_msm_engine(self, iss_fixtures) -> None:
        """Cross-checks Bearish main structure prerequisites with accepted MSMEngine at Bar 9."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        # Main Bearish structure: direction DOWNWARD, evaluated through bar 9
        config_main = MSMConfig(
            start_candle_time=df.index[0].to_pydatetime(),
            direction=Direction.DOWNWARD,
        )
        engine_main = MSMEngine(config_main)
        snap = engine_main.process_candles(df.iloc[:10])

        # Assert completed pair 1 exists
        assert len(snap.confirmed_pairs) == 1
        pair1 = snap.confirmed_pairs[0]

        # Main Level 2: Confirmed High (last_resistance) at Bar 4, price 1.2000
        assert snap.last_resistance is not None
        assert snap.last_resistance.candle_index == 4
        assert snap.last_resistance.price == 1.2000
        assert snap.last_resistance.is_confirmed is True
        assert snap.last_resistance.confirmed_bar_index == 5
        assert snap.last_resistance.confirmed_time == pd.to_datetime(fix["candles"][5]["close_time"])
        assert pair1.high.candle_index == 4
        assert pair1.high.price == 1.2000

        # Main Level 3: Active tentative low at Bar 7, price 1.1400, identified by pullback candle 2 at Bar 9
        assert snap.tentative_point is not None
        assert snap.tentative_point.candle_index == 7
        assert snap.tentative_point.price == 1.1400
        assert snap.tentative_point.identified_bar_index == 9
        assert snap.tentative_point.is_confirmed is False

        # Verify fixture prerequisite record matches exactly
        prereqs = fix["main_prerequisites"]
        assert prereqs["main_level_2"]["candle_index"] == 4
        assert prereqs["main_level_2"]["price"] == 1.2000
        assert prereqs["main_level_3"]["candle_index"] == 7
        assert prereqs["main_level_3"]["price"] == 1.1400
        assert prereqs["captured_boundary"]["min_price"] == 1.1400
        assert prereqs["captured_boundary"]["max_price"] == 1.2000
        assert prereqs["captured_boundary"]["frozen_at_index"] == 9
        assert prereqs["internal_search_reference_index"] == 7
        assert prereqs["first_eligible_internal_pullback_index"] == 10

    def test_main_bullish_prerequisites_provenance_from_msm_engine(self, iss_fixtures) -> None:
        """Cross-checks Bullish main structure prerequisites with accepted MSMEngine at Bar 9."""
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        config_main = MSMConfig(
            start_candle_time=df.index[0].to_pydatetime(),
            direction=Direction.UPWARD,
        )
        engine_main = MSMEngine(config_main)
        snap = engine_main.process_candles(df.iloc[:10])

        assert len(snap.confirmed_pairs) == 1
        pair1 = snap.confirmed_pairs[0]

        # Main Level 2: Confirmed Low (last_support) at Bar 4, price 1.1000
        assert snap.last_support is not None
        assert snap.last_support.candle_index == 4
        assert snap.last_support.price == 1.1000
        assert snap.last_support.is_confirmed is True
        assert snap.last_support.confirmed_bar_index == 5
        assert snap.last_support.confirmed_time == pd.to_datetime(fix["candles"][5]["close_time"])
        assert pair1.low.candle_index == 4
        assert pair1.low.price == 1.1000

        # Main Level 3: Active tentative high at Bar 7, price 1.1600, identified at Bar 9
        assert snap.tentative_point is not None
        assert snap.tentative_point.candle_index == 7
        assert snap.tentative_point.price == 1.1600
        assert snap.tentative_point.identified_bar_index == 9
        assert snap.tentative_point.is_confirmed is False

        prereqs = fix["main_prerequisites"]
        assert prereqs["main_level_2"]["candle_index"] == 4
        assert prereqs["main_level_2"]["price"] == 1.1000
        assert prereqs["main_level_3"]["candle_index"] == 7
        assert prereqs["main_level_3"]["price"] == 1.1600
        assert prereqs["captured_boundary"]["min_price"] == 1.1000
        assert prereqs["captured_boundary"]["max_price"] == 1.1600
        assert prereqs["captured_boundary"]["frozen_at_index"] == 9
        assert prereqs["internal_search_reference_index"] == 7
        assert prereqs["first_eligible_internal_pullback_index"] == 10

    def test_internal_upward_msm_points_crosscheck_with_delayed_scan(self, iss_fixtures) -> None:
        """Cross-checks internal upward MSM swings enforcing the delayed forward-scan boundary."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        # Internal upward marking:
        # Reference candle: Bar 7 (Main Level 3)
        # Delayed forward scan boundary: Bar 10 (strictly after main pullback Bar 9)
        config_int = MSMConfig(
            start_candle_time=df.index[7].to_pydatetime(),
            direction=Direction.UPWARD,
            earliest_pullback_time=df.index[10].to_pydatetime(),
        )
        engine_int = MSMEngine(config_int)
        snap_int = engine_int.process_candles(df)

        assert len(snap_int.confirmed_pairs) == 2

        # Point 1 (CH1) at Bar 10 (price 1.1600, confirmed at Bar 13)
        # Point 2 (CL1) at Bar 12 (price 1.1480, identified at Bar 12, confirmed at Bar 13)
        p1 = snap_int.confirmed_pairs[0]
        assert p1.high.candle_index == 10
        assert p1.high.price == 1.1600
        assert p1.high.identified_bar_index == 12
        assert p1.high.confirmed_bar_index == 13

        assert p1.low.candle_index == 12
        assert p1.low.price == 1.1480
        assert p1.low.confirmed_bar_index == 13

        # Point 3 (CH2) at Bar 14 (price 1.1750, confirmed at Bar 17)
        # Point 4 (CL2) at Bar 16 (price 1.1680, identified at Bar 16, confirmed at Bar 17)
        p2 = snap_int.confirmed_pairs[1]
        assert p2.high.candle_index == 14
        assert p2.high.price == 1.1750
        assert p2.high.identified_bar_index == 16
        assert p2.high.confirmed_bar_index == 17

        assert p2.low.candle_index == 16
        assert p2.low.price == 1.1680
        assert p2.low.confirmed_bar_index == 17

        # Point 5 (Tentative High) at Bar 18 (price 1.1920, identified at Bar 20)
        assert snap_int.tentative_point is not None
        assert snap_int.tentative_point.candle_index == 18
        assert snap_int.tentative_point.price == 1.1920
        assert snap_int.tentative_point.identified_bar_index == 20
        assert snap_int.tentative_point.is_confirmed is False

    def test_internal_downward_msm_points_crosscheck_with_delayed_scan(self, iss_fixtures) -> None:
        """Cross-checks internal downward MSM swings enforcing the delayed forward-scan boundary."""
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        # Internal downward marking:
        # Reference candle: Bar 7 (Main Level 3)
        # Delayed forward scan boundary: Bar 10 (strictly after main pullback Bar 9)
        config_int = MSMConfig(
            start_candle_time=df.index[7].to_pydatetime(),
            direction=Direction.DOWNWARD,
            earliest_pullback_time=df.index[10].to_pydatetime(),
        )
        engine_int = MSMEngine(config_int)
        snap_int = engine_int.process_candles(df)

        assert len(snap_int.confirmed_pairs) == 2

        # Point 1 (CL1) at Bar 10 (price 1.1400), Point 2 (CH1) at Bar 12 (price 1.1520)
        p1 = snap_int.confirmed_pairs[0]
        assert p1.low.candle_index == 10
        assert p1.low.price == 1.1400
        assert p1.low.confirmed_bar_index == 13

        assert p1.high.candle_index == 12
        assert p1.high.price == 1.1520
        assert p1.high.confirmed_bar_index == 13

        # Point 3 (CL2) at Bar 14 (price 1.1250), Point 4 (CH2) at Bar 16 (price 1.1320)
        p2 = snap_int.confirmed_pairs[1]
        assert p2.low.candle_index == 14
        assert p2.low.price == 1.1250
        assert p2.low.confirmed_bar_index == 17

        assert p2.high.candle_index == 16
        assert p2.high.price == 1.1320
        assert p2.high.confirmed_bar_index == 17

        # Point 5 (Tentative Low) at Bar 18 (price 1.1080, identified at Bar 20)
        assert snap_int.tentative_point is not None
        assert snap_int.tentative_point.candle_index == 18
        assert snap_int.tentative_point.price == 1.1080
        assert snap_int.tentative_point.identified_bar_index == 20

    def test_zone_provenance_and_exact_geometry(self, iss_fixtures) -> None:
        """Zones are strictly derived from internal points 3 and 4, never from main 3 or internal 5."""
        fix = iss_fixtures["iss_12_zone_provenance_and_geometry"]
        outcome = fix["expected_outcome"]

        # Level 3 zone: internal point 3 (CH2 at Bar 14) -> RBS [1.1750, 1.1780]
        assert outcome["level_3_provenance"]["point_number"] == 3
        assert outcome["level_3_provenance"]["role"] == "CH2"
        assert outcome["level_3_provenance"]["source_candle_index"] == 14
        assert outcome["level_3_provenance"]["geometry"] == [1.1750, 1.1780]

        # Level 4 / A+ zone: internal point 4 (CL2 at Bar 16) -> Buying A+ [1.1650, 1.1680]
        assert outcome["level_4_provenance"]["point_number"] == 4
        assert outcome["level_4_provenance"]["role"] == "CL2"
        assert outcome["level_4_provenance"]["source_candle_index"] == 16
        assert outcome["level_4_provenance"]["geometry"] == [1.1650, 1.1680]

        assert "MAIN_LEVEL_3" in outcome["disallowed_sources"]
        assert "INTERNAL_POINT_5" in outcome["disallowed_sources"]

    def test_specification_consistency_boundary_equality(self, iss_fixtures) -> None:
        """Specification consistency: boundary equality (P == boundary) satisfies the inclusive range."""
        fix = iss_fixtures["iss_03_boundary_equality"]
        b = fix["main_prerequisites"]["captured_boundary"]
        pts = fix["expected_internal_points"]

        pt5 = next(p for p in pts if p["point_number"] == 5)
        assert pt5["body_edge_price"] == b["max_price"] == 1.2000
        assert b["min_price"] <= pt5["body_edge_price"] <= b["max_price"]
        assert fix["expected_outcome"]["lifecycle_status"] == "CONFIRMED"

    def test_specification_consistency_wick_excursion(self, iss_fixtures) -> None:
        """Specification consistency: wick-only excursion outside boundary does not reject."""
        fix = iss_fixtures["iss_04_wick_excursion_allowed"]
        candles = fix["candles"]
        b = fix["main_prerequisites"]["captured_boundary"]

        # Candle 12 low is 1.1350 < 1.1400 (wick excursion below)
        assert candles[12]["low"] < b["min_price"]
        # Candle 14 high is 1.2060 > 1.2000 (wick excursion above)
        assert candles[14]["high"] > b["max_price"]

        assert fix["expected_outcome"]["lifecycle_status"] == "CONFIRMED"
        rbs_zone = fix["expected_outcome"]["zones"]["level_3_zone"]
        assert rbs_zone["upper_price"] == 1.2060

    def test_specification_consistency_out_of_bounds_rejection(self, iss_fixtures) -> None:
        """Specification consistency: marked body edge outside boundary triggers permanent rejection."""
        fix = iss_fixtures["iss_05_out_of_bounds_marked_point_rejection"]
        outcome = fix["expected_outcome"]
        assert outcome["lifecycle_status"] == "OUT_OF_BOUNDS_REJECTED"
        assert outcome["active_markings_deleted"] is True
        assert outcome["zones_created"] is False

    def test_specification_consistency_outside_range_completion_close(self, iss_fixtures) -> None:
        """Specification consistency: valid points but outside-range completion close enters tracking-only."""
        fix = iss_fixtures["iss_06_outside_range_completion_tracking_only"]
        outcome = fix["expected_outcome"]
        assert outcome["lifecycle_status"] == "OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY"
        assert outcome["completion_close_inside_boundary"] is False
        assert outcome["zones_created"] is False
        assert outcome["markings_retained_for_tracking_only"] is True

    def test_specification_consistency_first_pullback_chronological_timing(self, iss_fixtures) -> None:
        """Specification consistency: internal pullback candles must occur at chronological positions > 9."""
        fix = iss_fixtures["iss_14_first_internal_pullback_timing_restriction"]
        outcome = fix["expected_outcome"]
        assert outcome["min_allowed_first_pullback_index"] == 10
        assert outcome["reused_main_pullback_candles"] is False
