"""Focused MSM Coordinator and Dash Callbacks Module.

Implements the coherent market-data snapshot consumer architecture:
- Zero consumer-side fallback fetching (R12.1).
- Starting candle dropdown options extracted from the shared market snapshot.
- MSM Configuration application, unapplied edit tracking, and fail-closed validation.
- Causal provenance inspection table rendering (with revision ID and exact 1-based labels).
- Active request-generation and current-context publication guards (R12.3).
- Accurate classification of calculation vs. window-shift diagnostics (R12.4).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import dash
from dash import Dash, Input, Output, State, callback_context, html
import pandas as pd

logger = logging.getLogger(__name__)

from aladeen.data.fixtures import DEMO_SYMBOL, SUPPORTED_TIMEFRAMES, load_fixture
from aladeen.data.market_snapshot import MarketDataSnapshot
from aladeen.strategy.service import (
    MSMContext,
    MSMServiceResult,
    calculate_msm,
    is_candle_completed,
    is_context_compatible,
    validate_candle_completion,
)
from aladeen.strategy.types import Direction, MSMSnapshot


def get_completed_candle_options(snapshot_or_df: Any) -> list[dict]:
    """Extract list of completed candle options from *snapshot_or_df*.

    Zero fallback fetching: if snapshot_or_df is None, returns empty list.
    """
    if snapshot_or_df is None:
        return []

    if isinstance(snapshot_or_df, MarketDataSnapshot):
        if snapshot_or_df.fetch_status != "SUCCESS" or not snapshot_or_df.candles_data:
            return []
        df = snapshot_or_df.to_dataframe()
    elif isinstance(snapshot_or_df, dict):
        if snapshot_or_df.get("fetch_status") != "SUCCESS" or not snapshot_or_df.get("candles_data"):
            return []
        snap = MarketDataSnapshot.from_dict(snapshot_or_df)
        df = snap.to_dataframe()
    elif isinstance(snapshot_or_df, pd.DataFrame):
        df = snapshot_or_df
    else:
        return []

    if df.empty:
        return []

    options = []
    for row_pos, (ts, row) in enumerate(df.iterrows()):
        completed = is_candle_completed(row_pos, row)
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


def process_msm_dropdown_update(
    snapshot_or_df: Any = None,
    current_value: str | None = None,
) -> tuple[list[dict], str | None]:
    """Pure coordinator function for updating starting candle dropdown options.

    R12.1: Zero fallback fetching: consumers never fetch independently.
    """
    options = get_completed_candle_options(snapshot_or_df)
    valid_values = [o["value"] for o in options]
    new_value: Optional[str] = current_value if current_value and current_value in valid_values else None
    return options, new_value


def render_msm_inspection_table(
    snapshot: MSMSnapshot,
    context: MSMContext,
    revision_id: str = "",
) -> html.Div:
    """Generate the HTML inspection table for an applied MSM snapshot."""
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

    if revision_id:
        summary_items.append(
            html.Span([html.B("Snapshot Revision: "), html.Code(revision_id, style={"color": "#90caf9"})], style={"fontSize": "11px", "color": "#aaa"})
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


def evaluate_msm_for_snapshot(
    snapshot: MarketDataSnapshot,
    applied_data: Optional[Dict[str, Any]],
    draft_direction: Optional[str] = None,
    draft_start_candle: Optional[str] = None,
    current_context: Optional[Dict[str, Any]] = None,
    active_request_token: Optional[str] = None,
) -> Tuple[Optional[MSMServiceResult], str, Dict[str, str], Any]:
    """Evaluates applied MSM configuration against the coherent market data snapshot.

    Rules & Invariants (R12.3, R12.4):
    -----------------------------------
    - R12.3: Rejects snapshot if its request_token does not match active_request_token.
    - R12.3: Rejects snapshot if it does not match current_context.
    - R12.4: Accurately classifies insufficient history vs unconfirmed start vs malformed input vs engine failure.
    """
    # 0. R12.3 Active Request and Current Context Publication Guards
    if active_request_token and snapshot.request_token:
        if snapshot.request_token != active_request_token:
            logger.warning(
                f"Suppressing stale snapshot in MSM evaluation: snapshot token {snapshot.request_token} "
                f"!= active request token {active_request_token}"
            )
            return None, "Stale request response suppressed.", {"marginTop": "10px", "fontSize": "12px", "color": "#888"}, dash.no_update

    if current_context:
        cur_source = current_context.get("data_source")
        cur_sym = current_context.get("symbol")
        cur_tf = current_context.get("timeframe")
        if (
            (cur_source and snapshot.data_source != cur_source)
            or (cur_sym and snapshot.symbol != cur_sym)
            or (cur_tf and snapshot.timeframe != cur_tf)
        ):
            status_text = f"Context changed. Select direction and starting candle for {cur_sym} ({cur_tf}), then click 'Apply / Calculate MSM'."
            status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ffd54f"}
            panel = html.P(
                f"Context changed: No MSM applied for {cur_sym} ({cur_tf}). Select parameters and click 'Apply / Calculate MSM'.",
                style={"color": "#888", "fontSize": "13px", "margin": "8px 0"},
            )
            return None, status_text, status_style, panel

    # 1. MSM Disabled or not applied
    if not applied_data or not applied_data.get("enabled", False):
        status_text = "MSM is disabled. Check 'Enable MSM Overlay', choose an initial direction and starting candle, and click 'Apply / Calculate MSM'."
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#888"}
        panel = html.P(
            "MSM is currently disabled. Check 'Enable MSM Overlay' and click 'Apply / Calculate MSM' to inspect structure swing levels.",
            style={"color": "#666", "fontSize": "13px", "margin": "8px 0"},
        )
        return None, status_text, status_style, panel

    # 2. Market data fetch failure or disconnection
    if snapshot.fetch_status != "SUCCESS":
        status_text = f"🔴 Data unavailable: {snapshot.error_message or snapshot.fetch_status}. MSM inspection paused (rev: {snapshot.revision_id})."
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
        panel = html.Div(
            f"Market data unavailable ({snapshot.fetch_status}). MSM structure calculation paused.",
            style={"color": "#ff5252", "padding": "8px 0"},
        )
        return None, status_text, status_style, panel

    # 3. Context compatibility vs malformed payload check (R12.4)
    app_source = applied_data.get("data_source") if isinstance(applied_data, dict) else getattr(applied_data, "data_source", None)
    app_sym = applied_data.get("symbol") if isinstance(applied_data, dict) else getattr(applied_data, "symbol", None)
    app_tf = applied_data.get("timeframe") if isinstance(applied_data, dict) else getattr(applied_data, "timeframe", None)

    if (app_source != snapshot.data_source) or (app_sym != snapshot.symbol) or (app_tf != snapshot.timeframe):
        status_text = f"Context changed. Select direction and starting candle for {snapshot.symbol} ({snapshot.timeframe}), then click 'Apply / Calculate MSM'."
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ffd54f"}
        panel = html.P(
            f"Context changed: No MSM applied for {snapshot.symbol} ({snapshot.timeframe}). Select parameters and click 'Apply / Calculate MSM'.",
            style={"color": "#888", "fontSize": "13px", "margin": "8px 0"},
        )
        return None, status_text, status_style, panel

    # 4. Parse applied context and validate payload strictly
    try:
        if isinstance(applied_data, dict):
            ctx = MSMContext.from_dict(applied_data)
        elif isinstance(applied_data, MSMContext):
            ctx = applied_data
        else:
            raise TypeError(f"applied_data must be dict or MSMContext, got {type(applied_data).__name__}")
        df = snapshot.to_dataframe()
    except Exception as e:
        status_text = f"❌ MSM Context/Data Error: {e} (rev: {snapshot.revision_id})"
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
        panel = html.Div(f"Data validation failed: {e}", style={"color": "#ff5252"})
        return None, status_text, status_style, panel

    # 5. R12.4: Accurately distinguish genuinely missing start vs unconfirmed start vs calculation error
    if ctx.start_candle_time not in df.index:
        status_text = (
            f"⚠️ Insufficient history: Applied starting candle ({ctx.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')}) "
            f"is no longer in window ({snapshot.candle_count} bars, rev: {snapshot.revision_id}). Select a new start candle and Apply."
        )
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff9800", "fontWeight": "bold"}
        panel = html.Div(
            f"⚠️ Insufficient history: Applied starting candle ({ctx.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')}) "
            f"is no longer in the loaded window ({snapshot.candle_count} bars). Suppressing successful markings.",
            style={"color": "#ff9800", "padding": "8px 0"},
        )
        return None, status_text, status_style, panel

    # Start candle is present: check if unconfirmed
    start_pos = df.index.get_loc(ctx.start_candle_time)
    start_row = df.loc[ctx.start_candle_time]
    if not is_candle_completed(start_pos, start_row):
        status_text = (
            f"⚠️ Unconfirmed starting candle: Starting candle ({ctx.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')}) "
            f"is unconfirmed or forming. Select a completed candle and Apply."
        )
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff9800", "fontWeight": "bold"}
        panel = html.Div(status_text, style={"color": "#ff9800", "padding": "8px 0"})
        return None, status_text, status_style, panel

    # Execute MSM calculation
    try:
        res = calculate_msm(df, ctx)
    except Exception as e:
        status_text = f"❌ MSM Engine Calculation Error: {e} (rev: {snapshot.revision_id})"
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
        panel = html.Div(f"MSM calculation failed: {e}", style={"color": "#ff5252"})
        return None, status_text, status_style, panel

    if not res.is_valid or res.snapshot is None:
        status_text = f"❌ MSM Engine Calculation Error: {res.error} (rev: {snapshot.revision_id})"
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
        panel = html.Div(f"MSM engine error: {res.error}", style={"color": "#ff5252"})
        return None, status_text, status_style, panel

    # 6. Success: check unapplied draft edits
    pair_cnt = len(res.snapshot.confirmed_pairs)
    has_unapplied_draft = False
    if draft_direction and draft_direction != ctx.direction.value:
        has_unapplied_draft = True
    if draft_start_candle and draft_start_candle != ctx.start_candle_time.isoformat():
        has_unapplied_draft = True

    if has_unapplied_draft:
        status_text = (
            f"🟡 Unapplied changes (Click '⚡ Apply / Calculate MSM' to update) | "
            f"Applied: {ctx.direction.value} ({pair_cnt} pairs confirmed, rev: {snapshot.revision_id})"
        )
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ffd600", "fontWeight": "bold"}
    else:
        status_text = (
            f"🟢 Applied: {ctx.direction.value} from {ctx.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')} | "
            f"{pair_cnt} pairs confirmed | {res.snapshot.trend_status} (rev: {snapshot.revision_id})"
        )
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#00e676", "fontWeight": "bold"}

    panel = render_msm_inspection_table(res.snapshot, ctx, snapshot.revision_id)
    return res, status_text, status_style, panel


def process_msm_controls_update(
    triggered_id: str,
    enable_toggle_val: list[str],
    direction_val: str | None,
    start_candle_val: str | None,
    market_snapshot_data: dict | MarketDataSnapshot | None,
    applied_data: dict | None,
    current_context: dict | None = None,
    active_request_token: str | None = None,
) -> tuple[dict | None, str, dict, Any]:
    """Pure coordinator function for MSM controls, application, and unapplied edit detection.

    R12.1: Zero consumer-side fallback fetching.
    R12.3: Active request-generation and current-context publication guards.
    """
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

    # 2. Check market snapshot presence (R12.1: zero fallback fetching)
    if market_snapshot_data is None:
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#888"}
        panel = html.P(
            "Data pending/unavailable. Waiting for market data snapshot...",
            style={"color": "#888", "fontSize": "13px", "margin": "8px 0"},
        )
        return (
            applied_data,
            "Market data pending/unavailable. Waiting for market data snapshot...",
            status_style,
            panel,
        )

    try:
        if isinstance(market_snapshot_data, MarketDataSnapshot):
            snapshot = market_snapshot_data
        else:
            snapshot = MarketDataSnapshot.from_dict(market_snapshot_data)
    except Exception as e:
        status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252"}
        panel = html.Div(f"Invalid market data snapshot payload: {e}", style={"color": "#ff5252"})
        return (None, f"❌ Data Error: {e}", status_style, panel)

    # 3. Context change or new market data update triggered
    market_triggers = {
        "market-data-store",
        "timeframe-selector",
        "symbol-selector",
        "data-source-selector",
        "refresh-btn",
        "candle-count-selector",
        "mt5-connection-store",
    }
    if triggered_id in market_triggers:
        _, status_text, status_style, panel = evaluate_msm_for_snapshot(
            snapshot=snapshot,
            applied_data=applied_data,
            draft_direction=direction_val,
            draft_start_candle=start_candle_val,
            current_context=current_context,
            active_request_token=active_request_token,
        )
        new_applied = applied_data if is_context_compatible(applied_data, snapshot.data_source, snapshot.symbol, snapshot.timeframe) else None
        return new_applied, status_text, status_style, panel

    # 4. Detect unapplied edits without silently recalculating
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

    # 5. Handle Apply button click
    if triggered_id == "msm-apply-btn":
        # R12.3: Context check on Apply: cannot apply to a superseded context
        if current_context:
            cur_source = current_context.get("data_source")
            cur_sym = current_context.get("symbol")
            cur_tf = current_context.get("timeframe")
            if (
                (cur_source and snapshot.data_source != cur_source)
                or (cur_sym and snapshot.symbol != cur_sym)
                or (cur_tf and snapshot.timeframe != cur_tf)
            ):
                status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252", "fontWeight": "bold"}
                panel = html.Div(
                    f"Cannot apply to superseded context. Pending context change to {cur_sym} ({cur_tf}).",
                    style={"color": "#ff5252"},
                )
                return (applied_data, f"❌ Error: Cannot apply to superseded context ({cur_sym} {cur_tf}).", status_style, panel)

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

        if not snapshot.is_valid:
            status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#ff5252"}
            panel = html.Div(f"Cannot apply MSM: {snapshot.error_message or snapshot.fetch_status}", style={"color": "#ff5252"})
            return (None, f"❌ Error: {snapshot.error_message or snapshot.fetch_status}", status_style, panel)

        try:
            msm_ctx = MSMContext(
                data_source=snapshot.data_source,
                symbol=snapshot.symbol,
                timeframe=snapshot.timeframe,
                start_candle_time=start_candle_val,
                direction=Direction(direction_val),
                enabled=True,
            )
            df = snapshot.to_dataframe()
            res = calculate_msm(df, msm_ctx)
            if res.is_valid and res.snapshot is not None:
                pair_cnt = len(res.snapshot.confirmed_pairs)
                status_style = {"marginTop": "10px", "fontSize": "12px", "color": "#00e676", "fontWeight": "bold"}
                status_text = (
                    f"🟢 Applied: {msm_ctx.direction.value} from "
                    f"{msm_ctx.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')} | "
                    f"{pair_cnt} pairs confirmed | {res.snapshot.trend_status} (rev: {snapshot.revision_id})"
                )
                panel = render_msm_inspection_table(res.snapshot, msm_ctx, snapshot.revision_id)
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
    # Callback 3: Update Starting Candle Dropdown Options from shared market-data snapshot
    @app.callback(
        Output("msm-start-candle-dropdown", "options"),
        Output("msm-start-candle-dropdown", "value"),
        Input("market-data-store", "data"),
        State("msm-start-candle-dropdown", "value"),
    )
    def update_msm_dropdown_options(
        market_snapshot_data: dict | None,
        current_value: str | None,
    ) -> tuple[list[dict], str | None]:
        return process_msm_dropdown_update(market_snapshot_data, current_value)

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
        Input("market-data-store", "data"),
        State("msm-applied-store", "data"),
        State("active-request-store", "data"),
    )
    def handle_msm_controls(
        apply_clicks: int,
        enable_toggle_val: list[str],
        direction_val: str | None,
        start_candle_val: str | None,
        market_snapshot_data: dict | None,
        applied_data: dict | None,
        active_req_data: dict | None = None,
    ) -> tuple[dict | None, str, dict, Any]:
        ctx = callback_context
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        active_token = active_req_data.get("token") if active_req_data else None
        active_ctx = active_req_data.get("context") if active_req_data else None

        return process_msm_controls_update(
            triggered_id=triggered_id,
            enable_toggle_val=enable_toggle_val,
            direction_val=direction_val,
            start_candle_val=start_candle_val,
            market_snapshot_data=market_snapshot_data,
            applied_data=applied_data,
            current_context=active_ctx,
            active_request_token=active_token,
        )

    return update_msm_dropdown_options, handle_msm_controls
