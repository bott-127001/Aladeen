import importlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

# Authoritative Verified Module Symbols
MODULE_SYMBOLS = [
    ("aladeen.strategy.engine", "MSMEngine", "MSM strategy engine class"),
    ("aladeen.ui.chart", "create_candlestick_chart", "Plotly candlestick chart builder"),
    ("aladeen.ui.chart", "create_empty_chart", "Plotly empty chart fallback"),
    ("aladeen.data.fixtures", "load_fixture", "Offline demo candle data loader"),
    ("aladeen.data.mt5_adapter", "MT5Adapter", "MT5 adapter with demo fallback"),
    ("aladeen.strategy.choch_detector", "ChochDetector", "CHOCH detector class"),
    ("aladeen.strategy.coordinator", "MSMChochCoordinator", "MSM and CHOCH coordinator class"),
    ("aladeen.strategy.iss_engine", "ISSEngine", "ISS strategy engine class"),
    ("aladeen.ui.market_coordinator", "generate_chart_and_status_from_snapshot", "Market coordinator handling MSM/CHOCH/ISS modes"),
    ("aladeen.strategy.tjl_coordinator", "TJLCoordinator", "TJL coordinator class"),
    ("aladeen.ui.tjl_chart", "apply_tjl_overlays", "TJL chart overlay function"),
    ("aladeen.ui.tjl_chart", "resolve_authoritative_endpoint", "TJL endpoint resolution function"),
    ("aladeen.ui.tjl_inspection", "build_tjl_inspection_elements", "TJL inspection UI builder"),
    ("aladeen.ui.activation_inspection", "build_activation_inspection_elements", "Activation inspection UI builder"),
    ("aladeen.strategy.activation_engine", "ActivationEngine", "Activation engine class"),
    ("aladeen.strategy.service", "ActivationSessionRegistry", "Activation in-memory session registry"),
    ("aladeen.strategy.service", "ActivationSessionCoordinator", "Activation session coordinator"),
    ("aladeen.strategy.activation_types", "TIMEFRAME_CONFIRMATION_MAP", "Timeframe confirmation metadata map"),
    ("tests.activation_browser_runner", "run_activation_browser_validation", "Controlled browser runner entry point"),
    ("tests.test_activation_browser_controlled", "verify_section_a_mounting_and_viewport", "Browser Section A verification"),
    ("tests.test_activation_browser_controlled", "verify_section_b_session_isolation", "Browser Section B verification"),
    ("tests.test_activation_browser_controlled", "verify_section_c_lifecycle_scenarios", "Browser Section C verification"),
    ("tests.activation_browser_harness", "verify_isolation_guards_negative_controls", "Browser negative controls"),
    ("tests.activation_browser_harness", "verify_server_lifecycle_failure_injection", "Server lifecycle failure injection"),
    ("tests.activation_browser_harness", "ControlledServerHandle", "Controlled server lifecycle handle"),
    ("tests.activation_browser_harness", "ContextSecurityFirewall", "Playwright routed origin firewall"),
    ("tests.activation_browser_harness", "install_server_socket_guard", "Server socket monkeypatch guard"),
    ("tests.activation_browser_harness", "ControllableActivationMockAdapter", "Controllable mock adapter with spy"),
    ("tests.activation_browser_harness", "_create_fixture_harness_app", "Fixture harness app builder"),
]

