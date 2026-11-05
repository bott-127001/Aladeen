"""Dashboard layout, MT5 controls, and Dash callbacks.

Defines page structure, MT5 controls, MSM controls, inspection panel,
and wires up core callbacks. Delegated MSM callback logic lives in
`aladeen.ui.msm_callbacks` for focused modularity.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import dash
from dash import Dash, Input, Output, State, callback_context, dcc, html
import pandas as pd
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

from aladeen.data.contract import CandleValidationError
from aladeen.data.fixtures import (
    DEMO_SYMBOL,
    SUPPORTED_TIMEFRAMES,
    available_symbols,
    available_timeframes,
    load_fixture,
)
from aladeen.data.market_snapshot import MarketDataSnapshot, fetch_market_snapshot
from aladeen.data.mt5_adapter import (
    MT5ConnectionError,
    MT5ConnectionState,
    MT5DataError,
    MT5Error,
    MT5NotInstalledError,
    MT5SymbolError,
    get_mt5_adapter,
)
from aladeen.strategy.service import (
    MSMContext,
    MSMServiceResult,
    calculate_msm,
    is_context_compatible,
)
from aladeen.strategy.types import Direction, MSMSnapshot
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart
from aladeen.ui.market_coordinator import (
    generate_chart_and_status_from_snapshot,
    register_market_coordinator_callbacks,
)
from aladeen.ui.msm_callbacks import (
    get_completed_candle_options,
    register_msm_callbacks,
    render_msm_inspection_table,
)

# ---------------------------------------------------------------------------
# Badge & Banner Styles
# ---------------------------------------------------------------------------

BADGE_STYLE_CONNECTED_BROKER = {
    "padding": "4px 8px",
    "borderRadius": "4px",
    "background": "#1b5e20",
    "color": "#a5d6a7",
    "fontSize": "12px",
}

BADGE_STYLE_TERMINAL_ONLY = {
    "padding": "4px 8px",
    "borderRadius": "4px",
    "background": "#f57f17",
    "color": "#212121",
    "fontSize": "12px",
    "fontWeight": "bold",
}

BADGE_STYLE_DISCONNECTED = {
    "padding": "4px 8px",
    "borderRadius": "4px",
    "background": "#263238",
    "color": "#b0bec5",
    "fontSize": "12px",
}

BANNER_STYLE_DEMO = {
    "background": "#ff9800",
    "color": "#000",
    "textAlign": "center",
    "padding": "8px",
    "fontWeight": "bold",
    "fontSize": "13px",
}

BANNER_STYLE_MT5_CONNECTED = {
    "background": "#2e7d32",
    "color": "#fff",
    "textAlign": "center",
    "padding": "8px",
    "fontWeight": "bold",
    "fontSize": "13px",
}

BANNER_STYLE_MT5_TERMINAL_ONLY = {
    "background": "#e65100",
    "color": "#fff",
    "textAlign": "center",
    "padding": "8px",
    "fontWeight": "bold",
    "fontSize": "13px",
}

BANNER_STYLE_MT5_DISCONNECTED = {
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
                                "Chart Data Source",
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
                                style=BADGE_STYLE_DISCONNECTED,
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


def _build_msm_controls() -> html.Div:
    """Return the MSM Strategy Configuration control panel (R10.2: manual direction & start)."""
    return html.Div(
        id="msm-controls-panel",
        style={
            "background": "#1a1a2e",
            "border": "1px solid #2d2d48",
            "borderRadius": "6px",
            "padding": "14px 16px",
            "margin": "10px 16px",
        },
        children=[
            # Header
            html.Div(
                style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "10px"},
                children=[
                    html.Div([
                        html.H4("📐 Market Structure Marking (MSM) — Configuration", style={"margin": "0 0 4px 0", "color": "#00e5ff"}),
                        html.Span("Pure mathematical structure engine. Identifies confirmed swing points, last support/resistance, and tentative levels.", style={"color": "#888", "fontSize": "12px"}),
                    ]),
                    # MSM Enable Checkbox
                    dcc.Checklist(
                        id="msm-enable-toggle",
                        options=[{"label": " Enable MSM Overlay", "value": "enabled"}],
                        value=[],
                        inline=True,
                        style={"color": "#fff", "fontSize": "13px", "fontWeight": "bold"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
            ),
            # Controls Row (R10.2: initial value=None for direction & start candle)
            html.Div(
                style={"display": "flex", "alignItems": "center", "gap": "16px", "flexWrap": "wrap"},
                children=[
                    # Initial Direction (R10.2: value=None, manual selection required)
                    html.Div([
                        html.Label("Initial Direction", style={"color": "#aaa", "fontSize": "12px", "display": "block", "marginBottom": "4px"}),
                        dcc.RadioItems(
                            id="msm-direction-selector",
                            options=[
                                {"label": " ↗ UPWARD", "value": "UPWARD"},
                                {"label": " ↘ DOWNWARD", "value": "DOWNWARD"},
                            ],
                            value=None,
                            inline=True,
                            style={"color": "#e0e0e0", "fontSize": "13px"},
                            inputStyle={"marginRight": "4px", "marginLeft": "10px"},
                        ),
                    ]),
                    # Starting Candle Dropdown (R10.2: value=None, manual selection required)
                    html.Div([
                        html.Label("Starting Candle (Completed only)", style={"color": "#aaa", "fontSize": "12px", "display": "block", "marginBottom": "4px"}),
                        dcc.Dropdown(
                            id="msm-start-candle-dropdown",
                            options=[],
                            value=None,
                            placeholder="Select completed starting candle...",
                            clearable=False,
                            style={"width": "360px", "color": "#000"},
                        ),
                    ]),
                    # Apply / Calculate Button
                    html.Button(
                        "⚡ Apply / Calculate MSM",
                        id="msm-apply-btn",
                        n_clicks=0,
                        style={
                            "marginTop": "16px",
                            "padding": "7px 20px",
                            "background": "#0091ea",
                            "color": "#fff",
                            "border": "none",
                            "borderRadius": "4px",
                            "cursor": "pointer",
                            "fontWeight": "bold",
                            "fontSize": "13px",
                        },
                    ),
                ],
            ),
            # Edit / Calculation Status line
            html.Div(
                id="msm-edit-status",
                children="MSM is disabled. Check 'Enable MSM Overlay', choose an initial direction and starting candle, and click 'Apply / Calculate MSM'.",
                style={"marginTop": "10px", "fontSize": "12px", "color": "#888"},
            ),
        ],
    )


def _build_msm_inspection_panel() -> html.Div:
    """Return the MSM Structure Inspection and Provenance table panel."""
    return html.Div(
        id="msm-inspection-container",
        style={
            "background": "#151522",
            "border": "1px solid #2a2a3e",
            "borderRadius": "6px",
            "padding": "14px 16px",
            "margin": "10px 16px 20px 16px",
        },
        children=[
            html.Div(
                style={"marginBottom": "10px"},
                children=[
                    html.H4("📊 MSM Swing Points & Structure Inspection", style={"margin": "0 0 4px 0", "color": "#e0e0e0"}),
                    html.Span(
                        "Causal provenance for swing levels. Availability timestamp remains 'Unknown' where confirmation is pending or unrecorded.",
                        style={"color": "#777", "fontSize": "12px"},
                    ),
                ],
            ),
            # Inspection Table Content Area
            html.Div(
                id="msm-inspection-panel",
                children=[
                    html.P("No MSM overlay applied. Enable and apply MSM above to inspect structure swing levels.", style={"color": "#666", "fontSize": "13px", "margin": "8px 0"}),
                ],
            ),
            # Strategy Scope Boundaries Disclaimer
            html.Div(
                "ℹ️ Scope boundary: CHOCH, ISS, TJL, zone activations, and entry signals are not implemented in this milestone (Pure MSM read-only structure phase).",
                style={"fontSize": "11px", "color": "#555", "marginTop": "12px", "borderTop": "1px solid #222233", "paddingTop": "6px"},
            ),
        ],
    )


def build_layout() -> html.Div:
    """Return the complete dashboard layout."""
    return html.Div(
        style={"fontFamily": "Segoe UI, sans-serif", "background": "#14141f", "minHeight": "100vh"},
        children=[
            # Hidden Stores for State Management
            dcc.Store(
                id="mt5-connection-store",
                data={"state": "DISCONNECTED", "symbols": []},
            ),
            dcc.Store(
                id="connection-loss-trigger",
                data=None,
            ),
            dcc.Store(
                id="market-data-store",
                data=None,
            ),
            dcc.Store(
                id="active-request-store",
                data={
                    "token": "req-0",
                    "counter": 0,
                    "context": {"data_source": "demo", "symbol": DEMO_SYMBOL, "timeframe": "H4", "candle_count": 100},
                },
            ),
            dcc.Store(
                id="msm-applied-store",
                data=None,
            ),
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
                "⚠️ DEMO MODE — Viewing synthetic fixtures (MT5 disconnected)",
                id="source-banner",
                style=BANNER_STYLE_DEMO,
            ),
            # Controls
            _build_controls(),
            # Main chart
            dcc.Graph(id="main-chart", config={"displayModeBar": True}),
            # MSM Strategy Configuration Panel
            _build_msm_controls(),
            # MSM Inspection Table Panel
            _build_msm_inspection_panel(),
        ],
    )


# ---------------------------------------------------------------------------
# Pure Dashboard State Logic (Separated for Testing)
# ---------------------------------------------------------------------------


def process_connection_and_banner(
    triggered_id: str,
    data_source: str,
    store_data: dict,
    loss_trigger_data: dict | None = None,
    adapter: Any = None,
    current_symbol: str | None = None,
) -> dict[str, Any]:
    """Calculate connection badge, banner, and symbol options atomically."""
    if adapter is None:
        adapter = get_mt5_adapter()

    conn_state_str = store_data.get("state", "DISCONNECTED") if store_data else "DISCONNECTED"
    cached_symbols: list[str] = store_data.get("symbols", []) if store_data else []
    error_msg: str | None = None

    if triggered_id == "connection-loss-trigger" and loss_trigger_data:
        trigger_type = loss_trigger_data.get("type", "connection_loss")
        if trigger_type == "connection_loss":
            adapter.disconnect()
            conn_state_str = MT5ConnectionState.DISCONNECTED.value
            cached_symbols = []
            error_msg = f"Connection Lost during refresh: {loss_trigger_data.get('error', 'Unknown error')}"
        elif trigger_type == "state_change":
            conn_state_str = loss_trigger_data.get("new_state", conn_state_str)

    elif triggered_id == "connect-btn":
        try:
            state_enum = adapter.connect()
            conn_state_str = state_enum.value
            cached_symbols = adapter.get_symbols()
        except (MT5NotInstalledError, MT5ConnectionError) as e:
            adapter.disconnect()
            conn_state_str = MT5ConnectionState.DISCONNECTED.value
            cached_symbols = []
            error_msg = str(e)
        except Exception as e:
            adapter.disconnect()
            conn_state_str = MT5ConnectionState.DISCONNECTED.value
            cached_symbols = []
            error_msg = f"Unexpected connection error: {e}"

    elif triggered_id == "disconnect-btn":
        adapter.disconnect()
        conn_state_str = MT5ConnectionState.DISCONNECTED.value
        cached_symbols = []

    # Verify adapter connection health and synchronize state
    if conn_state_str != MT5ConnectionState.DISCONNECTED.value:
        current_adapter_state = adapter.get_connection_state().value
        if current_adapter_state == MT5ConnectionState.DISCONNECTED.value:
            conn_state_str = MT5ConnectionState.DISCONNECTED.value
            cached_symbols = []
        else:
            conn_state_str = current_adapter_state

    # Badge mapping
    if conn_state_str == MT5ConnectionState.CONNECTED_TO_BROKER.value:
        badge_text = "🟢 Connected to Broker"
        badge_style = BADGE_STYLE_CONNECTED_BROKER
    elif conn_state_str == MT5ConnectionState.TERMINAL_ONLY.value:
        badge_text = "🟡 Terminal Ready (Broker Offline)"
        badge_style = BADGE_STYLE_TERMINAL_ONLY
    else:
        badge_text = "Disconnected"
        badge_style = BADGE_STYLE_DISCONNECTED

    # Banner mapping
    if data_source == "demo":
        if conn_state_str == MT5ConnectionState.CONNECTED_TO_BROKER.value:
            banner_text = "⚠️ DEMO MODE — Viewing synthetic fixtures (MT5 connected to broker in background)"
        elif conn_state_str == MT5ConnectionState.TERMINAL_ONLY.value:
            banner_text = "⚠️ DEMO MODE — Viewing synthetic fixtures (MT5 terminal ready, broker offline in background)"
        else:
            banner_text = "⚠️ DEMO MODE — Viewing synthetic fixtures (MT5 disconnected)"
        banner_style = BANNER_STYLE_DEMO
        sym_options = [{"label": s, "value": s} for s in available_symbols()]
        if current_symbol and current_symbol in available_symbols():
            sym_value = current_symbol
        else:
            sym_value = available_symbols()[0]
        sym_disabled = True
    else:
        # MT5 mode
        if conn_state_str == MT5ConnectionState.CONNECTED_TO_BROKER.value:
            banner_text = "🟢 MT5 CONNECTED — Local Terminal Read-Only Market Data (Broker Connected)"
            banner_style = BANNER_STYLE_MT5_CONNECTED
        elif conn_state_str == MT5ConnectionState.TERMINAL_ONLY.value:
            banner_text = "🟡 MT5 TERMINAL READY — Broker Offline (Cached local history only)"
            banner_style = BANNER_STYLE_MT5_TERMINAL_ONLY
        else:
            banner_text = "🔴 MT5 DISCONNECTED — Click '⚡ Connect MT5' to load local terminal data"
            banner_style = BANNER_STYLE_MT5_DISCONNECTED

        if conn_state_str != MT5ConnectionState.DISCONNECTED.value and cached_symbols:
            sym_options = [{"label": s, "value": s} for s in cached_symbols]
            if current_symbol and current_symbol in cached_symbols:
                sym_value = current_symbol
            elif "EURUSD" in cached_symbols:
                sym_value = "EURUSD"
            else:
                sym_value = cached_symbols[0]
            sym_disabled = False
        elif conn_state_str != MT5ConnectionState.DISCONNECTED.value and not cached_symbols:
            sym_options = [{"label": "No symbols available", "value": ""}]
            sym_value = ""
            sym_disabled = True
        else:
            sym_options = [{"label": "Connect to MT5 first", "value": ""}]
            sym_value = ""
            sym_disabled = True

    if error_msg:
        alert_children = [html.B("MT5 Alert: "), html.Span(error_msg)]
        alert_style = {
            "display": "block",
            "background": "#b71c1c",
            "color": "#ffebee",
            "padding": "8px 12px",
            "borderRadius": "4px",
            "fontSize": "13px",
            "marginTop": "6px",
        }
    else:
        alert_children = []
        alert_style = {"display": "none"}

    new_store = {"state": conn_state_str, "symbols": cached_symbols}

    return {
        "store_data": new_store,
        "badge_text": badge_text,
        "badge_style": badge_style,
        "banner_text": banner_text,
        "banner_style": banner_style,
        "sym_options": sym_options,
        "sym_value": sym_value,
        "sym_disabled": sym_disabled,
        "alert_children": alert_children,
        "alert_style": alert_style,
    }





def generate_chart_and_status_with_trigger(
    data_source: str,
    symbol: str | None,
    timeframe: str,
    candle_count: int,
    is_connected: bool,
    adapter: Any = None,
    current_state: str | None = None,
    msm_applied: dict | None = None,
) -> tuple[go.Figure, str, dict | None]:
    """Generate chart and status text. Returns (figure, status_text, loss_trigger)."""
    snapshot, loss_trigger = fetch_market_snapshot(
        data_source=data_source,
        symbol=symbol,
        timeframe=timeframe,
        candle_count=candle_count,
        is_connected=is_connected,
        adapter=adapter,
        current_state=current_state,
    )
    fig, status = generate_chart_and_status_from_snapshot(snapshot, msm_applied=msm_applied)
    return fig, status, loss_trigger


def generate_chart_and_status(
    data_source: str,
    symbol: str | None,
    timeframe: str,
    candle_count: int,
    is_connected: bool,
    adapter: Any = None,
    msm_applied: dict | None = None,
) -> tuple[go.Figure, str]:
    """Compatibility helper returning (figure, status_text)."""
    fig, status, _ = generate_chart_and_status_with_trigger(
        data_source=data_source,
        symbol=symbol,
        timeframe=timeframe,
        candle_count=candle_count,
        is_connected=is_connected,
        adapter=adapter,
        msm_applied=msm_applied,
    )
    return fig, status


def process_dashboard_update(
    triggered_id: str,
    data_source: str,
    current_symbol: str | None,
    timeframe: str,
    candle_count: int,
    store_data: dict,
    adapter: Any = None,
    msm_applied: dict | None = None,
) -> dict[str, Any]:
    """Compatibility coordinator function for unit tests."""
    if adapter is None:
        adapter = get_mt5_adapter()

    conn_info = process_connection_and_banner(
        triggered_id=triggered_id,
        data_source=data_source,
        store_data=store_data,
        loss_trigger_data=None,
        adapter=adapter,
        current_symbol=current_symbol,
    )
    is_conn = conn_info["store_data"].get("state") != MT5ConnectionState.DISCONNECTED.value
    sym = current_symbol if current_symbol and is_conn and current_symbol in conn_info["store_data"].get("symbols", []) else conn_info["sym_value"]

    fig, status, loss_trigger = generate_chart_and_status_with_trigger(
        data_source=data_source,
        symbol=sym,
        timeframe=timeframe,
        candle_count=candle_count,
        is_connected=is_conn,
        adapter=adapter,
        current_state=conn_info["store_data"].get("state"),
        msm_applied=msm_applied,
    )

    if loss_trigger:
        conn_info = process_connection_and_banner(
            "connection-loss-trigger",
            data_source,
            conn_info["store_data"],
            loss_trigger,
            adapter,
            current_symbol=sym,
        )

    return {
        "store_data": conn_info["store_data"],
        "badge_text": conn_info["badge_text"],
        "badge_style": conn_info["badge_style"],
        "banner_text": conn_info["banner_text"],
        "banner_style": conn_info["banner_style"],
        "sym_options": conn_info["sym_options"],
        "sym_value": sym if data_source == "mt5" and is_conn and sym in conn_info["store_data"].get("symbols", []) else conn_info["sym_value"],
        "sym_disabled": conn_info["sym_disabled"],
        "alert_children": conn_info["alert_children"],
        "alert_style": conn_info["alert_style"],
        "figure": fig,
        "status_text": status,
    }


# ---------------------------------------------------------------------------
# Callbacks Registration
# ---------------------------------------------------------------------------


def register_callbacks(app: Dash, adapter: Any = None) -> tuple[Any, Any]:
    """Register all Dash callbacks on *app*."""
    if adapter is None:
        adapter = get_mt5_adapter()

    # Callback 1: Connection & Source & Symbol Options
    @app.callback(
        Output("mt5-connection-store", "data"),
        Output("connection-badge", "children"),
        Output("connection-badge", "style"),
        Output("source-banner", "children"),
        Output("source-banner", "style"),
        Output("symbol-selector", "options"),
        Output("symbol-selector", "value"),
        Output("symbol-selector", "disabled"),
        Output("error-alert", "children"),
        Output("error-alert", "style"),
        Input("connect-btn", "n_clicks"),
        Input("disconnect-btn", "n_clicks"),
        Input("data-source-selector", "value"),
        Input("connection-loss-trigger", "data"),
        State("mt5-connection-store", "data"),
        State("symbol-selector", "value"),
    )
    def handle_connection_and_options(
        _connect_clicks: int,
        _disconnect_clicks: int,
        data_source: str,
        loss_trigger: dict | None,
        store_data: dict,
        current_symbol: str | None,
        triggered_id: str | None = None,
    ) -> tuple:
        if triggered_id is None:
            ctx = callback_context
            triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
        if not triggered_id and loss_trigger is not None:
            triggered_id = "connection-loss-trigger"

        logger.debug(f"handle_connection triggered={triggered_id}, source={data_source}")

        res = process_connection_and_banner(
            triggered_id=triggered_id,
            data_source=data_source,
            store_data=store_data,
            loss_trigger_data=loss_trigger,
            adapter=adapter,
            current_symbol=current_symbol,
        )

        return (
            res["store_data"],
            res["badge_text"],
            res["badge_style"],
            res["banner_text"],
            res["banner_style"],
            res["sym_options"],
            res["sym_value"],
            res["sym_disabled"],
            res["alert_children"],
            res["alert_style"],
        )

    # Register market data coordinator callbacks (single-fetch coordinator + chart renderer)
    update_market_data, render_chart_from_snapshot = register_market_coordinator_callbacks(app, adapter=adapter)

    def update_chart(
        data_source: str = "demo",
        symbol: str | None = None,
        timeframe: str = "H4",
        candle_count: int = 100,
        _n_clicks: int = 0,
        store_data: dict | None = None,
        msm_applied: dict | None = None,
    ) -> tuple[go.Figure, str, Any]:
        """Compatibility wrapper invoking update_market_data and render_chart_from_snapshot."""
        snap_dict, trigger, _ = update_market_data(
            data_source=data_source,
            symbol=symbol,
            timeframe=timeframe,
            candle_count=candle_count,
            _n_clicks=_n_clicks,
            store_data=store_data,
        )
        fig, status = render_chart_from_snapshot(snap_dict, msm_applied=msm_applied)
        return fig, status, trigger

    # Register MSM callbacks from focused module
    register_msm_callbacks(app, adapter=adapter)

    return handle_connection_and_options, update_chart
