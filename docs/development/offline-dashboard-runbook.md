# Offline Dashboard Runbook & Reproducibility Guide — Project Aladeen / TopG

**Milestone**: Milestone 29 — Read-Only Dashboard Release-Readiness Audit and Reproducible Offline Runbook  
**Branch**: `requirements/dashboard-release-readiness`  
**Accepted Baseline**: `bf737ea41e8bfd554b9386a6e9be86f700824fb3` (Milestone 28 accepted)  
**Safety Boundary**: Strictly read-only market-data retrieval and offline presentation. Strictly zero order execution, zero MT5 trading calls, zero live account modification.  

---

## 1. Overview & Operational Principles

### 1.1 Purpose
This runbook provides complete, executable, step-by-step instructions for any developer or reviewer to clone, install, launch, test, and validate the Aladeen Read-Only Trading Analysis Dashboard in a strictly offline environment from a clean checkout.

### 1.2 Non-Broker Safety Warning
> [!IMPORTANT]
> **SIMULATED / MOCK ENVIRONMENT ONLY**:  
> In offline demo mode, the dashboard connects to synthetic fixture loaders (`aladeen.data.fixtures.load_fixture`) or `ControllableActivationMockAdapter`. Status badges displaying `CONNECTED_TO_BROKER` or symbols such as `DEMO_XAUUSD` indicate internal mock data streams. **They do not establish a connection to a real broker, terminal, or account.** Strictly zero order execution, trade placement, or balance modifications can occur.

---

## 2. System & Dependency Prerequisites

### 2.1 Software Requirements
- **Python**: Version `>=3.10` (Formally tested and verified on Python `3.13.12` 64-bit AMD64 on Windows 11).
- **Git**: Modern Git client.
- **Operating System**: Windows 11 64-bit AMD64 (Native MT5 library requirement for live data mode; all offline demo, unit, integration, and browser validation suites are executed under Windows 11. Linux / macOS environments remain untested).
- **Browser Automation Drivers & Binaries**:
  * Historical Accepted Baseline (Milestone 28): Python package `playwright==1.57.0` driving `Chromium 153.0.8010.12`.
  * Clean Worktree Reproduction (Milestone 29): Python package `playwright==1.64.1` driving `Chromium 156.0.8078.4`.

### 2.2 Core Declared Dependencies (`pyproject.toml`)
- `dash >= 2.14` (Verified: `4.5.0`)
- `plotly >= 5.18` (Verified: `7.1.0`)
- `pandas >= 2.0` (Verified: `3.1.1`)
- `pytest >= 7.4` (Verified: `9.2.0`)
- `playwright >= 1.50` (Verified: `1.64.1`)

---

## 3. Clean Checkout & Environment Installation

Execute the following commands in PowerShell or your platform terminal:

```powershell
# 1. Clone the repository
git clone https://github.com/bott-127001/Aladeen.git
cd Aladeen

# 2. Checkout the release-readiness branch
git checkout requirements/dashboard-release-readiness

# 3. Create a clean virtual environment
python -m venv .venv

# 4. Activate the virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
# source .venv/bin/activate

# 5. Upgrade pip and build tools
python -m pip install --upgrade pip setuptools wheel

# 6. Install the project in editable mode with development dependencies
pip install -e ".[dev]"

# 7. Install Playwright and download the headless Chromium browser binary
pip install playwright
python -m playwright install chromium
```

---

## 4. Local Offline Demo Dashboard Launch

### 4.1 Launching the Default Demo Dashboard
To launch the interactive dashboard locally:

```powershell
# Launch the dashboard server on localhost:8068
python -c "from aladeen.app import create_app; app = create_app(); app.run(host='127.0.0.1', port=8068, debug=False)"
```

#### Actual Default Source-Selection Path:
When `create_app()` is invoked without explicit adapter arguments, it queries MetaTrader 5 terminal connectivity:
- If MT5 is installed, running, and successfully initialized, `MT5Adapter` is instantiated.
- If MT5 is unavailable, fails connection, or the terminal is not running, `create_app()` safely falls back to offline demo data mode using fixture data (`load_fixture`), displaying `CONNECTED_TO_BROKER (DEMO)`.

### 4.2 Launching with Controllable Mock Adapter
To explicitly launch with the controllable test mock adapter (`ControllableActivationMockAdapter`), which generates synthetic offline data and spies on live broker invocations:

