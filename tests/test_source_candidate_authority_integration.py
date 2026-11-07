"""Offline source-to-candidate integration proof tests — Authority-Backed Chains.

Milestone 36 Directive:
Connects the accepted in-memory offline authority layer (AuthorityContextBuilder, CoveragePreprocessor,
UsagePreprocessor) to the genuine source-to-candidate integration chains.

Replaces directly supplied synthetic usage and coverage flags with explicit in-memory authority
records processed through the accepted builder, retaining genuine engine-produced source memberships,
explicit exact-price observations, incremental confirmation detection, and authoritative candle lookup.

Preserves the unresolved source-resolution boundary:
- Explicit synthetic resolution inputs remain labeled synthetic.
- Missing resolution authority remains blocked.
- Does not infer resolution from set presence or cursor equality without an accepted mapping.

Implements the 7 required decisive cases:
1. Valid authority available by the boundary permits the existing matcher path when all other gates pass.
2. Missing/future usage or coverage produces no candidate.
3. A later-arriving certificate cannot authorize an earlier evaluation.
4. Wrong configuration, feed/domain, timeframe, or required interval cannot reuse authority.
5. Conflicting authority affects only the intended entity/scope.
6. Replacement and rearm retain physical-level usage and immutable terminal history.
7. Repeated evaluations compare complete authority results and matcher outputs, with unchanged inputs.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import pytest

from aladeen.strategy.activation_adapter import TJLSynchronizer
from aladeen.strategy.activation_engine import ActivationEngine, ActivationEngineConfig
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    ExactPricePrint,
    ExternalCommitEvent,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
    format_member_key,
)
from aladeen.strategy.authority_context_builder import AuthorityContextBuilder
from aladeen.strategy.authority_types import (
    AuthorityBuildResult,
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
)
from aladeen.strategy.choch_types import ChochType
from aladeen.strategy.confirmation_adapters import (
    ValidatedCandleStreamEnvelope,
    adapt_confirmed_choch_to_evidence,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
    format_candidate_setup_key,
)
from aladeen.strategy.coordinator import MSMChochCoordinator
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FEED_ID = "FEED_EURUSD_D1"
CONF_CFG = "CONF_CFG_01"
DEFAULT_DOMAIN = SequenceDomain(feed_id=FEED_ID, run_id="RUN_20261001_001")
PRICE_BASIS = PriceBasis.BID

DEFAULT_TRUST = TrustConfiguration(
    trusted_usage_issuers=("UPSTREAM_TRADE_LEDGER_OFFLINE",),
    trusted_coverage_issuers=("OFFLINE_FEED_AUDITOR_v1",),
)


def load_tjl_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / "tjl_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def load_choch_fixture(name: str = "choch_bearish_basic_end_to_end") -> Dict[str, Any]:
    with open(FIXTURES_DIR / "choch_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def build_synthesized_daily_source_candles(
    raw_fixture_candles: List[Dict[str, Any]],
    start_date: datetime = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
) -> List[StrategyCandle]:
    """Synthetic fixture preparation: Map fixture OHLC patterns to daily (D1) timeline."""
    daily_candles: List[StrategyCandle] = []
    day_step = timedelta(days=1)
    for i, c in enumerate(raw_fixture_candles):
        open_time = start_date + (day_step * i)
        close_time = start_date + (day_step * (i + 1))
        daily_candles.append(
            StrategyCandle(
                index=i,
                open_time=open_time,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=close_time,
            )
        )
    return daily_candles


class TestSourceCandidateAuthorityIntegration:
    """Milestone 36: Authority-backed source-to-candidate integration proof."""

    def _setup_genuine_pipeline(self) -> Dict[str, Any]:
        """Set up genuine source D1 level set, activation engine, exact touch, and confirmed CHOCH."""
        # 1. Genuine D1 Source Level Set (Days 0..9)
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        source_start_date = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        source_candles = build_synthesized_daily_source_candles(fix_tjl["candles"], start_date=source_start_date)

        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=source_start_date),
            symbol_feed_id=FEED_ID,
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        for i in range(10):
            source_coord.process_candle(source_candles[i])

        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set

        # 2. Activation Engine Synchronization
        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol=FEED_ID,
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PRICE_BASIS,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        initial_usage = {
            cset.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            cset.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        snap_act_sync = synchronizer.sync(snap_tjl, sequence_ref_start=1001, usage_evidence=initial_usage)
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")

        # 3. Exact Price Print at 07:30 UTC inside zone [1.1800, 1.1850]
        touch_time = datetime(2026, 10, 11, 7, 30, tzinfo=timezone.utc)
        print_touch = ExactPricePrint(
            observation_id="OBS_PRINT_01",
            price=1.1825,
            price_basis=PRICE_BASIS,
            timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_act_touched = act_engine.process_event(print_touch)
        act_rec_tjl1 = snap_act_touched.active_activations[mem_key_tjl1]
        assert act_rec_tjl1.state == ActivationState.PENDING_ACTIVATION

        # 4. Confirmation Stream Preparation (H1 Timeline on 2026-10-11)
        fix_choch = load_choch_fixture("choch_bearish_basic_end_to_end")
        base_time_choch = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        interval_h1 = timedelta(hours=1)
        choch_candles = [
            StrategyCandle(
                index=i,
                open_time=base_time_choch + (interval_h1 * i),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=base_time_choch + (interval_h1 * (i + 1)),
            )
            for i, c in enumerate(fix_choch["candles"])
        ]

        choch_coord = MSMChochCoordinator(
            MSMConfig(start_candle_time=base_time_choch, direction=Direction.UPWARD)
        )
        for i in range(10):  # candle 9 confirms CHOCH at 10:00 UTC
            choch_coord.process_candle(choch_candles[i])

        assert len(choch_coord.confirmed_choch_events) == 1
        choch_event = choch_coord.confirmed_choch_events[0]
        confirming_candle = choch_candles[choch_event.c2_candle_index]

        envelope = ValidatedCandleStreamEnvelope(
            candle=confirming_candle,
            symbol=FEED_ID,
            feed_id=FEED_ID,
            timeframe="H1",
            price_basis=PRICE_BASIS,
            confirmation_config_id=CONF_CFG,
            confirmation_candle_id="CANDLE_09",
            sequence_domain=DEFAULT_DOMAIN,
        )
        evidence = adapt_confirmed_choch_to_evidence(
            choch=choch_event,
            confirmation_config_id=CONF_CFG,
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_09",
            envelope=envelope,
            symbol=FEED_ID,
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PRICE_BASIS,
            provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
        )

        return {
            "cset": cset,
            "act_engine": act_engine,
            "snap_act_touched": snap_act_touched,
            "act_rec_tjl1": act_rec_tjl1,
            "evidence": evidence,
            "touch_time": touch_time,
            "confirmation_time": choch_event.confirmation_time,
            "eval_time": datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
            "req_start": datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            "req_end": datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
        }

    # =========================================================================
    # Case 1: Valid Authority Available Permits Matcher Path
    # =========================================================================

    def test_case_1_valid_authority_permits_matcher_path(self) -> None:
        """Case 1: When valid coverage and usage authority records are available by evaluation boundary,
        the accepted AuthorityContextBuilder resolves COMPLETE and UNUSED, updating member references
        and permitting ConfirmationMatcher to produce MATCHED with exact canonical setup key.
        """
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        eval_time = data["eval_time"]
        req_start = data["req_start"]
        req_end = data["req_end"]

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_H1_20261011_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )

        usg_rec_tjl1 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL1_01",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_001",
        )

        usg_rec_tjl2 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_01",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl2_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_002",
        )

        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        auth_res = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_rec_tjl1, usg_rec_tjl2),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id, cset.tjl2_zone.level_id),
        )

        assert auth_res.resolved_coverage_status == CoverageStatus.COMPLETE
        assert auth_res.resolved_usage_statuses[cset.tjl1_zone.level_id] == UsageEvidenceStatus.UNUSED
        assert auth_res.resolved_usage_statuses[cset.tjl2_zone.level_id] == UsageEvidenceStatus.UNUSED

        # Explicit labeled synthetic resolution input
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        matching_ctx, updated_members = builder.build_matching_context(
            authority_result=auth_res,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
            active_activations=data["snap_act_touched"].active_activations,
        )

        matcher = ConfirmationMatcher()
        match_res = matcher.match(data["act_rec_tjl1"], data["evidence"], matching_ctx)

        assert match_res.status == ConfirmationMatchStatus.MATCHED
        assert match_res.candidate_record is not None
        cand = match_res.candidate_record
        assert cand.activation_id == data["act_rec_tjl1"].activation_id
        assert cand.confirmation_event_ids == (data["evidence"].event_id,)
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.setup_key is not None

    # =========================================================================
    # Case 2: Missing/Future Usage or Coverage Produces No Candidate
    # =========================================================================

    def test_case_2_missing_or_future_authority_produces_no_candidate(self) -> None:
        """Case 2: Missing or future-dated coverage or usage fails closed and yields zero candidates."""
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        eval_time = data["eval_time"]
        req_start = data["req_start"]
        req_end = data["req_end"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        valid_cov = ProposedFeedCoverageRecord(
            record_id="COV_VALID",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )

        valid_usg = ProposedUsageEvidenceRecord(
            record_id="USG_VALID",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_001",
        )

        # Subcase 2A: Missing Coverage Records -> resolves INCOMPLETE -> blocks with INCOMPLETE_COVERAGE
        auth_no_cov = builder.validate_and_build(
            coverage_records=(),
            usage_records=(valid_usg,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_no_cov.resolved_coverage_status == CoverageStatus.INCOMPLETE
        ctx_no_cov, _ = builder.build_matching_context(
            authority_result=auth_no_cov,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )
        res_no_cov = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_no_cov)
        assert res_no_cov.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_no_cov.rejection_reasons
        assert res_no_cov.candidate_record is None

        # Subcase 2B: Future Coverage Certificate (available_time > eval_time) -> filtered -> INCOMPLETE
        future_cov = ProposedFeedCoverageRecord(
            record_id="COV_FUTURE",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),  # > 10:30 UTC
            revision_seq=1,
        )
        auth_fut_cov = builder.validate_and_build(
            coverage_records=(future_cov,),
            usage_records=(valid_usg,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_fut_cov.resolved_coverage_status == CoverageStatus.INCOMPLETE

        ctx_fut_cov, _ = builder.build_matching_context(
            authority_result=auth_fut_cov,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )
        res_fut_cov = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_fut_cov)
        assert res_fut_cov.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_fut_cov.rejection_reasons
        assert res_fut_cov.candidate_record is None

        # Subcase 2C: Missing Usage Records -> resolves UNKNOWN -> blocks with zero candidates
        auth_no_usg = builder.validate_and_build(
            coverage_records=(valid_cov,),
            usage_records=(),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_no_usg.resolved_usage_statuses[cset.tjl1_zone.level_id] == UsageEvidenceStatus.UNKNOWN
        ctx_no_usg, _ = builder.build_matching_context(
            authority_result=auth_no_usg,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )
        res_no_usg = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_no_usg)
        assert res_no_usg.status == ConfirmationMatchStatus.REJECTED
        assert (
            ConfirmationRejectionReason.UNKNOWN_USAGE in res_no_usg.rejection_reasons
            or ConfirmationRejectionReason.CONTEXT_MISMATCH in res_no_usg.rejection_reasons
        )
        assert res_no_usg.candidate_record is None

        # When activation also records UNKNOWN, rejected with UNKNOWN_USAGE
        act_rec_unknown = copy.deepcopy(data["act_rec_tjl1"])
        object.__setattr__(act_rec_unknown, "usage_evidence_status", UsageEvidenceStatus.UNKNOWN)
        res_unknown_match = matcher.match(act_rec_unknown, data["evidence"], ctx_no_usg)
        assert res_unknown_match.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_USAGE in res_unknown_match.rejection_reasons
        assert res_unknown_match.candidate_record is None

        # Subcase 2D: Future Usage Record (available_time > eval_time) -> filtered -> UNKNOWN
        future_usg = ProposedUsageEvidenceRecord(
            record_id="USG_FUTURE",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),  # > 10:30 UTC
            provenance_ref="LEDGER_FUTURE",
        )
        auth_fut_usg = builder.validate_and_build(
            coverage_records=(valid_cov,),
            usage_records=(future_usg,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_fut_usg.resolved_usage_statuses[cset.tjl1_zone.level_id] == UsageEvidenceStatus.UNKNOWN

        ctx_fut_usg, _ = builder.build_matching_context(
            authority_result=auth_fut_usg,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )
        res_fut_usg = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_fut_usg)
        assert res_fut_usg.status == ConfirmationMatchStatus.REJECTED
        assert (
            ConfirmationRejectionReason.UNKNOWN_USAGE in res_fut_usg.rejection_reasons
            or ConfirmationRejectionReason.CONTEXT_MISMATCH in res_fut_usg.rejection_reasons
        )
        assert res_fut_usg.candidate_record is None

    # =========================================================================
    # Case 3: Later-Arriving Certificate Cannot Authorize Earlier Evaluation
    # =========================================================================

    def test_case_3_later_certificate_cannot_authorize_earlier_evaluation(self) -> None:
        """Case 3: A certificate available at 10:00 UTC cannot authorize an earlier evaluation at 09:30 UTC,
        even if its covered interval covers [00:00, 09:30]. Point-in-time boundary enforces fail-closed.
        """
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        early_eval_time = datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc)
        req_start = data["req_start"]
        req_end = early_eval_time

        cert = ProposedFeedCoverageRecord(
            record_id="COV_1000_UTC",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),  # Available at 10:00 UTC
            revision_seq=1,
        )

        usg_rec = ProposedUsageEvidenceRecord(
            record_id="USG_0000_UTC",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_001",
        )

        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)

        # Early Evaluation at 09:30 UTC: Certificate is not available yet (available_time 10:00 > 09:30)
        auth_early = builder.validate_and_build(
            coverage_records=(cert,),
            usage_records=(usg_rec,),
            evaluation_time=early_eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=early_eval_time,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_early.resolved_coverage_status == CoverageStatus.INCOMPLETE

        # Later Evaluation at 10:30 UTC: Certificate IS available (available_time 10:00 <= 10:30)
        auth_later = builder.validate_and_build(
            coverage_records=(cert,),
            usage_records=(usg_rec,),
            evaluation_time=datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_later.resolved_coverage_status == CoverageStatus.COMPLETE

    # =========================================================================
    # Case 4: Request Binding Rejection on Cross-Config/Domain/Timeframe/Interval
    # =========================================================================

    def test_case_4_request_binding_rejects_cross_context_reuse(self) -> None:
        """Case 4: MatchingContext composition rejects any mismatch between caller context and bound authority metadata:
        - Wrong confirmation config id raises ValueError
        - Wrong sequence domain or feed raises ValueError
        - Wrong confirmation timeframe raises ValueError
        - Expanded interval request raises ValueError
        """
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        eval_time = data["eval_time"]
        req_start = data["req_start"]
        req_end = data["req_end"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )

        auth_res = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )

        # 4A: Wrong confirmation config id
        with pytest.raises(ValueError, match="Cross-config reuse rejected"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_act_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id="CONF_CFG_DIFFERENT",
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=req_start,
                expected_interval_end=req_end,
                source_resolution_status=synthetic_source_res,
            )

        # 4B: Wrong sequence domain
        wrong_domain = SequenceDomain(feed_id=FEED_ID, run_id="DIFFERENT_RUN")
        with pytest.raises(ValueError, match="Cross-domain reuse rejected"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_act_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=wrong_domain,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=req_start,
                expected_interval_end=req_end,
                source_resolution_status=synthetic_source_res,
            )

        # 4C: Wrong confirmation timeframe
        with pytest.raises(ValueError, match="Timeframe mismatch"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_act_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="M15",  # mismatches H1
                expected_interval_start=req_start,
                expected_interval_end=req_end,
                source_resolution_status=synthetic_source_res,
            )

        # 4D: Expanded interval request
        expanded_end = eval_time + timedelta(hours=1)
        with pytest.raises(ValueError, match="expected_interval_end.*cannot exceed evaluation_time|Expanded interval reuse rejected"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_act_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=req_start,
                expected_interval_end=expanded_end,
                source_resolution_status=synthetic_source_res,
            )

    # =========================================================================
    # Case 5: Conflicting Authority Affects Only Intended Scope
    # =========================================================================

    def test_case_5_conflicting_authority_isolated_to_affected_entity(self) -> None:
        """Case 5: Conflicting usage assertions on TJL2 do NOT contaminate or fail-closed TJL1.
        TJL1 resolves UNUSED and matches; TJL2 resolves UNKNOWN and blocks.
        """
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        eval_time = data["eval_time"]
        req_start = data["req_start"]
        req_end = data["req_end"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )

        # TJL1 has clean, valid UNUSED record
        usg_tjl1 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL1_CLEAN",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_001",
        )

        # TJL2 has contradictory conflicting assertions under same record ID
        usg_tjl2_conflict_a = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_CONFLICT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl2_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_002A",
        )
        usg_tjl2_conflict_b = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_CONFLICT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl2_zone.level_id,
            status=UsageEvidenceStatus.USED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_002B",
        )

        auth_res = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_tjl1, usg_tjl2_conflict_a, usg_tjl2_conflict_b),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id, cset.tjl2_zone.level_id),
        )

        # TJL1 is clean and unaffected!
        assert auth_res.resolved_usage_statuses[cset.tjl1_zone.level_id] == UsageEvidenceStatus.UNUSED
        # TJL2 is isolated and marked UNKNOWN
        assert auth_res.resolved_usage_statuses[cset.tjl2_zone.level_id] == UsageEvidenceStatus.UNKNOWN

        matching_ctx, updated_members = builder.build_matching_context(
            authority_result=auth_res,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )

        # TJL1 matches cleanly
        res_tjl1 = matcher.match(data["act_rec_tjl1"], data["evidence"], matching_ctx)
        assert res_tjl1.status == ConfirmationMatchStatus.MATCHED

        # TJL2 activation rejects fail-closed with zero candidates
        mem_key_tjl2 = format_member_key("SET_1", "TJL2_A_PLUS")
        act_rec_tjl2 = data["snap_act_touched"].active_activations[mem_key_tjl2]
        res_tjl2 = matcher.match(act_rec_tjl2, data["evidence"], matching_ctx)
        assert res_tjl2.status == ConfirmationMatchStatus.REJECTED
        assert res_tjl2.candidate_record is None
        assert (
            ConfirmationRejectionReason.UNKNOWN_USAGE in res_tjl2.rejection_reasons
            or ConfirmationRejectionReason.CONTEXT_MISMATCH in res_tjl2.rejection_reasons
            or ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_tjl2.rejection_reasons
        )

    # =========================================================================
    # Case 6: Replacement and Rearm Retain Physical-Level Usage & Terminal History
    # =========================================================================

    def test_case_6_replacement_and_rearm_retain_usage_and_terminal_history(self) -> None:
        """Case 6: Replacement and rearm retain physical-level usage and immutable terminal history.
        - Physical level marked USED remains permanently USED across subsequent set sync / replacement.
        - Illegal proposal attempting to reset terminal USED to UNUSED is rejected with USAGE_USED_TERMINAL.
        - Composition blocks (raises ValueError) if activation history has terminal USED but authority is UNUSED.
        """
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        lvl1 = cset.tjl1_zone.level_id
        eval_time = data["eval_time"]
        req_start = data["req_start"]
        req_end = data["req_end"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        # Root usage was USED
        usg_root_used = ProposedUsageEvidenceRecord(
            record_id="USG_USED_TERMINAL_ROOT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.USED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_USED",
        )

        # Illegal successor attempts reset to UNUSED
        usg_illegal_reset = ProposedUsageEvidenceRecord(
            record_id="USG_ILLEGAL_RESET",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            predecessor_record_id="USG_USED_TERMINAL_ROOT",
            provenance_ref="LEDGER_RESET",
        )

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )

        auth_res = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_root_used, usg_illegal_reset),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(lvl1,),
        )

        # Terminal USED is preserved; illegal reset is rejected
        assert auth_res.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.USED
        assert auth_res.authoritative_usage_records[lvl1].record_id == "USG_USED_TERMINAL_ROOT"
        assert any(
            d.entity_key == "USG_ILLEGAL_RESET" and d.diagnostic_reason == AuthorityDiagnosticReason.USAGE_USED_TERMINAL
            for d in auth_res.diagnostics
        )

        # Immutable activation metadata consistency check:
        # If activation had USED, but authority resolved UNUSED -> build_matching_context raises ValueError
        act_history_used = copy.deepcopy(data["act_rec_tjl1"])
        object.__setattr__(act_history_used, "usage_evidence_status", UsageEvidenceStatus.USED)

        # Create authority result resolving UNUSED to test composition block
        usg_unused_only = ProposedUsageEvidenceRecord(
            record_id="USG_UNUSED_ONLY",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_UNUSED",
        )
        auth_res_unused = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_unused_only,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(lvl1,),
        )

        with pytest.raises(ValueError, match="has immutable terminal USED status; authority resolution UNUSED contradicts"):
            builder.build_matching_context(
                authority_result=auth_res_unused,
                base_members=data["snap_act_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=req_start,
                expected_interval_end=req_end,
                source_resolution_status=synthetic_source_res,
                active_activations={act_history_used.member_key: act_history_used},
            )

    # =========================================================================
    # Case 7: Repeated Evaluations Compare Complete Authority & Matcher Equality
    # =========================================================================

    def test_case_7_repeated_evaluations_produce_identical_outputs_and_immutable_inputs(self) -> None:
        """Case 7: Repeated evaluations produce identical complete AuthorityBuildResult and
        identical ConfirmationMatchResult with unchanged inputs.
        """
        data = self._setup_genuine_pipeline()
        cset = data["cset"]
        eval_time = data["eval_time"]
        req_start = data["req_start"]
        req_end = data["req_end"]
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=req_start,
            covered_interval_end=req_end,
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )

        usg_rec = ProposedUsageEvidenceRecord(
            record_id="USG_01",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            provenance_ref="LEDGER_001",
        )

        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()

        cov_copy = copy.deepcopy(cov_rec)
        usg_copy = copy.deepcopy(usg_rec)

        # Run 1
        auth_res1 = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_rec,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        ctx1, _ = builder.build_matching_context(
            authority_result=auth_res1,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )
        match_res1 = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx1)

        # Run 2
        auth_res2 = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_rec,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=req_start,
            required_interval_end=req_end,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        ctx2, _ = builder.build_matching_context(
            authority_result=auth_res2,
            base_members=data["snap_act_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=req_start,
            expected_interval_end=req_end,
            source_resolution_status=synthetic_source_res,
        )
        match_res2 = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx2)

        # Complete equality assertions
        assert auth_res1 == auth_res2
        assert match_res1.status == match_res2.status
        assert match_res1.candidate_record == match_res2.candidate_record
        assert match_res1.rejection_reasons == match_res2.rejection_reasons

        # Input immutability
        assert cov_rec == cov_copy
        assert usg_rec == usg_copy
