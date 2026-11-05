"""Dashboard layout and Dash callbacks.

Defines the page structure and wires up interactivity.
Chart construction and data loading are delegated to other modules.
"""

from __future__ import annotations

from dash import Dash, Input, Output, callback, dcc, html

from aladeen.data.fixtures import (
    DEMO_SYMBOL,
    SUPPORTED_TIMEFRAMES,
    available_symbols,
    available_timeframes,
    load_fixture,
)
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart

# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

_DEMO_BANNER = html.Div(
    "⚠️  DEMO DATA — NOT CONNECTED TO MT5",
    style={
        "background": "#ff9800",
        "color": "#000",
        "textAlign": "center",
        "padding": "8px",
        "fontWeight": "bold",
        "fontSize": "14px",
    },
)


def _build_controls() -> html.Div:
    """Return the control bar with symbol, timeframe, and refresh."""
    symbols = available_symbols()
    timeframes = available_timeframes()

    return html.Div(
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "16px",
            "padding": "12px 16px",
            "background": "#1e1e2f",
        },
        children=[
            # Symbol selector — disabled when only one fixture symbol
            html.Div(
                [
                    html.Label("Symbol", style={"color": "#aaa", "fontSize": "12px"}),
                    dcc.Dropdown(
                        id="symbol-selector",
                        options=[{"label": s, "value": s} for s in symbols],
                        value=symbols[0],
                        clearable=False,
                        disabled=len(symbols) == 1,
                        style={"width": "180px"},
                    ),
                ]
            ),
            # Timeframe selector
            html.Div(
                [
                    html.Label(
                        "Timeframe", style={"color": "#aaa", "fontSize": "12px"}
                    ),
                    dcc.Dropdown(
                        id="timeframe-selector",
                        options=[{"label": tf, "value": tf} for tf in timeframes],
                        value="H4",
                        clearable=False,
                        style={"width": "120px"},
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
                },
            ),
            # Connection / status area
            html.Div(
                id="status-area",
                style={
                    "marginTop": "16px",
                    "marginLeft": "auto",
                    "color": "#ff9800",
                    "fontSize": "13px",
                },
            ),
        ],
    )


def _build_placeholder(title: str, description: str) -> html.Div:
    """Return a clearly labeled placeholder panel."""
    return html.Div(
        style={
            "border": "1px dashed #555",
            "borderRadius": "6px",
            "padding": "20px",
            "margin": "12px 16px",
            "color": "#888",
        },
        children=[
            html.H4(
                title,
                style={"margin": "0 0 6px 0", "color": "#aaa"},
            ),
            html.P(description, style={"margin": 0, "fontSize": "13px"}),
        ],
    )


def build_layout() -> html.Div:
    """Return the complete dashboard layout."""
    return html.Div(
        style={"fontFamily": "Segoe UI, sans-serif", "background": "#14141f"},
        children=[
            # Title bar
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "10px 16px",
                    "background": "#0d0d1a",
                },
                children=[
                    html.H2(
                        "Aladeen / TopG",
                        style={"margin": 0, "color": "#e0e0e0"},
                    ),
                    html.Span(
                        "Dashboard",
                        style={
                            "marginLeft": "10px",
                            "color": "#777",
                            "fontSize": "16px",
                        },
                    ),
                ],
            ),
            # Demo-data banner
            _DEMO_BANNER,
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
# Callbacks
# ---------------------------------------------------------------------------


def register_callbacks(app: Dash) -> None:
    """Register all Dash callbacks on *app*."""

    @app.callback(
        Output("main-chart", "figure"),
        Output("status-area", "children"),
        Input("symbol-selector", "value"),
        Input("timeframe-selector", "value"),
        Input("refresh-btn", "n_clicks"),
    )
    def update_chart(
        symbol: str, timeframe: str, _n_clicks: int
    ) -> tuple:
        """Reload fixture data and rebuild the chart."""
        if timeframe not in SUPPORTED_TIMEFRAMES:
            msg = (
                f"Timeframe {timeframe} is not available in demo mode. "
                f"Supported demo timeframes: {', '.join(SUPPORTED_TIMEFRAMES)}."
            )
            fig = create_empty_chart(msg)
            return fig, f"⚠️ {msg}"

        df = load_fixture(symbol, timeframe)

        if df is None or df.empty:
            msg = f"No demo data for {symbol} / {timeframe}."
            fig = create_empty_chart(msg)
            return fig, f"⚠️ {msg}"

        fig = create_candlestick_chart(df, symbol, timeframe, is_demo=True)
        status = (
            f"Demo mode — showing {len(df)} fixed {timeframe} candles for {symbol}. "
            f"Not connected to MT5."
        )
        return fig, status
