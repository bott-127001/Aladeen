# Aladeen / TopG Dashboard

A Python and MetaTrader 5 (MT5) trading-analysis dashboard for monitoring, analyzing, and reviewing trading setups and market structure.

> [!IMPORTANT]
> **Read-Only Market Data**: This application only reads candlestick market data. It contains **no order execution**, **no automated trading**, and **no trading strategy calculations**. It never requests, stores, logs, or commits MT5 passwords, account logins, or balances.

---

## Current Status

- ✅ Installable Python package with Dash/Plotly (`aladeen`)
- ✅ Shared Candle Data Contract with strict UTC normalization, finite numeric checks, and chronological/OHLC integrity
- ✅ Explicit Candle Completion Semantics:
  - Documented MT5 bar position zero semantics (`copy_rates_from_pos(..., 0, count)`)
  - Denoted unconfirmed completion explicitly (`UNCONFIRMED_LATEST` / `is_forming = True`)
  - No client-clock bias or guessing broker close boundaries
- ✅ Granular Connection Health Monitoring:
  - Distinguishes local terminal process responsiveness (`mt5.terminal_info() != None`) from broker trade-server connectivity (`terminal_info().connected`)
  - Distinct UI badges: `🟢 Connected to Broker` vs `🟡 Terminal Ready (Broker Offline)` vs `Disconnected`
  - Atomic UI updates on refresh failure (clears green connected banner immediately, sets actionable error)
- ✅ Dual Data Source Support:
  - **Demo Mode**: Built-in deterministic synthetic fixtures (works out of the box without MT5)
  - **MT5 Mode**: Read-only connection to local MetaTrader 5 desktop terminal
- ✅ Safe Idempotent Disconnect & Process Cleanup (`atexit`)
- ✅ Timeframe support: D1, H4, H1, M5, M1
- ✅ Bounded candle count selection (50 to 1000 bars)
- ✅ Forming candle distinction on chart (real-time bar highlighted)
- ✅ 89 automated tests passing (fixtures, contract validation, mocked MT5 adapter, mode isolation, UI consistency)
- ❌ No strategy logic (MSM, CHOCH, ISS, TJL, MTF) implemented yet
- ❌ No SQLite caching / offline replay yet
- ❌ No order execution (strictly out of scope)

---

## Environment Setup & Installation

### Option A: Demo Mode Only (Cross-Platform)

Requires Python 3.10+. Works on Windows, macOS, and Linux without MetaTrader 5:

```bash
# Clone the repository
git clone https://github.com/bott-127001/Aladeen.git
cd Aladeen

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install package with development dependencies
pip install -e ".[dev]"
```

### Option B: With MT5 Integration (Windows Only)

To enable live local MT5 terminal integration:

```bash
# Install with optional MT5 dependency
pip install -e ".[dev,mt5]"
```

*Note*: The `MetaTrader5` library requires Windows 64-bit and Python 3.10+.

---

## Running the Dashboard

```bash
# Run on localhost (127.0.0.1:8050) with debug disabled by default
python -m aladeen.app

# Optional: Enable development debug mode or custom port
python -m aladeen.app --debug --port 8050
```

Open your browser to: **http://127.0.0.1:8050**

---

## Using MT5 Local Market Data

### Local Terminal Prerequisites
1. **MetaTrader 5 Desktop Application** must be installed and running on the same Windows machine.
2. The terminal must be **logged into a trading account** (demo or real broker account).
3. In MT5: Tools → Options → Expert Advisors, ensure **"Allow algorithmic trading"** is checked.

### Connection Steps
1. Open the dashboard in your browser.
2. Switch **Data Source** from `Demo Mode` to `MT5 (Local Terminal)`.
3. Click the green **"⚡ Connect MT5"** button. The connection badge will update to `🟢 Connected (Local Terminal)`.
4. Choose an instrument symbol from the dropdown (populated directly from your MT5 terminal MarketWatch).
5. Choose a timeframe (`D1`, `H4`, `H1`, `M5`, `M1`) and desired candle count.
6. Click **"🔄 Refresh"** at any time to re-fetch the latest candles.
7. Click **"✖ Disconnect"** to release the terminal connection.

