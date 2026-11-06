"""Automated integrity checks for Tap and Zone Activation acceptance fixtures.

Validates:
1. Schema, authorities, and categories of all 10 acceptance fixtures.
2. Strict UTC timezone-awareness, finite positive prices, and geometric consistency (upper_edge >= lower_edge, is_line).
3. Half-open candle event intervals (close_time > time) and strictly chronological event sequences.
4. Independent verification of touch detection (low <= upper_edge and high >= lower_edge).
5. No retroactive wick usage: events strictly prior to eligibility_available_time are rejected (OPEN-04).
6. Observed touch vs. zero geometric path interpolation across gap bars (OPEN-06).
7. Non-resetting repeated touch observations during pending activation (MTF-Analysis.pdf §5).
8. Source CHOCH and t2 replacement cancellation semantics (MTF-Analysis.pdf §9, OPEN-03).
9. External winning entry cancellation, out-of-zone departure, and retouch rearming (MTF-Analysis.pdf §8–10, OPEN-05).
10. Shared-timestamp invalidation precedence (OPEN-03, OPEN-12) and configuration isolation / replay idempotence (OPEN-08, OPEN-09).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict

import pytest

from aladeen.strategy.types import Direction, validate_and_normalize_timestamp


@pytest.fixture(scope="module")
def activation_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "activation_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestActivationFixtureIntegrity:
    """Rigorous integrity validation of Tap and Zone Activation acceptance fixtures."""

    def test_fixture_schema_and_keys(self, activation_fixtures: Dict[str, Any]) -> None:
        """Verifies all 10 required fixture keys are present and categorized."""
        expected_keys = [
            "act_01_known_availability_first_touch",
            "act_02_unknown_availability_blocks_activation",
            "act_03_no_retroactive_wick_claim",
            "act_04_observed_touch_vs_interpolated_path",
            "act_05_repeated_observations_no_reset",
            "act_06_source_choch_cancellation",
            "act_07_source_t2_replacement_cancellation",
            "act_08_external_entry_cancellation_and_rearm",
            "act_09_same_time_event_ordering",
            "act_10_run_isolation_and_replay_idempotence",
        ]
        for key in expected_keys:
            assert key in activation_fixtures, f"Missing required fixture: {key}"
            fix = activation_fixtures[key]
            assert "category" in fix, f"Fixture {key} missing category"
            assert "description" in fix, f"Fixture {key} missing description"
            assert "authority" in fix, f"Fixture {key} missing authority"

    def test_timestamps_and_pricing_geometry(self, activation_fixtures: Dict[str, Any]) -> None:
        """Verifies UTC datetimes, positive finite prices, and geometric bounds across all fixtures."""
        for name, fix in activation_fixtures.items():
            # Check source levels
            for lvl_key in ("source_level", "source_level_set1", "source_level_set2", "source_level_d1"):
                if lvl_key in fix:
                    lvl = fix[lvl_key]
                    lower = lvl["lower_edge"]
                    upper = lvl["upper_edge"]
                    assert math.isfinite(lower) and lower > 0
                    assert math.isfinite(upper) and upper > 0
                    assert upper >= lower
                    expected_is_line = (lower == upper)
                    assert lvl["is_line"] == expected_is_line, f"is_line mismatch in {name} {lvl_key}"

                    lvl_id = lvl["level_id"]
                    t_open = validate_and_normalize_timestamp(lvl_id["source_open_time"], "source_open_time")
                    assert t_open.tzinfo == timezone.utc
                    assert lvl_id["side"] in ("HIGH", "LOW")

                    avail = lvl.get("eligibility_available_time")
                    if avail is not None:
                        t_avail = validate_and_normalize_timestamp(avail, "eligibility_available_time")
                        assert t_avail.tzinfo == timezone.utc
                        assert t_avail >= t_open

            # Check market events
            if "market_events" in fix:
                prev_time: datetime | None = None
                for idx, ev in enumerate(fix["market_events"]):
                    t_ev = validate_and_normalize_timestamp(ev["time"], f"{name} event {idx} time")
                    t_close = validate_and_normalize_timestamp(ev["close_time"], f"{name} event {idx} close_time")
                    assert t_close > t_ev, f"Candle close_time must be strictly greater than open time in {name} event {idx}"
                    if prev_time is not None:
                        assert t_ev >= prev_time, f"Chronological order violated in {name} event {idx}"
                    prev_time = t_ev

                    for price_field in ("open", "high", "low", "close"):
                        val = ev[price_field]
                        assert math.isfinite(val) and val > 0
                    assert ev["high"] >= ev["low"]
                    assert ev["high"] >= max(ev["open"], ev["close"])
                    assert ev["low"] <= min(ev["open"], ev["close"])

    def test_act_01_known_availability_first_touch(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 1: Verifies first touch detection and confirmation timeframe mapping."""
        fix = activation_fixtures["act_01_known_availability_first_touch"]
        lvl = fix["source_level"]
        ev = fix["market_events"][0]

        # Verify touch calculation: low <= upper and high >= lower
        is_touch = (ev["low"] <= lvl["upper_edge"]) and (ev["high"] >= lvl["lower_edge"])
        assert is_touch is True

        # Verify timing: event_time >= availability
        t_avail = validate_and_normalize_timestamp(lvl["eligibility_available_time"], "t_avail")
        t_ev = validate_and_normalize_timestamp(ev["time"], "t_ev")
        assert t_ev >= t_avail

        # Verify expected confirmation mapping (H1 -> M1)
        assert fix["confirmation_timeframe"] == "M1"
        assert fix["expected"]["final_state"] == "PENDING_ACTIVATION"
        assert fix["expected"]["first_touch_time"] == ev["time"]
        assert fix["expected"]["used_status"] is False

    def test_act_02_unknown_availability_blocks_activation(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 2: Unknown availability blocks time-extended activation (fail-closed)."""
        fix = activation_fixtures["act_02_unknown_availability_blocks_activation"]
        lvl = fix["source_level"]
        assert lvl["eligibility_available_time"] is None
        assert fix["expected"]["final_state"] == "INACTIVE_INELIGIBLE"
        assert fix["expected"]["first_touch_time"] is None
        assert fix["expected"]["blocked_reason"] == "UNKNOWN_AVAILABILITY_TIMING"

    def test_act_03_no_retroactive_wick_claim(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 3: Pre-availability wick touch cannot be retroactively claimed (OPEN-04)."""
        fix = activation_fixtures["act_03_no_retroactive_wick_claim"]
        lvl = fix["source_level"]
        t_avail = validate_and_normalize_timestamp(lvl["eligibility_available_time"], "t_avail")

        ev_pre = fix["market_events"][0]
        t_pre = validate_and_normalize_timestamp(ev_pre["time"], "t_pre")
        assert t_pre < t_avail, "Pre-event must occur before availability"
        is_touch_pre = (ev_pre["low"] <= lvl["upper_edge"]) and (ev_pre["high"] >= lvl["lower_edge"])
        assert is_touch_pre is True, "Pre-event physically touched price boundaries"
        assert fix["expected"]["event_pre_wick_accepted"] is False

        ev_post = fix["market_events"][1]
        t_post = validate_and_normalize_timestamp(ev_post["time"], "t_post")
        assert t_post >= t_avail, "Post-event occurs after availability"
        is_touch_post = (ev_post["low"] <= lvl["upper_edge"]) and (ev_post["high"] >= lvl["lower_edge"])
        assert is_touch_post is True
        assert fix["expected"]["activated_event_id"] == ev_post["event_id"]
        assert fix["expected"]["first_touch_time"] == ev_post["time"]

    def test_act_04_observed_touch_vs_interpolated_path(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 4: Zero path interpolation; gaps over zone do not constitute a touch (OPEN-06)."""
        fix = activation_fixtures["act_04_observed_touch_vs_interpolated_path"]
        lvl = fix["source_level"]
        lower, upper = lvl["lower_edge"], lvl["upper_edge"]

        ev_below = fix["market_events"][0]
        assert ev_below["high"] < lower, "Below event is strictly below zone"
        touch_below = (ev_below["low"] <= upper) and (ev_below["high"] >= lower)
        assert touch_below is False

        ev_above = fix["market_events"][1]
        assert ev_above["low"] > upper, "Above event is strictly above zone"
        touch_above = (ev_above["low"] <= upper) and (ev_above["high"] >= lower)
        assert touch_above is False

        ev_real = fix["market_events"][2]
        touch_real = (ev_real["low"] <= upper) and (ev_real["high"] >= lower)
        assert touch_real is True
        assert fix["expected"]["activated_event_id"] == ev_real["event_id"]

    def test_act_05_repeated_observations_no_reset(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 5: Repeated touches do not reset search start time (MTF-Analysis.pdf §5)."""
        fix = activation_fixtures["act_05_repeated_observations_no_reset"]
        evs = fix["market_events"]
        t1 = validate_and_normalize_timestamp(evs[0]["time"], "t1")
        t2 = validate_and_normalize_timestamp(evs[1]["time"], "t2")
        t3 = validate_and_normalize_timestamp(evs[2]["time"], "t3")
        assert t1 < t2 < t3

        # First touch establishes activation time
        assert fix["expected"]["first_touch_time"] == evs[0]["time"]
        assert fix["expected"]["repeated_observations_count"] == 2
        assert fix["expected"]["search_reset_occurred"] is False

    def test_act_06_source_choch_cancellation(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 6: Source main CHOCH immediately cancels pending activation (MTF-Analysis.pdf §9, OPEN-03)."""
        fix = activation_fixtures["act_06_source_choch_cancellation"]
        ev_touch = fix["lifecycle_events"][0]
        ev_choch = fix["lifecycle_events"][1]

        t_touch = validate_and_normalize_timestamp(ev_touch["time"], "t_touch")
        t_choch = validate_and_normalize_timestamp(ev_choch["time"], "t_choch")
        assert t_choch > t_touch

        assert fix["expected"]["state_after_touch"] == "PENDING_ACTIVATION"
        assert fix["expected"]["state_after_choch"] == "CANCELLED_SOURCE_CHOCH"
        assert fix["expected"]["rearm_eligible"] is False
        assert fix["expected"]["used_status"] is False

    def test_act_07_source_t2_replacement_cancellation(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 7: t2 replacement cancels SET_1 activation; SET_2 requires independent touch."""
        fix = activation_fixtures["act_07_source_t2_replacement_cancellation"]
        lvl1 = fix["source_level_set1"]
        lvl2 = fix["source_level_set2"]
        assert lvl1["set_id"] == "SET_1"
        assert lvl2["set_id"] == "SET_2"
        assert lvl1["level_id"] != lvl2["level_id"]

        ev_touch = fix["lifecycle_events"][0]
        ev_repl = fix["lifecycle_events"][1]
        assert ev_repl["outgoing_cancelled_set_id"] == "SET_1"

        assert fix["expected"]["set1_state_after_touch"] == "PENDING_ACTIVATION"
        assert fix["expected"]["set1_state_after_replacement"] == "CANCELLED_SOURCE_REPLACEMENT"
        assert fix["expected"]["set1_rearm_eligible"] is False
        assert fix["expected"]["set2_initial_state"] == "INACTIVE_ELIGIBLE"
        assert fix["expected"]["set2_activation_inherited"] is False

    def test_act_08_external_entry_cancellation_and_rearm(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 8: External entry cancels pending activation without consuming level; leaving zone and retouching rearms."""
        fix = activation_fixtures["act_08_external_entry_cancellation_and_rearm"]
        lvl = fix["source_level_d1"]
        lower, upper = lvl["lower_edge"], lvl["upper_edge"]

        ev_dep = fix["lifecycle_events"][2]
        # Verify departure is strictly outside zone boundaries
        assert ev_dep["high"] < lower or ev_dep["low"] > upper

        ev_retouch = fix["lifecycle_events"][3]
        # Verify retouch intersects zone
        is_retouch = (ev_retouch["low"] <= upper) and (ev_retouch["high"] >= lower)
        assert is_retouch is True

        assert fix["expected"]["state_after_first_touch"] == "PENDING_ACTIVATION"
        assert fix["expected"]["state_after_external_entry"] == "CANCELLED_EXTERNAL_ENTRY"
        assert fix["expected"]["d1_level_used_status_after_cancellation"] is False
        assert fix["expected"]["state_after_departure"] == "OUT_OF_ZONE_ARMED"
        assert fix["expected"]["state_after_retouch"] == "REARMED_PENDING"
        assert fix["expected"]["new_first_touch_time"] == ev_retouch["time"]

    def test_act_09_same_time_event_ordering(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 9: Shared close invalidation precedence (OPEN-03, OPEN-12)."""
        fix = activation_fixtures["act_09_same_time_event_ordering"]
        shared_t = validate_and_normalize_timestamp(fix["shared_timestamp"], "shared_t")
        assert shared_t.tzinfo == timezone.utc

        competing = fix["competing_events_at_t"]
        assert len(competing) == 2
        # Invalidation must have lower order_priority number (higher execution precedence)
        inval_evt = next(e for e in competing if e["event_type"] == "SOURCE_INVALIDATION")
        entry_evt = next(e for e in competing if e["event_type"] == "POTENTIAL_CONFIRMATION_ENTRY")
        assert inval_evt["order_priority"] < entry_evt["order_priority"]

        assert fix["expected"]["invalidation_applied_first"] is True
        assert fix["expected"]["entry_permitted"] is False
        assert fix["expected"]["final_state"] == "CANCELLED_SOURCE_CHOCH"

    def test_act_10_run_isolation_and_replay_idempotence(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 10: Run isolation (OPEN-08) and idempotent replay consistency (OPEN-09)."""
        fix = activation_fixtures["act_10_run_isolation_and_replay_idempotence"]
        assert fix["run_a_config"]["engine_id"] != fix["run_b_config"]["engine_id"]
        assert fix["run_a_config"]["direction"] != fix["run_b_config"]["direction"]
        assert fix["expected"]["run_a_isolated_from_run_b"] is True
        assert fix["expected"]["run_b_does_not_inherit_run_a_activation"] is True
        assert fix["expected"]["run_a_replay_pass_1_matches_pass_2"] is True
        assert fix["expected"]["state_hashes_equal"] is True
