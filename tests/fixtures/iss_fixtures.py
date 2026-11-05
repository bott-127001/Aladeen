"""Centrally defined fixtures and generators for ISS strategy testing.

Scope & Design Boundary:
-------------------------
Centralizes all synthetic and derived candle sequences for ISS candidate lifecycles,
including outside-range completion, ongoing tracking progression, and subsequent
coordination cancellation.
Used across unit tests (test_iss_engine.py), offline dashboard integration tests
(test_iss_dashboard_integration.py), and browser automation tests (test_iss_browser_controlled.py).
Zero monkey-patching, zero order execution.

EVIDENCE CATEGORIES:
-------------------
1. Complete-State Integration Fixtures:
   - get_candle_19_20_cancellation_fixture(): Full deterministic history where Candle 19 (1.205)
     and Candle 20 (1.201) close strictly above Level 2 (1.200). With complete provenance,
     Candle 20 confirms Main Bullish CHOCH and cancels the unfinished candidate with MAIN_CHOCH_CANCELLED.
2. Synthetic Missing-Evidence Fixtures:
   - get_synthetic_missing_evidence_tracking_fixture(): Supplies OHLC candles for an isolated
     lifecycle test where Main CHOCH confirmation is withheld via missing zone provenance
     (REQUIRED_ZONE_PROVENANCE_MISSING), isolating the source-defined tracking-only engine branch.
     This does NOT represent a complete-state candle-driven reachability demonstration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def _load_base_iss_01_candles() -> List[Dict[str, Any]]:
    path = Path(__file__).parent / "iss_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)["fixtures"]["iss_01_bearish_basic_end_to_end"]
    return [dict(c) for c in data["candles"]]


def get_candle_19_20_cancellation_fixture() -> Dict[str, Any]:
    """Fixture where Candles 19 (1.205) and 20 (1.201) close strictly above Level 2 (1.200).

    Under unmodified production strategy rules:
    - Candle 19 is qualifying Close 1 above Last Resistance (1.200).
    - Candle 20 is qualifying Close 2 above Last Resistance (1.200).
    - Provenance is complete (resistance candle 4, p3 candle 7, low candle 2).
    - Candle 20 confirms Main Bullish CHOCH.
    - Confirmed Main CHOCH unconditionally cancels the candidate with MAIN_CHOCH_CANCELLED.
    - Final state: 0 active tracking points, 0 active zones, 0 confirmed events.
    """
    candles = _load_base_iss_01_candles()
    candles[19]["open"] = 1.206
    candles[19]["high"] = 1.207
    candles[19]["low"] = 1.204
    candles[19]["close"] = 1.205

    candles[20]["open"] = 1.205
    candles[20]["high"] = 1.206
    candles[20]["low"] = 1.2005
    candles[20]["close"] = 1.201

    return {
        "candles": candles,
        "expected_prefix_20": {
            "lifecycle_status": "MAIN_CHOCH_CANCELLED",
            "is_tracking_only": False,
            "main_choch_count": 1,
            "attempted_points_count": 0,
            "tracking_points_count": 0,
            "active_zones_count": 0,
            "confirmed_events_count": 0,
        },
    }


def get_synthetic_missing_evidence_tracking_fixture() -> Dict[str, Any]:
    """Synthetic missing-evidence fixture for isolated tracking-only lifecycle testing.

    NON-REACHABILITY IN COMPLETE INTEGRATED STATE:
    ----------------------------------------------
    In an integrated complete-state run with complete provenance:
    - Upward candidate requires pullback (p1, p2) with C2 < L1 <= C1.
    - If completion candle C20 (p2) closes above Level 2 (> 1.2000), then C19 (p1)
      necessarily closes above Level 2 (> 1.2000) as well.
    - Both adjacent closes above Level 2 trigger Main Bullish CHOCH confirmation,
      unconditionally cancelling the candidate (MAIN_CHOCH_CANCELLED).
    - Therefore, OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY cannot be reached in a complete-state
      integrated run where all zone provenances are intact.

    PURPOSE OF THIS SYNTHETIC FIXTURE:
    ----------------------------------
    - Models an isolated lifecycle test where Main CHOCH confirmation is withheld due
      to missing zone provenance (REQUIRED_ZONE_PROVENANCE_MISSING at Main Level 2).
    - Allows direct verification of the source-defined OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
      state, progression of tracking points without eligibility revival, and subsequent
      clean cancellation when evidence is restored.
    - Missing CHOCH provenance leaves the dependency blocked/unresolved; it does NOT
      represent an authoritative candle-driven complete-state resolution.
    """
    base_candles = _load_base_iss_01_candles()
    base_candles[19]["open"] = 1.206
    base_candles[19]["high"] = 1.207
    base_candles[19]["low"] = 1.204
    base_candles[19]["close"] = 1.205

    base_candles[20]["open"] = 1.205
    base_candles[20]["high"] = 1.206
    base_candles[20]["low"] = 1.2005
    base_candles[20]["close"] = 1.201

    # Candle 21 & 22: Extension candles advancing internal tracking points
    t20 = datetime.fromisoformat(base_candles[20]["time"])
    t21 = t20 + timedelta(hours=1)
    c21 = {
        "time": t21.isoformat(),
        "open": 1.195,
        "high": 1.198,
        "low": 1.194,
        "close": 1.197,
        "is_forming": False,
        "bar_status": "CONFIRMED_COMPLETED",
        "close_time": (t21 + timedelta(hours=1)).isoformat(),
    }
    t22 = t21 + timedelta(hours=1)
    c22 = {
        "time": t22.isoformat(),
        "open": 1.197,
        "high": 1.199,
        "low": 1.192,
        "close": 1.193,
        "is_forming": False,
        "bar_status": "CONFIRMED_COMPLETED",
        "close_time": (t22 + timedelta(hours=1)).isoformat(),
    }

    # Subsequent cancellation candles (Candles 23, 24)
    t23 = t22 + timedelta(hours=1)
    c23 = {
        "time": t23.isoformat(),
        "open": 1.202,
        "high": 1.210,
        "low": 1.201,
        "close": 1.208,
        "is_forming": False,
        "bar_status": "CONFIRMED_COMPLETED",
        "close_time": (t23 + timedelta(hours=1)).isoformat(),
    }
    t24 = t23 + timedelta(hours=1)
    c24 = {
        "time": t24.isoformat(),
        "open": 1.208,
        "high": 1.212,
        "low": 1.203,
        "close": 1.206,
        "is_forming": False,
        "bar_status": "CONFIRMED_COMPLETED",
        "close_time": (t24 + timedelta(hours=1)).isoformat(),
    }

    return {
        "candles_prefix_20": base_candles[:21],
        "extension_candles": [c21, c22],
        "cancellation_candles": [c23, c24],
        "all_candles": base_candles[:21] + [c21, c22, c23, c24],
    }


# Backward compatibility alias
get_tracking_only_fixture = get_synthetic_missing_evidence_tracking_fixture


def make_dataframe_from_candles(raw_candles: List[Dict[str, Any]]) -> pd.DataFrame:
    """Converts a list of candle dicts into a validated UTC DatetimeIndex DataFrame."""
    records = []
    times = []
    for i, c in enumerate(raw_candles):
        ts = pd.to_datetime(c["time"], utc=True)
        times.append(ts)
        records.append({
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "is_forming": bool(c.get("is_forming", False)),
            "bar_status": str(c.get("bar_status", "CONFIRMED_COMPLETED")),
            "close_time": c.get("close_time"),
            "index": i,
        })
    df = pd.DataFrame(records, index=pd.DatetimeIndex(times, tz=timezone.utc))
    return df
