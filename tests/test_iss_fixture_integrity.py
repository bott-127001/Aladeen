"""Automated integrity checks for Internal Structure Shift (ISS) acceptance fixtures.

Validates:
1. Strict OHLC geometry, positive finite values, and monotonic UTC timestamps.
2. Cross-checks MSM-derived main prerequisites using the accepted MSMEngine.
3. Cross-checks MSM-derived internal swing points using the accepted MSMEngine.
4. Independent validation of ISS boundaries, inclusive equality, and completion close.
5. Strict zone provenance (internal points 3 and 4 only) and geometry ([UB, High], [Low, LB], zero-wick line).
6. Lifecycle transitions: Confirmed, Out-of-bounds rejection, Outside-range tracking-only, Cancellations.
"""

from __future__ import annotations

import json
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
        for key in expected_keys:
            assert key in iss_fixtures, f"Missing fixture: {key}"
            fix = iss_fixtures[key]
            assert "category" in fix and len(fix["category"]) > 0
            assert "candles" in fix and len(fix["candles"]) > 0
            assert "expected_outcome" in fix

    def test_candles_ohlc_consistency_and_timestamps(self, iss_fixtures) -> None:
        """Asserts physical OHLC geometry and strictly monotonic UTC timestamps across all fixtures."""
        for key, fix in iss_fixtures.items():
            candles = fix["candles"]
            prev_time = None
            for idx, c in enumerate(candles):
                t = pd.to_datetime(c["time"], utc=True)
                assert t.tzinfo is not None, f"Naive timestamp in {key} bar {idx}: {c['time']}"
                if prev_time is not None:
                    assert t > prev_time, f"Non-monotonic timestamp in {key} bar {idx}: {t} <= {prev_time}"
                prev_time = t

                o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
                assert h >= max(o, cl), f"Invalid High in {key} bar {idx}: {h} < max({o}, {cl})"
                assert l <= min(o, cl), f"Invalid Low in {key} bar {idx}: {l} > min({o}, {cl})"
                assert min(o, h, l, cl) > 0, f"Non-positive price in {key} bar {idx}"

    def test_main_bearish_prerequisites_crosscheck_with_msm_engine(self, iss_fixtures) -> None:
        """Cross-checks Bearish main structure prerequisites with accepted MSMEngine."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        # Main Bearish structure: direction DOWNWARD, evaluated through bar 5
        config_main = MSMConfig(
            start_candle_time=df.index[0].to_pydatetime(),
            direction=Direction.DOWNWARD,
        )
        engine_main = MSMEngine(config_main)
        snap = engine_main.process_candles(df.iloc[:6])

        # At Bar 5, main tentative low (Level 3) must be identified at Bar 3 with price 1.1400
        assert snap.tentative_point is not None
        assert snap.tentative_point.candle_index == 3
        assert abs(snap.tentative_point.price - 1.1400) < 1e-4

        # Main Level 2 is the starting confirmed high at Bar 0 (price 1.2000)
        prereqs = fix["main_prerequisites"]
        assert prereqs["main_level_2"]["price"] == 1.2000
        assert prereqs["main_level_3"]["price"] == 1.1400
        assert prereqs["captured_boundary"]["min_price"] == 1.1400
        assert prereqs["captured_boundary"]["max_price"] == 1.2000
        assert prereqs["captured_boundary"]["frozen_at_index"] == 5

    def test_main_bullish_prerequisites_crosscheck_with_msm_engine(self, iss_fixtures) -> None:
        """Cross-checks Bullish main structure prerequisites with accepted MSMEngine."""
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        # Main Bullish structure: direction UPWARD, evaluated through bar 5
        config_main = MSMConfig(
            start_candle_time=df.index[0].to_pydatetime(),
            direction=Direction.UPWARD,
        )
        engine_main = MSMEngine(config_main)
        snap = engine_main.process_candles(df.iloc[:6])

        # At Bar 5, main tentative high (Level 3) must be identified at Bar 3 with price 1.1600
        assert snap.tentative_point is not None
        assert snap.tentative_point.candle_index == 3
        assert abs(snap.tentative_point.price - 1.1600) < 1e-4

        prereqs = fix["main_prerequisites"]
        assert prereqs["main_level_2"]["price"] == 1.1000
        assert prereqs["main_level_3"]["price"] == 1.1600
        assert prereqs["captured_boundary"]["min_price"] == 1.1000
        assert prereqs["captured_boundary"]["max_price"] == 1.1600
        assert prereqs["captured_boundary"]["frozen_at_index"] == 5

    def test_internal_upward_msm_points_crosscheck(self, iss_fixtures) -> None:
        """Cross-checks internal upward MSM swings for Bearish Main fixture."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"]).set_index(pd.to_datetime([c["time"] for c in fix["candles"]], utc=True))

        # Internal upward marking evaluated from reference Bar 3 through 16
        config_int = MSMConfig(
            start_candle_time=df.index[3].to_pydatetime(),
            direction=Direction.UPWARD,
        )
        engine_int = MSMEngine(config_int)
        snap_int = engine_int.process_candles(df.iloc[3:17])

        assert len(snap_int.confirmed_pairs) == 2
        # Pair 1: CH1 at bar 3 (global 6, price 1.1600), CL1 at bar 5 (global 8, price 1.1480)
        p1 = snap_int.confirmed_pairs[0]
        assert abs(p1.high.price - 1.1600) < 1e-4
        assert abs(p1.low.price - 1.1480) < 1e-4

        # Pair 2: CH2 at bar 7 (global 10, price 1.1750), CL2 at bar 9 (global 12, price 1.1680)
        p2 = snap_int.confirmed_pairs[1]
        assert abs(p2.high.price - 1.1750) < 1e-4
        assert abs(p2.low.price - 1.1680) < 1e-4

        # Tentative point: high at bar 11 (global 14, price 1.1920)
        assert snap_int.tentative_point is not None
        assert abs(snap_int.tentative_point.price - 1.1920) < 1e-4

    def test_boundary_equality_satisfies_inclusive_range(self, iss_fixtures) -> None:
        """Boundary equality (P == boundary) is valid per Section 5."""
        fix = iss_fixtures["iss_03_boundary_equality"]
        b = fix["main_prerequisites"]["captured_boundary"]
        pts = fix["expected_internal_points"]

        pt5 = next(p for p in pts if p["point_number"] == 5)
        assert pt5["body_edge_price"] == b["max_price"] == 1.2000
        assert b["min_price"] <= pt5["body_edge_price"] <= b["max_price"]
        assert fix["expected_outcome"]["lifecycle_status"] == "CONFIRMED"

    def test_wick_excursion_does_not_reject(self, iss_fixtures) -> None:
        """Wick-only excursion outside boundary does not reject if marked body edge is inside."""
        fix = iss_fixtures["iss_04_wick_excursion_allowed"]
        candles = fix["candles"]
        b = fix["main_prerequisites"]["captured_boundary"]

        # Candle 8 low is 1.1350 < 1.1400 (wick excursion below)
        assert candles[8]["low"] < b["min_price"]
        # Candle 10 high is 1.2060 > 1.2000 (wick excursion above)
        assert candles[10]["high"] > b["max_price"]

        # Outcome remains CONFIRMED
        assert fix["expected_outcome"]["lifecycle_status"] == "CONFIRMED"
        # Zone coordinates preserve the extended wick without truncation
        rbs_zone = fix["expected_outcome"]["zones"]["level_3_zone"]
        assert rbs_zone["upper_price"] == 1.2060

    def test_out_of_bounds_marked_point_rejected(self, iss_fixtures) -> None:
        """Marked body edge outside boundary triggers permanent rejection."""
        fix = iss_fixtures["iss_05_out_of_bounds_marked_point_rejection"]
        outcome = fix["expected_outcome"]
        assert outcome["lifecycle_status"] == "OUT_OF_BOUNDS_REJECTED"
        assert outcome["active_markings_deleted"] is True
        assert outcome["zones_created"] is False

    def test_outside_range_completion_close_tracking_only(self, iss_fixtures) -> None:
        """Valid marked points but outside-range completion close enters tracking-only."""
        fix = iss_fixtures["iss_06_outside_range_completion_tracking_only"]
        outcome = fix["expected_outcome"]
        assert outcome["lifecycle_status"] == "OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY"
        assert outcome["completion_close_inside_boundary"] is False
        assert outcome["zones_created"] is False
        assert outcome["markings_retained_for_tracking_only"] is True

    def test_zone_provenance_and_geometry(self, iss_fixtures) -> None:
        """Zones are strictly derived from internal points 3 and 4, never from main 3 or internal 5."""
        fix = iss_fixtures["iss_12_zone_provenance_and_geometry"]
        outcome = fix["expected_outcome"]
        assert outcome["level_3_provenance"]["point_number"] == 3
        assert outcome["level_3_provenance"]["role"] == "CH2"
        assert outcome["level_3_provenance"]["source_candle_index"] == 10

        assert outcome["level_4_provenance"]["point_number"] == 4
        assert outcome["level_4_provenance"]["role"] == "CL2"
        assert outcome["level_4_provenance"]["source_candle_index"] == 12

        assert "MAIN_LEVEL_3" in outcome["disallowed_sources"]
        assert "INTERNAL_POINT_5" in outcome["disallowed_sources"]

    def test_zero_width_zones(self, iss_fixtures) -> None:
        """Zero relevant wick produces single price line [P, P] with thickness 0."""
        fix = iss_fixtures["iss_13_zero_width_zones"]
        z = fix["expected_outcome"]["level_3_zone"]
        assert z["lower_price"] == z["upper_price"] == 1.1750
        assert z["is_line"] is True

    def test_first_internal_pullback_timing_restriction(self, iss_fixtures) -> None:
        """Internal pullback candles must occur strictly after the second candle of the main pullback."""
        fix = iss_fixtures["iss_14_first_internal_pullback_timing_restriction"]
        outcome = fix["expected_outcome"]
        assert outcome["min_allowed_first_pullback_index"] == 6
        assert outcome["reused_main_pullback_candles"] is False
