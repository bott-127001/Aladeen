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
> In offline demo mode, the dashboard connects to `MockMT5Adapter` or `ControllableActivationMockAdapter`. Status badges displaying `CONNECTED_TO_BROKER` or symbols such as `DEMO_XAUUSD` indicate internal mock data streams. **They do not establish a connection to a real broker, terminal, or account.** Strictly zero order execution, trade placement, or balance modifications can occur.

---

## 2. System & Dependency Prerequisites

### 2.1 Software Requirements
- **Python**: Version `>=3.10` (Formally tested and verified on Python `3.13.12` 64-bit AMD64 on Windows 11).
- **Git**: Modern Git client.
- **Operating System**: Windows (native MT5 library requirement for live data; all offline demo, unit, integration, and browser validation tests are 100% platform-agnostic).
- **Browser Automation Binary**: Playwright-managed Chromium browser binary (`Chromium 153.0.8010.12`).

### 2.2 Core Declared Dependencies (`pyproject.toml`)
- `dash >= 2.14` (Verified: `4.5.0`)
- `plotly >= 5.18` (Verified: `6.7.0`)
- `pandas >= 2.0` (Verified: `2.2.3`)
- `pytest >= 7.4` (Verified: `9.0.3`)
- `playwright >= 1.50` (Verified: `1.63.0`)

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

To launch the interactive dashboard locally using the built-in offline mock adapter:

```powershell
# Launch the dashboard server on localhost:8068
python -c "from aladeen.app import create_app; app = create_app(); app.run(host='127.0.0.1', port=8068, debug=False)"
```

### Expected Indicators:
- Terminal Output:
  ```text
  Dash is running on http://127.0.0.1:8068/
   * Serving Flask app 'aladeen.app'
   * Debug mode: off
  ```
- **Access URL**: Open your browser to `http://127.0.0.1:8068/`.
- **Visible Elements**:
  * Top Navigation Bar with `CONNECTED_TO_BROKER (DEMO)` status.
  * Symbol selector (`EURUSD`, `GBPUSD`, `XAUUSD`) and timeframe selector (`M1` to `D1`).
  * Strategy calculation mode selector (`INTEGRATED_MSM_CHOCH_TJL`).
  * Interactive Plotly candlestick chart with structural swing overlays, CHOCH levels, and TJL zone boxes.
  * Activation Inspection Panel displaying non-execution disclaimer banner, sequence domain context card, registered membership table, active activations table, terminal history, and rearm controllers.
- **Teardown**: Press `Ctrl+C` in the terminal to stop the server cleanly.

---

## 5. Executing the Test Suites

### 5.1 Focused Activation Dashboard & App Tests
Runs the activation dashboard presentation unit/integration tests and core app callbacks:

```powershell
pytest tests/test_activation_dashboard_integration.py tests/test_app.py -v
```
**Expected Result**: `38 passed in ~2.0s` (0 failures).

---

### 5.2 Full Repository Offline Test Suite
Runs all offline unit and integration tests across MSM, CHOCH, ISS, TJL, Activation Engine, and UI components:

```powershell
pytest -q tests/ --ignore=tests/test_tjl_browser_controlled.py --ignore=tests/test_iss_browser_controlled.py --ignore=tests/test_activation_browser_controlled.py --ignore=tests/activation_browser_runner.py --ignore=tests/activation_browser_harness.py
```
**Expected Result**: `542 passed in ~8-9s` (0 failures, 100% pass rate).

> [!NOTE]
> **Why Browser Tests Are Excluded From the Default Suite**:  
> Controlled browser validation tests require spawning local Werkzeug server processes on ports 8068/8069 and launching headless Chromium instances. To avoid port binding contention during rapid CI or local test loops, browser suites are orchestrated through dedicated runner scripts.

---

### 5.3 Controlled Activation Browser Validation Suite
Executes the comprehensive, end-to-end controlled browser validation for Milestone 28 under strict security firewalls and socket guards:

```powershell
python -u tests/activation_browser_runner.py
```

#### Detailed Execution Sequence:
1. **Server Lifecycle & Recovery Failure Injection**:
   - Verifies single server clean startup, socket binding, thread join, and port release.
   - Verifies multi-server collision recovery (simulating occupied port on Server 2 cleanly aborts and terminates Server 1).
   - Verifies managed-body exception recovery (assertion raised inside execution body cleanly terminates both servers and releases sockets).
