"""Adapters translating authoritative CHOCH and ISS engine outputs into immutable ConfirmationEvidenceRecords.

Scope & Design Boundary:
-------------------------
- Pure adapter layer between existing accepted detector engines (CHOCH, ISS) and the confirmation monitor.
- Preserves continuous detection: does not alter engine history, reset start candles, or mutate snapshots.
- Explicit observational field mapping:
  * Direction is explicitly mapped from detector structural domain rules (e.g. Bullish CHOCH -> UPWARD,
    Bearish Main ISS -> UPWARD internal shift). Direction is NEVER inferred from producer names or IDs.
  * Structural dependency references are captured as explicit, auditable provenance references.
- Strictly read-only calculation logic. Zero order execution, zero network access.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

from .activation_types import PriceBasis, SequenceDomain
from .choch_types import ChochType, ConfirmedChoch
from .confirmation_types import ConfirmationEvidenceRecord
from .iss_types import ConfirmedISSEvent
from .types import Direction, validate_and_normalize_timestamp


def adapt_confirmed_choch_to_evidence(
    choch: ConfirmedChoch,
    confirmation_config_id: str,
    confirmation_timeframe: str,
    confirmation_candle_id: str,
    close_price: float,
    price_basis: PriceBasis = PriceBasis.BID,
    symbol: Optional[str] = None,
    feed_id: Optional[str] = None,
    sequence_domain: Optional[SequenceDomain] = None,
    sequence_ref: Optional[int] = None,
    is_isolated_tracking: bool = False,
    has_unresolved_dependencies: bool = False,
    activation_id: Optional[str] = None,
    source_member_key: Optional[str] = None,
) -> ConfirmationEvidenceRecord:
    """Adapts an authoritative ConfirmedChoch event into an immutable ConfirmationEvidenceRecord.

    Direction Mapping Contract:
    - ChochType.BULLISH_CHOCH -> Direction.UPWARD (Intended for BUY trade side)
    - ChochType.BEARISH_CHOCH -> Direction.DOWNWARD (Intended for SELL trade side)
    """
    if choch.choch_type == ChochType.BULLISH_CHOCH:
        mapped_direction = Direction.UPWARD
    elif choch.choch_type == ChochType.BEARISH_CHOCH:
        mapped_direction = Direction.DOWNWARD
    else:
        raise ValueError(f"Unknown ChochType: {choch.choch_type!r}")

    close_time = choch.confirmation_time
    if close_time is None:
        close_time = choch.c2_open_time

    # Capture explicit structural provenance references
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
        close_timestamp=close_time,
        close_price=close_price,
        price_basis=price_basis,
        direction=mapped_direction,
        price_provenance="CONFIRMATION_CANDLE_CLOSE",
        is_completed=True,
        has_unresolved_dependencies=has_unresolved_dependencies,
        structural_dependency_references=tuple(structural_refs),
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
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
    close_price: Optional[float] = None,
    price_basis: PriceBasis = PriceBasis.BID,
    symbol: Optional[str] = None,
    feed_id: Optional[str] = None,
    sequence_domain: Optional[SequenceDomain] = None,
    sequence_ref: Optional[int] = None,
    is_isolated_tracking: bool = False,
    has_unresolved_dependencies: bool = False,
    activation_id: Optional[str] = None,
    source_member_key: Optional[str] = None,
) -> ConfirmationEvidenceRecord:
    """Adapts an authoritative ConfirmedISSEvent into an immutable ConfirmationEvidenceRecord.

    Direction Mapping Contract (docs/requirements/iss-acceptance.md §3):
    Internal marking runs in the opposite direction of prevailing main marking:
    - Bearish Main Structure (Direction.DOWNWARD) -> Internal UPWARD marking (CL1, CH1, CL2, CH2, Tentative High)
      -> Direction.UPWARD (Bullish ISS, intended for BUY trade side).
    - Bullish Main Structure (Direction.UPWARD) -> Internal DOWNWARD marking (CH1, CL1, CH2, CL2, Tentative Low)
      -> Direction.DOWNWARD (Bearish ISS, intended for SELL trade side).
    """
    if iss.main_direction == Direction.DOWNWARD:
        mapped_direction = Direction.UPWARD
    elif iss.main_direction == Direction.UPWARD:
        mapped_direction = Direction.DOWNWARD
    else:
        raise ValueError(f"Unknown ISS main_direction: {iss.main_direction!r}")

    eff_close_price = close_price if close_price is not None else iss.completion_close_price

    close_time = iss.confirmation_time
    if close_time is None:
        raise ValueError("ConfirmedISSEvent must have confirmation_time to adapt to ConfirmationEvidenceRecord")

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
        close_timestamp=close_time,
        close_price=eff_close_price,
        price_basis=price_basis,
        direction=mapped_direction,
        price_provenance="CONFIRMATION_CANDLE_CLOSE",
        is_completed=True,
        has_unresolved_dependencies=has_unresolved_dependencies,
        structural_dependency_references=tuple(structural_refs),
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        sequence_ref=sequence_ref,
        is_isolated_tracking=is_isolated_tracking,
        activation_id=activation_id,
        source_member_key=source_member_key,
    )
