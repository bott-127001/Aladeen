"""Authoritative Confirmation Matcher and Evaluation Facade.

Scope & Design Boundary:
-------------------------
- Pure mathematical, typing, and domain matching between activations and confirmation evidence.
- Independent of MT5, Dash, Plotly, network, broker connection, and persistent storage.
- Delegates pair evaluation to ConfirmationPairMatcher and batch consolidation to ConfirmationBatchConsolidator.
- Explicit diagnostic results for all rejected, blocked, or uncertain associations.
- Strict authoritative gating: missing authority or unresolved source dependencies fail closed locally.
- Strict causal ordering: cross-domain bare integers are rejected; evaluation availability enforced.
- Batch consolidation validates conflicts using complete evidence equality, deduplicates
  identical evidence, and produces unique candidates with deterministic output sorting
  invariant to input permutations.
- Zero wall-clock dependence: evaluation time is an explicit required parameter.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .activation_types import ActivationRecord
from .confirmation_batch_consolidator import ConfirmationBatchConsolidator
from .confirmation_pair_matcher import (
    ConfirmationPairMatcher,
    MatchingContext,
    ROLE_RANK_MAP,
    TIMEFRAME_RANK_MAP,
)
from .confirmation_types import (
    BatchMatchResult,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
)

__all__ = [
    "MatchingContext",
    "ConfirmationMatcher",
    "ConfirmationPairMatcher",
    "ConfirmationBatchConsolidator",
    "TIMEFRAME_RANK_MAP",
    "ROLE_RANK_MAP",
]


class ConfirmationMatcher:
    """Authoritative Confirmation Matcher facade combining pair matching and batch consolidation."""

    def __init__(
        self,
        pair_matcher: Optional[ConfirmationPairMatcher] = None,
        batch_consolidator: Optional[ConfirmationBatchConsolidator] = None,
    ) -> None:
        self._pair_matcher = pair_matcher or ConfirmationPairMatcher()
        self._batch_consolidator = batch_consolidator or ConfirmationBatchConsolidator(self._pair_matcher)

    def match(
        self,
        activation: ActivationRecord,
        evidence: ConfirmationEvidenceRecord,
        context: MatchingContext,
    ) -> ConfirmationMatchResult:
        """Evaluates whether a single confirmation evidence record associates with an activation."""
        return self._pair_matcher.match(activation, evidence, context)

    def match_batch(
        self,
        activations: Sequence[ActivationRecord],
        evidences: Sequence[ConfirmationEvidenceRecord],
        context: MatchingContext,
    ) -> BatchMatchResult:
        """Evaluates associations across activations and confirmation evidences with batch consolidation."""
        return self._batch_consolidator.match_batch(activations, evidences, context)
