"""Deterministic Market Structure Marking (MSM) Engine.

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network access, or persistent storage.
- Purely deterministic, sequential state machine over completed historical candles.
- Supports both batch replay and streaming sequential completed-candle ingestion.
- Zero side-effects on input data; returns immutable snapshots.
"""

from __future__ import annotations

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

        # Engine pointers and markers
        self._start_candle_index: Optional[int] = None
        self._search_start_index: int = 0
        self._next_eligible_pullback_index: int = 0
        self._pullback_scan_pointer: int = 0

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

        self._last_processed_index: int = -1

    @property
    def direction(self) -> Direction:
        return self._direction

    @property
    def state(self) -> EngineState:
        return self._state

    def reset(self) -> None:
        """Resets engine to clean run identity with zero state inheritance."""
        self.__init__(self.config)

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> MSMSnapshot:
        """Processes a sequence of candles in batch and returns the final snapshot."""
        candles = adapt_candles(data)

        # Validate start candle if not initialized
        if self._start_candle_index is None:
            self._start_candle_index = validate_start_candle(self.config, candles)
            self._search_start_index = self._start_candle_index
            self._next_eligible_pullback_index = self._start_candle_index
            self._pullback_scan_pointer = self._start_candle_index

        for c in candles:
            self._ingest_candle(c)

        return self.get_snapshot()

    def process_candle(self, candle: StrategyCandle) -> MSMSnapshot:
        """Processes a single sequentially delivered candle."""
        # Validate sequential ordering against history
        if self._completed_candles:
            last = self._completed_candles[-1]
            if candle.open_time <= last.open_time:
                raise ValueError(
                    f"Sequential candle timestamp {candle.open_time} is not strictly greater "
                    f"than last completed candle {last.open_time} (duplicate or out-of-order)."
                )

        # If starting candle not yet validated, we need to locate it
        if self._start_candle_index is None:
            # Check if this candle is the start candle
            target_time = self.config.start_candle_time
            if target_time.tzinfo is None and candle.open_time.tzinfo is not None:
                target_time = target_time.replace(tzinfo=candle.open_time.tzinfo)

            if candle.open_time == target_time:
                if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
                    raise ValueError(
                        "Invalid starting candle: start candle must be a verified completed historical candle."
                    )
                self._start_candle_index = candle.index
                self._search_start_index = candle.index
                self._next_eligible_pullback_index = candle.index
                self._pullback_scan_pointer = candle.index
            else:
                # If this candle is after the requested start time, then the start candle was missing
                if candle.open_time > target_time:
                    raise ValueError(
                        "Invalid starting candle: start candle must be a verified completed historical candle."
                    )

        self._ingest_candle(candle)
        return self.get_snapshot()

    def replay(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> List[MSMSnapshot]:
        """Processes candles step-by-step, returning an immutable snapshot at each bar."""
        candles = adapt_candles(data)

        if self._start_candle_index is None:
            self._start_candle_index = validate_start_candle(self.config, candles)
            self._search_start_index = self._start_candle_index
            self._next_eligible_pullback_index = self._start_candle_index
            self._pullback_scan_pointer = self._start_candle_index

        snapshots: List[MSMSnapshot] = []
        for c in candles:
            self._ingest_candle(c)
            snapshots.append(self.get_snapshot())

        return snapshots

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a candle. Completed bars advance the state machine; forming bars do not."""
        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            # Completed-candles-only rule: forming bar causes no completed state mutation
            return

        self._completed_candles.append(candle)
        self._last_processed_index = candle.index
        self._evaluate_state_transitions()

    def _evaluate_state_transitions(self) -> None:
        """Evaluates sequential state transitions on newly available completed candles."""
        if self._start_candle_index is None:
            return

        total_candles = len(self._completed_candles)

        while True:
            if self._state == EngineState.SEARCHING_PULLBACK:
                # Need at least two candidate candles starting at or after next_eligible_pullback_index
                p1 = max(self._pullback_scan_pointer, self._next_eligible_pullback_index)
                p2 = p1 + 1

                if p2 >= total_candles:
                    # Not enough completed candles yet to form a 2-candle pair
                    self._pullback_scan_pointer = p1
                    break

                candle_p1 = self._completed_candles[p1]
                candle_p2 = self._completed_candles[p2]

                # Test 2-candle pullback condition
                if self._is_valid_pullback(candle_p1, candle_p2):
                    # Valid 2-candle pullback found!
                    # Search window for tentative point: [search_start_index, p1 - 1]
                    window_start = self._search_start_index
                    window_end = p1 - 1

                    if window_end < window_start:
                        # Empty Range Rule (reconciled clarification):
                        # p1 == search_start_index, so search range is empty (0 candles).
                        # Skip this pullback pair (p1, p2), retain search_start_index unchanged.
                        self._pullback_scan_pointer = p1 + 1
                        continue

                    # Search for tentative extreme
                    if self._direction == Direction.UPWARD:
                        # Highest upper body edge in [window_start, window_end]
                        best_idx, best_price = self._find_max_ub(window_start, window_end)
                        self._tentative_point = SwingPoint(
                            price=best_price,
                            candle_index=best_idx,
                            candle_open_time=self._completed_candles[best_idx].open_time,
                            event_bar_index=p2,
                            event_time=candle_p2.close_time,
                        )
                    else:
                        # Lowest lower body edge in [window_start, window_end]
                        best_idx, best_price = self._find_min_lb(window_start, window_end)
                        self._tentative_point = SwingPoint(
                            price=best_price,
                            candle_index=best_idx,
                            candle_open_time=self._completed_candles[best_idx].open_time,
                            event_bar_index=p2,
                            event_time=candle_p2.close_time,
                        )

                    self._state = EngineState.WAITING_FOR_BREAK
                    # Candidate closing break search begins strictly after p2
                    self._pullback_scan_pointer = p2 + 1
                    continue
                else:
                    # Move candidate window forward by one bar
                    self._pullback_scan_pointer = p1 + 1
                    continue

            elif self._state == EngineState.WAITING_FOR_BREAK:
                # Lockout: no subsequent pullbacks evaluated while waiting
                # Test candles from pullback_scan_pointer onward for strict closing break
                k = self._pullback_scan_pointer
                if k >= total_candles:
                    break

                candle_k = self._completed_candles[k]
                assert self._tentative_point is not None

                is_break = False
                if self._direction == Direction.UPWARD:
                    # Strict upward closing break: close > tentative_high
                    if candle_k.close > self._tentative_point.price:
                        is_break = True
                else:
                    # Strict downward closing break: close < tentative_low
                    if candle_k.close < self._tentative_point.price:
                        is_break = True

                if is_break:
                    # Closing break confirmed!
                    # Search window for opposite level: [tentative_point.candle_index, k] (inclusive)
                    opp_start = self._tentative_point.candle_index
                    opp_end = k

                    if self._direction == Direction.UPWARD:
                        # Confirmed Low: min LB in [opp_start, opp_end]
                        conf_low_idx, conf_low_price = self._find_min_lb(opp_start, opp_end)
                        conf_low = SwingPoint(
                            price=conf_low_price,
                            candle_index=conf_low_idx,
                            candle_open_time=self._completed_candles[conf_low_idx].open_time,
                            event_bar_index=k,
                            event_time=candle_k.close_time,
                        )
                        conf_high = SwingPoint(
                            price=self._tentative_point.price,
                            candle_index=self._tentative_point.candle_index,
                            candle_open_time=self._tentative_point.candle_open_time,
                            event_bar_index=k,
                            event_time=candle_k.close_time,
                        )
                        self._last_support = conf_low
                        self._search_start_index = conf_low_idx

                    else:
                        # Confirmed High: max UB in [opp_start, opp_end]
                        conf_high_idx, conf_high_price = self._find_max_ub(opp_start, opp_end)
                        conf_high = SwingPoint(
                            price=conf_high_price,
                            candle_index=conf_high_idx,
                            candle_open_time=self._completed_candles[conf_high_idx].open_time,
                            event_bar_index=k,
                            event_time=candle_k.close_time,
                        )
                        conf_low = SwingPoint(
                            price=self._tentative_point.price,
                            candle_index=self._tentative_point.candle_index,
                            candle_open_time=self._tentative_point.candle_open_time,
                            event_bar_index=k,
                            event_time=candle_k.close_time,
                        )
                        self._last_resistance = conf_high
                        self._search_start_index = conf_high_idx

                    # Record confirmed pair
                    pair_idx = len(self._confirmed_pairs) + 1
                    new_pair = ConfirmedPair(
                        pair_index=pair_idx,
                        high=conf_high,
                        low=conf_low,
                        confirmation_bar_index=k,
                        confirmation_time=candle_k.close_time,
                    )
                    self._confirmed_pairs.append(new_pair)

                    # Update display-only diagnostic trend status
                    self._update_trend_status()

                    # Advance state
                    self._tentative_point = None
                    self._state = EngineState.SEARCHING_PULLBACK
                    # Post-break pullback restriction: p1 > k (break candle cannot be reused)
                    self._next_eligible_pullback_index = k + 1
                    self._pullback_scan_pointer = k + 1
                    continue
                else:
                    # Advance to next candidate break candle
                    self._pullback_scan_pointer = k + 1
                    continue

    def _is_valid_pullback(self, p1: StrategyCandle, p2: StrategyCandle) -> bool:
        """Tests whether two consecutive candles satisfy the strict 2-candle pullback rule."""
        if self._direction == Direction.UPWARD:
            # Bullish marking: Two consecutive RED candles where close[p2] < low[p1]
            if p1.color != CandleColor.RED or p2.color != CandleColor.RED:
                return False
            # Strict inequality: touch is failure
            return p2.close < p1.low
        else:
            # Bearish marking: Two consecutive GREEN candles where close[p2] > high[p1]
            if p1.color != CandleColor.GREEN or p2.color != CandleColor.GREEN:
                return False
            # Strict inequality: touch is failure
            return p2.close > p1.high

    def _find_max_ub(self, start_idx: int, end_idx: int) -> Tuple[int, float]:
        """Finds highest upper body edge in [start_idx, end_idx], selecting latest on tie."""
        best_idx = start_idx
        best_price = self._completed_candles[start_idx].upper_body_edge

        for i in range(start_idx + 1, end_idx + 1):
            price = self._completed_candles[i].upper_body_edge
            if price > best_price:
                best_price = price
                best_idx = i
            elif price == best_price:
                # Latest candle tie-breaker
                best_idx = i

        return best_idx, best_price

    def _find_min_lb(self, start_idx: int, end_idx: int) -> Tuple[int, float]:
        """Finds lowest lower body edge in [start_idx, end_idx], selecting latest on tie."""
        best_idx = start_idx
        best_price = self._completed_candles[start_idx].lower_body_edge

        for i in range(start_idx + 1, end_idx + 1):
            price = self._completed_candles[i].lower_body_edge
            if price < best_price:
                best_price = price
                best_idx = i
            elif price == best_price:
                # Latest candle tie-breaker
                best_idx = i

        return best_idx, best_price

    def _update_trend_status(self) -> None:
        """Evaluates display-only diagnostic trend status without affecting engine direction."""
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
        return MSMSnapshot(
            state=self._state,
            direction=self._direction,
            search_start_index=self._search_start_index,
            tentative_point=self._tentative_point,
            confirmed_pairs=tuple(self._confirmed_pairs),
            trend_status=self._trend_status,
            last_processed_index=self._last_processed_index,
            last_support=self._last_support,
            last_resistance=self._last_resistance,
            next_eligible_pullback_index=self._next_eligible_pullback_index,
        )
