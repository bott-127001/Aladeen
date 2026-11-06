"""Authoritative tests for Milestone 31 Offline Confirmation-to-Activation Matcher.

Scope & Design Boundary:
-------------------------
- Pure mathematical, typing, and domain matching tests for offline confirmation monitor.
- Independent of MT5, Dash, Plotly, network, broker connection, and live storage.
- Comprehensive coverage of:
  * Authoritative matching context and fail-closed boundaries.
  * Known source availability and pre-availability touch gating.
  * Unresolved source calculation isolation (affected member blocks, independent members match).
  * Physical level identity and metadata consistency (feed, timeframe, side, line geometry).
  * Confirming candle stream authority (open, close, index, duration, exact completion price).
  * Rejection of arbitrary caller prices and missing structural dependencies.
  * Complete duplicate equality semantics and permutation invariance under batch consolidation.
  * Continuous pre-tap CHOCH pattern detection and authoritative ISS matching.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import permutations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
)
from aladeen.strategy.choch_detector import ChochDetector
from aladeen.strategy.choch_types import (
    ChochSnapshot,
    ChochType,
    ChochZone,
    ChochZoneType,
    ConfirmedChoch,
)
from aladeen.strategy.confirmation_adapters import (
    adapt_confirmed_choch_to_evidence,
    adapt_confirmed_iss_to_evidence,
)
from aladeen.strategy.confirmation_batch_consolidator import ConfirmationBatchConsolidator
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher, MatchingContext
from aladeen.strategy.confirmation_pair_matcher import ConfirmationPairMatcher
from aladeen.strategy.confirmation_types import (
    BatchMatchResult,
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
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
    eligibility_available_time: Optional[datetime] = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
    is_line: bool = False,
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
        is_line=is_line,
        direction=direction,
        level_id=level_id,
        eligibility_available_time=eligibility_available_time,
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
    provenance_type: EvidenceProvenanceType = EvidenceProvenanceType.DETECTOR_CONFIRMED,
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
        provenance_type=provenance_type,
    )


def make_context(
    members: Optional[Dict[str, SourceMemberReference]] = None,
    evaluation_time: datetime = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
    expected_config: str = "CONF_CFG_EURUSD_M5_v1",
    expected_basis: PriceBasis = PriceBasis.BID,
    matching_domain: SequenceDomain = DEFAULT_DOMAIN,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    touch_evidence: Optional[Dict[str, TouchSequenceEvidence]] = None,
    source_unresolved_members: Optional[List[str]] = None,
    source_unresolved_sets: Optional[List[str]] = None,
) -> MatchingContext:
    if members is None:
        m = make_member()
        members = {m.member_key: m}
    return MatchingContext(
        domain_session_id="SESS_20261002_001",
        revision_id="REV_001",
        expected_price_basis=expected_basis,
        expected_confirmation_config_id=expected_config,
        matching_sequence_domain=matching_domain,
        evaluation_time=evaluation_time,
        current_members=members,
        coverage_status=coverage_status,
        touch_sequence_evidence=touch_evidence,
        source_unresolved_members=frozenset(source_unresolved_members or []),
        source_unresolved_sets=frozenset(source_unresolved_sets or []),
    )


def make_test_choch(
    event_id: str = "CHOCH_TEST_01",
    open_time: datetime = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
    confirmation_time: Optional[datetime] = datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc),
    choch_type: ChochType = ChochType.BEARISH_CHOCH,
    broken_level_price: float = 1.1350,
    point_3_source_index: int = 5,
    c1_candle_index: int = 8,
    c2_candle_index: int = 9,
) -> ConfirmedChoch:
    return ConfirmedChoch(
        event_id=event_id,
        choch_type=choch_type,
        broken_level_type="LAST_SUPPORT",
        broken_level_price=broken_level_price,
        broken_level_source_index=4,
        c1_candle_index=c1_candle_index,
        c2_candle_index=c2_candle_index,
        c1_chronological_pos=c1_candle_index,
        c2_chronological_pos=c2_candle_index,
        c1_open_time=open_time - timedelta(minutes=5),
        c2_open_time=open_time,
        confirmation_time=confirmation_time,
        point_3_source_index=point_3_source_index,
        point_3_open_time=open_time - timedelta(minutes=20),
        point_3_identified_bar_index=6,
        point_3_identified_at=None,
        zones=(
            ChochZone(ChochZoneType.SBR, 1.1340, 1.1350, False, 4, open_time),
            ChochZone(ChochZoneType.QML_A_PLUS, 1.1360, 1.1370, False, 1, open_time),
            ChochZone(ChochZoneType.DOUBLE_TOP, 1.1380, 1.1390, False, 5, open_time),
        ),
        new_direction=Direction.DOWNWARD,
        restart_reference_candle_index=c2_candle_index,
        restart_reference_open_time=open_time,
        first_eligible_pullback_pos=c2_candle_index + 1,
    )


def make_test_iss(
    candidate_id: str = "ISS_TEST_01",
    confirmation_candle_index: int = 20,
    confirmation_time: Optional[datetime] = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc),
    completion_close_price: float = 1.1120,
    main_direction: Direction = Direction.UPWARD,
) -> ConfirmedISSEvent:
    return ConfirmedISSEvent(
        candidate_id=candidate_id,
        main_direction=main_direction,
        confirmation_candle_index=confirmation_candle_index,
        confirmation_time=confirmation_time,
        completion_close_price=completion_close_price,
        captured_boundary=FrozenBoundary(
            min_price=1.1000,
            max_price=1.1200,
            main_level_2_price=1.1050,
            main_level_3_price=1.1150,
            frozen_at_candle_index=10,
        ),
        internal_points=(
            InternalPoint(
                point_number=1,
                role="CL1",
                source_candle_index=10,
                candle_open_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
                body_edge_price=1.1400,
                is_confirmed=True,
                identified_bar_index=11,
            ),
            InternalPoint(
                point_number=2,
                role="CH1",
                source_candle_index=12,
                candle_open_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
                body_edge_price=1.1520,
                is_confirmed=True,
                identified_bar_index=13,
            ),
            InternalPoint(
                point_number=3,
                role="CL2",
                source_candle_index=14,
                candle_open_time=datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc),
                body_edge_price=1.1250,
                is_confirmed=True,
                identified_bar_index=15,
            ),
            InternalPoint(
                point_number=4,
                role="CH2",
                source_candle_index=16,
                candle_open_time=datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc),
                body_edge_price=1.1320,
                is_confirmed=True,
                identified_bar_index=17,
            ),
            InternalPoint(
                point_number=5,
                role="TENTATIVE_LOW",
                source_candle_index=18,
                candle_open_time=datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc),
                body_edge_price=1.1080,
                is_confirmed=True,
                identified_bar_index=19,
            ),
        ),
        level_3_zone=ISSZone(
            zone_type=ISSZoneType.RBS,
            lower_price=1.1080,
            upper_price=1.1100,
            is_line=False,
            source_candle_index=5,
            source_candle_open_time=datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc),
            source_point_number=3,
            source_point_role="L3",
        ),
        level_4_zone=ISSZone(
            zone_type=ISSZoneType.BUYING_A_PLUS,
            lower_price=1.1120,
            upper_price=1.1140,
            is_line=False,
            source_candle_index=7,
            source_candle_open_time=datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc),
            source_point_number=4,
            source_point_role="L4",
        ),
    )


@pytest.fixture
def choch_fixtures() -> Dict[str, Any]:
    p = Path("tests/fixtures/choch_acceptance.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def iss_fixtures() -> Dict[str, Any]:
    p = Path("tests/fixtures/iss_acceptance.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


class TestAuthoritativeMatchingAuthority:
    """Verifies that matching context is fully authoritative and fail-closed."""

    @pytest.mark.parametrize(
        "source_tf,conf_tf,member_dir,ev_dir,expected_side",
        [
            ("D1", "H1", Direction.UPWARD, Direction.UPWARD, "BUY"),
            ("D1", "H1", Direction.DOWNWARD, Direction.DOWNWARD, "SELL"),
            ("H4", "M5", Direction.UPWARD, Direction.UPWARD, "BUY"),
            ("H4", "M5", Direction.DOWNWARD, Direction.DOWNWARD, "SELL"),
            ("H1", "M1", Direction.UPWARD, Direction.UPWARD, "BUY"),
            ("H1", "M1", Direction.DOWNWARD, Direction.DOWNWARD, "SELL"),
        ],
    )
    def test_bullish_bearish_and_all_three_timeframe_mappings(
        self,
        source_tf: str,
        conf_tf: str,
        member_dir: Direction,
        ev_dir: Direction,
        expected_side: str,
    ) -> None:
        """Validates Bullish and Bearish matching across all 3 MTF pairs."""
        matcher = ConfirmationMatcher()
        cfg_id = f"CONF_CFG_{conf_tf}"
        act = make_activation(
            source_timeframe=source_tf,
            confirmation_timeframe=conf_tf,
            role="TJL2_A_PLUS",
        )
        mem = make_member(
            source_timeframe=source_tf,
            role="TJL2_A_PLUS",
            direction=member_dir,
        )
        ev = make_evidence(
            confirmation_timeframe=conf_tf,
            confirmation_config_id=cfg_id,
            direction=ev_dir,
        )
        ctx = make_context(
            members={mem.member_key: mem},
            expected_config=cfg_id,
        )

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        assert res.candidate_record.signal_side == expected_side
        assert res.candidate_record.source_timeframe == source_tf
        assert res.candidate_record.confirmation_timeframe == conf_tf

    def test_missing_current_members_map_blocks_with_authority_error(self) -> None:
        """Context lacking current_members raises TypeError at instantiation."""
        with pytest.raises(TypeError, match="current_members must be a Mapping"):
            MatchingContext(
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PriceBasis.BID,
                expected_confirmation_config_id="CONF_CFG_01",
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
                current_members=None,  # type: ignore[arg-type]
            )

    def test_member_absent_from_current_members_fails_closed(self) -> None:
        """Activation whose member_key is not in current_members rejects with MEMBERSHIP_CANCELLED_OR_REPLACED."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()
        ctx = make_context(members={})  # Empty active members

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res.rejection_reasons

    @pytest.mark.parametrize(
        "field_name,wrong_value",
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
        self, field_name: str, wrong_value: Any
    ) -> None:
        """Any discrepancy between ActivationRecord and registered SourceMemberReference rejects fail-closed."""
        matcher = ConfirmationMatcher()
        act_kwargs: Dict[str, Any] = {field_name: wrong_value}
        act = make_activation(**act_kwargs)
        mem = make_member()
        ev = make_evidence()
        ctx = make_context(members={mem.member_key: mem})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert (
            ConfirmationRejectionReason.CONTEXT_MISMATCH in res.rejection_reasons
            or ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res.rejection_reasons
        )

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

    def test_physical_level_metadata_mismatch_fails_closed(self) -> None:
        """Physical level metadata contradicting member context rejects with PHYSICAL_LEVEL_METADATA_MISMATCH."""
        matcher = ConfirmationMatcher()
        ev = make_evidence()

        # 1. Contradictory feed in level_id relative to context feed
        wrong_level = StableLevelId(
            symbol_feed_id="FEED_OTHER_H4",
            source_timeframe="H4",
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
            side="HIGH",
        )
        act = make_activation(level_id=wrong_level)
        mem = make_member(level_id=wrong_level)
        ctx = make_context(
            members={mem.member_key: mem},
            matching_domain=DEFAULT_DOMAIN,  # feed is FEED_EURUSD_H4, not FEED_OTHER_H4
        )
        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PHYSICAL_LEVEL_METADATA_MISMATCH in res.rejection_reasons

        # 2. Level timeframe mismatch: member is H4, but level_id says H1
        tf_level = StableLevelId(
            symbol_feed_id="FEED_EURUSD_H4",
            source_timeframe="H1",  # Contradicts member source_timeframe H4
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
            side="HIGH",
        )
        act_tf = make_activation(level_id=tf_level)
        mem_tf = make_member(level_id=tf_level, source_timeframe="H4")
        ctx_tf = make_context(members={mem_tf.member_key: mem_tf})
        res_tf = matcher.match(act_tf, ev, ctx_tf)
        assert res_tf.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PHYSICAL_LEVEL_METADATA_MISMATCH in res_tf.rejection_reasons

        # 3. Level side mismatch: member is HIGH, but level_id says LOW
        side_level = StableLevelId(
            symbol_feed_id="FEED_EURUSD_H4",
            source_timeframe="H4",
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
            side="LOW",  # Contradicts member side HIGH
        )
        act_side = make_activation(level_id=side_level)
        mem_side = make_member(level_id=side_level, side="HIGH")
        ctx_side = make_context(members={mem_side.member_key: mem_side})
        res_side = matcher.match(act_side, ev, ctx_side)
        assert res_side.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PHYSICAL_LEVEL_METADATA_MISMATCH in res_side.rejection_reasons

    def test_member_unknown_eligibility_available_time_fails_closed(self) -> None:
        """Member with unknown eligibility_available_time rejects fail-closed."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        mem = make_member(eligibility_available_time=None)
        ev = make_evidence()
        ctx = make_context(members={mem.member_key: mem})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_ELIGIBILITY_AVAILABLE_TIME in res.rejection_reasons

    def test_activation_touch_before_member_eligibility_fails_closed(self) -> None:
        """Activation first touch occurring before member eligibility rejects with TOUCH_BEFORE_ELIGIBILITY."""
        matcher = ConfirmationMatcher()
        act = make_activation(first_touch_time=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc))
        mem = make_member(eligibility_available_time=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))
        ev = make_evidence()
        ctx = make_context(members={mem.member_key: mem})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.TOUCH_BEFORE_ELIGIBILITY in res.rejection_reasons

    def test_activation_under_unresolved_source_structure_fails_closed_locally(self) -> None:
        """Pending activation under unresolved source structure blocks locally; independent members match."""
        matcher = ConfirmationMatcher()

        # Member A: under unresolved source structure
        mem_a = make_member(role="TJL1")
        act_a = make_activation(
            activation_id="ACT_A",
            role="TJL1",
        )

        # Member B: independent resolved structure
        mem_b = make_member(
            set_id="SET_B",
            role="TJL2_A_PLUS",
            side="LOW",
            lower_edge=1.1200,
            upper_edge=1.1220,
            direction=Direction.UPWARD,
        )
        act_b = make_activation(
            activation_id="ACT_B",
            set_id="SET_B",
            role="TJL2_A_PLUS",
            lower_edge=1.1200,
            upper_edge=1.1220,
            level_id=mem_b.level_id,
        )

        ev = make_evidence()
        ctx = make_context(
            members={mem_a.member_key: mem_a, mem_b.member_key: mem_b},
            source_unresolved_members=[mem_a.member_key],  # Only Member A is unresolved
        )

        # Act A fails closed as BLOCKED
        res_a = matcher.match(act_a, ev, ctx)
        assert res_a.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY in res_a.rejection_reasons

        # Act B matches cleanly
        res_b = matcher.match(act_b, ev, ctx)
        assert res_b.status == ConfirmationMatchStatus.MATCHED

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
        """General detector event (activation_id=None, source_member_key=None) matches multiple eligible activations."""
        matcher = ConfirmationMatcher()
        act1 = make_activation(
            activation_id="ACT_GEN_01",
            generation_seq=1,
            role="TJL1",
        )
        act2 = make_activation(
            activation_id="ACT_GEN_02",
            generation_seq=2,
            role="TJL1",
        )
        ev = make_evidence(activation_id=None, source_member_key=None)
        mem = make_member(role="TJL1")
        ctx = make_context(members={mem.member_key: mem})

        res1 = matcher.match(act1, ev, ctx)
        res2 = matcher.match(act2, ev, ctx)
        assert res1.status == ConfirmationMatchStatus.MATCHED
        assert res2.status == ConfirmationMatchStatus.MATCHED


class TestDomainScopedCausalityAndAvailability:
    """Verifies domain-scoped sequence comparison and evaluation availability boundary."""

    def test_cross_domain_sequence_comparison_rejected(self) -> None:
        """Comparing sequence numbers across different sequence domains rejects fail-closed."""
        matcher = ConfirmationMatcher()
        touch_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        act = make_activation(first_touch_time=touch_time)

        other_domain = SequenceDomain(feed_id="FEED_EURUSD_M5", run_id="RUN_DIFF")
        ev = make_evidence(
            close_timestamp=touch_time,
            sequence_domain=other_domain,
            sequence_ref=200,
        )
        touch_seq = TouchSequenceEvidence(sequence_domain=DEFAULT_DOMAIN, sequence_ref=100)
        ctx = make_context(
            touch_evidence={act.activation_id: touch_seq},
            matching_domain=DEFAULT_DOMAIN,
        )

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED in res.rejection_reasons

    def test_compatible_domain_sequence_comparison_case_b_valid(self) -> None:
        """When sequence domains match context, Case B tie resolution functions correctly."""
        matcher = ConfirmationMatcher()
        touch_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        act = make_activation(first_touch_time=touch_time)

        # 1. Confirmation sequence > touch sequence -> Valid Case B association
        ev_valid = make_evidence(
            close_timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=150,
        )
        touch_seq = TouchSequenceEvidence(sequence_domain=DEFAULT_DOMAIN, sequence_ref=100)
        ctx = make_context(
            touch_evidence={act.activation_id: touch_seq},
            matching_domain=DEFAULT_DOMAIN,
        )

        res_valid = matcher.match(act, ev_valid, ctx)
        assert res_valid.status == ConfirmationMatchStatus.MATCHED

        # 2. Confirmation sequence <= touch sequence -> Rejected
        ev_pre = make_evidence(
            close_timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=90,
        )
        res_pre = matcher.match(act, ev_pre, ctx)
        assert res_pre.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_pre.rejection_reasons

    def test_future_evidence_beyond_evaluation_boundary_rejected(self) -> None:
        """Confirmation evidence with close_timestamp > context.evaluation_time rejects fail-closed."""
        matcher = ConfirmationMatcher()
        eval_time = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
        future_time = datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc)

        act = make_activation(first_touch_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        ev_future = make_evidence(close_timestamp=future_time)
        ctx = make_context(evaluation_time=eval_time)

        res = matcher.match(act, ev_future, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE in res.rejection_reasons


class TestAdapterProvenanceAndCompletionIntegrity:
    """Verifies candle-stream authority, duration integrity, and rejection of arbitrary inputs."""

    def test_choch_missing_confirmation_time_is_incomplete_without_open_fallback(self) -> None:
        """When CHOCH lacks confirmation_time, adapter sets close_timestamp=None and is_completed=False."""
        choch = make_test_choch(event_id="CHOCH_INCOMPLETE_01", confirmation_time=None)

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
        assert ev.close_timestamp is None

        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()
        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_EVIDENCE in res.rejection_reasons

    def test_choch_forming_candle_marked_incomplete(self) -> None:
        """Supplying a forming candle to the adapter marks is_completed=False."""
        open_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        choch = make_test_choch(open_time=open_time)

        forming_candle = StrategyCandle(
            index=9,
            open_time=open_time,
            open=1.1340,
            high=1.1345,
            low=1.1310,
            close=1.1320,
            is_forming=True,
            bar_status="FORMING",
            close_time=open_time + timedelta(minutes=5),
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
        close_time = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        choch = make_test_choch(open_time=open_time, confirmation_time=close_time)

        hourly_candle = StrategyCandle(
            index=9,
            open_time=open_time,
            open=1.1340,
            high=1.1345,
            low=1.1310,
            close=1.1320,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=close_time,
        )

        with pytest.raises(ValueError, match="contradicts declared confirmation_timeframe"):
            adapt_confirmed_choch_to_evidence(
                choch=choch,
                confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
                confirmation_timeframe="M5",
                confirmation_candle_id="EURUSD:M5:20261002T080000Z",
                confirming_candle=hourly_candle,
                symbol="EURUSD",
                feed_id="FEED_EURUSD_H4",
                sequence_domain=DEFAULT_DOMAIN,
            )

    def test_choch_confirming_candle_open_and_close_time_mismatches_fail_closed(self) -> None:
        """Confirming candle with wrong open_time or close_time raises ValueError."""
        open_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        close_time = datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc)
        choch = make_test_choch(open_time=open_time, confirmation_time=close_time)

        # 1. Open time mismatch
        candle_wrong_open = StrategyCandle(
            index=9,
            open_time=open_time + timedelta(minutes=1),
            open=1.1340,
            high=1.1345,
            low=1.1310,
            close=1.1320,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=close_time + timedelta(minutes=1),
        )
        with pytest.raises(ValueError, match="does not match CHOCH c2_open_time"):
            adapt_confirmed_choch_to_evidence(
                choch=choch,
                confirmation_config_id="CONF_CFG_01",
                confirmation_timeframe="M5",
                confirmation_candle_id="CANDLE_01",
                confirming_candle=candle_wrong_open,
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
            )

        # 2. Close time mismatch
        candle_wrong_close = StrategyCandle(
            index=9,
            open_time=open_time,
            open=1.1340,
            high=1.1345,
            low=1.1310,
            close=1.1320,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=close_time + timedelta(minutes=1),
        )
        with pytest.raises(ValueError, match="does not match candle close_time|contradicts declared"):
            adapt_confirmed_choch_to_evidence(
                choch=choch,
                confirmation_config_id="CONF_CFG_01",
                confirmation_timeframe="M5",
                confirmation_candle_id="CANDLE_01",
                confirming_candle=candle_wrong_close,
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
            )

    def test_choch_caller_price_conflicts_with_candle_close_fails_closed(self) -> None:
        """Caller supplying a close_price that contradicts the confirming candle close raises ValueError."""
        open_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        close_time = datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc)
        choch = make_test_choch(open_time=open_time, confirmation_time=close_time)

        candle = StrategyCandle(
            index=9,
            open_time=open_time,
            open=1.1340,
            high=1.1345,
            low=1.1310,
            close=1.1320,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=close_time,
        )

        with pytest.raises(ValueError, match="conflicts with candle close price"):
            adapt_confirmed_choch_to_evidence(
                choch=choch,
                confirmation_config_id="CONF_CFG_01",
                confirmation_timeframe="M5",
                confirmation_candle_id="CANDLE_01",
                confirming_candle=candle,
                close_price=1.1399,
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
            )

    def test_choch_completed_detector_evidence_without_candle_fails_closed(self) -> None:
        """Claiming completed detector confirmation without supplying confirming_candle raises ValueError."""
        choch = make_test_choch()

        with pytest.raises(ValueError, match="Completed detector confirmation requires authoritative confirming_candle"):
            adapt_confirmed_choch_to_evidence(
                choch=choch,
                confirmation_config_id="CONF_CFG_01",
                confirmation_timeframe="M5",
                confirmation_candle_id="CANDLE_01",
                confirming_candle=None,
                close_price=1.1320,
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
                provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
            )

    def test_iss_candle_close_conflicts_with_event_completion_price_fails_closed(self) -> None:
        """ISS confirming candle close contradicting iss.completion_close_price raises ValueError."""
        open_time = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
        close_time = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)
        iss = make_test_iss(
            confirmation_candle_index=20,
            confirmation_time=close_time,
            completion_close_price=1.1120,
        )

        candle_wrong_close = StrategyCandle(
            index=20,
            open_time=open_time,
            open=1.1100,
            high=1.1180,
            low=1.1090,
            close=1.1175,
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=close_time,
        )

        with pytest.raises(ValueError, match="contradicts ISS completion_close_price"):
            adapt_confirmed_iss_to_evidence(
                iss=iss,
                confirmation_config_id="CONF_CFG_H1_01",
                confirmation_timeframe="H1",
                confirmation_candle_id="CANDLE_20",
                confirming_candle=candle_wrong_close,
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
            )

    def test_choch_missing_structural_dependencies_rejected_at_adapter(self) -> None:
        """ConfirmedChoch with missing/placeholder structural fields raises ValueError at adaptation."""
        choch_bad_p3 = make_test_choch(point_3_source_index=-1)

        with pytest.raises(ValueError, match="missing valid point_3 structural dependency"):
            adapt_confirmed_choch_to_evidence(
                choch=choch_bad_p3,
                confirmation_config_id="CONF_CFG_01",
                confirmation_timeframe="M5",
                confirmation_candle_id="CANDLE_01",
                close_price=1.1320,
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
            )

    def test_evidence_placeholder_structural_references_rejected(self) -> None:
        """ConfirmationEvidenceRecord containing placeholder references raises ValueError."""
        with pytest.raises(ValueError, match="Invalid structural dependency reference"):
            ConfirmationEvidenceRecord(
                event_id="EVT_BAD_REF",
                producer_id="DETECTOR",
                pattern_type="CHOCH",
                confirmation_config_id="CFG_01",
                confirmation_timeframe="M5",
                confirmation_candle_id="CANDLE_01",
                symbol="EURUSD",
                feed_id="FEED_01",
                sequence_domain=DEFAULT_DOMAIN,
                close_price=1.1320,
                price_basis=PriceBasis.BID,
                direction=Direction.UPWARD,
                structural_dependency_references=("POINT_3_INDEX:None",),
            )


class TestBatchConsolidationAndDeterministicOrdering:
    """Verifies complete duplicate equality, shared-setup conflict gating, and permutation invariance."""

    def test_duplicate_event_with_conflicting_completion_fails_closed(self) -> None:
        """Duplicate event with differing completion status fails closed with CONFLICTING_IDENTITY in all permutations."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev_complete = make_evidence(
            event_id="DUP_EVT_01",
            close_timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc),
            is_completed=True,
        )
        ev_incomplete = make_evidence(
            event_id="DUP_EVT_01",
            close_timestamp=None,
            is_completed=False,
        )

        res_fwd = matcher.match_batch([act], [ev_complete, ev_incomplete], ctx)
        assert len(res_fwd.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in res_fwd.pair_results
        )

        res_rev = matcher.match_batch([act], [ev_incomplete, ev_complete], ctx)
        assert len(res_rev.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in res_rev.pair_results
        )

    def test_duplicate_event_with_conflicting_unresolved_dependencies_fails_closed(self) -> None:
        """Duplicate event differing in unresolved dependencies fails closed as CONFLICTING_IDENTITY."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev1 = make_evidence(event_id="DUP_UNRES_01", has_unresolved_dependencies=False)
        ev2 = make_evidence(event_id="DUP_UNRES_01", has_unresolved_dependencies=True)

        res = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(res.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in res.pair_results
        )

    def test_identical_duplicates_deduplicated_cleanly(self) -> None:
        """Identical duplicates with exact field equality are deduplicated without conflict."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev1 = make_evidence(event_id="IDENT_01", close_price=1.1390)
        ev2 = make_evidence(event_id="IDENT_01", close_price=1.1390)

        res = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(res.unique_candidates) == 1
        assert res.unique_candidates[0].confirmation_event_ids == ("IDENT_01",)

    def test_shared_setup_with_conflicting_prices_fails_closed(self) -> None:
        """Shared setup key with conflicting prices fails closed with CONFLICTING_IDENTITY."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev1 = make_evidence(event_id="EVT_A", close_price=1.1350)
        ev2 = make_evidence(event_id="EVT_B", close_price=1.1355)

        res = matcher.match_batch([act], [ev1, ev2], ctx)
        assert len(res.unique_candidates) == 0
        assert any(
            ConfirmationRejectionReason.CONFLICTING_IDENTITY in r.rejection_reasons
            for r in res.pair_results
        )

    def test_permutation_invariance_of_batch_consolidation(self) -> None:
        """Batch consolidation produces strictly identical results across all input permutations."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ctx = make_context()

        ev_choch = make_evidence(
            event_id="EVT_CHOCH",
            pattern_type="CHOCH",
            close_price=1.1350,
        )
        ev_iss = make_evidence(
            event_id="EVT_ISS",
            pattern_type="ISS",
            close_price=1.1350,
        )

        res1 = matcher.match_batch([act], [ev_choch, ev_iss], ctx)
        res2 = matcher.match_batch([act], [ev_iss, ev_choch], ctx)

        assert res1.unique_candidates == res2.unique_candidates
        assert res1.pair_results == res2.pair_results
        assert len(res1.unique_candidates) == 1
        cand = res1.unique_candidates[0]
        assert cand.is_consolidated is True
        assert cand.confirmation_patterns == ("CHOCH", "ISS")

    def test_batch_consolidation_full_permutation_invariance_and_conflict_isolation(self) -> None:
        """Verifies multi-activation multi-evidence permutations isolate conflicts and retain valid setups."""
        matcher = ConfirmationMatcher()

        # Act 1 (Valid)
        mem1 = make_member(role="TJL1")
        act1 = make_activation(
            activation_id="ACT_01",
            role="TJL1",
        )

        # Act 2 (Different Set)
        mem2 = make_member(
            set_id="SET_02",
            role="TJL2_A_PLUS",
            lower_edge=1.1200,
            upper_edge=1.1220,
        )
        act2 = make_activation(
            activation_id="ACT_02",
            set_id="SET_02",
            role="TJL2_A_PLUS",
            lower_edge=1.1200,
            upper_edge=1.1220,
            level_id=mem2.level_id,
        )

        ctx = make_context(members={mem1.member_key: mem1, mem2.member_key: mem2})

        ev_valid = make_evidence(event_id="EVT_VALID_01", close_price=1.1350)
        ev_conflict_a = make_evidence(event_id="EVT_CONF_01", close_price=1.1350, is_completed=True)
        ev_conflict_b = make_evidence(event_id="EVT_CONF_01", close_price=1.1350, is_completed=False)

        ev_inputs = [ev_valid, ev_conflict_a, ev_conflict_b]

        reference_result = None
        for p in permutations(ev_inputs):
            res = matcher.match_batch([act1, act2], list(p), ctx)
            if reference_result is None:
                reference_result = res
            else:
                assert res.unique_candidates == reference_result.unique_candidates
                assert res.pair_results == reference_result.pair_results

    def test_deterministic_matching_independent_of_wall_clock(self) -> None:
        """Deterministic matching output derives strictly from context.evaluation_time."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()

        fixed_time = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        ctx = make_context(evaluation_time=fixed_time)

        res1 = matcher.match(act, ev, ctx)
        res2 = matcher.match(act, ev, ctx)
        assert res1.evaluated_at == fixed_time
        assert res2.evaluated_at == fixed_time
        assert res1 == res2


class TestCandleDerivedContinuousDetection:
    """End-to-end integration tests using genuine candle fixtures demonstrating continuous detection."""

    def test_actual_candle_derived_choch_pattern_pre_tap_formation_post_tap_completion(
        self, choch_fixtures: Dict[str, Any]
    ) -> None:
        """Demonstrates continuous CHOCH detection spanning pre-tap formation through post-tap completion.

        Pattern formation starts at candle 1-5; activation tapped at candle 7; confirmation completes at candle 9.
        Matcher validates the association and produces CandidateSetupRecord.
        """
        fix = choch_fixtures["fixtures"]["choch_bearish_basic_end_to_end"]
        raw_candles = fix["candles"]
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        h1_candles = []
        for i, c in enumerate(raw_candles):
            c_copy = dict(c)
            c_copy["time"] = (base_time + timedelta(hours=i)).isoformat()
            c_copy["close_time"] = (base_time + timedelta(hours=i + 1)).isoformat()
            h1_candles.append(c_copy)

        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(h1_candles)

        assert len(coordinator.confirmed_choch_events) == 1
        choch = coordinator.confirmed_choch_events[0]
        assert choch.choch_type == ChochType.BEARISH_CHOCH
        assert choch.c2_candle_index == 9

        # Tap occurs at candle 7 (after Point 3 at candle 5, before CHOCH confirmation at candle 9)
        tap_time = datetime.fromisoformat(h1_candles[7]["time"]).astimezone(timezone.utc)
        conf_close = choch.confirmation_time or datetime.fromisoformat(h1_candles[9]["close_time"]).astimezone(timezone.utc)
        assert tap_time < conf_close

        # Authoritative confirming candle 9 with full provenance
        confirming_candle = StrategyCandle(
            index=9,
            open_time=datetime.fromisoformat(h1_candles[9]["time"]).astimezone(timezone.utc),
            open=float(h1_candles[9]["open"]),
            high=float(h1_candles[9]["high"]),
            low=float(h1_candles[9]["low"]),
            close=float(h1_candles[9]["close"]),
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=conf_close,
        )

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
            confirmation_candle_id="EURUSD:H1:20261001T100000Z",
            confirming_candle=confirming_candle,
            close_price=1.0850,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
            feed_id="FEED_EURUSD_H4",
            sequence_domain=DEFAULT_DOMAIN,
        )

        matcher = ConfirmationMatcher()
        ctx = make_context(
            members={mem.member_key: mem},
            expected_config="CONF_CFG_EURUSD_H1_v1",
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        )

        res = matcher.match(act, evidence, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.entry_reference_price == 1.0850

    def test_actual_candle_derived_iss_authoritative_matching_and_unresolved_blocking(
        self, iss_fixtures: Dict[str, Any]
    ) -> None:
        """Validates candle-derived ISS: authoritative 2-candle pullback matches; unresolved multi-candle blocks fail-closed."""
        fix = iss_fixtures["fixtures"]["iss_02_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"]).astimezone(timezone.utc)
        engine = ISSEngine(ISSConfig(main_direction=Direction.UPWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap.confirmed_events) == 1
        iss_event = snap.confirmed_events[0]

        c20_raw = fix["candles"][20]
        conf_time = iss_event.confirmation_time or datetime.fromisoformat(c20_raw["close_time"]).astimezone(timezone.utc)
        tap_time = datetime.fromisoformat(fix["candles"][15]["time"]).astimezone(timezone.utc)
        assert tap_time < conf_time

        confirming_candle = StrategyCandle(
            index=20,
            open_time=datetime.fromisoformat(c20_raw["time"]).astimezone(timezone.utc),
            open=float(c20_raw["open"]),
            high=float(c20_raw["high"]),
            low=float(c20_raw["low"]),
            close=float(c20_raw["close"]),
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=conf_time,
        )

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
            confirming_candle=confirming_candle,
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
            confirming_candle=confirming_candle,
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
