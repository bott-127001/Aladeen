"""Integration tests for Read-Only Activation Dashboard Inspection Panel.

Covers:
1. Lossless fixture loading and presentation of all 16 acceptance scenarios with explicit assertions.
2. Real service pipeline execution via calculate_msm() in INTEGRATED_MSM_CHOCH_TJL mode.
3. Real executed engine lifecycle reactivation presentation from live ActivationEngine.
4. Rendering purity preserving checkpoints, sequence cursor, and engine cache.
5. Value-preserving price strings (narrow zones, subsecond precision, non-UTC conversion, diagnostics).
6. Malformed and invalid input fallbacks (naive timestamps, invalid prices, non-null errors).
7. Service-managed context switching and recalculation resets.
8. Bounded terminal history display (50 of 75 records) with deterministic multi-tier sorting.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd
import pytest
from dash import html

from aladeen.strategy.activation_engine import (
    ActivationEngine,
    ActivationEngineConfig,
)
from aladeen.strategy.activation_adapter import (
    TJLSynchronizer,
    adapt_tjl_current_set,
)
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    CoverageStatus,
    ExactPricePrint,
    ExternalCommitEvent,
    PriceBasis,
    RearmController,
    SequenceDomain,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
    format_activation_id,
    format_member_key,
)
from aladeen.strategy.coordinator import MSMChochCoordinator
from aladeen.strategy.service import (
    ActivationSessionCoordinator,
    CalculationMode,
    MSMContext,
    MSMServiceResult,
    calculate_msm,
)
from aladeen.strategy.tjl_types import (
    CurrentEligibleSet,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLSnapshot,
    TJLTransitionRecord,
    TJLTransitionType,
    TJLZone,
)
from aladeen.strategy.types import (
    Direction,
    EngineState,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
)
from aladeen.ui.activation_inspection import (
    AWAITING_CONTEXT_TEXT,
    CANONICAL_UNRESOLVED_BANNER,
    DISCLAIMER_TEXT,
    _format_datetime,
    _format_level_id,
    _format_price,
    build_activation_inspection_elements,
)


FIXTURES_PATH = Path("tests/fixtures/activation_dashboard_acceptance.json")
TJL_FIXTURES_PATH = Path("tests/fixtures/tjl_acceptance.json")


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val or val == "None":
        return None
    dt = datetime.fromisoformat(val)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_canonical_member_key(member_key: str) -> Tuple[str, str]:
    """Safely extracts set_id and role from canonical length-prefixed MK[<len>:<set_id>][<len>:<role>]."""
    if not member_key.startswith("MK["):
        raise ValueError(f"Invalid member key format: {member_key}")
    content = member_key[2:]
    parts = []
    idx = 0
    while idx < len(content):
        if content[idx] != "[":
            raise ValueError(f"Expected '[' at {idx} in {member_key}")
        colon = content.find(":", idx)
        if colon == -1:
            raise ValueError(f"Expected ':' in {member_key}")
        length = int(content[idx + 1:colon])
        val_start = colon + 1
        val_end = val_start + length
        val = content[val_start:val_end]
        if content[val_end] != "]":
            raise ValueError(f"Expected ']' at {val_end} in {member_key}")
        parts.append(val)
        idx = val_end + 1
    if len(parts) != 2:
        raise ValueError(f"Expected 2 parts in member key, got {len(parts)}: {member_key}")
    return parts[0], parts[1]


def serialize_component(comp: Any) -> Any:
    """Recursively serializes Dash HTML components to a dictionary tree for robust assertion testing."""
    if comp is None:
        return None
    if isinstance(comp, (str, int, float, bool)):
        return comp
    if isinstance(comp, (list, tuple)):
        return [serialize_component(c) for c in comp]
    if hasattr(comp, "to_plotly_json"):
        json_data = comp.to_plotly_json()
        props = json_data.get("props", {})
        res: Dict[str, Any] = {
            "type": json_data.get("type", comp.__class__.__name__),
            "id": props.get("id"),
            "children": serialize_component(props.get("children")),
        }
        for k, v in props.items():
            if k not in {"children", "id"}:
                res[k] = v
        return res
    if hasattr(comp, "children"):
        return {
            "type": comp.__class__.__name__,
            "id": getattr(comp, "id", None),
            "children": serialize_component(comp.children),
        }
    return str(comp)


def find_component(tree: Any, target_id: str) -> Optional[Dict[str, Any]]:
    """Finds a component by its HTML/Dash id in a serialized component tree."""
    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            return tree
        for v in tree.values():
            found = find_component(v, target_id)
            if found is not None:
                return found
    elif isinstance(tree, list):
        for item in tree:
            found = find_component(item, target_id)
            if found is not None:
                return found
    return None


def extract_all_text(tree: Any) -> str:
    """Extracts all text content recursively from a serialized component tree."""
    if tree is None:
        return ""
    if isinstance(tree, (str, int, float)):
        return str(tree)
    if isinstance(tree, list):
        return " ".join(extract_all_text(x) for x in tree)
    if isinstance(tree, dict):
        texts = []
        if "children" in tree:
            texts.append(extract_all_text(tree["children"]))
        return " ".join(t for t in texts if t)
    return ""


def make_snapshot_from_fixture(fixture: Dict[str, Any]) -> Tuple[ActivationSnapshot, Optional[TJLSnapshot]]:
    """Losslessly constructs authoritative ActivationSnapshot and optional TJLSnapshot from fixture inputs."""
    inputs = fixture["presentation_inputs"]
    ctx = inputs["context"]
    seq_dom = SequenceDomain(feed_id=ctx["sequence_domain"]["feed_id"], run_id=ctx["sequence_domain"]["run_id"])

    # 1. Members
    current_members = {}
    m_lookup: Dict[str, Dict[str, Any]] = {}
    for m in inputs.get("membership", []):
        mk = m.get("member_key") or format_member_key(m["set_id"], m["role"])
        m_lookup[mk] = m
        level_id = None
        if m.get("level_id"):
            raw_lid = m["level_id"]
            sym = raw_lid.get("symbol_feed_id") or raw_lid.get("symbol") or ctx["symbol"]
            tf = raw_lid.get("source_timeframe") or raw_lid.get("timeframe") or ctx["source_timeframe"]
            open_t = _parse_dt(raw_lid.get("source_open_time"))
            if open_t is None:
                raise ValueError(f"Missing source_open_time in level_id for membership {mk}")
            side_val = TJLSide.HIGH if raw_lid.get("side") == "HIGH" else TJLSide.LOW
            level_id = StableLevelId(
                symbol_feed_id=sym,
                source_timeframe=tf,
                source_open_time=open_t,
                side=side_val,
            )
        usage_val = UsageEvidenceStatus(m.get("usage_evidence_status", "UNKNOWN"))
        ref = SourceMemberReference(
            engine_id=ctx["engine_id"],
            symbol=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            set_id=m["set_id"],
            role=m["role"],
            side=m["level_id"]["side"] if m.get("level_id") else "HIGH",
            lower_edge=float(m["lower_edge"]),
            upper_edge=float(m["upper_edge"]),
            is_line=bool(m.get("is_line", False)),
            direction=Direction.UPWARD,
            level_id=level_id,
            eligibility_available_time=_parse_dt(m.get("eligibility_available_time")),
            usage_evidence_status=usage_val,
        )
        current_members[ref.member_key] = ref

    # 2. Active Activations
    active_activations = {}
    for act in inputs.get("active_activations", []):
        mk = act["member_key"]
        set_id, role = parse_canonical_member_key(mk)
        mem_def = m_lookup.get(mk, {})

        level_id = None
        raw_lid = act.get("level_id") or mem_def.get("level_id")
        if raw_lid:
            sym = raw_lid.get("symbol_feed_id") or raw_lid.get("symbol") or ctx["symbol"]
            tf = raw_lid.get("source_timeframe") or raw_lid.get("timeframe") or ctx["source_timeframe"]
            open_t = _parse_dt(raw_lid.get("source_open_time"))
            if open_t is None:
                raise ValueError(f"Missing source_open_time in level_id for active activation {mk}")
            side_val = TJLSide.HIGH if raw_lid.get("side") == "HIGH" else TJLSide.LOW
            level_id = StableLevelId(
                symbol_feed_id=sym,
                source_timeframe=tf,
                source_open_time=open_t,
                side=side_val,
            )
        lower_edge_val = act.get("lower_edge") if "lower_edge" in act else mem_def.get("lower_edge")
        upper_edge_val = act.get("upper_edge") if "upper_edge" in act else mem_def.get("upper_edge")
        if lower_edge_val is None or upper_edge_val is None:
            raise ValueError(f"Missing lower/upper edge for active activation {mk}")
        lower_edge = float(lower_edge_val)
        upper_edge = float(upper_edge_val)

        rec = ActivationRecord(
            activation_id=act["activation_id"],
            engine_id=ctx["engine_id"],
            symbol=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            confirmation_timeframe=ctx["confirmation_timeframe"],
            set_id=set_id,
            role=role,
            level_id=level_id,
            lower_edge=lower_edge,
            upper_edge=upper_edge,
            state=ActivationState(act["state"]),
            first_touch_time=_parse_dt(act.get("first_touch_time")),
            first_touch_price=float(act["first_touch_price"]) if act.get("first_touch_price") is not None else None,
            trigger_observation_id=act.get("trigger_observation_id"),
            prior_activation_id=act.get("prior_activation_id"),
            generation_seq=int(act.get("generation_seq", 0)),
            usage_evidence_status=UsageEvidenceStatus(act.get("usage_evidence_status", "UNKNOWN")),
            blocked_reason=act.get("blocked_reason"),
            last_observed_position=act.get("last_observed_position"),
        )
        active_activations[rec.member_key] = rec

    # 3. Rearm Controllers
    rearm_controllers = {}
    for ctrl in inputs.get("rearm_controllers", []):
        mk = ctrl["member_key"]
        rearm_armed = bool(ctrl["rearm_armed"])
        if ctrl.get("state"):
            state_val = ActivationState(ctrl["state"])
        else:
            state_val = ActivationState.OUT_OF_ZONE_ARMED if rearm_armed else ActivationState.CANCELLED_EXTERNAL_ENTRY
        rc = RearmController(
            member_key=mk,
            prior_activation_id=ctrl["prior_activation_id"],
            generation_seq=int(ctrl["generation_seq"]),
            state=state_val,
            rearm_armed=rearm_armed,
            last_observed_position=ctrl.get("last_observed_position"),
            cancellation_time=_parse_dt(ctrl.get("cancellation_time")),
            cancellation_sequence_ref=ctrl.get("cancellation_sequence_ref"),
        )
        rearm_controllers[rc.member_key] = rc

    # 4. Terminal Activations
    terminal_activations = []
    terminal_source = inputs.get("terminal_history") or inputs.get("terminal_activations") or []
    for term in terminal_source:
        mk = term["member_key"]
        set_id, role = parse_canonical_member_key(mk)
        mem_def = m_lookup.get(mk, {})

        level_id = None
        raw_lid = term.get("level_id") or mem_def.get("level_id")
        if raw_lid:
            sym = raw_lid.get("symbol_feed_id") or raw_lid.get("symbol") or ctx["symbol"]
            tf = raw_lid.get("source_timeframe") or raw_lid.get("timeframe") or ctx["source_timeframe"]
            open_t = _parse_dt(raw_lid.get("source_open_time"))
            if open_t is None:
                raise ValueError(f"Missing source_open_time in level_id for terminal activation {mk}")
            side_val = TJLSide.HIGH if raw_lid.get("side") == "HIGH" else TJLSide.LOW
            level_id = StableLevelId(
                symbol_feed_id=sym,
                source_timeframe=tf,
                source_open_time=open_t,
                side=side_val,
            )
        lower_edge_val = term.get("lower_edge") if "lower_edge" in term else mem_def.get("lower_edge")
        upper_edge_val = term.get("upper_edge") if "upper_edge" in term else mem_def.get("upper_edge")
        if lower_edge_val is None or upper_edge_val is None:
            raise ValueError(f"Missing lower/upper edge for terminal activation {mk}")
        lower_edge = float(lower_edge_val)
        upper_edge = float(upper_edge_val)

        trec = ActivationRecord(
            activation_id=term["activation_id"],
            engine_id=ctx["engine_id"],
            symbol=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            confirmation_timeframe=ctx["confirmation_timeframe"],
            set_id=set_id,
            role=role,
            level_id=level_id,
            lower_edge=lower_edge,
            upper_edge=upper_edge,
            state=ActivationState(term["state"]),
            first_touch_time=_parse_dt(term.get("first_touch_time")),
            first_touch_price=float(term["first_touch_price"]) if term.get("first_touch_price") is not None else None,
            generation_seq=int(term.get("generation_seq", 1)),
            cancellation_reason=CancellationReason(term["cancellation_reason"]) if term.get("cancellation_reason") else None,
            cancellation_time=_parse_dt(term.get("cancellation_time")),
            cancellation_sequence_ref=term.get("cancellation_sequence_ref"),
            terminal=True,
        )
        terminal_activations.append(trec)

    sync = inputs.get("synchronization", {})
    act_snap = ActivationSnapshot(
        engine_id=ctx["engine_id"],
        symbol=ctx["symbol"],
        source_timeframe=ctx["source_timeframe"],
        confirmation_timeframe=ctx["confirmation_timeframe"],
        sequence_domain=seq_dom,
        active_activations=active_activations,
        terminal_activations=tuple(terminal_activations),
        coverage_status=CoverageStatus(inputs["evidence_gating"]["coverage_status"]),
        last_processed_sequence=sync.get("last_processed_sequence"),
        last_processed_timestamp=_parse_dt(sync.get("last_processed_timestamp")),
        current_members=current_members,
        rearm_controllers=rearm_controllers,
    )

    tjl_snap = None
    if sync.get("is_unresolved"):
        tjl_snap = TJLSnapshot(
            source_engine_id=ctx["engine_id"],
            symbol_feed_id=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=None,
            all_labeled_zones=(),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=True,
            unresolved_diagnostic=sync.get("unresolved_diagnostic"),
            last_processed_index=sync.get("last_processed_index", -1),
            last_received_index=sync.get("last_received_index", -1),
        )

    return act_snap, tjl_snap


@pytest.fixture(scope="module")
def fixture_catalog() -> Dict[str, Any]:
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestActivationDashboardIntegration:
    """Comprehensive test suite for Read-Only Activation Dashboard inspection presentation."""

    def test_all_16_scenarios_execute_through_presentation_builder_with_explicit_assertions(
        self,
        fixture_catalog: Dict[str, Any],
    ) -> None:
        """Executes every one of the 16 acceptance scenarios and verifies scenario-specific contracts."""
        fixtures = fixture_catalog["fixtures"]
        assert len(fixtures) == 16

        for scenario_id, data in fixtures.items():
            act_snap, tjl_snap = make_snapshot_from_fixture(data)
            elements = build_activation_inspection_elements(
                activation_snapshot=act_snap,
                tjl_snapshot=tjl_snap,
                last_synced_transition_index=data["presentation_inputs"]["synchronization"].get("last_synced_transition_index"),
                exact_observation_count=data["presentation_inputs"]["synchronization"].get("exact_observation_count"),
            )
            tree = serialize_component(elements)
            all_text = extract_all_text(tree)

            # Universal invariants across all scenarios:
            assert find_component(tree, "activation-disclaimer-badge") is not None
            assert DISCLAIMER_TEXT in all_text

            # --- Explicit Scenario-Specific Assertions ---
            if scenario_id == "dash_act_01_eligible_untouched":
                assert "ELIGIBLE (UNTOUCHED)" in all_text
                assert "SET_1" in all_text
                assert "—" in all_text  # zero first touch claim

            elif scenario_id == "dash_act_02_first_exact_touch":
                assert "PENDING ACTIVATION" in all_text
                assert "OBS_01" in all_text
                assert "1.1370" in all_text

            elif scenario_id == "dash_act_03_repeated_touch":
                assert "PENDING ACTIVATION" in all_text
                assert "OBS_01" in all_text
                assert "2026-10-02 08:15:00 UTC" in all_text

            elif scenario_id == "dash_act_04_unknown_usage":
                assert "PENDING ACTIVATION" in all_text
                assert "USAGE UNCERTAIN (FAIL-CLOSED)" in all_text
                assert "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED" in all_text

            elif scenario_id == "dash_act_05_incomplete_coverage":
                assert "COVERAGE INCOMPLETE" in all_text
                assert "COVERAGE_INCOMPLETE" in all_text

            elif scenario_id == "dash_act_06_unknown_availability":
                assert "UNKNOWN_AVAILABILITY_TIMING" in all_text
                assert "UNKNOWN AVAILABILITY" in all_text

            elif scenario_id == "dash_act_07_source_cancellation":
                assert find_component(tree, "activation-history-table") is not None

            elif scenario_id == "dash_act_08_cancellation_unknown_time":
                assert "Unknown" in all_text
                assert "#125" in all_text

            elif scenario_id == "dash_act_09_external_cancellation_inside":
                assert "CONTROLLER-MANAGED (AWAITING DEPARTURE)" in all_text
                assert "Gen 2" in all_text

            elif scenario_id == "dash_act_10_armed_controller":
                assert "ARMED FOR RETOUCH" in all_text
                assert "Armed (Outside Zone)" in all_text
                assert "Gen 2" in all_text

            elif scenario_id == "dash_act_11_valid_reactivation":
                expected_prior_id = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)
                expected_active_id = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 2)
                assert expected_prior_id in all_text
                assert expected_active_id in all_text
                assert "REARMED PENDING (GEN 2)" in all_text

            elif scenario_id == "dash_act_12_successor_set_persistent_level":
                assert "SET_2" in all_text
                # Physical-level continuity between SET_1 and SET_2
                assert act_snap is not None
                active_rec = next(iter(act_snap.active_activations.values()))
                term_rec = act_snap.terminal_activations[0]
                assert active_rec.level_id == term_rec.level_id
                assert active_rec.level_id is not None
                assert active_rec.set_id == "SET_2"
                assert term_rec.set_id == "SET_1"
                assert _format_level_id(active_rec.level_id) in all_text

            elif scenario_id == "dash_act_13_unresolved_source_snapshot":
                assert CANONICAL_UNRESOLVED_BANNER in all_text
                assert "Bar #15" in all_text
                assert "Bar #19" in all_text

            elif scenario_id == "dash_act_14_equal_coarse_timestamps":
                assert "#201" in all_text
                assert "#202" in all_text
                # Exact descending history order of rows: #202 must appear strictly before #201
                hist_table = find_component(tree, "activation-history-table")
                assert hist_table is not None
                hist_text = extract_all_text(hist_table)
                idx_202 = hist_text.find("#202")
                idx_201 = hist_text.find("#201")
                assert idx_202 != -1 and idx_201 != -1
                assert idx_202 < idx_201, f"Expected #202 before #201 in history table, got {idx_202} >= {idx_201}"

            elif scenario_id == "dash_act_15_multiple_source_timeframes":
                assert "Source TF: H4" in all_text
                assert "Mapped Confirmation TF:" in all_text
                assert "M5" in all_text

            elif scenario_id == "dash_act_16_repeated_rendering":
                assert "No active members registered in current snapshot." in all_text
                assert find_component(tree, "activation-active-heading") is not None

    def test_repeated_rendering_invariance(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies idempotent and deterministic component tree generation across repeated calls."""
        fixture_data = fixture_catalog["fixtures"]["dash_act_11_valid_reactivation"]
        act_snap, tjl_snap = make_snapshot_from_fixture(fixture_data)

        res1 = serialize_component(build_activation_inspection_elements(activation_snapshot=act_snap, tjl_snapshot=tjl_snap))
        res2 = serialize_component(build_activation_inspection_elements(activation_snapshot=act_snap, tjl_snapshot=tjl_snap))
        assert res1 == res2

    def test_rendering_purity_preserves_engine_checkpoints_cursor_and_cache(self) -> None:
        """Strictly asserts that presentation rendering never mutates live engine state."""
        seq_domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_PURITY")
        config = ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            sequence_domain=seq_domain,
            price_basis=PriceBasis.BID,
        )
        engine = ActivationEngine(config)
        synchronizer = TJLSynchronizer(engine=engine)

        lid1 = StableLevelId(
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            source_open_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            side=TJLSide.HIGH,
        )
        zone1 = TJLZone(
            level_id=lid1,
            label=TJLLabel.TJL1,
            lower_price=1.1350,
            upper_price=1.1400,
            is_line=False,
            source_candle_index=5,
            source_candle_open_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            confirmed_candle_index=10,
        )
        lid2 = StableLevelId(
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            source_open_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            side=TJLSide.LOW,
        )
        zone2 = TJLZone(
            level_id=lid2,
            label=TJLLabel.TJL2_A_PLUS,
            lower_price=1.1200,
            upper_price=1.1250,
            is_line=False,
            source_candle_index=7,
            source_candle_open_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            confirmed_candle_index=10,
        )
        fp = TJLFingerprint(
            source_engine_id="ENGINE_EURUSD_H1",
            direction=Direction.UPWARD,
            ch_point_id=5,
            cl_point_id=7,
            p3_point_id=5,
        )
        curr_set = CurrentEligibleSet(
            set_id="SET_1",
            fingerprint=fp,
            direction=Direction.UPWARD,
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            tjl1_zone=zone1,
            tjl2_zone=zone2,
            p3_source_index=5,
            p3_open_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            p3_price=1.1400,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            created_at_candle_index=10,
        )
        tjl_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=curr_set,
            all_labeled_zones=(zone1,),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=10,
            last_received_index=10,
        )

        snap = synchronizer.sync(tjl_snap, sequence_ref_start=0)

        # Capture complete engine and synchronizer state before rendering
        cp_before = engine.create_checkpoint()
        cursor_before = engine._last_processed_sequence
        members_before = copy.deepcopy(engine._current_members)
        active_before = copy.deepcopy(engine._active_activations)
        controllers_before = copy.deepcopy(engine._rearm_controllers)
        history_before = copy.deepcopy(engine._terminal_activations)
        sync_cursor_before = synchronizer.last_synced_transition_index
        sync_cache_before = copy.deepcopy(synchronizer._usage_cache)
        sync_trans_before = copy.deepcopy(synchronizer._consumed_transitions)

        # Repeated presentation rendering
        for _ in range(5):
            build_activation_inspection_elements(activation_snapshot=snap, tjl_snapshot=tjl_snap)

        # Assert zero mutation
        cp_after = engine.create_checkpoint()
        assert cp_before == cp_after
        assert cursor_before == engine._last_processed_sequence
        assert members_before == engine._current_members
        assert active_before == engine._active_activations
        assert controllers_before == engine._rearm_controllers
        assert history_before == engine._terminal_activations
        assert synchronizer.last_synced_transition_index == sync_cursor_before
        assert synchronizer._usage_cache == sync_cache_before
        assert synchronizer._consumed_transitions == sync_trans_before

    def test_value_preserving_price_and_timestamp_formatting(self) -> None:
        """Verifies value preservation for narrow zones, subseconds, UTC conversions, and diagnostics."""
        # Price formatting
        assert _format_price(None) == "—"
        assert _format_price("invalid") == "[INVALID_PRICE:'invalid']"
        assert _format_price(True) == "[INVALID_PRICE:True]"
        assert _format_price(1.135) == "1.1350"
        assert _format_price(1.135000001) == "1.135000001"
        assert _format_price(1.135000002) == "1.135000002"
        assert _format_price(1.135000001) != _format_price(1.135000002)  # 9th-decimal distinction preserved!
        assert _format_price(1.12345678901234) == "1.12345678901234"

        # Scientific notation & extreme precision round-trip preservation
        for val in [1.135, 1.135000001, 1e-13, 2e-13, 1e-18, 1e10, 123456789.123456]:
            formatted = _format_price(val)
            assert float(formatted) == val, f"Round-trip failed for {val}: got {formatted}"
        assert _format_price(1e-13) != _format_price(2e-13)  # Distinct small values preserved!

        # Datetime formatting
        assert _format_datetime(None) == "Unknown"
        assert _format_datetime("not-a-dt") == "[INVALID_TIMESTAMP:'not-a-dt']"

        naive = datetime(2026, 10, 2, 8, 0, 0)
        assert _format_datetime(naive) == "[NAIVE_TIMESTAMP:2026-10-02T08:00:00]"

        subsecond = datetime(2026, 10, 2, 8, 0, 0, 123456, tzinfo=timezone.utc)
        assert _format_datetime(subsecond) == "2026-10-02 08:00:00.123456 UTC"

        non_utc = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert _format_datetime(non_utc) == "2026-10-02 08:00:00 UTC"

    def test_missing_and_malformed_context_diagnostics(self) -> None:
        """Verifies diagnostic fallback for missing or malformed non-null input."""
        res_none = build_activation_inspection_elements(None)
        assert AWAITING_CONTEXT_TEXT in extract_all_text(serialize_component(res_none))

        res_malformed = build_activation_inspection_elements(activation_snapshot="not_a_snapshot")  # type: ignore
        assert AWAITING_CONTEXT_TEXT in extract_all_text(serialize_component(res_malformed))

    def test_bounded_history_display_and_total_count(self) -> None:
        """Verifies that terminal history is bounded to 50 rows in DOM while displaying total count."""
        domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_BOUNDED")
        terminal_records = []
        for i in range(75):
            rec = ActivationRecord(
                activation_id=f"ACT_EURUSD_H1_SET_1_TJL1_G{i}",
                engine_id="ENGINE_EURUSD_H1",
                symbol="EURUSD",
                source_timeframe="H1",
                confirmation_timeframe="M1",
                set_id="SET_1",
                role="TJL1",
                level_id=None,
                lower_edge=1.1350,
                upper_edge=1.1400,
                state=ActivationState.CANCELLED_EXTERNAL_ENTRY,
                first_touch_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
                cancellation_sequence_ref=i,
                cancellation_time=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
                cancellation_reason=CancellationReason.EXTERNAL_ENTRY,
                generation_seq=i,
                terminal=True,
            )
            terminal_records.append(rec)

        snap = ActivationSnapshot(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            confirmation_timeframe="M1",
            sequence_domain=domain,
            active_activations={},
            terminal_activations=tuple(terminal_records),
            coverage_status=CoverageStatus.COMPLETE,
            last_processed_sequence=100,
            last_processed_timestamp=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            current_members={},
            rearm_controllers={},
        )

        elements = build_activation_inspection_elements(activation_snapshot=snap)
        tree = serialize_component(elements)

        heading = find_component(tree, "activation-history-heading")
        assert heading is not None
        heading_text = extract_all_text(heading)
        assert "75 total records" in heading_text
        assert "Showing latest 50 of 75 records" in heading_text

        table = find_component(tree, "activation-history-table")
        assert table is not None
        tbody = table["children"][1]
        assert len(tbody["children"]) == 50

    def test_service_pipeline_execution_and_context_reset(self) -> None:
        """Verifies offline service calculation produces activation_snapshot and resets on context boundary."""
        with open(TJL_FIXTURES_PATH, "r", encoding="utf-8") as f:
            tjl_data = json.load(f)

        fix = tjl_data["fixtures"]["tjl_02_bearish_basic_end_to_end"]
        df = pd.DataFrame(fix["candles"])
        df["open_time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("open_time")

        coordinator = ActivationSessionCoordinator()
        ctx1 = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction(fix["direction"]),
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        # Execute service run 1
        res1 = calculate_msm(df, ctx1, activation_coordinator=coordinator)
        assert res1.is_valid
        assert res1.tjl_snapshot is not None
        assert res1.activation_snapshot is not None
        assert res1.activation_snapshot.symbol == "EURUSD"
        assert res1.activation_snapshot.source_timeframe == "H1"

        # In candle-only run, 2 members are registered into current_members with fail-closed UNKNOWN usage status
        assert len(res1.activation_snapshot.current_members) == 2
        for m in res1.activation_snapshot.current_members.values():
            assert m.usage_evidence_status == UsageEvidenceStatus.UNKNOWN

        # Execute presentation rendering from real service result
        panel = build_activation_inspection_elements(res1)
        tree = serialize_component(panel)
        assert find_component(tree, "activation-active-table") is not None
        all_text = extract_all_text(tree)
        assert "MK[5:SET_1][4:TJL1]" in all_text
        assert "MK[5:SET_1][11:TJL2_A_PLUS]" in all_text
        assert "INACTIVE_INELIGIBLE" in all_text
        assert "USAGE UNCERTAIN (FAIL-CLOSED)" in all_text

        # Execute service run 2 with DIFFERENT context (GBPUSD) -> verify clean context reset
        ctx2 = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="GBPUSD",
            timeframe="H1",
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction(fix["direction"]),
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        res2 = calculate_msm(df, ctx2, activation_coordinator=coordinator)
        assert res2.is_valid
        assert res2.activation_snapshot is not None
        assert res2.activation_snapshot.symbol == "GBPUSD"
        assert coordinator.engine.symbol == "GBPUSD"

    def test_real_engine_lifecycle_reactivation_presentation(self) -> None:
        """Executes full reactivation lifecycle through real ActivationEngine and asserts presentation."""
        domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_EXEC")
        config = ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            sequence_domain=domain,
            price_basis=PriceBasis.BID,
        )
        engine = ActivationEngine(config)

        # Register eligible member
        lid = StableLevelId(
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            source_open_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            side=TJLSide.HIGH,
        )
        member = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            set_id="SET_1",
            role="TJL1",
            side="HIGH",
            lower_edge=1.1350,
            upper_edge=1.1400,
            is_line=False,
            direction=Direction.UPWARD,
            level_id=lid,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_member(member)

        # 1. First touch -> Gen 1 PENDING_ACTIVATION
        print1 = ExactPricePrint(
            observation_id="OBS_001",
            price=1.1375,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=1,
        )
        engine.process_event(print1)

        # 2. External commit -> Terminal CANCELLED_EXTERNAL_ENTRY & RearmController
        commit = ExternalCommitEvent(
            event_id="COMMIT_01",
            timestamp=datetime(2026, 10, 2, 9, 45, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=2,
            winning_engine_id="ENGINE_OTHER",
            winning_set_id="SET_OTHER",
            winning_role="TJL1",
            target_symbol="EURUSD",
            target_source_timeframe="H1",
        )
        engine.process_event(commit)

        # 3. Departure outside zone -> OUT_OF_ZONE_ARMED
        print_outside = ExactPricePrint(
            observation_id="OBS_002",
            price=1.1450,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=3,
        )
        engine.process_event(print_outside)

        # 4. Retouch -> REARMED_PENDING Gen 2
        print_retouch = ExactPricePrint(
            observation_id="OBS_003",
            price=1.1380,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 10, 15, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=4,
        )
        snap = engine.process_event(print_retouch)

        # Present through UI renderer
        panel = build_activation_inspection_elements(activation_snapshot=snap)
        tree = serialize_component(panel)
        all_text = extract_all_text(tree)

        assert "REARMED PENDING (GEN 2)" in all_text
        assert "ACT_G02[16:ENGINE_EURUSD_H1][2:H1][6:EURUSD][5:SET_1][4:TJL1]" in all_text
        assert "ACT_G01[16:ENGINE_EURUSD_H1][2:H1][6:EURUSD][5:SET_1][4:TJL1]" in all_text
        assert "1.1380" in all_text
        assert "EXTERNAL_ENTRY" in all_text

    def test_same_run_successive_cancellation_sync_with_monotonic_sequences_and_error_preservation(self) -> None:
        """Verifies monotonic sequence allocation across successive sync calls in the same run, and error preservation."""
        coord = ActivationSessionCoordinator("RUN_MONOTONIC_TEST")
        ctx = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        lid1 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        zone1 = TJLZone(lid1, TJLLabel.TJL1, 1.135, 1.140, False, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 10)
        lid2 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), TJLSide.LOW)
        zone2 = TJLZone(lid2, TJLLabel.TJL2_A_PLUS, 1.120, 1.125, False, 7, datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), 10)
        fp = TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 5, 7, 5)
        set1 = CurrentEligibleSet("SET_1", fp, Direction.UPWARD, "ENGINE_EURUSD_H1", "EURUSD", "H1", zone1, zone2, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 1.140, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 10)

        # Call 1: Initial sync with 1 cancellation transition
        trans1 = TJLTransitionRecord(
            transition_type=TJLTransitionType.CHOCH_INVALIDATION,
            outgoing_cancellation_intent=True,
            current_set=None,
            newly_labeled_zones=(),
            transition_candle_index=12,
            transition_time=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=fp,
        )
        snap1 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=None,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(set1,),
            outgoing_cancellation_intent=True,
            last_transition=trans1,
            transition_history=(trans1,),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=12,
            last_received_index=12,
        )

        act_snap1 = coord.sync_tjl_snapshot(snap1, ctx)
        assert act_snap1 is not None
        assert coord.last_synced_transition_index == 0
        assert coord.next_sequence_ref == 1

        # Call 2: Successor sync in same run consuming second cancellation transition
        trans2 = TJLTransitionRecord(
            transition_type=TJLTransitionType.SET_REPLACEMENT,
            outgoing_cancellation_intent=True,
            current_set=None,
            newly_labeled_zones=(),
            transition_candle_index=15,
            transition_time=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_2",
            outgoing_cancelled_fingerprint=fp,
        )
        snap2 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=None,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(set1,),
            outgoing_cancellation_intent=True,
            last_transition=trans2,
            transition_history=(trans1, trans2),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=15,
            last_received_index=15,
        )

        act_snap2 = coord.sync_tjl_snapshot(snap2, ctx)
        assert act_snap2 is not None
        assert coord.last_synced_transition_index == 1
        # Strictly monotonic sequence allocation: transition 1 got 0, transition 2 got 1, next is 2
        assert coord.next_sequence_ref == 2

        # Verify processed cancellation events have strictly monotonic sequences
        events = list(coord.engine._processed_events.values())
        cancellation_events = [e for e in events if hasattr(e, "sequence_ref")]
        assert len(cancellation_events) >= 2
        seqs = [e.sequence_ref for e in cancellation_events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # Strictly unique!

        # Call 3: Truncated / corrupted transition history rejected atomically by synchronizer
        snap_corrupt = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=None,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(set1,),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(trans1,),  # Truncated history: only 1 transition when 2 were consumed!
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=16,
            last_received_index=16,
        )

        # Capture complete authoritative coordinator state before failure
        cp_before = coord.engine.create_checkpoint()
        cursor_before = coord.last_synced_transition_index
        cache_before = copy.deepcopy(coord.synchronizer._usage_cache)
        trans_before = copy.deepcopy(coord.synchronizer._consumed_transitions)
        next_seq_before = coord.next_sequence_ref
        run_id_before = coord.current_run_id
        bound_ctx_before = coord._bound_context_key

        with pytest.raises(Exception) as exc_info:
            coord.sync_tjl_snapshot(snap_corrupt, ctx)

        assert "Transition history truncated" in str(exc_info.value)
        # Authoritative state complete preservation check across all components
        assert coord.engine.create_checkpoint() == cp_before
        assert coord.last_synced_transition_index == cursor_before
        assert coord.synchronizer._usage_cache == cache_before
        assert coord.synchronizer._consumed_transitions == trans_before
        assert coord.next_sequence_ref == next_seq_before
        assert coord.current_run_id == run_id_before
        assert coord._bound_context_key == bound_ctx_before
        assert coord.last_sync_error is not None

        # Verify UI rendering presents the diagnostic banner without wiping state
        panel = build_activation_inspection_elements(
            activation_snapshot=coord.engine.get_snapshot(),
            activation_error=coord.last_sync_error,
        )
        tree = serialize_component(panel)
        assert find_component(tree, "activation-sync-error-banner") is not None
        all_text = extract_all_text(tree)
        assert "Transition history truncated" in all_text

    def test_interleaved_sessions_and_bounded_cleanup(self) -> None:
        """Directive HANDOFF-070: Interleaved sessions A/B maintain strict isolation and bounded LRU eviction."""
        from aladeen.strategy.service import ActivationSessionRegistry

        registry = ActivationSessionRegistry(max_sessions=3)

        # 1. Session A calculates on EURUSD
        coord_a = registry.get_or_create("session_A", run_id_prefix="RUN_A")
        ctx_a = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        lid_a1 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        zone_a1 = TJLZone(lid_a1, TJLLabel.TJL1, 1.135, 1.140, False, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 10)
        lid_a2 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), TJLSide.LOW)
        zone_a2 = TJLZone(lid_a2, TJLLabel.TJL2_A_PLUS, 1.120, 1.125, False, 7, datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), 10)
        fp_a = TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 5, 7, 5)
        set_a = CurrentEligibleSet("SET_A", fp_a, Direction.UPWARD, "ENGINE_EURUSD_H1", "EURUSD", "H1", zone_a1, zone_a2, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 1.140, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 10)
        snap_a = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=set_a,
            all_labeled_zones=(zone_a1, zone_a2),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=10,
            last_received_index=10,
        )
        act_snap_a1 = coord_a.sync_tjl_snapshot(snap_a, ctx_a)
        assert act_snap_a1 is not None
        cp_a_before = coord_a.engine.create_checkpoint()
        run_a_before = coord_a.current_run_id

        # 2. Session B calculates on GBPUSD
        coord_b = registry.get_or_create("session_B", run_id_prefix="RUN_B")
        ctx_b = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="GBPUSD",
            timeframe="H1",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )
        lid_b1 = StableLevelId("GBPUSD", "H1", datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        zone_b1 = TJLZone(lid_b1, TJLLabel.TJL1, 1.250, 1.255, False, 6, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 10)
        lid_b2 = StableLevelId("GBPUSD", "H1", datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc), TJLSide.LOW)
        zone_b2 = TJLZone(lid_b2, TJLLabel.TJL2_A_PLUS, 1.230, 1.235, False, 8, datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc), 10)
        fp_b = TJLFingerprint("ENGINE_GBPUSD_H1", Direction.UPWARD, 6, 8, 6)
        set_b = CurrentEligibleSet("SET_B", fp_b, Direction.UPWARD, "ENGINE_GBPUSD_H1", "GBPUSD", "H1", zone_b1, zone_b2, 6, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.255, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 10)
        snap_b = TJLSnapshot(
            source_engine_id="ENGINE_GBPUSD_H1",
            symbol_feed_id="GBPUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=set_b,
            all_labeled_zones=(zone_b1, zone_b2),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=10,
            last_received_index=10,
        )
        act_snap_b = coord_b.sync_tjl_snapshot(snap_b, ctx_b)
        assert act_snap_b is not None
        cp_b_before = coord_b.engine.create_checkpoint()

        # 3. Session A steady refresh
        act_snap_a2 = coord_a.sync_tjl_snapshot(snap_a, ctx_a)
        assert act_snap_a2 is not None

        # Assert strict cross-session isolation:
        assert coord_a.engine.create_checkpoint() == cp_a_before
        assert coord_a.current_run_id == run_a_before
        assert coord_a.engine.symbol == "EURUSD"
        assert coord_b.engine.create_checkpoint() == cp_b_before
        assert coord_b.engine.symbol == "GBPUSD"
        assert coord_b.current_run_id != coord_a.current_run_id

        # 4. Bounded LRU eviction test (max_sessions=3)
        assert registry.active_session_count == 2
        coord_c = registry.get_or_create("session_C")
        assert registry.active_session_count == 3

        # Access session_A so access order is [B, C, A]
        registry.get_or_create("session_A")

        # Adding session_D should evict session_B
        coord_d = registry.get_or_create("session_D")
        assert registry.active_session_count == 3
        assert "session_B" not in registry._sessions
        assert "session_A" in registry._sessions
        assert "session_C" in registry._sessions
        assert "session_D" in registry._sessions

    def test_explicit_recalculation_advances_run_and_steady_refresh_retains(self) -> None:
        """Directive HANDOFF-070: Explicit recalculation obtains a fresh run identity; steady refresh retains it."""
        coord = ActivationSessionCoordinator("RUN_LIFECYCLE")
        ctx = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        lid1 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        zone1 = TJLZone(lid1, TJLLabel.TJL1, 1.135, 1.140, False, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 10)
        lid2 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), TJLSide.LOW)
        zone2 = TJLZone(lid2, TJLLabel.TJL2_A_PLUS, 1.120, 1.125, False, 7, datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), 10)
        fp = TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 5, 7, 5)
        curr_set = CurrentEligibleSet("SET_1", fp, Direction.UPWARD, "ENGINE_EURUSD_H1", "EURUSD", "H1", zone1, zone2, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 1.140, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 10)
        snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=curr_set,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=10,
            last_received_index=10,
        )

        # 1. Initial calculation (Run 1)
        res1 = coord.sync_tjl_snapshot(snap, ctx)
        assert res1 is not None
        run_1 = coord.current_run_id

        # 2. Steady refresh (force_recalculation=False) -> MUST retain Run 1
        res_refresh = coord.sync_tjl_snapshot(snap, ctx, force_recalculation=False)
        assert res_refresh is not None
        assert coord.current_run_id == run_1

        # 3. Explicit recalculation (force_recalculation=True) -> MUST obtain fresh Run 2
        res2 = coord.sync_tjl_snapshot(snap, ctx, force_recalculation=True)
        assert res2 is not None
        run_2 = coord.current_run_id
        assert run_2 != run_1
        assert "RUN_LIFECYCLE_2" in run_2

        # 4. Subsequent steady refresh -> MUST retain Run 2
        res2_refresh = coord.sync_tjl_snapshot(snap, ctx, force_recalculation=False)
        assert res2_refresh is not None
        assert coord.current_run_id == run_2

    def test_mixed_events_observations_and_transitions_ordering(self) -> None:
        """Directive HANDOFF-070: Mixed exact observations and source cancellations maintain strict sequence monotonicity."""
        coord = ActivationSessionCoordinator("RUN_MIXED_EVENTS")
        ctx = MSMContext(
            data_source="OFFLINE_TEST",
            symbol="EURUSD",
            timeframe="H1",
            start_candle_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            direction=Direction.UPWARD,
            calculation_mode=CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        )

        lid1 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        zone1 = TJLZone(lid1, TJLLabel.TJL1, 1.135, 1.140, False, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 10)
        lid2 = StableLevelId("EURUSD", "H1", datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), TJLSide.LOW)
        zone2 = TJLZone(lid2, TJLLabel.TJL2_A_PLUS, 1.120, 1.125, False, 7, datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc), 10)
        fp = TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 5, 7, 5)
        set1 = CurrentEligibleSet("SET_1", fp, Direction.UPWARD, "ENGINE_EURUSD_H1", "EURUSD", "H1", zone1, zone2, 5, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 1.140, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 10)

        # 1. Source registration
        snap0 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=set1,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=10,
            last_received_index=10,
        )
        coord.sync_tjl_snapshot(snap0, ctx)
        assert coord.next_sequence_ref == 0

        # 2. Accepted exact observation (seq=0)
        domain = coord.engine.sequence_domain
        obs1 = ExactPricePrint(
            observation_id="OBS_01",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=0,
        )
        snap_obs1 = coord.process_exact_price_print(obs1)
        assert snap_obs1 is not None
        assert coord.exact_observation_count == 1
        assert coord.next_sequence_ref == 1

        # 3. Finalized source cancellation (transition 1) -> must allocate seq=1
        trans1 = TJLTransitionRecord(
            transition_type=TJLTransitionType.CHOCH_INVALIDATION,
            outgoing_cancellation_intent=True,
            current_set=None,
            newly_labeled_zones=(),
            transition_candle_index=12,
            transition_time=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=fp,
        )
        snap1 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=None,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(set1,),
            outgoing_cancellation_intent=True,
            last_transition=trans1,
            transition_history=(trans1,),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=12,
            last_received_index=12,
        )
        coord.sync_tjl_snapshot(snap1, ctx)
        assert coord.next_sequence_ref == 2

        # 4. Next accepted exact observation (seq=2)
        obs2 = ExactPricePrint(
            observation_id="OBS_02",
            price=1.1380,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=2,
        )
        snap_obs2 = coord.process_exact_price_print(obs2)
        assert snap_obs2 is not None
        assert coord.exact_observation_count == 2
        assert coord.next_sequence_ref == 3

        # 5. Next source transition -> must allocate seq=3
        trans2 = TJLTransitionRecord(
            transition_type=TJLTransitionType.SET_REPLACEMENT,
            outgoing_cancellation_intent=True,
            current_set=None,
            newly_labeled_zones=(),
            transition_candle_index=15,
            transition_time=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_2",
            outgoing_cancelled_fingerprint=fp,
        )
        snap2 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="EURUSD",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            structural_epoch=1,
            current_eligible_set=None,
            all_labeled_zones=(zone1, zone2),
            historical_sets=(set1,),
            outgoing_cancellation_intent=True,
            last_transition=trans2,
            transition_history=(trans1, trans2),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=15,
            last_received_index=15,
        )
        coord.sync_tjl_snapshot(snap2, ctx)
        assert coord.next_sequence_ref == 4

        # Verify all events have strictly monotonically increasing sequences: 0, 1, 2, 3
        events = list(coord.engine._processed_events.values())
        seqs = [e.sequence_ref for e in events if hasattr(e, "sequence_ref")]
        assert seqs == [0, 1, 2, 3]

        # 6. Failure atomicity: corrupted event does not consume sequence or mutate state
        cp_before = coord.engine.create_checkpoint()
        next_seq_before = coord.next_sequence_ref

        with pytest.raises(Exception):
            coord.process_exact_price_print("NOT_AN_EVENT")  # type: ignore

        assert coord.engine.create_checkpoint() == cp_before
        assert coord.next_sequence_ref == next_seq_before