```powershell
python -c "from aladeen.app import create_app; from tests.activation_browser_harness import ControllableActivationMockAdapter; adapter = ControllableActivationMockAdapter(); app = create_app(adapter=adapter); app.run(host='127.0.0.1', port=8068, debug=False)"
```

> [!NOTE]
> **Adapter vs Fixture Harness Distinction**:  
> `ControllableActivationMockAdapter` supplies mock MT5 tick and bar streams for the production app. It does not project multi-scenario activation test cases. The 13 catalog lifecycle scenarios are projected exclusively on the secondary visual fixture harness (`http://127.0.0.1:8069`) created via `_create_fixture_harness_app` in `tests/activation_browser_harness.py`.

### 4.3 Network Guards Scope Notice
> [!NOTE]
> **Automated vs Manual Network Isolation Scope**:  
> Automated network firewall intercepts (`ContextSecurityFirewall`) and server-side socket monkeypatches (`install_server_socket_guard`) are test fixtures configured exclusively within the automated browser test runner (`tests/activation_browser_runner.py`). A standalone manual launch (`python -c "..."`) runs as a standard local Flask/Werkzeug process without attaching client firewalls. Both modes, however, run strictly against in-memory mock adapters without real MT5 or external broker connectivity.

### 4.4 UI Navigation Steps to Mount Activation Inspection Panel
When accessing the running dashboard at `http://127.0.0.1:8068/`:
1. **Enable Structure Marking**: In the left sidebar control card, toggle `#msm-enable-toggle` to **ON** (`True`).
2. **Select Calculation Mode**: Set `#strategy-calculation-mode` dropdown to `INTEGRATED_MSM_CHOCH_TJL`.
3. **Select Structural Direction**: Choose `UPWARD` or `DOWNWARD` in `#msm-direction-selector`.
4. **Choose Start Candle**: Select a reference start candle from `#msm-start-candle-dropdown`.
5. **Apply Calculation**: Click the `#msm-apply-btn` button (`Calculate / Refresh Structure`).
6. **Inspect Mounted Activation Container**: The Activation Inspection Panel mounts dynamically inside the DOM with container ID `#activation-inspection-container`, displaying:
   * Non-Execution Disclaimer Banner (amber banner).
   * Context Card (Sequence Domain, Feed ID, Run ID, Timeframe mapping).
   * Registered Membership Table (zones, levels, roles, price bounds).
   * Active Activations Table (state, touch price, evidence badges).
   * Terminal History Table (retained exhausted/cancelled records with 50-row limit).
   * Rearm Controllers Table (departure status, armed flag, next generation).

### 4.5 Teardown & Port Conflict Prevention
- **Teardown**: Press `Ctrl+C` in the terminal to stop the server cleanly.
- **Port Conflict Pre-Check**: Before launching `activation_browser_runner.py`, verify that ports `8068` and `8069` are completely free. If an earlier manual server instance is running, terminate it before starting the test runner:
  ```powershell
  Get-NetTCPConnection -LocalPort 8068,8069 -ErrorAction SilentlyContinue
  ```

---

## 5. Executing the Test Suites & Clean Reproduction Records

### 5.1 Hardened Reproduction Runner Script (`scripts/run_reproduction_m29.py`)
To ensure fully reproducible and verifiable execution, the reproduction suite is encapsulated in a fail-closed, parameterized CLI runner:

```powershell
# Default execution against retained reproduction worktree
python scripts/run_reproduction_m29.py

# Injected failure propagation gate verification (runs 5-case failure & CLI suite)
python scripts/run_reproduction_m29.py --test-failure-gate

# Parameterized paths for alternative environments
python scripts/run_reproduction_m29.py --worktree <path_to_worktree> --python-exe <path_to_python> --output-dir <path_to_evidence>
```

