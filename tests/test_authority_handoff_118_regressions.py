"""Decisive regression tests for HANDOFF-118/119 findings.

Specifically addresses Perplexity Milestone 35 / HANDOFF-118 & HANDOFF-119 directives:
1. Full-chain usage transition validity: An invalid usage transition at any edge invalidates
   all descendants (reason: INVALID_ANCESTOR) while preserving the independently valid terminal
   USED record and its authoritative provenance, immune to input ordering and permutation.
   - Chain 1: A: USED -> B: UNUSED (pred=A) -> C: UNKNOWN (pred=B) -> D: UNUSED (pred=C)
   - Chain 2: A: UNUSED -> B: USED (pred=A) -> C: UNUSED (pred=B) -> D: UNKNOWN (pred=C)
   - Both chain shapes tested across multiple ID assignment schemes (chronological, reverse-alphabetic, scrambled)
     and asserted for complete returned (resolved, authoritative, diagnostics) tuple equality across all permutations.
2. Strict TrustConfiguration validation: Rejects scalar strings with TypeError, rejects empty/whitespace
   issuers with ValueError, canonicalizes to sorted unique tuples. Rejects boolean revision_seq (type is int).
3. Direct CoveragePreprocessor.process() validation: Enforces required_interval_start <= required_interval_end
   and required_interval_end <= evaluation_time on direct public calls.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import itertools
from typing import List, Tuple
import pytest

from aladeen.strategy.activation_types import (
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    UsageEvidenceStatus,
)
from aladeen.strategy.authority_context_builder import AuthorityContextBuilder
from aladeen.strategy.authority_types import (
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
)
from aladeen.strategy.coverage_preprocessor import CoveragePreprocessor
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.usage_preprocessor import UsagePreprocessor


FEED_ID = "FEED_EURUSD_H1"
SEQ_DOMAIN = SequenceDomain(feed_id=FEED_ID, run_id="RUN_001")
TIMEFRAME = "H1"
CONF_CFG = "CONF_CFG_01"

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
T4 = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
T5 = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)

LEVEL_A = StableLevelId(
    symbol_feed_id=FEED_ID,
    source_timeframe=TIMEFRAME,
    source_open_time=T0,
    side=TJLSide.HIGH,
)

DEFAULT_TRUST = TrustConfiguration(
    trusted_usage_issuers=("UPSTREAM_TRADE_LEDGER_OFFLINE",),
    trusted_coverage_issuers=("OFFLINE_FEED_AUDITOR_v1",),
)


def make_usage(
    record_id: str,
    status: UsageEvidenceStatus,
    established_time: datetime,
    predecessor_record_id: str | None = None,
    level_id: StableLevelId = LEVEL_A,
    available_time: datetime = T4,
    issuer_id: str = "UPSTREAM_TRADE_LEDGER_OFFLINE",
) -> ProposedUsageEvidenceRecord:
    return ProposedUsageEvidenceRecord(
        record_id=record_id,
        schema_version="v1",
        issuer_id=issuer_id,
        level_id=level_id,
        status=status,
        established_time=established_time,
        available_time=available_time,
        provenance_ref=f"PROV_{record_id}",
        predecessor_record_id=predecessor_record_id,
    )


# =============================================================================
# Finding 1 Regressions: Full-chain transition validity & descendant invalidation
# =============================================================================

class TestUsageFullChainTransitionValidity:
    """Regressions for Finding 1: Every ancestor edge must be validated.
    
    Invalid transitions (e.g. USED -> UNUSED) must invalidate the immediate offender
    (USAGE_USED_TERMINAL) and all subsequent descendants (INVALID_ANCESTOR), while
    preserving the valid terminal USED fact and its authoritative provenance.
    """

    def test_chain_1_used_to_unused_to_unknown_invalidation(self) -> None:
        """Chain 1: A: USED -> B: UNUSED (pred=A) -> C: UNKNOWN (pred=B).
        
        Asserts:
        - B is rejected with USAGE_USED_TERMINAL.
        - C is rejected with INVALID_ANCESTOR (does not pass merely because C!=UNUSED).
        - A is NOT superseded by invalid successors B or C.
        - Level resolves to USED.
        - Authoritative usage record is preserved as A.
        - Supersession diagnostic is NOT emitted for A (A remains the active authority).
        """
        rec_a = make_usage("REC_A", UsageEvidenceStatus.USED, established_time=T1)
        rec_b = make_usage("REC_B", UsageEvidenceStatus.UNUSED, established_time=T2, predecessor_record_id="REC_A")
        rec_c = make_usage("REC_C", UsageEvidenceStatus.UNKNOWN, established_time=T3, predecessor_record_id="REC_B")

        preprocessor = UsagePreprocessor(trust_config=DEFAULT_TRUST)
        resolved, authoritative, diags = preprocessor.process(
            usage_records=(rec_a, rec_b, rec_c),
            evaluation_time=T4,
            physical_levels=(LEVEL_A,),
        )

        assert resolved[LEVEL_A] == UsageEvidenceStatus.USED
        assert LEVEL_A in authoritative
        assert authoritative[LEVEL_A].record_id == "REC_A"
        assert authoritative[LEVEL_A].status == UsageEvidenceStatus.USED

        # Inspect diagnostics: B rejected for terminal reset, C rejected for invalid ancestor
        diag_map = {d.entity_key: d for d in diags}
        assert "REC_B" in diag_map
        assert diag_map["REC_B"].diagnostic_reason == AuthorityDiagnosticReason.USAGE_USED_TERMINAL
        assert "REC_C" in diag_map
        assert diag_map["REC_C"].diagnostic_reason == AuthorityDiagnosticReason.INVALID_ANCESTOR

        # A was not superseded
        superseded_recs = {
            d.entity_key for d in diags
            if d.diagnostic_reason == AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION
        }
        assert "REC_A" not in superseded_recs

    def test_chain_1_with_d_rejected_and_a_retains_authority(self) -> None:
        """Chain 1 extended: A: USED -> B: UNUSED (pred=A) -> C: UNKNOWN (pred=B) -> D: UNUSED (pred=C).
        
        Under any ordering, invalid descendants B, C, D cannot retire A in the supersession loop.
        """
        rec_a = make_usage("REC_A", UsageEvidenceStatus.USED, established_time=T1)
        rec_b = make_usage("REC_B", UsageEvidenceStatus.UNUSED, established_time=T2, predecessor_record_id="REC_A")
        rec_c = make_usage("REC_C", UsageEvidenceStatus.UNKNOWN, established_time=T3, predecessor_record_id="REC_B")
        rec_d = make_usage("REC_D", UsageEvidenceStatus.UNUSED, established_time=T4, predecessor_record_id="REC_C")

        preprocessor = UsagePreprocessor(trust_config=DEFAULT_TRUST)
        resolved, authoritative, diags = preprocessor.process(
            usage_records=(rec_a, rec_b, rec_c, rec_d),
            evaluation_time=T5,
            physical_levels=(LEVEL_A,),
        )

        assert resolved[LEVEL_A] == UsageEvidenceStatus.USED
        assert authoritative[LEVEL_A].record_id == "REC_A"

        diag_reasons = {d.entity_key: d.diagnostic_reason for d in diags}
        assert diag_reasons["REC_B"] == AuthorityDiagnosticReason.USAGE_USED_TERMINAL
        assert diag_reasons["REC_C"] == AuthorityDiagnosticReason.INVALID_ANCESTOR
        assert diag_reasons["REC_D"] == AuthorityDiagnosticReason.INVALID_ANCESTOR

    def test_chain_2_unused_to_used_to_unused_to_unknown(self) -> None:
        """Chain 2: A: UNUSED -> B: USED (pred=A) -> C: UNUSED (pred=B) -> D: UNKNOWN (pred=C).
        
        Asserts:
        - B validly supersedes A (A is marked SUPERSEDED_BY_VALID_REVISION).
        - C attempts invalid reset from USED to UNUSED -> rejected with USAGE_USED_TERMINAL.
        - D is descendant of invalid C -> rejected with INVALID_ANCESTOR.
        - Level resolves to USED.
        - Authoritative usage record is B (the valid terminal USED fact).
        - D never supersedes B.
        """
        rec_a = make_usage("REC_A", UsageEvidenceStatus.UNUSED, established_time=T1)
        rec_b = make_usage("REC_B", UsageEvidenceStatus.USED, established_time=T2, predecessor_record_id="REC_A")
        rec_c = make_usage("REC_C", UsageEvidenceStatus.UNUSED, established_time=T3, predecessor_record_id="REC_B")
        rec_d = make_usage("REC_D", UsageEvidenceStatus.UNKNOWN, established_time=T4, predecessor_record_id="REC_C")

        preprocessor = UsagePreprocessor(trust_config=DEFAULT_TRUST)
        resolved, authoritative, diags = preprocessor.process(
            usage_records=(rec_a, rec_b, rec_c, rec_d),
            evaluation_time=T5,
            physical_levels=(LEVEL_A,),
        )

        assert resolved[LEVEL_A] == UsageEvidenceStatus.USED
        assert LEVEL_A in authoritative
        assert authoritative[LEVEL_A].record_id == "REC_B"
        assert authoritative[LEVEL_A].status == UsageEvidenceStatus.USED

        diag_reasons = {d.entity_key: d.diagnostic_reason for d in diags}
        assert diag_reasons["REC_A"] == AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION
        assert diag_reasons["REC_C"] == AuthorityDiagnosticReason.USAGE_USED_TERMINAL
        assert diag_reasons["REC_D"] == AuthorityDiagnosticReason.INVALID_ANCESTOR

        # B was NOT superseded
        superseded_recs = {
            d.entity_key for d in diags
            if d.diagnostic_reason == AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION
        }
        assert "REC_B" not in superseded_recs

    @pytest.mark.parametrize("chain_shape", ["chain_1", "chain_2"])
    @pytest.mark.parametrize(
        "id_scheme",
        [
            ("REC_01_A", "REC_02_B", "REC_03_C", "REC_04_D"),  # alphabetic matches chronological
            ("ID_Z_01", "ID_Y_02", "ID_X_03", "ID_W_04"),      # alphabetic reverse of chronological
            ("ID_M_ROOT", "ID_Z_TERM", "ID_A_INV", "ID_K_DESC"), # alphabetic scrambled relative to chronological
        ],
    )
    def test_chain_complete_result_permutation_equality_and_immutability(
        self, chain_shape: str, id_scheme: Tuple[str, str, str, str]
    ) -> None:
        """Comprehensive verification of permutation invariance, ID independence, and input immutability.
        
        Tests both Chain 1 and Chain 2 shapes across multiple record-ID assignments.
        Asserts that every single permutation of the 4 records produces identical complete returned
        tuples: (resolved, authoritative, diagnostics) == (ref_resolved, ref_authoritative, ref_diagnostics),
        and that input records remain strictly unmodified.
        """
        id1, id2, id3, id4 = id_scheme

        if chain_shape == "chain_1":
            # Chain 1: Node 1: USED -> Node 2: UNUSED (pred=Node 1) -> Node 3: UNKNOWN (pred=Node 2) -> Node 4: UNUSED (pred=Node 3)
            r1 = make_usage(id1, UsageEvidenceStatus.USED, established_time=T1)
            r2 = make_usage(id2, UsageEvidenceStatus.UNUSED, established_time=T2, predecessor_record_id=id1)
            r3 = make_usage(id3, UsageEvidenceStatus.UNKNOWN, established_time=T3, predecessor_record_id=id2)
            r4 = make_usage(id4, UsageEvidenceStatus.UNUSED, established_time=T4, predecessor_record_id=id3)
            expected_auth_id = id1
            expected_superseded_ids: set[str] = set()
            expected_terminal_rejections = {id2, id4}
            expected_invalid_ancestor = {id3, id4}
        else:
            # Chain 2: Node 1: UNUSED -> Node 2: USED (pred=Node 1) -> Node 3: UNUSED (pred=Node 2) -> Node 4: UNKNOWN (pred=Node 3)
            r1 = make_usage(id1, UsageEvidenceStatus.UNUSED, established_time=T1)
            r2 = make_usage(id2, UsageEvidenceStatus.USED, established_time=T2, predecessor_record_id=id1)
            r3 = make_usage(id3, UsageEvidenceStatus.UNUSED, established_time=T3, predecessor_record_id=id2)
            r4 = make_usage(id4, UsageEvidenceStatus.UNKNOWN, established_time=T4, predecessor_record_id=id3)
            expected_auth_id = id2
            expected_superseded_ids = {id1}
            expected_terminal_rejections = {id3}
            expected_invalid_ancestor = {id4}

        canonical_records = [r1, r2, r3, r4]
        preprocessor = UsagePreprocessor(trust_config=DEFAULT_TRUST)

        # Compute reference result from canonical chronological ordering
        ref_resolved, ref_auth, ref_diags = preprocessor.process(
            usage_records=canonical_records,
            evaluation_time=T5,
            physical_levels=(LEVEL_A,),
        )

        # Baseline checks on reference result
        assert ref_resolved[LEVEL_A] == UsageEvidenceStatus.USED
        assert ref_auth[LEVEL_A].record_id == expected_auth_id
        assert ref_auth[LEVEL_A].status == UsageEvidenceStatus.USED

        ref_diag_map = {d.entity_key: d.diagnostic_reason for d in ref_diags}
        for s_id in expected_superseded_ids:
            assert ref_diag_map.get(s_id) == AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION
        assert expected_auth_id not in {
            d.entity_key for d in ref_diags
            if d.diagnostic_reason == AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION
        }

        # Assert every one of the 24 permutations produces exact complete result equality
        for perm in itertools.permutations(canonical_records):
            perm_copies = copy.deepcopy(perm)
            resolved, authoritative, diags = preprocessor.process(
                usage_records=perm,
                evaluation_time=T5,
                physical_levels=(LEVEL_A,),
            )

            # Complete returned (resolved, authoritative, diagnostics) tuple equality
            assert resolved == ref_resolved
            assert authoritative == ref_auth
            assert diags == ref_diags

            # Input immutability
            assert perm == perm_copies


# =============================================================================
# Finding 2 Regressions: Strict TrustConfiguration & ProposedFeedCoverageRecord validation
# =============================================================================

class TestTrustConfigurationAndRevisionValidation:
    """Regressions for Finding 2:
    - Scalar strings passed to TrustConfiguration raise TypeError.
    - Non-empty strings required, malformed/whitespace elements raise ValueError.
    - Collections are canonicalized to sorted tuples of stripped unique strings.
    - ProposedFeedCoverageRecord rejects bool revision_seq values (type is int).
    """

    def test_trust_config_rejects_scalar_string_with_type_error(self) -> None:
        """Scalar strings like 'OFFLINE_ISSUER' must not be silently decomposed into char tuples."""
        with pytest.raises(TypeError, match="must be a collection of strings, got scalar str"):
            TrustConfiguration(trusted_usage_issuers="OFFLINE_ISSUER")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="must be a collection of strings, got scalar str"):
            TrustConfiguration(trusted_coverage_issuers="OFFLINE_AUDITOR")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="must be a collection of strings, got scalar bytes"):
            TrustConfiguration(trusted_usage_issuers=b"OFFLINE_ISSUER")  # type: ignore[arg-type]

    def test_trust_config_rejects_empty_or_whitespace_elements(self) -> None:
        """Elements must be non-empty strings."""
        with pytest.raises(ValueError, match="must be non-empty strings"):
            TrustConfiguration(trusted_usage_issuers=("VALID", ""))

        with pytest.raises(ValueError, match="must be non-empty strings"):
            TrustConfiguration(trusted_usage_issuers=("VALID", "   "))

        with pytest.raises(ValueError, match="must be non-empty strings"):
            TrustConfiguration(trusted_coverage_issuers=("VALID", None))  # type: ignore[arg-type]

    def test_trust_config_canonicalizes_to_sorted_unique_tuple(self) -> None:
        """Trust declarations are canonicalized consistently: deduplicated, stripped, and sorted."""
        cfg = TrustConfiguration(
            trusted_usage_issuers=["ISSUER_B", "ISSUER_A", " ISSUER_B ", "ISSUER_C"],
            trusted_coverage_issuers=("AUDITOR_Z", "AUDITOR_A", "AUDITOR_Z"),
        )
        assert cfg.trusted_usage_issuers == ("ISSUER_A", "ISSUER_B", "ISSUER_C")
        assert cfg.trusted_coverage_issuers == ("AUDITOR_A", "AUDITOR_Z")

    def test_proposed_feed_coverage_record_rejects_boolean_revision_seq(self) -> None:
        """ProposedFeedCoverageRecord must reject bool for revision_seq even though isinstance(True, int) is True."""
        with pytest.raises(ValueError, match="revision_seq must be positive integer >= 1 \\(bool not permitted\\)"):
            ProposedFeedCoverageRecord(
                record_id="COV_01",
                schema_version="v1",
                issuer_id="OFFLINE_FEED_AUDITOR_v1",
                feed_id=FEED_ID,
                sequence_domain=SEQ_DOMAIN,
                timeframe=TIMEFRAME,
                confirmation_config_id=CONF_CFG,
                covered_interval_start=T0,
                covered_interval_end=T4,
                status=CoverageStatus.COMPLETE,
                issued_time=T1,
                available_time=T1,
                revision_seq=True,  # type: ignore[arg-type]
            )

        with pytest.raises(ValueError, match="revision_seq must be positive integer >= 1 \\(bool not permitted\\)"):
            ProposedFeedCoverageRecord(
                record_id="COV_01",
                schema_version="v1",
                issuer_id="OFFLINE_FEED_AUDITOR_v1",
                feed_id=FEED_ID,
                sequence_domain=SEQ_DOMAIN,
                timeframe=TIMEFRAME,
                confirmation_config_id=CONF_CFG,
                covered_interval_start=T0,
                covered_interval_end=T4,
                status=CoverageStatus.COMPLETE,
                issued_time=T1,
                available_time=T1,
                revision_seq=False,  # type: ignore[arg-type]
            )


# =============================================================================
# Finding 3 Regressions: CoveragePreprocessor.process() direct-call interval checks
# =============================================================================

class TestCoveragePreprocessorDirectCallIntervalBoundaries:
    """Regressions for Finding 3: Direct public CoveragePreprocessor.process() calls must reject
    invalid interval requests:
    - required_interval_start > required_interval_end
    - required_interval_end > evaluation_time
    """

    def test_direct_process_rejects_inverted_interval(self) -> None:
        """Calling process() directly with start > end raises ValueError."""
        preprocessor = CoveragePreprocessor(trust_config=DEFAULT_TRUST)
        with pytest.raises(ValueError, match="cannot be after required_interval_end"):
            preprocessor.process(
                coverage_records=(),
                evaluation_time=T5,
                target_feed_id=FEED_ID,
                target_sequence_domain=SEQ_DOMAIN,
                target_timeframe=TIMEFRAME,
                target_confirmation_config_id=CONF_CFG,
                required_interval_start=T4,
                required_interval_end=T1,  # T1 < T4
            )

    def test_direct_process_rejects_interval_end_exceeding_evaluation_time(self) -> None:
        """Calling process() directly with required_interval_end > evaluation_time raises ValueError."""
        preprocessor = CoveragePreprocessor(trust_config=DEFAULT_TRUST)
        with pytest.raises(ValueError, match="cannot exceed evaluation_time"):
            preprocessor.process(
                coverage_records=(),
                evaluation_time=T4,
                target_feed_id=FEED_ID,
                target_sequence_domain=SEQ_DOMAIN,
                target_timeframe=TIMEFRAME,
                target_confirmation_config_id=CONF_CFG,
                required_interval_start=T0,
                required_interval_end=T5,  # T5 > T4
            )
