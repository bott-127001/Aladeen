"""Automated integrity validation for Activation Read-Only Dashboard acceptance fixtures.

Validates:
1. Schema, authorities, version, and non-execution disclaimer.
2. Complete inventory of all 16 required dashboard acceptance scenarios.
3. Evidence category compliance: strictly one of {"synthetic", "engine-derived", "candle-pipeline-derived"}.
4. Structural completeness across all 8 required display groups (G1-G8).
5. Valid sequence domain: feed_id and run_id present; domain_id absent.
6. Valid domain vocabulary: CoverageStatus strictly in {"COMPLETE", "INCOMPLETE", "UNCERTAIN"}.
7. Non-actionability invariant: is_actionable is strictly False across all scenarios.
8. Raw domain blocked reason alignment: UNKNOWN_AVAILABILITY_TIMING.
9. Delineation between frozen authoritative processed bars and latest received bars with canonical banner.
10. Execution status labeling: "specified; not yet executed through the presentation implementation".

Note:
This suite validates the requirements-phase fixture data contract only.
It does NOT claim executable UI integration or DOM coverage.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from aladeen.strategy.activation_types import (
    ActivationState,
    CoverageStatus,
    Direction,
    ExternalCommitEvent,
    PriceBasis,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
    format_activation_id,
    format_member_key,
)
from aladeen.strategy.activation_engine import (
    ActivationEngine,
    ActivationEngineConfig,
    ExactPricePrint,
    SequenceDomain,
    SourceMemberReference,
)


EXPECTED_SCENARIOS = [
    "dash_act_01_eligible_untouched",
    "dash_act_02_first_exact_touch",
    "dash_act_03_repeated_touch",
    "dash_act_04_unknown_usage",
    "dash_act_05_incomplete_coverage",
    "dash_act_06_unknown_availability",
    "dash_act_07_source_cancellation",
    "dash_act_08_cancellation_unknown_time",
    "dash_act_09_external_cancellation_inside",
    "dash_act_10_armed_controller",
    "dash_act_11_valid_reactivation",
    "dash_act_12_successor_set_persistent_level",
    "dash_act_13_unresolved_source_snapshot",
    "dash_act_14_equal_coarse_timestamps",
    "dash_act_15_multiple_source_timeframes",
    "dash_act_16_repeated_rendering",
]

ALLOWED_CATEGORIES = frozenset({"synthetic", "engine-derived", "candle-pipeline-derived"})
VALID_COVERAGE_STATUSES = frozenset({e.value for e in CoverageStatus})
EXPECTED_EXECUTION_STATUS = "specified; not yet executed through the presentation implementation"
CANONICAL_UNRESOLVED_BANNER = "LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"

REQUIRED_DISPLAY_GROUPS = [
    "context",
    "membership",
    "active_activations",
    "evidence_gating",
    "cancellation",
    "rearm_controllers",
    "terminal_history",
    "synchronization",
]


@pytest.fixture(scope="module")
def fixture_catalog() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "activation_dashboard_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestActivationDashboardFixtureIntegrity:
    """Rigorous integrity validation of Activation Dashboard acceptance fixtures."""

    def test_schema_and_metadata(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies top-level fixture metadata, authorities, and non-execution disclaimer."""
        assert fixture_catalog.get("version") == "1.4"
        assert len(fixture_catalog.get("authorities", [])) >= 3

        disclaimer = fixture_catalog.get("disclaimer", "")
        assert "FIXTURE INTEGRITY TEST ONLY" in disclaimer
        assert "Does not claim executable UI integration" in disclaimer

        categories = set(fixture_catalog.get("supported_evidence_categories", []))
        assert categories == ALLOWED_CATEGORIES

    def test_all_fixture_member_keys_canonical_format(self, fixture_catalog: Dict[str, Any]) -> None:
        """Validates that every member key across all fixtures adheres strictly to format_member_key().

        Verifies:
        1. All member keys start with 'MK[' length-prefixed format.
        2. Membership member_keys match format_member_key(set_id, role).
        3. Active activations, controllers, and terminal history keys match canonical format.
        4. Joins across membership, active activations, and controllers are consistent.
        """
        for scenario_id, data in fixture_catalog["fixtures"].items():
            inputs = data["presentation_inputs"]
            membership_keys = set()
            for m in inputs.get("membership", []):
                mk = m.get("member_key")
                expected_mk = format_member_key(m["set_id"], m["role"])
                assert mk == expected_mk, f"Scenario {scenario_id} membership key mismatch: {mk} vs {expected_mk}"
                assert mk.startswith("MK["), f"Scenario {scenario_id} membership key {mk} missing MK prefix"
                membership_keys.add(mk)

            for act in inputs.get("active_activations", []):
                mk = act["member_key"]
                assert mk.startswith("MK["), f"Scenario {scenario_id} active activation member_key {mk} missing MK prefix"
                if membership_keys:
                    assert mk in membership_keys, f"Scenario {scenario_id} active activation key {mk} not in membership"

            for ctrl in inputs.get("rearm_controllers", []):
                mk = ctrl["member_key"]
                assert mk.startswith("MK["), f"Scenario {scenario_id} controller member_key {mk} missing MK prefix"
                if membership_keys:
                    assert mk in membership_keys, f"Scenario {scenario_id} controller key {mk} not in membership"

            for term in inputs.get("terminal_history", []):
                mk = term["member_key"]
                assert mk.startswith("MK["), f"Scenario {scenario_id} terminal member_key {mk} missing MK prefix"

    def test_scenario_inventory_completeness(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies exactly all 16 required scenario IDs exist in the catalog."""
        fixtures = fixture_catalog["fixtures"]
        assert len(fixtures) == 16
        for scenario_id in EXPECTED_SCENARIOS:
            assert scenario_id in fixtures, f"Missing required scenario: {scenario_id}"

    def test_evidence_categories_and_execution_status(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies valid categories, construction procedures, and requirements execution status."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            cat = data.get("evidence_category")
            assert cat in ALLOWED_CATEGORIES, (
                f"Scenario {scenario_id} has invalid category {cat!r}; must be in {ALLOWED_CATEGORIES}"
            )
            assert data.get("construction_procedure"), f"Scenario {scenario_id} missing construction_procedure"
            assert data.get("execution_status") == EXPECTED_EXECUTION_STATUS, (
                f"Scenario {scenario_id} execution_status must be {EXPECTED_EXECUTION_STATUS!r}"
            )

    def test_display_groups_present_in_inputs(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies presentation_inputs contains all 8 required display groups."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            inputs = data.get("presentation_inputs")
            assert isinstance(inputs, dict), f"Scenario {scenario_id} missing presentation_inputs dict"
            for grp in REQUIRED_DISPLAY_GROUPS:
                assert grp in inputs, f"Scenario {scenario_id} missing display group {grp!r}"

    def test_strict_non_actionability_invariant(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies is_actionable is strictly False across all expected views and assertions."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            expected = data.get("expected_view", {})
            assertions = data.get("assertions", {})
            assert expected.get("is_actionable") is False, (
                f"Scenario {scenario_id} expected_view.is_actionable must be strictly False"
            )
            assert assertions.get("is_actionable") is False, (
                f"Scenario {scenario_id} assertions.is_actionable must be strictly False"
            )

    def test_context_sequence_domain_and_timeframe_mappings(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies sequence domain fields (feed_id, run_id) and timeframe mapping."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            ctx = data["presentation_inputs"]["context"]
            assert ctx.get("engine_id")
            assert ctx.get("symbol")
            assert ctx.get("source_timeframe")

            # Sequence domain: feed_id and run_id must be explicit; domain_id must NOT be present
            seq_dom = ctx.get("sequence_domain", {})
            assert "feed_id" in seq_dom, f"Scenario {scenario_id} missing feed_id in sequence_domain"
            assert "run_id" in seq_dom, f"Scenario {scenario_id} missing run_id in sequence_domain"
            assert "domain_id" not in seq_dom, f"Scenario {scenario_id} contains non-domain domain_id"

            src_tf = ctx["source_timeframe"]
            conf_tf = ctx.get("confirmation_timeframe")
            expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(src_tf)
            if expected_conf_tf is not None:
                assert conf_tf == expected_conf_tf, (
                    f"Scenario {scenario_id} timeframe mapping mismatch: {src_tf} -> {conf_tf}, expected {expected_conf_tf}"
                )

    def test_coverage_status_valid_domain_enum(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies all coverage status values belong strictly to valid CoverageStatus enum values."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            gating = data["presentation_inputs"]["evidence_gating"]
            cov = gating.get("coverage_status")
            assert cov in VALID_COVERAGE_STATUSES, (
                f"Scenario {scenario_id} has invalid coverage_status {cov!r}; must be in {VALID_COVERAGE_STATUSES}"
            )

    def test_scenario_specific_assertion_contracts(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies precise assertions for key individual scenario contracts."""
        fixtures = fixture_catalog["fixtures"]

        # Scenario 1: Untouched
        sc1 = fixtures["dash_act_01_eligible_untouched"]
        assert sc1["assertions"]["has_first_touch_claim"] is False
        assert sc1["expected_view"]["first_touch_display"] == "—"

        # Scenario 2: First Touch
        sc2 = fixtures["dash_act_02_first_exact_touch"]
        assert sc2["assertions"]["has_first_touch_claim"] is True
        assert sc2["assertions"]["trigger_observation_id"] == "OBS_01"
        assert sc2["assertions"]["first_touch_price_exact"] == 1.1370

        # Scenario 3: Repeated Touch
        sc3 = fixtures["dash_act_03_repeated_touch"]
        assert sc3["assertions"]["first_touch_time_preserved"] == "2026-10-02T08:15:00+00:00"
        assert sc3["assertions"]["trigger_observation_id_preserved"] == "OBS_01"

        # Scenario 4: Preserved pending provenance under usage uncertainty
        sc4 = fixtures["dash_act_04_unknown_usage"]
        assert sc4["assertions"]["has_preserved_pending_provenance"] is True
        assert sc4["assertions"]["usage_evidence_status"] == "UNKNOWN"
        assert sc4["assertions"]["blocked_reason"] == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"
        assert sc4["assertions"]["initial_unknown_usage_blocks_touch"] is True

        # Scenario 5: Coverage Incomplete / Uncertain
        sc5 = fixtures["dash_act_05_incomplete_coverage"]
        assert sc5["assertions"]["coverage_status_valid_domain"] is True
        assert sc5["assertions"]["coverage_status"] in ("INCOMPLETE", "UNCERTAIN")
        assert sc5["assertions"]["alternate_coverage_status"] in ("INCOMPLETE", "UNCERTAIN")

        # Scenario 6: Unknown Availability blocks activation with raw domain reason
        sc6 = fixtures["dash_act_06_unknown_availability"]
        assert sc6["assertions"]["raw_blocked_reason"] == "UNKNOWN_AVAILABILITY_TIMING"
        assert sc6["expected_view"]["raw_blocked_reason_display"] == "UNKNOWN_AVAILABILITY_TIMING"
        assert sc6["assertions"]["inferred_time_used"] is False

        # Scenario 7: Source Cancellation
        sc7 = fixtures["dash_act_07_source_cancellation"]
        assert sc7["assertions"]["active_member_count"] == 0
        assert sc7["assertions"]["terminal_history_count"] == 1

        # Scenario 8: Cancellation with unknown timestamp
        sc8 = fixtures["dash_act_08_cancellation_unknown_time"]
        assert sc8["assertions"]["timestamp_shown_as_unknown"] is True
        assert sc8["assertions"]["sequence_shown_separately"] is True
        assert sc8["expected_view"]["cancellation_time_display"] == "Unknown"
        assert sc8["expected_view"]["sequence_ref_display"] == "#125"

        # Scenario 9: Inside cancellation -> awaiting departure
        sc9 = fixtures["dash_act_09_external_cancellation_inside"]
        assert sc9["assertions"]["rearm_armed"] is False
        assert sc9["assertions"]["rearm_controller_present"] is True
        assert sc9["assertions"]["controller_generation_seq"] == 2
        assert sc9["assertions"]["linked_terminal_generation_seq"] == 1
        assert sc9["assertions"]["generation_consistency"] is True
        assert sc9["presentation_inputs"]["rearm_controllers"][0]["generation_seq"] == 2
        assert (
            sc9["presentation_inputs"]["rearm_controllers"][0]["generation_seq"]
            == sc9["presentation_inputs"]["terminal_history"][0]["generation_seq"] + 1
        )

        # Scenario 10: Armed controller
        sc10 = fixtures["dash_act_10_armed_controller"]
        assert sc10["assertions"]["rearm_armed"] is True
        assert sc10["assertions"]["active_activations_count"] == 0
        assert sc10["assertions"]["controller_generation_seq"] == 2
        assert sc10["assertions"]["linked_terminal_generation_seq"] == 1
        assert sc10["assertions"]["generation_consistency"] is True
        assert sc10["presentation_inputs"]["rearm_controllers"][0]["generation_seq"] == 2
        assert (
            sc10["presentation_inputs"]["rearm_controllers"][0]["generation_seq"]
            == sc10["presentation_inputs"]["terminal_history"][0]["generation_seq"] + 1
        )

        # Scenario 11: Valid reactivation
        sc11 = fixtures["dash_act_11_valid_reactivation"]
        expected_prior_id = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)
        expected_active_id = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 2)
        assert sc11["assertions"]["prior_activation_id"] == expected_prior_id
        assert sc11["expected_view"]["prior_activation_display"] == expected_prior_id
        assert sc11["presentation_inputs"]["active_activations"][0]["activation_id"] == expected_active_id
        assert sc11["assertions"]["generation_seq"] == 2
        assert sc11["assertions"]["canonical_id_formatter_match"] is True

        # Scenario 12: Successor set
        sc12 = fixtures["dash_act_12_successor_set_persistent_level"]
        assert sc12["assertions"]["active_set_id"] == "SET_2"
        assert sc12["assertions"]["distinct_set_identity"] is True
        assert sc12["assertions"]["level_identity_continuous"] is True

        # Scenario 13: Unresolved source snapshot
        sc13 = fixtures["dash_act_13_unresolved_source_snapshot"]
        assert sc13["assertions"]["is_unresolved"] is True
        assert sc13["assertions"]["canonical_banner_text"] == CANONICAL_UNRESOLVED_BANNER
        assert sc13["expected_view"]["unresolved_banner_text"] == CANONICAL_UNRESOLVED_BANNER
        assert sc13["assertions"]["processed_bar_index"] == 15
        assert sc13["assertions"]["received_bar_index"] == 19

        # Scenario 14: Equal coarse timestamps
        sc14 = fixtures["dash_act_14_equal_coarse_timestamps"]
        assert sc14["assertions"]["terminal_history_count"] == 2
        assert sc14["assertions"]["distinct_sequences"] == [201, 202]

        # Scenario 15: Multiple timeframe mapping
        sc15 = fixtures["dash_act_15_multiple_source_timeframes"]
        assert sc15["assertions"]["source_timeframe"] == "H4"
        assert sc15["assertions"]["confirmation_timeframe"] == "M5"
        assert sc15["assertions"]["cross_timeframe_arbitration"] is False

        # Scenario 16: Repeated rendering invariance
        sc16 = fixtures["dash_act_16_repeated_rendering"]
        assert sc16["assertions"]["render_invariant"] is True
        assert sc16["assertions"]["component_tree_hash_identical"] is True
        assert sc16["assertions"]["engine_state_unmutated"] is True
        assert sc16["assertions"]["synchronizer_cursor_unmutated"] is True

    def test_canonical_identifier_and_key_formatters(self) -> None:
        """Validates canonical formatting functions for activation IDs and member keys."""
        mk1 = format_member_key("SET_1", "TJL1")
        assert mk1 == "MK[5:SET_1][4:TJL1]"
        mk2 = format_member_key("SET_1", "TJL2_A_PLUS")
        assert mk2 == "MK[5:SET_1][11:TJL2_A_PLUS]"

        aid1 = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)
        assert aid1 == "ACT_G01[16:ENGINE_EURUSD_H1][2:H1][6:EURUSD][5:SET_1][4:TJL1]"
        aid2 = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 2)
        assert aid2 == "ACT_G02[16:ENGINE_EURUSD_H1][2:H1][6:EURUSD][5:SET_1][4:TJL1]"

    def test_requirements_domain_consistency_against_engine_types(self) -> None:
        """Verifies requirements-phase domain invariants and full lifecycle through accepted engine.

        Validates:
        1. Untouched member with default usage defaults to UNKNOWN -> INACTIVE_INELIGIBLE
           with blocked_reason == 'USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED'.
        2. Initial UNKNOWN usage fails closed on price print (produces 0 activations).
        3. Explicit UNUSED evidence transitions untouched member to INACTIVE_ELIGIBLE.
        4. First in-zone touch produces PENDING_ACTIVATION (generation 1).
        5. Preserved pending uncertainty follows UNUSED -> touch -> UNKNOWN sequence.
        6. Full lifecycle reactivation execution:
           External commit cancels record to CANCELLED_EXTERNAL_ENTRY and creates RearmController(generation_seq=2).
           Outside departure print arms controller (OUT_OF_ZONE_ARMED, rearm_armed=True).
           In-zone retouch print activates generation 2 (REARMED_PENDING, prior_activation_id=gen1_id, generation_seq=2).
        """
        domain = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_DOM_CHECK")
        config = ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="EURUSD",
            source_timeframe="H1",
            sequence_domain=domain,
            price_basis=PriceBasis.BID,
        )
        engine = ActivationEngine(config)

        # 1. Untouched member with default usage is INACTIVE_INELIGIBLE
        m_default = SourceMemberReference(
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
        )
        assert m_default.usage_evidence_status == UsageEvidenceStatus.UNKNOWN
        snap1 = engine.register_source_member(m_default)
        rec1 = snap1.active_activations[m_default.member_key]
        assert rec1.state == ActivationState.INACTIVE_INELIGIBLE
        assert rec1.blocked_reason == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"

        # 2. Initial UNKNOWN usage fails closed on price print (0 pending activations)
        print_in_zone = ExactPricePrint(
            observation_id="OBS_01",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=101,
        )
        snap2 = engine.process_event(print_in_zone)
        rec2 = snap2.active_activations[m_default.member_key]
        assert rec2.state == ActivationState.INACTIVE_INELIGIBLE
        assert rec2.first_touch_time is None
        assert rec2.trigger_observation_id is None

        # 3. Explicit UNUSED evidence transitions to INACTIVE_ELIGIBLE
        engine.reset()
        m_unused = SourceMemberReference(
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
        snap3 = engine.register_source_member(m_unused)
        rec3 = snap3.active_activations[m_unused.member_key]
        assert rec3.state == ActivationState.INACTIVE_ELIGIBLE
        assert rec3.blocked_reason is None

        # 4. Touch transitions to PENDING_ACTIVATION (generation 1)
        snap4 = engine.process_event(print_in_zone)
        rec4 = snap4.active_activations[m_unused.member_key]
        assert rec4.state == ActivationState.PENDING_ACTIVATION
        assert rec4.first_touch_price == 1.1370
        assert rec4.trigger_observation_id == "OBS_01"
        assert rec4.generation_seq == 1
        gen1_act_id = rec4.activation_id

        # 5. Subsequent UNKNOWN usage preserves pending provenance while gating
        m_unknown = SourceMemberReference(
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
            usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
        )
        snap5 = engine.register_source_member(m_unknown)
        rec5 = snap5.active_activations[m_unknown.member_key]
        assert rec5.state == ActivationState.PENDING_ACTIVATION
        assert rec5.activation_id == gen1_act_id
        assert rec5.first_touch_price == 1.1370
        assert rec5.generation_seq == 1
        assert rec5.blocked_reason == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"
        assert rec5.usage_evidence_status == UsageEvidenceStatus.UNKNOWN

        # 6. Full lifecycle reactivation execution through engine:
        # Restore UNUSED usage
        engine.register_source_member(m_unused)

        # External commit cancels level while inside zone
        commit_evt = ExternalCommitEvent(
            event_id="COMMIT_01",
            timestamp=datetime(2026, 10, 2, 9, 45, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=130,
            winning_engine_id="ENGINE_OTHER",
            winning_set_id="SET_OTHER",
            winning_role="TJL1",
            target_symbol="EURUSD",
            target_source_timeframe="H1",
        )
        snap_cancel = engine.process_event(commit_evt)
        assert m_unused.member_key not in snap_cancel.active_activations
        assert len(snap_cancel.terminal_activations) == 1
        term_rec = snap_cancel.terminal_activations[0]
        assert term_rec.activation_id == gen1_act_id
        assert term_rec.generation_seq == 1
        assert term_rec.state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # RearmController initialized with generation_seq = 2 (cancelled_record.generation_seq + 1)
        ctrl = snap_cancel.rearm_controllers[m_unused.member_key]
        assert ctrl.generation_seq == 2
        assert ctrl.generation_seq == term_rec.generation_seq + 1
        assert ctrl.prior_activation_id == gen1_act_id
        assert ctrl.rearm_armed is False
        assert ctrl.state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Departure print outside zone arms controller
        print_outside = ExactPricePrint(
            observation_id="OBS_DEPART",
            price=1.1450,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=135,
        )
        snap_armed = engine.process_event(print_outside)
        ctrl_armed = snap_armed.rearm_controllers[m_unused.member_key]
        assert ctrl_armed.rearm_armed is True
        assert ctrl_armed.state == ActivationState.OUT_OF_ZONE_ARMED
        assert ctrl_armed.last_observed_position == "OUTSIDE"
        assert ctrl_armed.generation_seq == 2

        # Retouch print inside zone executes reactivation into generation 2
        print_retouch = ExactPricePrint(
            observation_id="OBS_RETOUCH",
            price=1.1375,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 10, 15, tzinfo=timezone.utc),
            sequence_domain=domain,
            sequence_ref=140,
        )
        snap_reactivated = engine.process_event(print_retouch)
        assert m_unused.member_key in snap_reactivated.active_activations
        rec_gen2 = snap_reactivated.active_activations[m_unused.member_key]
        assert rec_gen2.state == ActivationState.REARMED_PENDING
        assert rec_gen2.generation_seq == 2
        assert rec_gen2.prior_activation_id == gen1_act_id
        expected_gen2_id = format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 2)
        assert rec_gen2.activation_id == expected_gen2_id
        assert m_unused.member_key not in snap_reactivated.rearm_controllers
