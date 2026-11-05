"""Acceptance fixture integrity tests for Market Structure Marking (MSM).

Scope & Verification Boundary:
------------------------------
This module verifies the data consistency, OHLC geometry, chronological ordering,
referenced index validity, body-edge calculations, and mathematical extreme selection
(with latest-candle tie-breaking) of the independently documented MSM acceptance fixtures
stored in `tests/fixtures/msm_acceptance.json`.

IMPORTANT:
This test verifies fixture geometry and documented search-window mathematics only.
It does NOT implement or verify the MSM state machine, lifecycle transitions,
or strategy event sequencing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from datetime import datetime
import pytest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "msm_acceptance.json"


@pytest.fixture(scope="module")
def acceptance_data() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ub(c: dict) -> float:
    return max(float(c["open"]), float(c["close"]))


def lb(c: dict) -> float:
    return min(float(c["open"]), float(c["close"]))


class TestMSMFixtureIntegrity:
    """Verifies acceptance dataset integrity without implementing strategy state machine."""

    def test_fixture_file_exists_and_loads(self, acceptance_data):
        assert "fixtures" in acceptance_data
        assert len(acceptance_data["fixtures"]) >= 14

    def test_ohlc_geometry_and_chronology(self, acceptance_data):
        """Every fixture candle must satisfy strict OHLC bounds, finite checks, and chronological order."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            candles = fix.get("candles", [])
            assert len(candles) > 0, f"{fix_id}: empty candles"

            prev_time = None
            for i, c in enumerate(candles):
                o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])

                # Positive finite prices (strictly rejecting +inf, -inf, nan)
                for val, name in [(o, "open"), (h, "high"), (l, "low"), (cl, "close")]:
                    assert math.isfinite(val), f"{fix_id}[{i}]: {name} is not finite ({val})"
                    assert val > 0, f"{fix_id}[{i}]: {name} is non-positive ({val})"

                # High is upper bound, Low is lower bound
                assert h >= l, f"{fix_id}[{i}]: high < low"
                assert h >= ub(c), f"{fix_id}[{i}]: high < upper body edge"
                assert l <= lb(c), f"{fix_id}[{i}]: low > lower body edge"

                # Chronological ordering of open timestamps
                curr_time = datetime.fromisoformat(c.get("open_time", c["time"]))
                if prev_time is not None:
                    assert curr_time > prev_time, f"{fix_id}[{i}]: timestamps not strictly increasing"
                prev_time = curr_time

                # If close_time is provided, ensure close_time > open_time
                if "close_time" in c:
                    close_time = datetime.fromisoformat(c["close_time"])
                    assert close_time > curr_time, f"{fix_id}[{i}]: close_time not after open_time"

    def test_referenced_indices_exist(self, acceptance_data):
        """All referenced indices in search evaluations, events, and prefixes must exist in candles."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            candles = fix.get("candles", [])
            c_indices = {c["index"] for c in candles}

            # Search evaluations
            for s in fix.get("search_evaluations", []):
                # Search type validation: must strictly be MAX_UB or MIN_LB
                assert s["search_type"] in ("MAX_UB", "MIN_LB"), (
                    f"{fix_id}: invalid search_type '{s.get('search_type')}'"
                )

                start, end = s["search_window"]
                assert start in c_indices, f"{fix_id}: search start index {start} not in candles"
                assert end in c_indices, f"{fix_id}: search end index {end} not in candles"
                assert start <= end, f"{fix_id}: search window inverted ({start} > {end})"
                assert s["selected_index"] in c_indices, f"{fix_id}: selected_index {s['selected_index']} not in candles"
                for idx in s["eligible_indices"]:
                    assert idx in c_indices, f"{fix_id}: eligible_index {idx} not in candles"
                for idx in s["extreme_indices"]:
                    assert idx in c_indices, f"{fix_id}: extreme_index {idx} not in candles"

            # Event indices validation
            events = fix.get("expected_events", {})
            if "pullback_candles" in events:
                for idx in events["pullback_candles"]:
                    assert idx in c_indices, f"{fix_id}: pullback candle {idx} not in candles"
            if "tentative_high" in events and "candle_index" in events["tentative_high"]:
                assert events["tentative_high"]["candle_index"] in c_indices
            if "tentative_low" in events and "candle_index" in events["tentative_low"]:
                assert events["tentative_low"]["candle_index"] in c_indices
            if "confirmed_high" in events and "candle_index" in events["confirmed_high"]:
                assert events["confirmed_high"]["candle_index"] in c_indices
            if "confirmed_low" in events and "candle_index" in events["confirmed_low"]:
                assert events["confirmed_low"]["candle_index"] in c_indices
            if "next_search_start_index" in events:
                assert events["next_search_start_index"] in c_indices

            # Prefix indices validation
            for p_name, p_data in fix.get("prefixes", {}).items():
                if "available_indices" in p_data:
                    for idx in p_data["available_indices"]:
                        assert idx in c_indices, f"{fix_id} {p_name}: index {idx} not in candles"

    def test_body_edge_arithmetic_matches(self, acceptance_data):
        """Expected extreme prices must exactly match the upper or lower body edge of selected candle."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            c_map = {c["index"]: c for c in fix.get("candles", [])}

            for s in fix.get("search_evaluations", []):
                sel_candle = c_map[s["selected_index"]]
                expected_price = float(s["selected_price"])

                if s["search_type"] == "MAX_UB":
                    actual_edge = ub(sel_candle)
                    assert actual_edge == expected_price, (
                        f"{fix_id}: {s['target']} UB mismatch: actual={actual_edge}, expected={expected_price}"
                    )
                elif s["search_type"] == "MIN_LB":
                    actual_edge = lb(sel_candle)
                    assert actual_edge == expected_price, (
                        f"{fix_id}: {s['target']} LB mismatch: actual={actual_edge}, expected={expected_price}"
                    )

    def test_search_window_extremes_and_tie_breaking(self, acceptance_data):
        """Independently verifies exact extreme value selection and latest-index tie-breaking (no approx)."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            c_map = {c["index"]: c for c in fix.get("candles", [])}

            for s in fix.get("search_evaluations", []):
                start, end = s["search_window"]
                window_indices = list(range(start, end + 1))
                assert window_indices == s["eligible_indices"], f"{fix_id}: eligible_indices do not match window"

                # Calculate actual body edges
                if s["search_type"] == "MAX_UB":
                    edges = [(idx, ub(c_map[idx])) for idx in window_indices]
                    target_val = max(v for _, v in edges)
                elif s["search_type"] == "MIN_LB":
                    edges = [(idx, lb(c_map[idx])) for idx in window_indices]
                    target_val = min(v for _, v in edges)
                else:
                    pytest.fail(f"Unknown search type {s['search_type']}")

                # Collect all indices matching the extremum with EXACT equality (never approx)
                matches = [idx for idx, v in edges if v == target_val]
                expected_extremes = s["extreme_indices"]
                assert matches == expected_extremes, (
                    f"{fix_id} {s['target']}: extreme indices mismatch: actual {matches} vs expected {expected_extremes}"
                )

                # Latest index tie-breaking rule
                latest_idx = max(matches)
                assert s["selected_index"] == latest_idx, (
                    f"{fix_id} {s['target']}: tie-breaker failed! Selected {s['selected_index']}, expected {latest_idx}"
                )

                # Tie flag verification
                is_tied = len(matches) > 1
                assert s["is_tied"] == is_tied, f"{fix_id} {s['target']}: is_tied flag mismatch"

    def test_near_but_unequal_prices_not_treated_as_ties(self):
        """Regression test: verifies that values differing by small floating point deltas are NOT classified as ties."""
        # Synthetic test window with near prices
        test_window = [
            {"index": 0, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.000000},      # UB = 104.000000
            {"index": 1, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.000001},      # UB = 104.000001 (strictly higher!)
            {"index": 2, "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.999999},      # UB = 103.999999 (strictly lower)
        ]
        edges = [(c["index"], ub(c)) for c in test_window]
        target_val = max(v for _, v in edges)

        # Exact equality check: only index 1 should match
        exact_matches = [idx for idx, v in edges if v == target_val]
        assert exact_matches == [1], f"Expected exact match [1], got {exact_matches}"
        assert len(exact_matches) == 1  # Must NOT be a tie!

        # Demonstrate that a flawed approx check would have falsely grouped them
        flawed_matches = [idx for idx, v in edges if v == pytest.approx(target_val, rel=1e-5)]
        assert len(flawed_matches) > 1, "Sanity check on flawed approx grouping"
