"""Tests for pure offline authority preprocessor (AuthorityContextBuilder).

Validates Milestone 35 implementation under accepted Milestone 34 contract:
- 6-step preprocessing pipeline.
- 25 proposed synthetic cases (AUT-SYN-01 through AUT-SYN-23, including subcases a/b).
- Point-in-time boundary checks before and after successor availability.
- Input immutability and permutation invariance.
- Composition into accepted ConfirmationMatcher.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_member_key,
)
from aladeen.strategy.authority_context_builder import AuthorityContextBuilder
from aladeen.strategy.authority_types import (
    AuthorityBuildResult,
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
)
from aladeen.strategy.confirmation_pair_matcher import ConfirmationPairMatcher, MatchingContext
from aladeen.strategy.confirmation_types import (
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
)
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction


# -----------------------------------------------------------------------------
# Test Fixtures & Constants
# -----------------------------------------------------------------------------

FEED_ID = "FEED_EURUSD_H1"
SEQ_DOMAIN = SequenceDomain(feed_id=FEED_ID, run_id="RUN_001")
TIMEFRAME = "H1"
CONF_CFG = "CONF_CFG_01"
PRICE_BASIS = PriceBasis.BID

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
T4 = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)

LEVEL_A = StableLevelId(symbol_feed_id=FEED_ID, source_timeframe=TIMEFRAME, source_open_time=T0, side=TJLSide.HIGH)
LEVEL_B = StableLevelId(symbol_feed_id=FEED_ID, source_timeframe=TIMEFRAME, source_open_time=T1, side=TJLSide.LOW)


def make_coverage_record(
    record_id: str = "COV_REC_01",
    schema_version: str = "v1",
    issuer_id: str = "OFFLINE_FEED_AUDITOR_v1",
    feed_id: str = FEED_ID,
    sequence_domain: SequenceDomain = SEQ_DOMAIN,
    timeframe: str = TIMEFRAME,
    confirmation_config_id: str = CONF_CFG,
    covered_interval_start: datetime = T0,
    covered_interval_end: datetime = T4,
    status: CoverageStatus = CoverageStatus.COMPLETE,
    issued_time: datetime = T1,
    available_time: datetime = T1,
    revision_seq: int = 1,
    supersedes_record_id: str | None = None,
) -> ProposedFeedCoverageRecord:
    return ProposedFeedCoverageRecord(
        record_id=record_id,
        schema_version=schema_version,
        issuer_id=issuer_id,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        timeframe=timeframe,
        confirmation_config_id=confirmation_config_id,
        covered_interval_start=covered_interval_start,
        covered_interval_end=covered_interval_end,
        status=status,
        issued_time=issued_time,
        available_time=available_time,
        revision_seq=revision_seq,
        supersedes_record_id=supersedes_record_id,
    )


def make_usage_record(
    record_id: str = "USG_REC_01",
    schema_version: str = "v1",
    issuer_id: str = "UPSTREAM_TRADE_LEDGER_OFFLINE",
    level_id: StableLevelId = LEVEL_A,
    status: UsageEvidenceStatus = UsageEvidenceStatus.UNUSED,
    established_time: datetime = T1,
    available_time: datetime = T1,
    provenance_ref: str = "TICKET_1001",
    predecessor_record_id: str | None = None,
    optional_integrity_hash: str | None = None,
) -> ProposedUsageEvidenceRecord:
    return ProposedUsageEvidenceRecord(
        record_id=record_id,
        schema_version=schema_version,
        issuer_id=issuer_id,
        level_id=level_id,
        status=status,
        established_time=established_time,
        available_time=available_time,
        provenance_ref=provenance_ref,
        predecessor_record_id=predecessor_record_id,
        optional_integrity_hash=optional_integrity_hash,
    )


def make_activation_record(
    activation_id: str = "ACT_01",
    engine_id: str = "TJL",
    symbol: str = "EURUSD",
    source_timeframe: str = "H1",
    confirmation_timeframe: str = "M1",
    set_id: str = "SET_1",
    role: str = "TJL2_A_PLUS",
    level_id: StableLevelId = LEVEL_A,
    lower_edge: float = 1.2000,
    upper_edge: float = 1.2020,
    state: ActivationState = ActivationState.PENDING_ACTIVATION,
    first_touch_time: datetime = T1,
    first_touch_price: float = 1.2005,
    trigger_observation_id: str = "OBS_01",
    generation_seq: int = 1,
    usage_evidence_status: UsageEvidenceStatus = UsageEvidenceStatus.UNKNOWN,
) -> ActivationRecord:
    return ActivationRecord(
        activation_id=activation_id,
        engine_id=engine_id,
        symbol=symbol,
        source_timeframe=source_timeframe,
        confirmation_timeframe=confirmation_timeframe,
        set_id=set_id,
        role=role,
        level_id=level_id,
        lower_edge=lower_edge,
        upper_edge=upper_edge,
        state=state,
        first_touch_time=first_touch_time,
        first_touch_price=first_touch_price,
        trigger_observation_id=trigger_observation_id,
        generation_seq=generation_seq,
        usage_evidence_status=usage_evidence_status,
    )


def make_evidence_record(
    event_id: str = "EV_01",
    producer_id: str = "FIXTURE",
    pattern_type: str = "CHOCH",
    confirmation_config_id: str = CONF_CFG,
    confirmation_timeframe: str = "M1",
    confirmation_candle_id: str = "EURUSD:M1:20261001T120000Z",
    symbol: str = "EURUSD",
    feed_id: str = FEED_ID,
    sequence_domain: SequenceDomain = SEQ_DOMAIN,
    close_price: float = 1.2010,
    price_basis: PriceBasis = PRICE_BASIS,
    direction: Direction = Direction.UPWARD,
    close_timestamp: datetime = T2,
    provenance_type: EvidenceProvenanceType = EvidenceProvenanceType.DETECTOR_CONFIRMED,
    is_completed: bool = True,
    activation_id: str | None = "ACT_01",
    source_member_key: str | None = None,
    structural_dependency_references: tuple = ("CHOCH_TYPE:BULLISH_CHOCH", "POINT_3_INDEX:5"),
) -> ConfirmationEvidenceRecord:
    return ConfirmationEvidenceRecord(
        event_id=event_id,
        producer_id=producer_id,
        pattern_type=pattern_type,
        confirmation_config_id=confirmation_config_id,
        confirmation_timeframe=confirmation_timeframe,
        confirmation_candle_id=confirmation_candle_id,
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        close_price=close_price,
        price_basis=price_basis,
        direction=direction,
        close_timestamp=close_timestamp,
        provenance_type=provenance_type,
        is_completed=is_completed,
        activation_id=activation_id,
        source_member_key=source_member_key,
        structural_dependency_references=structural_dependency_references,
    )


# -----------------------------------------------------------------------------
# Synthetic Cases: AUT-SYN-01 through AUT-SYN-23
# -----------------------------------------------------------------------------

def test_aut_syn_01_contradictory_usage_assertions() -> None:
    """AUT-SYN-01: Contradictory Usage Evidence degrades to UNKNOWN."""
    builder = AuthorityContextBuilder()
    r1 = make_usage_record(record_id="U1", status=UsageEvidenceStatus.UNUSED, available_time=T1)
    r2 = make_usage_record(record_id="U2", status=UsageEvidenceStatus.USED, available_time=T1)

    result = builder.validate_and_build(
        usage_records=[r1, r2],
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert result.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.CONTRADICTORY_ASSERTION for d in result.diagnostics)


def test_aut_syn_02_retroactive_coverage_rejection() -> None:
    """AUT-SYN-02: Coverage extent covers interval, but T_avail > T_eval -> INCOMPLETE."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(
        covered_interval_start=T0,
        covered_interval_end=T4,
        available_time=T3, # Available in future relative to eval_time
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cov],
        evaluation_time=T2, # Before availability
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE for d in result.diagnostics)


