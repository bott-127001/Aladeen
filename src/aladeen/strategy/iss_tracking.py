"""Internal Structure Shift (ISS) Structural Point & Tracking Extraction.

Scope & Design Boundary:
-------------------------
Pure functional extraction of structural swing points and ongoing tracking points
from internal MSMEngine snapshots according to approved ISS rules.
Zero mutable external state, zero I/O, zero network dependencies.
"""

from __future__ import annotations

from typing import Any, List

from .iss_types import FrozenBoundary, InternalPoint
from .types import Direction


def extract_internal_points(
    internal_snap: Any,
    main_direction: Direction,
    boundary: FrozenBoundary,
) -> List[InternalPoint]:
    """Extracts up to 5 structural points (CH1, CL1, CH2, CL2, Tentative) from internal MSM snapshot.

    Direction Mapping:
    - Bearish Main -> Internal UPWARD:
        Pair 1: CH1 (high), CL1 (low)
        Pair 2: CH2 (high), CL2 (low)
        Tentative: TENTATIVE_HIGH (Point 1, 3, or 5)
    - Bullish Main -> Internal DOWNWARD:
        Pair 1: CL1 (low), CH1 (high)
        Pair 2: CL2 (low), CH2 (high)
        Tentative: TENTATIVE_LOW (Point 1, 3, or 5)
    """
    points: List[InternalPoint] = []
    pairs = internal_snap.confirmed_pairs

    if main_direction == Direction.DOWNWARD:
        # Bearish Main -> Internal is UPWARD
        if len(pairs) >= 1:
            p1 = pairs[0]
            points.append(
                InternalPoint(
                    point_number=1,
                    role="CH1",
                    source_candle_index=p1.high.candle_index,
                    candle_open_time=p1.high.candle_open_time,
                    body_edge_price=p1.high.price,
                    is_confirmed=True,
                    identified_bar_index=p1.high.identified_bar_index,
                    confirmed_bar_index=p1.high.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p1.high.price),
                )
            )
            points.append(
                InternalPoint(
                    point_number=2,
                    role="CL1",
                    source_candle_index=p1.low.candle_index,
                    candle_open_time=p1.low.candle_open_time,
                    body_edge_price=p1.low.price,
                    is_confirmed=True,
                    identified_bar_index=p1.low.identified_bar_index,
                    confirmed_bar_index=p1.low.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p1.low.price),
                )
            )

        if len(pairs) >= 2:
            p2 = pairs[1]
            points.append(
                InternalPoint(
                    point_number=3,
                    role="CH2",
                    source_candle_index=p2.high.candle_index,
                    candle_open_time=p2.high.candle_open_time,
                    body_edge_price=p2.high.price,
                    is_confirmed=True,
                    identified_bar_index=p2.high.identified_bar_index,
                    confirmed_bar_index=p2.high.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p2.high.price),
                )
            )
            points.append(
                InternalPoint(
                    point_number=4,
                    role="CL2",
                    source_candle_index=p2.low.candle_index,
                    candle_open_time=p2.low.candle_open_time,
                    body_edge_price=p2.low.price,
                    is_confirmed=True,
                    identified_bar_index=p2.low.identified_bar_index,
                    confirmed_bar_index=p2.low.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p2.low.price),
                )
            )

        tp = internal_snap.tentative_point
        if tp is not None:
            pt_num = 1 if len(pairs) == 0 else (3 if len(pairs) == 1 else 5)
            points.append(
                InternalPoint(
                    point_number=pt_num,
                    role="TENTATIVE_HIGH",
                    source_candle_index=tp.candle_index,
                    candle_open_time=tp.candle_open_time,
                    body_edge_price=tp.price,
                    is_confirmed=False,
                    identified_bar_index=tp.identified_bar_index,
                    is_inside_boundary=boundary.contains_price(tp.price),
                )
            )

    else:
        # Bullish Main -> Internal is DOWNWARD
        if len(pairs) >= 1:
            p1 = pairs[0]
            points.append(
                InternalPoint(
                    point_number=1,
                    role="CL1",
                    source_candle_index=p1.low.candle_index,
                    candle_open_time=p1.low.candle_open_time,
                    body_edge_price=p1.low.price,
                    is_confirmed=True,
                    identified_bar_index=p1.low.identified_bar_index,
                    confirmed_bar_index=p1.low.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p1.low.price),
                )
            )
            points.append(
                InternalPoint(
                    point_number=2,
                    role="CH1",
                    source_candle_index=p1.high.candle_index,
                    candle_open_time=p1.high.candle_open_time,
                    body_edge_price=p1.high.price,
                    is_confirmed=True,
                    identified_bar_index=p1.high.identified_bar_index,
                    confirmed_bar_index=p1.high.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p1.high.price),
                )
            )

        if len(pairs) >= 2:
            p2 = pairs[1]
            points.append(
                InternalPoint(
                    point_number=3,
                    role="CL2",
                    source_candle_index=p2.low.candle_index,
                    candle_open_time=p2.low.candle_open_time,
                    body_edge_price=p2.low.price,
                    is_confirmed=True,
                    identified_bar_index=p2.low.identified_bar_index,
                    confirmed_bar_index=p2.low.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p2.low.price),
                )
            )
            points.append(
                InternalPoint(
                    point_number=4,
                    role="CH2",
                    source_candle_index=p2.high.candle_index,
                    candle_open_time=p2.high.candle_open_time,
                    body_edge_price=p2.high.price,
                    is_confirmed=True,
                    identified_bar_index=p2.high.identified_bar_index,
                    confirmed_bar_index=p2.high.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p2.high.price),
                )
            )

        tp = internal_snap.tentative_point
        if tp is not None:
            pt_num = 1 if len(pairs) == 0 else (3 if len(pairs) == 1 else 5)
            points.append(
                InternalPoint(
                    point_number=pt_num,
                    role="TENTATIVE_LOW",
                    source_candle_index=tp.candle_index,
                    candle_open_time=tp.candle_open_time,
                    body_edge_price=tp.price,
                    is_confirmed=False,
                    identified_bar_index=tp.identified_bar_index,
                    is_inside_boundary=boundary.contains_price(tp.price),
                )
            )

    return points


