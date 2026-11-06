"""Automated integrity checks for Tap and Zone Activation acceptance fixtures.

Validates:
1. Schema, authorities, and categories of all 20 acceptance fixtures.
2. Strict UTC timezone-awareness, finite positive prices, and geometric consistency (upper_edge >= lower_edge, is_line).
3. Explicit observed price print evidence vs. candidate range overlap (OPEN-06).
4. No retroactive wick usage: events strictly prior to eligibility_available_time are rejected (OPEN-04).
5. Intra-candle availability ordering: known sub-bar ordering vs. blocked UNKNOWN_ORDER (OPEN-04).
6. Non-resetting repeated touch observations during pending activation (MTF-Analysis.pdf §5).
7. Independent concurrent pending activations for both TJL1 and TJL2 (MTF-Analysis.pdf §8, Q&A 22).
8. All three source-to-confirmation timeframe mappings (D1 -> H1, H4 -> M5, H1 -> M1) (MTF-Analysis.pdf §6).
9. Continuation t1 retention: old current set eligible vs. next labels ineligible.
10. Source CHOCH and t2 replacement cancellation semantics (MTF-Analysis.pdf §9, OPEN-03).
11. Persistent physical level surviving replacement without activation inheritance (MTF-Analysis.pdf §4, §9).
12. Rearming semantics (OPEN-05):
    - Path B: already outside at cancellation -> next touch rearms.
    - Path A: inside at cancellation -> departure required; lingering inside blocks rearming.
13. Coarse timestamp T event sequencing after commit finalization (OPEN-12) and rejection of recycled evidence.
14. Unknown usage evidence and incomplete batch / unknown coverage fail-closed blocking.
15. Configuration isolation (OPEN-08) and idempotent replay determinism (OPEN-09).
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
        """Verifies all 20 required fixture keys are present and categorized."""
        expected_keys = [
            "act_01_known_availability_first_touch",
            "act_01b_both_tjl1_and_tjl2_pending_independently",
            "act_01c_all_three_timeframe_mappings",
            "act_01d_t1_retention_current_set_eligible_labels_ineligible",
            "act_02_unknown_availability_blocks_activation",
            "act_02b_unknown_usage_evidence_blocks",
            "act_03_no_retroactive_wick_claim",
            "act_03b_intra_candle_availability_known_vs_unknown",
            "act_04_straddling_range_without_observed_print",
            "act_04b_inclusive_boundary_and_zero_width_line",
            "act_05_repeated_observations_no_reset",
            "act_06_source_choch_cancellation",
            "act_07_source_t2_replacement_cancellation",
            "act_07b_persistent_member_survives_into_replacement_set",
            "act_08a_already_outside_cancellation_rearm",
            "act_08b_lingering_inside_blocks_rearm",
            "act_09a_coarse_timestamp_rearm_after_commit",
            "act_09b_pre_commit_event_recycled_tap_rejected",
            "act_09c_incomplete_batch_unknown_coverage_blocks",
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
            for lvl_key in (
                "source_level",
                "source_level_tjl1",
                "source_level_tjl2",
                "current_set_level",
                "next_labels_level",
                "source_level_set1",
                "source_level_set2",
                "source_level_d1",
            ):
                if lvl_key in fix:
                    lvl = fix[lvl_key]
                    lower = lvl["lower_edge"]
                    upper = lvl["upper_edge"]
                    assert math.isfinite(lower) and lower > 0
                    assert math.isfinite(upper) and upper > 0
                    assert upper >= lower
                    if "is_line" in lvl:
                        expected_is_line = (lower == upper)
                        assert lvl["is_line"] == expected_is_line, f"is_line mismatch in {name} {lvl_key}"

                    if "level_id" in lvl:
                        lvl_id = lvl["level_id"]
                        t_open = validate_and_normalize_timestamp(lvl_id["source_open_time"], "source_open_time")
                        assert t_open.tzinfo == timezone.utc
                        assert lvl_id["side"] in ("HIGH", "LOW")

                    avail = lvl.get("eligibility_available_time")
                    if avail is not None:
                        t_avail = validate_and_normalize_timestamp(avail, "eligibility_available_time")
                        assert t_avail.tzinfo == timezone.utc

            # Check market events
            if "market_events" in fix:
                prev_time: datetime | None = None
                for idx, ev in enumerate(fix["market_events"]):
                    if "time" in ev and "close_time" in ev:
                        t_ev = validate_and_normalize_timestamp(ev["time"], f"{name} event {idx} time")
                        t_close = validate_and_normalize_timestamp(ev["close_time"], f"{name} event {idx} close_time")
                        assert t_close > t_ev, f"Candle close_time must be strictly greater than open time in {name} event {idx}"
                        if prev_time is not None:
                            assert t_ev >= prev_time, f"Chronological order violated in {name} event {idx}"
                        prev_time = t_ev

                    for price_field in ("open", "high", "low", "close"):
                        if price_field in ev:
                            val = ev[price_field]
                            assert math.isfinite(val) and val > 0
                    if "high" in ev and "low" in ev:
                        assert ev["high"] >= ev["low"]

    def test_act_01_known_availability_first_touch(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 1: Verifies first touch detection with explicit observed print and timeframe mapping."""
        fix = activation_fixtures["act_01_known_availability_first_touch"]
        lvl = fix["source_level"]
        ev = fix["market_events"][0]

        # Verify explicit observed print inside [lower, upper]
        prints_in_zone = [p for p in ev["recorded_prints"] if lvl["lower_edge"] <= p <= lvl["upper_edge"]]
        assert len(prints_in_zone) > 0
        assert prints_in_zone[0] == fix["expected"]["observed_print_price"]

        # Verify timing: event_time >= availability
        t_avail = validate_and_normalize_timestamp(lvl["eligibility_available_time"], "t_avail")
        t_ev = validate_and_normalize_timestamp(ev["time"], "t_ev")
        assert t_ev >= t_avail

        assert fix["confirmation_timeframe"] == "M1"
        assert fix["expected"]["final_state"] == "PENDING_ACTIVATION"
        assert fix["expected"]["first_touch_time"] == ev["time"]
        assert fix["expected"]["used_status"] is False

    def test_act_01b_both_tjl1_and_tjl2_pending_independently(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 1B: Both TJL1 and TJL2 on same source timeframe can be pending concurrently."""
        fix = activation_fixtures["act_01b_both_tjl1_and_tjl2_pending_independently"]
        lvl1 = fix["source_level_tjl1"]
        lvl2 = fix["source_level_tjl2"]
        assert lvl1["set_id"] == lvl2["set_id"] == "SET_1"
        assert lvl1["role"] == "TJL1" and lvl2["role"] == "TJL2_A_PLUS"

        ev1 = fix["market_events"][0]
        ev2 = fix["market_events"][1]
        assert ev1["recorded_prints"][0] >= lvl1["lower_edge"] and ev1["recorded_prints"][0] <= lvl1["upper_edge"]
        assert ev2["recorded_prints"][0] >= lvl2["lower_edge"] and ev2["recorded_prints"][0] <= lvl2["upper_edge"]

        assert fix["expected"]["tjl1_state"] == "PENDING_ACTIVATION"
        assert fix["expected"]["tjl2_state"] == "PENDING_ACTIVATION"
        assert fix["expected"]["both_concurrently_pending"] is True

    def test_act_01c_all_three_timeframe_mappings(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 1C: Verifies all three source-to-confirmation timeframe mappings."""
        fix = activation_fixtures["act_01c_all_three_timeframe_mappings"]
        expected_map = {"D1": "H1", "H4": "M5", "H1": "M1"}
        for item in fix["mappings"]:
            src = item["source_timeframe"]
            assert item["expected_confirmation_timeframe"] == expected_map[src]
        assert fix["expected"]["valid_mappings"] is True

    def test_act_01d_t1_retention_current_set_eligible_labels_ineligible(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 1D: At t1, current set remains eligible while next-set labels are ineligible."""
        fix = activation_fixtures["act_01d_t1_retention_current_set_eligible_labels_ineligible"]
        curr_lvl = fix["current_set_level"]
        next_lvl = fix["next_labels_level"]

        assert curr_lvl["set_id"] == "SET_1"
        assert curr_lvl["eligibility_available_time"] is not None
        assert next_lvl["set_id"] is None
        assert next_lvl["eligibility_available_time"] is None

        assert fix["expected"]["current_set_touch_accepted"] is True
        assert fix["expected"]["next_labels_touch_accepted"] is False
        assert fix["expected"]["next_labels_rejection_reason"] == "INELIGIBLE_NOT_CURRENT_MEMBER"

    def test_act_02_unknown_availability_blocks_activation(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 2: Unknown availability blocks activation evidence while preserving structural membership."""
        fix = activation_fixtures["act_02_unknown_availability_blocks_activation"]
        lvl = fix["source_level"]
        assert lvl["eligibility_available_time"] is None
        assert fix["expected"]["structural_set_membership_preserved"] is True
        assert fix["expected"]["activation_evidence_blocked"] is True
        assert fix["expected"]["final_state"] == "INACTIVE_INELIGIBLE"
        assert fix["expected"]["blocked_reason"] == "UNKNOWN_AVAILABILITY_TIMING"

    def test_act_02b_unknown_usage_evidence_blocks(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 2B: Uncertain usage evidence blocks activation (fail-closed)."""
        fix = activation_fixtures["act_02b_unknown_usage_evidence_blocks"]
        assert fix["source_level"]["usage_evidence_status"] == "UNCERTAIN_USAGE_LEDGER_UNVERIFIED"
        assert fix["expected"]["activation_permitted"] is False
        assert fix["expected"]["blocked_reason"] == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"

    def test_act_03_no_retroactive_wick_claim(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 3: Pre-availability wick touch cannot be retroactively claimed (OPEN-04)."""
        fix = activation_fixtures["act_03_no_retroactive_wick_claim"]
        lvl = fix["source_level"]
        t_avail = validate_and_normalize_timestamp(lvl["eligibility_available_time"], "t_avail")

        ev_pre = fix["market_events"][0]
        t_pre = validate_and_normalize_timestamp(ev_pre["time"], "t_pre")
        assert t_pre < t_avail
        assert fix["expected"]["event_pre_wick_accepted"] is False
        assert fix["expected"]["event_pre_wick_rejection_reason"] == "TOUCH_BEFORE_ELIGIBILITY_AVAILABILITY"

        ev_post = fix["market_events"][1]
        t_post = validate_and_normalize_timestamp(ev_post["time"], "t_post")
        assert t_post >= t_avail
        assert fix["expected"]["activated_event_id"] == ev_post["event_id"]
        assert fix["expected"]["first_touch_time"] == ev_post["time"]

    def test_act_03b_intra_candle_availability_known_vs_unknown(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 3B: Intra-candle availability: known ordering activates; unknown ordering blocks as UNKNOWN_ORDER."""
        fix = activation_fixtures["act_03b_intra_candle_availability_known_vs_unknown"]
        lvl = fix["source_level"]
        t_avail = validate_and_normalize_timestamp(lvl["eligibility_available_time"], "t_avail")

        # Case 1: Known ordering
        c1 = fix["case_known_ordering"]
        t_tick = validate_and_normalize_timestamp(c1["touch_tick_time"], "t_tick")
        assert t_tick >= t_avail
        assert lvl["lower_edge"] <= c1["touch_tick_price"] <= lvl["upper_edge"]
        assert c1["expected_result"] == "VALID_TOUCH_POST_AVAILABILITY"

        # Case 2: Unknown ordering
        c2 = fix["case_unknown_ordering"]
        assert c2["tick_sequence_available"] is False
        assert c2["expected_result"] == "BLOCKED_UNKNOWN_ORDER"

    def test_act_04_straddling_range_without_observed_print(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 4: Range straddling without discrete print in zone is rejected as NO_OBSERVED_TOUCH (OPEN-06)."""
        fix = activation_fixtures["act_04_straddling_range_without_observed_print"]
        lvl = fix["source_level"]
        lower, upper = lvl["lower_edge"], lvl["upper_edge"]

        ev = fix["market_events"][0]
        # Range straddles
        assert ev["low"] < lower and ev["high"] > upper
        assert fix["expected"]["range_overlap_diagnostic"] is True

        # But discrete prints do not intersect
        prints_in_zone = [p for p in ev["recorded_prints"] if lower <= p <= upper]
        assert len(prints_in_zone) == 0
        assert fix["expected"]["observed_print_in_zone"] is False
        assert fix["expected"]["touch_accepted"] is False
        assert fix["expected"]["rejection_reason"] == "NO_OBSERVED_PRINT_INSIDE_ZONE"
        assert fix["expected"]["final_state"] == "INACTIVE_ELIGIBLE"

    def test_act_04b_inclusive_boundary_and_zero_width_line(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 4B: Inclusive boundary prints and zero-width lines successfully activate."""
        fix = activation_fixtures["act_04b_inclusive_boundary_and_zero_width_line"]
        reg = fix["regular_zone"]
        assert reg["lower_edge"] <= reg["exact_lower_touch_price"] <= reg["upper_edge"]
        assert reg["lower_edge"] <= reg["exact_upper_touch_price"] <= reg["upper_edge"]

        line = fix["line_level"]
        assert line["is_line"] is True
        assert line["lower_edge"] == line["upper_edge"] == line["exact_line_touch_price"]

        assert fix["expected"]["lower_boundary_touch"] is True
        assert fix["expected"]["upper_boundary_touch"] is True
        assert fix["expected"]["line_level_touch"] is True

    def test_act_05_repeated_observations_no_reset(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 5: Repeated touches while pending do NOT reset first_touch_time or restart search."""
        fix = activation_fixtures["act_05_repeated_observations_no_reset"]
        evs = fix["market_events"]
        assert fix["expected"]["final_state"] == "PENDING_ACTIVATION"
        assert fix["expected"]["first_touch_time"] == evs[0]["time"]
        assert fix["expected"]["repeated_observations_count"] == 2
        assert fix["expected"]["search_reset_occurred"] is False

    def test_act_06_source_choch_cancellation(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 6: Source main CHOCH immediately cancels pending activation with rearm_eligible=False."""
        fix = activation_fixtures["act_06_source_choch_cancellation"]
        assert fix["expected"]["state_after_touch"] == "PENDING_ACTIVATION"
        assert fix["expected"]["state_after_choch"] == "CANCELLED_SOURCE_CHOCH"
        assert fix["expected"]["rearm_eligible"] is False
        assert fix["expected"]["used_status"] is False

    def test_act_07_source_t2_replacement_cancellation(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 7: Source t2 replacement cancels SET_1 activation; SET_2 requires independent touch."""
        fix = activation_fixtures["act_07_source_t2_replacement_cancellation"]
        assert fix["expected"]["set1_state_after_replacement"] == "CANCELLED_SOURCE_REPLACEMENT"
        assert fix["expected"]["set1_rearm_eligible"] is False
        assert fix["expected"]["set2_initial_state"] == "INACTIVE_ELIGIBLE"
        assert fix["expected"]["set2_activation_inherited"] is False

    def test_act_07b_persistent_member_survives_into_replacement_set(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 7B: Persistent physical level survives into SET_2; no activation inheritance; requires fresh touch."""
        fix = activation_fixtures["act_07b_persistent_member_survives_into_replacement_set"]
        assert fix["expected"]["set1_activation_state"] == "CANCELLED_SOURCE_REPLACEMENT"
        assert fix["expected"]["set2_initial_state"] == "INACTIVE_ELIGIBLE"
        assert fix["expected"]["set2_state_after_new_touch"] == "PENDING_ACTIVATION"
        assert fix["expected"]["activation_inherited"] is False
        assert fix["expected"]["physical_identity_preserved"] is True
        assert fix["expected"]["lifetime_usage_committed"] is False

    def test_act_08a_already_outside_cancellation_rearm(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 8A: Price already observed outside at cancellation arms immediately; next touch rearms."""
        fix = activation_fixtures["act_08a_already_outside_cancellation_rearm"]
        assert fix["expected"]["state_after_cancellation"] == "OUT_OF_ZONE_ARMED"
        assert fix["expected"]["state_after_subsequent_touch"] == "REARMED_PENDING"
        assert fix["expected"]["extra_departure_required"] is False

    def test_act_08b_lingering_inside_blocks_rearm(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 8B: Lingering inside without confirmed outside departure blocks rearming (OPEN-05 Path A)."""
        fix = activation_fixtures["act_08b_lingering_inside_blocks_rearm"]
        assert fix["expected"]["state_after_cancellation"] == "CANCELLED_EXTERNAL_ENTRY"
        assert fix["expected"]["rearm_armed"] is False
        assert fix["expected"]["lingering_touch_accepted"] is False
        assert fix["expected"]["rejection_reason"] == "LINGERING_INSIDE_WITHOUT_ZONE_DEPARTURE"

    def test_act_09a_coarse_timestamp_rearm_after_commit(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 9A: Event at coarse timestamp T rearms only AFTER winning commit finalizes (OPEN-12)."""
        fix = activation_fixtures["act_09a_coarse_timestamp_rearm_after_commit"]
        seq = fix["deterministic_event_sequence"]
        commit_evt = next(e for e in seq if e["event_type"] == "WINNING_ENTRY_COMMIT_FINALIZED")
        touch_evt = next(e for e in seq if e["event_type"] == "FRESH_MARKET_TOUCH_EVENT")
        assert commit_evt["sequence_index"] < touch_evt["sequence_index"]
        assert fix["expected"]["commit_finalized_before_touch"] is True
        assert fix["expected"]["rearm_permitted"] is True
        assert fix["expected"]["rearmed_state"] == "REARMED_PENDING"

    def test_act_09b_pre_commit_event_recycled_tap_rejected(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 9B: Pre-commit events and recycled evidence are rejected (OPEN-12)."""
        fix = activation_fixtures["act_09b_pre_commit_event_recycled_tap_rejected"]
        assert fix["expected"]["recycled_evidence_accepted"] is False
        assert fix["expected"]["rejection_reason"] == "CANNOT_RECYCLE_COMPETED_EVIDENCE_PRIOR_TO_COMMIT"

    def test_act_09c_incomplete_batch_unknown_coverage_blocks(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 9C: Incomplete batch or unknown coverage blocks activation transitions (fail-closed)."""
        fix = activation_fixtures["act_09c_incomplete_batch_unknown_coverage_blocks"]
        assert fix["batch_status"] == "INCOMPLETE_MISSING_CANDLE_GAPS"
        assert fix["expected"]["activation_transition_permitted"] is False
        assert fix["expected"]["blocked_reason"] == "UNKNOWN_COVERAGE_FAIL_CLOSED"

    def test_act_10_run_isolation_and_replay_idempotence(self, activation_fixtures: Dict[str, Any]) -> None:
        """Category 10: Run isolation (OPEN-08) and idempotent replay determinism (OPEN-09)."""
        fix = activation_fixtures["act_10_run_isolation_and_replay_idempotence"]
        assert fix["run_a_config"]["engine_id"] != fix["run_b_config"]["engine_id"]
        assert fix["expected"]["run_a_isolated_from_run_b"] is True
        assert fix["expected"]["run_b_does_not_inherit_run_a_activation"] is True
        assert fix["expected"]["run_a_replay_pass_1_matches_pass_2"] is True
        assert fix["expected"]["state_hashes_equal"] is True