def test_aut_syn_03_coverage_config_mismatch() -> None:
    """AUT-SYN-03: Certificate generated for CONF_CFG_02, evaluation requests CONF_CFG_01 -> INCOMPLETE."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(confirmation_config_id="CONF_CFG_02")

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG, # requests CONF_CFG_01
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.SCOPE_MISMATCH_CONFIG for d in result.diagnostics)


def test_aut_syn_04_conflicting_usage_duplicate_payloads() -> None:
    """AUT-SYN-04 / AUT-SYN-15: Duplicate record_id with differing payloads -> CONFLICTING_IDENTITY."""
    builder = AuthorityContextBuilder()
    u1 = make_usage_record(record_id="U_DUP", status=UsageEvidenceStatus.UNUSED)
    u2 = make_usage_record(record_id="U_DUP", status=UsageEvidenceStatus.USED)

    result = builder.validate_and_build(
        usage_records=[u1, u2],
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert result.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.CONFLICTING_IDENTITY for d in result.diagnostics)


def test_aut_syn_05_conflicting_coverage_duplicate_payloads() -> None:
    """AUT-SYN-05 / AUT-SYN-15: Duplicate coverage record_id with differing payloads -> CONFLICTING_IDENTITY."""
    builder = AuthorityContextBuilder()
    c1 = make_coverage_record(record_id="C_DUP", status=CoverageStatus.COMPLETE)
    c2 = make_coverage_record(record_id="C_DUP", status=CoverageStatus.INCOMPLETE)

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c1, c2],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.CONFLICTING_IDENTITY for d in result.diagnostics)


def test_aut_syn_06_persistent_usage_across_set_replacement() -> None:
    """AUT-SYN-06: Once Level L reaches USED, it remains USED permanently."""
    builder = AuthorityContextBuilder()
    u_used = make_usage_record(record_id="U_USED", status=UsageEvidenceStatus.USED, established_time=T1, available_time=T1)

    result = builder.validate_and_build(
        usage_records=[u_used],
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert result.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.USED

    # Now verify that an invalid successor attempting to reset USED -> UNUSED is rejected
    u_invalid_reset = make_usage_record(
        record_id="U_RESET",
        status=UsageEvidenceStatus.UNUSED,
        established_time=T2,
        available_time=T2,
        predecessor_record_id="U_USED",
    )

    result2 = builder.validate_and_build(
        usage_records=[u_used, u_invalid_reset],
        coverage_records=[],
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert result2.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.USED
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.USAGE_USED_TERMINAL for d in result2.diagnostics)


def test_aut_syn_07_evaluation_preceding_availability() -> None:
    """AUT-SYN-07: Records available after T_eval are filtered out."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(available_time=T3)
    usg = make_usage_record(available_time=T3)

    result = builder.validate_and_build(
        usage_records=[usg],
        coverage_records=[cov],
        evaluation_time=T2, # Precedes T3
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert result.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN


def test_aut_syn_08_unresolved_source_resolution_status() -> None:
    """AUT-SYN-08: Unresolved source resolution status fails closed in Matcher."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(status=CoverageStatus.COMPLETE)
    usg = make_usage_record(status=UsageEvidenceStatus.UNUSED)

    res = builder.validate_and_build(
        usage_records=[usg],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    m_k = format_member_key("SET_1", "TJL2_A_PLUS")
    base_member = SourceMemberReference(
        engine_id="TJL",
        symbol="EURUSD",
        source_timeframe="H1",
        set_id="SET_1",
        role="TJL2_A_PLUS",
        side="HIGH",
        lower_edge=1.2000,
        upper_edge=1.2020,
        is_line=False,
        direction=Direction.UPWARD,
        level_id=LEVEL_A,
        eligibility_available_time=T1,
        usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
    )

    # Without source_resolution_status provided (unresolved upstream)
    ctx, updated_members = builder.build_matching_context(
        authority_result=res,
        base_members={m_k: base_member},
        domain_session_id="SESS_01",
        revision_id="REV_01",
        expected_price_basis=PRICE_BASIS,
        expected_confirmation_config_id=CONF_CFG,
        matching_sequence_domain=SEQ_DOMAIN,
        evaluation_time=T2,
        source_resolution_status=None, # Missing/unresolved!
    )

    assert ctx.source_resolution_status == {}
    # Verify that ConfirmationMatcher blocks on unknown source resolution authority
    matcher = ConfirmationPairMatcher()
    act = make_activation_record(
        activation_id="ACT_01",
        usage_evidence_status=updated_members[m_k].usage_evidence_status,
    )
    ev = make_evidence_record(
        event_id="EV_01",
        activation_id="ACT_01",
        source_member_key=m_k,
    )

    match_res = matcher.match(act, ev, ctx)
    assert match_res.status == ConfirmationMatchStatus.BLOCKED
    assert ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY in match_res.rejection_reasons


def test_aut_syn_09_uncertain_coverage_degradation() -> None:
    """AUT-SYN-09: Explicit CoverageStatus.UNCERTAIN degrades preprocessor to UNCERTAIN."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(status=CoverageStatus.UNCERTAIN)

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.UNCERTAIN


def test_aut_syn_11_missing_authority_record() -> None:
    """AUT-SYN-11: Level omitted entirely from usage records defaults to UNKNOWN."""
    builder = AuthorityContextBuilder()
    result = builder.validate_and_build(
        usage_records=[], # Zero usage records
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A, LEVEL_B],
    )

    assert result.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert result.resolved_usage_statuses[LEVEL_B] == UsageEvidenceStatus.UNKNOWN
    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE


