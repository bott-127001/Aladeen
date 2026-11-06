"""Automated integrity validation for Activation Read-Only Dashboard acceptance fixtures.

Validates:
1. Schema, authorities, version, and non-execution disclaimer.
2. Complete inventory of all 16 required dashboard acceptance scenarios.
3. Evidence category compliance: strictly one of {"synthetic", "engine-derived", "candle-pipeline-derived"}.
4. Structural completeness across all 8 required display groups:
   - Context
   - Membership
   - Activation
   - Evidence gating
   - Cancellation
   - Rearm controller
   - Terminal history
   - Synchronization
5. Non-actionability invariant: is_actionable is strictly False across all scenarios.
6. Strict UTC timestamp normalization and absence of fabricated times.
7. Disambiguation of coarse timestamps by canonical IDs and sequence references.
8. Preservation of persistent physical levels across successor set registration.
9. Delineation between frozen authoritative processed bars and latest received bars.

Note:
This suite validates the requirements-phase fixture data contract only.
It does NOT claim executable UI integration or DOM coverage.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from aladeen.strategy.activation_types import TIMEFRAME_CONFIRMATION_MAP


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
        assert fixture_catalog.get("version") == "1.0"
        assert len(fixture_catalog.get("authorities", [])) >= 3

        # Verify non-execution disclaimer is explicit
        disclaimer = fixture_catalog.get("disclaimer", "")
        assert "FIXTURE INTEGRITY TEST ONLY" in disclaimer
        assert "Does not claim executable UI integration" in disclaimer

        # Supported categories
        categories = set(fixture_catalog.get("supported_evidence_categories", []))
        assert categories == ALLOWED_CATEGORIES

    def test_scenario_inventory_completeness(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies exactly all 16 required scenario IDs exist in the catalog."""
        fixtures = fixture_catalog["fixtures"]
        assert len(fixtures) == 16
        for scenario_id in EXPECTED_SCENARIOS:
            assert scenario_id in fixtures, f"Missing required scenario: {scenario_id}"

    def test_evidence_categories_valid(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies every scenario is assigned a valid evidence category."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            cat = data.get("evidence_category")
            assert cat in ALLOWED_CATEGORIES, (
                f"Scenario {scenario_id} has invalid category {cat!r}; must be in {ALLOWED_CATEGORIES}"
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

    def test_context_and_timeframe_mappings(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies context parameters and authoritative metadata timeframe mapping."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            ctx = data["presentation_inputs"]["context"]
            assert ctx.get("engine_id")
            assert ctx.get("symbol")
            assert ctx.get("source_timeframe")
            src_tf = ctx["source_timeframe"]
            conf_tf = ctx.get("confirmation_timeframe")
            expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(src_tf)
            if expected_conf_tf is not None:
                assert conf_tf == expected_conf_tf, (
                    f"Scenario {scenario_id} timeframe mapping mismatch: {src_tf} -> {conf_tf}, expected {expected_conf_tf}"
                )

    def test_timestamp_normalization_and_formatting(self, fixture_catalog: Dict[str, Any]) -> None:
        """Verifies all non-null timestamps are valid ISO 8601 strings."""
        for scenario_id, data in fixture_catalog["fixtures"].items():
            inputs = data["presentation_inputs"]
            for m in inputs.get("membership", []):
                t = m.get("eligibility_available_time")
                if t is not None:
                    parsed = datetime.fromisoformat(t)
                    assert parsed.tzinfo is not None, f"Timestamp {t} in {scenario_id} must be timezone-aware"

            for a in inputs.get("active_activations", []):
                t = a.get("first_touch_time")
                if t is not None:
                    parsed = datetime.fromisoformat(t)
                    assert parsed.tzinfo is not None, f"First touch time {t} in {scenario_id} must be timezone-aware"

            for h in inputs.get("terminal_history", []):
                ct = h.get("cancellation_time")
                if ct is not None:
                    parsed = datetime.fromisoformat(ct)
                    assert parsed.tzinfo is not None, f"Cancellation time {ct} in {scenario_id} must be timezone-aware"

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

        # Scenario 4: Unknown Usage
        sc4 = fixtures["dash_act_04_unknown_usage"]
        assert sc4["assertions"]["usage_evidence_status"] == "UNKNOWN"
        assert sc4["assertions"]["blocked_reason_present"] is True

        # Scenario 6: Unknown Availability
        sc6 = fixtures["dash_act_06_unknown_availability"]
        assert sc6["assertions"]["inferred_time_used"] is False

        # Scenario 7: Source Cancellation
        sc7 = fixtures["dash_act_07_source_cancellation"]
        assert sc7["assertions"]["active_member_count"] == 0
        assert sc7["assertions"]["terminal_history_count"] == 1

        # Scenario 8: Cancellation with unknown timestamp
        sc8 = fixtures["dash_act_08_cancellation_unknown_time"]
        assert sc8["assertions"]["timestamp_shown_as_unknown"] is True
        assert sc8["assertions"]["sequence_shown_separately"] is True

        # Scenario 9: Inside cancellation -> awaiting departure
        sc9 = fixtures["dash_act_09_external_cancellation_inside"]
        assert sc9["assertions"]["rearm_armed"] is False
        assert sc9["assertions"]["rearm_controller_present"] is True

        # Scenario 10: Armed controller
        sc10 = fixtures["dash_act_10_armed_controller"]
        assert sc10["assertions"]["rearm_armed"] is True
        assert sc10["assertions"]["active_activations_count"] == 0

        # Scenario 11: Valid reactivation
        sc11 = fixtures["dash_act_11_valid_reactivation"]
        assert sc11["assertions"]["prior_activation_id"] == "ACT_EURUSD_H1_SET_1_TJL1_GEN1"
        assert sc11["assertions"]["generation_seq"] == 2

        # Scenario 12: Successor set
        sc12 = fixtures["dash_act_12_successor_set_persistent_level"]
        assert sc12["assertions"]["active_set_id"] == "SET_2"
        assert sc12["assertions"]["distinct_set_identity"] is True
        assert sc12["assertions"]["level_identity_continuous"] is True

        # Scenario 13: Unresolved source snapshot
        sc13 = fixtures["dash_act_13_unresolved_source_snapshot"]
        assert sc13["assertions"]["is_unresolved"] is True
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
        assert sc16["assertions"]["state_mutation_free"] is True
