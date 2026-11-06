"""Offline source-to-candidate integration proof tests — ISS Chain and Chronological Prefixes.

Covers:
- INT-04: Complete chronological chain from genuine source D1 level set (TJLCoordinator on declared daily timeline)
  -> atomic sync via TJLSynchronizer -> exact physical touch on TJL2 -> continuous interleaved ISS detection
  -> ValidatedCandleStreamEnvelope -> ConfirmationMatcher -> exact canonical setup key.
- Chronological event/evaluation schedule: Evaluates actual source, activation, detector, and matcher
  states at each causal boundary:
  * Boundary 1 (Before touch, 12:00 UTC): Detector processes candles closed by 12:00 UTC; active activations
    in INACTIVE_ELIGIBLE; batch matcher evaluated with empty evidence asserts zero candidates.
  * Boundary 2 (At touch, 15:00 UTC): Exact price print inside TJL2 zone transitions record to PENDING_ACTIVATION;
    retained detector state (zero confirmed events); batch matcher asserts zero candidates.
  * Boundary 3 (Immediately before confirmation close, 20:30 UTC): Detector processes candles through bar 19;
    completing bar 20 is NOT processed; zero confirmed events; batch matcher asserts zero candidates.
  * Boundary 4 (At confirmation close, 21:00 UTC): Completing bar 20 is processed; ISS confirms;
    ValidatedCandleStreamEnvelope bound; matcher evaluated at 22:00 UTC matches with MATCHED and exact canonical identity.
  * Boundary 5 (Repeated evaluation): Complete ConfirmationMatchResult equality across repeated calls.
- Separate Negative Assertion: Completed evidence closing at 21:00 UTC evaluated against earlier boundary
  (T_eval = 20:30 UTC < 21:00 UTC) decisively rejects fail-closed with EVIDENCE_NOT_YET_AVAILABLE; zero candidates.
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
from aladeen.strategy.confirmation_adapters import (
    ValidatedCandleStreamEnvelope,
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
from aladeen.strategy.iss_engine import ISSEngine
from aladeen.strategy.iss_types import ISSConfig, ISSLifecycleStatus
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_001")


def load_tjl_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / "tjl_acceptance.json", "r", encoding="utf-8") as f:
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


class TestSourceCandidateIssChain:
    """Integration proof test for genuine source-to-candidate ISS chain (INT-04)."""

    def test_int_04_genuine_source_exact_print_iss_chronological_schedule(self) -> None:
        """INT-04: Chronological event/evaluation schedule for D1 source + touch on TJL2 + ISS confirmation."""
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
        mem_key_tjl2 = format_member_key("SET_1", "TJL2_A_PLUS")
        mem_tjl2 = snap_act_sync.current_members[mem_key_tjl2]
        assert mem_tjl2.lower_edge == 1.2000
        assert mem_tjl2.upper_edge == 1.2050

        # --- Stage 2: Confirmation Stream Preparation (H1 Timeline on 2026-10-11) ---
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

        # =========================================================================
        # Boundary 1: Before Touch (at 2026-10-11 12:00 UTC)
        # =========================================================================
        # ISS engine processes candles closed by 12:00 UTC (candles 0..11)
        for i in range(12):
            iss_engine.process_candle(iss_candles[i])
        snap_iss_b1 = iss_engine.get_snapshot()
        assert len(snap_iss_b1.confirmed_events) == 0

        # State check: Activation record is INACTIVE_ELIGIBLE
        act_rec_b1 = snap_act_sync.active_activations[mem_key_tjl2]
        assert act_rec_b1.state == ActivationState.INACTIVE_ELIGIBLE

        # Batch matcher evaluation with available evidence ([]): asserts 0 candidates
        ctx_b1 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
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
        # Boundary 2: At Touch (at 2026-10-11 15:00 UTC)
        # =========================================================================
        # Exact price print on TJL2 zone [1.2000, 1.2050] arrives at 15:00 UTC
        touch_time = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)
        print_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_ISS",
            price=1.2025,
            price_basis=PriceBasis.BID,
            timestamp=touch_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_act_touched = act_engine.process_event(print_touch)
        act_rec_b2 = snap_act_touched.active_activations[mem_key_tjl2]
        assert act_rec_b2.state == ActivationState.PENDING_ACTIVATION
        assert act_rec_b2.first_touch_time == touch_time

        # ISS engine processes candles 12..14 (closed by 15:00 UTC)
        for i in range(12, 15):
            iss_engine.process_candle(iss_candles[i])
        assert len(iss_engine.get_snapshot().confirmed_events) == 0

        # Batch matcher evaluation at 15:00 UTC with available evidence ([]): asserts 0 candidates
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
        # Boundary 3: Immediately Before Confirmation Close (at 2026-10-11 20:30 UTC)
        # =========================================================================
        # ISS engine processes candles 15..19 (closed by 20:00 UTC).
        # Completing candle 20 (closing at 21:00 UTC) is NOT processed yet.
        for i in range(15, 20):
            iss_engine.process_candle(iss_candles[i])
        assert len(iss_engine.get_snapshot().confirmed_events) == 0

        # Available evidence derived from current detector state: empty list
        available_evidences_b3: List[ConfirmationEvidenceRecord] = []

        ctx_b3 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc),
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
        # Boundary 4: At Confirmation Close (at 2026-10-11 21:00 UTC)
        # =========================================================================
        # Process completing candle 20 (closes at 21:00 UTC)
        iss_engine.process_candle(iss_candles[20])
        snap_iss_b4 = iss_engine.get_snapshot()
        assert snap_iss_b4.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap_iss_b4.confirmed_events) == 1
        iss_event = snap_iss_b4.confirmed_events[0]
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

        # Matcher evaluation at 22:00 UTC (after close at 21:00 UTC)
        ctx_b4 = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_b4 = matcher.match(act_rec_b2, evidence, ctx_b4)
        assert res_b4.status == ConfirmationMatchStatus.MATCHED
        assert res_b4.candidate_record is not None
        cand = res_b4.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.entry_reference_price == 1.1120

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

        assert len(eval_log) == 5

        # =========================================================================
        # Separate Negative Assertion: Future-Evidence Injection Test
        # =========================================================================
        # Completed evidence (closing at 21:00 UTC) evaluated against earlier boundary (20:30 UTC)
        ctx_future = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc),  # 20:30 UTC < 21:00 UTC
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_future = matcher.match(act_rec_b2, evidence, ctx_future)
        assert res_future.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE in res_future.rejection_reasons
        assert res_future.candidate_record is None
