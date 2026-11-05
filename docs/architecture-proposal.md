# Architecture Proposal — Aladeen / TopG Dashboard

> [!IMPORTANT]
> All technology choices below are **proposals, not approved decisions**, except where noted as used in the prototype. This document does not include order execution.

---

## 1. Overview

A local Python application that connects to a running MetaTrader 5 terminal, retrieves candlestick data, runs the strategy-marking modules, and renders an interactive chart with overlaid structure, zones, and signals.

---

## 2. Proposed Technology Stack

### Backend: Python

| Component | Proposal | Rationale |
|-----------|----------|-----------|
| MT5 connection | `MetaTrader5` (official Python package) | Only officially supported Python–MT5 bridge; local terminal required |
| Data handling | `pandas` | Standard for OHLC time-series; MT5 package returns data convertible to DataFrames |
| Strategy engine | Pure Python modules (no external dependencies) | Testable without MT5; deterministic; no third-party indicator libraries |
| Persistence | SQLite via `sqlite3` (stdlib) | Zero-config local storage for candle snapshots, marking state, signals |
| Configuration | TOML or `.env` for connection; JSON/TOML for strategy params | Simple, no server infrastructure |

### Frontend: Browser-Based Dashboard — **Dash/Plotly selected for prototype**

| Component | Proposal | Rationale |
|-----------|----------|-----------|
| App framework | `Dash` (by Plotly) — **used in prototype** | Python-native; no JS build step; supports callbacks and layout |
| Chart library | `plotly` (via Dash) — **used in prototype** | Real candlestick charts with overlays, zoom, hover; interactive out of the box |
| ~~Alternative to evaluate~~ | ~~`Streamlit`~~ | Dash was selected; Streamlit is no longer under evaluation |

> [!NOTE]
> Dash + Plotly was used for the app-shell prototype and is the stack going forward. Streamlit is no longer under active consideration.

### Why Not Desktop GUI?
- Tkinter/PyQt require manual charting; no built-in candlestick support
- Browser-based avoids OS-specific rendering issues
- Plotly provides financial chart primitives (candlestick, shapes for zones, annotations)

---

## 3. MT5 Connection Model

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  MT5 Terminal │◄────│  MetaTrader5 pkg │◄────│  Data Service    │
│  (running)    │     │  (Python bridge) │     │  (fetch/cache)   │
└──────────────┘     └─────────────────┘     └──────────────────┘
                                                      │
                                                      ▼
                                              ┌──────────────────┐
                                              │  SQLite DB       │
                                              │  (candle cache)  │
                                              └──────────────────┘
