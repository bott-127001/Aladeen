"""Acceptance fixture integrity and prerequisite validation tests for Change of Character (CHOCH).

Scope & Verification Boundary:
------------------------------
This module verifies:
1. Static fixture integrity: data consistency, OHLC geometry, chronological ordering,
   body-edge calculations, zone boundary arithmetic, strict inequality assertions,
   and explicit isolation of unresolved same-close questions.
2. MSM Prerequisite Integration: verifies that fixtures labeled "end-to-end MSM-derived"
   produce the EXACT same swing points, support/resistance levels, and Point 3 states
   when evaluated by the accepted deterministic MSMEngine.

IMPORTANT:
This test verifies fixture geometry, contracts, and MSM prerequisite consistency.
It does NOT implement or verify the CHOCH engine state machine, lifecycle transitions,
or strategy event sequencing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from datetime import datetime
import pytest

from aladeen.strategy.types import Direction, MSMConfig
from aladeen.strategy.engine import MSMEngine


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "choch_acceptance.json"


@pytest.fixture(scope="module")
def choch_fixtures() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ub(c: dict) -> float:
    return max(float(c["open"]), float(c["close"]))


def lb(c: dict) -> float:
    return min(float(c["open"]), float(c["close"]))


class TestCHOCHFixtureIntegrity:
    """Verifies CHOCH acceptance dataset integrity without implementing strategy state machine."""

    def test_fixture_file_exists_and_loads(self, choch_fixtures):
        assert "fixtures" in choch_fixtures
        assert "categories" in choch_fixtures
        valid_cats = set(choch_fixtures["categories"])
        assert len(choch_fixtures["fixtures"]) >= 15

        for fix_id, fix in choch_fixtures["fixtures"].items():
            cats = fix.get("category", [])
            assert isinstance(cats, list) and len(cats) > 0, f"{fix_id}: missing category"
            for c in cats:
                assert c in valid_cats, f"{fix_id}: invalid category '{c}'"

    def test_ohlc_geometry_finite_and_chronology(self, choch_fixtures):
        """Every fixture candle must satisfy strict OHLC bounds, finite checks, and chronological order."""
        for fix_id, fix in choch_fixtures["fixtures"].items():
            candles = fix.get("candles", [])
            if not candles:
                continue

            prev_time = None
            for i, c in enumerate(candles):
                o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])

                # Positive finite prices (strictly rejecting +inf, -inf, nan)
                for val, name in [(o, "open"), (h, "high"), (l, "low"), (cl, "close")]:
                    assert math.isfinite(val), f"{fix_id}[{i}]: {name} is not finite ({val})"
                    assert val > 0, f"{fix_id}[{i}]: {name} is non-positive ({val})"

                # High is upper bound, Low is lower bound
                assert h >= l, f"{fix_id}[{i}]: high < low"
                assert h >= ub(c), f"{fix_id}[{i}]: high < upper body edge"
                assert l <= lb(c), f"{fix_id}[{i}]: low > lower body edge"

                # Chronological ordering of timestamps
                curr_time = datetime.fromisoformat(c.get("time"))
                if prev_time is not None:
                    assert curr_time > prev_time, f"{fix_id}[{i}]: timestamps not strictly increasing"
                prev_time = curr_time

                # If close_time is provided, ensure close_time > time
                if "close_time" in c:
                    close_time = datetime.fromisoformat(c["close_time"])
                    assert close_time > curr_time, f"{fix_id}[{i}]: close_time not after open time"

    def test_bearish_basic_end_to_end_integrity(self, choch_fixtures):
        """Validates OHLC, swing indices, consecutive closes, and zone geometry for Bearish CHOCH."""
        fix = choch_fixtures["fixtures"]["choch_bearish_basic_end_to_end"]
        candles = fix["candles"]
        c_map = {i: c for i, c in enumerate(candles)}

        prereq = fix["prerequisite_state"]
        # Last Support is candle 4 (latest-candle tie-breaker among [1, 3, 4] with LB=1.105)
        support_idx = prereq["last_support"]["candle_idx"]
        assert support_idx == 4
        assert lb(c_map[support_idx]) == prereq["last_support"]["price"]

        high_idx = prereq["confirmed_high"]["candle_idx"]
        assert high_idx == 1
        assert ub(c_map[high_idx]) == prereq["confirmed_high"]["price"]

        p3_idx = prereq["active_point_3"]["candle_idx"]
        assert p3_idx == 5
        assert ub(c_map[p3_idx]) == prereq["active_point_3"]["price"]
        assert prereq["active_point_3"]["identified_at_idx"] == 7

        exp = fix["expected_choch"]
        assert exp["confirmed"] is True
        assert exp["type"] == "BEARISH_CHOCH"
        assert exp["c2_idx"] == exp["c1_idx"] + 1  # Consecutive chronological positions
        assert exp["c1_idx"] == 8
        assert exp["c2_idx"] == 9

        # Strict closing price comparison
        broken_price = prereq["last_support"]["price"]
        c1_close = float(candles[exp["c1_idx"]]["close"])
        c2_close = float(candles[exp["c2_idx"]]["close"])
        assert c1_close < broken_price, "c1 close must be strictly below last support"
        assert c2_close < broken_price, "c2 close must be strictly below last support"
        assert c1_close == exp["c1_close"]
        assert c2_close == exp["c2_close"]

        # Zone geometry validation
        zones = exp["zones"]
        # SBR from Last Support candle (index 4)
        sbr_candle = c_map[support_idx]
        assert zones["SBR"]["lower_price"] == float(sbr_candle["low"])  # 1.104
        assert zones["SBR"]["upper_price"] == lb(sbr_candle)            # 1.105

        # QML / A+ from Confirmed High candle (index 1)
        qml_candle = c_map[high_idx]
        assert zones["QML_A_PLUS"]["lower_price"] == ub(qml_candle)     # 1.135
        assert zones["QML_A_PLUS"]["upper_price"] == float(qml_candle["high"])  # 1.140

        # Double Top from Point 3 candle (index 5)
        dt_candle = c_map[p3_idx]
        assert zones["DOUBLE_TOP"]["lower_price"] == ub(dt_candle)       # 1.155
        assert zones["DOUBLE_TOP"]["upper_price"] == float(dt_candle["high"])    # 1.160

    def test_bullish_basic_end_to_end_integrity(self, choch_fixtures):
        """Validates OHLC, swing indices, consecutive closes, equality handling, and zone geometry for Bullish CHOCH."""
        fix = choch_fixtures["fixtures"]["choch_bullish_basic_end_to_end"]
        candles = fix["candles"]
        c_map = {i: c for i, c in enumerate(candles)}

        prereq = fix["prerequisite_state"]
        # Last Resistance is candle 1 (maximum UB in [1, 4] is 1.245 at candle 1)
        res_idx = prereq["last_resistance"]["candle_idx"]
        assert res_idx == 1
        assert ub(c_map[res_idx]) == prereq["last_resistance"]["price"]
        broken_price = prereq["last_resistance"]["price"]
        assert broken_price == 1.245

        low_idx = prereq["confirmed_low"]["candle_idx"]
        assert low_idx == 1
        assert lb(c_map[low_idx]) == prereq["confirmed_low"]["price"]

        p3_idx = prereq["active_point_3"]["candle_idx"]
        assert p3_idx == 5
        assert lb(c_map[p3_idx]) == prereq["active_point_3"]["price"]
        assert prereq["active_point_3"]["identified_at_idx"] == 7

        # Verify Candle 8 equality rejection within dataset
        c8_close = float(candles[8]["close"])
        assert c8_close == broken_price, "Candle 8 close must exactly equal resistance (1.245) to demonstrate equality rejection"

        exp = fix["expected_choch"]
        assert exp["confirmed"] is True
        assert exp["type"] == "BULLISH_CHOCH"
        assert exp["c1_idx"] == 9
        assert exp["c2_idx"] == 10
        assert exp["c2_idx"] == exp["c1_idx"] + 1

        c1_close = float(candles[exp["c1_idx"]]["close"])
        c2_close = float(candles[exp["c2_idx"]]["close"])
        assert c1_close > broken_price, "c1 close must be strictly above last resistance"
        assert c2_close > broken_price, "c2 close must be strictly above last resistance"
        assert c1_close == exp["c1_close"]
        assert c2_close == exp["c2_close"]

        # Zone geometry validation
        zones = exp["zones"]
        # RBS from Last Resistance candle (index 1)
        rbs_candle = c_map[res_idx]
        assert zones["RBS"]["lower_price"] == ub(rbs_candle)             # 1.245
        assert zones["RBS"]["upper_price"] == float(rbs_candle["high"])  # 1.248

        # QML / A+ from Confirmed Low candle (index 1)
        qml_candle = c_map[low_idx]
        assert zones["QML_A_PLUS"]["lower_price"] == float(qml_candle["low"])  # 1.210
        assert zones["QML_A_PLUS"]["upper_price"] == lb(qml_candle)            # 1.215

        # Double Bottom from Point 3 candle (index 5)
        db_candle = c_map[p3_idx]
        assert zones["DOUBLE_BOTTOM"]["lower_price"] == float(db_candle["low"])  # 1.180
        assert zones["DOUBLE_BOTTOM"]["upper_price"] == lb(db_candle)            # 1.185

    def test_end_to_end_msm_prerequisites_match_msm_engine(self, choch_fixtures):
        """Cross-checks that MSM Engine execution on prefix candles independently produces the exact prerequisite state at Point 3 identification."""
        # 1. Bearish basic prefix verification at Point 3 identification (prefix 0..7)
        bearish_fix = choch_fixtures["fixtures"]["choch_bearish_basic_end_to_end"]
        config_b = MSMConfig(
            start_candle_time=datetime.fromisoformat(bearish_fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine_b_prefix = MSMEngine(config_b)
        snap_b_prefix = engine_b_prefix.process_candles(bearish_fix["candles"][:8])  # Candles 0 through 7

        prereq_b = bearish_fix["prerequisite_state"]
        assert snap_b_prefix.last_support is not None
        assert snap_b_prefix.last_support.candle_index == prereq_b["last_support"]["candle_idx"]  # 4
        assert snap_b_prefix.last_support.price == prereq_b["last_support"]["price"]              # 1.105
        assert snap_b_prefix.confirmed_pairs[0].high.candle_index == prereq_b["confirmed_high"]["candle_idx"]  # 1
        assert snap_b_prefix.tentative_point is not None
        assert snap_b_prefix.tentative_point.candle_index == prereq_b["active_point_3"]["candle_idx"]  # 5
        assert snap_b_prefix.tentative_point.identified_bar_index == prereq_b["active_point_3"]["identified_at_idx"]  # 7

        # Also verify that full candle sequence maintains the same prerequisite levels
        engine_b_full = MSMEngine(config_b)
        snap_b_full = engine_b_full.process_candles(bearish_fix["candles"])
        assert snap_b_full.last_support.candle_index == 4
        assert snap_b_full.last_support.price == 1.105
        assert snap_b_full.tentative_point.candle_index == 5

        # 2. Bullish basic prefix verification at Point 3 identification (prefix 0..7)
        bullish_fix = choch_fixtures["fixtures"]["choch_bullish_basic_end_to_end"]
        config_bull = MSMConfig(
            start_candle_time=datetime.fromisoformat(bullish_fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        engine_bull_prefix = MSMEngine(config_bull)
        snap_bull_prefix = engine_bull_prefix.process_candles(bullish_fix["candles"][:8])  # Candles 0 through 7

        prereq_bull = bullish_fix["prerequisite_state"]
        assert snap_bull_prefix.last_resistance is not None
        assert snap_bull_prefix.last_resistance.candle_index == prereq_bull["last_resistance"]["candle_idx"]  # 1
        assert snap_bull_prefix.last_resistance.price == prereq_bull["last_resistance"]["price"]              # 1.245
        assert snap_bull_prefix.confirmed_pairs[0].low.candle_index == prereq_bull["confirmed_low"]["candle_idx"]  # 1
        assert snap_bull_prefix.tentative_point is not None
        assert snap_bull_prefix.tentative_point.candle_index == prereq_bull["active_point_3"]["candle_idx"]  # 5
        assert snap_bull_prefix.tentative_point.identified_bar_index == prereq_bull["active_point_3"]["identified_at_idx"]  # 7

        # Also verify that full candle sequence maintains the same prerequisite levels
        engine_bull_full = MSMEngine(config_bull)
        snap_bull_full = engine_bull_full.process_candles(bullish_fix["candles"])
        assert snap_bull_full.last_resistance.candle_index == 1
        assert snap_bull_full.last_resistance.price == 1.245
        assert snap_bull_full.tentative_point.candle_index == 5

    def test_rejection_fixtures_integrity(self, choch_fixtures):
        """Validates all negative/rejection fixture assertions without engine execution."""
        # Single close rejection
        fix_single = choch_fixtures["fixtures"]["choch_bearish_single_qualifying_close_rejected"]
        assert fix_single["expected_choch"]["confirmed"] is False
        c_cand = fix_single["candidate_candles"]
        sup = fix_single["prerequisite_state"]["last_support"]["price"]
        assert c_cand[0]["close"] < sup
        assert c_cand[1]["close"] >= sup

        # Equality rejection
        fix_eq = choch_fixtures["fixtures"]["choch_equality_rejected_on_first_or_second_close"]
        for case in fix_eq["candidate_cases"]:
            assert case["expected_confirmed"] is False

        # Non-consecutive closes rejection
        fix_nonconsec = choch_fixtures["fixtures"]["choch_nonconsecutive_qualifying_closes_rejected"]
        assert fix_nonconsec["expected_choch"]["confirmed"] is False
        assert [c["idx"] for c in fix_nonconsec["candidate_closes"]] == [8, 9, 10]
        assert fix_nonconsec["candidate_closes"][1]["qualifies"] is False

        # Wick crossing only rejection
        fix_wick = choch_fixtures["fixtures"]["choch_wick_crossing_without_qualifying_close_rejected"]
        assert fix_wick["expected_choch"]["confirmed"] is False
        for c in fix_wick["candidate_candles"]:
            assert c["low"] < sup
            assert c["close"] >= sup

        # Color independence
        fix_col = choch_fixtures["fixtures"]["choch_qualifying_closes_with_mixed_candle_colors_confirmed"]
        assert fix_col["expected_choch"]["confirmed"] is True
        for c in fix_col["candidate_candles"]:
            assert c["close"] < sup

        # Missing Point 3
        fix_no_p3 = choch_fixtures["fixtures"]["choch_rejected_when_no_active_point_3"]
        assert fix_no_p3["prerequisite_state"]["active_point_3"] is None
        assert fix_no_p3["expected_choch"]["confirmed"] is False

        # Strictly before Point 3 identification rejection
        fix_before = choch_fixtures["fixtures"]["choch_closes_strictly_before_point_3_identification_rejected"]
        assert fix_before["expected_choch"]["confirmed"] is False
        assert fix_before["candle_strictly_before"]["idx"] < fix_before["prerequisite_state"]["point_3_identified_at_idx"]

    def test_unresolved_same_close_boundary_fixture(self, choch_fixtures):
        """Verifies that c1 == p2 is strictly isolated as UNRESOLVED with NO fabricated boolean outcome."""
        fix = choch_fixtures["fixtures"]["choch_same_close_point_3_identification_unresolved"]
        assert "unresolved_boundary" in fix["category"]
        assert fix["eligibility_status"] == "UNRESOLVED_PENDING_RECONCILIATION"
        assert fix["expected_confirmed"] is None  # Must NOT force True or False!

        # Verify static geometry: p2 close is indeed below last support
        sup_price = fix["prerequisite_state"]["last_support"]["price"]
        p2_close = fix["candidate_candle_p2"]["close"]
        assert p2_close < sup_price
        assert fix["candidate_candle_p2"]["idx"] == fix["prerequisite_state"]["point_3_identified_at_idx"]
        assert fix["static_geometry_check"]["p2_close_strictly_below_support"] is True

        # Verify interpretation options are clearly articulated
        assert "option_a_simultaneous_close_eligible" in fix["interpretation_options"]
        assert "option_b_strictly_later_close_required" in fix["interpretation_options"]

    def test_equal_level_search_geometry_boundary(self, choch_fixtures):
        """Verifies mathematical non-overlap of continuation vs CHOCH using inclusive search geometry."""
        fix = choch_fixtures["fixtures"]["choch_equal_level_search_geometry_boundary"]
        ded = fix["search_geometry_deduction"]
        assert ded["tentative_high_price"] == ded["last_support_price"]
        level = ded["tentative_high_price"]

        for eval_case in fix["test_evaluations"]:
            cl = eval_case["close"]
            cont_sat = cl > level
            choch_sat = cl < level
            assert eval_case["continuation_satisfied"] == cont_sat
            assert eval_case["choch_satisfied"] == choch_sat
            # Core proof: they can NEVER both be True simultaneously
            assert not (cont_sat and choch_sat), f"Simultaneous overlap violated at close={cl}"

    def test_zero_width_zones_geometry(self, choch_fixtures):
        """Validates zero-wick zones preserve single price line contracts with zero thickness."""
        fix = choch_fixtures["fixtures"]["choch_zero_width_zones_preserved_as_price_lines"]
        orig = fix["original_candles"]
        zones = fix["expected_zones"]

        # Confirmed High has high == ub
        c_high = orig["confirmed_high"]
        assert c_high["high"] == ub(c_high)
        assert zones["QML_A_PLUS"]["lower_price"] == zones["QML_A_PLUS"]["upper_price"]
        assert zones["QML_A_PLUS"]["is_line"] is True

        # Confirmed Low has low == lb
        c_low = orig["confirmed_low"]
        assert c_low["low"] == lb(c_low)
        assert zones["SBR"]["lower_price"] == zones["SBR"]["upper_price"]
        assert zones["SBR"]["is_line"] is True

        # Point 3 has top wick
        p3 = orig["point_3"]
        assert p3["high"] > ub(p3)
        assert zones["DOUBLE_TOP"]["lower_price"] < zones["DOUBLE_TOP"]["upper_price"]
        assert zones["DOUBLE_TOP"]["is_line"] is False

    def test_cycle_reset_and_restart_reference_rules(self, choch_fixtures):
        """Validates Point 3 confirmation reset and new cycle restart indexing."""
        # Cycle completion resets tentative status
        fix_reset = choch_fixtures["fixtures"]["choch_tentative_point_confirmed_resets_choch_sequence"]
        p3_price = fix_reset["prerequisite_state"]["active_point_3"]["price"]
        break_close = fix_reset["continuation_break_candle"]["close"]
        assert break_close > p3_price
        assert fix_reset["expected_state_after_idx_8"]["tentative_point_3_active"] is False
        assert fix_reset["expected_state_after_idx_8"]["choch_close_count"] == 0
        assert fix_reset["expected_choch_at_idx_10"]["confirmed"] is False

        # Unconfirmed raw extreme does not alter Point 3 anchor
        fix_raw = choch_fixtures["fixtures"]["choch_active_point_3_not_replaced_by_later_raw_extreme"]
        assert fix_raw["intermediate_raw_extreme"]["high"] > fix_raw["prerequisite_state"]["active_point_3"]["price"]
        assert fix_raw["expected_choch"]["double_top_source_candle_idx"] == 5

        # Restart reference and post-confirmation pullback restriction
        fix_restart = choch_fixtures["fixtures"]["choch_restart_reference_and_post_confirmation_pullback_restriction"]
        conf_idx = fix_restart["choch_confirmation_candle_idx"]
        assert fix_restart["expected_new_cycle"]["direction"] == "DOWNWARD"
        assert fix_restart["expected_new_cycle"]["search_start_candle_idx"] == 5
        assert fix_restart["expected_new_cycle"]["first_pullback_min_candidate_idx"] == conf_idx + 1