def test_aut_syn_12_wrong_scope_variations() -> None:
    """AUT-SYN-12: Wrong feed_id, wrong run_id/domain, wrong timeframe all rejected."""
    builder = AuthorityContextBuilder()

    # Case A: Wrong feed
    cov_feed = make_coverage_record(record_id="C_FEED", feed_id="WRONG_FEED")
    res_feed = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cov_feed],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )
    assert res_feed.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.SCOPE_MISMATCH_FEED for d in res_feed.diagnostics)

    # Case B: Wrong run/domain
    wrong_seq = SequenceDomain(feed_id=FEED_ID, run_id="WRONG_RUN")
    cov_seq = make_coverage_record(record_id="C_SEQ", sequence_domain=wrong_seq)
    res_seq = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cov_seq],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )
    assert res_seq.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.SCOPE_MISMATCH_RUN for d in res_seq.diagnostics)

    # Case C: Wrong timeframe
    cov_tf = make_coverage_record(record_id="C_TF", timeframe="M15")
    res_tf = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cov_tf],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )
    assert res_tf.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.SCOPE_MISMATCH_TIMEFRAME for d in res_tf.diagnostics)


def test_aut_syn_13_future_usage_knowledge_availability() -> None:
    """AUT-SYN-13: Usage record established at T1 <= T_eval but available_time > T_eval is filtered."""
    builder = AuthorityContextBuilder()
    usg = make_usage_record(
        established_time=T1,
        available_time=T3, # Available after T_eval
        status=UsageEvidenceStatus.UNUSED,
    )

    result = builder.validate_and_build(
        usage_records=[usg],
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert result.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE for d in result.diagnostics)