def extract_tracking_points(
    internal_snap: Any,
    main_direction: Direction,
    boundary: FrozenBoundary,
) -> List[InternalPoint]:
    """Extracts all sequential confirmed pairs and current tentative point for tracking."""
    points: List[InternalPoint] = []
    pairs = internal_snap.confirmed_pairs

    if main_direction == Direction.DOWNWARD:
        # Bearish Main -> Internal is UPWARD
        for i, p in enumerate(pairs):
            points.append(
                InternalPoint(
                    point_number=2 * i + 1,
                    role=f"CH{i + 1}",
                    source_candle_index=p.high.candle_index,
                    candle_open_time=p.high.candle_open_time,
                    body_edge_price=p.high.price,
                    is_confirmed=True,
                    identified_bar_index=p.high.identified_bar_index,
                    confirmed_bar_index=p.high.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p.high.price),
                )
            )
            points.append(
                InternalPoint(
                    point_number=2 * i + 2,
                    role=f"CL{i + 1}",
                    source_candle_index=p.low.candle_index,
                    candle_open_time=p.low.candle_open_time,
                    body_edge_price=p.low.price,
                    is_confirmed=True,
                    identified_bar_index=p.low.identified_bar_index,
                    confirmed_bar_index=p.low.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p.low.price),
                )
            )

        tp = internal_snap.tentative_point
        if tp is not None:
            points.append(
                InternalPoint(
                    point_number=2 * len(pairs) + 1,
                    role="TENTATIVE_HIGH",
                    source_candle_index=tp.candle_index,
                    candle_open_time=tp.candle_open_time,
                    body_edge_price=tp.price,
                    is_confirmed=False,
                    identified_bar_index=tp.identified_bar_index,
                    is_inside_boundary=boundary.contains_price(tp.price),
                )
            )

    else:
        # Bullish Main -> Internal is DOWNWARD
        for i, p in enumerate(pairs):
            points.append(
                InternalPoint(
                    point_number=2 * i + 1,
                    role=f"CL{i + 1}",
                    source_candle_index=p.low.candle_index,
                    candle_open_time=p.low.candle_open_time,
                    body_edge_price=p.low.price,
                    is_confirmed=True,
                    identified_bar_index=p.low.identified_bar_index,
                    confirmed_bar_index=p.low.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p.low.price),
                )
            )
            points.append(
                InternalPoint(
                    point_number=2 * i + 2,
                    role=f"CH{i + 1}",
                    source_candle_index=p.high.candle_index,
                    candle_open_time=p.high.candle_open_time,
                    body_edge_price=p.high.price,
                    is_confirmed=True,
                    identified_bar_index=p.high.identified_bar_index,
                    confirmed_bar_index=p.high.confirmed_bar_index,
                    is_inside_boundary=boundary.contains_price(p.high.price),
                )
            )

        tp = internal_snap.tentative_point
        if tp is not None:
            points.append(
                InternalPoint(
                    point_number=2 * len(pairs) + 1,
                    role="TENTATIVE_LOW",
                    source_candle_index=tp.candle_index,
                    candle_open_time=tp.candle_open_time,
                    body_edge_price=tp.price,
                    is_confirmed=False,
                    identified_bar_index=tp.identified_bar_index,
                    is_inside_boundary=boundary.contains_price(tp.price),
                )
            )

    return points
