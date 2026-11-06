"""Automated integrity checks for Trade-Signal acceptance fixtures — Milestone 30.

Validates:
1. Schema, authorities, and categories of all 39 trade-signal acceptance fixtures.
2. Temporal consistency: all timestamps are valid UTC ISO strings; confirmation close >= tap time in valid signals.
3. Directional concordance: Bullish structure requires Bullish CHOCH/ISS -> BUY; Bearish requires Bearish -> SELL.
4. Pre-activation confirmation rejection: confirmations completed prior to tap cannot be reused (MTF-Analysis.pdf §7).
5. Competing candidate tie-breaking hierarchy:
   - Earliest close timestamp wins (MTF-Analysis.pdf §8).
   - Simultaneous close: lower confirmation timeframe wins (M1 < M5 < H1).
   - Simultaneous same-source: TJL2 / A+ wins over TJL1.
   - Order-independent candidate arrival: arrival order does not affect winning candidate (sig_27).
6. Cross-timeframe coverage & completeness:
   - Forming higher-timeframe bar is not missing evidence (sig_28).
   - Incomplete coverage of due events at timestamp T blocks arbitration fail-closed (sig_29).
7. Same-candle causality:
   - Known monotonic sequence establishes causal ordering within same coarse bar despite absent fine timestamps (sig_30).
   - Unknown intra-candle ordering blocks signal with UNKNOWN_ORDER (sig_22).
8. Batch finalization, retries, and late arrivals:
   - Candidates arriving before batch finalization are evaluated together (sig_31).
   - Confirmations on later candles are evaluated in their own batch (sig_32).
   - Idempotent duplicate commit succeeds without duplicate creation (sig_33).
   - Conflicting commit retry fails closed with COMMIT_CONFLICT_REJECTED (sig_34).
   - Genuinely new due evidence arriving after finalization triggers coverage violation (sig_37).
9. Candidate setup identity & canonical encoding:
   - Canonical CandidateSetupKey format: CSK[len:session][len:rev][len:act][len:member][len:conf_cfg][len:candle][len:close].
   - Round-trip parsing and length prefix validation (sig_38, sig_39).
   - Setup key embeds activation ID, source set, and shared confirmation config without conflation.
   - Scoped ledger namespace prevents cross-session level consumption (OPEN-08, sig_35).
10. Confirmation consolidation:
   - Different detectors (CHOCH vs ISS) consolidate under shared confirmation config (OPEN-07, sig_18).
11. One-trade-per-level usage accounting:
   - Winning entry consumes its level (marks USED); cancelled competing levels remain UNUSED.
   - Used level cannot reactivate or produce repeat signals (MTF-Analysis.pdf §10).
12. Rearming semantics:
   - Departure followed by fresh touch transitions to REARMED_PENDING and allows signal (MTF-Analysis.pdf §9, OPEN-05).
   - Lingering inside zone without departure blocks rearming (MTF-Analysis.pdf §9 Q&A 25).
13. Source invalidation triggers:
   - Source TJL replacement cancels pending activation (MTF-Analysis.pdf §9, OPEN-03).
   - Source Main CHOCH reverses direction and immediately cancels old-direction activation (MTF-Analysis.pdf §9 Q&A 24).
14. Chronological signal listing without hypothetical open position gating (OPEN-11).
15. Fail-closed handling of unresolved strategy ambiguities:
   - Source c1 == p2 unresolved structure blocks signal (Choch.pdf §1, sig_20).
   - Unresolved ISS multi-candle pullback blocks signal with BLOCKED_UNRESOLVED_CONFIRMATION_GAP (sig_21).
   - Isolated tracking record rejected as confirmation (sig_36).
   - Forming / incomplete candle cannot confirm signal (sig_23).
16. Zero-width line boundary equality and deterministic replay (OPEN-09).
17. Safety boundary enforcement: all signals carry is_broker_execution == false and signal_type == "CONCEPTUAL_ANALYSIS_SIGNAL".
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List

import pytest
from aladeen.strategy.activation_types import format_activation_id, format_member_key

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "trade_signal_acceptance.json"


def format_length_prefixed(val: str) -> str:
    """Format string with canonical length prefix [len:val]."""
    return f"[{len(val)}:{val}]"


def format_candidate_setup_key(
    domain_session_id: str,
    revision_id: str,
    activation_id: str,
    source_member_key: str,
    confirmation_config_id: str,
    confirmation_candle_id: str,
    confirmation_close_iso: str,
) -> str:
    """Canonical length-prefixed encoding for CandidateSetupKey."""
    return (
        "CSK"
        f"{format_length_prefixed(domain_session_id)}"
        f"{format_length_prefixed(revision_id)}"
        f"{format_length_prefixed(activation_id)}"
        f"{format_length_prefixed(source_member_key)}"
        f"{format_length_prefixed(confirmation_config_id)}"
        f"{format_length_prefixed(confirmation_candle_id)}"
        f"{format_length_prefixed(confirmation_close_iso)}"
    )


def parse_candidate_setup_key(key: str) -> Dict[str, str]:
    """Parse and mathematically validate a canonical CandidateSetupKey."""
    assert key.startswith("CSK["), f"Invalid CSK key prefix in {key!r}"
    parts: List[str] = []
    idx = 3
    while idx < len(key):
        assert key[idx] == "[", f"Expected '[' at index {idx} in {key!r}"
        colon = key.find(":", idx)
        assert colon != -1, f"Expected ':' after index {idx} in {key!r}"
        length_str = key[idx + 1:colon]
        assert length_str.isdigit(), f"Non-digit length prefix {length_str!r} in {key!r}"
        length = int(length_str)
        val_start = colon + 1
        val_end = val_start + length
        assert val_end < len(key), f"Declared length {length} exceeds string boundary in {key!r}"
        assert key[val_end] == "]", f"Expected ']' at index {val_end} in {key!r}"
        val = key[val_start:val_end]
        assert len(val) == length, f"Actual length {len(val)} != declared length {length}"
        parts.append(val)
        idx = val_end + 1

    assert len(parts) == 7, f"Expected 7 components, got {len(parts)} in {key!r}"
    return {
        "domain_session_id": parts[0],
        "revision_id": parts[1],
        "activation_id": parts[2],
        "source_member_key": parts[3],
        "confirmation_config_id": parts[4],
        "confirmation_candle_id": parts[5],
        "confirmation_close_iso": parts[6],
    }


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
        assert len(data["fixtures"]) == 39

    def test_candidate_setup_key_canonical_encoding_and_round_trip(self) -> None:
        """Verifies mathematical round-trip and collision resistance for canonical setup keys."""
        # 1. Standard round-trip
        act_id = format_activation_id("ACT_ENG", "H4", "EURUSD", "SET_1", "TJL1", 1)
        mk_key = format_member_key("SET_1", "TJL1")
        key = format_candidate_setup_key(
            domain_session_id="SESSION_01",
            revision_id="REV_1",
            activation_id=act_id,
            source_member_key=mk_key,
            confirmation_config_id="CONF_M5_CFG_01",
            confirmation_candle_id="EURUSD:M5:20261002T083500Z",
            confirmation_close_iso="2026-10-02T08:35:00+00:00",
        )
        parsed = parse_candidate_setup_key(key)
        assert parsed["domain_session_id"] == "SESSION_01"
        assert parsed["revision_id"] == "REV_1"
        assert parsed["activation_id"] == act_id
        assert parsed["source_member_key"] == mk_key
        assert parsed["confirmation_config_id"] == "CONF_M5_CFG_01"
        assert parsed["confirmation_candle_id"] == "EURUSD:M5:20261002T083500Z"
        assert parsed["confirmation_close_iso"] == "2026-10-02T08:35:00+00:00"

        # 2. Adversarial delimiter round-trip (brackets, colons, newlines)
        adv_session = "SES[SION]:01\nADVERSARIAL"
        adv_key = format_candidate_setup_key(
            domain_session_id=adv_session,
            revision_id="REV:01[A]",
            activation_id=act_id,
            source_member_key=mk_key,
            confirmation_config_id="CONF::CFG",
            confirmation_candle_id="CANDLE[BAR]:01",
            confirmation_close_iso="2026-10-02T08:35:00+00:00",
        )
        adv_parsed = parse_candidate_setup_key(adv_key)
        assert adv_parsed["domain_session_id"] == adv_session
        assert adv_parsed["revision_id"] == "REV:01[A]"
        assert adv_parsed["confirmation_config_id"] == "CONF::CFG"

    def test_fixture_inventory_and_categories(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies all 39 required fixture keys are present and correctly categorized."""
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
            "sig_28_m1_confirmation_between_htf_closes_eligible",
            "sig_29_missing_due_event_blocks_arbitration",
            "sig_30_known_ordered_same_coarse_candle",
            "sig_31_late_candidate_before_batch_finalization",
            "sig_32_late_confirmation_after_finalization_ignored",
            "sig_33_idempotent_duplicate_commit",
            "sig_34_conflicting_commit_retry_rejected",
            "sig_35_scoped_ledger_namespace_prevents_cross_session_consumption",
            "sig_36_isolated_tracking_record_cannot_confirm_signal",
            "sig_37_genuinely_new_late_due_evidence_triggers_coverage_violation",
            "sig_38_same_physical_level_distinct_set_and_activation_identities",
            "sig_39_different_confirmation_configurations_distinct_setup_keys",
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

    def test_all_canonical_length_prefixes_in_fixtures_are_valid(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Mathematically verifies that every length prefix in every fixture key equals the actual slice length."""
        for fix_id, fix in trade_signal_fixtures.items():
            for key_field in ["setup_key", "candidate_setup_key", "setup_key_set_1", "setup_key_set_2", "setup_key_config_a", "setup_key_config_b"]:
                if key_field in fix:
                    csk_str = fix[key_field]
                    parsed = parse_candidate_setup_key(csk_str)
                    assert len(parsed) == 7, f"Fixture {fix_id}: incomplete CSK components!"

    def test_activation_ids_and_cancellation_targets_are_valid_activation_ids(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that all cancelled_activation_ids contain valid activation IDs (ACT_G...), never candidate IDs (CAND_...)."""
        act_pattern = re.compile(r"^ACT_G\d{2}\[\d+:.*\]\[\d+:.*\]\[\d+:.*\]\[\d+:.*\]\[\d+:.*\]$")

        for fix_id, fix in trade_signal_fixtures.items():
            expected = fix.get("expected", {})
            if "cancelled_activation_ids" in expected:
                cancelled = expected["cancelled_activation_ids"]
                assert isinstance(cancelled, list)
                for target_id in cancelled:
                    assert not target_id.startswith("CAND_"), f"Fixture {fix_id}: cancelled target {target_id} is a candidate ID, not an activation ID!"
                    assert act_pattern.match(target_id), f"Fixture {fix_id}: cancelled target {target_id} does not match accepted activation_id format!"

    def test_consolidated_choch_and_iss_confirmation_single_signal(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies OPEN-07: different detectors (CHOCH vs ISS) consolidate under shared confirmation config (sig_18)."""
        sig18 = trade_signal_fixtures["sig_18_consolidated_choch_and_iss_confirmation_single_signal"]
        assert sig18["expected"]["signal_published"] is True
        assert sig18["expected"]["signal_count"] == 1
        assert sig18["expected"]["different_producers_consolidated"] is True
        assert len(sig18["confirmation_events"]) == 2

        # Producers must be distinct (CHOCH detector vs ISS engine)
        producers = [e["producer_id"] for e in sig18["confirmation_events"]]
        assert len(set(producers)) == 2, "Consolidation requires different producer identities!"

        # CandidateSetupKey must parse and use shared confirmation config
        csk = parse_candidate_setup_key(sig18["candidate_setup_key"])
        assert csk["confirmation_config_id"] == sig18["shared_confirmation_config_id"]

        # Reference price must be present
        assert sig18["expected"]["entry_reference_price"] == 1.1395
        assert sig18["expected"]["price_provenance"] == "CONFIRMATION_CANDLE_CLOSE"

    def test_valid_signal_causal_timing(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that for all valid published signals, confirmation close is on or after tap and reference price is present."""
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
            assert "entry_reference_price" in fix["expected"]
            assert fix["expected"]["price_provenance"] == "CONFIRMATION_CANDLE_CLOSE"

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
        c1 = sig09["candidates"][0]  # 08:35 M5
        c2 = sig09["candidates"][1]  # 09:00 H1
        assert parse_utc_timestamp(c1["close_timestamp"]) < parse_utc_timestamp(c2["close_timestamp"])
        assert sig09["expected"]["winning_candidate_id"] == "CAND_H4_M5"
        assert len(sig09["expected"]["cancelled_activation_ids"]) == 1
        assert sig09["expected"]["cancelled_activation_ids"][0].startswith("ACT_G")
        assert sig09["expected"]["signal_timestamp"] == c1["close_timestamp"]

        # 2. Simultaneous timestamp: lower confirmation timeframe wins (sig_10)
        sig10 = trade_signal_fixtures["sig_10_competing_simultaneous_timestamp_lower_timeframe_wins"]
        assert sig10["candidates"][0]["close_timestamp"] == sig10["candidates"][1]["close_timestamp"]
        assert sig10["expected"]["winning_candidate_id"] == "CAND_H4_M5"
        assert len(sig10["expected"]["cancelled_activation_ids"]) == 1
        assert sig10["expected"]["cancelled_activation_ids"][0].startswith("ACT_G")

        # 3. Simultaneous same-source TJL1 vs TJL2: TJL2 / A+ wins (sig_11)
        sig11 = trade_signal_fixtures["sig_11_competing_simultaneous_same_source_tjl2_wins"]
        assert sig11["candidates"][0]["close_timestamp"] == sig11["candidates"][1]["close_timestamp"]
        assert sig11["expected"]["winning_candidate_id"] == "CAND_H4_TJL2"
        assert len(sig11["expected"]["cancelled_activation_ids"]) == 1
        assert sig11["expected"]["cancelled_activation_ids"][0].startswith("ACT_G")

    def test_order_independent_candidate_arrival(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that competing candidates delivered in different arrival orders produce identical winners (sig_27)."""
        sig27 = trade_signal_fixtures["sig_27_order_independent_candidate_arrival"]
        assert sig27["expected"]["order_a_winner"] == sig27["expected"]["order_b_winner"]
        assert sig27["expected"]["arrival_order_independent"] is True

    def test_m1_confirmation_between_htf_closes_eligible(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that forming higher-timeframe bar does not block M1 confirmation (sig_28)."""
        sig28 = trade_signal_fixtures["sig_28_m1_confirmation_between_htf_closes_eligible"]
        assert sig28["due_events_received"] is True
        assert sig28["expected"]["arbitration_allowed"] is True
        assert sig28["expected"]["winning_candidate_id"] == "CAND_H1_M1"
        assert sig28["expected"]["blocked_by_forming_htf"] is False

    def test_missing_due_event_blocks_arbitration(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that missing due event at timestamp T blocks arbitration fail-closed (sig_29)."""
        sig29 = trade_signal_fixtures["sig_29_missing_due_event_blocks_arbitration"]
        assert sig29["missing_due_event"]["status"] == "UNRECEIVED"
        assert sig29["expected"]["arbitration_allowed"] is False
        assert sig29["expected"]["rejection_reason"] == "BLOCKED_INCOMPLETE_EVIDENCE_COVERAGE"
        assert sig29["expected"]["signal_published"] is False

    def test_known_ordered_same_coarse_candle(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies monotonic sequence establishes causal ordering within same coarse bar despite absent fine timestamps (sig_30)."""
        sig30 = trade_signal_fixtures["sig_30_known_ordered_same_coarse_candle"]
        tap_seq = sig30["tap_event"]["sequence_index"]
        conf_seq = sig30["confirmation_event"]["sequence_index"]
        assert tap_seq < conf_seq, "Tap sequence must precede confirmation sequence!"
        assert sig30["tap_event"]["sub_bar_timestamp_available"] is False
        assert sig30["confirmation_event"]["sub_bar_timestamp_available"] is False
        assert sig30["expected"]["causality_valid"] is True
        assert sig30["expected"]["signal_published"] is True
        assert sig30["expected"]["order_established_by_sequence"] is True
        assert sig30["expected"]["fine_timestamp_required"] is False

    def test_late_candidate_before_batch_finalization(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies candidate arriving before finalization is deferred and evaluated (sig_31)."""
        sig31 = trade_signal_fixtures["sig_31_late_candidate_before_batch_finalization"]
        assert sig31["expected"]["deferred_until_complete"] is True
        assert sig31["expected"]["winning_candidate_id"] == "CAND_M5"
        assert sig31["expected"]["tie_broken_by_lower_timeframe"] is True

    def test_later_candle_confirmation_evaluated_in_own_batch(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies confirmation on a later candle is evaluated in its own batch against current activation state (sig_32)."""
        sig32 = trade_signal_fixtures["sig_32_late_confirmation_after_finalization_ignored"]
        assert sig32["expected"]["published_signal_mutated"] is False
        assert sig32["expected"]["evaluated_in_own_batch"] is True
        assert sig32["expected"]["batch_timestamp"] == "2026-10-02T08:45:00+00:00"
        assert sig32["expected"]["signal_published_at_0845"] is False
        assert sig32["expected"]["rejection_reason"] == "LEVEL_ALREADY_USED"
        assert sig32["expected"]["is_immutable"] is True

    def test_idempotent_duplicate_commit(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies identical commit retry succeeds idempotently without duplicate signals (sig_33)."""
        sig33 = trade_signal_fixtures["sig_33_idempotent_duplicate_commit"]
        assert sig33["commit_request_1"]["commit_id"] == sig33["commit_request_2"]["commit_id"]
        assert sig33["expected"]["commit_success"] is True
        assert sig33["expected"]["is_idempotent"] is True
        assert sig33["expected"]["duplicate_signal_created"] is False

    def test_conflicting_commit_retry_rejected(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies conflicting commit retry is strictly rejected with COMMIT_CONFLICT_REJECTED (sig_34)."""
        sig34 = trade_signal_fixtures["sig_34_conflicting_commit_retry_rejected"]
        assert sig34["commit_initial"]["winner_id"] != sig34["commit_conflicting"]["winner_id"]
        assert sig34["expected"]["commit_success"] is False
        assert sig34["expected"]["rejection_reason"] == "COMMIT_CONFLICT_REJECTED"
        assert sig34["expected"]["state_mutated"] is False

    def test_genuinely_new_late_due_evidence_triggers_coverage_violation(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies genuinely new evidence due before batch finalization triggers coverage violation and blocks subsequent decisions (sig_37)."""
        sig37 = trade_signal_fixtures["sig_37_genuinely_new_late_due_evidence_triggers_coverage_violation"]
        assert sig37["expected"]["completeness_violation_triggered"] is True
        assert sig37["expected"]["violation_code"] == "COMPLETENESS_COVERAGE_VIOLATION"
        assert sig37["expected"]["published_signal_mutated"] is False
        assert sig37["expected"]["subsequent_decisions_blocked"] is True
        assert sig37["expected"]["is_immutable"] is True
        assert sig37["expected"]["retained_as_diagnostic"] is True

    def test_same_physical_level_distinct_set_and_activation_identities(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies persistent level across distinct sets produces distinct setup keys without conflation (sig_38)."""
        sig38 = trade_signal_fixtures["sig_38_same_physical_level_distinct_set_and_activation_identities"]
        parsed1 = parse_candidate_setup_key(sig38["setup_key_set_1"])
        parsed2 = parse_candidate_setup_key(sig38["setup_key_set_2"])

        # Computed relationships:
        assert parsed1["activation_id"] != parsed2["activation_id"]
        assert parsed1["source_member_key"] != parsed2["source_member_key"]
        assert parsed1["domain_session_id"] == parsed2["domain_session_id"]
        assert parsed1["confirmation_config_id"] == parsed2["confirmation_config_id"]
        assert sig38["expected"]["setup_keys_distinct"] is True
        assert sig38["expected"]["collision_detected"] is False

    def test_different_confirmation_configurations_distinct_setup_keys(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies distinct confirmation engine configurations produce distinct setup keys without conflation (sig_39)."""
        sig39 = trade_signal_fixtures["sig_39_different_confirmation_configurations_distinct_setup_keys"]
        parsed_a = parse_candidate_setup_key(sig39["setup_key_config_a"])
        parsed_b = parse_candidate_setup_key(sig39["setup_key_config_b"])

        # Computed relationships:
        assert parsed_a["confirmation_config_id"] != parsed_b["confirmation_config_id"]
        assert parsed_a["activation_id"] == parsed_b["activation_id"]
        assert parsed_a["source_member_key"] == parsed_b["source_member_key"]
        assert sig39["expected"]["setup_keys_distinct"] is True
        assert sig39["expected"]["cross_engine_conflation"] is False

    def test_one_trade_per_level_and_usage_consumption(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that winning entry consumes physical level and cancelled levels stay unused."""
        # Winning entry consumes winner; cancelled remain unused (sig_12)
        sig12 = trade_signal_fixtures["sig_12_winning_entry_marks_level_used_and_cancels_all_others"]
        assert sig12["expected"]["consumed_level_keys"] == ["FEED_EURUSD_H4:H4:LVL_01"]
        assert "FEED_EURUSD_D1:D1:LVL_01" in sig12["expected"]["remaining_unused_level_keys"]
        assert "FEED_EURUSD_H1:H1:LVL_01" in sig12["expected"]["remaining_unused_level_keys"]
        assert len(sig12["expected"]["cancelled_activation_ids"]) == 2
        for act_id in sig12["expected"]["cancelled_activation_ids"]:
            assert act_id.startswith("ACT_G")

        # Used level cannot trade again (sig_13)
        sig13 = trade_signal_fixtures["sig_13_used_level_cannot_rearm_or_trade_again"]
        assert sig13["source_context"]["used_status"] is True
        assert sig13["expected"]["activation_granted"] is False
        assert sig13["expected"]["rejection_reason"] == "LEVEL_ALREADY_USED"

    def test_scoped_ledger_namespace_isolation(self, trade_signal_fixtures: Dict[str, Any]) -> None:
        """Verifies that level consumption in session A does not cross-consume in session B (sig_35)."""
        sig35 = trade_signal_fixtures["sig_35_scoped_ledger_namespace_prevents_cross_session_consumption"]
        assert sig35["expected"]["consumed_in_session_a"] is True
        assert sig35["expected"]["consumed_in_session_b"] is False
        assert sig35["expected"]["cross_session_leakage"] is False

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

        # Isolated tracking record cannot confirm signal (sig_36)
        sig36 = trade_signal_fixtures["sig_36_isolated_tracking_record_cannot_confirm_signal"]
        assert sig36["expected"]["signal_published"] is False
        assert sig36["expected"]["rejection_reason"] == "REJECTED_ISOLATED_TRACKING_NOT_CONFIRMATION"

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