def test_aut_syn_14_validated_superseded_precedence() -> None:
    """AUT-SYN-14: Validated Rev 2 supersedes Rev 1 in its entirety."""
    builder = AuthorityContextBuilder()
    c1 = make_coverage_record(
        record_id="C1",
        revision_seq=1,
        status=CoverageStatus.INCOMPLETE,
        available_time=T1,
    )
    c2 = make_coverage_record(
        record_id="C2",
        revision_seq=2,
        supersedes_record_id="C1",
        status=CoverageStatus.COMPLETE,
        available_time=T2,
    )

    # Point-in-time check: before C2 is available (at T1.5)
    t1_5 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    res_before = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c1, c2],
        evaluation_time=t1_5,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=t1_5,
    )
    # At T1.5, only C1 is visible
    assert res_before.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert res_before.authoritative_coverage_record is None

    # After C2 is available (at T3)
    res_after = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c1, c2],
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )
    assert res_after.resolved_coverage_status == CoverageStatus.COMPLETE
    assert res_after.authoritative_coverage_record is not None
    assert res_after.authoritative_coverage_record.record_id == "C2"


def test_aut_syn_16a_unknown_predecessor_prior_valid_preserved() -> None:
    """AUT-SYN-16a: Invalid successor claims unknown predecessor; prior valid certificate preserved."""
    builder = AuthorityContextBuilder()
    c_valid = make_coverage_record(record_id="C_VALID", status=CoverageStatus.COMPLETE)
    c_bogus = make_coverage_record(
        record_id="C_BOGUS",
        revision_seq=2,
        supersedes_record_id="NON_EXISTENT_PRED",
        status=CoverageStatus.INCOMPLETE,
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c_valid, c_bogus],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    # Prior valid certificate preserved!
    assert result.resolved_coverage_status == CoverageStatus.COMPLETE
    assert result.authoritative_coverage_record.record_id == "C_VALID"
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR for d in result.diagnostics)


def test_aut_syn_16b_unknown_predecessor_no_prior_valid_fail_closed() -> None:
    """AUT-SYN-16b: Invalid successor claims unknown predecessor; no prior certificate -> fails closed."""
    builder = AuthorityContextBuilder()
    c_bogus = make_coverage_record(
        record_id="C_BOGUS",
        revision_seq=2,
        supersedes_record_id="NON_EXISTENT_PRED",
        status=CoverageStatus.COMPLETE,
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c_bogus],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert result.authoritative_coverage_record is None
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR for d in result.diagnostics)


def test_aut_syn_17a_wrong_scope_supersession_prior_valid_preserved() -> None:
    """AUT-SYN-17a: Out-of-scope successor ignored; prior valid in-scope certificate preserved."""
    builder = AuthorityContextBuilder()
    c_valid = make_coverage_record(record_id="C_VALID", status=CoverageStatus.COMPLETE)
    c_out_of_scope = make_coverage_record(
        record_id="C_OUT_OF_SCOPE",
        feed_id="OTHER_FEED",
        revision_seq=2,
        supersedes_record_id="C_VALID",
        status=CoverageStatus.INCOMPLETE,
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c_valid, c_out_of_scope],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.COMPLETE
    assert result.authoritative_coverage_record.record_id == "C_VALID"