```

- MT5 terminal must be running locally with a logged-in account
- `MetaTrader5.initialize()` connects to the terminal
- `copy_rates_from_pos()` / `copy_rates_range()` retrieves OHLC data
- Data cached in SQLite to enable offline replay and deterministic testing
- No credentials stored in code; MT5 login handled by the terminal itself

---

## 4. Proposed Folder Structure

```
TopG/
├── docs/
│   ├── strategy/              # Source documents (existing)
│   │   ├── extracted/         # Markdown transcriptions (existing)
│   │   └── README.md
│   ├── requirements/          # Source map (existing)
│   │   └── source-map.md
│   └── architecture-proposal.md   # This document
│
├── src/
│   ├── __init__.py
│   ├── app.py                 # Dash/Streamlit entry point
│   ├── config.py              # Load settings (symbol, timeframe, DB path)
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── mt5_client.py      # MT5 connection, fetch candles
│   │   ├── cache.py           # SQLite read/write for candle data
│   │   └── models.py          # Candle dataclass, enums (Direction, CandleColour)
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── msm.py             # Market Structure Marking engine
│   │   ├── choch.py           # CHOCH detection
│   │   ├── iss.py             # Internal Structure Shift
│   │   ├── tjl.py             # Trend Joining Level labeling
│   │   ├── mtf.py             # Multi-timeframe entry confirmation
│   │   └── types.py           # Shared types: Level, Zone, Signal, MarkingState
│   │
│   └── ui/
│       ├── __init__.py
│       ├── chart.py           # Candlestick chart rendering with overlays
│       ├── controls.py        # Symbol/timeframe selector, starting candle picker
│       └── layout.py          # Dashboard layout composition
│
├── tests/
│   ├── __init__.py
│   ├── test_msm.py            # MSM unit tests with synthetic candle data
│   ├── test_choch.py
│   ├── test_iss.py
│   ├── test_tjl.py
│   ├── test_mtf.py
│   └── fixtures/              # Saved candle sequences for deterministic replay
│       └── README.md
│
├── data/                      # Runtime data (gitignored)
│   └── topg.db                # SQLite database
│
├── .env.example               # Template: MT5_PATH, DB_PATH (no real credentials)
├── .gitignore
├── README.md
├── requirements.txt           # or pyproject.toml
└── pyproject.toml
```

---

## 5. Key Design Principles

### Strategy Separated from Rendering
- Strategy modules in `src/strategy/` operate on plain candle arrays/DataFrames
- They accept input data and return marking results (levels, zones, signals)
- No imports from `src/ui/` or `src/data/` in strategy modules
- UI reads strategy outputs; strategy never calls UI

### Independently Testable
- Each strategy module has its own test file
- Tests use synthetic candle fixtures (not live MT5 data)
- `tests/fixtures/` stores saved candle sequences as JSON/CSV for deterministic replay
- No MT5 connection required for strategy tests

### Historical Signal Inspection and Traceability
- Every marking decision includes: source candle index, rule applied, timestamp
- Confirmed levels store the candle that created them and the candle that confirmed them
- UI can highlight any historical level and show its derivation chain
- SQLite stores completed marking runs for post-session review

### Path to Persistence and Deterministic Replay
- SQLite cache stores raw candle data with symbol + timeframe + timestamp as key
- Marking state can be serialized (JSON) alongside the candle snapshot
- Replay mode: load candles from DB, run strategy bar-by-bar, compare outputs
- Enables regression testing when rules are updated

---

## 6. Staged Build Order

| Stage | Scope | Depends On | Status |
|-------|-------|------------|--------|
| **1. App shell** | Dash app; symbol and timeframe dropdowns; candlestick chart; placeholder panels | — | ✅ Complete |
| **2. MT5 data connection** | Connect to local MT5; fetch OHLC for selected symbol/TF; display real candlestick chart | Stage 1 | Not started |
| **3. SQLite cache** | Cache fetched candles; offline chart from DB; manual refresh button | Stage 2 | Not started |
| **4. MSM engine** | Implement Market Structure Marking module; unit tests with fixtures | Stage 3 | Not started — see note below |
| **5. MSM chart overlay** | Render MSM tentative/confirmed levels and zones on the candlestick chart | Stages 3 + 4 | Not started |
| **6. CHOCH engine + overlay** | CHOCH detection module; tests; chart overlay for CHOCH zones | Stage 5 | Not started |
| **7. ISS engine + overlay** | ISS module; tests; chart overlay for ISS zones | Stage 6 | Not started |
| **8. TJL engine + overlay** | TJL labeling module; tests; chart overlay for TJL zones | Stage 5 | Not started |
| **9. MTF confirmation** | Multi-timeframe monitoring; activation/confirmation state; entry signals | Stages 6 + 7 + 8 | Not started |
| **10. Replay and inspection** | Bar-by-bar replay; historical signal browser; marking-decision audit trail | Stage 9 | Not started |

> [!WARNING]
> **Strategy implementation requires reconciliation with later approved clarifications.** The source documents (Market Structure Marking.docx, Choch.pdf, ISS.pdf, TJL.pdf, MTF-Analysis.pdf) may not reflect all user-approved decisions made after their publication dates. Before beginning MSM or any strategy module, all later clarifications must be collected, documented, and reconciled with the source-map ambiguities listed in `docs/requirements/source-map.md`. Do not start strategy implementation using only these source documents as authority.

---

## 7. What This Proposal Does NOT Cover

- **Order execution**: no buy/sell/modify/close order logic
- **Stop loss, targets, position sizing**: explicitly out of scope per strategy documents
- **Live trading automation**: dashboard is for analysis and review only
- **Deployment**: runs locally only
- **Authentication/multi-user**: single local user
- **Approved decisions**: all technology choices require user approval before implementation, except Dash/Plotly which is used in the prototype