2. **Isolation Guards Negative Controls**:
   - `ContextSecurityFirewall`: Confirms that requests to unauthorized local ports (`8070`) or external domains (`example.com`) are immediately aborted with `blockedbyclient` / `ERR_BLOCKED_BY_CLIENT` before navigation.
   - `install_server_socket_guard`: Confirms that prohibited destinations (`('8.8.8.8', 53)`) immediately raise `PermissionError` without reaching underlying connect methods, while permitted local hosts pass through. Confirms clean restoration on exceptions.
3. **Managed Server Startup**:
   - Production App launched on `http://127.0.0.1:8068`.
   - Visual Fixture Harness launched on `http://127.0.0.1:8069`.
4. **Section A (Mounting & Viewport Usability)**:
   - Mounts desktop view at 1280x800; captures `01_app_mounting_desktop.png`.
   - Resizes viewport to 800x600; asserts zero vertical overlap between disclaimer, context card, and table heading.
   - Measures real horizontal scroll container (`window.scrollX` shift from 0 to 256px), asserting rightmost column (`Usage Evidence`) is visible.
   - Asserts code typography font size is 10.0px (within `[9.0px, 11.5px]`).
5. **Section B (Session & Tab Isolation)**:
   - Validates multi-context isolation (`sid_a != sid_b`).
   - Validates causal run domain advancement in Context A (`..._INC1_2` -> `..._INC1_3`) while Context B remains invariant.
   - Validates steady polling interval retention.
   - Validates timeframe switching to `D1` (confirmation `H1`).
   - Validates same-tab reload preserves session identity.
   - Validates programmatic `window.open` detects un-named tab, generates fresh UUID session ID, and maintains complete recalculation isolation.
6. **Section C (15 Visual Lifecycle Scenarios)**:
   - Scenarios 2–14 (13 catalog fixtures) plus 2 custom cases (history 50-limit bounding, synchronization diagnostic banner).
   - Captures screenshots `05` through `09`.
7. **Final Audits**:
   - Zero console errors, zero page errors, zero failed callback requests/responses.
   - Zero firewall violations, zero socket guard violations, zero live broker invocations.

**Expected Completion Indicator**:
```text
================================================================================
CONTROLLED BROWSER VALIDATION COMPLETED SUCCESSFULLY (ALL ASSERTIONS PASSED)
================================================================================
```
Exit code: `0`.

---

## 6. Generated Visual Evidence Artifacts

Upon successful completion of the controlled browser suite, inspect the captured PNG screenshots in `tests/evidence/activation_browser/`:

| Filename | Description | Key Visible Invariants |
|---|---|---|
| `01_app_mounting_desktop.png` | Desktop layout at 1280x800 | Non-execution disclaimer, sequence domain header, layout mounting |
| `03_session_isolation_context_a.png` | Context A post-recalculation | Advanced run domain `..._INC1_3`, active activations table |
| `04_session_isolation_context_b.png` | Context B isolation | Invariant run domain `..._INC2_2`, preserved active activations table |
| `05_scenario_02_first_exact_touch.png` | Scenario 2 First Exact Touch | `PENDING_ACTIVATION`, first touch price `1.1370`, trigger `OBS_01` |
| `06_scenario_10_armed_controller.png` | Scenario 10 Armed Controller | `ARMED FOR RETOUCH`, next generation `Gen 2`, armed=`YES` |
| `07_scenario_13_unresolved_source_banner.png` | Scenario 13 Unresolved Source | Canonical warning banner, processed bar #15 vs received bar #19 |
| `08_scenario_history_50_limit.png` | Custom Scenario History 50-Limit | "Showing latest 50 of 75 records", exactly 50 rows in DOM |
| `09_scenario_sync_error_banner.png` | Custom Scenario Sync Error | TJL cursor mismatch banner alongside established evidence |

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
- **Tab Ownership**: Same-tab reloads preserve the session ID via `window.name` verification; opening a duplicate tab generates a fresh UUID session ID, maintaining complete isolation from parent tabs.

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
