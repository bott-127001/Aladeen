# Automated Reference Validation Artifact — Milestone 29

Generated: 2026-11-06
Repository Root: `D:\Downloads\TopG`

**Overall Symbol Validation**: ALL FOUND
**Overall Pytest Node Validation**: ALL COLLECTED

## 1. Verified Python Module Symbols

| Module | Symbol | Description | Status |
|---|---|---|---|
| `aladeen.strategy.engine` | `MSMEngine` | MSM strategy engine class | **FOUND** |
| `aladeen.ui.chart` | `create_candlestick_chart` | Plotly candlestick chart builder | **FOUND** |
| `aladeen.ui.chart` | `create_empty_chart` | Plotly empty chart fallback | **FOUND** |
| `aladeen.data.fixtures` | `load_fixture` | Offline demo candle data loader | **FOUND** |
| `aladeen.data.mt5_adapter` | `MT5Adapter` | MT5 adapter with demo fallback | **FOUND** |
| `aladeen.strategy.choch_detector` | `ChochDetector` | CHOCH detector class | **FOUND** |
| `aladeen.strategy.coordinator` | `MSMChochCoordinator` | MSM and CHOCH coordinator class | **FOUND** |
| `aladeen.strategy.iss_engine` | `ISSEngine` | ISS strategy engine class | **FOUND** |
| `aladeen.ui.market_coordinator` | `generate_chart_and_status_from_snapshot` | Market coordinator handling MSM/CHOCH/ISS modes | **FOUND** |
| `aladeen.strategy.tjl_coordinator` | `TJLCoordinator` | TJL coordinator class | **FOUND** |
| `aladeen.ui.tjl_chart` | `apply_tjl_overlays` | TJL chart overlay function | **FOUND** |
| `aladeen.ui.tjl_chart` | `resolve_authoritative_endpoint` | TJL endpoint resolution function | **FOUND** |
| `aladeen.ui.tjl_inspection` | `build_tjl_inspection_elements` | TJL inspection UI builder | **FOUND** |
| `aladeen.ui.activation_inspection` | `build_activation_inspection_elements` | Activation inspection UI builder | **FOUND** |
| `aladeen.strategy.activation_engine` | `ActivationEngine` | Activation engine class | **FOUND** |
| `aladeen.strategy.service` | `ActivationSessionRegistry` | Activation in-memory session registry | **FOUND** |
| `aladeen.strategy.service` | `ActivationSessionCoordinator` | Activation session coordinator | **FOUND** |
| `aladeen.strategy.activation_types` | `TIMEFRAME_CONFIRMATION_MAP` | Timeframe confirmation metadata map | **FOUND** |
| `tests.activation_browser_runner` | `run_activation_browser_validation` | Controlled browser runner entry point | **FOUND** |
| `tests.test_activation_browser_controlled` | `verify_section_a_mounting_and_viewport` | Browser Section A verification | **FOUND** |
| `tests.test_activation_browser_controlled` | `verify_section_b_session_isolation` | Browser Section B verification | **FOUND** |
| `tests.test_activation_browser_controlled` | `verify_section_c_lifecycle_scenarios` | Browser Section C verification | **FOUND** |
| `tests.activation_browser_harness` | `verify_isolation_guards_negative_controls` | Browser negative controls | **FOUND** |
| `tests.activation_browser_harness` | `verify_server_lifecycle_failure_injection` | Server lifecycle failure injection | **FOUND** |
| `tests.activation_browser_harness` | `ControlledServerHandle` | Controlled server lifecycle handle | **FOUND** |
| `tests.activation_browser_harness` | `ContextSecurityFirewall` | Playwright routed origin firewall | **FOUND** |
| `tests.activation_browser_harness` | `install_server_socket_guard` | Server socket monkeypatch guard | **FOUND** |
| `tests.activation_browser_harness` | `ControllableActivationMockAdapter` | Controllable mock adapter with spy | **FOUND** |
| `tests.activation_browser_harness` | `_create_fixture_harness_app` | Fixture harness app builder | **FOUND** |

## 2. Verified Pytest Node IDs

