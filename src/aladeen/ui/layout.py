"""Dashboard layout and Dash callbacks.

Defines the page structure, MT5 controls, and wires up interactivity.
Chart construction, MT5 connection, and data loading are separated into
dedicated modules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import dash
from dash import Dash, Input, Output, State, callback_context, dcc, html
import plotly.graph_objects as go

from aladeen.data.contract import CandleValidationError
from aladeen.data.fixtures import (
    DEMO_SYMBOL,
    SUPPORTED_TIMEFRAMES,
    available_symbols,
    available_timeframes,
    load_fixture,
)
from aladeen.data.mt5_adapter import (
    MT5ConnectionError,
    MT5DataError,
    MT5Error,
    MT5NotInstalledError,
    MT5SymbolError,
    get_mt5_adapter,
)
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart

# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

_BANNER_STYLE_DEMO = {
    "background": "#ff9800",
    "color": "#000",
    "textAlign": "center",
    "padding": "8px",
    "fontWeight": "bold",
    "fontSize": "13px",
}

_BANNER_STYLE_MT5_CONNECTED = {
    "background": "#2e7d32",
    "color": "#fff",
    "textAlign": "center",
    "padding": "8px",
    "fontWeight": "bold",
    "fontSize": "13px",
}

_BANNER_STYLE_MT5_DISCONNECTED = {
    "background": "#37474f",
    "color": "#cfd8dc",
    "textAlign": "center",
    "padding": "8px",
    "fontWeight": "bold",
    "fontSize": "13px",
}


def _build_controls() -> html.Div:
    """Return the control bar with data source, connection, symbol, and timeframe."""
    symbols = available_symbols()
    timeframes = available_timeframes()

    return html.Div(
        style={
            "display": "flex",
            "flexDirection": "column",
            "gap": "10px",
            "padding": "12px 16px",
            "background": "#1e1e2f",
            "borderBottom": "1px solid #2d2d44",
        },
        children=[
            # Row 1: Source selector & MT5 Connection controls
            html.Div(
                style={"display": "flex", "alignItems": "center", "gap": "16px", "flexWrap": "wrap"},
                children=[
                    # Data Source Radio
                    html.Div(
                        [
                            html.Label(
                                "Data Source",
                                style={"color": "#aaa", "fontSize": "12px", "display": "block", "marginBottom": "4px"},
                            ),
                            dcc.RadioItems(
                                id="data-source-selector",
                                options=[
                                    {"label": " Demo Mode", "value": "demo"},
                                    {"label": " MT5 (Local Terminal)", "value": "mt5"},
                                ],
                                value="demo",
                                inline=True,
                                style={"color": "#e0e0e0", "fontSize": "13px"},
                                inputStyle={"marginRight": "5px", "marginLeft": "10px"},
                            ),
                        ]
                    ),
                    # Divider
                    html.Div(style={"width": "1px", "height": "32px", "background": "#444"}),
                    # MT5 Connect / Disconnect Buttons
                    html.Div(
                        id="mt5-controls-container",
                        style={"display": "flex", "alignItems": "center", "gap": "8px"},
                        children=[
                            html.Button(
                                "⚡ Connect MT5",
                                id="connect-btn",
                                n_clicks=0,
                                style={
                                    "padding": "6px 14px",
                                    "background": "#2e7d32",
                                    "color": "#fff",
                                    "border": "none",
                                    "borderRadius": "4px",
                                    "cursor": "pointer",
                                    "fontWeight": "bold",
                                },
                            ),
                            html.Button(
                                "✖ Disconnect",
                                id="disconnect-btn",
                                n_clicks=0,
                                style={
                                    "padding": "6px 14px",
                                    "background": "#546e7a",
                                    "color": "#fff",
                                    "border": "none",
                                    "borderRadius": "4px",
                                    "cursor": "pointer",
                                },
                            ),
                            # Connection Badge
                            html.Span(
                                "Disconnected",
                                id="connection-badge",
                                style={
                                    "padding": "4px 8px",
                                    "borderRadius": "4px",
                                    "background": "#263238",
                                    "color": "#b0bec5",
                                    "fontSize": "12px",
                                },
                            ),
                        ],
                    ),
                ],
            ),
            # Row 2: Symbol, Timeframe, Candle count, Refresh, and Status
            html.Div(
                style={"display": "flex", "alignItems": "center", "gap": "16px", "flexWrap": "wrap"},
                children=[
                    # Symbol selector
                    html.Div(
                        [
                            html.Label("Symbol", style={"color": "#aaa", "fontSize": "12px"}),
                            dcc.Dropdown(
                                id="symbol-selector",
                                options=[{"label": s, "value": s} for s in symbols],
                                value=symbols[0],
                                clearable=False,
                                disabled=True,
                                style={"width": "180px", "color": "#000"},
                            ),
                        ]
                    ),
                    # Timeframe selector
                    html.Div(
                        [
                            html.Label("Timeframe", style={"color": "#aaa", "fontSize": "12px"}),
                            dcc.Dropdown(
                                id="timeframe-selector",
                                options=[{"label": tf, "value": tf} for tf in timeframes],
                                value="H4",
                                clearable=False,
                                style={"width": "110px", "color": "#000"},
                            ),
                        ]
                    ),
                    # Candle count selector (bounded)
                    html.Div(
                        [
                            html.Label("Candles", style={"color": "#aaa", "fontSize": "12px"}),
                            dcc.Dropdown(
                                id="candle-count-selector",
                                options=[
                                    {"label": "50 bars", "value": 50},
                                    {"label": "100 bars", "value": 100},
                                    {"label": "200 bars", "value": 200},
                                    {"label": "500 bars", "value": 500},
                                ],
                                value=100,
                                clearable=False,
                                style={"width": "110px", "color": "#000"},
                            ),
                        ]
                    ),
                    # Refresh button
                    html.Button(
                        "🔄 Refresh",
                        id="refresh-btn",
                        n_clicks=0,
                        style={
                            "marginTop": "16px",
                            "padding": "6px 18px",
                            "cursor": "pointer",
                            "background": "#1565c0",
                            "color": "#fff",
                            "border": "none",
                            "borderRadius": "4px",
                        },
                    ),
                    # Status area
                    html.Div(
                        id="status-area",
                        style={
                            "marginTop": "16px",
                            "marginLeft": "auto",
                            "color": "#e0e0e0",
                            "fontSize": "13px",
                        },
                    ),
                ],
            ),
            # Actionable Error Alert Bar (hidden when no error)
            html.Div(
                id="error-alert",
                style={"display": "none", "padding": "8px 12px", "borderRadius": "4px", "fontSize": "13px"},
            ),
        ],
    )


def _build_placeholder(title: str, description: str) -> html.Div:
    """Return a clearly labeled placeholder panel."""
    return html.Div(
        style={
            "border": "1px dashed #555",
            "borderRadius": "6px",
            "padding": "16px",
            "margin": "10px 16px",
            "color": "#888",
        },
        children=[
            html.H4(title, style={"margin": "0 0 6px 0", "color": "#aaa"}),
            html.P(description, style={"margin": 0, "fontSize": "13px"}),
        ],
    )


def build_layout() -> html.Div:
    """Return the complete dashboard layout."""
    return html.Div(
        style={"fontFamily": "Segoe UI, sans-serif", "background": "#14141f", "minHeight": "100vh"},
        children=[
            # Hidden Stores for State Management
            dcc.Store(id="mt5-connection-store", data={"connected": False, "symbols": []}),
            # Title bar
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "10px 16px",
                    "background": "#0d0d1a",
                },
                children=[
                    html.H2("Aladeen / TopG", style={"margin": 0, "color": "#e0e0e0"}),
                    html.Span("Dashboard", style={"marginLeft": "10px", "color": "#777", "fontSize": "16px"}),
                ],
            ),
            # Data source banner
            html.Div(
                "⚠️  DEMO DATA — NOT CONNECTED TO MT5",
                id="source-banner",
                style=_BANNER_STYLE_DEMO,
            ),
            # Controls
            _build_controls(),
            # Main chart
            dcc.Graph(id="main-chart", config={"displayModeBar": True}),
            # Placeholder: strategy configuration
            _build_placeholder(
                "📐 Strategy Configuration — Not Yet Implemented",
                "MSM, CHOCH, ISS, TJL, and MTF modules will be added in a later phase. "
                "Starting candle and direction selection will appear here. "
                "No strategy logic exists in this prototype.",
            ),
            # Placeholder: signal history
            _build_placeholder(
                "📋 Signal History — Not Yet Implemented",
                "Historical marking results, confirmed levels, zone activations, and "
                "entry signals will appear here once strategy modules are built. "
                "No signals are generated by this prototype.",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Core Chart & Status Generation (Testable standalone function)
# ---------------------------------------------------------------------------


def generate_chart_and_status(
    data_source: str,
    symbol: str,
    timeframe: str,
    candle_count: int,
    is_connected: bool,
    adapter: Any = None,
) -> tuple[go.Figure, str]:
    """Generate the chart figure and status text according to selected source.

    Separated from the Dash callback wrapper for direct unit testing.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if adapter is None:
        adapter = get_mt5_adapter()

    # ------------------- DEMO MODE -------------------
    if data_source == "demo":
        if timeframe not in SUPPORTED_TIMEFRAMES:
            msg = (
                f"Timeframe '{timeframe}' is not available in demo mode. "
                f"Supported demo timeframes: {', '.join(SUPPORTED_TIMEFRAMES)}."
            )
            fig = create_empty_chart(msg, title=f"Demo: {DEMO_SYMBOL} ({timeframe}) — Unsupported")
            status = f"⚠️ Demo: {msg}"
            return fig, status

        df = load_fixture(DEMO_SYMBOL, timeframe)
        if df is None or df.empty:
            msg = f"No demo data available for {DEMO_SYMBOL} on {timeframe}."
            fig = create_empty_chart(msg)
            return fig, f"⚠️ {msg}"

        fig = create_candlestick_chart(
            df,
            symbol=DEMO_SYMBOL,
            timeframe=timeframe,
            data_source="demo",
            is_demo=True,
            last_fetch_time=now_utc,
            candle_count=len(df),
        )
        status = (
            f"Source: Demo | Symbol: {DEMO_SYMBOL} | TF: {timeframe} | "
            f"Count: {len(df)} candles | Last Fetch: {now_utc}"
        )
        return fig, status

    # ------------------- MT5 MODE -------------------
    if not is_connected:
        msg = "MT5 terminal is not connected. Click '⚡ Connect MT5' above."
        fig = create_empty_chart(msg, title="MT5 Terminal: Disconnected")
        status = "🔴 MT5 Disconnected. Please connect to terminal."
        return fig, status

    if not symbol:
        msg = "No symbol selected. Please select a valid symbol from MT5 MarketWatch."
        fig = create_empty_chart(msg, title="MT5: Select Symbol")
        status = "⚠️ No symbol selected."
        return fig, status

    try:
        df = adapter.fetch_candles(symbol, timeframe, count=candle_count)
        fig = create_candlestick_chart(
            df,
            symbol=symbol,
            timeframe=timeframe,
            data_source="mt5",
            is_demo=False,
            is_stale=False,
            last_fetch_time=now_utc,
            candle_count=len(df),
        )
        status = (
            f"Source: MT5 Local Terminal | Symbol: {symbol} | TF: {timeframe} | "
            f"Count: {len(df)} candles | Last Fetch: {now_utc}"
        )
        return fig, status

    except MT5SymbolError as e:
        msg = f"Symbol Error: {e}"
        fig = create_empty_chart(msg, title=f"MT5: Symbol Unavailable ({symbol})")
        status = f"❌ {msg}"
        return fig, status

    except MT5DataError as e:
        msg = f"Data Fetch Error: {e}"
        fig = create_empty_chart(msg, title=f"MT5: Fetch Failed ({symbol} {timeframe})")
        status = f"❌ {msg}"
        return fig, status

    except MT5ConnectionError as e:
        msg = f"Connection Lost: {e}"
        fig = create_empty_chart(msg, title="MT5: Connection Lost")
        status = f"❌ {msg}"
        return fig, status

    except CandleValidationError as e:
        msg = f"Data Contract Violation: {e}"
        fig = create_empty_chart(msg, title="MT5: Malformed Data Received")
        status = f"❌ {msg}"
        return fig, status

    except Exception as e:
        msg = f"Unexpected Error fetching MT5 data: {e}"
        fig = create_empty_chart(msg, title="MT5: Error")
        status = f"❌ {msg}"
        return fig, status