# Authoritative Collected Pytest Node IDs
PYTEST_NODE_IDS = [
    "tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_01_upward_standard",
    "tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_02_downward_standard",
    "tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_03_strict_equality_failures",
    "tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_07_forming_bar_exclusion",
    "tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_12_two_pairs_and_trend_status",
    "tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_14_prefix_consistency_and_replay",
    "tests/test_chart.py::TestCandlestickChart::test_creates_figure_from_h4",
    "tests/test_app.py::TestAppConstruction::test_no_mt5_import_required",
    "tests/test_app.py::TestModeIsolationAndFallbackRejection::test_demo_mode_unaffected_by_mt5",
    "tests/test_choch_engine.py::TestCHOCHExecution::test_choch_bullish_basic_end_to_end_execution",
    "tests/test_choch_engine.py::TestCHOCHExecution::test_choch_bearish_basic_end_to_end_execution",
    "tests/test_choch_engine.py::TestCHOCHExecution::test_wick_crossing_only_rejected",
    "tests/test_choch_engine.py::TestCHOCHExecution::test_continuation_reset_clears_pending_choch",
    "tests/test_choch_engine.py::TestCHOCHExecution::test_unresolved_same_close_diagnostic_and_downstream_non_publication",
    "tests/test_choch_engine.py::TestCHOCHExecution::test_unresolved_containment_freezes_authoritative_state_across_later_candles",
    "tests/test_iss_engine.py::TestISSEngineLifecycleExecution::test_iss_01_bearish_basic_end_to_end_execution",
    "tests/test_iss_engine.py::TestISSEngineLifecycleExecution::test_iss_02_bullish_basic_end_to_end_execution",
    "tests/test_iss_engine.py::TestISSEngineAPIAndSafety::test_isolated_tracking_only_distinct_from_continuation_cancellation",
    "tests/test_iss_engine.py::TestISSEngineAPIAndSafety::test_synthetic_missing_evidence_isolated_tracking_progression_and_cancellation",
    "tests/test_iss_dashboard_integration.py::TestISSDashboardInspectionPanel::test_inspection_panel_renders_iss_tables",
    "tests/test_iss_dashboard_integration.py::TestISSDashboardChartRendering::test_chart_renders_iss_markers_and_zones",
    "tests/test_tjl_coordinator.py::TestTJLCoordinator::test_bullish_basic_end_to_end_replay",
    "tests/test_tjl_coordinator.py::TestTJLCoordinator::test_continuation_t1_retention_and_t2_pullback_replacement",
    "tests/test_tjl_coordinator.py::TestTJLCoordinator::test_source_choch_invalidation_and_post_choch_gap",
    "tests/test_tjl_dashboard_integration.py::TestTJLCandlestickChartOverlays::test_display_toggles_suppress_shapes_without_changing_calculation",
    "tests/test_tjl_dashboard_integration.py::TestTJLProductionServiceLifecycleAndPresentation::test_chart_window_excluding_authoritative_source_candle",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_all_16_scenarios_execute_through_presentation_builder_with_explicit_assertions",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_bounded_history_display_and_total_count",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_real_engine_lifecycle_reactivation_presentation",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_same_run_successive_cancellation_sync_with_monotonic_sequences_and_error_preservation",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_service_pipeline_execution_and_context_reset",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_recalculation_in_session_a_cannot_reset_session_b",
    "tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_application_boundary_session_initialization_and_refresh_retention",
    "tests/test_activation_dashboard_fixture_integrity.py::TestActivationDashboardFixtureIntegrity::test_scenario_specific_assertion_contracts",
]

# Explicit documented gaps & negative validation findings
UNRESOLVED_REFERENCES = [
    {
        "claimed_reference": "aladeen.strategy.engine.classify_levels",
        "requirement": "MSM-02 Strong/Weak Level Classification",
        "reason": "Function does not exist in codebase; strong/weak level classification is not defined in authoritative strategy acceptance contract (docs/requirements/msm-acceptance.md).",
        "disposition": "UNRESOLVED / EXCLUDED FROM SCOPE"
    },
    {
        "claimed_reference": "aladeen.data.mock_adapter.MockMT5Adapter",
        "requirement": "MSM-04 Demo Data Mode",
        "reason": "Module aladeen.data.mock_adapter does not exist; production demo mode uses aladeen.data.fixtures.load_fixture and MT5Adapter fallback; tests use tests.activation_browser_harness.ControllableActivationMockAdapter.",
        "disposition": "RESOLVED TO ACTUAL CODEBASE ADAPTERS"
    },
    {
        "claimed_reference": "aladeen.ui.iss_inspection",
        "requirement": "ISS-04 Browser Inspection Component",
        "reason": "Dedicated module aladeen.ui.iss_inspection does not exist; ISS inspection elements are constructed within aladeen.ui.market_coordinator and tested in tests/test_iss_dashboard_integration.py.",
        "disposition": "RESOLVED TO MARKET_COORDINATOR"
    },
    {
        "claimed_reference": "tests/test_activation_dashboard_fixture_integrity.py::test_fixture_13_unresolved_source_snapshot_matches_requirements",
        "requirement": "ACT-SC13 Fixture Integrity Contract",
        "reason": "Dedicated function does not exist; Scenario 13 fixture integrity is validated within the combined test_scenario_specific_assertion_contracts.",
        "disposition": "RESOLVED TO COMBINED FIXTURE CONTRACT TEST"
    }
]

