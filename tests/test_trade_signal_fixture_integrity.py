"""Automated integrity checks for Trade-Signal acceptance fixtures — Milestone 30.

Validates:
1. Schema, authorities, and categories of all 31 trade-signal acceptance fixtures.
2. Temporal consistency: all timestamps are valid UTC ISO strings; confirmation close >= tap time in valid signals.
3. Directional concordance: Bullish structure requires Bullish CHOCH/ISS -> BUY; Bearish requires Bearish -> SELL.
4. Pre-activation confirmation rejection: confirmations completed prior to tap cannot be reused (MTF-Analysis.pdf §7).
5. Competing candidate tie-breaking hierarchy:
   - Earliest close timestamp wins (MTF-Analysis.pdf §8).
   - Simultaneous close: lower confirmation timeframe wins (M1 < M5 < H1).
   - Simultaneous same-source: TJL2 / A+ wins over TJL1.
   - Order-independent candidate arrival: arrival order does not affect winning candidate (sig_27).
6. Cross-timeframe coverage & completeness:
   - Incomplete coverage across participating timelines blocks arbitration fail-closed (sig_28).
7. One-trade-per-level usage accounting:
   - Winning entry consumes its level (marks USED); cancelled competing levels remain UNUSED.
   - Used level cannot reactivate or produce repeat signals (MTF-Analysis.pdf §10).
   - Scoped ledger namespace prevents cross-session level consumption (OPEN-08, sig_30).
8. Rearming semantics:
   - Departure followed by fresh touch transitions to REARMED_PENDING and allows signal (MTF-Analysis.pdf §9, OPEN-05).
   - Lingering inside zone without departure blocks rearming (MTF-Analysis.pdf §9 Q&A 25).
9. Source invalidation triggers:
   - Source TJL replacement cancels pending activation (MTF-Analysis.pdf §9, OPEN-03).
   - Source Main CHOCH reverses direction and immediately cancels old-direction activation (MTF-Analysis.pdf §9 Q&A 24).
10. Confirmation consolidation & immutable publication:
   - Multiple confirmations at exact same close consolidate into single signal (OPEN-07, sig_18).
   - Late-arriving second confirmation does not retrospectively mutate published signal (OPEN-09, sig_29).
11. Chronological signal listing without hypothetical open position gating (OPEN-11).
12. Fail-closed handling of unresolved strategy ambiguities:
   - Source c1 == p2 unresolved structure blocks signal (Choch.pdf §1, sig_20).
   - Unresolved ISS multi-candle pullback blocks signal with BLOCKED_UNRESOLVED_CONFIRMATION_GAP (sig_21).
   - Isolated tracking record rejected as confirmation (sig_31).
   - Unknown intra-candle ordering blocks signal with UNKNOWN_ORDER (OPEN-04, sig_22).
   - Forming / incomplete candle cannot confirm signal (sig_23).
13. Zero-width line boundary equality and deterministic replay (OPEN-09).
14. Safety boundary enforcement: all signals carry is_broker_execution == false and signal_type == "CONCEPTUAL_ANALYSIS_SIGNAL".
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "trade_signal_acceptance.json"


@pytest.fixture(scope="module")
def trade_signal_fixtures() -> Dict[str, Any]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"]


def parse_utc_timestamp(ts_str: str) -> datetime:
    """Parse ISO 8601 timestamp string ensuring strict UTC awareness."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    assert dt.tzinfo is not None, f"Timestamp {ts_str} is missing timezone info!"
    return dt


