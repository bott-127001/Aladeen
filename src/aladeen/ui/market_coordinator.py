"""Market Data Fetch and Layout Coordination Module.

Houses the single fetch coordinator, active request-generation tracking,
and chart rendering callbacks separated cleanly from layout definition.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
import dash
from dash import Dash, Input, Output, State, callback_context
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

from aladeen.data.market_snapshot import MarketDataSnapshot, fetch_market_snapshot
from aladeen.data.mt5_adapter import MT5ConnectionState, get_mt5_adapter
from aladeen.strategy.service import MSMContext, calculate_msm, is_context_compatible
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart


def generate_chart_and_status_from_snapshot(
    market_snapshot_data: dict | MarketDataSnapshot | None,
    msm_applied: dict | None = None,
    current_context: dict | None = None,
    active_request_token: str | None = None,
) -> tuple[go.Figure, str]:
    """Pure chart and status renderer consuming a serialized or MarketDataSnapshot object.

    Enforces active request-token and current-context publication guards (R12.3).
    """
    if not market_snapshot_data:
        msg = "No market data loaded."
        return create_empty_chart(msg, title="No Data"), f"⚠️ {msg}"

    if isinstance(market_snapshot_data, MarketDataSnapshot):
        snapshot = market_snapshot_data
    else:
        snapshot = MarketDataSnapshot.from_dict(market_snapshot_data)

    # R12.3: Stale response publication guard against active request token
    if active_request_token and snapshot.request_token:
        if snapshot.request_token != active_request_token:
            logger.warning(
                f"Suppressing stale snapshot render: snapshot token {snapshot.request_token} "
                f"does not match active request token {active_request_token}"
            )
            return dash.no_update, dash.no_update

    # R12.3: Context guard against current UI selection
    if current_context:
        cur_source = current_context.get("data_source")
        cur_sym = current_context.get("symbol")
        cur_tf = current_context.get("timeframe")
        if (
            (cur_source and snapshot.data_source != cur_source)
            or (cur_sym and snapshot.symbol != cur_sym)
            or (cur_tf and snapshot.timeframe != cur_tf)
        ):
            logger.warning(
                f"Suppressing mismatched context snapshot: snapshot ({snapshot.symbol} {snapshot.timeframe}) "
                f"does not match current context ({cur_sym} {cur_tf})"
            )
            return dash.no_update, dash.no_update

    if snapshot.fetch_status != "SUCCESS":
        status_msg = snapshot.error_message or snapshot.fetch_status
        if snapshot.fetch_status == "DISCONNECTED":
            msg = "MT5 terminal is not connected. Click '⚡ Connect MT5' above."
            fig = create_empty_chart(msg, title="MT5 Terminal: Disconnected")
            status = "🔴 MT5 Disconnected. Please connect to terminal."
        elif snapshot.fetch_status == "NO_SYMBOL":
            msg = "No symbol selected. Please select a valid symbol from MT5 MarketWatch."
            fig = create_empty_chart(msg, title="MT5: Select Symbol")
            status = "⚠️ No symbol selected."
        elif snapshot.fetch_status == "CONNECTION_ERROR":
            msg = f"Connection Lost: {status_msg}"
            fig = create_empty_chart(msg, title="MT5: Connection Lost")
            status = f"❌ {msg}"
        elif snapshot.fetch_status == "VALIDATION_ERROR":
            msg = f"Data Contract Violation: {status_msg}"
            fig = create_empty_chart(msg, title="MT5: Malformed Data Received")
            status = f"❌ {msg}"
        else:
            msg = f"Data Fetch Error: {status_msg}"
            fig = create_empty_chart(
                msg,
                title=f"MT5: Fetch Failed ({snapshot.symbol} {snapshot.timeframe})"
                if snapshot.data_source == "mt5"
                else f"Demo: {snapshot.symbol} ({snapshot.timeframe}) — Unsupported",
            )
            status = f"❌ {msg}" if snapshot.data_source == "mt5" else f"⚠️ Demo: {msg}"
        return fig, status

    df = snapshot.to_dataframe()

    # Check MSM overlay
    msm_res = None
    msm_status_suffix = ""
    if msm_applied and msm_applied.get("enabled", False):
        if is_context_compatible(msm_applied, snapshot.data_source, snapshot.symbol, snapshot.timeframe):
            try:
                ctx = MSMContext.from_dict(msm_applied)
                msm_res = calculate_msm(df, ctx)
                if msm_res.is_valid and msm_res.snapshot is not None:
                    msm_status_suffix = f" | 📐 MSM: {msm_res.snapshot.trend_status} ({len(msm_res.snapshot.confirmed_pairs)} pairs)"
                else:
                    msm_status_suffix = f" | ⚠️ MSM Error: {msm_res.error}"
            except Exception as e:
                msm_status_suffix = f" | ❌ MSM Exception: {e}"

    fig = create_candlestick_chart(
        df,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        data_source=snapshot.data_source,
        is_demo=(snapshot.data_source == "demo"),
        is_stale=False,
        last_fetch_time=snapshot.timestamp_utc,
        candle_count=len(df),
        msm_result=msm_res,
    )

    if snapshot.data_source == "demo":
        status = (
            f"Source: Demo | Symbol: {snapshot.symbol} | TF: {snapshot.timeframe} | "
            f"Count: {len(df)} candles | Last Fetch: {snapshot.timestamp_utc}{msm_status_suffix}"
        )
    else:
        broker_note = " (Broker Connected)" if snapshot.broker_connected else " (Broker Offline - Cached)"
        status = (
            f"Source: MT5 Terminal{broker_note} | Symbol: {snapshot.symbol} | TF: {snapshot.timeframe} | "
            f"Count: {len(df)} candles | Last Fetch: {snapshot.timestamp_utc}{msm_status_suffix}"
        )

    return fig, status


def register_market_coordinator_callbacks(app: Dash, adapter: Any = None) -> tuple[Any, Any]:
    """Register market data fetch coordinator and chart rendering callbacks on *app*."""
    if adapter is None:
        adapter = get_mt5_adapter()

    # Callback 2a: Unified Market Data Fetch Coordinator (Single-fetch path with generation token)
    @app.callback(
        Output("market-data-store", "data"),
        Output("connection-loss-trigger", "data"),
        Output("active-request-store", "data"),
        Input("data-source-selector", "value"),
        Input("symbol-selector", "value"),
        Input("timeframe-selector", "value"),
        Input("candle-count-selector", "value"),
        Input("refresh-btn", "n_clicks"),
        Input("mt5-connection-store", "data"),
        State("active-request-store", "data"),
    )
    def update_market_data(
        data_source: str,
        symbol: str | None,
        timeframe: str,
        candle_count: int,
        _n_clicks: int,
        store_data: dict | None,
        active_req_data: dict | None = None,
    ) -> tuple[dict, Any, dict]:
        if not store_data:
            store_data = {}
        is_connected = store_data.get("state", "DISCONNECTED") != MT5ConnectionState.DISCONNECTED.value
        current_state = store_data.get("state", "DISCONNECTED")

        # R12.3: Increment request generation counter
        prev_token_id = active_req_data.get("counter", 0) if active_req_data else 0
        new_token_id = prev_token_id + 1
        req_token = f"req-{new_token_id}"

        new_active_store = {
            "token": req_token,
            "counter": new_token_id,
            "context": {
                "data_source": data_source,
                "symbol": symbol,
                "timeframe": timeframe,
                "candle_count": candle_count,
            },
        }

        snapshot, loss_trigger = fetch_market_snapshot(
            data_source=data_source,
            symbol=symbol,
            timeframe=timeframe,
            candle_count=candle_count,
            is_connected=is_connected,
            adapter=adapter,
            current_state=current_state,
            request_token=req_token,
        )
        trigger_output = loss_trigger if loss_trigger is not None else dash.no_update
        return snapshot.to_dict(), trigger_output, new_active_store

    # Callback 2b: Main Chart & Status Area Renderer (from shared snapshot with publication guard)
    @app.callback(
        Output("main-chart", "figure"),
        Output("status-area", "children"),
        Input("market-data-store", "data"),
        Input("msm-applied-store", "data"),
        State("active-request-store", "data"),
    )
    def render_chart_from_snapshot(
        market_snapshot_data: dict | None,
        msm_applied: dict | None = None,
        active_req_data: dict | None = None,
    ) -> tuple[go.Figure, str]:
        active_token = active_req_data.get("token") if active_req_data else None
        active_ctx = active_req_data.get("context") if active_req_data else None
        return generate_chart_and_status_from_snapshot(
            market_snapshot_data=market_snapshot_data,
            msm_applied=msm_applied,
            current_context=active_ctx,
            active_request_token=active_token,
        )

    return update_market_data, render_chart_from_snapshot
