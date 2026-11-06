"""Offline source-to-candidate integration proof tests — Genuine Chains and Chronological Prefixes.

Covers:
- INT-03: Complete chain from genuine source level set (TJLCoordinator on declared daily timeline)
  -> atomic sync via TJLSynchronizer -> exact physical touch -> continuous CHOCH detection
  -> ValidatedCandleStreamEnvelope -> ConfirmationMatcher -> exact canonical setup key.
- INT-04: Complete chain from genuine source level set (TJLCoordinator on declared daily timeline)
  -> atomic sync via TJLSynchronizer -> exact physical touch on TJL2 -> continuous ISS detection
  -> ValidatedCandleStreamEnvelope -> ConfirmationMatcher -> exact canonical setup key.
- Chronological event/evaluation schedule: Evaluates actual source, activation, detector, and matcher
  states at each causal boundary:
  * Pre-formation: No eligible set exists; 0 candidates.
  * Post-formation / Pre-touch: Members registered in INACTIVE_ELIGIBLE; matcher rejects fail-closed
    with INELIGIBLE_ACTIVATION_STATE; 0 candidates.
  * Post-touch / Pre-confirmation: Record in PENDING_ACTIVATION.
  * Future Evidence / Pre-Close: Evaluating completed future evidence against earlier evaluation time
    (T_eval < T_close) decisively rejects fail-closed with EVIDENCE_NOT_YET_AVAILABLE; 0 candidates.
  * At/After Confirmation Close: Matcher matches with MATCHED, emitting exact runtime-derived candidate setup key.
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
from aladeen.strategy.choch_types import ChochType
from aladeen.strategy.confirmation_adapters import (
    ValidatedCandleStreamEnvelope,
    adapt_confirmed_choch_to_evidence,
    adapt_confirmed_iss_to_evidence,
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
from aladeen.strategy.iss_engine import ISSEngine
from aladeen.strategy.iss_types import ISSConfig, ISSLifecycleStatus
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_001")


def load_tjl_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / "tjl_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def load_choch_fixture(name: str = "choch_bearish_basic_end_to_end") -> Dict[str, Any]:
    with open(FIXTURES_DIR / "choch_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def load_iss_fixture(name: str = "iss_02_bullish_basic_end_to_end") -> Dict[str, Any]:
    with open(FIXTURES_DIR / "iss_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def build_synthesized_daily_source_candles(
    raw_fixture_candles: List[Dict[str, Any]],
    start_date: datetime = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
) -> List[StrategyCandle]:
    """Synthetic fixture preparation: Map fixture OHLC patterns to an explicit daily (D1) timeline.

    Assumes continuous 24-hour daily sessions starting at 00:00 UTC, each lasting exactly 1 day.
    Explicitly labeled as synthetic fixture preparation to satisfy D1 -> H1 timeframe mapping consistency.
    Requires explicit fixture fields (open, high, low, close, is_forming, bar_status) without default fallbacks.
    """
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


class TestSourceCandidateChains:
    """Integration proof tests for genuine source-to-candidate chains (INT-03, INT-04)."""

    def test_int_03_genuine_source_exact_print_choch_end_to_end_with_chronological_trace(self) -> None:
        """INT-03: Complete chronological chain from genuine source D1 set to exact print to CHOCH confirmation.

        Executes an actual chronological event/evaluation schedule:
        1. Pre-formation boundary (Days 0..8): no eligible set exists; 0 candidates.
        2. Set formation boundary (Day 9 close at 2026-10-11 00:00 UTC): SET_1 forms; sync registers
           members as INACTIVE_ELIGIBLE; pre-touch evaluation rejects fail-closed with INELIGIBLE_ACTIVATION_STATE; 0 candidates.
        3. Touch boundary (2026-10-11 08:30 UTC): exact price print transitions activation to PENDING_ACTIVATION.
        4. Pre-confirmation close / future evidence boundary (T_eval = 2026-10-11 15:30 UTC): evaluating completed
           evidence closing at 16:00 UTC against earlier evaluation boundary rejects fail-closed with EVIDENCE_NOT_YET_AVAILABLE; 0 candidates.
        5. At/after confirmation close (2026-10-11 16:30 UTC): confirming candle 9 closes at 16:00 UTC; detector confirms;
           matcher produces CandidateSetupRecord with exact canonical setup key and candidate ID.
        """
        matcher = ConfirmationMatcher()
        eval_log: List[Dict[str, Any]] = []

        # --- Stage 1 & 2: Genuine Source Chain on Declared Daily (D1) Timeline ---
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        source_start_date = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        source_candles = build_synthesized_daily_source_candles(fix_tjl["candles"], start_date=source_start_date)
        # Validate interval provenance: each candle spans exactly 1 day (D1)
        assert all(c.close_time - c.open_time == timedelta(days=1) for c in source_candles)

        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=source_start_date),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )

        # Boundary 1: Chronological pre-formation evaluation (Days 0..8)
        for i in range(9):
            source_coord.process_candle(source_candles[i])
        snap_pre9 = source_coord.get_snapshot()
        assert snap_pre9.current_eligible_set is None
        eval_log.append({
            "boundary": "1_pre_formation",
            "time": source_candles[8].close_time.isoformat(),
            "has_set": False,
        })

        # Process Day 9 (close at 2026-10-11 00:00:00 UTC) -> SET_1 formed
        source_coord.process_candle(source_candles[9])
        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set
        assert cset.set_id == "SET_1"
        assert cset.direction == Direction.DOWNWARD
        assert cset.tjl1_zone.lower_price == 1.1800
        assert cset.tjl1_zone.upper_price == 1.1850
        assert cset.eligibility_available_time == datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        eval_log.append({
            "boundary": "2a_set_formed",
            "time": cset.eligibility_available_time.isoformat(),
            "set_id": cset.set_id,
        })

        # --- Boundary 2b: Synchronize to ActivationEngine and Chronological Pre-Touch Evaluation ---
        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        usage_evidence = {
            cset.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            cset.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        snap_act_sync = synchronizer.sync(snap_tjl, sequence_ref_start=1001, usage_evidence=usage_evidence)
        assert len(snap_act_sync.current_members) == 2
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        mem_tjl1 = snap_act_sync.current_members[mem_key_tjl1]
        assert mem_tjl1.usage_evidence_status == UsageEvidenceStatus.UNUSED

        # Registered member in active_activations is in state INACTIVE_ELIGIBLE (Gen 0)
        assert mem_key_tjl1 in snap_act_sync.active_activations
        act_pre_touch = snap_act_sync.active_activations[mem_key_tjl1]
        assert act_pre_touch.state == ActivationState.INACTIVE_ELIGIBLE
        assert act_pre_touch.generation_seq == 0

        # Decisive chronological evaluation prior to physical touch (at 2026-10-11 04:00 UTC)
        ctx_pre_touch = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_sync.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_sync.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        dummy_ev_pre_touch = ConfirmationEvidenceRecord(
            event_id="EV_EARLY",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_EARLY",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        res_pre_touch = matcher.match(act_pre_touch, dummy_ev_pre_touch, ctx_pre_touch)
        assert res_pre_touch.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res_pre_touch.rejection_reasons
        assert res_pre_touch.candidate_record is None
        eval_log.append({
            "boundary": "2b_pre_touch_rejected",
            "time": ctx_pre_touch.evaluation_time.isoformat(),
            "status": res_pre_touch.status.value,
            "reasons": [r.value for r in res_pre_touch.rejection_reasons],
        })

        # --- Boundary 3: Physical Observation Exact Price Print Touch ---
        touch_time = datetime(2026, 10, 11, 8, 30, tzinfo=timezone.utc)
        assert touch_time >= cset.eligibility_available_time

        print_touch = ExactPricePrint(
            observation_id="OBS_PRINT_01",
            price=1.1825,  # Strictly within [1.1800, 1.1850]
            price_basis=PriceBasis.BID,
            timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_act_touched = act_engine.process_event(print_touch)
        assert mem_key_tjl1 in snap_act_touched.active_activations
        act_record = snap_act_touched.active_activations[mem_key_tjl1]
        assert act_record.state == ActivationState.PENDING_ACTIVATION
        assert act_record.first_touch_time == touch_time
        assert act_record.generation_seq == 1
        eval_log.append({
            "boundary": "3_touched",
            "time": touch_time.isoformat(),
            "state": act_record.state.value,
        })

        # --- Boundary 4: Continuous Confirmation Detection on Declared H1 Timeline ---
        # Maps CHOCH fixture OHLC pattern onto an explicitly labeled synthesized H1 timeline
        # (1-hour candle duration) on 2026-10-11, satisfying D1 -> H1 confirmation mapping.
        fix_choch = load_choch_fixture("choch_bearish_basic_end_to_end")
        base_time_choch = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)
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
        assert all(c.close_time - c.open_time == timedelta(hours=1) for c in choch_candles)

        choch_coord = MSMChochCoordinator(
            MSMConfig(start_candle_time=base_time_choch, direction=Direction.UPWARD)
        )

        # Process candles up to bar 8 (closing at 15:00 UTC)
        for i in range(9):
            choch_coord.process_candle(choch_candles[i])
        assert len(choch_coord.confirmed_choch_events) == 0

        # Process bar 9 (closes at 16:00 UTC) -> confirms bearish CHOCH
        choch_coord.process_candle(choch_candles[9])
        assert len(choch_coord.confirmed_choch_events) == 1
        choch_event = choch_coord.confirmed_choch_events[0]
        assert choch_event.choch_type == ChochType.BEARISH_CHOCH
        assert choch_event.c2_candle_index == 9
        assert choch_event.confirmation_time == datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)

        confirming_candle = choch_candles[choch_event.c2_candle_index]
        assert confirming_candle.close_time == choch_event.confirmation_time
        assert touch_time < choch_event.confirmation_time  # 08:30 UTC < 16:00 UTC

        envelope = ValidatedCandleStreamEnvelope(
            candle=confirming_candle,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            timeframe="H1",
            price_basis=PriceBasis.BID,
            confirmation_config_id="CONF_CFG_01",
            confirmation_candle_id="CANDLE_09",
            sequence_domain=DEFAULT_DOMAIN,
        )
        evidence = adapt_confirmed_choch_to_evidence(
            choch=choch_event,
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_09",
            envelope=envelope,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
        )

        # Boundary 4a: Decisive check of future completed evidence against earlier evaluation time
        # Evaluation time is 15:30 UTC, but evidence close timestamp is 16:00 UTC (future!)
        ctx_pre_close = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 15, 30, tzinfo=timezone.utc),  # Before close (16:00 UTC)
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_pre_close = matcher.match(act_record, evidence, ctx_pre_close)
        assert res_pre_close.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE in res_pre_close.rejection_reasons
        assert res_pre_close.candidate_record is None
        eval_log.append({
            "boundary": "4a_pre_close_future_evidence_rejected",
            "time": ctx_pre_close.evaluation_time.isoformat(),
            "status": res_pre_close.status.value,
            "reasons": [r.value for r in res_pre_close.rejection_reasons],
        })

        # --- Boundary 5: At/After Confirmation Close Matcher Evaluation ---
        ctx_at_close = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 16, 30, tzinfo=timezone.utc),  # After close (16:00 UTC)
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res = matcher.match(act_record, evidence, ctx_at_close)

        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.entry_reference_price == 1.0850  # Confirming candle close price
        assert cand.provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED
        assert cand.is_consolidated is False

        # Assert canonical identity using runtime-derived format functions
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx_at_close.domain_session_id,
            revision_id=ctx_at_close.revision_id,
            activation_id=act_record.activation_id,
            source_member_key=act_record.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"

        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id
        eval_log.append({
            "boundary": "5_matched_at_close",
            "time": ctx_at_close.evaluation_time.isoformat(),
            "status": res.status.value,
            "candidate_id": cand.candidate_id,
        })

        # Decisively verify all 6 distinct chronological evaluation boundaries logged actual outcomes
        assert len(eval_log) == 6

    def test_int_04_genuine_source_exact_print_iss_end_to_end_with_chronological_trace(self) -> None:
        """INT-04: Complete chronological chain from genuine source D1 set to exact print to ISS confirmation.

        Executes an actual chronological event/evaluation schedule:
        1. Pre-formation & formation: Source D1 timeline processes candles 0..9. SET_1 forms with eligibility at 2026-10-11 00:00 UTC.
        2. Sync & Pre-touch evaluation (T_eval = 2026-10-11 04:00 UTC): INACTIVE_ELIGIBLE rejects fail-closed with INELIGIBLE_ACTIVATION_STATE.
        3. Touch boundary (2026-10-11 15:00 UTC): exact price print on TJL2 zone [1.2000, 1.2050] transitions to PENDING_ACTIVATION.
        4. Pre-confirmation close / future evidence boundary (T_eval = 2026-10-11 20:30 UTC): completed evidence
           closing at 21:00 UTC evaluated against earlier boundary rejects fail-closed with EVIDENCE_NOT_YET_AVAILABLE.
        5. At/after confirmation close (2026-10-11 22:00 UTC): confirming candle 20 closes at 21:00 UTC; detector confirms;
           matcher produces CandidateSetupRecord with exact canonical setup key and candidate ID.
        """
        matcher = ConfirmationMatcher()
        eval_log: List[Dict[str, Any]] = []

        # --- Stage 1: Genuine Source Chain on Declared Daily (D1) Timeline ---
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        source_start_date = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        source_candles = build_synthesized_daily_source_candles(fix_tjl["candles"], start_date=source_start_date)
        assert all(c.close_time - c.open_time == timedelta(days=1) for c in source_candles)

        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=source_start_date),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        for i in range(10):
            source_coord.process_candle(source_candles[i])

        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set
        assert cset.eligibility_available_time == datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)

        # --- Stage 2: Synchronize to Activation Engine & Pre-Touch Gating ---
        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        usage_evidence = {
            cset.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            cset.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        snap_act_sync = synchronizer.sync(snap_tjl, sequence_ref_start=1001, usage_evidence=usage_evidence)
        mem_key_tjl2 = format_member_key("SET_1", "TJL2_A_PLUS")
        mem_tjl2 = snap_act_sync.current_members[mem_key_tjl2]
        assert mem_tjl2.lower_edge == 1.2000
        assert mem_tjl2.upper_edge == 1.2050

        # Pre-touch chronological evaluation
        act_pre_touch = snap_act_sync.active_activations[mem_key_tjl2]
        assert act_pre_touch.state == ActivationState.INACTIVE_ELIGIBLE
        ctx_pre_touch = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_sync.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_sync.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        dummy_ev = ConfirmationEvidenceRecord(
            event_id="EV_EARLY_ISS",
            producer_id="PROD_ISS",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="ISS",
            close_price=1.1120,
            close_timestamp=datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        res_pre_touch = matcher.match(act_pre_touch, dummy_ev, ctx_pre_touch)
        assert res_pre_touch.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res_pre_touch.rejection_reasons
        eval_log.append({
            "boundary": "1_pre_touch_rejected",
            "time": ctx_pre_touch.evaluation_time.isoformat(),
            "status": res_pre_touch.status.value,
        })

        # --- Stage 3: Physical Observation Exact Price Print Touch on TJL2 ---
        touch_time = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)
        assert touch_time >= cset.eligibility_available_time
        print_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_ISS",
            price=1.2025,
            price_basis=PriceBasis.BID,
            timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_act_touched = act_engine.process_event(print_touch)
        act_record = snap_act_touched.active_activations[mem_key_tjl2]
        assert act_record.state == ActivationState.PENDING_ACTIVATION
        eval_log.append({
            "boundary": "2_touched",
            "time": touch_time.isoformat(),
            "state": act_record.state.value,
        })

        # --- Stage 4: Continuous ISS Detection on Declared H1 Timeline ---
        # Maps ISS fixture OHLC pattern onto an explicitly labeled synthesized H1 timeline
        # (1-hour candle duration) on 2026-10-11, satisfying D1 -> H1 confirmation mapping.
        fix_iss = load_iss_fixture("iss_02_bullish_basic_end_to_end")
        base_time_iss = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        interval_h1 = timedelta(hours=1)
        iss_candles = [
            StrategyCandle(
                index=i,
                open_time=base_time_iss + (interval_h1 * i),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=base_time_iss + (interval_h1 * (i + 1)),
            )
            for i, c in enumerate(fix_iss["candles"])
        ]
        assert all(c.close_time - c.open_time == timedelta(hours=1) for c in iss_candles)

        iss_engine = ISSEngine(
            ISSConfig(main_direction=Direction.UPWARD, start_candle_time=base_time_iss)
        )
        snap_iss = iss_engine.process_candles(iss_candles)
        assert snap_iss.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap_iss.confirmed_events) > 0
        iss_event = snap_iss.confirmed_events[0]
        assert iss_event.confirmation_candle_index == 20
        assert iss_event.completion_close_price == 1.1120
        assert iss_event.confirmation_time == datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)

        confirming_candle = iss_candles[iss_event.confirmation_candle_index]
        assert confirming_candle.close_time == iss_event.confirmation_time
        assert touch_time < iss_event.confirmation_time  # 15:00 UTC < 21:00 UTC

        envelope = ValidatedCandleStreamEnvelope(
            candle=confirming_candle,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            timeframe="H1",
            price_basis=PriceBasis.BID,
            confirmation_config_id="CONF_CFG_01",
            confirmation_candle_id="CANDLE_20",
            sequence_domain=DEFAULT_DOMAIN,
        )
        evidence = adapt_confirmed_iss_to_evidence(
            iss=iss_event,
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_20",
            envelope=envelope,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
        )

        # Boundary 4a: Chronological check of future evidence against earlier evaluation boundary (20:30 UTC)
        ctx_pre_close = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc),  # Before close (21:00 UTC)
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_pre_close = matcher.match(act_record, evidence, ctx_pre_close)
        assert res_pre_close.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE in res_pre_close.rejection_reasons
        assert res_pre_close.candidate_record is None
        eval_log.append({
            "boundary": "3_pre_close_future_evidence_rejected",
            "time": ctx_pre_close.evaluation_time.isoformat(),
            "status": res_pre_close.status.value,
        })

        # --- Boundary 5: At/After Confirmation Close Matcher Evaluation ---
        ctx_at_close = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc),  # After close (21:00 UTC)
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res = matcher.match(act_record, evidence, ctx_at_close)

        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.entry_reference_price == 1.1120

        # Assert canonical identity using runtime-derived format functions
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx_at_close.domain_session_id,
            revision_id=ctx_at_close.revision_id,
            activation_id=act_record.activation_id,
            source_member_key=act_record.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"

        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id
        eval_log.append({
            "boundary": "4_matched_at_close",
            "time": ctx_at_close.evaluation_time.isoformat(),
            "status": res.status.value,
            "candidate_id": cand.candidate_id,
        })

        assert len(eval_log) == 4
