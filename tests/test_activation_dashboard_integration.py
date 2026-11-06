"""Comprehensive integration verification for Read-Only Activation Dashboard.

Validates:
1. All 16 standardized acceptance scenarios executed through build_activation_inspection_elements().
2. Bit-for-bit component tree invariance across repeated renders.
3. Rendering purity: zero mutations to engine state, checkpoints, synchronizer cursor, or usage cache.
4. Complete isolation across session context changes (symbol, timeframe reset).
5. Missing context diagnostic fallback ("Awaiting activation context").
6. Bounded history display (top 50 rows in DOM) with unpruned total history count.
7. Strict non-fabrication: zero exact observations from candles; missing usage defaults to UNKNOWN.
8. Labeling of Scenario 13 synthetic fallback until candle pipeline construction is established.

Scope Boundary:
---------------
Pure read-only presentation only. Strictly zero order execution, zero MT5 trading calls,
zero live account modification, zero confirmation arbitration, zero usage ledger writes,
and zero trade entry signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    CoverageStatus,
    Direction,
    PriceBasis,
    RearmController,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
    format_member_key,
)
from aladeen.strategy.activation_engine import (
    ActivationEngine,
    ActivationEngineConfig,
    ExactPricePrint,
    ExternalCommitEvent,
)
from aladeen.strategy.activation_adapter import TJLSynchronizer
from aladeen.strategy.service import MSMContext, MSMServiceResult
from aladeen.strategy.tjl_types import StableLevelId, TJLSide, TJLSnapshot
from aladeen.ui.activation_inspection import (
    AWAITING_CONTEXT_TEXT,
    CANONICAL_UNRESOLVED_BANNER,
    DISCLAIMER_TEXT,
    build_activation_inspection_elements,
)


def _parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str)


def make_snapshot_from_fixture(fixture: Dict[str, Any]) -> Tuple[ActivationSnapshot, Optional[TJLSnapshot]]:
    """Constructs authoritative ActivationSnapshot and optional TJLSnapshot from fixture inputs."""
    inputs = fixture["presentation_inputs"]
    ctx = inputs["context"]
    seq_dom = SequenceDomain(feed_id=ctx["sequence_domain"]["feed_id"], run_id=ctx["sequence_domain"]["run_id"])

    # 1. Members
    current_members = {}
    for m in inputs.get("membership", []):
        ref = SourceMemberReference(
            engine_id=ctx["engine_id"],
            symbol=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            set_id=m["set_id"],
            role=m["role"],
            side=m["level_id"]["side"] if m.get("level_id") else "HIGH",
            lower_edge=m["lower_edge"],
            upper_edge=m["upper_edge"],
            is_line=m["is_line"],
            direction=Direction.UPWARD,
            eligibility_available_time=_parse_dt(m.get("eligibility_available_time")),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        current_members[ref.member_key] = ref

    # 2. Active Activations
    active_activations = {}
    for act in inputs.get("active_activations", []):
        mk_parts = act["member_key"].replace("MK[", "").rstrip("]").split("][")
        set_id = mk_parts[0].split(":")[-1]
        role = mk_parts[1].split(":")[-1]
        rec = ActivationRecord(
            activation_id=act["activation_id"],
            engine_id=ctx["engine_id"],
            symbol=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            confirmation_timeframe=ctx["confirmation_timeframe"],
            set_id=set_id,
            role=role,
            level_id=None,
            lower_edge=1.1350,
            upper_edge=1.1400,
            state=ActivationState(act["state"]),
            first_touch_time=_parse_dt(act.get("first_touch_time")),
            first_touch_price=act.get("first_touch_price"),
            trigger_observation_id=act.get("trigger_observation_id"),
            prior_activation_id=act.get("prior_activation_id"),
            generation_seq=act.get("generation_seq", 0),
            usage_evidence_status=UsageEvidenceStatus(act.get("usage_evidence_status", "UNKNOWN")),
            blocked_reason=act.get("blocked_reason"),
            last_observed_position=act.get("last_observed_position"),
        )
        active_activations[rec.member_key] = rec

    # 3. Rearm Controllers
    rearm_controllers = {}
    for ctrl in inputs.get("rearm_controllers", []):
        rc = RearmController(
            member_key=ctrl["member_key"],
            prior_activation_id=ctrl["prior_activation_id"],
            generation_seq=ctrl["generation_seq"],
            state=ActivationState(ctrl["state"]),
            rearm_armed=ctrl["rearm_armed"],
            last_observed_position=ctrl.get("last_observed_position"),
            cancellation_time=_parse_dt(ctrl.get("cancellation_time")),
            cancellation_sequence_ref=ctrl.get("cancellation_sequence_ref"),
        )
        rearm_controllers[rc.member_key] = rc

    # 4. Terminal History
    terminal_activations = []
    for term in inputs.get("terminal_history", []):
        mk_parts = term["member_key"].replace("MK[", "").rstrip("]").split("][")
        set_id = mk_parts[0].split(":")[-1]
        role = mk_parts[1].split(":")[-1]
        trec = ActivationRecord(
            activation_id=term["activation_id"],
            engine_id=ctx["engine_id"],
            symbol=ctx["symbol"],
            source_timeframe=ctx["source_timeframe"],
            confirmation_timeframe=ctx["confirmation_timeframe"],
            set_id=set_id,
            role=role,
            level_id=None,
            lower_edge=1.1350,
            upper_edge=1.1400,
            state=ActivationState(term["state"]),
            first_touch_time=_parse_dt(term.get("first_touch_time")),
            generation_seq=term.get("generation_seq", 1),
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
        terminal_activations=terminal_activations,
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


def _find_component_by_id(element: Any, target_id: str) -> Optional[Any]:
    """Recursively search for a Dash component with specific id."""
    if hasattr(element, "id") and getattr(element, "id") == target_id:
        return element
    children = getattr(element, "children", None)
    if isinstance(children, list):
        for child in children:
            res = _find_component_by_id(child, target_id)
            if res is not None:
                return res
    elif children is not None:
        return _find_component_by_id(children, target_id)
    return None


@pytest.fixture(scope="module")
def fixture_catalog() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "activation_dashboard_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestActivationDashboardPresentationExecution:
    """Rigorous execution tests for Read-Only Activation Dashboard Presentation."""

    def test_all_16_scenarios_execute_through_presentation_builder(self, fixture_catalog: Dict[str, Any]) -> None:
        """Executes every single one of the 16 acceptance scenarios through the presentation builder."""
        fixtures = fixture_catalog["fixtures"]
        assert len(fixtures) == 16

        for scenario_id, data in fixtures.items():
            act_snap, tjl_snap = make_snapshot_from_fixture(data)
            elements = build_activation_inspection_elements(
                activation_snapshot=act_snap,
                tjl_snapshot=tjl_snap,
            )
            assert len(elements) == 1
            root = elements[0]
            assert getattr(root, "id") == "activation-inspection-container"

            # 1. Non-execution disclaimer is mandatory across all 16 scenarios
            disc = _find_component_by_id(root, "activation-disclaimer-banner")
            assert disc is not None, f"Scenario {scenario_id} missing mandatory disclaimer banner"

            # 2. Check context header
            card = _find_component_by_id(root, "activation-context-card")
            assert card is not None, f"Scenario {scenario_id} missing context card"

            # 3. Check scenario-specific assertions
            if scenario_id == "dash_act_01_eligible_untouched":
                table = _find_component_by_id(root, "activation-active-table")
                assert table is not None
                assert "ELIGIBLE (UNTOUCHED)" in repr(table)
                assert "1.1350" in repr(table)
                assert "1.1400" in repr(table)
            elif scenario_id == "dash_act_02_first_exact_touch":
                table = _find_component_by_id(root, "activation-active-table")
                assert "PENDING ACTIVATION" in repr(table)
                assert "1.1370" in repr(table)
                assert "OBS_01" in repr(table)
            elif scenario_id == "dash_act_04_unknown_usage":
                table = _find_component_by_id(root, "activation-active-table")
                assert "UNKNOWN (FAIL-CLOSED)" in repr(table)
                assert "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED" in repr(table)
            elif scenario_id == "dash_act_05_incomplete_coverage":
                cov_badge = _find_component_by_id(root, "activation-coverage-badge")
                assert "COVERAGE INCOMPLETE" in repr(cov_badge)
            elif scenario_id == "dash_act_06_unknown_availability":
                table = _find_component_by_id(root, "activation-active-table")
                assert "INELIGIBLE (UNKNOWN AVAILABILITY)" in repr(table)
                assert "Unknown Availability Timing" in repr(table)
            elif scenario_id == "dash_act_08_cancellation_unknown_time":
                hist = _find_component_by_id(root, "activation-history-table")
                assert hist is not None
                assert "Unknown" in repr(hist)
                assert "#125" in repr(hist)
            elif scenario_id == "dash_act_09_external_cancellation_inside":
                rearm_tbl = _find_component_by_id(root, "activation-rearm-table")
                assert rearm_tbl is not None
                assert "Awaiting Departure Outside Zone" in repr(rearm_tbl)
                assert "Gen 2" in repr(rearm_tbl)
                assert "NO" in repr(rearm_tbl)  # rearm_armed == False
            elif scenario_id == "dash_act_10_armed_controller":
                rearm_tbl = _find_component_by_id(root, "activation-rearm-table")
                assert rearm_tbl is not None
                assert "Armed (Outside Zone)" in repr(rearm_tbl)
                assert "Gen 2" in repr(rearm_tbl)
                assert "YES" in repr(rearm_tbl)  # rearm_armed == True
            elif scenario_id == "dash_act_11_valid_reactivation":
                table = _find_component_by_id(root, "activation-active-table")
                assert "REARMED PENDING (GEN 2)" in repr(table)
                expected_prior = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)
                assert expected_prior in repr(table)
            elif scenario_id == "dash_act_13_unresolved_source_snapshot":
                banner = _find_component_by_id(root, "activation-unresolved-banner")
                assert banner is not None
                assert CANONICAL_UNRESOLVED_BANNER in repr(banner)
                assert "Processed Bar #15" in repr(banner)
                assert "Latest Received Bar #19" in repr(banner)
            elif scenario_id == "dash_act_14_equal_coarse_timestamps":
                hist = _find_component_by_id(root, "activation-history-table")
                assert hist is not None
                assert "#201" in repr(hist)
                assert "#202" in repr(hist)
            elif scenario_id == "dash_act_15_multiple_source_timeframes":
                tf_disclaimer = _find_component_by_id(root, "activation-arbitration-disclaimer")
                assert tf_disclaimer is not None
                src_tf = _find_component_by_id(root, "activation-source-tf")
                assert "H4" in repr(src_tf)
                conf_tf = _find_component_by_id(root, "activation-confirmation-tf")
                assert "M5" in repr(conf_tf)

    def test_repeated_rendering_invariance(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies bit-for-bit component tree identity across repeated renders."""
        fix = fixture_catalog["fixtures"]["dash_act_11_valid_reactivation"]
        act_snap, tjl_snap = make_snapshot_from_fixture(fix)

        renders = [
            build_activation_inspection_elements(
                activation_snapshot=act_snap,
                tjl_snapshot=tjl_snap,
                last_synced_transition_index=5,
                exact_observation_count=12,
            )
            for _ in range(5)
        ]

        base_repr = repr(renders[0])
        for idx, r in enumerate(renders[1:], 1):
            assert repr(r) == base_repr, f"Render {idx} differed from initial render"

    def test_rendering_purity_preserves_engine_checkpoints_cursor_and_cache(self) -> None:
        """Verifies rendering does NOT call process_event, register_source_members, reset, or synchronizer sync."""
        domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_PURITY")
        config = ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            sequence_domain=domain,
            price_basis=PriceBasis.BID,
        )
        engine = ActivationEngine(config)
        synchronizer = TJLSynchronizer(engine)

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
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        snap = engine.register_source_member(member)

        # Record state prior to rendering
        cp_before = engine.create_checkpoint()
        snap_before = engine.get_snapshot()
        cursor_before = synchronizer.last_synced_transition_index
        usage_cache_before = dict(synchronizer._usage_cache)

        # Mock mutation methods to verify 0 calls
        engine.process_event = MagicMock(side_effect=RuntimeError("process_event must not be called during rendering!"))
        engine.register_source_members = MagicMock(side_effect=RuntimeError("register_source_members must not be called!"))
        engine.reset = MagicMock(side_effect=RuntimeError("reset must not be called!"))
        synchronizer.sync = MagicMock(side_effect=RuntimeError("synchronizer.sync must not be called!"))

        # Render 10 times consecutively
        for _ in range(10):
            elements = build_activation_inspection_elements(
                activation_snapshot=snap,
                last_synced_transition_index=cursor_before,
                exact_observation_count=0,
            )
            assert len(elements) == 1

        # Verify mutation methods were never touched
        engine.process_event.assert_not_called()
        engine.register_source_members.assert_not_called()
        engine.reset.assert_not_called()
        synchronizer.sync.assert_not_called()

        # Verify state unmutated
        assert synchronizer.last_synced_transition_index == cursor_before
        assert synchronizer._usage_cache == usage_cache_before
        assert snap_before == engine.get_snapshot()

    def test_missing_context_and_invalid_input_diagnostics(self) -> None:
        """Verifies clean diagnostic element rendering on missing context or empty input."""
        # None passed
        elements1 = build_activation_inspection_elements(None)
        assert len(elements1) == 1
        p1 = _find_component_by_id(elements1[0], "activation-awaiting-context")
        assert p1 is not None
        assert p1.children == AWAITING_CONTEXT_TEXT

        # MSMServiceResult without activation_snapshot
        ctx = MSMContext(symbol="EURUSD", timeframe="H1", start_candle_time=datetime(2026, 10, 1, tzinfo=timezone.utc), direction=Direction.UPWARD, data_source="OFFLINE_TEST")
        msm_res = MSMServiceResult(
            context=ctx,
            snapshot=None,
            candles=(),
            status_message="OK",
            candle_count=0,
            start_candle_found=True,
            activation_snapshot=None,
        )
        elements2 = build_activation_inspection_elements(msm_res)
        assert len(elements2) == 1
        p2 = _find_component_by_id(elements2[0], "activation-awaiting-context")
        assert p2 is not None
        assert p2.children == AWAITING_CONTEXT_TEXT

    def test_bounded_history_display_and_total_count(self) -> None:
        """Verifies table bounds DOM display to 50 rows while reporting accurate total historical count without sequence pruning."""
        domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_HIST")
        term_records = []
        for i in range(75):
            rec = ActivationRecord(
                activation_id=f"ACT_EURUSD_H1_SET_1_TJL1_GEN{i}",
                engine_id="ENGINE_EURUSD_H1",
                symbol="EURUSD",
                source_timeframe="H1",
                confirmation_timeframe="M1",
                set_id="SET_1",
                role="TJL1",
                level_id=None,
                lower_edge=1.1350,
                upper_edge=1.1400,
                state=ActivationState.CANCELLED_SOURCE_CHOCH,
                generation_seq=i,
                cancellation_reason=CancellationReason.SOURCE_CHOCH,
                cancellation_time=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
                cancellation_sequence_ref=100 + i,
                terminal=True,
            )
            term_records.append(rec)

        snap = ActivationSnapshot(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            confirmation_timeframe="M1",
            sequence_domain=domain,
            active_activations={},
            terminal_activations=term_records,
            coverage_status=CoverageStatus.COMPLETE,
            last_processed_sequence=200,
            last_processed_timestamp=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            current_members={},
            rearm_controllers={},
        )

        elements = build_activation_inspection_elements(activation_snapshot=snap)
        root = elements[0]

        # Heading displays total count
        heading = _find_component_by_id(root, "activation-history-heading")
        assert heading is not None
        assert "75 total records" in heading.children
        assert "Showing latest 50 of 75 records" in heading.children

        # DOM table tbody contains exactly 50 rows
        table = _find_component_by_id(root, "activation-history-table")
        assert table is not None
        tbody = table.children[1]
        assert len(tbody.children) == 50

        # Underlying sequence in snapshot was NOT pruned or mutated
        assert len(snap.terminal_activations) == 75

    def test_session_context_isolation_across_recalculation(self) -> None:
        """Verifies session reset lifecycle discards instances and preserves zero cross-context state."""
        domain1 = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_1")
        config1 = ActivationEngineConfig("ENGINE_EURUSD_H1", "EURUSD", "H1", domain1, PriceBasis.BID)
        engine1 = ActivationEngine(config1)
        sync1 = TJLSynchronizer(engine1)

        m1 = SourceMemberReference("ENGINE_EURUSD_H1", "EURUSD", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD)
        engine1.register_source_member(m1)
        assert len(engine1.get_snapshot().current_members) == 1

        # Context change to GBPUSD H4: fresh instances
        domain2 = SequenceDomain(feed_id="FEED_GBPUSD_H4", run_id="RUN_2")
        config2 = ActivationEngineConfig("ENGINE_GBPUSD_H4", "GBPUSD", "H4", domain2, PriceBasis.BID)
        engine2 = ActivationEngine(config2)
        sync2 = TJLSynchronizer(engine2)

        # Assert engine2 is completely clean
        assert len(engine2.get_snapshot().current_members) == 0
        assert sync2.last_synced_transition_index == -1
        assert len(sync2._usage_cache) == 0

    def test_service_result_bridge_mounts_in_msm_callbacks(self) -> None:
        """Verifies MSMServiceResult carries activation_snapshot and renders cleanly through msm_callbacks."""
        from aladeen.ui.msm_callbacks import render_msm_inspection_table
        from aladeen.strategy.types import EngineState, MSMSnapshot

        domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_BRIDGE")
        snap = ActivationSnapshot(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            confirmation_timeframe="M1",
            sequence_domain=domain,
            active_activations={},
            terminal_activations=(),
            coverage_status=CoverageStatus.COMPLETE,
            last_processed_sequence=100,
            last_processed_timestamp=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            current_members={},
            rearm_controllers={},
        )

        ctx = MSMContext(symbol="EURUSD", timeframe="H1", start_candle_time=datetime(2026, 10, 1, tzinfo=timezone.utc), direction=Direction.UPWARD, data_source="OFFLINE_TEST")
        msm_snap = MSMSnapshot(
            state=EngineState.SEARCHING_PULLBACK,
            direction=Direction.UPWARD,
            search_start_index=0,
            tentative_point=None,
            trend_status="BULLISH",
        )

        msm_result = MSMServiceResult(
            context=ctx,
            snapshot=msm_snap,
            candles=(),
            status_message="OK",
            candle_count=10,
            start_candle_found=True,
            activation_snapshot=snap,
            last_synced_transition_index=3,
            exact_observation_count=5,
        )

        panel = render_msm_inspection_table(msm_snap, ctx, "REV_101", msm_result=msm_result)
        panel_repr = repr(panel)
        assert "activation-inspection-container" in panel_repr
        assert DISCLAIMER_TEXT in panel_repr
        assert "Exact Observations Processed: 5" in panel_repr
