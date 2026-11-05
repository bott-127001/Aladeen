"""Focused MSM Coordinator and Dash Callbacks Module.

Separates MSM UI interactions and callbacks from the layout foundation:
- Starting candle dropdown extraction using validated completion predicate.
- MSM Configuration application, unapplied edit tracking, and fail-closed validation.
- Causal provenance inspection table rendering (retaining 'Unknown' where unrecorded).
- Context isolation across symbol / timeframe / data source transitions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import dash
from dash import Dash, Input, Output, State, callback_context, html
import pandas as pd

logger = logging.getLogger(__name__)

from aladeen.data.fixtures import DEMO_SYMBOL, SUPPORTED_TIMEFRAMES, load_fixture
from aladeen.data.mt5_adapter import MT5ConnectionState, get_mt5_adapter
from aladeen.strategy.service import (
    MSMContext,
    MSMServiceResult,
    calculate_msm,
    is_candle_completed,
    is_context_compatible,
    validate_candle_completion,
)
from aladeen.strategy.types import Direction, MSMSnapshot


def get_completed_candle_options(df: Optional[pd.DataFrame]) -> list[dict]:
    """Extract list of completed candle options from *df* for the start candle selector.

    Rules & Invariants (R10.1):
    ---------------------------
    - Uses the exact shared completion predicate `is_candle_completed()`.
    - Strictly rejects missing or null completion fields.
    - Excludes forming / unconfirmed candles (`is_forming == True` or `bar_status != "CONFIRMED_COMPLETED"`).
    """
    if df is None or df.empty:
        return []

    options = []
    for row_pos, (ts, row) in enumerate(df.iterrows()):
        try:
            completed = is_candle_completed(row_pos, row)
        except Exception as e:
            logger.warning(f"Row {row_pos} failed completion validation in dropdown extraction: {e}")
            continue

        if not completed:
            continue

        ts_str = ts.strftime("%Y-%m-%d %H:%M UTC")
        iso_str = ts.isoformat()
        open_val = float(row["open"])
        high_val = float(row["high"])
        low_val = float(row["low"])
        close_val = float(row["close"])
        label = f"{ts_str} | O:{open_val:.2f} H:{high_val:.2f} L:{low_val:.2f} C:{close_val:.2f}"
        options.append({"label": label, "value": iso_str})

    return options


def render_msm_inspection_table(snapshot: MSMSnapshot, context: MSMContext) -> html.Div:
    """Generate the HTML inspection table for an applied MSM snapshot.

    Rules & Invariants (R10.3, R10.4):
    -----------------------------------
    - Pair labels use pair_index directly: H1, L1, Pair #1 (R10.3).
    - Explicitly renders last support / resistance summary values (R10.4).
    - Availability timestamps remain 'Unknown' where not established.
    """
    table_header = html.Thead(
        html.Tr(
            style={"background": "#1e1e30", "color": "#a0a0b8", "fontSize": "12px", "textAlign": "left"},
            children=[
                html.Th("Level Type", style={"padding": "8px 12px"}),
                html.Th("Price", style={"padding": "8px 12px"}),
                html.Th("Source Candle (UTC)", style={"padding": "8px 12px"}),
                html.Th("Identified At", style={"padding": "8px 12px"}),
                html.Th("Confirmed At", style={"padding": "8px 12px"}),
                html.Th("Status", style={"padding": "8px 12px"}),
            ],
        )
    )

    rows = []
    pairs = snapshot.confirmed_pairs
    for p in pairs:
        # Confirmed High (R10.3: direct pair_index)
        h = p.high
        id_h = h.identified_time.strftime("%Y-%m-%d %H:%M UTC") if h.identified_time else "Unknown"
        conf_h = h.confirmed_time.strftime("%Y-%m-%d %H:%M UTC") if h.confirmed_time else "Unknown"
        rows.append(
            html.Tr(
                style={"borderBottom": "1px solid #232338", "fontSize": "12px", "color": "#e0e0e0"},
                children=[
                    html.Td([html.Span("▲ ", style={"color": "#00e676"}), f"Confirmed High (H{p.pair_index})"], style={"padding": "6px 12px"}),
                    html.Td(f"{h.price:.4f}", style={"padding": "6px 12px", "fontWeight": "bold", "color": "#00e676"}),
                    html.Td(f"{h.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Bar #{h.candle_index})", style={"padding": "6px 12px"}),
                    html.Td(f"{id_h} (Bar #{h.identified_bar_index})", style={"padding": "6px 12px"}),
                    html.Td(f"{conf_h} (Bar #{h.confirmed_bar_index})", style={"padding": "6px 12px"}),
                    html.Td(html.Span("CONFIRMED", style={"padding": "2px 6px", "borderRadius": "3px", "background": "#1b5e20", "color": "#a5d6a7", "fontSize": "10px"}), style={"padding": "6px 12px"}),
                ],
            )
        )
        # Confirmed Low (R10.3: direct pair_index)
        low = p.low
        id_l = low.identified_time.strftime("%Y-%m-%d %H:%M UTC") if low.identified_time else "Unknown"
        conf_l = low.confirmed_time.strftime("%Y-%m-%d %H:%M UTC") if low.confirmed_time else "Unknown"
        rows.append(
            html.Tr(
                style={"borderBottom": "1px solid #232338", "fontSize": "12px", "color": "#e0e0e0"},
                children=[
                    html.Td([html.Span("▼ ", style={"color": "#ff5252"}), f"Confirmed Low (L{p.pair_index})"], style={"padding": "6px 12px"}),
                    html.Td(f"{low.price:.4f}", style={"padding": "6px 12px", "fontWeight": "bold", "color": "#ff5252"}),
                    html.Td(f"{low.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Bar #{low.candle_index})", style={"padding": "6px 12px"}),
                    html.Td(f"{id_l} (Bar #{low.identified_bar_index})", style={"padding": "6px 12px"}),
                    html.Td(f"{conf_l} (Bar #{low.confirmed_bar_index})", style={"padding": "6px 12px"}),
                    html.Td(html.Span("CONFIRMED", style={"padding": "2px 6px", "borderRadius": "3px", "background": "#1b5e20", "color": "#a5d6a7", "fontSize": "10px"}), style={"padding": "6px 12px"}),
                ],
            )
        )

    # Tentative Point
    if snapshot.tentative_point is not None:
        tent = snapshot.tentative_point
        id_t = tent.identified_time.strftime("%Y-%m-%d %H:%M UTC") if tent.identified_time else "Unknown"
        rows.append(
            html.Tr(
                style={"borderBottom": "1px solid #232338", "fontSize": "12px", "color": "#e0e0e0", "background": "#222218"},
                children=[
                    html.Td([html.Span("◇ ", style={"color": "#ffd600"}), "Tentative Swing Level"], style={"padding": "6px 12px"}),
                    html.Td(f"{tent.price:.4f}", style={"padding": "6px 12px", "fontWeight": "bold", "color": "#ffd600"}),
                    html.Td(f"{tent.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Bar #{tent.candle_index})", style={"padding": "6px 12px"}),
                    html.Td(f"{id_t} (Bar #{tent.identified_bar_index})", style={"padding": "6px 12px"}),
                    html.Td("Pending Break", style={"padding": "6px 12px", "color": "#ffd600"}),
                    html.Td(html.Span("TENTATIVE", style={"padding": "2px 6px", "borderRadius": "3px", "background": "#f57f17", "color": "#212121", "fontSize": "10px", "fontWeight": "bold"}), style={"padding": "6px 12px"}),
                ],
            )
        )

    table_body = html.Tbody(rows) if rows else html.Tbody([
        html.Tr(html.Td("No swing levels identified yet. Currently searching for a valid pullback.", colSpan=6, style={"padding": "12px", "color": "#888", "textAlign": "center"}))
    ])

    summary_items = [
        html.Span([html.B("Engine State: "), html.Code(snapshot.state.value, style={"color": "#00b0ff"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Trend Status: "), html.Span(snapshot.trend_status, style={"color": "#00e5ff"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Confirmed Pairs: "), html.Span(str(len(snapshot.confirmed_pairs)), style={"color": "#00e676", "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Starting Candle: "), html.Span(context.start_candle_time.strftime("%Y-%m-%d %H:%M UTC"), style={"color": "#ffd54f"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Direction: "), html.Span(context.direction.value, style={"color": "#ff80ab"})], style={"fontSize": "12px", "color": "#ccc"}),
    ]

    # R10.4: Render explicit last support / resistance summary indicators
    if snapshot.last_support is not None:
        summary_items.append(
            html.Span(
                [html.B("Last Support: "), html.Span(f"{snapshot.last_support.price:.4f} (Bar #{snapshot.last_support.candle_index})", style={"color": "#76ff03", "fontWeight": "bold"})],
                style={"fontSize": "12px", "color": "#ccc"},
            )
        )
    if snapshot.last_resistance is not None:
        summary_items.append(
            html.Span(
                [html.B("Last Resistance: "), html.Span(f"{snapshot.last_resistance.price:.4f} (Bar #{snapshot.last_resistance.candle_index})", style={"color": "#ff1744", "fontWeight": "bold"})],
                style={"fontSize": "12px", "color": "#ccc"},
            )
        )

    summary_bar = html.Div(
        style={"display": "flex", "gap": "14px", "alignItems": "center", "marginBottom": "10px", "flexWrap": "wrap"},
        children=summary_items,
    )

    return html.Div([
        summary_bar,
        html.Table(
            [table_header, table_body],
            style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c"},
        ),
    ])


def process_msm_dropdown_update(
    data_source: str,
    symbol: str | None,
    timeframe: str,
    candle_count: int,
    store_data: dict | None,
    current_value: str | None,
    adapter: Any = None,
) -> tuple[list[dict], str | None]:
    """Pure helper returning updated (options, selected_value) for the starting candle dropdown (R10.2)."""
    if adapter is None:
        adapter = get_mt5_adapter()

    df: Optional[pd.DataFrame] = None
    if data_source == "demo":
        if timeframe in SUPPORTED_TIMEFRAMES:
            df = load_fixture(DEMO_SYMBOL, timeframe)
    else:
        is_connected = store_data.get("state", "DISCONNECTED") != MT5ConnectionState.DISCONNECTED.value if store_data else False
        if is_connected and symbol:
            try:
                df = adapter.fetch_candles(symbol, timeframe, count=candle_count)
            except Exception:
                df = None

    options = get_completed_candle_options(df)
    valid_values = [o["value"] for o in options]

    # R10.2: Do NOT silently auto-select the first candle! Preserve selection only if still valid; else None.
    new_value: Optional[str] = current_value if current_value and current_value in valid_values else None

    return options, new_value


def process_msm_controls_update(
    triggered_id: str,
    enable_toggle_val: list[str],
    direction_val: str | None,
    start_candle_val: str | None,
    data_source: str,
    symbol: str | None,
    timeframe: str,
    candle_count: int,
    store_data: dict | None,
    applied_data: dict | None,
    adapter: Any = None,
) -> tuple[dict | None, str, dict, Any]:
    """Pure coordinator function for MSM controls, application, and unapplied edit detection."""
    if adapter is None:
        adapter = get_mt5_adapter()

    is_enabled = "enabled" in enable_toggle_val if enable_toggle_val else False

    # 1. Handle MSM Disabled
    if not is_enabled:
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#888"}
        panel = html.P(
            "MSM is currently disabled. Check 'Enable MSM Overlay' and click 'Apply / Calculate MSM' to inspect structure swing levels.",
            style={"color": "#666", "fontSize": "13px", "margin": "8px 0"},
        )
        return (
            None,
            "MSM is disabled. Check 'Enable MSM Overlay' and click 'Apply / Calculate MSM' to mark structure.",
            status_style,
            panel,
        )

    # 2. Context changed (symbol / timeframe / source) -> Incompatible markings disappear
    if triggered_id in {"data-source-selector", "symbol-selector", "timeframe-selector"}:
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ffd54f"}
        panel = html.P(
            "Context changed. Please select an initial direction and completed starting candle, then click 'Apply / Calculate MSM'.",
            style={"color": "#888", "fontSize": "13px", "margin": "8px 0"},
        )
        return (
            None,
            "Context changed. Select direction and starting candle, then click 'Apply / Calculate MSM'.",
            status_style,
            panel,
        )

    # 3. Detect unapplied edits without silently recalculating
    if triggered_id in {"msm-direction-selector", "msm-start-candle-dropdown"}:
        if applied_data and applied_data.get("enabled", False):
            dir_diff = applied_data.get("direction") != direction_val
            start_diff = applied_data.get("start_candle_time") != start_candle_val
            if dir_diff or start_diff:
                status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ffd600", "fontWeight": "bold"}
                return (
                    applied_data,  # Preserve existing applied configuration without recalculation
                    "🟡 Unapplied changes (Click '⚡ Apply / Calculate MSM' to update)",
                    status_style,
                    dash.no_update,
                )

    # 4. Handle Apply button click
    if triggered_id == "msm-apply-btn":
        # R10.2: Direction must be explicitly selected
        if not direction_val or direction_val not in {"UPWARD", "DOWNWARD"}:
            status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
            panel = html.Div("Please select an initial direction (↗ UPWARD or ↘ DOWNWARD).", style={"color": "#ff5252"})
            return (applied_data, "❌ Error: Initial direction not selected.", status_style, panel)

        # R10.2: Starting candle must be explicitly selected
        if not start_candle_val:
            status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
            panel = html.Div("Please select a verified completed starting candle from the dropdown.", style={"color": "#ff5252"})
            return (applied_data, "❌ Error: No starting candle selected.", status_style, panel)

        active_sym = DEMO_SYMBOL if data_source == "demo" else (symbol or "")
        df: Optional[pd.DataFrame] = None
        if data_source == "demo":
            if timeframe in SUPPORTED_TIMEFRAMES:
                df = load_fixture(DEMO_SYMBOL, timeframe)
        else:
            is_connected = store_data.get("state", "DISCONNECTED") != MT5ConnectionState.DISCONNECTED.value if store_data else False
            if is_connected and active_sym:
                try:
                    df = adapter.fetch_candles(active_sym, timeframe, count=candle_count)
                except Exception as e:
                    status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252"}
                    panel = html.Div(f"Failed to fetch market data: {e}", style={"color": "#ff5252"})
                    return (None, f"❌ Data Fetch Error: {e}", status_style, panel)

        if df is None or df.empty:
            status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252"}
            panel = html.Div("No chart data available to calculate MSM.", style={"color": "#ff5252"})
            return (None, "❌ Error: No data available.", status_style, panel)

        try:
            msm_ctx = MSMContext(
                data_source=data_source,
                symbol=active_sym,
                timeframe=timeframe,
                start_candle_time=start_candle_val,
                direction=Direction(direction_val),
                enabled=True,
            )
            res = calculate_msm(df, msm_ctx)
            if res.is_valid and res.snapshot is not None:
                pair_cnt = len(res.snapshot.confirmed_pairs)
                status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#00e676", "fontWeight": "bold"}
                status_text = (
                    f"🟢 Applied: {msm_ctx.direction.value} from "
                    f"{msm_ctx.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')} | "
                    f"{pair_cnt} pairs confirmed | {res.snapshot.trend_status}"
                )
                panel = render_msm_inspection_table(res.snapshot, msm_ctx)
                return (msm_ctx.to_dict(), status_text, status_style, panel)
            else:
                status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
                panel = html.Div(f"Calculation failed: {res.error}", style={"color": "#ff5252"})
                return (None, f"❌ MSM Error: {res.error}", status_style, panel)
        except Exception as e:
            status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252"}
            panel = html.Div(f"MSM Exception: {e}", style={"color": "#ff5252"})
            return (None, f"❌ MSM Exception: {e}", status_style, panel)

    # Default fallback
    status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#888"}
    return (
        dash.no_update,
        "MSM enabled. Select initial direction and completed starting candle, then click '⚡ Apply / Calculate MSM'.",
        status_style,
        dash.no_update,
    )


def register_msm_callbacks(app: Dash, adapter: Any = None) -> tuple[Any, Any]:
    """Register MSM-specific callbacks on *app*."""
    if adapter is None:
        adapter = get_mt5_adapter()

    # Callback 3: Update Starting Candle Dropdown Options
    @app.callback(
        Output("msm-start-candle-dropdown", "options"),
        Output("msm-start-candle-dropdown", "value"),
        Input("data-source-selector", "value"),
        Input("symbol-selector", "value"),
        Input("timeframe-selector", "value"),
        Input("candle-count-selector", "value"),
        Input("refresh-btn", "n_clicks"),
        Input("mt5-connection-store", "data"),
        State("msm-start-candle-dropdown", "value"),
    )
    def update_msm_dropdown_options(
        data_source: str,
        symbol: str | None,
        timeframe: str,
        candle_count: int,
        _refresh_clicks: int,
        store_data: dict | None,
        current_value: str | None,
    ) -> tuple[list[dict], str | None]:
        return process_msm_dropdown_update(
            data_source=data_source,
            symbol=symbol,
            timeframe=timeframe,
            candle_count=candle_count,
            store_data=store_data,
            current_value=current_value,
            adapter=adapter,
        )

    # Callback 4: Handle MSM Controls, Application, and Inspection Panel
    @app.callback(
        Output("msm-applied-store", "data"),
        Output("msm-edit-status", "children"),
        Output("msm-edit-status", "style"),
        Output("msm-inspection-panel", "children"),
        Input("msm-apply-btn", "n_clicks"),
        Input("msm-enable-toggle", "value"),
        Input("msm-direction-selector", "value"),
        Input("msm-start-candle-dropdown", "value"),
        Input("data-source-selector", "value"),
        Input("symbol-selector", "value"),
        Input("timeframe-selector", "value"),
        State("candle-count-selector", "value"),
        State("mt5-connection-store", "data"),
        State("msm-applied-store", "data"),
    )
    def handle_msm_controls(
        apply_clicks: int,
        enable_toggle_val: list[str],
        direction_val: str | None,
        start_candle_val: str | None,
        data_source: str,
        symbol: str | None,
        timeframe: str,
        candle_count: int,
        store_data: dict | None,
        applied_data: dict | None,
    ) -> tuple[dict | None, str, dict, Any]:
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        return process_msm_controls_update(
            triggered_id=triggered_id,
            enable_toggle_val=enable_toggle_val,
            direction_val=direction_val,
            start_candle_val=start_candle_val,
            data_source=data_source,
            symbol=symbol,
            timeframe=timeframe,
            candle_count=candle_count,
            store_data=store_data,
            applied_data=applied_data,
            adapter=adapter,
        )

    return update_msm_dropdown_options, handle_msm_controls
