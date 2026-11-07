"""Offline source-to-candidate integration proof tests — Complete Equality and Immutability.

Covers Milestone 36 Directive (HANDOFF-122):
- Case 7: Deterministic equality and input immutability:
  * Repeated evaluations produce identical complete AuthorityBuildResult (auth_res1 == auth_res2).
  * Repeated evaluations produce identical complete ConfirmationMatchResult (match_res1 == match_res2).
  * Strict input immutability verified against deep copies (cov_rec == cov_copy, usg_rec == usg_copy).
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
from aladeen.strategy.confirmation_adapters import (
    ValidatedCandleStreamEnvelope,
    adapt_confirmed_choch_to_evidence,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    EvidenceProvenanceType,
)
from aladeen.strategy.coordinator import MSMChochCoordinator
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.tjl_types import StableLevelId
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
    start_date: datetime,
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


class TestSourceCandidateAuthorityEquality:
    """Case 7: Deterministic equality and input immutability."""

    def _setup_genuine_pipeline(self) -> Dict[str, Any]:
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

        # Boundary 3: Exact price touch at 07:30 UTC
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
            "lvl1": lvl1,
            "lvl2": lvl2,
            "t0": t0,
            "t_1000": datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            "eval_time": datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
            "snap_touched": snap_touched,
            "act_rec_tjl1": act_rec_tjl1,
            "evidence": evidence,
        }

    def test_case_7_repeated_evaluations_produce_identical_outputs_and_immutable_inputs(self) -> None:
        """Case 7: Repeated evaluations produce identical complete AuthorityBuildResult and
        identical ConfirmationMatchResult with unchanged inputs.
        """
        data = self._setup_genuine_pipeline()
        lvl1 = data["lvl1"]
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
        usg_rec = ProposedUsageEvidenceRecord(
            record_id="USG_01",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_001",
        )

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
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl1,),
        )
        ctx1, _ = builder.build_matching_context(
            authority_result=auth_res1,
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
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl1,),
        )
        ctx2, _ = builder.build_matching_context(
            authority_result=auth_res2,
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
        match_res2 = matcher.match(data["act_rec_tjl1"], data["evidence"], ctx2)

        # Complete dataclass equality assertions
        assert auth_res1 == auth_res2
        assert match_res1 == match_res2  # Complete dataclass equality!
        assert match_res1.status == match_res2.status == ConfirmationMatchStatus.MATCHED
        assert match_res1.candidate_record == match_res2.candidate_record
        assert match_res1.rejection_reasons == match_res2.rejection_reasons == ()
        assert match_res1.diagnostic_message == match_res2.diagnostic_message

        # Input immutability assertions
        assert cov_rec == cov_copy
        assert usg_rec == usg_copy