# ---------------------------------------------------------------------------
# Callbacks Registration
# ---------------------------------------------------------------------------


def register_callbacks(app: Dash) -> None:
    """Register all Dash callbacks on *app*."""
    adapter = get_mt5_adapter()

    # Callback 1: MT5 Connection & Source Selector management
    @app.callback(
        Output("mt5-connection-store", "data"),
        Output("connection-badge", "children"),
        Output("connection-badge", "style"),
        Output("symbol-selector", "options"),
        Output("symbol-selector", "value"),
        Output("symbol-selector", "disabled"),
        Output("error-alert", "children"),
        Output("error-alert", "style"),
        Output("source-banner", "children"),
        Output("source-banner", "style"),
        Input("connect-btn", "n_clicks"),
        Input("disconnect-btn", "n_clicks"),
        Input("data-source-selector", "value"),
        State("symbol-selector", "value"),
        State("mt5-connection-store", "data"),
    )
    def handle_connection_and_source(
        _connect_clicks: int,
        _disconnect_clicks: int,
        data_source: str,
        current_symbol: str | None,
        store_data: dict,
    ) -> tuple:
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        is_connected = store_data.get("connected", False) if store_data else False
        cached_symbols = store_data.get("symbols", []) if store_data else []
        error_msg: str | None = None

        if triggered_id == "connect-btn":
            try:
                adapter.connect()
                is_connected = True
                cached_symbols = adapter.get_symbols()
            except MT5NotInstalledError as e:
                is_connected = False
                error_msg = str(e)
            except MT5ConnectionError as e:
                is_connected = False
                error_msg = str(e)
            except Exception as e:
                is_connected = False
                error_msg = f"Unexpected connection error: {e}"

        elif triggered_id == "disconnect-btn":
            adapter.disconnect()
            is_connected = False
            cached_symbols = []

        # Synchronize connection state with adapter
        if is_connected and not adapter.is_connected():
            is_connected = False

        new_store = {"connected": is_connected, "symbols": cached_symbols}

        # Determine UI states
        if is_connected:
            badge_text = "🟢 Connected (Local Terminal)"
            badge_style = {"padding": "4px 8px", "borderRadius": "4px", "background": "#1b5e20", "color": "#a5d6a7", "fontSize": "12px"}
        else:
            badge_text = "Disconnected"
            badge_style = {"padding": "4px 8px", "borderRadius": "4px", "background": "#263238", "color": "#b0bec5", "fontSize": "12px"}

        if data_source == "demo":
            banner_text = "⚠️  DEMO DATA — NOT CONNECTED TO MT5"
            banner_style = _BANNER_STYLE_DEMO
            sym_options = [{"label": s, "value": s} for s in available_symbols()]
            sym_value = available_symbols()[0]
            sym_disabled = True
        else:
            # MT5 mode
            if is_connected:
                banner_text = "🟢 MT5 CONNECTED — Local Terminal Read-Only Data"
                banner_style = _BANNER_STYLE_MT5_CONNECTED
                if cached_symbols:
                    sym_options = [{"label": s, "value": s} for s in cached_symbols]
                    sym_value = current_symbol if current_symbol in cached_symbols else cached_symbols[0]
                    sym_disabled = False
                else:
                    sym_options = [{"label": "No symbols available", "value": ""}]
                    sym_value = ""
                    sym_disabled = True
            else:
                banner_text = "🔴 MT5 DISCONNECTED — Click '⚡ Connect MT5' to stream local terminal data"
                banner_style = _BANNER_STYLE_MT5_DISCONNECTED
                sym_options = [{"label": "Connect to MT5 first", "value": ""}]
                sym_value = ""
                sym_disabled = True

        if error_msg:
            alert_children = [html.B("MT5 Connection Alert: "), html.Span(error_msg)]
            alert_style = {"display": "block", "background": "#b71c1c", "color": "#ffebee", "padding": "8px 12px", "borderRadius": "4px", "fontSize": "13px"}
        else:
            alert_children = []
            alert_style = {"display": "none"}

        return (
            new_store,
            badge_text,
            badge_style,
            sym_options,
            sym_value,
            sym_disabled,
            alert_children,
            alert_style,
            banner_text,
            banner_style,
        )

    # Callback 2: Chart and status area update
    @app.callback(
        Output("main-chart", "figure"),
        Output("status-area", "children"),
        Input("data-source-selector", "value"),
        Input("symbol-selector", "value"),
        Input("timeframe-selector", "value"),
        Input("candle-count-selector", "value"),
        Input("refresh-btn", "n_clicks"),
        Input("mt5-connection-store", "data"),
    )
    def update_chart(
        data_source: str,
        symbol: str,
        timeframe: str,
        candle_count: int,
        _n_clicks: int,
        store_data: dict,
    ) -> tuple:
        """Fetch and render data according to selected source and timeframe."""
        is_connected = store_data.get("connected", False) if store_data else False
        return generate_chart_and_status(
            data_source=data_source,
            symbol=symbol,
            timeframe=timeframe,
            candle_count=candle_count,
            is_connected=is_connected,
            adapter=adapter,
        )