| Pytest Node ID | Status |
|---|---|
| `tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_01_upward_standard` | **COLLECTED** |
| `tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_02_downward_standard` | **COLLECTED** |
| `tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_03_strict_equality_failures` | **COLLECTED** |
| `tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_07_forming_bar_exclusion` | **COLLECTED** |
| `tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_12_two_pairs_and_trend_status` | **COLLECTED** |
| `tests/test_msm_engine.py::TestMSMAcceptanceFixtures::test_msm_14_prefix_consistency_and_replay` | **COLLECTED** |
| `tests/test_chart.py::TestCandlestickChart::test_creates_figure_from_h4` | **COLLECTED** |
| `tests/test_app.py::TestAppConstruction::test_no_mt5_import_required` | **COLLECTED** |
| `tests/test_app.py::TestModeIsolationAndFallbackRejection::test_demo_mode_unaffected_by_mt5` | **COLLECTED** |
| `tests/test_choch_engine.py::TestCHOCHExecution::test_choch_bullish_basic_end_to_end_execution` | **COLLECTED** |
| `tests/test_choch_engine.py::TestCHOCHExecution::test_choch_bearish_basic_end_to_end_execution` | **COLLECTED** |
| `tests/test_choch_engine.py::TestCHOCHExecution::test_wick_crossing_only_rejected` | **COLLECTED** |
| `tests/test_choch_engine.py::TestCHOCHExecution::test_continuation_reset_clears_pending_choch` | **COLLECTED** |
| `tests/test_choch_engine.py::TestCHOCHExecution::test_unresolved_same_close_diagnostic_and_downstream_non_publication` | **COLLECTED** |
| `tests/test_choch_engine.py::TestCHOCHExecution::test_unresolved_containment_freezes_authoritative_state_across_later_candles` | **COLLECTED** |
| `tests/test_iss_engine.py::TestISSEngineLifecycleExecution::test_iss_01_bearish_basic_end_to_end_execution` | **COLLECTED** |
| `tests/test_iss_engine.py::TestISSEngineLifecycleExecution::test_iss_02_bullish_basic_end_to_end_execution` | **COLLECTED** |
| `tests/test_iss_engine.py::TestISSEngineAPIAndSafety::test_isolated_tracking_only_distinct_from_continuation_cancellation` | **COLLECTED** |
| `tests/test_iss_engine.py::TestISSEngineAPIAndSafety::test_synthetic_missing_evidence_isolated_tracking_progression_and_cancellation` | **COLLECTED** |
| `tests/test_iss_dashboard_integration.py::TestISSDashboardInspectionPanel::test_inspection_panel_renders_iss_tables` | **COLLECTED** |
| `tests/test_iss_dashboard_integration.py::TestISSDashboardChartRendering::test_chart_renders_iss_markers_and_zones` | **COLLECTED** |
| `tests/test_tjl_coordinator.py::TestTJLCoordinator::test_bullish_basic_end_to_end_replay` | **COLLECTED** |
| `tests/test_tjl_coordinator.py::TestTJLCoordinator::test_continuation_t1_retention_and_t2_pullback_replacement` | **COLLECTED** |
| `tests/test_tjl_coordinator.py::TestTJLCoordinator::test_source_choch_invalidation_and_post_choch_gap` | **COLLECTED** |
| `tests/test_tjl_dashboard_integration.py::TestTJLCandlestickChartOverlays::test_display_toggles_suppress_shapes_without_changing_calculation` | **COLLECTED** |
| `tests/test_tjl_dashboard_integration.py::TestTJLProductionServiceLifecycleAndPresentation::test_chart_window_excluding_authoritative_source_candle` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_all_16_scenarios_execute_through_presentation_builder_with_explicit_assertions` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_bounded_history_display_and_total_count` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_real_engine_lifecycle_reactivation_presentation` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_same_run_successive_cancellation_sync_with_monotonic_sequences_and_error_preservation` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_service_pipeline_execution_and_context_reset` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_recalculation_in_session_a_cannot_reset_session_b` | **COLLECTED** |
| `tests/test_activation_dashboard_integration.py::TestActivationDashboardIntegration::test_application_boundary_session_initialization_and_refresh_retention` | **COLLECTED** |
| `tests/test_activation_dashboard_fixture_integrity.py::TestActivationDashboardFixtureIntegrity::test_scenario_specific_assertion_contracts` | **COLLECTED** |

## 3. Explicit Unresolved & Corrected References

| Claimed Reference | Requirement | Recorded Status & Resolution |
|---|---|---|
| `aladeen.strategy.engine.classify_levels` | MSM-02 Strong/Weak Level Classification | **UNRESOLVED / EXCLUDED FROM SCOPE**: Function does not exist in codebase; strong/weak level classification is not defined in authoritative strategy acceptance contract (docs/requirements/msm-acceptance.md). |
| `aladeen.data.mock_adapter.MockMT5Adapter` | MSM-04 Demo Data Mode | **RESOLVED TO ACTUAL CODEBASE ADAPTERS**: Module aladeen.data.mock_adapter does not exist; production demo mode uses aladeen.data.fixtures.load_fixture and MT5Adapter fallback; tests use tests.activation_browser_harness.ControllableActivationMockAdapter. |
| `aladeen.ui.iss_inspection` | ISS-04 Browser Inspection Component | **RESOLVED TO MARKET_COORDINATOR**: Dedicated module aladeen.ui.iss_inspection does not exist; ISS inspection elements are constructed within aladeen.ui.market_coordinator and tested in tests/test_iss_dashboard_integration.py. |
| `tests/test_activation_dashboard_fixture_integrity.py::test_fixture_13_unresolved_source_snapshot_matches_requirements` | ACT-SC13 Fixture Integrity Contract | **RESOLVED TO COMBINED FIXTURE CONTRACT TEST**: Dedicated function does not exist; Scenario 13 fixture integrity is validated within the combined test_scenario_specific_assertion_contracts. |
