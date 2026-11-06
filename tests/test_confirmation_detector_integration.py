"""Separately retrievable integration tests verifying detector-derived CHOCH and ISS confirmation.

Scope & Design Boundary (Explicit Evidence Labeling):
-----------------------------------------------------
- Demonstrates complete end-to-end continuous detection and authoritative confirmation matching:
  1. Fixture loading and exact candle stream adaptation from authoritative JSON fixtures.
  2. Detector/coordinator execution from configured start candle without reset or mutation.
  3. Retrieval of actual emitted detector events.
  4. Confirming-candle lookup directly from the processed input candle stream (no reconstructed expected candles).
  5. Immutable ValidatedCandleStreamEnvelope construction binding looked-up candle and stream/config metadata.
  6. Pair matcher execution against eligible activations.
  7. Exact CandidateSetupRecord assertions and fail-closed blocked-branch verification.
- Explicit Evidence Provenance Labeling:
  Confirmation evidence is genuinely detector-derived and candle-provenanced from the detector engines.
  Activations, source levels, and source member records are synthetic, fully conforming domain inputs
  for the offline matcher (this does not claim a full candle-derived source TJL touch-to-candidate pipeline).
- Strictly offline, read-only calculation layer. Zero network, zero MT5, zero live execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
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
)
from aladeen.strategy.iss_engine import ISSEngine
from aladeen.strategy.iss_types import ISSConfig, ISSLifecycleStatus
from aladeen.strategy.tjl_types import StableLevelId
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_H4", run_id="RUN_20261001_001")


def load_choch_fixture(name: str = "choch_bearish_basic_end_to_end") -> Dict[str, Any]:
    with open(FIXTURES_DIR / "choch_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def load_iss_fixture(name: str = "iss_02_bullish_basic_end_to_end") -> Dict[str, Any]:
    with open(FIXTURES_DIR / "iss_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def create_synthesized_h1_candles_from_prices(
    raw_candles: List[Dict[str, Any]],
    base_time: datetime,
) -> List[StrategyCandle]:
    """Synthesizes a 1-hour candle stream from fixture price series for H1 confirmation testing."""
    interval = timedelta(hours=1)
    candles: List[StrategyCandle] = []
    for i, c in enumerate(raw_candles):
        open_time = base_time + (interval * i)
        close_time = open_time + interval
        candles.append(
            StrategyCandle(
                index=i,
                open_time=open_time,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                close_time=close_time,
            )
        )
    return candles


def parse_canonical_iss_candles(raw_candles: List[Dict[str, Any]]) -> List[StrategyCandle]:
    """Parses raw candles preserving original fixture timestamps and completion attributes."""
    candles: List[StrategyCandle] = []
    for i, c in enumerate(raw_candles):
        open_time = datetime.fromisoformat(c["time"]).astimezone(timezone.utc)
        close_time = (
            datetime.fromisoformat(c["close_time"]).astimezone(timezone.utc)
            if "close_time" in c
            else open_time + timedelta(hours=1)
        )
        candles.append(
            StrategyCandle(
                index=i,
                open_time=open_time,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c.get("is_forming", False)),
                bar_status=str(c.get("bar_status", "CONFIRMED_COMPLETED")),
                close_time=close_time,
            )
        )
    return candles


def test_detector_derived_choch_matched_with_synthetic_activation() -> None:
    """Demonstrates complete candle-derived CHOCH: stream adaptation, coordinator execution,

    confirming candle lookup from processed input, envelope binding, and candidate matching
    against a synthetic source activation.
    """
    # 1. Fixture loading & synthesized 1-hour timeline matching D1 -> H1 confirmation mapping
    fix = load_choch_fixture("choch_bearish_basic_end_to_end")
    base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    processed_candles = create_synthesized_h1_candles_from_prices(fix["candles"], base_time)

    # 2. Coordinator execution from configured start using canonical candle collection
    config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
    coordinator = MSMChochCoordinator(config)
    coordinator.process_candles(processed_candles)

    # 3. Retrieve actual emitted event
    assert len(coordinator.confirmed_choch_events) == 1
    choch = coordinator.confirmed_choch_events[0]
    assert choch.choch_type == ChochType.BEARISH_CHOCH
    assert choch.c2_candle_index == 9
    assert choch.point_3_source_index == 5

    # 4. Confirming candle lookup directly from processed input candle collection
    confirming_candle = processed_candles[choch.c2_candle_index]
    assert confirming_candle.index == 9
    assert confirming_candle.close == 1.0850
    assert confirming_candle.close_time == choch.confirmation_time

    # Synthetic activation tap occurs at candle 7 (pre-confirmation, post-point 3)
    tap_time = processed_candles[7].open_time
    assert tap_time < choch.confirmation_time

    # 5. Envelope construction using looked-up candle and stream metadata
    envelope = ValidatedCandleStreamEnvelope(
        candle=confirming_candle,
        symbol="EURUSD",
        feed_id="FEED_EURUSD_H4",
        timeframe="H1",
        price_basis=PriceBasis.BID,
        confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        confirmation_candle_id="EURUSD:H1:20261001T100000Z",
        sequence_domain=DEFAULT_DOMAIN,
    )

    evidence = adapt_confirmed_choch_to_evidence(
        choch=choch,
        confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        confirmation_timeframe="H1",
        confirmation_candle_id="EURUSD:H1:20261001T100000Z",
        envelope=envelope,
        symbol="EURUSD",
        feed_id="FEED_EURUSD_H4",
        sequence_domain=DEFAULT_DOMAIN,
        price_basis=PriceBasis.BID,
        provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
    )

    # 6. Synthetic Activation and Member setup (D1 source -> H1 confirmation)
    level_id = StableLevelId(
        symbol_feed_id="FEED_EURUSD_H4",
        source_timeframe="D1",
        source_open_time=datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc),
        side="HIGH",
    )
    mem = SourceMemberReference(
        engine_id="ACT_ENGINE_DEMO",
        symbol="EURUSD",
        source_timeframe="D1",
        set_id="SET_20261001_D1",
        role="TJL1",
        side="HIGH",
        lower_edge=1.1350,
        upper_edge=1.1350,
        is_line=True,
        direction=Direction.DOWNWARD,
        level_id=level_id,
        eligibility_available_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
        usage_evidence_status=UsageEvidenceStatus.UNUSED,
    )
    act = ActivationRecord(
        activation_id=format_activation_id("ACT_ENGINE_DEMO", "D1", "EURUSD", "SET_20261001_D1", "TJL1", 1),
        engine_id="ACT_ENGINE_DEMO",
        symbol="EURUSD",
        source_timeframe="D1",
        confirmation_timeframe="H1",
        set_id="SET_20261001_D1",
        role="TJL1",
        lower_edge=1.1350,
        upper_edge=1.1350,
        level_id=level_id,
        state=ActivationState.PENDING_ACTIVATION,
        first_touch_time=tap_time,
        first_touch_price=1.1350,
        trigger_observation_id="OBS_TOUCH_07",
        generation_seq=1,
        usage_evidence_status=UsageEvidenceStatus.UNUSED,
    )

    ctx = MatchingContext(
        domain_session_id="SESS_20261001_001",
        revision_id="REV_001",
        expected_price_basis=PriceBasis.BID,
        expected_confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        matching_sequence_domain=DEFAULT_DOMAIN,
        evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        current_members={mem.member_key: mem},
        source_resolution_status={mem.member_key: True},
        coverage_status=CoverageStatus.COMPLETE,
    )

    matcher = ConfirmationMatcher()
    res = matcher.match(act, evidence, ctx)

    # 7. Exact candidate assertions
    assert res.status == ConfirmationMatchStatus.MATCHED
    assert res.candidate_record is not None
    cand = res.candidate_record
    assert cand.signal_side == "SELL"
    assert cand.source_timeframe == "D1"
    assert cand.confirmation_timeframe == "H1"
    assert cand.entry_reference_price == 1.0850
    assert cand.confirmation_close_timestamp == choch.confirmation_time
    assert cand.provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED
    assert cand.is_consolidated is False


def test_detector_derived_iss_matched_with_synthetic_activation() -> None:
    """Demonstrates complete candle-derived ISS: canonical fixture adaptation without retiming,

    engine execution on the canonical collection, confirming candle lookup from the same collection,
    envelope binding, candidate matching against a synthetic source activation,
    and fail-closed unresolved dependency blocking.
    """
    # 1. Canonical fixture candle loading preserving original timestamps
    fix = load_iss_fixture("iss_02_bullish_basic_end_to_end")
    raw_candles = fix["candles"]
    canonical_candles = parse_canonical_iss_candles(raw_candles)

    # 2. Engine execution from configured start on the single canonical candle collection
    start_time = canonical_candles[0].open_time
    engine = ISSEngine(ISSConfig(main_direction=Direction.UPWARD, start_candle_time=start_time))
    snap = engine.process_candles(canonical_candles)

    # 3. Retrieve actual emitted event
    assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
    assert len(snap.confirmed_events) == 1
    iss_event = snap.confirmed_events[0]
    assert iss_event.confirmation_candle_index == 20
    assert iss_event.completion_close_price == 1.1120

    # 4. Confirming candle lookup directly from the same canonical candle collection
    confirming_candle = canonical_candles[iss_event.confirmation_candle_index]
    assert confirming_candle.index == 20
    assert confirming_candle.close == 1.1120
    assert confirming_candle.close_time == iss_event.confirmation_time

    # Synthetic activation tap occurs at candle 15 (pre-confirmation)
    tap_time = canonical_candles[15].open_time
    assert tap_time < iss_event.confirmation_time

    # 5. Envelope construction using looked-up candle and stream metadata
    envelope = ValidatedCandleStreamEnvelope(
        candle=confirming_candle,
        symbol="EURUSD",
        feed_id="FEED_EURUSD_H4",
        timeframe="H1",
        price_basis=PriceBasis.BID,
        confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        confirmation_candle_id="EURUSD:H1:20261001T210000Z",
        sequence_domain=DEFAULT_DOMAIN,
    )

    # 6. Synthetic Activation and Member setup (D1 source -> H1 confirmation)
    level_id = StableLevelId(
        symbol_feed_id="FEED_EURUSD_H4",
        source_timeframe="D1",
        source_open_time=datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc),
        side="HIGH",
    )
    mem = SourceMemberReference(
        engine_id="ACT_ENGINE_DEMO",
        symbol="EURUSD",
        source_timeframe="D1",
        set_id="SET_20261001_D1",
        role="TJL2_A_PLUS",
        side="HIGH",
        lower_edge=1.1150,
        upper_edge=1.1150,
        is_line=True,
        direction=Direction.DOWNWARD,
        level_id=level_id,
        eligibility_available_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
        usage_evidence_status=UsageEvidenceStatus.UNUSED,
    )
    act = ActivationRecord(
        activation_id=format_activation_id("ACT_ENGINE_DEMO", "D1", "EURUSD", "SET_20261001_D1", "TJL2_A_PLUS", 1),
        engine_id="ACT_ENGINE_DEMO",
        symbol="EURUSD",
        source_timeframe="D1",
        confirmation_timeframe="H1",
        set_id="SET_20261001_D1",
        role="TJL2_A_PLUS",
        lower_edge=1.1150,
        upper_edge=1.1150,
        level_id=level_id,
        state=ActivationState.PENDING_ACTIVATION,
        first_touch_time=tap_time,
        first_touch_price=1.1150,
        trigger_observation_id="OBS_TOUCH_15",
        generation_seq=1,
        usage_evidence_status=UsageEvidenceStatus.UNUSED,
    )

    ctx = MatchingContext(
        domain_session_id="SESS_20261001_001",
        revision_id="REV_001",
        expected_price_basis=PriceBasis.BID,
        expected_confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        matching_sequence_domain=DEFAULT_DOMAIN,
        evaluation_time=datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc),
        current_members={mem.member_key: mem},
        source_resolution_status={mem.member_key: True},
        coverage_status=CoverageStatus.COMPLETE,
    )

    matcher = ConfirmationMatcher()

    # Branch A: Authoritative completed evidence matches
    ev_auth = adapt_confirmed_iss_to_evidence(
        iss=iss_event,
        confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        confirmation_timeframe="H1",
        confirmation_candle_id="EURUSD:H1:20261001T210000Z",
        envelope=envelope,
        symbol="EURUSD",
        feed_id="FEED_EURUSD_H4",
        sequence_domain=DEFAULT_DOMAIN,
        price_basis=PriceBasis.BID,
        provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
        has_unresolved_dependencies=False,
    )
    res_auth = matcher.match(act, ev_auth, ctx)
    assert res_auth.status == ConfirmationMatchStatus.MATCHED
    assert res_auth.candidate_record is not None
    assert res_auth.candidate_record.signal_side == "SELL"
    assert res_auth.candidate_record.entry_reference_price == 1.1120

    # Branch B: Unresolved ISS evidence blocks fail-closed
    ev_unres = adapt_confirmed_iss_to_evidence(
        iss=iss_event,
        confirmation_config_id="CONF_CFG_EURUSD_H1_v1",
        confirmation_timeframe="H1",
        confirmation_candle_id="EURUSD:H1:20261001T210000Z",
        envelope=envelope,
        symbol="EURUSD",
        feed_id="FEED_EURUSD_H4",
        sequence_domain=DEFAULT_DOMAIN,
        price_basis=PriceBasis.BID,
        provenance_type=EvidenceProvenanceType.DETECTOR_CONFIRMED,
        has_unresolved_dependencies=True,
    )
    res_unres = matcher.match(act, ev_unres, ctx)
    assert res_unres.status == ConfirmationMatchStatus.BLOCKED
    assert ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP in res_unres.rejection_reasons
    assert res_unres.candidate_record is None
