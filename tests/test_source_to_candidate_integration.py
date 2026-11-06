"""Offline source-to-candidate integration proof tests for Milestone 33.

Scope & Design Boundary:
-------------------------
- Demonstrates complete offline source-to-candidate integration connecting:
  1. Genuine source level set and member emission from TJLCoordinator.
  2. TJLSynchronizer atomic synchronization into ActivationEngine.
  3. Discrete, scoped physical ExactPricePrint observations driving activation lifecycle.
  4. Independent continuous confirmation detection (MSMChochCoordinator, ISSEngine).
  5. Authoritative candle lookup from processed collection + ValidatedCandleStreamEnvelope binding.
  6. ConfirmationMatcher evaluation asserting candidate identity, side, close price, and provenance.
- Demonstrates decisive lifecycle assertions:
  * INT-03: Genuine source + exact print + continuous CHOCH detection.
  * INT-04: Genuine source + exact print + continuous canonical ISS detection.
  * ACT-02: Source replacement terminal non-revival (MEMBERSHIP_CANCELLED_OR_REPLACED).
  * ACT-03: Source Main CHOCH invalidation terminal non-revival (INELIGIBLE_ACTIVATION_STATE).
  * ACT-01: Rearm Path A (inside at cancel -> outside print -> retouch Gen 2 -> immutable predecessor).
  * ACT-04: Rearm Path B (already outside at cancel -> direct arm -> retouch Gen 2).
  * ORD-01 to ORD-04: Equal-time causal ordering matrix.
  * Repeated evaluation and input immutability.
- Strictly offline, read-only calculation layer. Zero network, zero MT5, zero live execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from aladeen.strategy.activation_adapter import TJLSynchronizer, adapt_tjl_current_set
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
    format_member_key,
)
from aladeen.strategy.coordinator import MSMChochCoordinator
from aladeen.strategy.choch_types import ChochType
from aladeen.strategy.confirmation_adapters import (
    ValidatedCandleStreamEnvelope,
    adapt_confirmed_choch_to_evidence,
    adapt_confirmed_iss_to_evidence,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
    TouchSequenceEvidence,
)
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


def adapt_strategy_candles(raw_candles: List[Dict[str, Any]]) -> List[StrategyCandle]:
    candles: List[StrategyCandle] = []
    for i, c in enumerate(raw_candles):
        candles.append(
            StrategyCandle(
                index=i,
                open_time=datetime.fromisoformat(c["time"]),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c.get("is_forming", False)),
                bar_status=str(c.get("bar_status", "CONFIRMED_COMPLETED")),
                close_time=datetime.fromisoformat(c["close_time"]),
            )
        )
    return candles


class TestSourceToCandidateIntegration:
    """Comprehensive offline integration proof tests for Milestone 33."""

    def test_int_03_genuine_source_exact_print_choch_end_to_end(self) -> None:
        """INT-03: Complete chain from genuine source level set to exact print activation to CHOCH confirmation."""
        # --- Prefix 1: Genuine Source Chain (TJLCoordinator) ---
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        start_time_tjl = datetime.fromisoformat(fix_tjl["start_candle_time"])
        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time_tjl),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        source_candles = adapt_strategy_candles(fix_tjl["candles"])
        for c in source_candles:
            source_coord.process_candle(c)

        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set
        assert cset.set_id == "SET_1"
        assert cset.direction == Direction.DOWNWARD
        assert cset.tjl1_zone.lower_price == 1.1800
        assert cset.tjl1_zone.upper_price == 1.1850

        # --- Prefix 2: Synchronize to Activation Engine via TJLSynchronizer ---
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
        assert mem_tjl1.lower_edge == 1.1800
        assert mem_tjl1.upper_edge == 1.1850

        # --- Prefix 3: Physical Observation Exact Price Print Touch ---
        touch_time = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)
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
        assert act_record.trigger_observation_id == "OBS_PRINT_01"

        # --- Prefix 4: Independent Continuous Confirmation Detection (CHOCH) ---
        fix_choch = load_choch_fixture("choch_bearish_basic_end_to_end")
        base_time_choch = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
        interval_h1 = timedelta(hours=1)
        choch_candles = [
            StrategyCandle(
                index=i,
                open_time=base_time_choch + (interval_h1 * i),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                close_time=base_time_choch + (interval_h1 * (i + 1)),
            )
            for i, c in enumerate(fix_choch["candles"])
        ]
        choch_coord = MSMChochCoordinator(
            MSMConfig(start_candle_time=base_time_choch, direction=Direction.UPWARD)
        )
        choch_coord.process_candles(choch_candles)
        assert len(choch_coord.confirmed_choch_events) == 1
        choch_event = choch_coord.confirmed_choch_events[0]
        assert choch_event.choch_type == ChochType.BEARISH_CHOCH
        assert choch_event.c2_candle_index == 9

        # --- Prefix 5: Direct Confirming Candle Lookup & Validated Stream Envelope ---
        confirming_candle = choch_candles[choch_event.c2_candle_index]
        assert confirming_candle.close_time == choch_event.confirmation_time
        assert touch_time < choch_event.confirmation_time

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

        # --- Prefix 6: Matcher Evaluation & Candidate Formation ---
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res = matcher.match(act_record, evidence, ctx)

        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.source_timeframe == "D1"
        assert cand.confirmation_timeframe == "H1"
        assert cand.entry_reference_price == 1.0850
        assert cand.provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED
        assert cand.is_consolidated is False
        assert cand.candidate_id.startswith("CAND[")
        assert "CSK[" in cand.candidate_id

    def test_int_04_genuine_source_exact_print_iss_end_to_end(self) -> None:
        """INT-04: Complete chain from genuine source level set to exact print activation to ISS confirmation."""
        # --- Prefix 1: Genuine Source Chain (TJLCoordinator) ---
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        start_time_tjl = datetime.fromisoformat(fix_tjl["start_candle_time"])
        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time_tjl),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        source_candles = adapt_strategy_candles(fix_tjl["candles"])
        for c in source_candles:
            source_coord.process_candle(c)

        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set

        # --- Prefix 2: Synchronize to Activation Engine ---
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

        # --- Prefix 3: Physical Observation Exact Price Print Touch on TJL2 ---
        touch_time = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
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

        # --- Prefix 4: Independent Continuous ISS Detection ---
        fix_iss = load_iss_fixture("iss_02_bullish_basic_end_to_end")
        iss_candles = [
            StrategyCandle(
                index=i,
                open_time=datetime.fromisoformat(c["time"]).astimezone(timezone.utc),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=datetime.fromisoformat(c["close_time"]).astimezone(timezone.utc),
            )
            for i, c in enumerate(fix_iss["candles"])
        ]
        iss_engine = ISSEngine(
            ISSConfig(main_direction=Direction.UPWARD, start_candle_time=iss_candles[0].open_time)
        )
        snap_iss = iss_engine.process_candles(iss_candles)
        assert snap_iss.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        iss_event = snap_iss.confirmed_events[0]
        assert iss_event.confirmation_candle_index == 20
        assert iss_event.completion_close_price == 1.1120

        # --- Prefix 5: Direct Confirming Candle Lookup & Validated Stream Envelope ---
        confirming_candle = iss_candles[iss_event.confirmation_candle_index]
        assert confirming_candle.close_time == iss_event.confirmation_time
        assert touch_time < iss_event.confirmation_time

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

        # --- Prefix 6: Matcher Evaluation ---
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 23, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res = matcher.match(act_record, evidence, ctx)

        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        assert res.candidate_record.signal_side == "SELL"
        assert res.candidate_record.entry_reference_price == 1.1120

    def test_act_02_source_set_replacement_terminal_non_revival(self) -> None:
        """ACT-02: Source replacement permanently cancels outgoing activations; matching rejects fail-closed."""
        fix = load_tjl_fixture("tjl_06_pullback_t2_replacement_and_cancellation_intent")
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        candles = adapt_strategy_candles(fix["candles"])

        # Process candles up to SET_1 creation (bar 9)
        for i in range(10):
            coord.process_candle(candles[i])
        snap_s1 = coord.get_snapshot()
        assert snap_s1.current_eligible_set is not None
        assert snap_s1.current_eligible_set.set_id == "SET_1"

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
        usage = {
            snap_s1.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap_s1.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        synchronizer.sync(snap_s1, sequence_ref_start=1001, usage_evidence=usage)

        # Touch SET_1::TJL1 to activate
        mem_key_s1 = format_member_key("SET_1", "TJL1")
        print_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_S1",
            price=1.1825,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_touched = act_engine.process_event(print_touch)
        act_s1 = snap_touched.active_activations[mem_key_s1]
        assert act_s1.state == ActivationState.PENDING_ACTIVATION

        # Continue processing until SET_REPLACEMENT occurs (bar 16)
        for i in range(10, 17):
            coord.process_candle(candles[i])
        snap_s2 = coord.get_snapshot()
        assert snap_s2.current_eligible_set is not None
        assert snap_s2.current_eligible_set.set_id == "SET_2"

        usage_s2 = {
            snap_s2.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap_s2.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        snap_act_replaced = synchronizer.sync(snap_s2, sequence_ref_start=1004, usage_evidence=usage_s2)

        # Assert SET_1 is permanently cancelled
        assert mem_key_s1 not in snap_act_replaced.current_members
        assert mem_key_s1 not in snap_act_replaced.active_activations
        term_s1 = [t for t in snap_act_replaced.terminal_activations if t.activation_id == act_s1.activation_id]
        assert len(term_s1) == 1
        assert term_s1[0].state == ActivationState.CANCELLED_SOURCE_REPLACEMENT

        # Matcher rejects evidence matching replaced member
        evidence_dummy = adapt_confirmed_choch_to_evidence(
            choch=load_choch_fixture()["fixtures"] if False else MSMChochCoordinator(MSMConfig(datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), Direction.UPWARD)).confirmed_choch_events if False else None,  # type: ignore[arg-type]
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_09",
            envelope=ValidatedCandleStreamEnvelope(
                candle=StrategyCandle(9, datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc), 1.1, 1.2, 1.0, 1.15, False, "CONFIRMED_COMPLETED", datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)),
                symbol="FEED_EURUSD_D1",
                feed_id="FEED_EURUSD_D1",
                timeframe="H1",
                price_basis=PriceBasis.BID,
                confirmation_config_id="CONF_CFG_01",
                confirmation_candle_id="CANDLE_09",
                sequence_domain=DEFAULT_DOMAIN,
            ),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            close_price=1.15,
        ) if False else None  # Will use valid synthetic evidence

        from aladeen.strategy.confirmation_types import ConfirmationEvidenceRecord
        ev = ConfirmationEvidenceRecord(
            event_id="EVT_01",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_09",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.15,
            close_timestamp=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_replaced.current_members),  # Only SET_2 members!
            source_resolution_status={m_k: True for m_k in snap_act_replaced.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res = matcher.match(act_s1, ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res.rejection_reasons
        assert res.candidate_record is None

    def test_act_03_source_main_choch_invalidation_terminal_non_revival(self) -> None:
        """ACT-03: Source Main CHOCH invalidates pending activation; matching rejects fail-closed."""
        fix = load_tjl_fixture("tjl_09_source_choch_eligibility_invalidation_and_gap")
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        candles = adapt_strategy_candles(fix["candles"])

        # Process candles up to bar 8 (active SET_1)
        for i in range(8):
            coord.process_candle(candles[i])
        snap_s1 = coord.get_snapshot()

        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_H1",
                symbol="FEED_EURUSD_H1",
                source_timeframe="H1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        usage = {
            snap_s1.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap_s1.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        synchronizer.sync(snap_s1, sequence_ref_start=1001, usage_evidence=usage)

        # In-zone print activates TJL1
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        print_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_CH",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
        )
        snap_act = act_engine.process_event(print_touch)
        act_rec = snap_act.active_activations[mem_key_tjl1]
        assert act_rec.state == ActivationState.PENDING_ACTIVATION

        # Candles 8 and 9 Bearish CHOCH confirmation cancels SET_1
        coord.process_candle(candles[8])
        coord.process_candle(candles[9])
        snap_choch = coord.get_snapshot()
        assert snap_choch.current_eligible_set is None

        snap_act_inv = synchronizer.sync(snap_choch, sequence_ref_start=1005)
        assert len(snap_act_inv.current_members) == 0
        assert len(snap_act_inv.active_activations) == 0
        term_acts = snap_act_inv.terminal_activations
        assert len(term_acts) == 1
        assert term_acts[0].state == ActivationState.CANCELLED_SOURCE_CHOCH

        # Matcher rejects confirmation against invalidated activation
        from aladeen.strategy.confirmation_types import ConfirmationEvidenceRecord
        ev = ConfirmationEvidenceRecord(
            event_id="EVT_CH_01",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="M1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.UPWARD,
            pattern_type="CHOCH",
            close_price=1.1400,
            close_timestamp=datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_H1",
            feed_id="FEED_EURUSD_H1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc),
            current_members={},
            source_resolution_status={},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res = matcher.match(term_acts[0], ev, ctx)
        assert res.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res.rejection_reasons

    def test_act_01_rearm_path_a_inside_at_cancel_with_immutable_predecessor(self) -> None:
        """ACT-01: Rearm Path A: inside-at-cancel -> outside print -> inside retouch spawns Gen 2 linked record."""
        engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        mem = SourceMemberReference(
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
        engine.register_source_member(mem)

        # 1. Gen 1 Touch inside zone [1.1350, 1.1400]
        touch1_time = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        p1 = ExactPricePrint("OBS_01", 1.1375, PriceBasis.BID, touch1_time, DEFAULT_DOMAIN, 1001)
        snap1 = engine.process_event(p1)
        act1 = snap1.active_activations[mem.member_key]
        assert act1.state == ActivationState.PENDING_ACTIVATION
        assert act1.generation_seq == 1

        # 2. External commit cancellation while price is inside zone
        cancel_time = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
        c_evt = ExternalCommitEvent(
            event_id="EVT_EXT_CANCEL",
            timestamp=cancel_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1002,
            winning_engine_id="OTHER_ENGINE",
            winning_set_id="SET_OTHER",
            winning_role="OTHER_ROLE",
            cancelled_competing_scope="ENGINE_LOCAL",
            target_engine_id="ENGINE_EURUSD_D1",
            note="Competing entry committed",
        )
        snap2 = engine.process_event(c_evt)
        assert len(snap2.active_activations) == 0
        assert len(snap2.terminal_activations) == 1
        term_act1 = snap2.terminal_activations[0]
        assert term_act1.state == ActivationState.CANCELLED_EXTERNAL_ENTRY
        assert term_act1.generation_seq == 1

        # Decoupled controller spawned referencing prior_activation_id
        assert mem.member_key in snap2.rearm_controllers
        ctrl = snap2.rearm_controllers[mem.member_key]
        assert ctrl.prior_activation_id == act1.activation_id
        assert ctrl.last_observed_position == "INSIDE"
        assert ctrl.rearm_armed is False

        # 3. Fresh outside observation strictly later than cancellation
        out_time = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        p_out = ExactPricePrint("OBS_OUT", 1.1300, PriceBasis.BID, out_time, DEFAULT_DOMAIN, 1003)
        snap3 = engine.process_event(p_out)
        ctrl3 = snap3.rearm_controllers[mem.member_key]
        assert ctrl3.state == ActivationState.OUT_OF_ZONE_ARMED
        assert ctrl3.rearm_armed is True
        assert len(snap3.terminal_activations) == 1  # Predecessor permanently immutable

        # 4. Fresh physical inside touch print strictly later than outside observation
        retouch_time = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
        p_retouch = ExactPricePrint("OBS_RETOUCH", 1.1380, PriceBasis.BID, retouch_time, DEFAULT_DOMAIN, 1004)
        snap4 = engine.process_event(p_retouch)

        # Brand-new linked ActivationRecord Gen 2 in REARMED_PENDING
        assert mem.member_key in snap4.active_activations
        act2 = snap4.active_activations[mem.member_key]
        assert act2.state == ActivationState.REARMED_PENDING
        assert act2.generation_seq == 2
        assert act2.first_touch_time == retouch_time
        assert act2.trigger_observation_id == "OBS_RETOUCH"
        assert len(snap4.terminal_activations) == 1  # Predecessor unchanged

        # 5. Stale Gen 1 confirmation evidence rejects fail-closed
        from aladeen.strategy.confirmation_types import ConfirmationEvidenceRecord
        ev_stale = ConfirmationEvidenceRecord(
            event_id="EVT_STALE",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 8, 15, tzinfo=timezone.utc),  # Before Gen 2 touch!
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem.member_key: mem},
            source_resolution_status={mem.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res_stale = matcher.match(act2, ev_stale, ctx)
        assert res_stale.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_stale.rejection_reasons

        # 6. Fresh Gen 2 confirmation matches
        ev_fresh = ConfirmationEvidenceRecord(
            event_id="EVT_FRESH",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_02",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),  # After Gen 2 touch!
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        res_fresh = matcher.match(act2, ev_fresh, ctx)
        assert res_fresh.status == ConfirmationMatchStatus.MATCHED
        assert res_fresh.candidate_record is not None
        assert res_fresh.candidate_record.candidate_id.startswith("CAND[")

    def test_act_04_rearm_path_b_already_outside_at_cancel_with_immutable_predecessor(self) -> None:
        """ACT-04: Rearm Path B: already outside at cancellation -> arms directly -> retouch creates Gen 2."""
        engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        mem = SourceMemberReference(
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
        engine.register_source_member(mem)

        # 1. Gen 1 Touch
        t1 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        engine.process_event(ExactPricePrint("OBS_01", 1.1375, PriceBasis.BID, t1, DEFAULT_DOMAIN, 1001))

        # 2. Price observed outside zone before cancellation
        t_out = datetime(2026, 10, 1, 8, 15, tzinfo=timezone.utc)
        engine.process_event(ExactPricePrint("OBS_OUT", 1.1300, PriceBasis.BID, t_out, DEFAULT_DOMAIN, 1002))

        # 3. External commit cancellation occurs when price is already outside
        t_cancel = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
        c_evt = ExternalCommitEvent(
            event_id="EVT_EXT_CANCEL",
            timestamp=t_cancel,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
            winning_engine_id="OTHER_ENGINE",
            winning_set_id="SET_OTHER",
            winning_role="OTHER_ROLE",
            cancelled_competing_scope="ENGINE_LOCAL",
            target_engine_id="ENGINE_EURUSD_D1",
        )
        snap_cancel = engine.process_event(c_evt)

        # RearmController is armed directly as OUT_OF_ZONE_ARMED
        assert mem.member_key in snap_cancel.rearm_controllers
        ctrl = snap_cancel.rearm_controllers[mem.member_key]
        assert ctrl.state == ActivationState.OUT_OF_ZONE_ARMED
        assert ctrl.rearm_armed is True
        assert len(snap_cancel.terminal_activations) == 1

        # 4. Fresh inside retouch print strictly later than cancellation
        t_retouch = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        p_retouch = ExactPricePrint("OBS_RETOUCH_B", 1.1380, PriceBasis.BID, t_retouch, DEFAULT_DOMAIN, 1004)
        snap_retouch = engine.process_event(p_retouch)

        assert mem.member_key in snap_retouch.active_activations
        act2 = snap_retouch.active_activations[mem.member_key]
        assert act2.state == ActivationState.REARMED_PENDING
        assert act2.generation_seq == 2
        assert act2.first_touch_time == t_retouch

    def test_equal_time_causal_ordering_matrix(self) -> None:
        """ORD-01 to ORD-04: Timestamp tie between touch and confirmation evaluated via sequence ordering."""
        matcher = ConfirmationMatcher()
        touch_time = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)

        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        mem = SourceMemberReference(
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

        from aladeen.strategy.activation_types import format_activation_id
        act = ActivationRecord(
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
            first_touch_time=touch_time,
            first_touch_price=1.1375,
            trigger_observation_id="OBS_01",
            generation_seq=1,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )

        from aladeen.strategy.confirmation_types import ConfirmationEvidenceRecord

        # ORD-01: Timestamp tie without sequence reference rejects as UNKNOWN_ORDER
        ev_no_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_01",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,  # Equal to touch!
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=None,  # Missing!
        )
        ctx_no_seq = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem.member_key: mem},
            source_resolution_status={mem.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_ord1 = matcher.match(act, ev_no_seq, ctx_no_seq)
        assert res_ord1.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_ORDER in res_ord1.rejection_reasons

        # ORD-02: Cross-domain sequence references reject as CROSS_DOMAIN_ORDERING_REJECTED
        other_domain = SequenceDomain("FEED_OTHER", "RUN_OTHER")
        ev_cross = ConfirmationEvidenceRecord(
            event_id="EV_ORD_02",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=other_domain,  # Contradicts matching domain!
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1005,
        )
        ctx_with_seq = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem.member_key: mem},
            source_resolution_status={mem.member_key: True},
            touch_sequence_evidence={
                act.activation_id: TouchSequenceEvidence(DEFAULT_DOMAIN, 1002)
            },
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_ord2 = matcher.match(act, ev_cross, ctx_with_seq)
        assert res_ord2.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED in res_ord2.rejection_reasons

        # ORD-03: Confirmation sequence <= touch sequence rejects as PRE_ACTIVATION_CONFIRMATION
        ev_earlier_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_03",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1002,  # Exactly equal to touch sequence ref 1002!
        )
        res_ord3 = matcher.match(act, ev_earlier_seq, ctx_with_seq)
        assert res_ord3.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_ord3.rejection_reasons

        # ORD-04: Confirmation sequence strictly later (> 1002) in matching domain matches
        ev_later_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_04",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1005,  # Strictly later than touch sequence ref 1002!
        )
        res_ord4 = matcher.match(act, ev_later_seq, ctx_with_seq)
        assert res_ord4.status == ConfirmationMatchStatus.MATCHED
        assert res_ord4.candidate_record is not None

    def test_repeated_evaluation_and_input_immutability(self) -> None:
        """Deterministic repeated evaluation yields identical setup keys; input mappings remain frozen."""
        matcher = ConfirmationMatcher()
        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        mem = SourceMemberReference(
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
        from aladeen.strategy.activation_types import format_activation_id
        act = ActivationRecord(
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
        from aladeen.strategy.confirmation_types import ConfirmationEvidenceRecord
        ev = ConfirmationEvidenceRecord(
            event_id="EV_REP",
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

        members_map = {mem.member_key: mem}
        res_map = {mem.member_key: True}
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members=members_map,
            source_resolution_status=res_map,
            coverage_status=CoverageStatus.COMPLETE,
        )

        res1 = matcher.match(act, ev, ctx)
        res2 = matcher.match(act, ev, ctx)
        res3 = matcher.match(act, ev, ctx)

        assert res1.status == res2.status == res3.status == ConfirmationMatchStatus.MATCHED
        assert res1.candidate_record is not None and res2.candidate_record is not None and res3.candidate_record is not None
        assert res1.candidate_record.candidate_id == res2.candidate_record.candidate_id == res3.candidate_record.candidate_id
        assert res1.candidate_record.entry_reference_price == res2.candidate_record.entry_reference_price == res3.candidate_record.entry_reference_price

        # External dictionary mutation has zero effect on context
        members_map.clear()
        res_map[mem.member_key] = False
        assert mem.member_key in ctx.current_members
        assert ctx.source_resolution_status[mem.member_key] is True
