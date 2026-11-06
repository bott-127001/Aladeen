"""UsagePreprocessor — Pure in-memory physical level usage validation preprocessor.

Scope & Design Boundary:
-------------------------
- Pure in-memory validation of physical-level usage evidence records.
- Implements Steps 1-3 of the Milestone 34 preprocessing pipeline for usage.
- Admissibility check precedes duplicate grouping to prevent poisoning from untrusted records.
- Recursive ancestor chain validation back to root.
- Multi-hop terminal usage preservation (USED fact permanently terminal on StableLevelId).
- Ambiguous forks fail closed as UNKNOWN; conflicting branches cannot restore UNUSED.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import UsageEvidenceStatus
from .authority_types import (
    AuthorityDiagnosticEntry,
    AuthorityDiagnosticReason,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
)
from .tjl_types import StableLevelId
from .types import validate_and_normalize_timestamp


class UsagePreprocessor:
    """Preprocesses and resolves authoritative physical-level usage evidence."""

    def __init__(self, trust_config: TrustConfiguration) -> None:
        self._trust_config = trust_config

    def process(
        self,
        usage_records: Sequence[ProposedUsageEvidenceRecord],
        evaluation_time: datetime,
        physical_levels: Sequence[StableLevelId] = (),
    ) -> Tuple[
        Mapping[StableLevelId, UsageEvidenceStatus],
        Mapping[StableLevelId, ProposedUsageEvidenceRecord],
        Tuple[AuthorityDiagnosticEntry, ...],
    ]:
        """Execute Steps 1-3 of usage preprocessing."""
        eval_time = validate_and_normalize_timestamp(evaluation_time, "evaluation_time")

        diagnostics: List[AuthorityDiagnosticEntry] = []
        emitted_future_rids: Set[str] = set()

        # Step 1: Temporal filter (both available_time and established_time <= eval_time)
        visible_usage: List[ProposedUsageEvidenceRecord] = []
        for usg in usage_records:
            if usg.available_time > eval_time:
                if usg.record_id not in emitted_future_rids:
                    emitted_future_rids.add(usg.record_id)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=usg.record_id,
                            diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE,
                            message=f"Usage record {usg.record_id} available at {usg.available_time.isoformat()} > eval_time {eval_time.isoformat()}",
                        )
                    )
            elif usg.established_time > eval_time:
                if usg.record_id not in emitted_future_rids:
                    emitted_future_rids.add(usg.record_id)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=usg.record_id,
                            diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_ESTABLISHED,
                            message=f"Usage record {usg.record_id} established at {usg.established_time.isoformat()} > eval_time {eval_time.isoformat()}",
                        )
                    )
            else:
                visible_usage.append(usg)

        # Step 2: Admissibility validation precedes duplicate grouping
        admissible_records: List[ProposedUsageEvidenceRecord] = []
        for usg in visible_usage:
            rid = usg.record_id
            if usg.schema_version != "v1":
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.INVALID_SCHEMA_VERSION,
                        message=f"Unsupported schema version: {usg.schema_version}",
                    )
                )
                continue

            if usg.issuer_id not in self._trust_config.trusted_usage_issuers:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.ISSUER_NOT_TRUSTED,
                        message=f"Usage issuer {usg.issuer_id} not in trusted usage issuers",
                    )
                )
                continue

            admissible_records.append(usg)

        # Duplicate grouping on admissible trusted records
        usage_by_id: Dict[str, List[ProposedUsageEvidenceRecord]] = {}
        for usg in admissible_records:
            usage_by_id.setdefault(usg.record_id, []).append(usg)

        coalesced_usage: Dict[str, ProposedUsageEvidenceRecord] = {}
        for rid in sorted(usage_by_id.keys()):
            group = usage_by_id[rid]
            if any(u != group[0] for u in group[1:]):
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.CONFLICTING_IDENTITY,
                        message=f"Usage record {rid} has conflicting payloads across duplicates",
                    )
                )
                continue
            coalesced_usage[rid] = group[0]

        # Step 3: Complete Predecessor Chain Validation, Fork Tracking & Multi-Hop Terminal Usage
        claimed_usage_predecessors: Dict[str, List[ProposedUsageEvidenceRecord]] = {}
        for rid, u in coalesced_usage.items():
            if u.predecessor_record_id:
                claimed_usage_predecessors.setdefault(u.predecessor_record_id, []).append(u)

        forked_usage_predecessors: Set[str] = set()
        levels_with_ambiguous_fork: Set[StableLevelId] = set()

        for pred_id, claimants in claimed_usage_predecessors.items():
            if len(claimants) > 1:
                first_st = claimants[0].status
                if any(c.status != first_st for c in claimants[1:]):
                    forked_usage_predecessors.add(pred_id)
                    # Track that the predecessor's level has an ambiguous contradictory fork
                    pred_rec = coalesced_usage.get(pred_id)
                    if pred_rec:
                        levels_with_ambiguous_fork.add(pred_rec.level_id)
                    for c in claimants:
                        levels_with_ambiguous_fork.add(c.level_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=c.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.AMBIGUOUS_FORK,
                                message=f"Ambiguous usage fork claiming predecessor {pred_id}",
                            )
                        )

        def validate_usage_chain(
            rec: ProposedUsageEvidenceRecord,
        ) -> Tuple[bool, Optional[AuthorityDiagnosticReason], Optional[str], bool]:
            visited: Set[str] = {rec.record_id}
            curr = rec
            has_used_ancestor = (rec.status == UsageEvidenceStatus.USED)

            while curr.predecessor_record_id is not None:
                p_id = curr.predecessor_record_id
                if p_id in visited:
                    return False, AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK, f"Cyclic usage chain involving {p_id}", False
                visited.add(p_id)

                if p_id in forked_usage_predecessors:
                    return False, AuthorityDiagnosticReason.AMBIGUOUS_FORK, f"Usage ancestor {p_id} has ambiguous forks", False

                pred = coalesced_usage.get(p_id)
                if pred is None:
                    return False, AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR, f"Usage predecessor {p_id} unknown or unavailable at {eval_time.isoformat()}", False

                if pred.level_id != curr.level_id:
                    return False, AuthorityDiagnosticReason.WRONG_SCOPE_SUPERSEDED, f"Usage level {curr.level_id} mismatches predecessor {pred.level_id}", False

                if curr.established_time < pred.established_time:
                    return False, AuthorityDiagnosticReason.INVALID_USAGE_TRANSITION, f"Usage established {curr.established_time.isoformat()} < predecessor {pred.established_time.isoformat()}", False

                if pred.status == UsageEvidenceStatus.USED:
                    has_used_ancestor = True

                curr = pred

            if has_used_ancestor and rec.status == UsageEvidenceStatus.UNUSED:
                return False, AuthorityDiagnosticReason.USAGE_USED_TERMINAL, f"Level {rec.level_id} has USED in ancestry; cannot reset to UNUSED in {rec.record_id}", True

            return True, None, None, has_used_ancestor

        valid_usage_ids: Set[str] = set()
        superseded_usage_ids: Set[str] = set()
        levels_with_terminal_used: Set[StableLevelId] = set()
        authoritative_used_by_level: Dict[StableLevelId, ProposedUsageEvidenceRecord] = {}

        for rid in sorted(coalesced_usage.keys()):
            u = coalesced_usage[rid]
            is_valid, reason, msg, has_used = validate_usage_chain(u)
            if has_used and is_valid:
                levels_with_terminal_used.add(u.level_id)
                if u.status == UsageEvidenceStatus.USED:
                    authoritative_used_by_level[u.level_id] = u

            if is_valid:
                valid_usage_ids.add(rid)
            else:
                if reason == AuthorityDiagnosticReason.AMBIGUOUS_FORK:
                    levels_with_ambiguous_fork.add(u.level_id)
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=reason or AuthorityDiagnosticReason.INVALID_ANCESTOR,
                        message=msg or f"Invalid ancestor chain for usage {rid}",
                    )
                )

        for rid in sorted(valid_usage_ids):
            u = coalesced_usage[rid]
            curr_pred_id = u.predecessor_record_id
            while curr_pred_id and curr_pred_id in valid_usage_ids:
                superseded_usage_ids.add(curr_pred_id)
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=curr_pred_id,
                        diagnostic_reason=AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION,
                        message=f"Usage predecessor {curr_pred_id} superseded by validated successor {rid}",
                    )
                )
                curr_pred_id = coalesced_usage[curr_pred_id].predecessor_record_id

        active_usage_by_level: Dict[StableLevelId, List[ProposedUsageEvidenceRecord]] = {}
        for rid in sorted(valid_usage_ids):
            if rid not in superseded_usage_ids:
                u = coalesced_usage[rid]
                active_usage_by_level.setdefault(u.level_id, []).append(u)

        resolved_usage: Dict[StableLevelId, UsageEvidenceStatus] = {}
        authoritative_usage_map: Dict[StableLevelId, ProposedUsageEvidenceRecord] = {}

        all_target_levels = sorted(
            list(
                set(physical_levels)
                | set(active_usage_by_level.keys())
                | levels_with_terminal_used
                | levels_with_ambiguous_fork
            ),
            key=lambda l: (
                l.symbol_feed_id,
                l.source_timeframe,
                l.source_open_time.isoformat(),
                str(l.side),
            ),
        )

        for lvl in all_target_levels:
            active_for_lvl = active_usage_by_level.get(lvl, [])

            # 1. Contradictory unlinked assertions among active records -> UNKNOWN
            if active_for_lvl:
                statuses = {r.status for r in active_for_lvl}
                if len(statuses) > 1:
                    resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                    canonical_statuses = sorted(str(s.value) for s in statuses)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=str(lvl),
                            diagnostic_reason=AuthorityDiagnosticReason.CONTRADICTORY_ASSERTION,
                            message=f"Contradictory unlinked usage assertions for level {lvl}: {canonical_statuses}",
                        )
                    )
                    continue

            # 2. Finding 1: An unresolved contradictory fork must produce UNKNOWN and block candidates
            # Predecessor A cannot resolve to UNUSED if its successor branches forked!
            if lvl in levels_with_ambiguous_fork:
                if lvl in levels_with_terminal_used and any(r.status == UsageEvidenceStatus.USED for r in active_for_lvl):
                    resolved_usage[lvl] = UsageEvidenceStatus.USED
                    if lvl in authoritative_used_by_level:
                        authoritative_usage_map[lvl] = authoritative_used_by_level[lvl]
                    continue

                resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=str(lvl),
                        diagnostic_reason=AuthorityDiagnosticReason.AMBIGUOUS_FORK,
                        message=f"Level {lvl} has unresolved ambiguous usage fork; fails closed as UNKNOWN",
                    )
                )
                continue

            # 3. Multi-hop terminal USED fact: If level was ever USED without unresolved contradiction, status is permanently USED
            if lvl in levels_with_terminal_used:
                resolved_usage[lvl] = UsageEvidenceStatus.USED
                if lvl in authoritative_used_by_level:
                    authoritative_usage_map[lvl] = authoritative_used_by_level[lvl]
                continue

            # 4. No valid record exists -> UNKNOWN (strictly no negative proof)
            if not active_for_lvl:
                resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                continue

            # 5. Single active status
            final_st = list(statuses)[0]
            resolved_usage[lvl] = final_st
            active_for_lvl.sort(
                key=lambda r: (r.established_time.isoformat(), r.available_time.isoformat(), r.record_id),
                reverse=True,
            )
            authoritative_usage_map[lvl] = active_for_lvl[0]

        diagnostics.sort(key=lambda d: (d.entity_key, d.diagnostic_reason.value, d.message))
        return resolved_usage, authoritative_usage_map, tuple(diagnostics)
