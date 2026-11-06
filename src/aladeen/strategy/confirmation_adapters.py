"""Adapters translating authoritative CHOCH and ISS engine outputs into immutable ConfirmationEvidenceRecords.

Scope & Design Boundary:
-------------------------
- Pure adapter layer between existing accepted detector engines (CHOCH, ISS) and the confirmation monitor.
- Preserves continuous detection: does not alter engine history, reset start candles, or mutate snapshots.
- Explicit observational field mapping:
  * Direction is explicitly mapped from detector structural domain rules (e.g. Bullish CHOCH -> UPWARD,
    Bearish Main ISS -> UPWARD internal shift). Direction is NEVER inferred from producer names or IDs.
  * Structural dependency references are captured as explicit, auditable provenance references.
- Provenance integrity:
  * Completion requires authoritative candle-close confirmation time. Unknown completion time preserves
    close_timestamp=None and is_completed=False without candle-open or Unix epoch substitution.
  * Close price provenance is anchored strictly to candle-close prints without unverified overrides.
  * Timeframe consistency: validates that confirming candle intervals match declared confirmation timeframes
    (no relabeling of hourly candles as M5).
  * Zero wall-clock dependence: zero datetime.now() calls.
- Strictly read-only calculation logic. Zero order execution, zero network access.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List, Optional, Sequence, Tuple

from .activation_types import PriceBasis, SequenceDomain
from .choch_types import ChochType, ConfirmedChoch
from .confirmation_types import ConfirmationEvidenceRecord
from .iss_types import ConfirmedISSEvent
from .types import Direction, StrategyCandle, validate_and_normalize_timestamp

TIMEFRAME_DURATION_MAP = {
    "H1": timedelta(hours=1),
    "M5": timedelta(minutes=5),
    "M1": timedelta(minutes=1),
}


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

    Completion Provenance:
    - If confirmation_time is missing and no completed confirming_candle is provided,
      close_timestamp is None and is_completed is marked False (zero candle-open substitution).
    - If confirming_candle is provided, validates that candle index matches c2_candle_index,
      that the candle is completed, that its duration matches confirmation_timeframe, and
      anchors close_price directly to candle close.
    """
    if choch.choch_type == ChochType.BULLISH_CHOCH:
        mapped_direction = Direction.UPWARD
    elif choch.choch_type == ChochType.BEARISH_CHOCH:
        mapped_direction = Direction.DOWNWARD
    else:
        raise ValueError(f"Unknown ChochType: {choch.choch_type!r}")

    is_completed = True
    close_time = choch.confirmation_time

    if confirming_candle is not None:
        if confirming_candle.index != choch.c2_candle_index:
            raise ValueError(
                f"Confirming candle index {confirming_candle.index} does not match CHOCH c2_candle_index {choch.c2_candle_index}"
            )
        if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
            is_completed = False

        # Validate timeframe duration integrity (no relabeling of H1 as M5)
        c_open = confirming_candle.open_time
        c_close = getattr(confirming_candle, "close_time", None)
        if c_open is not None and c_close is not None:
            expected_dur = TIMEFRAME_DURATION_MAP.get(confirmation_timeframe)
            if expected_dur is not None and (c_close - c_open) != expected_dur:
                raise ValueError(
                    f"Candle interval duration {c_close - c_open} contradicts declared confirmation_timeframe {confirmation_timeframe}"
                )

        eff_close_price = confirming_candle.close
        if close_time is None and not confirming_candle.is_forming and c_close is not None:
            close_time = c_close
    else:
        if close_price is None:
            raise ValueError("Must provide either confirming_candle or close_price")
        eff_close_price = close_price

    if close_time is None:
        # Unknown completion time: preserve as None and incomplete without open-time substitution
        is_completed = False

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
        symbol=symbol,
        feed_id=feed_id,
        sequence_domain=sequence_domain,
        close_timestamp=close_time,
        close_price=eff_close_price,
        price_basis=price_basis,
        direction=mapped_direction,
        price_provenance="CONFIRMATION_CANDLE_CLOSE",
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

    Completion Provenance:
    - Anchors close price strictly to iss.completion_close_price or confirming_candle.close.
    - If caller-supplied close_price conflicts with verified candle completion price, raises ValueError.
    - Unknown completion time preserves close_timestamp=None without Unix epoch sentinel substitution.
    """
    if iss.main_direction == Direction.DOWNWARD:
        mapped_direction = Direction.UPWARD
    elif iss.main_direction == Direction.UPWARD:
        mapped_direction = Direction.DOWNWARD
    else:
        raise ValueError(f"Unknown ISS main_direction: {iss.main_direction!r}")

    is_completed = True
    close_time = iss.confirmation_time

    if confirming_candle is not None:
        if confirming_candle.index != iss.confirmation_candle_index:
            raise ValueError(
                f"Confirming candle index {confirming_candle.index} does not match ISS confirmation index {iss.confirmation_candle_index}"
            )
        if confirming_candle.is_forming or confirming_candle.bar_status != "CONFIRMED_COMPLETED":
            is_completed = False

        # Validate timeframe duration integrity (no relabeling of H1 as M5)
        c_open = confirming_candle.open_time
        c_close = getattr(confirming_candle, "close_time", None)
        if c_open is not None and c_close is not None:
            expected_dur = TIMEFRAME_DURATION_MAP.get(confirmation_timeframe)
            if expected_dur is not None and (c_close - c_open) != expected_dur:
                raise ValueError(
                    f"Candle interval duration {c_close - c_open} contradicts declared confirmation_timeframe {confirmation_timeframe}"
                )

        eff_close_price = confirming_candle.close
        if close_time is None and not confirming_candle.is_forming and c_close is not None:
            close_time = c_close
    else:
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
        is_completed=is_completed,
        has_unresolved_dependencies=has_unresolved_dependencies,
        structural_dependency_references=tuple(structural_refs),
        sequence_ref=sequence_ref,
        is_isolated_tracking=is_isolated_tracking,
        activation_id=activation_id,
        source_member_key=source_member_key,
    )
