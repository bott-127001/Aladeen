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
        """Every fixture candle must satisfy strict OHLC bounds and chronological order."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            candles = fix.get("candles", [])
            assert len(candles) > 0, f"{fix_id}: empty candles"

            prev_time = None
            for i, c in enumerate(candles):
                o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])

                # Positive finite prices
                assert o > 0 and h > 0 and l > 0 and cl > 0, f"{fix_id}[{i}]: non-positive prices"

                # High is upper bound, Low is lower bound
                assert h >= l, f"{fix_id}[{i}]: high < low"
                assert h >= ub(c), f"{fix_id}[{i}]: high < upper body edge"
                assert l <= lb(c), f"{fix_id}[{i}]: low > lower body edge"

                # Chronological ordering
                curr_time = datetime.fromisoformat(c["time"])
                if prev_time is not None:
                    assert curr_time > prev_time, f"{fix_id}[{i}]: timestamps not strictly increasing"
                prev_time = curr_time

    def test_referenced_indices_exist(self, acceptance_data):
        """All referenced indices in search evaluations and events must exist in candles."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            candles = fix.get("candles", [])
            c_indices = {c["index"] for c in candles}

            # Search evaluations
            for s in fix.get("search_evaluations", []):
                start, end = s["search_window"]
                assert start in c_indices, f"{fix_id}: search start index {start} not in candles"
                assert end in c_indices, f"{fix_id}: search end index {end} not in candles"
                assert start <= end, f"{fix_id}: search window inverted ({start} > {end})"
                assert s["selected_index"] in c_indices, f"{fix_id}: selected_index {s['selected_index']} not in candles"
                for idx in s["eligible_indices"]:
                    assert idx in c_indices, f"{fix_id}: eligible_index {idx} not in candles"
                for idx in s["extreme_indices"]:
                    assert idx in c_indices, f"{fix_id}: extreme_index {idx} not in candles"

    def test_body_edge_arithmetic_matches(self, acceptance_data):
        """Expected extreme prices must match the exact upper or lower body edge of selected candle."""
        for fix_id, fix in acceptance_data["fixtures"].items():
            c_map = {c["index"]: c for c in fix.get("candles", [])}

            for s in fix.get("search_evaluations", []):
                sel_candle = c_map[s["selected_index"]]
                expected_price = float(s["selected_price"])

                if s["search_type"] == "MAX_UB":
                    actual_edge = ub(sel_candle)
                    assert actual_edge == pytest.approx(expected_price), (
                        f"{fix_id}: {s['target']} UB mismatch: actual={actual_edge}, expected={expected_price}"
                    )
                elif s["search_type"] == "MIN_LB":
                    actual_edge = lb(sel_candle)
                    assert actual_edge == pytest.approx(expected_price), (
                        f"{fix_id}: {s['target']} LB mismatch: actual={actual_edge}, expected={expected_price}"
                    )

    def test_search_window_extremes_and_tie_breaking(self, acceptance_data):
        """Independently verifies that selected indices obey extreme value selection and latest-index tie-breaking."""
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
                else:
                    edges = [(idx, lb(c_map[idx])) for idx in window_indices]
                    target_val = min(v for _, v in edges)

                # Collect all indices matching the extremum
                matches = [idx for idx, v in edges if v == pytest.approx(target_val)]
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