#### Fail-Closed Architecture, Evaluator & Retained Failure Evidence:
1. **Failure Propagation & Non-Empty Input Enforcement**: The runner monitors all step return codes and exits immediately with nonzero status (`sys.exit(1)`) if any required test or provenance check fails. Evaluator requires non-empty inputs and expected inventory of steps/checks.
2. **Observed Browser Provenance Required**: Reproduction completeness requires five explicit checks: `valid_checkout_hash`, `clean_prerun_worktree`, `valid_python_interpreter`, `editable_install_matches_worktree`, and `observed_browser_binary`.
3. **Controlled CLI Production Failure Testing**: `--test-failure-gate` exercises the production evaluation path by executing 5 failure scenarios, including a real CLI subprocess call with `--inject-failing-step` that produces nonzero exit code 1, writes a real failure manifest, and retains:
   - Child execution transcript: [`docs/development/evidence/reproduction_m29/controlled_cli_failure.log`](evidence/reproduction_m29/controlled_cli_failure.log).
   - Retained failure manifest: [`docs/development/evidence/reproduction_m29/controlled_cli_failure_evidence/provenance_manifest.json`](evidence/reproduction_m29/controlled_cli_failure_evidence/provenance_manifest.json).
   - Complete failure test summary: [`docs/development/evidence/reproduction_m29/failure_injection_test_results.json`](evidence/reproduction_m29/failure_injection_test_results.json).

### 5.2 Automated Reference Validator Script (`scripts/validate_matrix_references.py`)
To prevent vacuous validation, the reference validator directly parses Section 2 of `docs/requirements/dashboard-release-readiness.md` and validates every cited symbol and pytest test node:

```powershell
# Run full matrix reference validation against real pytest collection
python scripts/validate_matrix_references.py

# Run simulated failure CLI negative control
python scripts/validate_matrix_references.py --test-failing-cli
```

#### Verification Rules & Negative Controls:
1. **Strict 38-Row Inventory Enforcement**: Directly parses all 38 requirement rows (`MSM-01`..`04`, `CHOCH-01`..`04`, `ISS-01`..`04`, `TJL-01`..`04`, `ACT-G1`..`G8`, `ACT-SC13`, `ACT-MTF`, `SES-01`..`05`, `VIEW-01`..`04`, `SEC-01`..`03`). Any missing, duplicate, or empty row triggers an immediate validation failure and nonzero exit.
2. **Required Evidence for Accepted Rows**: Every row marked `Accepted` must contain at least one valid implementation code span and at least one valid verification code span.
3. **Exact Pytest Node Collection vs. Explicit Browser Helpers**: Pytest test references must strictly match the real collected test node set (544 nodes) from `pytest --collect-only -q` (retained in [`docs/development/evidence/reproduction_m29/pytest_collection.log`](evidence/reproduction_m29/pytest_collection.log)). Reflection is strictly restricted to explicitly designated browser runner functions (`EXPLICIT_ALLOWED_BROWSER_HELPERS`); uncollected `test_*` functions cannot be relabeled as browser helpers.
4. **Nonzero Exit on Failure**: If any row or negative control fails, the script retains the reports and exits immediately with code 1.
5. **Eight Passing Negative Controls**:
   - `empty_matrix_rejected`: Empty matrix correctly rejected.
   - `missing_row_rejected`: Missing requirement row correctly rejected.
   - `duplicate_row_rejected`: Duplicate requirement ID correctly rejected.
   - `accepted_row_without_evidence_rejected`: Accepted row with empty evidence correctly rejected.
   - `uncollected_test_helper_reflection_rejected`: Uncollected test function reflection strictly rejected.
   - `wrong_class_node_rejected`: Wrong-class node strictly rejected.
   - `collection_error_detection`: Nonzero pytest collection exit code detected and aborted.
   - `failing_cli_produces_nonzero_exit`: Validator CLI verified to exit nonzero on validation failure.

### 5.3 Durable Clean-Reproduction Record (Milestone 29)
The replacement reproduction was executed from clean worktree checkout commit `3770989114997280b4f1b19406e294a16ec6c7b9`:
- **Worktree Location**: `D:\Downloads\TopG-repro` (retained, branch `repro-run`)
- **Pre-Run Working Tree Status**: `CLEAN`
- **Virtual Environment**: `D:\Downloads\TopG-repro\.venv_repro`
- **Operating System**: Windows 11 Version 10.0.26200 AMD64
- **Python**: `Python 3.13.12` (Editable location: `D:\Downloads\TopG-repro`)
- **Installed Packages**: Captured in `docs/development/evidence/reproduction_m29/01_pip_list.txt`
- **Browser Binary**: `Chromium 156.0.8078.4` via `playwright==1.64.1`
- **Setup Provenance Note**: Setup commands are operator-reported ('python -m venv .venv_repro', 'pip install -e . pytest pytest-asyncio playwright'); interactive setup transcripts were not retained. Package inventory (01_pip_list.txt) and subsequent command execution were captured.

