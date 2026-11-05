"""Deterministic Market Structure Marking (MSM) Engine.

Scope & Design Boundary:
-------------------------
Implements pure mathematical MSM algorithm from 'Market Structure Marking.docx'
and 'approved-clarifications.md'.
Strictly read-only calculation logic. Zero order execution, zero network access,
zero MT5 dependencies, zero Plotly/Dash UI code, and zero mutable external state.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple, Union
import pandas as pd

from .types import (
    CandleColor,
    ConfirmedPair,
    Direction,
    EngineState,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
    SwingPoint,
    TrendStatus,
)
from .validator import adapt_candles, validate_start_candle


class MSMEngine:
    """Deterministic implementation of Market Structure Marking."""

    def __init__(self, config: MSMConfig) -> None:
        self.config = config
        self._direction = config.direction
        self._state = EngineState.SEARCHING_PULLBACK

        # Historical completed candles buffer
        self._completed_candles: List[StrategyCandle] = []

        # Internal buffer position pointers (0-based list positions)
        self._start_candle_pos: Optional[int] = None
        self._search_start_pos: int = 0
        self._next_eligible_pullback_pos: int = 0
        self._pullback_scan_pos: int = 0

        # Swing levels
        self._tentative_point: Optional[SwingPoint] = None
        self._confirmed_pairs: List[ConfirmedPair] = []
        self._last_support: Optional[SwingPoint] = None
        self._last_resistance: Optional[SwingPoint] = None

        # Display-only diagnostic trend status
        self._trend_status: str = (
            TrendStatus.MARKING_UPWARD.value
            if self._direction == Direction.UPWARD
            else TrendStatus.MARKING_DOWNWARD.value
        )

        self._last_processed_source_index: int = -1

    @property
    def direction(self) -> Direction:
        return self._direction

    @property
    def state(self) -> EngineState:
        return self._state

    def reset(self) -> None:
        """Resets engine to clean run identity with zero state inheritance."""
        self.__init__(self.config)

    def restart_after_choch(
        self,
        new_direction: Direction,
        restart_reference_pos: int,
        first_eligible_pullback_pos: int,
    ) -> None:
        """Restarts the MSM state machine in the new direction following confirmed CHOCH.

        Preserves confirmed pairs and completed candles history.
        Terminates the previous unfinished cycle (clearing tentative_point).
        Sets search_start_pos to the original Point 3 candle position.
        Restricts next pullback search to strictly after the confirmation candle.
        """
        self._direction = new_direction
        self._state = EngineState.SEARCHING_PULLBACK
        self._tentative_point = None
        self._search_start_pos = restart_reference_pos
        self._next_eligible_pullback_pos = first_eligible_pullback_pos
        self._pullback_scan_pos = first_eligible_pullback_pos
        self._update_trend_status()

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> MSMSnapshot:
        """Processes a sequence of candles as a fresh batch run and returns the final snapshot.

        Validates all input candles upfront before mutating run state (transactional fail-closed).
        Calling process_candles on an engine executes a clean run over the provided data.
        """
        # Validate all candles upfront before mutating state
        candles = adapt_candles(data)
        start_completed_pos, start_source_idx = validate_start_candle(self.config, candles)

        # Reset state to clean run identity for fresh batch execution
        self.reset()
        self._start_candle_pos = start_completed_pos
        self._search_start_pos = start_completed_pos
        self._next_eligible_pullback_pos = start_completed_pos
        self._pullback_scan_pos = start_completed_pos

        for c in candles:
            self._ingest_candle(c)

        return self.get_snapshot()

    def process_candle(self, candle: StrategyCandle) -> MSMSnapshot:
        """Processes a single sequentially delivered candle incrementally."""
        if not isinstance(candle, StrategyCandle):
            # Adapt single dict/candle through strict validator
            adapted = adapt_candles([candle])
            candle = adapted[0]

        # Validate unique source index
        if any(c.index == candle.index for c in self._completed_candles):
            raise ValueError(f"Duplicate candle source index detected: {candle.index}")

        # Validate sequential ordering against existing history
        if self._completed_candles:
            last = self._completed_candles[-1]
            if candle.open_time <= last.open_time:
                raise ValueError(
                    f"Sequential candle timestamp {candle.open_time} is not strictly greater "
                    f"than last completed candle {last.open_time} (duplicate or out-of-order)."
                )

        # If starting candle not yet located
        if self._start_candle_pos is None:
            target_time = self.config.start_candle_time
            if candle.open_time == target_time:
                if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
                    raise ValueError(
                        "Invalid starting candle: start candle must be a verified completed historical candle."
                    )
                # This candle will be ingested at position len(_completed_candles)
                self._start_candle_pos = len(self._completed_candles)
                self._search_start_pos = self._start_candle_pos
                self._next_eligible_pullback_pos = self._start_candle_pos
                self._pullback_scan_pos = self._start_candle_pos
            elif candle.open_time > target_time:
                # Arrived past the start candle without seeing it
                raise ValueError(
                    "Invalid starting candle: start candle must be a verified completed historical candle."
                )

        self._ingest_candle(candle)
        return self.get_snapshot()

    def replay(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> List[MSMSnapshot]:
        """Processes candles step-by-step as a fresh run, returning an immutable snapshot at each bar."""
        candles = adapt_candles(data)
        start_completed_pos, start_source_idx = validate_start_candle(self.config, candles)

        self.reset()
        self._start_candle_pos = start_completed_pos
        self._search_start_pos = start_completed_pos
        self._next_eligible_pullback_pos = start_completed_pos
        self._pullback_scan_pos = start_completed_pos

        snapshots: List[MSMSnapshot] = []
        for c in candles:
            self._ingest_candle(c)
            snapshots.append(self.get_snapshot())

        return snapshots

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a single candle. Completed bars advance the state machine; forming bars do not."""
        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            # Forming bars cause zero mutation to completed historical state
            return

        self._completed_candles.append(candle)
        self._last_processed_source_index = candle.index
        self._evaluate_state_transitions()

    def _evaluate_state_transitions(self) -> None:
        """Evaluates sequential state transitions using internal buffer positions."""
        if self._start_candle_pos is None:
            return

        total_candles = len(self._completed_candles)

        while True:
            if self._state == EngineState.SEARCHING_PULLBACK:
                p1_pos = max(self._pullback_scan_pos, self._next_eligible_pullback_pos)
                p2_pos = p1_pos + 1

                if p2_pos >= total_candles:
                    self._pullback_scan_pos = p1_pos
                    break

                c_p1 = self._completed_candles[p1_pos]
                c_p2 = self._completed_candles[p2_pos]

                # Check sliding two-candle pullback rule
                if self._is_valid_pullback(c_p1, c_p2):
                    # Valid pullback found at positions (p1_pos, p2_pos)
                    # Search window for tentative point: [search_start_pos, p1_pos - 1]
                    window_start = self._search_start_pos
                    window_end = p1_pos - 1

                    if window_end < window_start:
                        # Empty-Range Rule: p1_pos == search_start_pos -> search window is empty (0 candles)
                        # Skip this pullback pair, retain search_start_pos unchanged.
                        self._pullback_scan_pos = p1_pos + 1
                        continue

                    # Search for tentative extreme
                    if self._direction == Direction.UPWARD:
                        best_pos, best_price = self._find_max_ub(window_start, window_end)
                        best_candle = self._completed_candles[best_pos]
                        self._tentative_point = SwingPoint(
                            price=best_price,
                            candle_index=best_candle.index,
                            candle_open_time=best_candle.open_time,
                            identified_bar_index=c_p2.index,
                            identified_time=c_p2.close_time,
                            confirmed_bar_index=None,
                            confirmed_time=None,
                        )
                    else:
                        best_pos, best_price = self._find_min_lb(window_start, window_end)
                        best_candle = self._completed_candles[best_pos]
                        self._tentative_point = SwingPoint(
                            price=best_price,
                            candle_index=best_candle.index,
                            candle_open_time=best_candle.open_time,
                            identified_bar_index=c_p2.index,
                            identified_time=c_p2.close_time,
                            confirmed_bar_index=None,
                            confirmed_time=None,
                        )

                    self._state = EngineState.WAITING_FOR_BREAK
                    # Candidate closing break search begins strictly after p2
                    self._pullback_scan_pos = p2_pos + 1
                    self._tentative_pos = best_pos
                    continue
                else:
                    # Move candidate window forward by one bar
                    self._pullback_scan_pos = p1_pos + 1
                    continue

            elif self._state == EngineState.WAITING_FOR_BREAK:
                # Lockout: no subsequent pullbacks evaluated while waiting
                k_pos = self._pullback_scan_pos
                if k_pos >= total_candles:
                    break

                c_k = self._completed_candles[k_pos]
                assert self._tentative_point is not None

                is_break = False
                if self._direction == Direction.UPWARD:
                    if c_k.close > self._tentative_point.price:
                        is_break = True
                else:
                    if c_k.close < self._tentative_point.price:
                        is_break = True

                if is_break:
                    # Closing break confirmed at position k_pos!
                    # Search window for opposite level: [tentative_pos, k_pos] (inclusive)
                    opp_start_pos = self._tentative_pos
                    opp_end_pos = k_pos

                    if self._direction == Direction.UPWARD:
                        # Confirmed Low: min LB in [opp_start_pos, opp_end_pos]
                        conf_low_pos, conf_low_price = self._find_min_lb(opp_start_pos, opp_end_pos)
                        conf_low_candle = self._completed_candles[conf_low_pos]

                        conf_low = SwingPoint(
                            price=conf_low_price,
                            candle_index=conf_low_candle.index,
                            candle_open_time=conf_low_candle.open_time,
                            identified_bar_index=c_k.index,
                            identified_time=c_k.close_time,
                            confirmed_bar_index=c_k.index,
                            confirmed_time=c_k.close_time,
                        )
                        # Retain original identification provenance of tentative high
                        conf_high = SwingPoint(
                            price=self._tentative_point.price,
                            candle_index=self._tentative_point.candle_index,
                            candle_open_time=self._tentative_point.candle_open_time,
                            identified_bar_index=self._tentative_point.identified_bar_index,
                            identified_time=self._tentative_point.identified_time,
                            confirmed_bar_index=c_k.index,
                            confirmed_time=c_k.close_time,
                        )
                        self._last_support = conf_low
                        self._search_start_pos = conf_low_pos

                    else:
                        # Confirmed High: max UB in [opp_start_pos, opp_end_pos]
                        conf_high_pos, conf_high_price = self._find_max_ub(opp_start_pos, opp_end_pos)
                        conf_high_candle = self._completed_candles[conf_high_pos]

                        conf_high = SwingPoint(
                            price=conf_high_price,
                            candle_index=conf_high_candle.index,
                            candle_open_time=conf_high_candle.open_time,
                            identified_bar_index=c_k.index,
                            identified_time=c_k.close_time,
                            confirmed_bar_index=c_k.index,
                            confirmed_time=c_k.close_time,
                        )
                        # Retain original identification provenance of tentative low
                        conf_low = SwingPoint(
                            price=self._tentative_point.price,
                            candle_index=self._tentative_point.candle_index,
                            candle_open_time=self._tentative_point.candle_open_time,
                            identified_bar_index=self._tentative_point.identified_bar_index,
                            identified_time=self._tentative_point.identified_time,
                            confirmed_bar_index=c_k.index,
                            confirmed_time=c_k.close_time,
                        )
                        self._last_resistance = conf_high
                        self._search_start_pos = conf_high_pos

                    pair_num = len(self._confirmed_pairs) + 1
                    confirmed_pair = ConfirmedPair(
                        pair_index=pair_num,
                        high=conf_high,
                        low=conf_low,
                        confirmation_bar_index=c_k.index,
                        confirmation_time=c_k.close_time,
                    )
                    self._confirmed_pairs.append(confirmed_pair)
                    self._update_trend_status()

                    # Reset cycle
                    self._tentative_point = None
                    self._next_eligible_pullback_pos = k_pos + 1
                    self._pullback_scan_pos = self._next_eligible_pullback_pos
                    self._state = EngineState.SEARCHING_PULLBACK
                    continue
                else:
                    # Closing break did not occur at k_pos; advance to k_pos + 1
                    self._pullback_scan_pos = k_pos + 1
                    continue

    def _is_valid_pullback(self, p1: StrategyCandle, p2: StrategyCandle) -> bool:
        """Determines if consecutive candles (p1, p2) constitute a valid pullback."""
        if self._direction == Direction.UPWARD:
            # Upward: 2 consecutive red candles with p2 close strictly below p1 low
            if p1.color != CandleColor.RED or p2.color != CandleColor.RED:
                return False
            return p2.close < p1.low
        else:
            # Downward: 2 consecutive green candles with p2 close strictly above p1 high
            if p1.color != CandleColor.GREEN or p2.color != CandleColor.GREEN:
                return False
            return p2.close > p1.high

    def _find_max_ub(self, start_pos: int, end_pos: int) -> Tuple[int, float]:
        """Finds max UB in [start_pos, end_pos] with latest-candle tie-breaking."""
        best_pos = start_pos
        best_price = self._completed_candles[start_pos].upper_body_edge

        for pos in range(start_pos + 1, end_pos + 1):
            price = self._completed_candles[pos].upper_body_edge
            if price > best_price:
                best_price = price
                best_pos = pos
            elif price == best_price:
                # Latest candle tie-breaker
                best_pos = pos

        return best_pos, best_price

    def _find_min_lb(self, start_pos: int, end_pos: int) -> Tuple[int, float]:
        """Finds min LB in [start_pos, end_pos] with latest-candle tie-breaking."""
        best_pos = start_pos
        best_price = self._completed_candles[start_pos].lower_body_edge

        for pos in range(start_pos + 1, end_pos + 1):
            price = self._completed_candles[pos].lower_body_edge
            if price < best_price:
                best_price = price
                best_pos = pos
            elif price == best_price:
                # Latest candle tie-breaker
                best_pos = pos

        return best_pos, best_price

    def _update_trend_status(self) -> None:
        if len(self._confirmed_pairs) < 2:
            self._trend_status = (
                TrendStatus.MARKING_UPWARD.value
                if self._direction == Direction.UPWARD
                else TrendStatus.MARKING_DOWNWARD.value
            )
            return

        curr_pair = self._confirmed_pairs[-1]
        prev_pair = self._confirmed_pairs[-2]

        h_curr = curr_pair.high.price
        h_prev = prev_pair.high.price
        l_curr = curr_pair.low.price
        l_prev = prev_pair.low.price

        if h_curr > h_prev and l_curr > l_prev:
            self._trend_status = TrendStatus.UPWARD_TREND.value
        elif h_curr < h_prev and l_curr < l_prev:
            self._trend_status = TrendStatus.DOWNWARD_TREND.value
        else:
            self._trend_status = TrendStatus.NOT_CONFIRMED.value

    def get_snapshot(self) -> MSMSnapshot:
        """Returns an immutable snapshot of current engine state."""
        # Map internal positions to source indices for external provenance
        if self._completed_candles and self._search_start_pos < len(self._completed_candles):
            search_start_idx = self._completed_candles[self._search_start_pos].index
        else:
            search_start_idx = 0

        if self._completed_candles and self._next_eligible_pullback_pos < len(self._completed_candles):
            next_pullback_idx: Optional[int] = self._completed_candles[self._next_eligible_pullback_pos].index
        else:
            # If past the buffer, source index is unknown (not fabricated)
            next_pullback_idx = None

        return MSMSnapshot(
            state=self._state,
            direction=self._direction,
            search_start_index=search_start_idx,
            tentative_point=self._tentative_point,
            confirmed_pairs=tuple(self._confirmed_pairs),
            trend_status=self._trend_status,
            last_processed_index=self._last_processed_source_index,
            last_support=self._last_support,
            last_resistance=self._last_resistance,
            next_eligible_pullback_index=next_pullback_idx,
            next_eligible_pullback_position=self._next_eligible_pullback_pos,
        )