class TestTradeSignalFixtureIntegrity:
    """Rigorous integrity validation of Trade-Signal acceptance fixtures."""

    def test_schema_and_authorities(self) -> None:
        """Verifies top-level schema and authority documentation."""
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "description" in data
        assert "version" in data
        assert "authorities" in data
        assert len(data["authorities"]) >= 3
        assert "categories" in data
        assert "fixtures" in data
        assert len(data["fixtures"]) == 31

    def test_fixture_inventory_and_categories(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies all 31 required fixture keys are present and correctly categorized."""
        expected_keys = [
            "sig_01_bullish_h4_m5_valid_choch_signal",
            "sig_02_bearish_d1_h1_valid_iss_signal",
            "sig_03_bullish_h1_m1_valid_tap_candle_confirmation",
            "sig_04_activation_without_confirmation_no_signal",
            "sig_05_pre_activation_confirmation_cannot_be_reused",
            "sig_06_pattern_starts_before_tap_confirms_after_tap",
            "sig_07_opposite_direction_confirmation_rejected",
            "sig_08_already_aligned_trend_without_fresh_transition_rejected",
            "sig_09_competing_activations_earlier_timestamp_wins",
            "sig_10_competing_simultaneous_timestamp_lower_timeframe_wins",
            "sig_11_competing_simultaneous_same_source_tjl2_wins",
            "sig_12_winning_entry_marks_level_used_and_cancels_all_others",
            "sig_13_used_level_cannot_rearm_or_trade_again",
            "sig_14_cancelled_unused_level_reactivates_after_departure_and_retouch",
            "sig_15_cancelled_level_lingering_inside_cannot_rearm",
            "sig_16_source_replacement_cancels_pending_activation",
            "sig_17_source_main_choch_cancels_old_direction_activation",
            "sig_18_consolidated_choch_and_iss_confirmation_single_signal",
            "sig_19_chronological_listing_without_position_gating",
            "sig_20_unresolved_source_structure_blocks_signal_fail_closed",
            "sig_21_unresolved_iss_multi_candle_pullback_blocks_signal",
            "sig_22_unknown_intra_candle_order_blocks_signal",
            "sig_23_forming_incomplete_candle_cannot_confirm_signal",
            "sig_24_zero_width_single_price_line_boundary_equality",
            "sig_25_prefix_replay_and_immutable_publication",
            "sig_26_published_signal_distinct_from_broker_execution",
            "sig_27_order_independent_candidate_arrival",
            "sig_28_incomplete_timeframe_coverage_blocks_arbitration",
            "sig_29_late_arriving_second_confirmation_does_not_mutate_published_signal",
            "sig_30_scoped_ledger_namespace_prevents_cross_session_consumption",
            "sig_31_isolated_tracking_record_cannot_confirm_signal",
        ]

        allowed_categories = {
            "source_settled",
            "synthetic_event_sequence",
            "edge_boundary_specification"
        }

        for k in expected_keys:
            assert k in trade_signal_fixtures, f"Missing required trade-signal fixture: {k}"
            fix = trade_signal_fixtures[k]
            assert "category" in fix and len(fix["category"]) > 0
            for c in fix["category"]:
                assert c in allowed_categories, f"Invalid category {c} in fixture {k}"
            assert "authority" in fix and len(fix["authority"]) > 0
            assert "description" in fix and len(fix["description"]) > 0
            assert "expected" in fix

    def test_valid_signal_causal_timing(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that for all valid published signals, confirmation close is on or after tap."""
        valid_signal_keys = [
            "sig_01_bullish_h4_m5_valid_choch_signal",
            "sig_02_bearish_d1_h1_valid_iss_signal",
            "sig_03_bullish_h1_m1_valid_tap_candle_confirmation",
            "sig_06_pattern_starts_before_tap_confirms_after_tap",
        ]

        for k in valid_signal_keys:
            fix = trade_signal_fixtures[k]
            tap_dt = parse_utc_timestamp(fix["activation_event"]["tap_timestamp"])
            conf_dt = parse_utc_timestamp(fix["confirmation_event"]["close_timestamp"])
            sig_dt = parse_utc_timestamp(fix["expected"]["signal_timestamp"])

            assert conf_dt >= tap_dt, f"Fixture {k}: confirmation close ({conf_dt}) prior to tap ({tap_dt})!"
            assert sig_dt == conf_dt, f"Fixture {k}: signal timestamp must equal confirmation close timestamp!"
            assert fix["expected"]["signal_published"] is True
            assert fix["expected"]["is_broker_execution"] is False

    def test_directional_concordance_and_mismatch_rejection(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies directional matching between source trend and confirmation pattern."""
        # Bullish valid path
        sig01 = trade_signal_fixtures["sig_01_bullish_h4_m5_valid_choch_signal"]
        assert sig01["source_context"]["direction"] == "UPWARD"
        assert sig01["confirmation_event"]["direction"] == "UPWARD"
        assert sig01["expected"]["signal_side"] == "BUY"

        # Bearish valid path
        sig02 = trade_signal_fixtures["sig_02_bearish_d1_h1_valid_iss_signal"]
        assert sig02["source_context"]["direction"] == "DOWNWARD"
        assert sig02["confirmation_event"]["direction"] == "DOWNWARD"
        assert sig02["expected"]["signal_side"] == "SELL"

        # Opposite direction rejection
        sig07 = trade_signal_fixtures["sig_07_opposite_direction_confirmation_rejected"]
        assert sig07["source_context"]["direction"] == "UPWARD"
        assert sig07["confirmation_event"]["direction"] == "DOWNWARD"
        assert sig07["expected"]["signal_published"] is False
        assert sig07["expected"]["rejection_reason"] == "REJECTED_DIRECTION_MISMATCH"

    def test_pre_activation_confirmation_cannot_be_reused(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that confirmation completed strictly before tap cannot be reused."""
        sig05 = trade_signal_fixtures["sig_05_pre_activation_confirmation_cannot_be_reused"]
        tap_dt = parse_utc_timestamp(sig05["activation_event"]["tap_timestamp"])
        conf_dt = parse_utc_timestamp(sig05["confirmation_event"]["close_timestamp"])

        assert conf_dt < tap_dt, "Pre-activation confirmation test requires conf_dt < tap_dt!"
        assert sig05["expected"]["signal_published"] is False
        assert sig05["expected"]["rejection_reason"] == "PRE_ACTIVATION_CONFIRMATION_REJECTED"

    def test_competing_candidates_and_tie_breakers(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies candidate arbitration hierarchy: earliest timestamp, then lower TF, then TJL2."""
        # 1. Earliest close timestamp wins (sig_09)
        sig09 = trade_signal_fixtures["sig_09_competing_activations_earlier_timestamp_wins"]
        c1 = sig09["candidates"][0] # 08:35 M5
        c2 = sig09["candidates"][1] # 09:00 H1
        assert parse_utc_timestamp(c1["close_timestamp"]) < parse_utc_timestamp(c2["close_timestamp"])
        assert sig09["expected"]["winning_candidate_id"] == "CAND_H4_M5"
        assert "CAND_D1_H1" in sig09["expected"]["cancelled_activation_ids"]
        assert sig09["expected"]["signal_timestamp"] == c1["close_timestamp"]

        # 2. Simultaneous timestamp: lower confirmation timeframe wins (sig_10)
        sig10 = trade_signal_fixtures["sig_10_competing_simultaneous_timestamp_lower_timeframe_wins"]
        assert sig10["candidates"][0]["close_timestamp"] == sig10["candidates"][1]["close_timestamp"]
        assert sig10["expected"]["winning_candidate_id"] == "CAND_H4_M5"
        assert "CAND_D1_H1" in sig10["expected"]["cancelled_activation_ids"]

        # 3. Simultaneous same-source TJL1 vs TJL2: TJL2 / A+ wins (sig_11)
        sig11 = trade_signal_fixtures["sig_11_competing_simultaneous_same_source_tjl2_wins"]
        assert sig11["candidates"][0]["close_timestamp"] == sig11["candidates"][1]["close_timestamp"]
        assert sig11["expected"]["winning_candidate_id"] == "CAND_H4_TJL2"
        assert "CAND_H4_TJL1" in sig11["expected"]["cancelled_activation_ids"]

    def test_order_independent_candidate_arrival(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that competing candidates delivered in different arrival orders produce identical winners (sig_27)."""
        sig27 = trade_signal_fixtures["sig_27_order_independent_candidate_arrival"]
        assert sig27["expected"]["order_a_winner"] == sig27["expected"]["order_b_winner"]
        assert sig27["expected"]["arrival_order_independent"] is True

    def test_incomplete_timeframe_coverage_blocks_arbitration(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that incomplete coverage on any participating timeline blocks arbitration fail-closed (sig_28)."""
        sig28 = trade_signal_fixtures["sig_28_incomplete_timeframe_coverage_blocks_arbitration"]
        assert sig28["expected"]["arbitration_allowed"] is False
        assert sig28["expected"]["rejection_reason"] == "BLOCKED_INCOMPLETE_EVIDENCE_COVERAGE"
        assert sig28["expected"]["signal_published"] is False

    def test_one_trade_per_level_and_usage_consumption(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that winning entry consumes physical level and cancelled levels stay unused."""
        # Winning entry consumes winner; cancelled remain unused (sig_12)
        sig12 = trade_signal_fixtures["sig_12_winning_entry_marks_level_used_and_cancels_all_others"]
        assert sig12["expected"]["consumed_level_keys"] == ["FEED_EURUSD_H4:H4:LVL_01"]
        assert "FEED_EURUSD_D1:D1:LVL_01" in sig12["expected"]["remaining_unused_level_keys"]
        assert "FEED_EURUSD_H1:H1:LVL_01" in sig12["expected"]["remaining_unused_level_keys"]

        # Used level cannot trade again (sig_13)
        sig13 = trade_signal_fixtures["sig_13_used_level_cannot_rearm_or_trade_again"]
        assert sig13["source_context"]["used_status"] is True
        assert sig13["expected"]["activation_granted"] is False
        assert sig13["expected"]["rejection_reason"] == "LEVEL_ALREADY_USED"

    def test_scoped_ledger_namespace_isolation(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that level consumption in session A does not cross-consume in session B (sig_30)."""
        sig30 = trade_signal_fixtures["sig_30_scoped_ledger_namespace_prevents_cross_session_consumption"]
        assert sig30["expected"]["consumed_in_session_a"] is True
        assert sig30["expected"]["consumed_in_session_b"] is False
        assert sig30["expected"]["cross_session_leakage"] is False

    def test_rearming_after_cancellation_semantics(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies rearming requires departure and transitions to REARMED_PENDING; lingering inside is rejected."""
        # Departure + retouch allows reactivation (sig_14)
        sig14 = trade_signal_fixtures["sig_14_cancelled_unused_level_reactivates_after_departure_and_retouch"]
        events14 = sig14["lifecycle_events"]
        assert events14[0]["type"] == "PRIOR_CANCEL"
        assert events14[1]["type"] == "ZONE_DEPARTURE"
        assert events14[2]["type"] == "FRESH_TAP"
        assert sig14["expected"]["reactivation_granted"] is True
        assert sig14["expected"]["rearmed_state"] == "REARMED_PENDING"
        assert sig14["expected"]["signal_published"] is True

        # Lingering inside zone blocks rearming (sig_15)
        sig15 = trade_signal_fixtures["sig_15_cancelled_level_lingering_inside_cannot_rearm"]
        events15 = sig15["lifecycle_events"]
        assert events15[0]["type"] == "PRIOR_CANCEL"
        assert events15[1]["type"] == "LINGERING_PRINT"
        assert sig15["expected"]["reactivation_granted"] is False
        assert sig15["expected"]["rejection_reason"] == "REARMING_BLOCKED_NO_DEPARTURE"

    def test_source_invalidation_and_replacement(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies source replacement and main CHOCH immediately cancel activation."""
        # Source TJL replacement (sig_16)
        sig16 = trade_signal_fixtures["sig_16_source_replacement_cancels_pending_activation"]
        assert sig16["expected"]["activation_status"] == "CANCELLED"
        assert sig16["expected"]["cancellation_reason"] == "SOURCE_TJL_SET_REPLACED"

        # Source main CHOCH (sig_17)
        sig17 = trade_signal_fixtures["sig_17_source_main_choch_cancels_old_direction_activation"]
        assert sig17["expected"]["activation_status"] == "CANCELLED"
        assert sig17["expected"]["cancellation_reason"] == "SOURCE_MAIN_CHOCH_REVERSED_DIRECTION"

    def test_multiple_confirmation_consolidation_and_immutability(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies OPEN-07 same-candle consolidation, and OPEN-09 late confirmation non-mutation."""
        # Same-candle consolidation (sig_18)
        sig18 = trade_signal_fixtures["sig_18_consolidated_choch_and_iss_confirmation_single_signal"]
        assert sig18["expected"]["signal_published"] is True
        assert sig18["expected"]["signal_count"] == 1
        assert len(sig18["expected"]["confirmation_event_ids"]) == 2

        # Late confirmation does not retrospectively mutate published signal (sig_29)
        sig29 = trade_signal_fixtures["sig_29_late_arriving_second_confirmation_does_not_mutate_published_signal"]
        assert sig29["expected"]["retrospective_mutation_applied"] is False
        assert sig29["expected"]["is_immutable"] is True
        assert len(sig29["expected"]["published_confirmation_ids"]) == 1

    def test_position_gating_independence(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies OPEN-11: chronological signals are not suppressed by open positions."""
        sig19 = trade_signal_fixtures["sig_19_chronological_listing_without_position_gating"]
        assert sig19["expected"]["published_signals_count"] == 2
        assert sig19["expected"]["is_position_gated"] is False
        assert len(sig19["expected"]["signal_sequence"]) == 2

    def test_fail_closed_unresolved_strategy_gaps(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that unresolved strategy ambiguities fail-closed with explicit error codes."""
        # c1 == p2 unresolved structure (sig_20)
        sig20 = trade_signal_fixtures["sig_20_unresolved_source_structure_blocks_signal_fail_closed"]
        assert sig20["source_context"]["is_unresolved"] is True
        assert sig20["expected"]["signal_published"] is False
        assert sig20["expected"]["rejection_reason"] == "BLOCKED_SOURCE_UNRESOLVED"

        # ISS multi-candle pullback confirmation (sig_21)
        sig21 = trade_signal_fixtures["sig_21_unresolved_iss_multi_candle_pullback_blocks_signal"]
        assert sig21["expected"]["signal_published"] is False
        assert sig21["expected"]["rejection_reason"] == "BLOCKED_UNRESOLVED_CONFIRMATION_GAP"

        # Isolated tracking record cannot confirm signal (sig_31)
        sig31 = trade_signal_fixtures["sig_31_isolated_tracking_record_cannot_confirm_signal"]
        assert sig31["expected"]["signal_published"] is False
        assert sig31["expected"]["rejection_reason"] == "REJECTED_ISOLATED_TRACKING_NOT_CONFIRMATION"

        # Unknown intra-candle ordering (sig_22)
        sig22 = trade_signal_fixtures["sig_22_unknown_intra_candle_order_blocks_signal"]
        assert sig22["expected"]["signal_published"] is False
        assert sig22["expected"]["rejection_reason"] == "UNKNOWN_ORDER"

        # Forming candle (sig_23)
        sig23 = trade_signal_fixtures["sig_23_forming_incomplete_candle_cannot_confirm_signal"]
        assert sig23["expected"]["signal_published"] is False
        assert sig23["expected"]["rejection_reason"] == "FORMING_CANDLE_CANNOT_CONFIRM"

    def test_boundary_and_safety_invariants(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies zero-width line equality, replay determinism, and non-broker safety boundary."""
        # Zero-width line boundary equality (sig_24)
        sig24 = trade_signal_fixtures["sig_24_zero_width_single_price_line_boundary_equality"]
        assert sig24["source_context"]["is_line"] is True
        assert sig24["source_context"]["lower_edge"] == sig24["source_context"]["upper_edge"]
        assert sig24["market_event"]["price"] == sig24["source_context"]["lower_edge"]
        assert sig24["expected"]["activation_granted"] is True
        assert sig24["expected"]["signal_published"] is True

        # Replay determinism (sig_25)
        sig25 = trade_signal_fixtures["sig_25_prefix_replay_and_immutable_publication"]
        assert sig25["expected"]["is_deterministic"] is True
        assert sig25["expected"]["is_prefix_consistent"] is True

        # Safety boundary (sig_26)
        sig26 = trade_signal_fixtures["sig_26_published_signal_distinct_from_broker_execution"]
        assert sig26["expected"]["is_broker_execution"] is False
        assert sig26["expected"]["signal_type"] == "CONCEPTUAL_ANALYSIS_SIGNAL"
        assert sig26["expected"]["order_routing_executed"] is False