def test_aut_syn_17b_wrong_scope_supersession_no_prior_valid_fail_closed() -> None:
    """AUT-SYN-17b: Out-of-scope successor; no prior in-scope valid exists -> fail closed."""
    builder = AuthorityContextBuilder()
    c_out_of_scope = make_coverage_record(
        record_id="C_OUT_OF_SCOPE",
        feed_id="OTHER_FEED",
        revision_seq=2,
        status=CoverageStatus.COMPLETE,
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[c_out_of_scope],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert result.authoritative_coverage_record is None


def test_aut_syn_18_cyclic_predecessor_link() -> None:
    """AUT-SYN-18: Cyclic predecessor link (A -> B -> A) degrades to UNCERTAIN."""
    builder = AuthorityContextBuilder()
    cA = make_coverage_record(record_id="CA", revision_seq=2, supersedes_record_id="CB")
    cB = make_coverage_record(record_id="CB", revision_seq=1, supersedes_record_id="CA")

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cA, cB],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.UNCERTAIN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK for d in result.diagnostics)


def test_aut_syn_19_forked_successors() -> None:
    """AUT-SYN-19: Multiple successors claim same predecessor with conflicting payloads -> UNCERTAIN."""
    builder = AuthorityContextBuilder()
    pred = make_coverage_record(record_id="C_PRED", revision_seq=1, status=CoverageStatus.COMPLETE)
    succ1 = make_coverage_record(
        record_id="C_SUCC1",
        revision_seq=2,
        supersedes_record_id="C_PRED",
        status=CoverageStatus.COMPLETE,
    )
    succ2 = make_coverage_record(
        record_id="C_SUCC2",
        revision_seq=2,
        supersedes_record_id="C_PRED",
        status=CoverageStatus.INCOMPLETE, # Conflicting status!
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[pred, succ1, succ2],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.UNCERTAIN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.AMBIGUOUS_FORK for d in result.diagnostics)


def test_aut_syn_20_compatible_overlapping_certificates() -> None:
    """AUT-SYN-20: Compatible overlapping certificates do not shrink coverage."""
    builder = AuthorityContextBuilder()
    # Cert A covers [T0, T2]
    cA = make_coverage_record(
        record_id="CA",
        covered_interval_start=T0,
        covered_interval_end=T2,
        status=CoverageStatus.COMPLETE,
    )
    # Cert B covers [T1, T4]
    cB = make_coverage_record(
        record_id="CB",
        covered_interval_start=T1,
        covered_interval_end=T4,
        status=CoverageStatus.COMPLETE,
    )

    # Required interval [T1, T2] is fully covered by both independently
    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cA, cB],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.COMPLETE
    assert result.authoritative_coverage_record is not None


def test_aut_syn_21_overlapping_conflict_inside_required_interval() -> None:
    """AUT-SYN-21: Conflicting statuses inside required interval degrade to UNCERTAIN."""
    builder = AuthorityContextBuilder()
    cA = make_coverage_record(
        record_id="CA",
        covered_interval_start=T0,
        covered_interval_end=T3,
        status=CoverageStatus.COMPLETE,
    )
    cB = make_coverage_record(
        record_id="CB",
        covered_interval_start=T1,
        covered_interval_end=T4,
        status=CoverageStatus.INCOMPLETE, # Conflicting!
    )

    # Required interval [T1, T2] is inside the overlap [T1, T3]
    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cA, cB],
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
    )

    assert result.resolved_coverage_status == CoverageStatus.UNCERTAIN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.INTERSECTING_CONFLICT for d in result.diagnostics)


def test_aut_syn_22_overlapping_conflict_outside_required_interval() -> None:
    """AUT-SYN-22: Conflicting statuses entirely outside required interval do NOT impair coverage."""
    builder = AuthorityContextBuilder()
    # Cert A covers required interval [T0, T2] cleanly
    cA = make_coverage_record(
        record_id="CA",
        covered_interval_start=T0,
        covered_interval_end=T2,
        status=CoverageStatus.COMPLETE,
    )
    # Cert B and Cert C conflict in [T3, T4], which is entirely outside [T0, T1]
    cB = make_coverage_record(
        record_id="CB",
        covered_interval_start=T3,
        covered_interval_end=T4,
        status=CoverageStatus.COMPLETE,
    )
    cC = make_coverage_record(
        record_id="CC",
        covered_interval_start=T3,
        covered_interval_end=T4,
        status=CoverageStatus.INCOMPLETE,
    )

    result = builder.validate_and_build(
        usage_records=[],
        coverage_records=[cA, cB, cC],
        evaluation_time=T4,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T0,
        required_interval_end=T1, # Required interval does NOT intersect [T3, T4]
    )

    assert result.resolved_coverage_status == CoverageStatus.COMPLETE
    assert result.authoritative_coverage_record.record_id == "CA"


