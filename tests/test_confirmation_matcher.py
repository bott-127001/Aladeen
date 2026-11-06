"""Comprehensive test suite for Offline Confirmation-to-Activation Matcher — Milestone 31 (HANDOFF-093).

Decisive regressions and coverage:
1. Authoritative matching authority: missing members, member inconsistency, missing physical level identity, and contradictory association targets.
2. Domain-scoped sequence comparison (cross-domain integers rejected) and evaluation availability boundary (future evidence rejected).
3. Adapter completion time integrity: no candle-open or Unix epoch substitution; timeframe interval validation; forming candle rejection.
4. Batch consolidation: duplicate deduplication using complete immutable evidence equality, conflicting identity rejection, unique candidate collection, and permutation invariance across reversed/shuffled orders.
5. Deterministic replay: zero wall-clock dependence.
6. Continuous pre-tap detection: truthful MTF adaptation for real candle-derived CHOCH (D1 source -> H1 confirmation) with pre-tap formation and post-tap completion.
7. Authoritative vs blocked ISS branches: genuine candle-derived ISS matches; unresolved dependencies fail closed.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
from typing import Any, Dict, List

import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
    format_activation_id,
    format_member_key,
)
from aladeen.strategy.choch_detector import ChochDetector
from aladeen.strategy.choch_types import ChochType, ChochZone, ChochZoneType, ConfirmedChoch
from aladeen.strategy.confirmation_adapters import (
    adapt_confirmed_choch_to_evidence,
    adapt_confirmed_iss_to_evidence,
)
from aladeen.strategy.confirmation_matcher import (
    ConfirmationMatcher,
    MatchingContext,
    ROLE_RANK_MAP,
    TIMEFRAME_RANK_MAP,
)
from aladeen.strategy.confirmation_types import (
    BatchMatchResult,
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    TouchSequenceEvidence,
    format_candidate_setup_key,
    parse_candidate_setup_key,
)
from aladeen.strategy.coordinator import MSMChochCoordinator
from aladeen.strategy.iss_engine import ISSEngine
from aladeen.strategy.iss_types import (
    ConfirmedISSEvent,
    FrozenBoundary,
    ISSConfig,
    ISSLifecycleStatus,
    ISSZone,
    ISSZoneType,
    InternalPoint,
)
from aladeen.strategy.tjl_types import StableLevelId
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle


DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_H4", run_id="RUN_20261001")
_DEFAULT_LEVEL = object()


def make_member(
    engine_id: str = "ACT_ENGINE_DEMO",
    symbol: str = "EURUSD",
    source_timeframe: str = "H4",
    set_id: str = "SET_20261001_H4",
    role: str = "TJL1",
    side: str = "HIGH",
    lower_edge: float = 1.1350,
    upper_edge: float = 1.1380,
    direction: Direction = Direction.UPWARD,
    feed_id: str = "FEED_EURUSD_H4",
    usage_evidence_status: UsageEvidenceStatus = UsageEvidenceStatus.UNUSED,
    level_id: Any = _DEFAULT_LEVEL,
) -> SourceMemberReference:
    if level_id is _DEFAULT_LEVEL:
        level_id = StableLevelId(
            symbol_feed_id=feed_id,
            source_timeframe=source_timeframe,
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
            side=side,
        )
    return SourceMemberReference(
        engine_id=engine_id,
        symbol=symbol,
        source_timeframe=source_timeframe,
        set_id=set_id,
        role=role,
        side=side,
        lower_edge=lower_edge,
        upper_edge=upper_edge,
        is_line=False,
        direction=direction,
        level_id=level_id,
        usage_evidence_status=usage_evidence_status,
    )


def make_activation(
    activation_id: str = "ACT_G01[15:ACT_ENGINE_DEMO][2:H4][6:EURUSD][15:SET_20261001_H4][4:TJL1]",
    engine_id: str = "ACT_ENGINE_DEMO",
    symbol: str = "EURUSD",
    source_timeframe: str = "H4",
    confirmation_timeframe: str = "M5",
    set_id: str = "SET_20261001_H4",
    role: str = "TJL1",
    lower_edge: float = 1.1350,
    upper_edge: float = 1.1380,
    state: ActivationState = ActivationState.PENDING_ACTIVATION,
    first_touch_time: datetime = datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
    first_touch_price: float = 1.1365,
    trigger_observation_id: str = "OBS_001",
    generation_seq: int = 1,
    usage_evidence_status: UsageEvidenceStatus = UsageEvidenceStatus.UNUSED,
    feed_id: str = "FEED_EURUSD_H4",
    level_id: Any = _DEFAULT_LEVEL,
) -> ActivationRecord:
    if level_id is _DEFAULT_LEVEL:
        level_id = StableLevelId(
            symbol_feed_id=feed_id,
            source_timeframe=source_timeframe,
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
            side="HIGH",
        )
    return ActivationRecord(
        activation_id=activation_id,
        engine_id=engine_id,
        symbol=symbol,
        source_timeframe=source_timeframe,
        confirmation_timeframe=confirmation_timeframe,
        set_id=set_id,
        role=role,
        level_id=level_id,
        lower_edge=lower_edge,
        upper_edge=upper_edge,
        state=state,
        first_touch_time=first_touch_time,
        first_touch_price=first_touch_price,
        trigger_observation_id=trigger_observation_id,
        generation_seq=generation_seq,
        usage_evidence_status=usage_evidence_status,
    )


def make_evidence(
    event_id: str = "EVT_CHOCH_01",
    producer_id: str = "CHOCH_DETECTOR_v1",
    pattern_type: str = "CHOCH",
    confirmation_config_id: str = "CONF_CFG_EURUSD_M5_v1",
    confirmation_timeframe: str = "M5",
    confirmation_candle_id: str = "EURUSD:M5:20261002T084500Z",
    close_timestamp: Optional[datetime] = datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc),
    close_price: float = 1.1395,
    price_basis: PriceBasis = PriceBasis.BID,
    direction: Direction = Direction.UPWARD,
    is_completed: bool = True,
    has_unresolved_dependencies: bool = False,
    structural_dependency_references: tuple = ("CHOCH_TYPE:BULLISH_CHOCH", "POINT_3_INDEX:5"),
    symbol: str = "EURUSD",
    feed_id: str = "FEED_EURUSD_H4",
    sequence_domain: SequenceDomain = DEFAULT_DOMAIN,
    sequence_ref: Optional[int] = 100,
    is_isolated_tracking: bool = False,
    activation_id: Optional[str] = None,
    source_member_key: Optional[str] = None,
) -> ConfirmationEvidenceRecord:
    return ConfirmationEvidenceRecord(
        event_id=event_id,
        producer_id=producer_id,
        pattern_type=pattern_type,
        confirmation_config_id=confirmation_config_id,
        confirmation_timeframe=confirmation_timeframe,
        confirmation_candle_id=confirmation_candle_id,
        close_timestamp=close_timestamp,
        close_price=close_price,
        price_basis=price_basis,
        direction=direction,
        is_completed=is_completed,
        has_unresolved_dependencies=has_unresolved_dependencies,
        structural_dependency_references=structural_dependency_references,
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        sequence_ref=sequence_ref,
        is_isolated_tracking=is_isolated_tracking,
        activation_id=activation_id,
        source_member_key=source_member_key,
    )


def make_context(
    members: Optional[Dict[str, SourceMemberReference]] = None,
    evaluation_time: datetime = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
    expected_config: str = "CONF_CFG_EURUSD_M5_v1",
    expected_basis: PriceBasis = PriceBasis.BID,
    matching_domain: SequenceDomain = DEFAULT_DOMAIN,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    touch_evidence: Optional[Dict[str, TouchSequenceEvidence]] = None,
) -> MatchingContext:
    if members is None:
        m = make_member()
        members = {m.member_key: m}
    return MatchingContext(
        domain_session_id="SESSION_20261001",
        revision_id="REV_001",
        expected_price_basis=expected_basis,
        expected_confirmation_config_id=expected_config,
        matching_sequence_domain=matching_domain,
        evaluation_time=evaluation_time,
        current_members=members,
        coverage_status=coverage_status,
        touch_sequence_evidence=touch_evidence,
    )


class TestAuthoritativeMatchingAuthority:
    """Regressions for Directive 1: Explicit matching authority & fail-closed validation."""

    @pytest.mark.parametrize(
        "src_tf,conf_tf,dir_enum,sig_side",
        [
            ("D1", "H1", Direction.UPWARD, "BUY"),
            ("D1", "H1", Direction.DOWNWARD, "SELL"),
            ("H4", "M5", Direction.UPWARD, "BUY"),
            ("H4", "M5", Direction.DOWNWARD, "SELL"),
            ("H1", "M1", Direction.UPWARD, "BUY"),
            ("H1", "M1", Direction.DOWNWARD, "SELL"),
        ],
    )
    def test_bullish_bearish_and_all_three_timeframe_mappings(
        self, src_tf: str, conf_tf: str, dir_enum: Direction, sig_side: str
    ) -> None:
        """Verifies (D1->H1), (H4->M5), (H1->M1) for both Bullish (BUY) and Bearish (SELL) under authoritative authority."""
        matcher = ConfirmationMatcher()
        cfg_id = f"CONF_CFG_EURUSD_{conf_tf}_v1"
        act = make_activation(
            source_timeframe=src_tf,
            confirmation_timeframe=conf_tf,
            role="TJL2_A_PLUS",
        )
        mem = make_member(
            source_timeframe=src_tf,
            role="TJL2_A_PLUS",
            direction=dir_enum,
        )
        ev = make_evidence(
            confirmation_config_id=cfg_id,
            confirmation_timeframe=conf_tf,
            direction=dir_enum,
        )
        ctx = make_context(
            members={mem.member_key: mem},
            expected_config=cfg_id,
        )

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == sig_side
        assert cand.source_timeframe == src_tf
        assert cand.confirmation_timeframe == conf_tf
        assert cand.timeframe_rank == TIMEFRAME_RANK_MAP[conf_tf]
        assert cand.role_rank == ROLE_RANK_MAP["TJL2_A_PLUS"]
        assert cand.is_consolidated is False

    def test_missing_current_members_map_blocks_with_authority_error(self) -> None:
        """Empty current_members fails closed with MISSING_MATCHING_AUTHORITY."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()
        ctx = make_context(members={})  # Empty authority

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.MISSING_MATCHING_AUTHORITY in res.rejection_reasons

    def test_member_absent_from_current_members_fails_closed(self) -> None:
        """Member not registered in current_members rejects with MEMBERSHIP_CANCELLED_OR_REPLACED."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()
        other_member = make_member(role="TJL2_A_PLUS")  # Different member key
        ctx = make_context(members={other_member.member_key: other_member})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res.rejection_reasons

    @pytest.mark.parametrize(
        "field_name,mismatched_val",
        [
            ("engine_id", "ACT_ENGINE_OTHER"),
            ("symbol", "GBPUSD"),
            ("source_timeframe", "H1"),
            ("set_id", "SET_REPLACED_H4"),
            ("lower_edge", 1.1340),
            ("upper_edge", 1.1390),
            ("usage_evidence_status", UsageEvidenceStatus.USED),
        ],
    )
    def test_member_to_activation_inconsistency_fails_closed(
        self, field_name: str, mismatched_val: Any
    ) -> None:
        """Full consistency: any discrepancy between activation and registered member rejects with CONTEXT_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()
        kwargs: Dict[str, Any] = {field_name: mismatched_val}
        corrupted_member = make_member(**kwargs)
        ctx = make_context(members={act.member_key: corrupted_member})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CONTEXT_MISMATCH in res.rejection_reasons

    def test_missing_physical_level_id_fails_closed(self) -> None:
        """Missing level_id on either activation or member rejects with CONTEXT_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation(level_id=None)
        mem = make_member()
        ev = make_evidence()
        ctx = make_context(members={mem.member_key: mem})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CONTEXT_MISMATCH in res.rejection_reasons

        # Also test member with missing level_id
        act_valid = make_activation()
        mem_no_level = make_member(level_id=None)
        ctx_mem = make_context(members={mem_no_level.member_key: mem_no_level})
        res2 = matcher.match(act_valid, ev, ctx_mem)
        assert res2.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CONTEXT_MISMATCH in res2.rejection_reasons

    def test_contradictory_explicit_association_fields_rejected(self) -> None:
        """Evidence with contradictory activation_id or member_key rejects with ASSOCIATION_TARGET_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev_wrong_act = make_evidence(activation_id="ACT_DIFFERENT_TARGET")
        ctx = make_context()

        res = matcher.match(act, ev_wrong_act, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.ASSOCIATION_TARGET_MISMATCH in res.rejection_reasons

        ev_wrong_mk = make_evidence(source_member_key="MK[10:OTHER_SET][4:TJL1]")
        res_mk = matcher.match(act, ev_wrong_mk, ctx)
        assert res_mk.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.ASSOCIATION_TARGET_MISMATCH in res_mk.rejection_reasons

    def test_unbound_source_event_matches_multiple_eligible_activations(self) -> None:
        """Unbound evidence (activation_id=None, source_member_key=None) legitimately associates with multiple activations."""
        matcher = ConfirmationMatcher()
        act1 = make_activation(role="TJL1")
        act2 = make_activation(role="TJL2_A_PLUS", activation_id="ACT_G01[15:ACT_ENGINE_DEMO][2:H4][6:EURUSD][15:SET_20261001_H4][11:TJL2_A_PLUS]")
        m1 = make_member(role="TJL1")
        m2 = make_member(role="TJL2_A_PLUS")
        ev_unbound = make_evidence()  # None for explicit association targets
        ctx = make_context(members={m1.member_key: m1, m2.member_key: m2})

        batch_res = matcher.match_batch([act1, act2], [ev_unbound], ctx)
        assert len(batch_res.unique_candidates) == 2
        assert all(r.status == ConfirmationMatchStatus.MATCHED for r in batch_res.pair_results)


class TestDomainScopedCausalityAndAvailability:
    """Regressions for Directive 2: Domain-scoped sequence ordering and evaluation boundary."""

    def test_cross_domain_sequence_comparison_rejected(self) -> None:
        """Cross-domain bare integers are rejected with CROSS_DOMAIN_ORDERING_REJECTED."""
        matcher = ConfirmationMatcher()
        shared_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        act = make_activation(first_touch_time=shared_time, trigger_observation_id="OBS_101")

        # Evidence in domain A
        ev = make_evidence(
            close_timestamp=shared_time,
            sequence_domain=SequenceDomain(feed_id="FEED_EURUSD_H4", run_id="RUN_20261001"),
            sequence_ref=200,
        )

        # Touch sequence in cross domain B
        cross_domain_touch = TouchSequenceEvidence(
            sequence_domain=SequenceDomain(feed_id="FEED_CROSS_RUN", run_id="RUN_DIFFERENT"),
            sequence_ref=100,
        )
        ctx = make_context(touch_evidence={"OBS_101": cross_domain_touch})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED in res.rejection_reasons

    def test_compatible_domain_sequence_comparison_case_b_valid(self) -> None:
        """Within compatible sequence domain, tap_seq < conf_seq validates Case B causal ordering."""
        matcher = ConfirmationMatcher()
        shared_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        act = make_activation(first_touch_time=shared_time, trigger_observation_id="OBS_101")
        ev = make_evidence(
            close_timestamp=shared_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=200,
        )
        valid_touch = TouchSequenceEvidence(sequence_domain=DEFAULT_DOMAIN, sequence_ref=150)
        ctx = make_context(touch_evidence={"OBS_101": valid_touch})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None

    def test_future_evidence_beyond_evaluation_boundary_rejected(self) -> None:
        """Confirmation evidence with close timestamp > evaluation_time rejects with EVIDENCE_NOT_YET_AVAILABLE."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        conf_close = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)  # After 12:00 evaluation boundary
        ev = make_evidence(close_timestamp=conf_close)
        ctx = make_context(evaluation_time=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc))

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE in res.rejection_reasons


class TestAdapterProvenanceAndCompletionIntegrity:
    """Regressions for Directive 3: No candle-open completion fabrication."""

    def test_choch_missing_confirmation_time_is_incomplete_without_open_fallback(self) -> None:
        """CHOCH without confirmation_time preserves close_timestamp=None and is_completed=False without candle-open fallback."""
        open_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        choch = ConfirmedChoch(
            choch_type=ChochType.BEARISH_CHOCH,
            broken_level_type="LAST_SUPPORT",
            broken_level_price=1.1350,
            broken_level_source_index=4,
            c1_candle_index=8,
            c2_candle_index=9,
            c1_chronological_pos=8,
            c2_chronological_pos=9,
            c1_open_time=open_time - timedelta(minutes=5),
            c2_open_time=open_time,
            confirmation_time=None,  # Missing completion time
            point_3_source_index=5,
            point_3_open_time=open_time - timedelta(minutes=20),
            point_3_identified_bar_index=6,
            point_3_identified_at=None,
            zones=(
                ChochZone(ChochZoneType.SBR, 1.1340, 1.1350, False, 4, open_time),
                ChochZone(ChochZoneType.QML_A_PLUS, 1.1360, 1.1370, False, 1, open_time),
                ChochZone(ChochZoneType.DOUBLE_TOP, 1.1380, 1.1390, False, 5, open_time),
            ),
            new_direction=Direction.DOWNWARD,
            restart_reference_candle_index=9,
            restart_reference_open_time=open_time,
            first_eligible_pullback_pos=10,
        )

        ev = adapt_confirmed_choch_to_evidence(
            choch=choch,
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            confirmation_timeframe="M5",
            confirmation_candle_id="EURUSD:M5:20261002T083000Z",
            close_price=1.1320,
            symbol="EURUSD",
            feed_id="FEED_EURUSD_H4",
            sequence_domain=DEFAULT_DOMAIN,
        )

        assert ev.is_completed is False
        assert ev.close_timestamp is None  # Zero fallback to c2_open_time!

        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()
        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_EVIDENCE in res.rejection_reasons

    def test_choch_forming_candle_marked_incomplete(self) -> None:
        """Supplying a forming candle to the adapter marks is_completed=False."""
        open_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        choch = ConfirmedChoch(
            choch_type=ChochType.BEARISH_CHOCH,
            broken_level_type="LAST_SUPPORT",
            broken_level_price=1.1350,
            broken_level_source_index=4,
            c1_candle_index=8,
            c2_candle_index=9,
            c1_chronological_pos=8,
            c2_chronological_pos=9,
            c1_open_time=open_time - timedelta(minutes=5),
            c2_open_time=open_time,
            confirmation_time=open_time + timedelta(minutes=5),
            point_3_source_index=5,
            point_3_open_time=open_time - timedelta(minutes=20),
            point_3_identified_bar_index=6,
            point_3_identified_at=None,
            zones=(
                ChochZone(ChochZoneType.SBR, 1.1340, 1.1350, False, 4, open_time),
                ChochZone(ChochZoneType.QML_A_PLUS, 1.1360, 1.1370, False, 1, open_time),
                ChochZone(ChochZoneType.DOUBLE_TOP, 1.1380, 1.1390, False, 5, open_time),
            ),
            new_direction=Direction.DOWNWARD,
            restart_reference_candle_index=9,
            restart_reference_open_time=open_time,
            first_eligible_pullback_pos=10,
        )

        forming_candle = StrategyCandle(
            index=9,
            open_time=open_time,
            open=1.1350,
            high=1.1360,
            low=1.1310,
            close=1.1320,
            is_forming=True,  # Still forming!
            bar_status="FORMING",
        )

        ev = adapt_confirmed_choch_to_evidence(
            choch=choch,
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            confirmation_timeframe="M5",
            confirmation_candle_id="EURUSD:M5:20261002T083000Z",
            confirming_candle=forming_candle,
            symbol="EURUSD",
            feed_id="FEED_EURUSD_H4",
            sequence_domain=DEFAULT_DOMAIN,
        )
        assert ev.is_completed is False

    def test_choch_confirming_candle_duration_mismatch_rejected(self) -> None:
        """Passing an hourly candle with confirmation_timeframe='M5' raises ValueError."""
        open_time = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
        close_time = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)  # 1 hour duration!
        choch = ConfirmedChoch(
            choch_type=ChochType.BEARISH_CHOCH,
            broken_level_type="LAST_SUPPORT",
            broken_level_price=1.1350,
            broken_level_source_index=4,
            c1_candle_index=8,
            c2_candle_index=9,
            c1_chronological_pos=8,
            c2_chronological_pos=9,
            c1_open_time=open_time - timedelta(hours=1),
            c2_open_time=open_time,
            confirmation_time=close_time,
            point_3_source_index=5,
            point_3_open_time=open_time - timedelta(hours=3),
            point_3_identified_bar_index=6,
            point_3_identified_at=None,
            zones=(
                ChochZone(ChochZoneType.SBR, 1.1340, 1.1350, False, 4, open_time),
                ChochZone(ChochZoneType.QML_A_PLUS, 1.1360, 1.1370, False, 1, open_time),
                ChochZone(ChochZoneType.DOUBLE_TOP, 1.1380, 1.1390, False, 5, open_time),
            ),
            new_direction=Direction.DOWNWARD,
            restart_reference_candle_index=9,
            restart_reference_open_time=open_time,
            first_eligible_pullback_pos=10,
        )

        hourly_candle = StrategyCandle(
            index=9,
            open_time=open_time,
            open=1.1350,
            high=1.1360,
            low=1.1310,
            close=1.1320,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
        )
        object.__setattr__(hourly_candle, "close_time", close_time)

        with pytest.raises(ValueError, match="contradicts declared confirmation_timeframe"):
            adapt_confirmed_choch_to_evidence(
                choch=choch,
                confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
                confirmation_timeframe="M5",  # Mismatch: 1 hour candle passed for M5!
                confirmation_candle_id="EURUSD:M5:20261002T080000Z",
                confirming_candle=hourly_candle,
                symbol="EURUSD",
                feed_id="FEED_EURUSD_H4",
                sequence_domain=DEFAULT_DOMAIN,
            )


class TestBatchConsolidationAndDeterministicOrdering:
    """Regressions for Directive 4: Duplicate deduplication, conflict rejection, and permutation invariance."""

    def test_duplicate_event_with_conflicting_completion_fails_closed(self) -> None:
        """Same event ID with conflicting completion status fails closed as CONFLICTING_IDENTITY in both orders."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev1 = make_evidence(event_id="EVT_DUP", is_completed=True)
        ev2 = make_evidence(event_id="EVT_DUP", is_completed=False)  # Conflicting completion!

        # Forward order
        batch_fwd = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(batch_fwd.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in batch_fwd.pair_results
        )

        # Reversed order
        batch_rev = matcher.match_batch([act], [ev2, ev1], ctx)
        assert len(batch_rev.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in batch_rev.pair_results
        )

    def test_duplicate_event_with_conflicting_unresolved_dependencies_fails_closed(self) -> None:
        """Same event ID with conflicting unresolved dependencies status fails closed in both orders."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev1 = make_evidence(event_id="EVT_DUP2", has_unresolved_dependencies=False)
        ev2 = make_evidence(event_id="EVT_DUP2", has_unresolved_dependencies=True)

        batch_fwd = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(batch_fwd.unique_candidates) == 0

        batch_rev = matcher.match_batch([act], [ev2, ev1], ctx)
        assert len(batch_rev.unique_candidates) == 0

    def test_identical_duplicates_deduplicated_cleanly(self) -> None:
        """Completely identical duplicate events are deduplicated to a single candidate setup."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev1 = make_evidence(event_id="EVT_IDENTICAL")
        ev2 = make_evidence(event_id="EVT_IDENTICAL")  # Exactly identical

        batch_res = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(batch_res.unique_candidates) == 1
        assert batch_res.unique_candidates[0].confirmation_event_ids == ("EVT_IDENTICAL",)

    def test_shared_setup_with_conflicting_prices_fails_closed(self) -> None:
        """Two different confirmation events on the same setup key with conflicting prices reject with CONFLICTING_IDENTITY."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()
        shared_time = datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc)

        ev1 = make_evidence(event_id="EVT_1", close_timestamp=shared_time, close_price=1.1390)
        ev2 = make_evidence(event_id="EVT_2", close_timestamp=shared_time, close_price=1.1395)  # Diff price on same setup!

        batch_res = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(batch_res.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in batch_res.pair_results
        )

    def test_permutation_invariance_of_batch_consolidation(self) -> None:
        """Reversing or shuffling the order of input evidence produces bit-identical unique_candidates."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()
        shared_time = datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc)

        ev_choch = make_evidence(
            event_id="EVT_CHOCH",
            producer_id="CHOCH_DETECTOR_v1",
            pattern_type="CHOCH",
            close_timestamp=shared_time,
            close_price=1.1395,
        )
        ev_iss = make_evidence(
            event_id="EVT_ISS",
            producer_id="ISS_ENGINE_v1",
            pattern_type="ISS",
            close_timestamp=shared_time,
            close_price=1.1395,
        )

        res_forward = matcher.match_batch([act], [ev_choch, ev_iss], ctx)
        res_reverse = matcher.match_batch([act], [ev_iss, ev_choch], ctx)

        assert len(res_forward.unique_candidates) == 1
        assert len(res_reverse.unique_candidates) == 1
        assert res_forward.unique_candidates[0] == res_reverse.unique_candidates[0]
        assert res_forward.unique_candidates[0].is_consolidated is True
        assert res_forward.unique_candidates[0].confirmation_event_ids == ("EVT_CHOCH", "EVT_ISS")
        assert res_forward.unique_candidates[0].confirmation_patterns == ("CHOCH", "ISS")

    def test_deterministic_matching_independent_of_wall_clock(self) -> None:
        """Matching results derive strictly from context.evaluation_time without wall-clock drift."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()
        eval_t = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
        ctx = make_context(evaluation_time=eval_t)

        res1 = matcher.match(act, ev, ctx)
        res2 = matcher.match(act, ev, ctx)

        assert res1.evaluated_at == eval_t
        assert res1 == res2


class TestCandleDerivedContinuousDetection:
    """Exact real-candle tests validating continuous pre-tap CHOCH and authoritative/blocked ISS."""

    @pytest.fixture
    def choch_fixtures(self) -> Dict[str, Any]:
        p = Path(__file__).parent / "fixtures" / "choch_acceptance.json"
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)["fixtures"]

    @pytest.fixture
    def iss_fixtures(self) -> Dict[str, Any]:
        p = Path(__file__).parent / "fixtures" / "iss_acceptance.json"
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)["fixtures"]

    def test_actual_candle_derived_choch_pattern_pre_tap_formation_post_tap_completion(
        self, choch_fixtures: Dict[str, Any]
    ) -> None:
        """Demonstrates genuine candle-derived CHOCH pattern beginning before activation tap and completing afterward.

        CHOCH pattern operates on H1 candles: D1 source -> H1 confirmation (§6).
        CHOCH starts forming at candle 1 / 4 / 5 (Point 3).
        TJL activation tap occurs at candle 7 (before CHOCH confirmation at candle 9).
        Continuous CHOCH detector processes candles without restarting at the tap.
        Adapter translates ConfirmedChoch into ConfirmationEvidenceRecord.
        Matcher validates the association and produces CandidateSetupRecord.
        """
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        config = MSMConfig(start_candle_time=start_time, direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])

        assert len(coordinator.confirmed_choch_events) == 1
        choch = coordinator.confirmed_choch_events[0]
        assert choch.choch_type == ChochType.BEARISH_CHOCH
        assert choch.c2_candle_index == 9

        # Tap occurs at candle 7 (after Point 3 at candle 5, before CHOCH confirmation at candle 9)
        tap_candle = fix["candles"][7]
        tap_time = datetime.fromisoformat(tap_candle["time"]).astimezone(timezone.utc)
        conf_close = choch.confirmation_time or datetime.fromisoformat(fix["candles"][9]["close_time"]).astimezone(timezone.utc)
        assert tap_time < conf_close

        # D1 source timeframe mapping to H1 confirmation (§6)
        act = make_activation(
            source_timeframe="D1",
            confirmation_timeframe="H1",
            first_touch_time=tap_time,
            role="TJL1",
        )
        mem = make_member(source_timeframe="D1", role="TJL1", direction=Direction.DOWNWARD)

        evidence = adapt_confirmed_choch_to_evidence(
            choch=choch,
            confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
            confirmation_timeframe="H1",
            confirmation_candle_id="EURUSD:H1:20261002T160000Z",
            close_price=1.1000,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
            feed_id="FEED_EURUSD_H4",
            sequence_domain=DEFAULT_DOMAIN,
        )

        matcher = ConfirmationMatcher()
        ctx = make_context(
            members={mem.member_key: mem},
            expected_config="CONF_CFG_EURUSD_H1_v1",
            evaluation_time=datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc),
        )

        res = matcher.match(act, evidence, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.entry_reference_price == 1.1000

    def test_actual_candle_derived_iss_authoritative_matching_and_unresolved_blocking(
        self, iss_fixtures: Dict[str, Any]
    ) -> None:
        """Validates candle-derived ISS: authoritative 2-candle pullback matches; unresolved multi-candle blocks fail-closed."""
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"]).astimezone(timezone.utc)
        engine = ISSEngine(ISSConfig(main_direction=Direction.UPWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap.confirmed_events) == 1
        iss_event = snap.confirmed_events[0]

        conf_time = iss_event.confirmation_time or datetime.fromisoformat(fix["candles"][20]["close_time"]).astimezone(timezone.utc)
        tap_time = datetime.fromisoformat(fix["candles"][15]["time"]).astimezone(timezone.utc)
        assert tap_time < conf_time

        # D1 source -> H1 confirmation
        act = make_activation(
            source_timeframe="D1",
            confirmation_timeframe="H1",
            first_touch_time=tap_time,
            role="TJL2_A_PLUS",
        )
        mem = make_member(source_timeframe="D1", role="TJL2_A_PLUS", direction=Direction.DOWNWARD)

        # 1. Authoritative ISS evidence matches
        ev_auth = adapt_confirmed_iss_to_evidence(
            iss=iss_event,
            confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
            confirmation_timeframe="H1",
            confirmation_candle_id="EURUSD:H1:20261001T210000Z",
            close_price=1.112,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
            feed_id="FEED_EURUSD_H4",
            sequence_domain=DEFAULT_DOMAIN,
            has_unresolved_dependencies=False,
        )

        matcher = ConfirmationMatcher()
        ctx = make_context(
            members={mem.member_key: mem},
            expected_config="CONF_CFG_EURUSD_H1_v1",
            evaluation_time=datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc),
        )

        res_auth = matcher.match(act, ev_auth, ctx)
        assert res_auth.status == ConfirmationMatchStatus.MATCHED
        assert res_auth.candidate_record is not None
        assert res_auth.candidate_record.signal_side == "SELL"

        # 2. Unresolved ISS evidence blocks fail-closed
        ev_unres = adapt_confirmed_iss_to_evidence(
            iss=iss_event,
            confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
            confirmation_timeframe="H1",
            confirmation_candle_id="EURUSD:H1:20261001T210000Z",
            close_price=1.112,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
            feed_id="FEED_EURUSD_H4",
            sequence_domain=DEFAULT_DOMAIN,
            has_unresolved_dependencies=True,  # Multi-candle pullback unresolved
        )

        res_unres = matcher.match(act, ev_unres, ctx)
        assert res_unres.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP in res_unres.rejection_reasons
