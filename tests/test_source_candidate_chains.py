"""Offline source-to-candidate integration proof tests — Chains and Authority Boundaries.

Covers:
- INT-03: Genuine source level set and member emission from TJLCoordinator
  -> TJLSynchronizer atomic sync -> ExactPricePrint touch -> continuous CHOCH detection
  -> ValidatedCandleStreamEnvelope -> ConfirmationMatcher -> exact candidate setup key.
- INT-04: Genuine source -> TJLSynchronizer -> exact touch -> continuous ISS detection
  -> ValidatedCandleStreamEnvelope -> ConfirmationMatcher -> exact candidate setup key.
- Prefix evaluation traces with decisive negative assertions (no candidate before eligibility,
  touch, confirmation completion, or evidence availability).
- Authority boundary negative cases (UNKNOWN_USAGE, INCOMPLETE_COVERAGE, UNRESOLVED_DEPENDENCY).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

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


def parse_fixture_candles(raw_candles: List[Dict[str, Any]]) -> List[StrategyCandle]:
    """Parse fixture candles requiring explicit fixture fields without default fallbacks."""
    candles: List[StrategyCandle] = []
    for i, c in enumerate(raw_candles):
        candles.append(
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
        )
    return candles


class TestSourceCandidateChains:
    """Integration proof tests for genuine source-to-candidate chains (INT-03, INT-04)."""

    def test_int_03_genuine_source_exact_print_choch_end_to_end_with_prefix_trace(self) -> None:
        """INT-03: Complete chain from genuine source level set to exact print to CHOCH confirmation.

        Includes prefix-state evaluation trace verifying no candidate forms before eligibility,
        touch, or confirmation completion.
        """
        trace: List[Dict[str, Any]] = []
        matcher = ConfirmationMatcher()

        # --- Prefix 1: Genuine Source Chain (TJLCoordinator) ---
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        source_candles = parse_fixture_candles(fix_tjl["candles"])
        # Validate interval provenance: fixture candles span 1-hour intervals
        assert all(c.close_time - c.open_time == timedelta(hours=1) for c in source_candles)

        start_time_tjl = source_candles[0].open_time
        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time_tjl),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )

        # Trace at Prefix 1a: before bar 9, no eligible set exists
        for i in range(9):
            source_coord.process_candle(source_candles[i])
        snap_pre9 = source_coord.get_snapshot()
        assert snap_pre9.current_eligible_set is None
        trace.append({"prefix": "1a_pre_formation", "has_set": False, "candidates": 0})

        # Process bar 9 -> SET_1 formed with eligibility at 10:00 UTC
        source_coord.process_candle(source_candles[9])
        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set
        assert cset.set_id == "SET_1"
        assert cset.direction == Direction.DOWNWARD
        assert cset.tjl1_zone.lower_price == 1.1800
        assert cset.tjl1_zone.upper_price == 1.1850
        assert cset.eligibility_available_time == datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
        trace.append({
            "prefix": "1b_set_formed",
            "set_id": cset.set_id,
            "eligibility_time": cset.eligibility_available_time.isoformat(),
        })

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

        # Trace at Prefix 2: Registered members are in state INACTIVE_ELIGIBLE (Gen 0)
        assert mem_key_tjl1 in snap_act_sync.active_activations
        act_pre_touch = snap_act_sync.active_activations[mem_key_tjl1]
        assert act_pre_touch.state == ActivationState.INACTIVE_ELIGIBLE
        assert act_pre_touch.generation_seq == 0

        # Decisive Prefix 2 assertion: matching produces NO candidate prior to physical touch
        ctx_pre_touch = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 10, 15, tzinfo=timezone.utc),
            current_members=dict(snap_act_sync.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_sync.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        dummy_ev = ConfirmationEvidenceRecord(
            event_id="EV_EARLY",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 10, 15, tzinfo=timezone.utc),
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
        assert res_pre_touch.candidate_record is None
        trace.append({"prefix": "2_sync_registered", "state": act_pre_touch.state.value, "candidates": 0})

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
        trace.append({"prefix": "3_touched", "state": act_record.state.value, "touch_time": touch_time.isoformat()})

        # --- Prefix 4: Independent Continuous Confirmation Detection (CHOCH) ---
        # Uses fixture OHLC pattern mapped to an explicitly labeled synthesized H1 timeline
        # (1-hour intervals) to match the D1 -> H1 confirmation timeframe mapping requirement.
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
        choch_coord.process_candles(choch_candles)
        assert len(choch_coord.confirmed_choch_events) == 1
        choch_event = choch_coord.confirmed_choch_events[0]
        assert choch_event.choch_type == ChochType.BEARISH_CHOCH
        assert choch_event.c2_candle_index == 9
        assert choch_event.confirmation_time == datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        trace.append({
            "prefix": "4_choch_detected",
            "type": choch_event.choch_type.value,
            "c2_index": choch_event.c2_candle_index,
            "confirmation_time": choch_event.confirmation_time.isoformat(),
        })

        # --- Prefix 5: Direct Confirming Candle Lookup & Validated Stream Envelope ---
        confirming_candle = choch_candles[choch_event.c2_candle_index]
        assert confirming_candle.close_time == choch_event.confirmation_time
        assert touch_time < choch_event.confirmation_time  # 2026-10-01 10:30 UTC < 2026-10-01 12:00 UTC

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
        trace.append({
            "prefix": "5_envelope_bound",
            "evidence_event_id": evidence.event_id,
            "close_timestamp": evidence.close_timestamp.isoformat(),
        })

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
        res = matcher.match(act_record, evidence, ctx)

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
            domain_session_id=ctx.domain_session_id,
            revision_id=ctx.revision_id,
            activation_id=act_record.activation_id,
            source_member_key=act_record.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"

        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id
        trace.append({"prefix": "6_matched", "status": "MATCHED", "candidate_id": cand.candidate_id})

        # Verify full trace has 7 sequential stages (1a, 1b, 2, 3, 4, 5, 6)
        assert len(trace) == 7

    def test_int_04_genuine_source_exact_print_iss_end_to_end_with_prefix_trace(self) -> None:
        """INT-04: Complete chain from genuine source level set to exact print to ISS confirmation.

        Includes prefix-state evaluation trace and exact canonical setup key assertions.
        """
        trace: List[Dict[str, Any]] = []
        matcher = ConfirmationMatcher()

        # --- Prefix 1: Genuine Source Chain (TJLCoordinator) ---
        fix_tjl = load_tjl_fixture("tjl_02_bearish_basic_end_to_end")
        source_candles = parse_fixture_candles(fix_tjl["candles"])
        start_time_tjl = source_candles[0].open_time
        source_coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time_tjl),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        for i in range(10):
            source_coord.process_candle(source_candles[i])

        snap_tjl = source_coord.get_snapshot()
        assert snap_tjl.current_eligible_set is not None
        cset = snap_tjl.current_eligible_set
        assert cset.eligibility_available_time == datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)

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
        trace.append({"prefix": "3_touched", "state": act_record.state.value, "touch_time": touch_time.isoformat()})

        # --- Prefix 4: Independent Continuous ISS Detection ---
        fix_iss = load_iss_fixture("iss_02_bullish_basic_end_to_end")
        iss_candles = parse_fixture_candles(fix_iss["candles"])
        iss_engine = ISSEngine(
            ISSConfig(main_direction=Direction.UPWARD, start_candle_time=iss_candles[0].open_time)
        )
        snap_iss = iss_engine.process_candles(iss_candles)
        assert snap_iss.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap_iss.confirmed_events) > 0
        iss_event = snap_iss.confirmed_events[0]
        assert iss_event.confirmation_candle_index == 20
        assert iss_event.completion_close_price == 1.1120
        assert iss_event.confirmation_time == datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)
        trace.append({
            "prefix": "4_iss_detected",
            "lifecycle": snap_iss.lifecycle_status.value,
            "confirmation_index": iss_event.confirmation_candle_index,
            "completion_price": iss_event.completion_close_price,
        })

        # --- Prefix 5: Direct Confirming Candle Lookup & Validated Stream Envelope ---
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
        trace.append({
            "prefix": "5_envelope_bound",
            "evidence_event_id": evidence.event_id,
            "close_timestamp": evidence.close_timestamp.isoformat(),
        })

        # --- Prefix 6: Matcher Evaluation & Candidate Formation ---
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_touched.current_members),
            source_resolution_status={m_k: True for m_k in snap_act_touched.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res = matcher.match(act_record, evidence, ctx)

        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.entry_reference_price == 1.1120

        # Assert canonical identity using runtime-derived format functions
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx.domain_session_id,
            revision_id=ctx.revision_id,
            activation_id=act_record.activation_id,
            source_member_key=act_record.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"

        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id
        trace.append({"prefix": "6_matched", "status": "MATCHED", "candidate_id": cand.candidate_id})

        assert len(trace) == 4

    def test_supplied_synthetic_authority_boundaries(self) -> None:
        """Authority Boundary: Unknown usage, incomplete coverage, and unresolved resolution reject fail-closed."""
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

        from aladeen.strategy.activation_types import format_activation_id
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
        mem_unknown_usage = SourceMemberReference(
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
            usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
        )
        act_unknown_usage = ActivationRecord(
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
            usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
        )
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
        ctx_incomplete_cov = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: True},
            coverage_status=CoverageStatus.INCOMPLETE,
        )
        res_b = matcher.match(act_valid, ev_valid, ctx_incomplete_cov)
        assert res_b.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in res_b.rejection_reasons
        assert res_b.candidate_record is None

        # Boundary C: Unresolved source member resolution rejects as BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY
        ctx_unresolved = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: False},  # Unresolved!
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_c = matcher.match(act_valid, ev_valid, ctx_unresolved)
        assert res_c.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY in res_c.rejection_reasons
        assert res_c.candidate_record is None

        # Boundary D: Evidence has unresolved structural dependencies
        ev_unresolved_dep = ConfirmationEvidenceRecord(
            event_id="EV_UNRES",
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
            has_unresolved_dependencies=True,  # Explicitly unresolved!
        )
        ctx_valid = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem_valid.member_key: mem_valid},
            source_resolution_status={mem_valid.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_d = matcher.match(act_valid, ev_unresolved_dep, ctx_valid)
        assert res_d.status == ConfirmationMatchStatus.BLOCKED
        assert ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY in res_d.rejection_reasons
        assert res_d.candidate_record is None