#### Step Execution & Timing Summary:
1. **Package Inventory (`pip list`)**:
   ```powershell
   D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m pip list
   ```
   * Exit Code: `0`
   * Wrapper Duration: `0.37s`
   * Status: `PASSED`
   * Durable Log: [`docs/development/evidence/reproduction_m29/01_pip_list.txt`](evidence/reproduction_m29/01_pip_list.txt)

2. **Focused Activation & App Tests**:
   ```powershell
   D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m pytest tests/test_activation_dashboard_integration.py tests/test_app.py -v
   ```
   * Exit Code: `0`
   * Wrapper Elapsed Duration: `12.45s`
   * Pytest Summary Duration: `6.26s`
   * Result: `38 passed, 1 warning in 6.26s`
   * Status: `PASSED`
   * Preserved Tooling Warnings:
     - `PytestRemovedIn10Warning`: hookimpl `pytest_addhooks` in `dash\testing\plugin.py:104` uses old-style configuration options.
     - `PytestDeprecationWarning` in stderr: `asyncio_default_fixture_loop_scope` is unset in `pytest_asyncio\plugin.py:300`.
   * Durable Log: [`docs/development/evidence/reproduction_m29/02_focused_tests.log`](evidence/reproduction_m29/02_focused_tests.log)

3. **Full Offline Repository Test Suite**:
   ```powershell
   D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py --ignore=tests/test_activation_browser_controlled.py --ignore=tests/activation_browser_runner.py --ignore=tests/activation_browser_harness.py
   ```
   * Exit Code: `0`
   * Wrapper Elapsed Duration: `7.95s`
   * Pytest Summary Duration: `6.82s`
   * Result: `542 passed, 1 warning in 6.82s`
   * Status: `PASSED`
   * Durable Log: [`docs/development/evidence/reproduction_m29/03_full_offline_suite.log`](evidence/reproduction_m29/03_full_offline_suite.log)

4. **Controlled Activation Browser Validation Suite**:
   ```powershell
   D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -u tests/activation_browser_runner.py
   ```
   * Exit Code: `0`
   * Wrapper Elapsed Duration: `35.73s`
   * Result: `ALL ASSERTIONS PASSED`
   * Status: `PASSED`
   * Durable Log: [`docs/development/evidence/reproduction_m29/04_browser_runner.log`](evidence/reproduction_m29/04_browser_runner.log)

5. **Post-Run Working Tree Status**:
   ```powershell
   git status
   ```
   * Exit Code: `0`
   * Wrapper Duration: `0.07s`
   * Status: `PASSED`
   * Durable Log: [`docs/development/evidence/reproduction_m29/05_git_status_post_browser_run.txt`](evidence/reproduction_m29/05_git_status_post_browser_run.txt)

6. **Aggregate Result**:
   * Total Wrapper Duration: `56.57s`
   * Aggregate Status: **`ALL_STEPS_PASSED`** (Fail-closed exit code `0`)
   * Durable Manifests: [`provenance_manifest.json`](evidence/reproduction_m29/provenance_manifest.json) & [`provenance_manifest.md`](evidence/reproduction_m29/provenance_manifest.md)
   * Automated Reference Validation: [`reference_validation.json`](evidence/reproduction_m29/reference_validation.json) & [`reference_validation.md`](evidence/reproduction_m29/reference_validation.md)

> [!NOTE]
> **Why Browser Tests Are Excluded From the Default Suite**:  
> Controlled browser validation tests require spawning local Werkzeug server processes on ports 8068/8069 and launching headless Chromium instances. To avoid port binding contention during rapid CI or local test loops, browser suites are orchestrated through dedicated runner scripts.

> [!NOTE]
> **Why Browser Tests Are Excluded From the Default Suite**:  
> Controlled browser validation tests require spawning local Werkzeug server processes on ports 8068/8069 and launching headless Chromium instances. To avoid port binding contention during rapid CI or local test loops, browser suites are orchestrated through dedicated runner scripts.

---

## 6. Generated Visual Evidence Artifacts Inventory

Upon successful execution of the controlled browser suite, exactly 9 PNG screenshots are generated in `tests/evidence/activation_browser/`:

