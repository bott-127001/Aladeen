"""Offline source-to-candidate integration proof tests — CHOCH Chain and Chronological Prefixes.

Covers:
- INT-03: Complete chronological chain from genuine source D1 level set (TJLCoordinator on declared daily timeline)
  -> atomic sync via TJLSynchronizer -> exact physical touch -> continuous interleaved CHOCH detection
  -> ValidatedCandleStreamEnvelope -> ConfirmationMatcher -> exact canonical setup key.
- Chronological event/evaluation schedule: Evaluates actual source, activation, detector, and matcher
  states at each causal boundary:
  * Boundary 1 (Before touch, 07:00 UTC): Detector processes candles closed by 07:00 UTC; active activations
    in INACTIVE_ELIGIBLE; batch matcher evaluated with empty evidence asserts zero candidates.
  * Boundary 2 (At touch, 07:30 UTC): Exact price print inside zone transitions record to PENDING_ACTIVATION;
    retained detector state (zero confirmed events); batch matcher asserts zero candidates.
  * Boundary 3 (Immediately before confirmation close, 09:30 UTC): Detector processes candles through bar 8;
    completing bar 9 is NOT processed; zero confirmed events; batch matcher asserts zero candidates.
  * Boundary 4 (At confirmation close, 10:00 UTC): Completing bar 9 is processed; CHOCH confirms;
    ValidatedCandleStreamEnvelope bound; matcher evaluated at 10:30 UTC matches with MATCHED and exact canonical identity.
  * Boundary 5 (Repeated evaluation): Complete ConfirmationMatchResult equality across repeated calls.
- Separate Negative Assertion: Completed evidence closing at 10:00 UTC evaluated against earlier boundary
  (T_eval = 09:30 UTC < 10:00 UTC) decisively rejects fail-closed with EVIDENCE_NOT_YET_AVAILABLE; zero candidates.
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
DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_001")


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


class TestSourceCandidateChochChain:
    """Integration proof test for genuine source-to-candidate CHOCH chain (INT-03)."""

    def test_int_03_genuine_source_exact_print_choch_chronological_schedule(self) -> None:
        """INT-03: Chronological event/evaluation schedule for D1 source + touch + CHOCH confirmation."""
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

        # Process Days 0..8
        for i in range(9):
            source_coord.process_candle(source_candles[i])
        assert source_coord.get_snapshot().current_eligible_set is None

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

        # Synchronize to Activation Engine
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
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        assert mem_key_tjl1 in snap_act_sync.active_activations
        assert snap_act_sync.active_activations[mem_key_tjl1].state == ActivationState.INACTIVE_ELIGIBLE

        # --- Stage 2: Confirmation Stream Preparation (H1 Timeline on 2026-10-11) ---
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
        assert all(c.close_time - c.open_time == timedelta(hours=1) for c in choch_candles)

        choch_coord = MSMChochCoordinator(
            MSMConfig(start_candle_time=base_time_choch, direction=Direction.UPWARD)
        )

        # =========================================================================
        # Boundary 1: Before Touch (at 2026-10-11 07:00 UTC)
        # =========================================================================
        # Detector processes only confirmation candles closed by 07:00 UTC (candles 0..6)
        for i in range(7):
            choch_coord.process_candle(choch_candles[i])
        assert len(choch_coord.confirmed_choch_events) == 0

        # State check: Activation is still INACTIVE_ELIGIBLE; detector has 0 confirmed events
        act_rec_b1 = snap_act_sync.active_activations[mem_key_tjl1]
        assert act_rec_b1.state == ActivationState.INACTIVE_ELIGIBLE

        # Batch matcher evaluation with available evidence (empty list): asserts 0 candidates
        ctx_b1 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_sync.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_sync.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_batch_b1 = matcher.match_batch(
            activations=list(snap_act_sync.active_activations.values()),
            evidences=[],
            context=ctx_b1,
        )
        assert len(res_batch_b1.unique_candidates) == 0
        eval_log.append({"boundary": "1_before_touch", "candidates": len(res_batch_b1.unique_candidates)})

        # =========================================================================
        # Boundary 2: At Touch (at 2026-10-11 07:30 UTC)
        # =========================================================================
        # Exact price print inside zone [1.1800, 1.1850] arrives at 07:30 UTC
        touch_time = datetime(2026, 10, 11, 7, 30, tzinfo=timezone.utc)
        print_touch = ExactPricePrint(
            observation_id="OBS_PRINT_01",
            price=1.1825,
            price_basis=PriceBasis.BID,
            timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_act_touched = act_engine.process_event(print_touch)
        act_rec_b2 = snap_act_touched.active_activations[mem_key_tjl1]
        assert act_rec_b2.state == ActivationState.PENDING_ACTIVATION
        assert act_rec_b2.first_touch_time == touch_time
        assert act_rec_b2.generation_seq == 1

        # Detector state retained from Boundary 1 (still 0 confirmed events)
        assert len(choch_coord.confirmed_choch_events) == 0

        # Batch matcher evaluation at 07:30 UTC with available evidence ([]): asserts 0 candidates
        ctx_b2 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=touch_time,
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_batch_b2 = matcher.match_batch(
            activations=list(snap_act_touched.active_activations.values()),
            evidences=[],
            context=ctx_b2,
        )
        assert len(res_batch_b2.unique_candidates) == 0
        eval_log.append({"boundary": "2_at_touch", "candidates": len(res_batch_b2.unique_candidates)})

        # =========================================================================
        # Boundary 3: Immediately Before Confirmation Close (at 2026-10-11 09:30 UTC)
        # =========================================================================
        # Detector processes candle 7 (closed at 08:00) and candle 8 (closed at 09:00).
        # Completing candle 9 (closing at 10:00 UTC) is NOT processed yet.
        choch_coord.process_candle(choch_candles[7])
        choch_coord.process_candle(choch_candles[8])
        assert len(choch_coord.confirmed_choch_events) == 0

        # Derive available evidence from current detector state: empty list
        available_evidences_b3: List[ConfirmationEvidenceRecord] = []

        ctx_b3 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc),
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_batch_b3 = matcher.match_batch(
            activations=list(snap_act_touched.active_activations.values()),
            evidences=available_evidences_b3,
            context=ctx_b3,
        )
        assert len(res_batch_b3.unique_candidates) == 0
        eval_log.append({"boundary": "3_pre_close", "candidates": len(res_batch_b3.unique_candidates)})

        # =========================================================================
        # Boundary 4: At Confirmation Close (at 2026-10-11 10:00 UTC)
        # =========================================================================
        # Process the completing candle (candle 9, closes at 10:00 UTC)
        choch_coord.process_candle(choch_candles[9])
        assert len(choch_coord.confirmed_choch_events) == 1
        choch_event = choch_coord.confirmed_choch_events[0]
        assert choch_event.choch_type == ChochType.BEARISH_CHOCH
        assert choch_event.c2_candle_index == 9
        assert choch_event.confirmation_time == datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)

        confirming_candle = choch_candles[choch_event.c2_candle_index]
        assert confirming_candle.close_time == choch_event.confirmation_time
        assert touch_time < choch_event.confirmation_time  # 07:30 UTC < 10:00 UTC

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

        # Matcher evaluation at 10:30 UTC (after close at 10:00 UTC)
        ctx_b4 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_b4 = matcher.match(act_rec_b2, evidence, ctx_b4)
        assert res_b4.status == ConfirmationMatchStatus.MATCHED
        assert res_b4.candidate_record is not None
        cand = res_b4.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.entry_reference_price == 1.0850

        # Exact canonical identity assertion derived via accepted formatters
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx_b4.domain_session_id,
            revision_id=ctx_b4.revision_id,
            activation_id=act_rec_b2.activation_id,
            source_member_key=act_rec_b2.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"
        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id

        # Batch matcher also outputs the unique candidate
        res_batch_b4 = matcher.match_batch(
            activations=list(snap_act_touched.active_activations.values()),
            evidences=[evidence],
            context=ctx_b4,
        )
        assert len(res_batch_b4.unique_candidates) == 1
        assert res_batch_b4.unique_candidates[0] == cand
        eval_log.append({"boundary": "4_at_close", "candidates": 1, "candidate_id": cand.candidate_id})

        # =========================================================================
        # Boundary 5: Repeated Evaluation & Snapshot Equality
        # =========================================================================
        res_repeat = matcher.match(act_rec_b2, evidence, ctx_b4)
        assert res_repeat == res_b4
        eval_log.append({"boundary": "5_repeated_equal", "equal": True})

        # Decisively assert all 5 chronological boundaries executed and recorded actual outputs
        assert len(eval_log) == 5

        # =========================================================================
        # Separate Negative Assertion: Future-Evidence Injection Test
        # =========================================================================
        # Completed evidence (closing at 10:00 UTC) evaluated against earlier boundary (09:30 UTC)
        ctx_future = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc),  # 09:30 UTC < 10:00 UTC
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_future = matcher.match(act_rec_b2, evidence, ctx_future)
        assert res_future.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE in res_future.rejection_reasons
        assert res_future.candidate_record is None
