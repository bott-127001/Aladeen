"""Offline source-to-candidate integration proof tests — Synthetic Authority Boundaries.

Covers:
- Integrated engine composition under declared synthetic authority inputs.
- Boundary A: UsageEvidenceStatus.UNKNOWN rejects fail-closed as UNKNOWN_USAGE.
- Boundary B: CoverageStatus.INCOMPLETE rejects fail-closed as INCOMPLETE_COVERAGE.
- Boundary C: source_resolution_status={m: False} blocks fail-closed as BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY.
- Boundary D: has_unresolved_dependencies=True blocks fail-closed as UNRESOLVED_DEPENDENCY.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
)
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction

DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_001")


class TestSourceCandidateAuthorityBoundaries:
    """Authority boundary negative tests under supplied synthetic authority."""

    def test_supplied_synthetic_authority_boundaries(self) -> None:
        """Authority Boundary: Unknown usage, incomplete coverage, and unresolved resolution reject fail-closed."""
        matcher = ConfirmationMatcher()
        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)

        # Baseline valid member
        mem_valid = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            set_id="SET_1",
            role="TJL1",
            side="HIGH",
            lower_edge=1.1350,
            upper_edge=1.1400,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=lvl,
            eligibility_available_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )

        act_valid = ActivationRecord(
            activation_id=format_activation_id("ENGINE_EURUSD_D1", "D1", "FEED_EURUSD_D1", "SET_1", "TJL1", 1),
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            confirmation_timeframe="H1",
            set_id="SET_1",
            role="TJL1",
            level_id=lvl,
            lower_edge=1.1350,
            upper_edge=1.1400,
            state=ActivationState.PENDING_ACTIVATION,
            first_touch_time=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            first_touch_price=1.1375,
            trigger_observation_id="OBS_01",
            generation_seq=1,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )

        ev_valid = ConfirmationEvidenceRecord(
            event_id="EV_VALID",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        # Boundary A: Unknown usage status rejects as UNKNOWN_USAGE
        mem_unknown_usage = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            set_id="SET_1",
            role="TJL1",
            side="HIGH",
            lower_edge=1.1350,
            upper_edge=1.1400,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=lvl,
            eligibility_available_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
        )
        act_unknown_usage = ActivationRecord(
            activation_id=format_activation_id("ENGINE_EURUSD_D1", "D1", "FEED_EURUSD_D1", "SET_1", "TJL1", 1),
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            confirmation_timeframe="H1",
            set_id="SET_1",
            role="TJL1",
            level_id=lvl,
            lower_edge=1.1350,
            upper_edge=1.1400,
            state=ActivationState.PENDING_ACTIVATION,
            first_touch_time=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            first_touch_price=1.1375,
            trigger_observation_id="OBS_01",
            generation_seq=1,
            usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
        )
        ctx_unknown_usage = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_unknown_usage.member_key: mem_unknown_usage},
            source_resolution_status={mem_unknown_usage.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_a = matcher.match(act_unknown_usage, ev_valid, ctx_unknown_usage)
        assert res_a.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_USAGE in res_a.rejection_reasons
        assert res_a.candidate_record is None

        # Boundary B: Incomplete stream coverage rejects as INCOMPLETE_COVERAGE
        ctx_incomplete_cov = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: True},
            coverage_status=CoverageStatus.INCOMPLETE,
        )
        res_b = matcher.match(act_valid, ev_valid, ctx_incomplete_cov)
        assert res_b.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_b.rejection_reasons
        assert res_b.candidate_record is None

        # Boundary C: Unresolved source member resolution rejects as BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY
        ctx_unresolved = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: False},  # Unresolved!
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_c = matcher.match(act_valid, ev_valid, ctx_unresolved)
        assert res_c.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY in res_c.rejection_reasons
        assert res_c.candidate_record is None

        # Boundary D: Evidence has unresolved structural dependencies
        ev_unresolved_dep = ConfirmationEvidenceRecord(
            event_id="EV_UNRES",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            has_unresolved_dependencies=True,  # Explicitly unresolved!
        )
        ctx_valid = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_d = matcher.match(act_valid, ev_unresolved_dep, ctx_valid)
        assert res_d.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY in res_d.rejection_reasons
        assert res_d.candidate_record is None
