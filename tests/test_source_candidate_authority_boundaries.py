"""Offline source-to-candidate integration proof tests — Authority Boundaries.

Covers Milestone 36 Directive:
- Negative boundary tests connecting genuine engine instances to authority validation:
  * Missing or future usage at source registration produces UNKNOWN usage, blocking candidate generation.
  * Missing or future usage at evaluation time produces member/activation metadata disagreement (CONTEXT_MISMATCH), blocking candidate generation.
  * Missing or future coverage at evaluation time resolves INCOMPLETE, rejecting fail-closed with INCOMPLETE_COVERAGE.
  * Later-arriving certificate available at 10:00 UTC cannot authorize earlier evaluation at 09:30 UTC.
  * Preserves real engine records without private field mutation.
"""

from __future__ import annotations

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
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_member_key,
)
from aladeen.strategy.authority_context_builder import AuthorityContextBuilder
from aladeen.strategy.authority_types import (
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
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
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


def build_synthesized_daily_source_candles(raw: List[Dict[str, Any]], start_date: datetime = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)) -> List[StrategyCandle]:
    step = timedelta(days=1)
    return [
        StrategyCandle(
            index=i, open_time=start_date + (step * i), open=float(c["open"]), high=float(c["high"]),
            low=float(c["low"]), close=float(c["close"]), is_forming=bool(c["is_forming"]),
            bar_status=str(c["bar_status"]), close_time=start_date + (step * (i + 1)),
        )
        for i, c in enumerate(raw)
    ]