| Filename | Description | Key Visible Invariants |
|---|---|---|
| `01_app_mounting_desktop.png` | Desktop layout at 1280x800 | Non-execution disclaimer, sequence domain header, layout mounting in DOM |
| `02_app_mounting_narrow_viewport.png` | Narrow viewport at 800x600 | Verifies non-overlapping geometry between disclaimer, context card, and table header under narrow viewport |
| `03_session_isolation_context_a.png` | Context A post-recalculation | Advanced run domain `..._INC1_3`, active activations table |
| `04_session_isolation_context_b.png` | Context B isolation | Invariant run domain `..._INC2_2`, preserved active activations table |
| `05_scenario_02_first_exact_touch.png` | Scenario 2 First Exact Touch | `PENDING_ACTIVATION`, first touch price `1.1370`, trigger `OBS_01` |
| `06_scenario_10_armed_controller.png` | Scenario 10 Armed Controller | `ARMED FOR RETOUCH`, next generation `Gen 2`, armed=`YES` |
| `07_scenario_13_unresolved_source_banner.png` | Scenario 13 Unresolved Source | Canonical warning banner, processed bar #15 vs received bar #19 |
| `08_scenario_history_50_limit.png` | Custom Scenario History 50-Limit | "Showing latest 50 of 75 records", exactly 50 rows in DOM |
| `09_scenario_sync_error_banner.png` | Custom Scenario Sync Error | TJL cursor mismatch banner alongside established evidence |

> [!WARNING]
> **Evidence Retention Notice Before Git Restore**:  
> Running `activation_browser_runner.py` re-generates and re-writes the screenshot PNG files on disk. If you need to preserve newly captured screenshots for evidence or review, **copy or back them up before running `git restore`**. Executing `git restore tests/evidence/activation_browser/` permanently discards all newly generated screenshot modifications in the working tree.

---

## 7. Security Architecture & In-Memory Isolation

### 7.1 Security Architecture
```
┌────────────────────────────────────────────────────────┐
│               Playwright Chromium Browser              │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ContextSecurityFirewall                          │  │
│  │  - Intercepts all requests (**/*)                │  │
│  │  - Whitelist: http://127.0.0.1:8068, 8069        │  │
│  │  - Aborts unauthorized external URLs (Fail-Closed)│  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ BrowserAuditWatcher                              │  │
│  │  - Traps console errors, page errors             │  │
│  │  - Monitors failed /_dash-update-component calls │  │
│  │  - Auto-attaches to newly spawned pages/tabs     │  │
│  └──────────────────────────────────────────────────┘  │
└───────────────────────────┬────────────────────────────┘
                            │ (Local Loopback HTTP Only)
┌───────────────────────────▼────────────────────────────┐
│              Python Werkzeug Server Process            │
│  ┌──────────────────────────────────────────────────┐  │
│  │ install_server_socket_guard                      │  │
│  │  - Monkeypatches socket.socket.connect           │  │
│  │  - Whitelist: 127.0.0.1, localhost               │  │
│  │  - Blocks non-local outbound socket calls        │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ControllableActivationMockAdapter                │  │
│  │  - In-memory synthetic OHLC data generator       │  │
│  │  - Throws PermissionError on order_send()        │  │
│  │  - Spies on live broker invocations (assert == 0) │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### 7.2 Process-Local Registry & Reset Behavior
- Session state is managed by `ActivationSessionRegistry` in `src/aladeen/strategy/service.py`.
- Sessions are stored in a process-local in-memory dictionary keyed by session ID (`sid`).
- **Reset Trigger**: Stopping or restarting the Python process completely resets all session state.
- **Tab Ownership Scope**: Tested tab duplication protection applies to programmatic `window.open()` calls with fresh UUID generation. Native browser-menu / context-menu tab duplication is not automated due to Playwright API limitations.

---

## 8. Failure Diagnostics & Safe Cleanup

### 8.1 Occupied Port Recovery (Ports 8068 or 8069)
If a server fails to start due to port collision:
- **Fail-Closed Behavior**: `ControlledServerHandle` catches socket collision `SystemExit` and raises a clean `RuntimeError`, safely aborting without leaking resources.
- **Diagnostics**:
  ```powershell
  # Check if port 8068 or 8069 is occupied:
  Get-NetTCPConnection -LocalPort 8068,8069 -ErrorAction SilentlyContinue
  ```
- **Safe Resolution**: Wait for the previous test runner to finish exiting, or close any orphaned test terminal. **Never kill arbitrary or unverified system PIDs.**

### 8.2 Clean Workspace Verification
To verify your workspace is completely clean and untainted:
```powershell
git status
```
Expected output:
```text
On branch requirements/dashboard-release-readiness
nothing to commit, working tree clean
```