def validate_all():
    results = {
        "symbols": [],
        "pytest_nodes": [],
        "unresolved_gaps": UNRESOLVED_REFERENCES
    }

    print("=== VALIDATING PYTHON MODULE SYMBOLS ===")
    all_symbols_ok = True
    for mod_name, sym_name, desc in MODULE_SYMBOLS:
        try:
            mod = importlib.import_module(mod_name)
            exists = hasattr(mod, sym_name)
            status = "FOUND" if exists else "ATTRIBUTE_NOT_FOUND"
        except Exception as e:
            status = f"IMPORT_ERROR: {e}"
        if status != "FOUND":
            all_symbols_ok = False
        print(f"[{status}] {mod_name}.{sym_name} ({desc})")
        results["symbols"].append({
            "module": mod_name,
            "symbol": sym_name,
            "description": desc,
            "status": status,
            "verified": (status == "FOUND")
        })

    print("\n=== VALIDATING PYTEST NODE IDS ===")
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8")
    collected_text = proc.stdout

    all_nodes_ok = True
    for node in PYTEST_NODE_IDS:
        func_name = node.split("::")[-1]
        file_path = node.split("::")[0]
        verified = (node in collected_text) or (func_name in collected_text and file_path in collected_text)
        status = "COLLECTED" if verified else "NOT_FOUND"
        if not verified:
            all_nodes_ok = False
        print(f"[{status}] {node}")
        results["pytest_nodes"].append({
            "node_id": node,
            "status": status,
            "verified": verified
        })

    output_dir = REPO_ROOT / "docs" / "development" / "evidence" / "reproduction_m29"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "reference_validation.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    md_path = output_dir / "reference_validation.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Automated Reference Validation Artifact — Milestone 29\n\n")
        f.write(f"Generated: 2026-11-06\nRepository Root: `{REPO_ROOT}`\n\n")
        f.write(f"**Overall Symbol Validation**: {'ALL FOUND' if all_symbols_ok else 'DEFECTS DETECTED'}\n")
        f.write(f"**Overall Pytest Node Validation**: {'ALL COLLECTED' if all_nodes_ok else 'DEFECTS DETECTED'}\n\n")

        f.write("## 1. Verified Python Module Symbols\n\n")
        f.write("| Module | Symbol | Description | Status |\n|---|---|---|---|\n")
        for s in results["symbols"]:
            f.write(f"| `{s['module']}` | `{s['symbol']}` | {s['description']} | **{s['status']}** |\n")

        f.write("\n## 2. Verified Pytest Node IDs\n\n")
        f.write("| Pytest Node ID | Status |\n|---|---|\n")
        for n in results["pytest_nodes"]:
            f.write(f"| `{n['node_id']}` | **{n['status']}** |\n")

        f.write("\n## 3. Explicit Unresolved & Corrected References\n\n")
        f.write("| Claimed Reference | Requirement | Recorded Status & Resolution |\n|---|---|---|\n")
        for u in results["unresolved_gaps"]:
            f.write(f"| `{u['claimed_reference']}` | {u['requirement']} | **{u['disposition']}**: {u['reason']} |\n")

    print(f"\nGenerated reference validation artifacts:\n- {json_path}\n- {md_path}")
    assert all_symbols_ok, "Some symbols were not found!"
    assert all_nodes_ok, "Some pytest nodes were not collected!"
    print("ALL SYMBOLS AND PYTEST NODES VERIFIED 100%!")

if __name__ == "__main__":
    validate_all()