### Troubleshooting MT5 Errors

| Error Message | Cause | Resolution |
|---------------|-------|------------|
| `The 'MetaTrader5' package is not installed` | Package missing from Python environment | Run `pip install -e ".[mt5]"` or `pip install MetaTrader5` |
| `Failed to connect to local MT5 terminal` | MT5 desktop app is not running | Launch the MetaTrader 5 desktop application and log into your account before connecting |
| `Symbol 'XYZ' not found or could not be selected` | Symbol is not in your broker's instruments or MarketWatch | Right-click in MT5 MarketWatch and click "Show All", then re-select in dashboard |
| `No candle data returned for symbol on TF` | Terminal history not yet downloaded | Open a chart for that symbol and timeframe in MT5 to initiate broker history download |

---

## Running Tests

### 1. Automated Unit Tests (Offline / Mocked)

All 89 automated unit tests run without requiring MT5 to be installed or running:

```bash
python -m pytest tests/ -v
```

Test coverage includes:
- **`test_fixtures.py`**: Synthetic fixture validation, chronological order, and determinism
- **`test_contract.py`**: Strict UTC normalization, NaT rejection, numeric/finite price enforcement (+inf, -inf, string, boolean checks), OHLC consistency, forming bar validation, and stale/market-closed snapshots
- **`test_chart.py`**: Candlestick and empty chart generation, manual refresh labels, forming bar annotations, edge cases
- **`test_app.py`**: App construction, CLI arguments (`--debug` disabled by default), mode isolation, rejection of silent demo fallbacks, atomic connection loss banner updates, and Demo/MT5 background connection coexistence
- **`test_mt5_adapter.py`**: Local terminal vs broker connectivity distinction (`TERMINAL_ONLY` vs `CONNECTED_TO_BROKER`), idempotent `disconnect()`, exit handler registration (`atexit`), symbol fetching, timeframe mapping, count bounding, forming candle semantics, malformed rates rejection with `CandleValidationError`, and absence of order-execution methods

### 2. Live Integration & Verification Checks

Optional scripts for verifying live environments:

- **Startup Smoke Test** (verifies HTTP 200 on `/` and `/_dash-layout`):
  ```bash
  python tests/smoke_test.py
  ```
- **Real MT5 Terminal Check** (connects to live local terminal, checks broker state, fetches EURUSD, validates contract):
  ```bash
  python tests/check_real_terminal.py
  ```
- **End-to-End Browser Flow** (Playwright automated test: connect → fetch → change timeframe → disconnect → reconnect):
  ```bash
  python tests/browser_check.py
  ```

---

## Project Structure

```
TopG/
├── src/
│   └── aladeen/
│       ├── __init__.py
│       ├── app.py                 # Dash application entry point & CLI parser
│       ├── data/
│       │   ├── __init__.py
│       │   ├── contract.py        # Shared Candle Data Contract & validator
│       │   ├── fixtures.py        # Deterministic synthetic OHLC demo fixtures
│       │   └── mt5_adapter.py     # Read-only MT5 terminal market data adapter
│       └── ui/
│           ├── __init__.py
│           ├── chart.py           # Candlestick chart rendering with Plotly
│           └── layout.py          # Dashboard layout, controls, and callbacks
├── tests/
│   ├── test_app.py                # App construction & CLI tests
│   ├── test_chart.py              # Chart construction tests
│   ├── test_contract.py           # Shared data contract integrity tests
│   ├── test_fixtures.py           # Fixture validity tests
│   └── test_mt5_adapter.py        # Mocked MT5 adapter tests
├── docs/
│   ├── strategy/                  # Strategy source documents & transcriptions
│   ├── requirements/              # Source map & requirements
│   ├── architecture-proposal.md   # Architectural blueprint & staged plan
│   └── development/               # Autonomous workflow documentation & status tracking
├── pyproject.toml                 # Package configuration & optional deps
├── AGENTS.md                      # Agent rules, authority boundaries & instructions
└── README.md
```