def test_aut_syn_23_equal_time_linked_vs_unlinked_precedence() -> None:
    """AUT-SYN-23: Equal-time linked update vs unlinked conflicting updates."""
    builder = AuthorityContextBuilder()

    # Sub-case A: Equal-time linked update (usage)
    # Both available at T2; u2 has predecessor u1 and established T2 >= T1
    u1 = make_usage_record(record_id="U1", status=UsageEvidenceStatus.UNUSED, established_time=T1, available_time=T2)
    u2 = make_usage_record(
        record_id="U2",
        status=UsageEvidenceStatus.USED,
        established_time=T2,
        available_time=T2,
        predecessor_record_id="U1",
    )

    res_linked = builder.validate_and_build(
        usage_records=[u1, u2],
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )
    # Linked successor validly establishes causal order
    assert res_linked.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.USED

    # Sub-case B: Equal-time unlinked conflicting update
    u3 = make_usage_record(record_id="U3", status=UsageEvidenceStatus.UNUSED, established_time=T2, available_time=T2)
    u4 = make_usage_record(record_id="U4", status=UsageEvidenceStatus.USED, established_time=T2, available_time=T2)

    res_unlinked = builder.validate_and_build(
        usage_records=[u3, u4],
        coverage_records=[],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )
    # Unlinked conflicting updates degrade to UNKNOWN
    assert res_unlinked.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert any(d.diagnostic_reason == AuthorityDiagnosticReason.CONTRADICTORY_ASSERTION for d in res_unlinked.diagnostics)


# -----------------------------------------------------------------------------
# Builder Properties: Immutability, Permutation Invariance & Determinism
# -----------------------------------------------------------------------------

