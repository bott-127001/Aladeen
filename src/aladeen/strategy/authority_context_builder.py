"""AuthorityContextBuilder — Modular orchestrator and matching context composer.

Scope & Design Boundary:
-------------------------
- Pure in-memory orchestration of CoveragePreprocessor and UsagePreprocessor.
- Strictly binds AuthorityBuildResult to validated request metadata.
- Composition requires exact compatible binding; rejects cross-config, cross-domain,
  earlier-time, or expanded-interval context reuse.
- Rejects any silent repair or contradiction of immutable activation metadata.
- Zero database writes, zero filesystem IO, zero live broker interaction.
"""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import (
    ActivationRecord,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
)
from .authority_types import (
    AuthorityBuildResult,
    AuthorityDiagnosticEntry,
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
)
from .confirmation_pair_matcher import MatchingContext
from .coverage_preprocessor import CoveragePreprocessor
from .tjl_types import StableLevelId
from .types import validate_and_normalize_timestamp
from .usage_preprocessor import UsagePreprocessor


class AuthorityContextBuilder:
    """Orchestrates offline authority preprocessing and builds validated MatchingContext."""

    def __init__(self, trust_config: Optional[TrustConfiguration] = None) -> None:
        self._trust_config = trust_config if trust_config is not None else TrustConfiguration()
        self._coverage_preprocessor = CoveragePreprocessor(self._trust_config)
        self._usage_preprocessor = UsagePreprocessor(self._trust_config)

    @property
    def trust_config(self) -> TrustConfiguration:
        return self._trust_config

    def validate_and_build(
        self,
        usage_records: Sequence[ProposedUsageEvidenceRecord],
        coverage_records: Sequence[ProposedFeedCoverageRecord],
        evaluation_time: datetime,
        target_feed_id: str,
        target_sequence_domain: SequenceDomain,
        target_timeframe: str,
        target_confirmation_config_id: str,
        required_interval_start: datetime,
        required_interval_end: datetime,
        physical_levels: Sequence[StableLevelId] = (),
    ) -> AuthorityBuildResult:
        """Execute the complete authority preprocessing pipeline."""
        eval_time = validate_and_normalize_timestamp(evaluation_time, "evaluation_time")
        req_start = validate_and_normalize_timestamp(required_interval_start, "required_interval_start")
        req_end = validate_and_normalize_timestamp(required_interval_end, "required_interval_end")

        if req_start > req_end:
            raise ValueError(
                f"required_interval_start ({req_start.isoformat()}) "
                f"cannot be after required_interval_end ({req_end.isoformat()})"
            )
        if req_end > eval_time:
            raise ValueError(
                f"required_interval_end ({req_end.isoformat()}) "
                f"cannot exceed evaluation_time ({eval_time.isoformat()})"
            )

        # 1. Process feed coverage certifications
        cov_status, auth_cov_rec, cov_diagnostics = self._coverage_preprocessor.process(
            coverage_records=coverage_records,
            evaluation_time=eval_time,
            target_feed_id=target_feed_id,
            target_sequence_domain=target_sequence_domain,
            target_timeframe=target_timeframe,
            target_confirmation_config_id=target_confirmation_config_id,
            required_interval_start=req_start,
            required_interval_end=req_end,
        )

        # 2. Process physical level usage evidence
        resolved_usage, auth_usage_map, usage_diagnostics = self._usage_preprocessor.process(
            usage_records=usage_records,
            evaluation_time=eval_time,
            physical_levels=physical_levels,
        )

        # Combine all diagnostics deterministically
        combined_diagnostics = list(cov_diagnostics) + list(usage_diagnostics)
        combined_diagnostics.sort(key=lambda d: (d.entity_key, d.diagnostic_reason.value, d.message))

        return AuthorityBuildResult(
            evaluation_time=eval_time,
            target_feed_id=target_feed_id,
            target_sequence_domain=target_sequence_domain,
            target_timeframe=target_timeframe,
            target_confirmation_config_id=target_confirmation_config_id,
            required_interval_start=req_start,
            required_interval_end=req_end,
            trust_config=self._trust_config,
            resolved_coverage_status=cov_status,
            resolved_usage_statuses=resolved_usage,
            diagnostics=tuple(combined_diagnostics),
            authoritative_coverage_record=auth_cov_rec,
            authoritative_usage_records=auth_usage_map,
        )

    def build_matching_context(
        self,
        authority_result: AuthorityBuildResult,
        base_members: Mapping[str, SourceMemberReference],
        domain_session_id: str,
        revision_id: str,
        expected_price_basis: PriceBasis,
        expected_confirmation_config_id: str,
        matching_sequence_domain: SequenceDomain,
        evaluation_time: datetime,
        source_resolution_status: Optional[Mapping[str, bool]] = None,
        expected_timeframe: Optional[str] = None,
        expected_interval_start: Optional[datetime] = None,
        expected_interval_end: Optional[datetime] = None,
        active_activations: Optional[Mapping[str, ActivationRecord]] = None,
    ) -> Tuple[MatchingContext, Dict[str, SourceMemberReference]]:
        """Map resolved authority into accepted MatchingContext and updated member references.

        Strictly enforces request binding compatibility between caller context and AuthorityBuildResult.
        Rejects cross-config, cross-domain, earlier/mismatched time, or expanded-interval reuse.
        Rejects any disagreement with immutable activation metadata.
        """
        eval_time = validate_and_normalize_timestamp(evaluation_time, "evaluation_time")

        # Strict Request Binding Validation
        if expected_confirmation_config_id != authority_result.target_confirmation_config_id:
            raise ValueError(
                f"Cross-config reuse rejected: context config {expected_confirmation_config_id!r} "
                f"!= authority bound config {authority_result.target_confirmation_config_id!r}"
            )

        if matching_sequence_domain != authority_result.target_sequence_domain:
            raise ValueError(
                f"Cross-domain reuse rejected: context domain {matching_sequence_domain} "
                f"!= authority bound domain {authority_result.target_sequence_domain}"
            )

        if matching_sequence_domain.feed_id != authority_result.target_feed_id:
            raise ValueError(
                f"Feed ID mismatch: context feed {matching_sequence_domain.feed_id!r} "
                f"!= authority bound feed {authority_result.target_feed_id!r}"
            )

        if eval_time != authority_result.evaluation_time:
            raise ValueError(
                f"Evaluation time mismatch: context time {eval_time.isoformat()} "
                f"!= authority bound time {authority_result.evaluation_time.isoformat()}"
            )

        if expected_timeframe is not None and expected_timeframe != authority_result.target_timeframe:
            raise ValueError(
                f"Timeframe mismatch: expected {expected_timeframe!r} "
                f"!= authority bound timeframe {authority_result.target_timeframe!r}"
            )

        if expected_interval_start is not None:
            norm_exp_start = validate_and_normalize_timestamp(expected_interval_start, "expected_interval_start")
            if norm_exp_start < authority_result.required_interval_start:
                raise ValueError(
                    f"Expanded interval reuse rejected: requested start {norm_exp_start.isoformat()} "
                    f"< authority validated start {authority_result.required_interval_start.isoformat()}"
                )

        if expected_interval_end is not None:
            norm_exp_end = validate_and_normalize_timestamp(expected_interval_end, "expected_interval_end")
            if norm_exp_end > authority_result.required_interval_end:
                raise ValueError(
                    f"Expanded interval reuse rejected: requested end {norm_exp_end.isoformat()} "
                    f"> authority validated end {authority_result.required_interval_end.isoformat()}"
                )

        # Update member usage evidence status based on resolved physical level usage
        updated_members: Dict[str, SourceMemberReference] = {}
        for m_k, mem in base_members.items():
            lvl = mem.level_id
            resolved_st = authority_result.resolved_usage_statuses.get(lvl, UsageEvidenceStatus.UNKNOWN)
            updated_mem = SourceMemberReference(
                engine_id=mem.engine_id,
                symbol=mem.symbol,
                source_timeframe=mem.source_timeframe,
                set_id=mem.set_id,
                role=mem.role,
                side=mem.side,
                lower_edge=mem.lower_edge,
                upper_edge=mem.upper_edge,
                is_line=mem.is_line,
                direction=mem.direction,
                level_id=mem.level_id,
                eligibility_available_time=mem.eligibility_available_time,
                usage_evidence_status=resolved_st,
            )
            updated_members[m_k] = updated_mem

        # Immutable activation metadata consistency check (blocks rather than silently repairing)
        if active_activations is not None:
            for act_k, act in active_activations.items():
                mem_k = act.member_key
                mem = updated_members.get(mem_k)
                if mem is not None:
                    if act.level_id != mem.level_id:
                        raise ValueError(
                            f"Activation {act.activation_id} level_id ({act.level_id}) "
                            f"contradicts registered member level_id ({mem.level_id})"
                        )
                    if act.symbol != mem.symbol or act.source_timeframe != mem.source_timeframe:
                        raise ValueError(
                            f"Activation {act.activation_id} symbol/timeframe contradicts registered member"
                        )
                    # If an activation already had immutable terminal USED status, authority cannot contradict it to UNUSED
                    if act.usage_evidence_status == UsageEvidenceStatus.USED and mem.usage_evidence_status == UsageEvidenceStatus.UNUSED:
                        raise ValueError(
                            f"Activation {act.activation_id} has immutable terminal USED status; "
                            f"authority resolution UNUSED contradicts immutable activation history"
                        )

        # Source resolution mapping: do not manufacture a True mapping
        src_res: Dict[str, bool] = {}
        if source_resolution_status is not None:
            src_res = dict(source_resolution_status)

        ctx = MatchingContext(
            domain_session_id=domain_session_id,
            revision_id=revision_id,
            expected_price_basis=expected_price_basis,
            expected_confirmation_config_id=expected_confirmation_config_id,
            matching_sequence_domain=matching_sequence_domain,
            evaluation_time=eval_time,
            current_members=updated_members,
            source_resolution_status=src_res,
            coverage_status=authority_result.resolved_coverage_status,
        )

        return ctx, updated_members
