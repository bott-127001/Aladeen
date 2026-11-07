"""Offline source-to-candidate integration proof tests — Lifecycle and Determinism.

Covers Milestone 36 Directives:
- Case 6: Actual lifecycle proof:
  * Genuine rearm lifecycle path: Gen 1 touch -> cancel via ExternalCommitEvent -> OUT_OF_ZONE_ARMED ->
    retouch -> Gen 2 REARMED_PENDING with fresh-generation linkage and prior activation equality ->
    matches confirming evidence with exact canonical identity, entry price 1.0850, and DETECTOR_CONFIRMED.
  * Genuine replacement lifecycle path: SET_1 replaced by SET_2 via TJLSynchronizer.sync() ->
    SET_1 cancelled into immutable history -> no revival of invalidated memberships ->
    physical-level usage preserved -> illegal attempt to reset terminal USED rejected with USAGE_USED_TERMINAL.
- Case 7: Deterministic equality and input immutability:
  * Repeated evaluations produce identical complete AuthorityBuildResult and identical ConfirmationMatchResult (res1 == res2).
  * Strict input immutability verified.
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
    CancellationReason,
    CoverageStatus,
    ExactPricePrint,
    ExternalCommitEvent,
    InvalidEvidenceError,
    PriceBasis,
    SequenceDomain,
    SourceCancellationEvent,
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


class TestSourceCandidateAuthorityLifecycle:
    """Case 6 and Case 7: Genuine lifecycle proof and deterministic evaluation equality."""

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
            "source_coord": source_coord,
            "source_candles": source_candles,
            "cset": cset,
            "lvl1": lvl1,
            "lvl2": lvl2,
            "t0": t0,
            "t_1000": datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            "eval_time": datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc),
            "act_engine": act_engine,
            "synchronizer": synchronizer,
            "snap_touched": snap_touched,
            "act_rec_tjl1": act_rec_tjl1,
            "evidence": evidence,
        }

    def test_genuine_rearm_lifecycle_produces_generation_2_candidate(self) -> None:
        """Case 6A: Genuine engine rearm execution:
        Touch -> Departure -> External commit cancel -> OUT_OF_ZONE_ARMED ->
        Retouch -> Gen 2 REARMED_PENDING with terminal predecessor equality ->
        Gen 2 confirmation match with canonical identity, entry price 1.0850, and DETECTOR_CONFIRMED.
        """
        data = self._setup_genuine_pipeline()
        act_engine: ActivationEngine = data["act_engine"]
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        act_gen1 = data["act_rec_tjl1"]
        t0 = data["t0"]
        t_1000 = data["t_1000"]
        eval_time = data["eval_time"]

        # 1. Price departs from zone: price 1.1860 (> 1.1850 upper edge)
        p_depart = ExactPricePrint("OBS_DEPART", 1.1860, PRICE_BASIS, datetime(2026, 10, 11, 7, 45, tzinfo=timezone.utc), DEFAULT_DOMAIN, 1004)
        act_engine.process_event(p_depart)

        # 2. External commit event cancels Gen 1
        evt_cancel = ExternalCommitEvent(
            event_id="EVT_EXT_COMMIT",
            timestamp=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1005,
            winning_engine_id="OTHER_ENGINE",
            winning_set_id="OTHER_SET",
            winning_role="OTHER_ROLE",
            target_symbol=FEED_ID,
            target_source_timeframe="D1",
        )
        snap_cancelled = act_engine.process_event(evt_cancel)

        # Gen 1 moved to immutable terminal_activations
        assert mem_key_tjl1 not in snap_cancelled.active_activations
        assert len(snap_cancelled.terminal_activations) >= 1
        hist_gen1 = snap_cancelled.terminal_activations[-1]
        assert hist_gen1.activation_id == act_gen1.activation_id
        assert hist_gen1.state == ActivationState.CANCELLED_EXTERNAL_ENTRY
        assert hist_gen1.terminal is True

        # Rearm controller armed (already outside zone)
        assert mem_key_tjl1 in snap_cancelled.rearm_controllers
        ctrl = snap_cancelled.rearm_controllers[mem_key_tjl1]
        assert ctrl.state == ActivationState.OUT_OF_ZONE_ARMED
        assert ctrl.rearm_armed is True

        # 3. Retouch print inside zone (1.1825) at 08:15 UTC rearms to Generation 2
        p_retouch = ExactPricePrint("OBS_RETOUCH", 1.1825, PRICE_BASIS, datetime(2026, 10, 11, 8, 15, tzinfo=timezone.utc), DEFAULT_DOMAIN, 1006)
        snap_rearmed = act_engine.process_event(p_retouch)

        # Gen 2 activation created in REARMED_PENDING
        assert mem_key_tjl1 in snap_rearmed.active_activations
        act_gen2 = snap_rearmed.active_activations[mem_key_tjl1]
        assert act_gen2.state == ActivationState.REARMED_PENDING
        assert act_gen2.generation_seq == 2
        assert act_gen2.prior_activation_id == act_gen1.activation_id  # Fresh-generation linkage!
        assert act_gen2.first_touch_time == datetime(2026, 10, 11, 8, 15, tzinfo=timezone.utc)
        assert act_gen2.trigger_observation_id == "OBS_RETOUCH"
        assert mem_key_tjl1 not in snap_rearmed.rearm_controllers  # Controller consumed

        # 4. Confirmation matching at Boundary 5 (10:00 UTC close / 10:30 UTC eval)
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
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
        usg_rec_rearm = ProposedUsageEvidenceRecord(
            record_id="USG_TJL1_REARM",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=data["lvl1"],
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_TX_001",
        )
        auth_eval = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_rec_rearm,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(data["lvl1"], data["lvl2"]),
        )
        synthetic_source_res = {m_k: True for m_k in snap_rearmed.current_members}
        ctx_rearm, _ = builder.build_matching_context(
            authority_result=auth_eval,
            base_members=snap_rearmed.current_members,
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
            active_activations=snap_rearmed.active_activations,
        )

        # Matcher matches Gen 2 REARMED_PENDING cleanly!
        res_rearm = matcher.match(act_gen2, data["evidence"], ctx_rearm)
        assert res_rearm.status == ConfirmationMatchStatus.MATCHED
        assert res_rearm.candidate_record is not None
        cand = res_rearm.candidate_record

        # Assert canonical identity, entry price, and provenance
        assert cand.activation_id == act_gen2.activation_id
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx_rearm.domain_session_id,
            revision_id=ctx_rearm.revision_id,
            activation_id=act_gen2.activation_id,
            source_member_key=act_gen2.member_key,
            confirmation_config_id=data["evidence"].confirmation_config_id,
            confirmation_candle_id=data["evidence"].confirmation_candle_id,
            confirmation_close_iso=data["evidence"].close_timestamp.isoformat(),
        )
        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == f"CAND{format_length_prefixed(expected_setup_key)}"
        assert cand.entry_reference_price == 1.0850
        assert cand.provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED

    def test_genuine_replacement_lifecycle_retains_usage_and_invalidates_old_memberships(self) -> None:
        """Case 6B: Genuine engine replacement execution:
        - SET_1 replaced by SET_2 via SourceCancellationEvent + register_source_members.
        - SET_1 activations cancelled into immutable terminal history.
        - Old invalidated memberships cannot be revived.
        - Physical-level usage is retained.
        - Illegal proposal attempting to reset terminal USED to UNUSED is rejected with USAGE_USED_TERMINAL.
        - Historical activation with terminal USED blocks context composition if authority resolves UNUSED.
        """
        data = self._setup_genuine_pipeline()
        act_engine: ActivationEngine = data["act_engine"]
        lvl1 = data["lvl1"]
        t0 = data["t0"]
        t_1000 = data["t_1000"]
        eval_time = data["eval_time"]
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()

        # 1. Process SourceCancellationEvent for SET_1 (genuine replacement cancellation)
        evt_replace = SourceCancellationEvent(
            event_id="EVT_REPLACE_SET_1",
            cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=3000,
            timestamp=datetime(2026, 10, 11, 8, 30, tzinfo=timezone.utc),
            target_set_id="SET_1",
            note="SET_1 replaced by newly formed SET_2",
        )
        snap_cancelled = act_engine.process_event(evt_replace)
        mem_key_set1_tjl1 = format_member_key("SET_1", "TJL1")

        # SET_1 activation was moved to terminal_activations
        assert mem_key_set1_tjl1 not in snap_cancelled.active_activations
        assert mem_key_set1_tjl1 not in snap_cancelled.current_members
        assert len(snap_cancelled.terminal_activations) >= 1
        term_rec_set1 = [t for t in snap_cancelled.terminal_activations if t.member_key == mem_key_set1_tjl1][-1]
        assert term_rec_set1.state == ActivationState.CANCELLED_SOURCE_REPLACEMENT
        assert term_rec_set1.terminal is True

        # Invalidated memberships cannot be revived: re-registering SET_1 raises InvalidEvidenceError
        with pytest.raises(InvalidEvidenceError, match="Source cancellations permanently retire outgoing set identities"):
            act_engine.register_source_members([data["snap_touched"].current_members[mem_key_set1_tjl1]])

        # 2. Register replacement set SET_2 into engine
        lvl_set2 = StableLevelId(
            symbol_feed_id=FEED_ID,
            source_timeframe="D1",
            source_open_time=datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc),
            side=lvl1.side,
        )
        m_set2_tjl1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol=FEED_ID,
            source_timeframe="D1",
            set_id="SET_2",
            role="TJL1",
            side=lvl1.side.value if hasattr(lvl1.side, "value") else str(lvl1.side),
            lower_edge=1.1810,
            upper_edge=1.1860,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=lvl_set2,
            eligibility_available_time=t0,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        snap_set2 = act_engine.register_source_members([m_set2_tjl1])
        mem_key_set2_tjl1 = format_member_key("SET_2", "TJL1")
        assert mem_key_set2_tjl1 in snap_set2.active_activations

        # Evaluating cancelled SET_1 activation against updated context rejects: no revival of invalidated memberships!
        synthetic_source_res = {m_k: True for m_k in snap_set2.current_members}
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
        auth_eval = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl1,),
        )
        ctx_replaced, _ = builder.build_matching_context(
            authority_result=auth_eval,
            base_members=snap_set2.current_members,
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
            active_activations=snap_set2.active_activations,
        )

        # Evaluating cancelled Gen 1 against updated context fails closed
        res_old = matcher.match(term_rec_set1, data["evidence"], ctx_replaced)
        assert res_old.status == ConfirmationMatchStatus.REJECTED
        assert res_old.candidate_record is None
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res_old.rejection_reasons

        # Authority Terminal USED Retention:
        # Physical level marked USED remains permanently USED; illegal reset to UNUSED is rejected
        usg_root_used = ProposedUsageEvidenceRecord(
            record_id="USG_USED_TERMINAL_ROOT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.USED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_USED",
        )
        usg_illegal_reset = ProposedUsageEvidenceRecord(
            record_id="USG_ILLEGAL_RESET",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            predecessor_record_id="USG_USED_TERMINAL_ROOT",
            provenance_ref="LEDGER_RESET",
        )
        auth_used_chain = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_root_used, usg_illegal_reset),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl1,),
        )
        assert auth_used_chain.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.USED
        assert any(
            d.entity_key == "USG_ILLEGAL_RESET" and d.diagnostic_reason == AuthorityDiagnosticReason.USAGE_USED_TERMINAL
            for d in auth_used_chain.diagnostics
        )

        # Context composition rejects if active activation has USED but authority resolves UNUSED
        from dataclasses import replace
        act_history_used = replace(data["act_rec_tjl1"], usage_evidence_status=UsageEvidenceStatus.USED)

        usg_unused_eval = ProposedUsageEvidenceRecord(
            record_id="USG_UNUSED_EVAL",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_UNUSED",
        )
        auth_eval_unused = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_unused_eval,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_1000,
            physical_levels=(lvl1,),
        )
        assert auth_eval_unused.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.UNUSED

        with pytest.raises(ValueError, match="contradicts immutable activation history"):
            builder.build_matching_context(
                authority_result=auth_eval_unused,  # auth_eval_unused resolved UNUSED
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
                active_activations={data["act_rec_tjl1"].member_key: act_history_used},
            )

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
        assert match_res1 == match_res2  # Complete result equality!
        assert match_res1.status == match_res2.status == ConfirmationMatchStatus.MATCHED
        assert match_res1.candidate_record == match_res2.candidate_record
        assert match_res1.rejection_reasons == match_res2.rejection_reasons == ()

        # Input immutability assertions
        assert cov_rec == cov_copy
        assert usg_rec == usg_copy