def test_builder_input_immutability_and_permutation_invariance() -> None:
    """Verifies input collections are not mutated and result is invariant to record order."""
    builder = AuthorityContextBuilder()
    u1 = make_usage_record(record_id="U1", status=UsageEvidenceStatus.UNUSED, established_time=T1, available_time=T1)
    u2 = make_usage_record(
        record_id="U2",
        status=UsageEvidenceStatus.USED,
        established_time=T2,
        available_time=T2,
        predecessor_record_id="U1",
    )
    c1 = make_coverage_record(record_id="C1", revision_seq=1, available_time=T1)
    c2 = make_coverage_record(record_id="C2", revision_seq=2, supersedes_record_id="C1", available_time=T2)

    usage_list_orig = [u1, u2]
    cov_list_orig = [c1, c2]

    usage_list_perm = [u2, u1]
    cov_list_perm = [c2, c1]

    # Repeated evaluation on orig
    res1 = builder.validate_and_build(
        usage_records=usage_list_orig,
        coverage_records=cov_list_orig,
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    res2 = builder.validate_and_build(
        usage_records=usage_list_orig,
        coverage_records=cov_list_orig,
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    # Permuted inputs
    res_perm = builder.validate_and_build(
        usage_records=usage_list_perm,
        coverage_records=cov_list_perm,
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    # Immutability of inputs
    assert usage_list_orig == [u1, u2]
    assert cov_list_orig == [c1, c2]

    # Determinism across repeated calls
    assert res1 == res2

    # Permutation invariance
    assert res1.resolved_coverage_status == res_perm.resolved_coverage_status
    assert res1.resolved_usage_statuses == res_perm.resolved_usage_statuses
    assert res1.authoritative_coverage_record == res_perm.authoritative_coverage_record
    assert res1.authoritative_usage_records == res_perm.authoritative_usage_records
    assert set(res1.diagnostics) == set(res_perm.diagnostics)


def test_trust_configuration_issuer_filtering() -> None:
    """Verifies records from untrusted issuers are rejected with ISSUER_NOT_TRUSTED."""
    custom_trust = TrustConfiguration(
        trusted_usage_issuers=("AUTHORIZED_USAGE_ISSUER",),
        trusted_coverage_issuers=("AUTHORIZED_COVERAGE_ISSUER",),
    )
    builder = AuthorityContextBuilder(trust_config=custom_trust)

    cov_untrusted = make_coverage_record(record_id="C_UNTRUST", issuer_id="UNTRUSTED_ISSUER")
    usg_untrusted = make_usage_record(record_id="U_UNTRUST", issuer_id="UNTRUSTED_ISSUER")

    res = builder.validate_and_build(
        usage_records=[usg_untrusted],
        coverage_records=[cov_untrusted],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert res.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert res.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert any(
        d.diagnostic_reason == AuthorityDiagnosticReason.ISSUER_NOT_TRUSTED and d.entity_key == "C_UNTRUST"
        for d in res.diagnostics
    )
    assert any(
        d.diagnostic_reason == AuthorityDiagnosticReason.ISSUER_NOT_TRUSTED and d.entity_key == "U_UNTRUST"
        for d in res.diagnostics
    )


def test_schema_version_filtering() -> None:
    """Verifies records with unsupported schema version are rejected with INVALID_SCHEMA_VERSION."""
    builder = AuthorityContextBuilder()
    cov_v2 = make_coverage_record(record_id="C_V2", schema_version="v2_unsupported")
    usg_v2 = make_usage_record(record_id="U_V2", schema_version="v2_unsupported")

    res = builder.validate_and_build(
        usage_records=[usg_v2],
        coverage_records=[cov_v2],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    assert res.resolved_coverage_status == CoverageStatus.INCOMPLETE
    assert res.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNKNOWN
    assert any(
        d.diagnostic_reason == AuthorityDiagnosticReason.INVALID_SCHEMA_VERSION and d.entity_key == "C_V2"
        for d in res.diagnostics
    )
    assert any(
        d.diagnostic_reason == AuthorityDiagnosticReason.INVALID_SCHEMA_VERSION and d.entity_key == "U_V2"
        for d in res.diagnostics
    )


# -----------------------------------------------------------------------------
# End-to-End Matcher Composition Tests
# -----------------------------------------------------------------------------

def test_matcher_composition_authorized_match_and_rejection() -> None:
    """Tests full pipeline from AuthorityContextBuilder into ConfirmationMatcher."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(record_id="C_VALID", status=CoverageStatus.COMPLETE)
    usg_unused = make_usage_record(record_id="U_UNUSED", status=UsageEvidenceStatus.UNUSED)

    auth_res = builder.validate_and_build(
        usage_records=[usg_unused],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    m_k = format_member_key("SET_1", "TJL2_A_PLUS")
    base_member = SourceMemberReference(
        engine_id="TJL",
        symbol="EURUSD",
        source_timeframe="H1",
        set_id="SET_1",
        role="TJL2_A_PLUS",
        side="HIGH",
        lower_edge=1.2000,
        upper_edge=1.2020,
        is_line=False,
        direction=Direction.UPWARD,
        level_id=LEVEL_A,
        eligibility_available_time=T1,
        usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
    )

    ctx, updated_members = builder.build_matching_context(
        authority_result=auth_res,
        base_members={m_k: base_member},
        domain_session_id="SESS_01",
        revision_id="REV_01",
        expected_price_basis=PRICE_BASIS,
        expected_confirmation_config_id=CONF_CFG,
        matching_sequence_domain=SEQ_DOMAIN,
        evaluation_time=T2,
        source_resolution_status={m_k: True}, # Explicitly resolved!
    )

    matcher = ConfirmationPairMatcher()
    act = make_activation_record(
        activation_id="ACT_01",
        usage_evidence_status=updated_members[m_k].usage_evidence_status,
    )
    ev = make_evidence_record(
        event_id="EV_01",
        activation_id="ACT_01",
        source_member_key=m_k,
    )

    # 1. Matching case: All conditions valid -> MATCHED
    match_res = matcher.match(act, ev, ctx)
    assert match_res.status == ConfirmationMatchStatus.MATCHED
    assert match_res.candidate_record is not None

    # 2. Rejection case: When usage is USED -> STALE_EVIDENCE_FOR_GENERATION
    usg_used = make_usage_record(record_id="U_USED", status=UsageEvidenceStatus.USED)
    auth_res_used = builder.validate_and_build(
        usage_records=[usg_used],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )
    ctx_used, updated_members_used = builder.build_matching_context(
        authority_result=auth_res_used,
        base_members={m_k: base_member},
        domain_session_id="SESS_01",
        revision_id="REV_01",
        expected_price_basis=PRICE_BASIS,
        expected_confirmation_config_id=CONF_CFG,
        matching_sequence_domain=SEQ_DOMAIN,
        evaluation_time=T2,
        source_resolution_status={m_k: True},
    )
    act_used = make_activation_record(
        activation_id="ACT_01",
        usage_evidence_status=updated_members_used[m_k].usage_evidence_status,
    )
    match_res_used = matcher.match(act_used, ev, ctx_used)
    assert match_res_used.status == ConfirmationMatchStatus.REJECTED
    assert ConfirmationRejectionReason.STALE_EVIDENCE_FOR_GENERATION in match_res_used.rejection_reasons

    # 3. Rejection case: When coverage is INCOMPLETE -> INCOMPLETE_COVERAGE
    auth_res_inc = builder.validate_and_build(
        usage_records=[usg_unused],
        coverage_records=[], # No coverage
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )
    ctx_inc, _ = builder.build_matching_context(
        authority_result=auth_res_inc,
        base_members={m_k: base_member},
        domain_session_id="SESS_01",
        revision_id="REV_01",
        expected_price_basis=PRICE_BASIS,
        expected_confirmation_config_id=CONF_CFG,
        matching_sequence_domain=SEQ_DOMAIN,
        evaluation_time=T2,
        source_resolution_status={m_k: True},
    )
    match_res_inc = matcher.match(act, ev, ctx_inc)
    assert match_res_inc.status == ConfirmationMatchStatus.REJECTED
    assert ConfirmationRejectionReason.INCOMPLETE_COVERAGE in match_res_inc.rejection_reasons


def test_aut_syn_10_incomplete_confirmation_evidence() -> None:
    """AUT-SYN-10: Incomplete confirmation evidence is rejected with INCOMPLETE_EVIDENCE."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(record_id="C_VALID", status=CoverageStatus.COMPLETE)
    usg = make_usage_record(record_id="U_UNUSED", status=UsageEvidenceStatus.UNUSED)

    auth_res = builder.validate_and_build(
        usage_records=[usg],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    m_k = format_member_key("SET_1", "TJL2_A_PLUS")
    base_member = SourceMemberReference(
        engine_id="TJL",
        symbol="EURUSD",
        source_timeframe="H1",
        set_id="SET_1",
        role="TJL2_A_PLUS",
        side="HIGH",
        lower_edge=1.2000,
        upper_edge=1.2020,
        is_line=False,
        direction=Direction.UPWARD,
        level_id=LEVEL_A,
        eligibility_available_time=T1,
        usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
    )

    ctx, updated_members = builder.build_matching_context(
        authority_result=auth_res,
        base_members={m_k: base_member},
        domain_session_id="SESS_01",
        revision_id="REV_01",
        expected_price_basis=PRICE_BASIS,
        expected_confirmation_config_id=CONF_CFG,
        matching_sequence_domain=SEQ_DOMAIN,
        evaluation_time=T2,
        source_resolution_status={m_k: True},
    )

    matcher = ConfirmationPairMatcher()
    act = make_activation_record(
        activation_id="ACT_01",
        level_id=LEVEL_A,
        usage_evidence_status=updated_members[m_k].usage_evidence_status,
    )
    # Incomplete evidence (is_completed=False)
    ev_incomplete = make_evidence_record(
        event_id="EV_INC",
        activation_id="ACT_01",
        source_member_key=m_k,
        is_completed=False,
    )

    match_res = matcher.match(act, ev_incomplete, ctx)
    assert match_res.status == ConfirmationMatchStatus.REJECTED
    assert ConfirmationRejectionReason.INCOMPLETE_EVIDENCE in match_res.rejection_reasons


def test_authority_validation_alone_does_not_manufacture_candidate() -> None:
    """Passing authority validation is a precondition, not an independent match producer."""
    builder = AuthorityContextBuilder()
    cov = make_coverage_record(record_id="C_VALID", status=CoverageStatus.COMPLETE)
    usg = make_usage_record(record_id="U_UNUSED", status=UsageEvidenceStatus.UNUSED)

    auth_res = builder.validate_and_build(
        usage_records=[usg],
        coverage_records=[cov],
        evaluation_time=T2,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )

    # Preconditions pass
    assert auth_res.resolved_coverage_status == CoverageStatus.COMPLETE
    assert auth_res.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNUSED

    # But without matching evidence and activation, NO candidate record is produced by the builder
    # The builder only outputs AuthorityBuildResult with resolved statuses and diagnostics
    assert isinstance(auth_res, AuthorityBuildResult)
    assert not hasattr(auth_res, "candidate_record")


def test_point_in_time_usage_successor_availability() -> None:
    """Usage successor is ignored before its availability time; governs after."""
    builder = AuthorityContextBuilder()
    u_pred = make_usage_record(
        record_id="U_PRED",
        status=UsageEvidenceStatus.UNUSED,
        established_time=T1,
        available_time=T1,
    )
    u_succ = make_usage_record(
        record_id="U_SUCC",
        status=UsageEvidenceStatus.USED,
        established_time=T2,
        available_time=T2,
        predecessor_record_id="U_PRED",
    )

    t1_5 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    # Before u_succ availability: only u_pred is visible
    res_before = builder.validate_and_build(
        usage_records=[u_pred, u_succ],
        coverage_records=[],
        evaluation_time=t1_5,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=t1_5,
        physical_levels=[LEVEL_A],
    )
    assert res_before.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.UNUSED
    assert res_before.authoritative_usage_records[LEVEL_A].record_id == "U_PRED"

    # After u_succ availability: u_succ supersedes u_pred
    res_after = builder.validate_and_build(
        usage_records=[u_pred, u_succ],
        coverage_records=[],
        evaluation_time=T3,
        target_feed_id=FEED_ID,
        target_sequence_domain=SEQ_DOMAIN,
        target_timeframe=TIMEFRAME,
        target_confirmation_config_id=CONF_CFG,
        required_interval_start=T1,
        required_interval_end=T2,
        physical_levels=[LEVEL_A],
    )
    assert res_after.resolved_usage_statuses[LEVEL_A] == UsageEvidenceStatus.USED
    assert res_after.authoritative_usage_records[LEVEL_A].record_id == "U_SUCC"
