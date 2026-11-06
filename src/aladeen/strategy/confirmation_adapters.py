"""Adapters translating authoritative CHOCH and ISS engine outputs into immutable ConfirmationEvidenceRecords.

Scope & Design Boundary:
-------------------------
- Pure adapter layer between existing accepted detector engines (CHOCH, ISS) and the confirmation monitor.
- Preserves continuous detection: does not alter engine history, reset start candles, or mutate snapshots.
- Explicit observational field mapping:
  * Direction is explicitly mapped from detector structural domain rules (e.g. Bullish CHOCH -> UPWARD,
    Bearish Main ISS -> UPWARD internal shift). Direction is NEVER inferred from producer names or IDs.
  * Structural dependency references are captured as explicit, auditable provenance references without placeholders.
- Authoritative candle-stream and configuration validation:
  * For completed detector evidence, validating candle identity, index, open_time, close_time, duration,
    and exact completion close price against authoritative candle stream for both CHOCH and ISS.
  * Preserves unknown completion time as close_timestamp=None and is_completed=False without substitutions.
  * Zero wall-clock dependence: zero datetime.now() calls.
- Strictly read-only calculation logic. Zero order execution, zero network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, List, Optional, Sequence, Tuple

from .activation_types import PriceBasis, SequenceDomain
from .choch_types import ChochType, ConfirmedChoch
from .confirmation_types import ConfirmationEvidenceRecord, EvidenceProvenanceType
from .iss_types import ConfirmedISSEvent
from .types import Direction, StrategyCandle, validate_and_normalize_timestamp

TIMEFRAME_DURATION_MAP = {
    "H1": timedelta(hours=1),
    "M5": timedelta(minutes=5),
    "M1": timedelta(minutes=1),
}


@dataclass(frozen=True)
class ValidatedCandleStreamEnvelope:
    """Explicit immutable validated candle-stream and configuration binding."""
    candle: StrategyCandle
    symbol: str
    feed_id: str
    timeframe: str
    price_basis: PriceBasis
    confirmation_config_id: str
    confirmation_candle_id: str
    sequence_domain: Optional[SequenceDomain] = None

    def __post_init__(self) -> None:
        if not isinstance(self.candle, StrategyCandle):
            raise TypeError("candle must be StrategyCandle instance")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty string")
        if not isinstance(self.feed_id, str) or not self.feed_id.strip():
            raise ValueError("feed_id must be non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise ValueError("timeframe must be non-empty string")
        if not isinstance(self.price_basis, PriceBasis):
            raise TypeError("price_basis must be PriceBasis enum")
        if not isinstance(self.confirmation_config_id, str) or not self.confirmation_config_id.strip():
            raise ValueError("confirmation_config_id must be non-empty string")
        if not isinstance(self.confirmation_candle_id, str) or not self.confirmation_candle_id.strip():
            raise ValueError("confirmation_candle_id must be non-empty string")
        if self.sequence_domain is not None and not isinstance(self.sequence_domain, SequenceDomain):
            raise TypeError("sequence_domain must be SequenceDomain instance if provided")


def adapt_confirmed_choch_to_evidence(
    choch: ConfirmedChoch,
    confirmation_config_id: str,
    confirmation_timeframe: str,
    confirmation_candle_id: str,
    symbol: str,
    feed_id: str,
    sequence_domain: SequenceDomain,
    close_price: Optional[float] = None,
    price_basis: PriceBasis = PriceBasis.BID,
    confirming_candle: Optional[StrategyCandle] = None,
    envelope: Optional[ValidatedCandleStreamEnvelope] = None,
    sequence_ref: Optional[int] = None,
    is_isolated_tracking: bool = False,
    has_unresolved_dependencies: bool = False,
    activation_id: Optional[str] = None,
    source_member_key: Optional[str] = None,
    provenance_type: EvidenceProvenanceType = EvidenceProvenanceType.DETECTOR_CONFIRMED,
) -> ConfirmationEvidenceRecord:
    """Adapts an authoritative ConfirmedChoch event into an immutable ConfirmationEvidenceRecord.

    Direction Mapping Contract:
    - ChochType.BULLISH_CHOCH -> Direction.UPWARD (Intended for BUY trade side)
    - ChochType.BEARISH_CHOCH -> Direction.DOWNWARD (Intended for SELL trade side)

    Authoritative Candle & Structural Provenance:
    - Validates required structural dependencies (event_id, broken_level, point_3, c1/c2 indices).
    - Requires authoritative confirming_candle for completed detector-confirmed evidence.
    - Validates candle index, c2 open time, confirmation close time, and timeframe duration.
    - Rejects conflicting caller close prices or envelope contradictions fail-closed.
    """
    if choch.choch_type == ChochType.BULLISH_CHOCH:
        mapped_direction = Direction.UPWARD
    elif choch.choch_type == ChochType.BEARISH_CHOCH:
        mapped_direction = Direction.DOWNWARD
    else:
        raise ValueError(f"Unknown ChochType: {choch.choch_type!r}")

    # Validate required structural dependencies
    if not choch.event_id or not isinstance(choch.event_id, str):
        raise ValueError("ConfirmedChoch missing valid event_id")
    if not choch.broken_level_type or choch.broken_level_price is None or choch.broken_level_price <= 0:
        raise ValueError("ConfirmedChoch missing valid broken_level structural dependency")
    if choch.point_3_source_index is None or choch.point_3_source_index < 0 or choch.point_3_open_time is None:
        raise ValueError("ConfirmedChoch missing valid point_3 structural dependency")
    if choch.c1_candle_index is None or choch.c1_candle_index < 0 or choch.c2_candle_index is None or choch.c2_candle_index < 0:
        raise ValueError("ConfirmedChoch missing valid c1/c2 candle indices")

    # For DETECTOR_CONFIRMED adaptation, ValidatedCandleStreamEnvelope is strictly mandatory
    if provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED:
        if envelope is None:
            raise ValueError(
                "DETECTOR_CONFIRMED adaptation strictly requires mandatory ValidatedCandleStreamEnvelope; raw confirming_candle cannot bypass envelope"
            )
        if envelope.sequence_domain is None:
            raise ValueError(
                "DETECTOR_CONFIRMED adaptation strictly requires sequence_domain binding in envelope"
            )
        if envelope.sequence_domain != sequence_domain:
            raise ValueError(
                f"Envelope sequence_domain ({envelope.sequence_domain}) contradicts parameter ({sequence_domain})"
            )
        if confirming_candle is not None and confirming_candle != envelope.candle:
            raise ValueError("confirming_candle contradicts envelope candle")
        confirming_candle = envelope.candle
    elif envelope is not None:
        if envelope.sequence_domain is not None and envelope.sequence_domain != sequence_domain:
            raise ValueError(
                f"Envelope sequence_domain ({envelope.sequence_domain}) contradicts parameter ({sequence_domain})"
            )
        confirming_candle = envelope.candle

    # If stream envelope is provided, validate explicit authority binding
    if envelope is not None:
        if envelope.symbol != symbol:
            raise ValueError(f"Envelope symbol ({envelope.symbol}) contradicts parameter symbol ({symbol})")
        if envelope.feed_id != feed_id:
            raise ValueError(f"Envelope feed_id ({envelope.feed_id}) contradicts parameter feed_id ({feed_id})")
        if envelope.timeframe != confirmation_timeframe:
            raise ValueError(f"Envelope timeframe ({envelope.timeframe}) contradicts parameter timeframe ({confirmation_timeframe})")
        if envelope.price_basis != price_basis:
            raise ValueError(f"Envelope price_basis ({envelope.price_basis.value}) contradicts parameter basis ({price_basis.value})")
        if envelope.confirmation_config_id != confirmation_config_id:
            raise ValueError(f"Envelope config ({envelope.confirmation_config_id}) contradicts parameter config ({confirmation_config_id})")
        if envelope.confirmation_candle_id != confirmation_candle_id:
            raise ValueError(f"Envelope candle ID ({envelope.confirmation_candle_id}) contradicts parameter candle ID ({confirmation_candle_id})")
        confirming_candle = envelope.candle

    expected_dur = TIMEFRAME_DURATION_MAP.get(confirmation_timeframe)
    if expected_dur is None:
        raise ValueError(
            f"Unsupported confirmation_timeframe {confirmation_timeframe!r}. Supported timeframes: {sorted(TIMEFRAME_DURATION_MAP.keys())}"
        )

    is_completed = True
    close_time = choch.confirmation_time

    if confirming_candle is not None:
        if confirming_candle.index != choch.c2_candle_index:
            raise ValueError(
                f"Confirming candle index {confirming_candle.index} does not match CHOCH c2_candle_index {choch.c2_candle_index}"
            )
        if choch.c2_open_time is not None and confirming_candle.open_time != choch.c2_open_time:
            raise ValueError(
                f"Confirming candle open_time {confirming_candle.open_time} does not match CHOCH c2_open_time {choch.c2_open_time}"
            )

        c_close = getattr(confirming_candle, "close_time", None)
        c_open = confirming_candle.open_time

        if provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED:
            if c_open is None:
                raise ValueError("Confirming candle open_time cannot be None for detector-confirmed evidence")
            if c_close is None:
                raise ValueError("Confirming candle close_time cannot be None for completed detector-confirmed evidence")
            if choch.confirmation_time is None:
                raise ValueError("ConfirmedChoch confirmation_time cannot be None for completed detector-confirmed evidence")
            if choch.confirmation_time != c_close:
                raise ValueError(
                    f"Event confirmation_time {choch.confirmation_time} does not match candle close_time {c_close}"
                )
            if (c_close - c_open) != expected_dur:
                raise ValueError(
                    f"Candle interval duration {c_close - c_open} contradicts declared confirmation_timeframe {confirmation_timeframe} ({expected_dur})"
                )
            if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
                is_completed = False
        else:
            if choch.confirmation_time is not None and c_close is not None and choch.confirmation_time != c_close:
                raise ValueError(
                    f"Event confirmation_time {choch.confirmation_time} does not match candle close_time {c_close}"
                )
            if c_open is not None and c_close is not None and (c_close - c_open) != expected_dur:
                raise ValueError(
                    f"Candle interval duration {c_close - c_open} contradicts declared confirmation_timeframe {confirmation_timeframe}"
                )
            if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
                is_completed = False

        eff_close_price = confirming_candle.close
        if close_price is not None and close_price != eff_close_price:
            raise ValueError(
                f"Supplied close_price ({close_price}) conflicts with candle close price ({eff_close_price})"
            )

        if close_time is None and not confirming_candle.is_forming and c_close is not None:
            close_time = c_close
    else:
        # If no confirming candle is provided for detector evidence claiming completion
        if provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED and close_time is not None:
            raise ValueError("Completed detector confirmation requires authoritative confirming_candle")
        if close_price is None:
            raise ValueError("Must provide either confirming_candle or close_price")
        eff_close_price = close_price

    if close_time is None:
        # Unknown completion time: preserve as None and incomplete without open-time substitution
        is_completed = False

    # Capture explicit, genuine structural provenance references
    structural_refs: List[str] = [
        f"CHOCH_TYPE:{choch.choch_type.value}",
        f"BROKEN_LEVEL:{choch.broken_level_type}:{choch.broken_level_price}",
        f"POINT_3_INDEX:{choch.point_3_source_index}",
        f"C1_INDEX:{choch.c1_candle_index}",
        f"C2_INDEX:{choch.c2_candle_index}",
    ]
    for z in choch.zones:
        structural_refs.append(f"ZONE:{z.zone_type.value}:{z.lower_price}-{z.upper_price}")

    return ConfirmationEvidenceRecord(
        event_id=choch.event_id,
        producer_id="CHOCH_DETECTOR_v1",
        pattern_type="CHOCH",
        confirmation_config_id=confirmation_config_id,
        confirmation_timeframe=confirmation_timeframe,
        confirmation_candle_id=confirmation_candle_id,
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        close_timestamp=close_time,
        close_price=eff_close_price,
        price_basis=price_basis,
        direction=mapped_direction,
        price_provenance="CONFIRMATION_CANDLE_CLOSE",
        provenance_type=provenance_type,
        is_completed=is_completed,
        has_unresolved_dependencies=has_unresolved_dependencies,
        structural_dependency_references=tuple(structural_refs),
        sequence_ref=sequence_ref,
        is_isolated_tracking=is_isolated_tracking,
        activation_id=activation_id,
        source_member_key=source_member_key,
    )


def adapt_confirmed_iss_to_evidence(
    iss: ConfirmedISSEvent,
    confirmation_config_id: str,
    confirmation_timeframe: str,
    confirmation_candle_id: str,
    symbol: str,
    feed_id: str,
    sequence_domain: SequenceDomain,
    close_price: Optional[float] = None,
    price_basis: PriceBasis = PriceBasis.BID,
    confirming_candle: Optional[StrategyCandle] = None,
    envelope: Optional[ValidatedCandleStreamEnvelope] = None,
    sequence_ref: Optional[int] = None,
    is_isolated_tracking: bool = False,
    has_unresolved_dependencies: bool = False,
    activation_id: Optional[str] = None,
    source_member_key: Optional[str] = None,
    provenance_type: EvidenceProvenanceType = EvidenceProvenanceType.DETECTOR_CONFIRMED,
) -> ConfirmationEvidenceRecord:
    """Adapts an authoritative ConfirmedISSEvent into an immutable ConfirmationEvidenceRecord.

    Direction Mapping Contract:
    - Bearish Main Structure (Direction.DOWNWARD) -> Direction.UPWARD (Bullish ISS for BUY trade side).
    - Bullish Main Structure (Direction.UPWARD) -> Direction.DOWNWARD (Bearish ISS for SELL trade side).

    Authoritative Candle & Structural Provenance:
    - Validates required structural dependencies (candidate_id, points, boundary, zones).
    - Requires authoritative confirming_candle for completed detector-confirmed evidence (same standard as CHOCH).
    - Rejects disagreement between candle close and iss.completion_close_price fail-closed.
    - Validates confirmation time, candle index, and timeframe duration.
    """
    if iss.main_direction == Direction.DOWNWARD:
        mapped_direction = Direction.UPWARD
    elif iss.main_direction == Direction.UPWARD:
        mapped_direction = Direction.DOWNWARD
    else:
        raise ValueError(f"Unknown ISS main_direction: {iss.main_direction!r}")

    # Validate required structural dependencies
    if not iss.candidate_id or not isinstance(iss.candidate_id, str):
        raise ValueError("ConfirmedISSEvent missing valid candidate_id")
    if iss.confirmation_candle_index is None or iss.confirmation_candle_index < 0:
        raise ValueError("ConfirmedISSEvent missing valid confirmation_candle_index")
    if iss.completion_close_price is None or iss.completion_close_price <= 0:
        raise ValueError("ConfirmedISSEvent missing valid completion_close_price")
    if iss.captured_boundary is None or iss.captured_boundary.min_price >= iss.captured_boundary.max_price:
        raise ValueError("ConfirmedISSEvent missing valid captured_boundary")
    if not iss.internal_points or len(iss.internal_points) != 5:
        raise ValueError("ConfirmedISSEvent missing valid 5 internal_points structural dependencies")

    # For DETECTOR_CONFIRMED adaptation, ValidatedCandleStreamEnvelope is strictly mandatory
    if provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED:
        if envelope is None:
            raise ValueError(
                "DETECTOR_CONFIRMED adaptation strictly requires mandatory ValidatedCandleStreamEnvelope; raw confirming_candle cannot bypass envelope"
            )
        if envelope.sequence_domain is None:
            raise ValueError(
                "DETECTOR_CONFIRMED adaptation strictly requires sequence_domain binding in envelope"
            )
        if envelope.sequence_domain != sequence_domain:
            raise ValueError(
                f"Envelope sequence_domain ({envelope.sequence_domain}) contradicts parameter ({sequence_domain})"
            )
        if confirming_candle is not None and confirming_candle != envelope.candle:
            raise ValueError("confirming_candle contradicts envelope candle")
        confirming_candle = envelope.candle
    elif envelope is not None:
        if envelope.sequence_domain is not None and envelope.sequence_domain != sequence_domain:
            raise ValueError(
                f"Envelope sequence_domain ({envelope.sequence_domain}) contradicts parameter ({sequence_domain})"
            )
        confirming_candle = envelope.candle

    # If stream envelope is provided, validate explicit authority binding
    if envelope is not None:
        if envelope.symbol != symbol:
            raise ValueError(f"Envelope symbol ({envelope.symbol}) contradicts parameter symbol ({symbol})")
        if envelope.feed_id != feed_id:
            raise ValueError(f"Envelope feed_id ({envelope.feed_id}) contradicts parameter feed_id ({feed_id})")
        if envelope.timeframe != confirmation_timeframe:
            raise ValueError(f"Envelope timeframe ({envelope.timeframe}) contradicts parameter timeframe ({confirmation_timeframe})")
        if envelope.price_basis != price_basis:
            raise ValueError(f"Envelope price_basis ({envelope.price_basis.value}) contradicts parameter basis ({price_basis.value})")
        if envelope.confirmation_config_id != confirmation_config_id:
            raise ValueError(f"Envelope config ({envelope.confirmation_config_id}) contradicts parameter config ({confirmation_config_id})")
        if envelope.confirmation_candle_id != confirmation_candle_id:
            raise ValueError(f"Envelope candle ID ({envelope.confirmation_candle_id}) contradicts parameter candle ID ({confirmation_candle_id})")
        confirming_candle = envelope.candle

    expected_dur = TIMEFRAME_DURATION_MAP.get(confirmation_timeframe)
    if expected_dur is None:
        raise ValueError(
            f"Unsupported confirmation_timeframe {confirmation_timeframe!r}. Supported timeframes: {sorted(TIMEFRAME_DURATION_MAP.keys())}"
        )

    is_completed = True
    close_time = iss.confirmation_time

    if confirming_candle is not None:
        if confirming_candle.index != iss.confirmation_candle_index:
            raise ValueError(
                f"Confirming candle index {confirming_candle.index} does not match ISS confirmation index {iss.confirmation_candle_index}"
            )

        c_close = getattr(confirming_candle, "close_time", None)
        c_open = confirming_candle.open_time

        if provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED:
            if c_open is None:
                raise ValueError("Confirming candle open_time cannot be None for detector-confirmed evidence")
            if c_close is None:
                raise ValueError("Confirming candle close_time cannot be None for completed detector-confirmed evidence")
            if iss.confirmation_time is None:
                raise ValueError("ConfirmedISSEvent confirmation_time cannot be None for completed detector-confirmed evidence")
            if iss.confirmation_time != c_close:
                raise ValueError(
                    f"ISS confirmation_time {iss.confirmation_time} does not match candle close_time {c_close}"
                )
            if (c_close - c_open) != expected_dur:
                raise ValueError(
                    f"Candle interval duration {c_close - c_open} contradicts declared confirmation_timeframe {confirmation_timeframe} ({expected_dur})"
                )
            if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
                is_completed = False
        else:
            if iss.confirmation_time is not None and c_close is not None and iss.confirmation_time != c_close:
                raise ValueError(
                    f"ISS confirmation_time {iss.confirmation_time} does not match candle close_time {c_close}"
                )
            if c_open is not None and c_close is not None and (c_close - c_open) != expected_dur:
                raise ValueError(
                    f"Candle interval duration {c_close - c_open} contradicts declared confirmation_timeframe {confirmation_timeframe}"
                )
            if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
                is_completed = False

        if confirming_candle.close != iss.completion_close_price:
            raise ValueError(
                f"Confirming candle close ({confirming_candle.close}) contradicts ISS completion_close_price ({iss.completion_close_price})"
            )

        if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
            is_completed = False

        eff_close_price = confirming_candle.close
        if close_time is None and not confirming_candle.is_forming and c_close is not None:
            close_time = c_close
    else:
        # ISS completed detector evidence strictly requires an authoritative confirming candle
        if provenance_type == EvidenceProvenanceType.DETECTOR_CONFIRMED and close_time is not None:
            raise ValueError("Completed detector confirmation requires authoritative confirming_candle")
        eff_close_price = iss.completion_close_price

    if close_price is not None and close_price != eff_close_price:
        raise ValueError(
            f"Supplied close_price ({close_price}) conflicts with verified ISS completion price ({eff_close_price})"
        )

    if close_time is None:
        is_completed = False

    structural_refs: List[str] = [
        f"ISS_CANDIDATE:{iss.candidate_id}",
        f"MAIN_DIRECTION:{iss.main_direction.value}",
        f"CONFIRMATION_BAR_INDEX:{iss.confirmation_candle_index}",
        f"BOUNDARY:[{iss.captured_boundary.min_price},{iss.captured_boundary.max_price}]",
    ]
    for pt in iss.internal_points:
        structural_refs.append(f"POINT_{pt.point_number}:{pt.role}:{pt.body_edge_price}")
    structural_refs.append(f"ZONE_L3:{iss.level_3_zone.zone_type.value}:{iss.level_3_zone.lower_price}-{iss.level_3_zone.upper_price}")
    structural_refs.append(f"ZONE_L4:{iss.level_4_zone.zone_type.value}:{iss.level_4_zone.lower_price}-{iss.level_4_zone.upper_price}")

    return ConfirmationEvidenceRecord(
        event_id=iss.candidate_id,
        producer_id="ISS_ENGINE_v1",
        pattern_type="ISS",
        confirmation_config_id=confirmation_config_id,
        confirmation_timeframe=confirmation_timeframe,
        confirmation_candle_id=confirmation_candle_id,
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        close_timestamp=close_time,
        close_price=eff_close_price,
        price_basis=price_basis,
        direction=mapped_direction,
        price_provenance="CONFIRMATION_CANDLE_CLOSE",
        provenance_type=provenance_type,
        is_completed=is_completed,
        has_unresolved_dependencies=has_unresolved_dependencies,
        structural_dependency_references=tuple(structural_refs),
        sequence_ref=sequence_ref,
        is_isolated_tracking=is_isolated_tracking,
        activation_id=activation_id,
        source_member_key=source_member_key,
    )
