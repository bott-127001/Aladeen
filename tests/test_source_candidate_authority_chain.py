"""Offline source-to-candidate integration proof tests — Authority-Backed Chronological Chain.

Covers Milestone 36 Directive:
- Full chronological causal schedule across retained source, activation, and detector instances:
  * Boundary 1 (Source Availability & Authority-Backed Registration, 2026-10-11 00:00 UTC):
    D1 source level set SET_1 formed by TJLCoordinator. Explicit usage authority records processed
    first through AuthorityContextBuilder; resolved usage passed into TJLSynchronizer. Activations
    in INACTIVE_ELIGIBLE. Empty evidence -> 0 candidates.
  * Boundary 2 (Pre-Touch, 2026-10-11 07:00 UTC):
    H1 CHOCH detector processes candles 0..6 (closed by 07:00 UTC); 0 confirmed events. Authority
    re-evaluated at 07:00 UTC. Empty evidence -> 0 candidates.
  * Boundary 3 (At Touch, 2026-10-11 07:30 UTC):
    Exact price print inside zone transitions TJL1 activation to PENDING_ACTIVATION. Detector state
    retained (0 confirmed events). Authority re-evaluated at 07:30 UTC. Empty evidence -> 0 candidates.
  * Boundary 4 (Pre-Confirmation Close, 2026-10-11 09:30 UTC):
    H1 detector processes candles 7..8 (closed by 09:00 UTC); completing candle 9 is NOT processed;
    0 confirmed events. Authority re-evaluated at 09:30 UTC. Empty evidence -> 0 candidates.
  * Boundary 5 (At Confirmation Close & Post-Close Evaluation, 2026-10-11 10:00 / 10:30 UTC):
    Completing candle 9 processed; CHOCH confirms at 10:00 UTC. Confirming candle lookup produces
    envelope and adapted ConfirmationEvidenceRecord. Coverage certificate covering [00:00, 10:00]
    issued/available at 10:00 UTC. Authority evaluated at 10:30 UTC for required interval [00:00, 10:00].
    Matcher matches with exact canonical identity, entry price 1.0850, and DETECTOR_CONFIRMED provenance.
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
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    EvidenceProvenanceType,
    format_candidate_setup_key,
    format_length_prefixed,
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


class TestSourceCandidateAuthorityChain:
    """Interleaved chronological authority-backed source-to-candidate chain."""

    def test_chronological_authority_backed_schedule_end_to_end(self) -> None:
        """Complete chronological schedule across causal boundaries 1..5."""
        matcher = ConfirmationMatcher()
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        eval_log: List[Dict[str, Any]] = []

        # =========================================================================
        # Stage 1: Genuine Source Chain on Declared Daily (D1) Timeline
        # =========================================================================
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        source_start_date = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        source_candles = build_synthesized_daily_source_candles(fix_tjl["candles"], start_date=source_start_date)

        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=source_start_date),
            symbol_feed_id=FEED_ID,
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        for i in range(9):
            source_coord.process_candle(source_candles[i])
        assert source_coord.get_snapshot().current_eligible_set is None

        # Day 9 candle completes at 2026-10-11 00:00 UTC -> SET_1 formed
        source_coord.process_candle(source_candles[9])
        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set
        lvl_tjl1 = cset.tjl1_zone.level_id
        lvl_tjl2 = cset.tjl2_zone.level_id
        t0 = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        assert cset.eligibility_available_time == t0

        # =========================================================================
        # Boundary 1: Source Availability & Authority-Backed Registration (00:00 UTC)
        # =========================================================================
        # Item 1: Process explicit usage authority records through accepted builder FIRST
        usg_rec_tjl1_b1 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL1_0000",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl_tjl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_TX_001",
        )
        usg_rec_tjl2_b1 = ProposedUsageEvidenceRecord(
            record_id="USG_TJL2_0000",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl_tjl2,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_TX_002",
        )

        auth_res_b1 = builder.validate_and_build(
            coverage_records=(),
            usage_records=(usg_rec_tjl1_b1, usg_rec_tjl2_b1),
            evaluation_time=t0,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0,
            physical_levels=(lvl_tjl1, lvl_tjl2),
        )
        assert auth_res_b1.resolved_usage_statuses[lvl_tjl1] == UsageEvidenceStatus.UNUSED
        assert auth_res_b1.resolved_usage_statuses[lvl_tjl2] == UsageEvidenceStatus.UNUSED

        # Pass authority-resolved usage into TJLSynchronizer
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
        snap_act_sync = synchronizer.sync(
            snap_tjl,
            sequence_ref_start=1001,
            usage_evidence=auth_res_b1.resolved_usage_statuses,
        )
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        assert mem_key_tjl1 in snap_act_sync.active_activations
        act_rec_b1 = snap_act_sync.active_activations[mem_key_tjl1]
        assert act_rec_b1.state == ActivationState.INACTIVE_ELIGIBLE
        assert act_rec_b1.usage_evidence_status == UsageEvidenceStatus.UNUSED

        # Confirmation detector initialized at 00:00 UTC (0 candles processed)
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
        assert len(choch_coord.confirmed_choch_events) == 0

        # Batch matcher evaluation at Boundary 1 with empty evidence -> 0 candidates
        synthetic_source_res = {m_k: True for m_k in snap_act_sync.current_members}
        ctx_b1, _ = builder.build_matching_context(
            authority_result=auth_res_b1,
            base_members=snap_act_sync.current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=t0,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t0,
            source_resolution_status=synthetic_source_res,
            active_activations=snap_act_sync.active_activations,
        )
        res_batch_b1 = matcher.match_batch(
            activations=list(snap_act_sync.active_activations.values()),
            evidences=[],
            context=ctx_b1,
        )
        assert len(res_batch_b1.unique_candidates) == 0
        eval_log.append({"boundary": "1_source_reg", "candidates": 0})

        # =========================================================================
        # Boundary 2: Pre-Touch (at 2026-10-11 07:00 UTC)
        # =========================================================================
        t_b2 = datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc)
        # Detector processes only candles closed by 07:00 UTC (candles 0..6)
        for i in range(7):
            choch_coord.process_candle(choch_candles[i])
        assert len(choch_coord.confirmed_choch_events) == 0

        # Authority re-evaluated at 07:00 UTC for interval [00:00, 07:00]
        cov_rec_b2 = ProposedFeedCoverageRecord(
            record_id="COV_H1_0700",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=t_b2,
            status=CoverageStatus.COMPLETE,
            issued_time=t_b2,
            available_time=t_b2,
            revision_seq=1,
        )
        auth_res_b2 = builder.validate_and_build(
            coverage_records=(cov_rec_b2,),
            usage_records=(usg_rec_tjl1_b1, usg_rec_tjl2_b1),
            evaluation_time=t_b2,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_b2,
            physical_levels=(lvl_tjl1, lvl_tjl2),
        )
        assert auth_res_b2.resolved_coverage_status == CoverageStatus.COMPLETE

        ctx_b2, _ = builder.build_matching_context(
            authority_result=auth_res_b2,
            base_members=snap_act_sync.current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=t_b2,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t_b2,
            source_resolution_status=synthetic_source_res,
            active_activations=snap_act_sync.active_activations,
        )
        res_batch_b2 = matcher.match_batch(
            activations=list(snap_act_sync.active_activations.values()),
            evidences=[],
            context=ctx_b2,
        )
        assert len(res_batch_b2.unique_candidates) == 0
        eval_log.append({"boundary": "2_pre_touch", "candidates": 0})

        # =========================================================================
        # Boundary 3: At Touch (at 2026-10-11 07:30 UTC)
        # =========================================================================
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
        act_rec_b3 = snap_act_touched.active_activations[mem_key_tjl1]
        assert act_rec_b3.state == ActivationState.PENDING_ACTIVATION
        assert act_rec_b3.first_touch_time == touch_time
        assert act_rec_b3.generation_seq == 1

        # Detector state retained from Boundary 2 (0 confirmed events)
        assert len(choch_coord.confirmed_choch_events) == 0

        # Authority re-evaluated at 07:30 UTC for interval [00:00, 07:00] (last completed bar)
        auth_res_b3 = builder.validate_and_build(
            coverage_records=(cov_rec_b2,),
            usage_records=(usg_rec_tjl1_b1, usg_rec_tjl2_b1),
            evaluation_time=touch_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_b2,
            physical_levels=(lvl_tjl1, lvl_tjl2),
        )
        ctx_b3, _ = builder.build_matching_context(
            authority_result=auth_res_b3,
            base_members=snap_act_touched.current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=touch_time,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t_b2,
            source_resolution_status=synthetic_source_res,
            active_activations=snap_act_touched.active_activations,
        )
        res_batch_b3 = matcher.match_batch(
            activations=list(snap_act_touched.active_activations.values()),
            evidences=[],
            context=ctx_b3,
        )
        assert len(res_batch_b3.unique_candidates) == 0
        eval_log.append({"boundary": "3_at_touch", "candidates": 0})

        # =========================================================================
        # Boundary 4: Pre-Confirmation Close (at 2026-10-11 09:30 UTC)
        # =========================================================================
        t_b4 = datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc)
        # Detector processes candle 7 and candle 8 (completing candle 9 is NOT yet processed)
        choch_coord.process_candle(choch_candles[7])
        choch_coord.process_candle(choch_candles[8])
        assert len(choch_coord.confirmed_choch_events) == 0

        # Authority re-evaluated at 09:30 UTC for interval [00:00, 09:00] (last completed bar)
        t_0900 = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
        cov_rec_b4 = ProposedFeedCoverageRecord(
            record_id="COV_H1_0900",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=t_0900,
            status=CoverageStatus.COMPLETE,
            issued_time=t_0900,
            available_time=t_0900,
            revision_seq=1,
        )
        auth_res_b4 = builder.validate_and_build(
            coverage_records=(cov_rec_b4,),
            usage_records=(usg_rec_tjl1_b1, usg_rec_tjl2_b1),
            evaluation_time=t_b4,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_0900,
            physical_levels=(lvl_tjl1, lvl_tjl2),
        )
        ctx_b4, _ = builder.build_matching_context(
            authority_result=auth_res_b4,
            base_members=snap_act_touched.current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=t_b4,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t_0900,
            source_resolution_status=synthetic_source_res,
            active_activations=snap_act_touched.active_activations,
        )
        res_batch_b4 = matcher.match_batch(
            activations=list(snap_act_touched.active_activations.values()),
            evidences=[],
            context=ctx_b4,
        )
        assert len(res_batch_b4.unique_candidates) == 0
        eval_log.append({"boundary": "4_pre_close", "candidates": 0})

        # =========================================================================
        # Boundary 5: At Confirmation Close & Post-Close Evaluation (10:00 / 10:30 UTC)
        # =========================================================================
        # Process completing candle 9 (closes at 10:00 UTC)
        choch_coord.process_candle(choch_candles[9])
        assert len(choch_coord.confirmed_choch_events) == 1
        choch_event = choch_coord.confirmed_choch_events[0]
        assert choch_event.choch_type == ChochType.BEARISH_CHOCH
        assert choch_event.c2_candle_index == 9
        t_1000 = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
        assert choch_event.confirmation_time == t_1000

        # Authoritative candle lookup from confirming candle
        confirming_candle = choch_candles[choch_event.c2_candle_index]
        assert confirming_candle.close_time == t_1000

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

        # Item 4: Coverage certificate covers through last required completed bar (10:00 UTC)
        # Issued and available at 10:00 UTC. Evaluation at 10:30 UTC.
        t_eval_b5 = datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc)
        cov_rec_b5 = ProposedFeedCoverageRecord(
            record_id="COV_H1_1000",
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
        auth_res_b5 = builder.validate_and_build(
            coverage_records=(cov_rec_b5,),
            usage_records=(usg_rec_tjl1_b1, usg_rec_tjl2_b1),
            evaluation_time=t_eval_b5,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl_tjl1, lvl_tjl2),
        )
        assert auth_res_b5.resolved_coverage_status == CoverageStatus.COMPLETE

        ctx_b5, _ = builder.build_matching_context(
            authority_result=auth_res_b5,
            base_members=snap_act_touched.current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=t_eval_b5,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t_1000,
            source_resolution_status=synthetic_source_res,
            active_activations=snap_act_touched.active_activations,
        )

        match_res = matcher.match(act_rec_b3, evidence, ctx_b5)
        assert match_res.status == ConfirmationMatchStatus.MATCHED
        assert match_res.candidate_record is not None
        cand = match_res.candidate_record

        # Concrete positive assertions: canonical identity, entry price, provenance
        assert cand.activation_id == act_rec_b3.activation_id
        assert cand.confirmation_event_ids == (evidence.event_id,)
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.entry_reference_price == 1.0850
        assert cand.provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED

        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx_b5.domain_session_id,
            revision_id=ctx_b5.revision_id,
            activation_id=act_rec_b3.activation_id,
            source_member_key=act_rec_b3.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"
        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id

        # Batch matcher produces the exact same unique candidate
        res_batch_b5 = matcher.match_batch(
            activations=list(snap_act_touched.active_activations.values()),
            evidences=[evidence],
            context=ctx_b5,
        )
        assert len(res_batch_b5.unique_candidates) == 1
        assert res_batch_b5.unique_candidates[0] == cand
        eval_log.append({"boundary": "5_at_confirmation", "candidates": 1})

        # Verification of complete chronological progression
        assert [e["candidates"] for e in eval_log] == [0, 0, 0, 0, 1]
