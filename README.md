# Aladeen / TopG Dashboard

A Python and MetaTrader 5 (MT5) trading-analysis dashboard for monitoring, analyzing, and reviewing trading setups and market structure.

## Status

**App-shell prototype** — the interface foundation is runnable but no strategy logic or MT5 integration exists.

- ✅ Installable Python package with Dash/Plotly
- ✅ Browser-based candlestick chart with demo data
- ✅ Symbol and timeframe selectors, refresh button
- ✅ 34 automated tests passing
- ❌ No MSM, CHOCH, ISS, TJL, or MTF modules implemented
- ❌ No MT5 connectivity — demo data only
- ❌ No SQLite persistence
- ❌ No order execution (out of scope)

## Environment Setup

**Requirements**: Python 3.10+

```bash
# Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

## Installation

```bash
# Install the package with development dependencies
pip install -e ".[dev]"
```

## Run the Dashboard

```bash
python -m aladeen.app
```

Then open http://127.0.0.1:8050 in your browser.

The dashboard displays deterministic demo OHLC data. It is **not connected to MT5** and shows a prominent warning banner. Symbol selection is disabled (only one demo fixture exists). Only H4 and D1 timeframes have fixture data; other timeframes show an explicit unsupported-demo message.

## Run Tests

```bash
python -m pytest tests/ -v
```

## Current Limitations

- **No strategy logic**: MSM, CHOCH, ISS, TJL, and MTF entry-confirmation modules are not implemented. Strategy configuration and signal history panels are placeholder only.
- **No MT5 integration**: the app does not connect to a MetaTrader 5 terminal. All chart data comes from hard-coded deterministic fixtures.
- **No persistence**: no SQLite caching or replay capability yet.
- **No order execution**: the dashboard is for analysis only. No buy/sell/modify/close order logic will be added.
- **Demo data only**: the chart shows fixed synthetic candles labeled clearly as demo data.

## Strategy & Requirements

- Strategy source documents are located in [docs/strategy/](docs/strategy/).
- Strategy requirements will be supplied separately; do not invent trading rules.
- Trading logic, strategy modules, and MT5 connectivity will be implemented in subsequent phases.

## Project Structure

```
src/aladeen/
├── app.py              # Dash application entry point
├── data/
│   └── fixtures.py     # Deterministic synthetic OHLC data
└── ui/
    ├── chart.py        # Candlestick chart construction
    └── layout.py       # Dashboard layout and callbacks
tests/
├── test_app.py         # App construction tests
├── test_chart.py       # Chart creation tests
└── test_fixtures.py    # Fixture validity and ordering tests
```
