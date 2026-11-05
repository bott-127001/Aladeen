"""Market Data Fetch and Layout Coordination Module.

Houses the single fetch coordinator, active request-generation tracking,
candidate acceptance gate, and chart rendering callbacks separated cleanly from layout definition.
Implements separated browser-side request issuance, candidate gating, and publication guards (R13.1, R14.1-R14.4).
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, Optional, Tuple
import uuid
import dash
from dash import Dash, Input, Output, State, callback_context
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

from aladeen.data.fixtures import DEMO_SYMBOL
from aladeen.data.market_snapshot import MarketDataSnapshot, fetch_market_snapshot
from aladeen.data.mt5_adapter import MT5ConnectionState, get_mt5_adapter
from aladeen.strategy.service import MSMContext, calculate_msm, is_context_compatible
from aladeen.ui.chart import create_candlestick_chart, create_empty_chart


CLIENTSIDE_REQUEST_ISSUANCE_JS = """
function(dataSource, symbol, timeframe, candleCount, nClicks, storeData, activeReq) {
    var prevCounter = (activeReq && activeReq.counter) ? activeReq.counter : 0;
    var newCounter = prevCounter + 1;
    var rand = Math.random().toString(36).substring(2, 9);
    var token = "req-" + Date.now() + "-" + rand + "-" + newCounter;
    var activeSym = symbol;
    if (!activeSym && dataSource === "demo") {
        activeSym = "DEMO_XAUUSD";
    }
    return {
        "token": token,
        "counter": newCounter,
        "context": {
            "data_source": dataSource || "demo",
            "symbol": activeSym || "",
            "timeframe": timeframe || "H4",
            "candle_count": candleCount || 100
        },
        "status": "pending",
        "issued_at": new Date().toISOString()
    };
}
"""

CLIENTSIDE_ACCEPTANCE_GATE_JS = """
function(candidateEnvelope, activeReq) {
    if (!candidateEnvelope || !activeReq) {
        return [window.dash_clientside.no_update, window.dash_clientside.no_update];
    }
    var activeToken = activeReq.token;
    var activeCtx = activeReq.context || {};
    var candToken = candidateEnvelope.request_token;
    var snapshot = candidateEnvelope.snapshot;

    console.log("[GATE_JS] Checking candidate token:", candToken, "against active token:", activeToken);

    // Strict token check
    if (!candToken || candToken !== activeToken) {
        console.warn("[GATE_JS] REJECTED stale candidate token:", candToken, "!= active:", activeToken);
        return [window.dash_clientside.no_update, window.dash_clientside.no_update];
    }

    // Strict context check
    if (snapshot) {
        if ((activeCtx.data_source && snapshot.data_source !== activeCtx.data_source) ||
            (activeCtx.symbol && snapshot.symbol !== activeCtx.symbol) ||
            (activeCtx.timeframe && snapshot.timeframe !== activeCtx.timeframe)) {
            console.warn("[GATE_JS] REJECTED mismatched context:", snapshot.symbol, snapshot.timeframe, "!= active:", activeCtx.symbol, activeCtx.timeframe);
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
    }

    console.log("[GATE_JS] ACCEPTED candidate token:", candToken);
    var lossOut = (candidateEnvelope.connection_event !== null && candidateEnvelope.connection_event !== undefined)
        ? candidateEnvelope.connection_event
        : window.dash_clientside.no_update;

    return [snapshot, lossOut];
}
"""


def issue_market_data_request(
    data_source: str,
    symbol: str | None,
    timeframe: str,
    candle_count: int,
    store_data: dict | None = None,
    current_active_req: dict | None = None,
) -> dict:
    """Issue a unique market data request identity and context prior to fetching (R13.1, R14.1).

    Generates unique request identifiers combining high-resolution timestamp and random hex.
    Does NOT perform fetching.
    """
    prev_counter = current_active_req.get("counter", 0) if current_active_req else 0
    new_counter = prev_counter + 1
    rand_id = uuid.uuid4().hex[:8]
    new_token = f"req-{time.time_ns()}-{rand_id}-{new_counter}"
    active_sym = symbol or (DEMO_SYMBOL if data_source == "demo" else "")
    return {
        "token": new_token,
        "counter": new_counter,
        "context": {
            "data_source": data_source,
            "symbol": active_sym,
            "timeframe": timeframe,
            "candle_count": candle_count,
        },
        "status": "pending",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_market_data_for_request(
    active_req_data: dict | None,
    store_data: dict | None = None,
    adapter: Any = None,
) -> dict | Any:
    """Execute market data fetch for an issued request (R13.1, R14.2).

    A fetch response writes a candidate envelope to market-candidate-envelope-store
    and NEVER writes to active-request-store or market-data-store.
    Candidate data and its side effect travel together in a single envelope:
    {
        "request_token": req_token,
        "snapshot": snapshot.to_dict(),
        "connection_event": loss_trigger or None,
    }
    """
    if not active_req_data:
        return dash.no_update

    if not store_data:
        store_data = {}
    is_connected = store_data.get("state", "DISCONNECTED") != MT5ConnectionState.DISCONNECTED.value
    current_state = store_data.get("state", "DISCONNECTED")

    req_token = active_req_data.get("token")
    ctx = active_req_data.get("context", {})
    data_source = ctx.get("data_source", "demo")
    symbol = ctx.get("symbol")
    timeframe = ctx.get("timeframe", "H4")
    candle_count = ctx.get("candle_count", 100)

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
    return {
        "request_token": req_token,
        "snapshot": snapshot.to_dict(),
        "connection_event": loss_trigger if loss_trigger is not None else None,
    }


def accept_market_data_candidate(
    candidate_envelope: dict | None,
    active_req_data: dict | None = None,
) -> tuple[Any, Any]:
    """Acceptance gate: validates candidate token and context against active request (R14.3).

    - If candidate token matches active request token: ACCEPT and publish snapshot to
      market-data-store and connection_event to connection-loss-trigger.
    - If candidate token is stale or does not match: REJECT and return dash.no_update!
      The accepted market-data-store and connection-loss-trigger are untouched.
    """
    if candidate_envelope is None:
        return dash.no_update, dash.no_update

    if not active_req_data:
        logger.warning("Acceptance gate: No active request store, rejecting candidate")
        return dash.no_update, dash.no_update

    active_token = active_req_data.get("token")
    active_ctx = active_req_data.get("context", {})

    cand_token = candidate_envelope.get("request_token")
    snapshot = candidate_envelope.get("snapshot")
    conn_event = candidate_envelope.get("connection_event")

    # Strict token matching
    if not cand_token or cand_token != active_token:
        logger.warning(
            f"Acceptance gate REJECTED stale candidate: token '{cand_token}' != active '{active_token}'"
        )
        return dash.no_update, dash.no_update

    # Context matching
    if snapshot:
        cand_src = snapshot.get("data_source")
        cand_sym = snapshot.get("symbol")
        cand_tf = snapshot.get("timeframe")
        if (
            (active_ctx.get("data_source") and cand_src != active_ctx.get("data_source"))
            or (active_ctx.get("symbol") and cand_sym != active_ctx.get("symbol"))
            or (active_ctx.get("timeframe") and cand_tf != active_ctx.get("timeframe"))
        ):
            logger.warning(
                f"Acceptance gate REJECTED mismatched context candidate: ({cand_sym} {cand_tf}) != active ({active_ctx.get('symbol')} {active_ctx.get('timeframe')})"
            )
            return dash.no_update, dash.no_update

    logger.info(f"Acceptance gate ACCEPTED candidate for token '{cand_token}'")
    loss_out = conn_event if conn_event is not None else dash.no_update
    return snapshot, loss_out


def _get_triggered_id() -> str:
    """Safely obtain triggered component ID without throwing outside Dash callback."""
    try:
        from dash import callback_context
        if callback_context and callback_context.triggered:
            return callback_context.triggered[0]["prop_id"].split(".")[0]
    except Exception:
        pass
    return ""


def generate_chart_and_status_from_snapshot(
    market_snapshot_data: dict | MarketDataSnapshot | None,
    msm_applied: dict | None = None,
    current_context: dict | None = None,
    active_request_token: str | None = None,
    active_req_data: dict | None = None,
    triggered_id: str | None = None,
) -> tuple[go.Figure, str]:
    """Pure chart and status renderer consuming snapshot and active request state.

    Enforces active request-token and current-context publication guards (R12.3, R13.1):
    - While a new request is pending, immediately clears or marks previous chart as stale.
    - Stale responses completing out-of-order are strictly suppressed with dash.no_update.
    """
    if triggered_id is None:
        triggered_id = _get_triggered_id()

    if active_req_data:
        active_token = active_req_data.get("token")
        active_ctx = active_req_data.get("context", {})
    else:
        active_token = active_request_token
        active_ctx = current_context or {}

    req_sym = active_ctx.get("symbol", "")
    req_tf = active_ctx.get("timeframe", "")
    req_src = active_ctx.get("data_source", "demo")

    if not active_req_data and not market_snapshot_data:
        msg = "No market data loaded."
        return create_empty_chart(msg, title="No Data"), f"⚠️ {msg}"

    if not market_snapshot_data:
        msg = f"Fetching market data for {req_sym} ({req_tf})..."
        return create_empty_chart(msg, title="Loading..."), f"⏳ {msg} [{active_token}]"

    if isinstance(market_snapshot_data, MarketDataSnapshot):
        snapshot = market_snapshot_data
    else:
        snapshot = MarketDataSnapshot.from_dict(market_snapshot_data)

    # R13.1: Stale response guard and Pending context transition handling
    if active_token and snapshot.request_token != active_token:
        if triggered_id == "active-request-store":
            # Active request changed: new fetch is pending!
            # Immediately clear or mark previous chart as stale (R13.1)
            ctx_changed = (
                (req_src and snapshot.data_source != req_src)
                or (req_sym and snapshot.symbol != req_sym)
                or (req_tf and snapshot.timeframe != req_tf)
            )
            if ctx_changed:
                msg = f"Loading {req_sym} ({req_tf})... (Previous context is stale)"
                return create_empty_chart(msg, title="Loading..."), f"⏳ Pending update for {req_sym} ({req_tf}) [{active_token}]... (Previous data is stale)"
            else:
                # Same-context refresh is pending: mark existing chart as stale
                df = snapshot.to_dataframe()
                fig = create_candlestick_chart(
                    df,
                    symbol=snapshot.symbol,
                    timeframe=snapshot.timeframe,
                    data_source=snapshot.data_source,
                    is_demo=(snapshot.data_source == "demo"),
                    is_stale=True,
                    last_fetch_time=snapshot.timestamp_utc,
                    candle_count=len(df),
                )
                return fig, f"⏳ Refreshing {req_sym} ({req_tf}) [{active_token}]... (Current data is stale)"
        else:
            # An older fetch completed or direct call with mismatched token: suppress!
            logger.warning(
                f"Suppressing stale snapshot render: snapshot token '{snapshot.request_token}' "
                f"does not match active request token '{active_token}'"
            )
            return dash.no_update, dash.no_update

    # R12.3: Context guard against current UI selection
    if active_ctx:
        cur_source = active_ctx.get("data_source")
        cur_sym = active_ctx.get("symbol")
        cur_tf = active_ctx.get("timeframe")
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
                    if msm_res.is_unresolved:
                        msm_status_suffix = (
                            f" | ⚠️ Integrated Unresolved: ambiguous at candle {msm_res.unresolved_candle_index} "
                            f"(Last Authoritative State: {msm_res.snapshot.trend_status}, Bar #{msm_res.last_processed_index})"
                        )
                    else:
                        choch_cnt = len(msm_res.confirmed_choch_events)
                        choch_str = f", {choch_cnt} CHOCH" if ctx.calculation_mode == "INTEGRATED_MSM_CHOCH" else ""
                        msm_status_suffix = f" | 📐 MSM: {msm_res.snapshot.trend_status} ({len(msm_res.snapshot.confirmed_pairs)} pairs{choch_str})"
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


def register_market_coordinator_callbacks(app: Dash, adapter: Any = None) -> tuple[Any, Any, Any, Any]:
    """Register market data request issuance, fetch coordinator, acceptance gate, and chart rendering callbacks (R14.1-R14.4)."""
    if adapter is None:
        adapter = get_mt5_adapter()

    # Callback 2a: Request Issuance (Synchronous browser-side token generation, R14.1)
    if hasattr(app, "clientside_callback"):
        app.clientside_callback(
            CLIENTSIDE_REQUEST_ISSUANCE_JS,
            Output("active-request-store", "data"),
            Input("data-source-selector", "value"),
            Input("symbol-selector", "value"),
            Input("timeframe-selector", "value"),
            Input("candle-count-selector", "value"),
            Input("refresh-btn", "n_clicks"),
            Input("mt5-connection-store", "data"),
            State("active-request-store", "data"),
        )

    # Callback 2b: Market Data Fetch -> Candidate Envelope Store (R14.2)
    @app.callback(
        Output("market-candidate-envelope-store", "data"),
        Input("active-request-store", "data"),
        State("mt5-connection-store", "data"),
    )
    def on_active_request_fetch(
        active_req_data: dict | None,
        store_data: dict | None,
    ) -> dict | Any:
        return fetch_market_data_for_request(
            active_req_data=active_req_data,
            store_data=store_data,
            adapter=adapter,
        )

    # Callback 2c: Acceptance Gate (Synchronous browser-side gating, R14.3)
    if hasattr(app, "clientside_callback"):
        app.clientside_callback(
            CLIENTSIDE_ACCEPTANCE_GATE_JS,
            Output("market-data-store", "data"),
            Output("connection-loss-trigger", "data"),
            Input("market-candidate-envelope-store", "data"),
            State("active-request-store", "data"),
        )

    # Callback 2d: Main Chart & Status Area Renderer (Observes accepted market-data-store as Input)
    @app.callback(
        Output("main-chart", "figure"),
        Output("status-area", "children"),
        Input("market-data-store", "data"),
        Input("active-request-store", "data"),
        Input("msm-applied-store", "data"),
    )
    def render_chart_from_snapshot(
        market_snapshot_data: dict | None,
        active_req_data: dict | None = None,
        msm_applied: dict | None = None,
    ) -> tuple[go.Figure, str]:
        triggered_id = _get_triggered_id()
        return generate_chart_and_status_from_snapshot(
            market_snapshot_data=market_snapshot_data,
            msm_applied=msm_applied,
            active_req_data=active_req_data,
            triggered_id=triggered_id,
        )

    return issue_market_data_request, on_active_request_fetch, accept_market_data_candidate, render_chart_from_snapshot
