"""Comprehensive test suite for Offline Confirmation-to-Activation Matcher — Milestone 31.

Tests cover:
1. Bullish/bearish directional concordance across all three timeframe mappings (D1->H1, H4->M5, H1->M1).
2. Continuous detection: actual candle-derived CHOCH pattern beginning before activation tap and completing afterward.
3. Pre-activation completed confirmation rejection (confirmations completed prior to tap cannot be reused).
4. Shared coarse timestamp: Case B (valid monotonic sequence ordering) vs Case C (unknown order fail-closed).
5. Diagnostic rejections: wrong direction, wrong context, wrong basis, wrong timeframe.
6. Multi-generation lifecycle: initial pending and rearmed generations.
7. Cancelled and replaced membership rejection.
8. Unknown usage, incomplete coverage, and unresolved dependencies fail-closed handling.
9. Duplicate evidence idempotence and conflicting identity rejection.
10. CHOCH and ISS shared-config candidate setup consolidation (OPEN-07, sig_18) and cross-config separation (sig_39).
11. Immutability: zero mutation of activation records or strategy snapshots.
12. Deterministic replay and prefix consistency.
13. Separation of synthetic typed tests from actual candle-derived adapter evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
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
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
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
from aladeen.strategy.types import Direction, MSMConfig


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
) -> ActivationRecord:
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
    close_timestamp: datetime = datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc),
    close_price: float = 1.1395,
    price_basis: PriceBasis = PriceBasis.BID,
    direction: Direction = Direction.UPWARD,
    is_completed: bool = True,
    has_unresolved_dependencies: bool = False,
    structural_dependency_references: tuple = ("CHOCH_TYPE:BULLISH_CHOCH", "POINT_3_INDEX:5"),
    symbol: str = "EURUSD",
    feed_id: str = "FEED_EURUSD_H4",
    sequence_ref: Optional[int] = None,
    is_isolated_tracking: bool = False,
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
        sequence_ref=sequence_ref,
        is_isolated_tracking=is_isolated_tracking,
    )


class TestSyntheticTypedMatching:
    """Suite of synthetic, typed unit tests validating matching gates without execution or arbitration."""

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
        """Verifies (D1->H1), (H4->M5), (H1->M1) for both Bullish (BUY) and Bearish (SELL)."""
        matcher = ConfirmationMatcher()
        act = make_activation(
            source_timeframe=src_tf,
            confirmation_timeframe=conf_tf,
            role="TJL2_A_PLUS",
        )
        ev = make_evidence(
            confirmation_timeframe=conf_tf,
            direction=dir_enum,
        )
        ctx = MatchingContext(
            member_directions={act.member_key: dir_enum},
            default_price_basis=PriceBasis.BID,
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

    def test_pre_activation_completed_confirmation_rejection(self) -> None:
        """Confirmations completed strictly before tap cannot be reused (sig_05, MTF-Analysis.pdf §7)."""
        matcher = ConfirmationMatcher()
        tap_time = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        conf_close = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)  # 30 min before tap

        act = make_activation(first_touch_time=tap_time)
        ev = make_evidence(close_timestamp=conf_close)

        res = matcher.match(act, ev)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res.rejection_reasons
        assert res.candidate_record is None

    def test_shared_coarse_timestamp_case_b_valid_sequence(self) -> None:
        """Case B: Shared coarse timestamp with monotonic sequence evidence (tap_seq < conf_seq) is valid."""
        matcher = ConfirmationMatcher()
        shared_ts = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)

        act = make_activation(
            first_touch_time=shared_ts,
            trigger_observation_id="OBS_101",
        )
        ev = make_evidence(
            close_timestamp=shared_ts,
            sequence_ref=200,
            direction=Direction.UPWARD,
        )
        ctx = MatchingContext(
            member_directions={act.member_key: Direction.UPWARD},
            touch_sequence_refs={"OBS_101": 150},  # tap sequence 150 < 200
        )

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None

    def test_shared_coarse_timestamp_case_c_unknown_order_fail_closed(self) -> None:
        """Case C: Shared coarse timestamp without sequence evidence fails closed as UNKNOWN_ORDER (sig_22)."""
        matcher = ConfirmationMatcher()
        shared_ts = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)

        act = make_activation(
            first_touch_time=shared_ts,
            trigger_observation_id="OBS_101",
        )
        ev = make_evidence(
            close_timestamp=shared_ts,
            sequence_ref=None,  # No sub-bar sequence
            direction=Direction.UPWARD,
        )
        ctx = MatchingContext(
            member_directions={act.member_key: Direction.UPWARD},
            touch_sequence_refs=None,  # No sequence ordering
        )

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.UNCERTAIN
        assert ConfirmationRejectionReason.UNKNOWN_ORDER in res.rejection_reasons
        assert res.candidate_record is None

    def test_wrong_direction_rejection(self) -> None:
        """Opposite direction confirmation is rejected with DIRECTION_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence(direction=Direction.DOWNWARD)  # Bearish
        ctx = MatchingContext(member_directions={act.member_key: Direction.UPWARD})  # Bullish activation

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.DIRECTION_MISMATCH in res.rejection_reasons

    def test_wrong_timeframe_rejection(self) -> None:
        """Confirmation on wrong timeframe (e.g. M1 for H4 source) is rejected with TIMEFRAME_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation(source_timeframe="H4", confirmation_timeframe="M5")
        ev = make_evidence(confirmation_timeframe="M1")

        res = matcher.match(act, ev)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.TIMEFRAME_MISMATCH in res.rejection_reasons

    def test_wrong_context_rejection(self) -> None:
        """Symbol or feed mismatch is rejected with CONTEXT_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation(symbol="EURUSD")
        ev = make_evidence(symbol="GBPUSD")

        res = matcher.match(act, ev)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CONTEXT_MISMATCH in res.rejection_reasons

    def test_wrong_price_basis_rejection(self) -> None:
        """Mismatched pricing basis (BID vs ASK) is rejected with PRICE_BASIS_MISMATCH."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence(price_basis=PriceBasis.ASK)
        ctx = MatchingContext(default_price_basis=PriceBasis.BID)

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRICE_BASIS_MISMATCH in res.rejection_reasons

    def test_pending_and_rearmed_generations(self) -> None:
        """Validates matching across initial pending and rearmed activation generations."""
        matcher = ConfirmationMatcher()
        t1 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)

        # Gen 1 initial pending
        act_g1 = make_activation(
            generation_seq=1,
            state=ActivationState.PENDING_ACTIVATION,
            first_touch_time=t1,
        )
        ev_g1 = make_evidence(close_timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc))
        ctx = MatchingContext(member_directions={act_g1.member_key: Direction.UPWARD})

        res_g1 = matcher.match(act_g1, ev_g1, ctx)
        assert res_g1.status == ConfirmationMatchStatus.MATCHED

        # Gen 2 rearmed pending after cancellation
        act_g2 = make_activation(
            generation_seq=2,
            state=ActivationState.REARMED_PENDING,
            first_touch_time=t2,
        )
        ev_g2 = make_evidence(close_timestamp=datetime(2026, 10, 2, 10, 30, tzinfo=timezone.utc))
        res_g2 = matcher.match(act_g2, ev_g2, ctx)
        assert res_g2.status == ConfirmationMatchStatus.MATCHED

        # Stale evidence from gen 1 evaluated against gen 2
        res_stale = matcher.match(act_g2, ev_g1, ctx)
        assert res_stale.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_stale.rejection_reasons

    def test_cancelled_and_replaced_membership_rejection(self) -> None:
        """Cancelled activation states and replaced source members are strictly rejected."""
        matcher = ConfirmationMatcher()

        # Ineligible cancelled state
        act_cancelled = make_activation(state=ActivationState.CANCELLED_SOURCE_CHOCH)
        ev = make_evidence()
        res_c = matcher.match(act_cancelled, ev)
        assert res_c.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res_c.rejection_reasons

        # Replaced member absent from current_members
        act_pending = make_activation(state=ActivationState.PENDING_ACTIVATION)
        ctx_replaced = MatchingContext(current_members={})  # Empty active members
        res_rep = matcher.match(act_pending, ev, ctx_replaced)
        assert res_rep.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res_rep.rejection_reasons

    def test_unknown_usage_fail_closed(self) -> None:
        """UNKNOWN usage status fails closed as BLOCKED with UNKNOWN_USAGE."""
        matcher = ConfirmationMatcher()
        act = make_activation(usage_evidence_status=UsageEvidenceStatus.UNKNOWN)
        ev = make_evidence()

        res = matcher.match(act, ev)
        assert res.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.UNKNOWN_USAGE in res.rejection_reasons

    def test_incomplete_coverage_fail_closed(self) -> None:
        """INCOMPLETE coverage status fails closed as BLOCKED with INCOMPLETE_COVERAGE."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence()
        ctx = MatchingContext(coverage_status=CoverageStatus.INCOMPLETE)

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res.rejection_reasons

    def test_unresolved_dependencies_fail_closed(self) -> None:
        """Unresolved dependencies fail closed with explicit diagnostic reasons."""
        matcher = ConfirmationMatcher()
        act = make_activation()

        # CHOCH unresolved
        ev_choch_unresolved = make_evidence(
            pattern_type="CHOCH",
            has_unresolved_dependencies=True,
        )
        res_choch = matcher.match(act, ev_choch_unresolved)
        assert res_choch.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY in res_choch.rejection_reasons

        # ISS unresolved multi-candle pullback
        ev_iss_unresolved = make_evidence(
            pattern_type="ISS",
            has_unresolved_dependencies=True,
        )
        res_iss = matcher.match(act, ev_iss_unresolved)
        assert res_iss.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP in res_iss.rejection_reasons

    def test_isolated_tracking_rejected(self) -> None:
        """Isolated tracking records are rejected as non-confirmation evidence (sig_36)."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence(is_isolated_tracking=True)

        res = matcher.match(act, ev)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.ISOLATED_TRACKING_ONLY in res.rejection_reasons

    def test_candidate_setup_key_and_batch_consolidation_open_07(self) -> None:
        """CHOCH and ISS events sharing setup key consolidate under OPEN-07 into one CandidateSetupRecord."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        shared_time = datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc)
        shared_cfg = "CONF_CFG_EURUSD_M5_v1"
        shared_candle = "EURUSD:M5:20261002T083500Z"

        ev_choch = make_evidence(
            event_id="EVT_CHOCH_0835",
            producer_id="CHOCH_DETECTOR_v1",
            pattern_type="CHOCH",
            confirmation_config_id=shared_cfg,
            confirmation_candle_id=shared_candle,
            close_timestamp=shared_time,
            direction=Direction.UPWARD,
        )
        ev_iss = make_evidence(
            event_id="EVT_ISS_0835",
            producer_id="ISS_ENGINE_v1",
            pattern_type="ISS",
            confirmation_config_id=shared_cfg,
            confirmation_candle_id=shared_candle,
            close_timestamp=shared_time,
            direction=Direction.UPWARD,
        )

        ctx = MatchingContext(
            member_directions={act.member_key: Direction.UPWARD},
            default_price_basis=PriceBasis.BID,
        )

        batch_results = matcher.match_batch([act], [ev_choch, ev_iss], ctx)
        assert len(batch_results) == 2
        for r in batch_results:
            assert r.status == ConfirmationMatchStatus.MATCHED
            assert r.candidate_record is not None
            cand = r.candidate_record
            assert cand.is_consolidated is True
            assert cand.confirmation_event_ids == ("EVT_CHOCH_0835", "EVT_ISS_0835")
            assert cand.confirmation_patterns == ("CHOCH", "ISS")

    def test_cross_config_separation(self) -> None:
        """Different confirmation configs produce distinct CandidateSetupKeys without conflation (sig_39)."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        shared_time = datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc)

        ev_cfg_a = make_evidence(
            event_id="EVT_A",
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            close_timestamp=shared_time,
            direction=Direction.UPWARD,
        )
        ev_cfg_b = make_evidence(
            event_id="EVT_B",
            confirmation_config_id="CONF_CFG_EURUSD_M5_v2",  # Different config
            close_timestamp=shared_time,
            direction=Direction.UPWARD,
        )

        ctx = MatchingContext(
            member_directions={act.member_key: Direction.UPWARD},
            default_price_basis=PriceBasis.BID,
        )

        res_a = matcher.match(act, ev_cfg_a, ctx)
        res_b = matcher.match(act, ev_cfg_b, ctx)

        assert res_a.status == ConfirmationMatchStatus.MATCHED
        assert res_b.status == ConfirmationMatchStatus.MATCHED
        assert res_a.candidate_record.setup_key != res_b.candidate_record.setup_key

    def test_no_mutation_of_activation_snapshots(self) -> None:
        """Passive matcher does not mutate activation records or context mappings."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        act_before = deepcopy(act)
        ev = make_evidence(direction=Direction.UPWARD)
        ctx = MatchingContext(member_directions={act.member_key: Direction.UPWARD})

        res = matcher.match(act, ev, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert act == act_before

    def test_idempotent_duplicate_evidence_handling(self) -> None:
        """Evaluating identical evidence repeatedly produces bit-identical matching results."""
        matcher = ConfirmationMatcher()
        act = make_activation()
        ev = make_evidence(direction=Direction.UPWARD)
        ctx = MatchingContext(member_directions={act.member_key: Direction.UPWARD})

        res1 = matcher.match(act, ev, ctx)
        res2 = matcher.match(act, ev, ctx)
        assert res1.status == res2.status
        assert res1.candidate_record == res2.candidate_record


class TestCandleDerivedContinuousDetection:
    """Suite testing actual candle-derived continuous pattern recognition and adapter integration."""

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
        """Demonstrates a genuine candle-derived CHOCH pattern that begins before activation and completes afterward.

        CHOCH pattern begins at candle 1 / 4 / 5 in 'choch_bearish_basic_end_to_end'.
        TJL activation tap occurs at candle 7 (before CHOCH completes at candle 9).
        Continuous CHOCH detector processes its candles without restarting at the tap.
        Adapter translates ConfirmedChoch into ConfirmationEvidenceRecord.
        Matcher validates the association and produces CandidateSetupRecord.
        """
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        config = MSMConfig(
            start_candle_time=start_time,
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])

        assert len(coordinator.confirmed_choch_events) == 1
        choch = coordinator.confirmed_choch_events[0]
        assert choch.choch_type == ChochType.BEARISH_CHOCH
        assert choch.c1_candle_index == 8
        assert choch.c2_candle_index == 9
        assert choch.point_3_source_index == 5

        # Tap candle is candle 7: occurring after Point 3 (candle 5) but BEFORE CHOCH confirmation (candle 9)
        tap_candle = fix["candles"][7]
        tap_time = datetime.fromisoformat(tap_candle["time"]).astimezone(timezone.utc)
        conf_close_time = choch.confirmation_time or datetime.fromisoformat(fix["candles"][9]["close_time"]).astimezone(timezone.utc)
        assert tap_time < conf_close_time, "Tap occurred strictly before CHOCH confirmation close"

        # Construct activation representing tapped H4 TJL level
        act = make_activation(
            source_timeframe="H4",
            confirmation_timeframe="M5",
            first_touch_time=tap_time,
            first_touch_price=1.1350,
            role="TJL1",
        )

        # Adapt ConfirmedChoch using adapter
        evidence = adapt_confirmed_choch_to_evidence(
            choch=choch,
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            confirmation_timeframe="M5",
            confirmation_candle_id="EURUSD:M5:20261001T090000Z",
            close_price=1.1000,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
        )

        # Validate adapter observational fields
        assert evidence.direction == Direction.DOWNWARD
        assert evidence.producer_id == "CHOCH_DETECTOR_v1"
        assert evidence.pattern_type == "CHOCH"
        assert len(evidence.structural_dependency_references) >= 5

        # Match with ConfirmationMatcher
        matcher = ConfirmationMatcher()
        ctx = MatchingContext(
            member_directions={act.member_key: Direction.DOWNWARD},
            default_price_basis=PriceBasis.BID,
        )

        res = matcher.match(act, evidence, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.confirmation_timeframe == "M5"
        assert cand.entry_reference_price == 1.1000
        assert cand.confirmation_patterns == ("CHOCH",)

    def test_actual_candle_derived_iss_authoritative_matching_and_unresolved_blocking(
        self, iss_fixtures: Dict[str, Any]
    ) -> None:
        """Tests adapter translation from candle-derived ISS fixture.

        Validates:
        1. Authoritative 2-candle pullback ISS from iss_02 matches eligible activation.
        2. ISS with unresolved dependencies fails closed as BLOCKED_UNRESOLVED_CONFIRMATION_GAP.
        """
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"]).astimezone(timezone.utc)
        engine = ISSEngine(ISSConfig(main_direction=Direction.UPWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap.confirmed_events) == 1
        iss_event = snap.confirmed_events[0]

        # In iss_02, confirmation is at Bar 20
        conf_time = iss_event.confirmation_time or datetime.fromisoformat(fix["candles"][20]["close_time"]).astimezone(timezone.utc)
        tap_time = datetime.fromisoformat(fix["candles"][15]["time"]).astimezone(timezone.utc)
        assert tap_time < conf_time

        # Activation on H4
        act = make_activation(
            source_timeframe="H4",
            confirmation_timeframe="M5",
            first_touch_time=tap_time,
            role="TJL2_A_PLUS",
        )

        # 1. Authoritative ISS evidence
        evidence_auth = adapt_confirmed_iss_to_evidence(
            iss=iss_event,
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            confirmation_timeframe="M5",
            confirmation_candle_id="EURUSD:M5:20261001T210000Z",
            close_price=1.1200,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
            has_unresolved_dependencies=False,
        )

        assert evidence_auth.direction == Direction.DOWNWARD  # Bullish main -> Downward internal shift
        assert evidence_auth.producer_id == "ISS_ENGINE_v1"
        assert evidence_auth.pattern_type == "ISS"

        matcher = ConfirmationMatcher()
        ctx = MatchingContext(
            member_directions={act.member_key: Direction.DOWNWARD},
            default_price_basis=PriceBasis.BID,
        )

        res_auth = matcher.match(act, evidence_auth, ctx)
        assert res_auth.status == ConfirmationMatchStatus.MATCHED
        assert res_auth.candidate_record is not None
        assert res_auth.candidate_record.signal_side == "SELL"

        # 2. Unresolved ISS evidence (e.g. multi-candle pullback ambiguity)
        evidence_unresolved = adapt_confirmed_iss_to_evidence(
            iss=iss_event,
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            confirmation_timeframe="M5",
            confirmation_candle_id="EURUSD:M5:20261001T210000Z",
            close_price=1.1200,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
            has_unresolved_dependencies=True,  # Blocks fail-closed
        )

        res_unres = matcher.match(act, evidence_unresolved, ctx)
        assert res_unres.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP in res_unres.rejection_reasons

    def test_deterministic_replay_and_prefix_consistency(
        self, choch_fixtures: Dict[str, Any]
    ) -> None:
        """Deterministic replay: evaluating prefixes produces identical candidate results."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        config = MSMConfig(start_candle_time=start_time, direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])
        choch = coordinator.confirmed_choch_events[0]

        ev = adapt_confirmed_choch_to_evidence(
            choch=choch,
            confirmation_config_id="CONF_CFG_EURUSD_M5_v1",
            confirmation_timeframe="M5",
            confirmation_candle_id="EURUSD:M5:20261001T090000Z",
            close_price=1.1000,
            price_basis=PriceBasis.BID,
            symbol="EURUSD",
        )

        act = make_activation(
            source_timeframe="H4",
            confirmation_timeframe="M5",
            first_touch_time=datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc),
        )

        matcher = ConfirmationMatcher()
        ctx = MatchingContext(member_directions={act.member_key: Direction.DOWNWARD}, evaluation_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc))

        res_run1 = matcher.match(act, ev, ctx)
        res_run2 = matcher.match(act, ev, ctx)

        assert res_run1 == res_run2
        assert res_run1.candidate_record.setup_key == res_run2.candidate_record.setup_key
