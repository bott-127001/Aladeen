"""Offline source-to-candidate integration proof tests — Binding and Entity Isolation.

Covers Milestone 36 Directives:
- Case 4: Request binding compatibility enforcement (cross-config, cross-domain, timeframe, expanded interval rejection).
- Case 5: Conflicting authority isolated to affected entity/scope (clean TJL1 matches, contradictory TJL2 fails closed).
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
    format_length_prefixed,
)
from aladeen.strategy.coordinator import MSMChochCoordinator
from aladeen.strategy.tjl_coordinator import TJLCoordinator
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


class TestSourceCandidateAuthorityBinding:
    """Case 4 and Case 5: Binding validation and authority conflict isolation."""

    def _setup_authority_pipeline(self) -> Dict[str, Any]:
        """Sets up genuine authority-backed pipeline through touch and confirmed evidence."""
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
        assert cset is not None

        t0 = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        lvl1 = cset.tjl1_zone.level_id
        lvl2 = cset.tjl2_zone.level_id

        # Boundary 1: Authority-backed registration
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        usg_1 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL1_0000",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_TX_001",
        )
        usg_2 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_0000",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl2,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_TX_002",
        )
        auth_reg = builder.validate_and_build(
            coverage_records=(),
            usage_records=(usg_1, usg_2),
            evaluation_time=t0,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0,
            physical_levels=(lvl1, lvl2),
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
        snap_sync = synchronizer.sync(snap_tjl, sequence_ref_start=1001, usage_evidence=auth_reg.resolved_usage_statuses)

        # Boundary 3: Exact price touch
        p_touch = ExactPricePrint("OBS_01", 1.1825, PRICE_BASIS, datetime(2026, 10, 11, 7, 30, tzinfo=timezone.utc), DEFAULT_DOMAIN, 1003)
        snap_touched = act_engine.process_event(p_touch)
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        act_rec_tjl1 = snap_touched.active_activations[mem_key_tjl1]
        assert act_rec_tjl1.state == ActivationState.PENDING_ACTIVATION

        # Boundary 5: Confirmation detector completes at 10:00 UTC
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
        choch_coord = MSMChochCoordinator(MSMConfig(start_candle_time=t0, direction=Direction.UPWARD))
        for i in range(10):
            choch_coord.process_candle(choch_candles[i])
        evt = choch_coord.confirmed_choch_events[0]
        confirming_candle = choch_candles[evt.c2_candle_index]
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
            choch=evt,
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
            "lvl1": lvl1,
            "lvl2": lvl2,
            "t0": t0,
            "t_1000": datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            "eval_time": datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
            "snap_touched": snap_touched,
            "act_rec_tjl1": act_rec_tjl1,
            "evidence": evidence,
        }

    def test_case_4_request_binding_rejects_cross_context_reuse(self) -> None:
        """Case 4: MatchingContext composition rejects any mismatch between caller context and bound authority:
        - Wrong confirmation config id raises ValueError
        - Wrong sequence domain or feed raises ValueError
        - Wrong confirmation timeframe raises ValueError
        - Expanded interval request raises ValueError
        """
        data = self._setup_authority_pipeline()
        cset = data["cset"]
        t0 = data["t0"]
        t_1000 = data["t_1000"]
        eval_time = data["eval_time"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        synthetic_source_res = {m_k: True for m_k in data["snap_touched"].current_members}

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=t_1000,
            status=CoverageStatus.COMPLETE,
            issued_time=t_1000,
            available_time=t_1000,
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
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(cset.tjl1_zone.level_id,),
        )

        # 4A: Wrong confirmation config id
        with pytest.raises(ValueError, match="Cross-config reuse rejected"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id="CONF_CFG_DIFFERENT",
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=t0,
                expected_interval_end=t_1000,
                source_resolution_status=synthetic_source_res,
            )

        # 4B: Wrong sequence domain
        wrong_domain = SequenceDomain(feed_id=FEED_ID, run_id="DIFFERENT_RUN")
        with pytest.raises(ValueError, match="Cross-domain reuse rejected"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=wrong_domain,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=t0,
                expected_interval_end=t_1000,
                source_resolution_status=synthetic_source_res,
            )

        # 4C: Wrong confirmation timeframe
        with pytest.raises(ValueError, match="Timeframe mismatch"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="M15",
                expected_interval_start=t0,
                expected_interval_end=t_1000,
                source_resolution_status=synthetic_source_res,
            )

        # 4D: Expanded interval request
        expanded_end = eval_time + timedelta(hours=1)
        with pytest.raises(ValueError, match="expected_interval_end.*cannot exceed evaluation_time|Expanded interval reuse rejected"):
            builder.build_matching_context(
                authority_result=auth_res,
                base_members=data["snap_touched"].current_members,
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=t0,
                expected_interval_end=expanded_end,
                source_resolution_status=synthetic_source_res,
            )

    def test_case_5_conflicting_authority_isolated_to_affected_entity(self) -> None:
        """Case 5: Contradictory authority on TJL2 is isolated; TJL1 matches cleanly while TJL2 fails closed."""
        data = self._setup_authority_pipeline()
        cset = data["cset"]
        lvl1 = data["lvl1"]
        lvl2 = data["lvl2"]
        t0 = data["t0"]
        t_1000 = data["t_1000"]
        eval_time = data["eval_time"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        synthetic_source_res = {m_k: True for m_k in data["snap_touched"].current_members}

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=t_1000,
            status=CoverageStatus.COMPLETE,
            issued_time=t_1000,
            available_time=t_1000,
            revision_seq=1,
        )

        # TJL1 has clean, valid UNUSED record
        usg_tjl1 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL1_CLEAN",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_001",
        )

        # TJL2 has contradictory conflicting assertions under same record ID
        usg_tjl2_conflict_a = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_CONFLICT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl2,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_002A",
        )
        usg_tjl2_conflict_b = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_CONFLICT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl2,
            status=UsageEvidenceStatus.USED,
            established_time=t0,
            available_time=t0,
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
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl1, lvl2),
        )

        # TJL1 is clean and unaffected: resolved to UNUSED
        assert auth_res.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.UNUSED
        # TJL2 is isolated: resolved to UNKNOWN with diagnostic
        assert auth_res.resolved_usage_statuses[lvl2] == UsageEvidenceStatus.UNKNOWN
        assert any(
            d.entity_key == "USG_TJL2_CONFLICT"
            and d.diagnostic_reason == AuthorityDiagnosticReason.CONFLICTING_IDENTITY
            for d in auth_res.diagnostics
        )

        matching_ctx, updated_members = builder.build_matching_context(
            authority_result=auth_res,
            base_members=data["snap_touched"].current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t_1000,
            source_resolution_status=synthetic_source_res,
            active_activations=data["snap_touched"].active_activations,
        )

        # TJL1 matches cleanly with complete canonical identity and provenance assertions
        res_tjl1 = matcher.match(data["act_rec_tjl1"], data["evidence"], matching_ctx)
        assert res_tjl1.status == ConfirmationMatchStatus.MATCHED
        assert res_tjl1.candidate_record is not None
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=matching_ctx.domain_session_id,
            revision_id=matching_ctx.revision_id,
            activation_id=data["act_rec_tjl1"].activation_id,
            source_member_key=data["act_rec_tjl1"].member_key,
            confirmation_config_id=data["evidence"].confirmation_config_id,
            confirmation_candle_id=data["evidence"].confirmation_candle_id,
            confirmation_close_iso=data["evidence"].close_timestamp.isoformat(),
        )
        assert res_tjl1.candidate_record.setup_key == expected_setup_key
        assert res_tjl1.candidate_record.candidate_id == f"CAND{format_length_prefixed(expected_setup_key)}"
        assert res_tjl1.candidate_record.entry_reference_price == 1.0850
        assert res_tjl1.candidate_record.provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED

        # TJL2 activation rejects fail-closed with zero candidates
        mem_key_tjl2 = format_member_key("SET_1", "TJL2_A_PLUS")
        act_rec_tjl2 = data["snap_touched"].active_activations[mem_key_tjl2]
        res_tjl2 = matcher.match(act_rec_tjl2, data["evidence"], matching_ctx)
        assert res_tjl2.status == ConfirmationMatchStatus.REJECTED
        assert res_tjl2.candidate_record is None
        assert (
            ConfirmationRejectionReason.UNKNOWN_USAGE in res_tjl2.rejection_reasons
            or ConfirmationRejectionReason.CONTEXT_MISMATCH in res_tjl2.rejection_reasons
            or ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_tjl2.rejection_reasons
        )