class TestSourceCandidateAuthorityBoundaries:
    """Authority boundary negative tests."""

    @staticmethod
    def _build_context(builder, auth, members, eval_time, t0, t_1000, src_res=None):
        ctx, _ = builder.build_matching_context(
            authority_result=auth, base_members=members, domain_session_id="SESS_01", revision_id="REV_01",
            expected_price_basis=PRICE_BASIS, expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN, evaluation_time=eval_time, expected_timeframe="H1",
            expected_interval_start=t0, expected_interval_end=t_1000,
            source_resolution_status=src_res if src_res is not None else {},
        )
        return ctx

    def _setup_pipeline(self) -> Dict[str, Any]:
        """Prepare source, touched activation, and confirmed evidence."""
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
        cset = snap_tjl.current_eligible_set

        t0 = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        usg_rec = ProposedUsageEvidenceRecord(
            record_id="USG_01",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_001",
        )
        auth_res = builder.validate_and_build(
            coverage_records=(),
            usage_records=(usg_rec,),
            evaluation_time=t0,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0,
            physical_levels=(cset.tjl1_zone.level_id,),
        )

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
        snap_act_sync = synchronizer.sync(snap_tjl, sequence_ref_start=1001, usage_evidence=auth_res.resolved_usage_statuses)
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")

        # Touch at 07:30 UTC
        touch_time = datetime(2026, 10, 11, 7, 30, tzinfo=timezone.utc)
        p_touch = ExactPricePrint("OBS_01", 1.1825, PRICE_BASIS, touch_time, DEFAULT_DOMAIN, 1003)
        snap_act_touched = act_engine.process_event(p_touch)
        act_rec_tjl1 = snap_act_touched.active_activations[mem_key_tjl1]

        # CHOCH confirmed at 10:00 UTC
        fix_choch = load_choch_fixture("choch_bearish_basic_end_to_end")
        interval_h1 = timedelta(hours=1)
        choch_candles = [
            StrategyCandle(
                index=i,
                open_time=t0 + (interval_h1 * i),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=t0 + (interval_h1 * (i + 1)),
            )
            for i, c in enumerate(fix_choch["candles"])
        ]
        choch_coord = MSMChochCoordinator(
            MSMConfig(start_candle_time=t0, direction=Direction.UPWARD)
        )
        for i in range(10):
            choch_coord.process_candle(choch_candles[i])

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
            "snap_tjl": snap_tjl,
            "act_engine": act_engine,
            "snap_act_touched": snap_act_touched,
            "act_rec_tjl1": act_rec_tjl1,
            "evidence": evidence,
            "t0": t0,
            "t_1000": datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            "eval_time": datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
        }

    def test_missing_or_future_usage_at_registration_blocks_candidates(self) -> None:
        """Missing or future usage at registration creates UNKNOWN activation, blocking candidates."""
        data = self._setup_pipeline()
        cset = data["cset"]
        t0 = data["t0"]
        lvl1 = cset.tjl1_zone.level_id
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        p_touch = ExactPricePrint("OBS_01", 1.1825, PRICE_BASIS, datetime(2026, 10, 11, 7, 30, tzinfo=timezone.utc), DEFAULT_DOMAIN, 1003)

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_1000",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=data["t_1000"],
            status=CoverageStatus.COMPLETE,
            issued_time=data["t_1000"],
            available_time=data["t_1000"],
            revision_seq=1,
        )

        # 1. Missing usage at registration -> resolves UNKNOWN
        auth_no_usg = builder.validate_and_build(
            coverage_records=(),
            usage_records=(),
            evaluation_time=t0,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0,
            physical_levels=(lvl1,),
        )
        assert auth_no_usg.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.UNKNOWN

        eng_missing = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_D1", FEED_ID, "D1", DEFAULT_DOMAIN, PRICE_BASIS))
        snap_missing = TJLSynchronizer(engine=eng_missing).sync(data["snap_tjl"], 1001, auth_no_usg.resolved_usage_statuses)
        snap_touched_missing = eng_missing.process_event(p_touch)
        act_missing = snap_touched_missing.active_activations[mem_key_tjl1]
        assert act_missing.state == ActivationState.INACTIVE_INELIGIBLE
        assert act_missing.usage_evidence_status == UsageEvidenceStatus.UNKNOWN

        auth_eval = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(),
            evaluation_time=data["eval_time"],
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=data["t_1000"],
            physical_levels=(lvl1,),
        )
        syn_res_missing = {m: True for m in snap_touched_missing.current_members}
        ctx_missing = self._build_context(builder, auth_eval, snap_touched_missing.current_members, data["eval_time"], t0, data["t_1000"], src_res=syn_res_missing)
        res_missing = matcher.match(act_missing, data["evidence"], ctx_missing)
        assert res_missing.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_USAGE in res_missing.rejection_reasons
        assert res_missing.candidate_record is None

        # 2. Future usage at registration (available_time > evaluation_time) -> resolves UNKNOWN
        fut_usg_reg = ProposedUsageEvidenceRecord(
            record_id="USG_FUT_REG",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0 + timedelta(hours=1),
            provenance_ref="LEDGER_FUT_01",
        )
        auth_fut_usg_reg = builder.validate_and_build(
            coverage_records=(),
            usage_records=(fut_usg_reg,),
            evaluation_time=t0,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0,
            physical_levels=(lvl1,),
        )
        assert auth_fut_usg_reg.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.UNKNOWN

        eng_fut = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_D1", FEED_ID, "D1", DEFAULT_DOMAIN, PRICE_BASIS))
        snap_fut = TJLSynchronizer(engine=eng_fut).sync(data["snap_tjl"], 2001, auth_fut_usg_reg.resolved_usage_statuses)
        snap_touched_fut = eng_fut.process_event(p_touch)
        act_fut = snap_touched_fut.active_activations[mem_key_tjl1]
        assert act_fut.state == ActivationState.INACTIVE_INELIGIBLE
        assert act_fut.usage_evidence_status == UsageEvidenceStatus.UNKNOWN

        syn_res_fut = {m: True for m in snap_touched_fut.current_members}
        ctx_fut = self._build_context(builder, auth_eval, snap_touched_fut.current_members, data["eval_time"], t0, data["t_1000"], src_res=syn_res_fut)
        res_fut = matcher.match(act_fut, data["evidence"], ctx_fut)
        assert res_fut.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_USAGE in res_fut.rejection_reasons
        assert res_fut.candidate_record is None

    def test_missing_or_future_usage_at_evaluation_blocks_candidates(self) -> None:
        """Usage resolved UNKNOWN at evaluation disagrees with UNUSED activation, blocking via CONTEXT_MISMATCH."""
        data = self._setup_pipeline()
        cset = data["cset"]
        lvl1 = cset.tjl1_zone.level_id
        t0 = data["t0"]
        eval_time = data["eval_time"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_1000",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=data["t_1000"],
            status=CoverageStatus.COMPLETE,
            issued_time=data["t_1000"],
            available_time=data["t_1000"],
            revision_seq=1,
        )

        # 1. Missing usage at evaluation -> resolves UNKNOWN member usage
        auth_no_usg = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=data["t_1000"],
            physical_levels=(lvl1,),
        )
        ctx_missing = self._build_context(builder, auth_no_usg, data["snap_act_touched"].current_members, eval_time, t0, data["t_1000"], synthetic_source_res)
        res_missing = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_missing)
        assert res_missing.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CONTEXT_MISMATCH in res_missing.rejection_reasons
        assert res_missing.candidate_record is None

        # 2. Future usage at evaluation (available_time > eval_time) -> resolves UNKNOWN member usage
        fut_usg_eval = ProposedUsageEvidenceRecord(
            record_id="USG_FUT_EVAL",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=eval_time + timedelta(hours=1),
            provenance_ref="LEDGER_FUT_EVAL",
        )
        auth_fut_usg = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(fut_usg_eval,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=data["t_1000"],
            physical_levels=(lvl1,),
        )
        ctx_fut = self._build_context(builder, auth_fut_usg, data["snap_act_touched"].current_members, eval_time, t0, data["t_1000"], synthetic_source_res)
        res_fut = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_fut)
        assert res_fut.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CONTEXT_MISMATCH in res_fut.rejection_reasons
        assert res_fut.candidate_record is None

    def test_missing_or_future_coverage_at_evaluation_blocks_candidates(self) -> None:
        """Missing or future coverage certificate rejects fail-closed with INCOMPLETE_COVERAGE."""
        data = self._setup_pipeline()
        cset = data["cset"]
        t0 = data["t0"]
        eval_time = data["eval_time"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        synthetic_source_res = {m_k: True for m_k in data["snap_act_touched"].current_members}

        usg_rec = ProposedUsageEvidenceRecord(
            record_id="USG_01",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=cset.tjl1_zone.level_id,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_001",
        )

        # 1. Missing coverage
        auth_no_cov = builder.validate_and_build(
            coverage_records=(),
            usage_records=(usg_rec,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=data["t_1000"],
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_no_cov.resolved_coverage_status == CoverageStatus.INCOMPLETE

        ctx_no_cov = self._build_context(builder, auth_no_cov, data["snap_act_touched"].current_members, eval_time, t0, data["t_1000"], synthetic_source_res)
        res_no_cov = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_no_cov)
        assert res_no_cov.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_no_cov.rejection_reasons
        assert res_no_cov.candidate_record is None

        # 2. Future coverage (available at 11:00 UTC > 10:30 UTC)
        fut_cov = ProposedFeedCoverageRecord(
            record_id="COV_FUTURE",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=data["t_1000"],
            status=CoverageStatus.COMPLETE,
            issued_time=datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 11, 0, tzinfo=timezone.utc),
            revision_seq=1,
        )
        auth_fut_cov = builder.validate_and_build(
            coverage_records=(fut_cov,),
            usage_records=(usg_rec,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=data["t_1000"],
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_fut_cov.resolved_coverage_status == CoverageStatus.INCOMPLETE

        ctx_fut_cov = self._build_context(builder, auth_fut_cov, data["snap_act_touched"].current_members, eval_time, t0, data["t_1000"], synthetic_source_res)
        res_fut_cov = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_fut_cov)
        assert res_fut_cov.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_fut_cov.rejection_reasons
        assert res_fut_cov.candidate_record is None

    def test_later_arriving_certificate_cannot_authorize_earlier_evaluation(self) -> None:
        """Certificate available at 10:00 UTC fails closed when evaluated at 09:30 UTC."""
        data = self._setup_pipeline()
        cset = data["cset"]
        t0 = data["t0"]
        early_eval = datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc)
        req_end_early = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)

        cert = ProposedFeedCoverageRecord(
            record_id="COV_1000",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=data["t_1000"],
            status=CoverageStatus.COMPLETE,
            issued_time=data["t_1000"],
            available_time=data["t_1000"],  # Available at 10:00 UTC
            revision_seq=1,
        )

        # Evaluated at 09:30 UTC (before 10:00 UTC) -> INCOMPLETE
        auth_early = builder.validate_and_build(
            coverage_records=(cert,),
            usage_records=(),
            evaluation_time=early_eval,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=req_end_early,
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_early.resolved_coverage_status == CoverageStatus.INCOMPLETE

        # Evaluated at 10:30 UTC (after 10:00 UTC) -> COMPLETE
        auth_later = builder.validate_and_build(
            coverage_records=(cert,),
            usage_records=(),
            evaluation_time=data["eval_time"],
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=data["t_1000"],
            physical_levels=(cset.tjl1_zone.level_id,),
        )
        assert auth_later.resolved_coverage_status == CoverageStatus.COMPLETE

    def test_empty_source_resolution_authority_blocks_candidate(self) -> None:
        """Empty source resolution mapping {} is preserved fail-closed and blocks matching."""
        data = self._setup_pipeline()
        lvl1 = data["cset"].tjl1_zone.level_id
        t0, eval_time = data["t0"], data["eval_time"]
        builder, matcher = AuthorityContextBuilder(trust_config=DEFAULT_TRUST), ConfirmationMatcher()

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01", schema_version="v1", issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID, sequence_domain=DEFAULT_DOMAIN, timeframe="H1",
            confirmation_config_id=CONF_CFG, covered_interval_start=t0, covered_interval_end=data["t_1000"],
            status=CoverageStatus.COMPLETE, issued_time=data["t_1000"], available_time=data["t_1000"], revision_seq=1,
        )
        usg_rec = ProposedUsageEvidenceRecord(
            record_id="USG_01", schema_version="v1", issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1, status=UsageEvidenceStatus.UNUSED, established_time=t0, available_time=t0, provenance_ref="LEDGER_001",
        )
        auth = builder.validate_and_build(
            coverage_records=(cov_rec,), usage_records=(usg_rec,), evaluation_time=eval_time,
            target_feed_id=FEED_ID, target_sequence_domain=DEFAULT_DOMAIN, target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG, required_interval_start=t0, required_interval_end=data["t_1000"],
            physical_levels=(lvl1,),
        )
        ctx_empty = self._build_context(builder, auth, data["snap_act_touched"].current_members, eval_time, t0, data["t_1000"], src_res={})
        assert ctx_empty.source_resolution_status == {}

        res = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx_empty)
        assert res.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY in res.rejection_reasons
        assert res.candidate_record is None

    def test_supplied_synthetic_authority_boundaries(self) -> None:
        """Synthetic Matcher-Contract Boundary: Unknown usage, incomplete coverage, and unresolved resolution reject fail-closed."""
        from aladeen.strategy.activation_types import format_activation_id
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
        from dataclasses import replace
        mem_unknown_usage = replace(mem_valid, usage_evidence_status=UsageEvidenceStatus.UNKNOWN)
        act_unknown_usage = replace(act_valid, usage_evidence_status=UsageEvidenceStatus.UNKNOWN)
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
        ctx_valid = MatchingContext(
            domain_session_id="SESS_01", revision_id="REV_01", expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01", matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: True}, coverage_status=CoverageStatus.COMPLETE,
        )
        ctx_incomplete_cov = replace(ctx_valid, coverage_status=CoverageStatus.INCOMPLETE)
        res_b = matcher.match(act_valid, ev_valid, ctx_incomplete_cov)
        assert res_b.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_b.rejection_reasons
        assert res_b.candidate_record is None

        # Boundary C: Unresolved source member resolution rejects as BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY
        ctx_unresolved = replace(ctx_valid, source_resolution_status={mem_valid.member_key: False})
        res_c = matcher.match(act_valid, ev_valid, ctx_unresolved)
        assert res_c.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY in res_c.rejection_reasons
        assert res_c.candidate_record is None

        # Boundary D: Evidence has unresolved structural dependencies
        ev_unresolved_dep = replace(ev_valid, event_id="EV_UNRES", has_unresolved_dependencies=True)
        res_d = matcher.match(act_valid, ev_unresolved_dep, ctx_valid)
        assert res_d.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY in res_d.rejection_reasons
        assert res_d.candidate_record is None
