"""Candlestick chart construction.

Builds a Plotly candlestick figure from an OHLC DataFrame and optionally
renders Market Structure Marking (MSM) overlays:
- Confirmed Swing Highs (triangle-up, exact pair label H1..Hn, provenance tooltip)
- Confirmed Swing Lows (triangle-down, exact pair label L1..Ln, provenance tooltip)
- Last Structural Support / Resistance (explicit indicators & horizontal guidelines)
- Tentative Swing Level (diamond-open, horizontal threshold guideline)
- Market Structure Path (interconnecting confirmed swing points)
- Starting candle annotation
"""

from __future__ import annotations

from typing import Any, Optional
import pandas as pd
import plotly.graph_objects as go


def create_candlestick_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    data_source: str = "demo",
    is_demo: bool = True,
    is_stale: bool = False,
    last_fetch_time: str | None = None,
    candle_count: int | None = None,
    msm_result: Any | None = None,
) -> go.Figure:
    """Create a Plotly candlestick figure from OHLC *df* with optional MSM overlays.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with a DatetimeIndex and columns ``open``, ``high``,
        ``low``, ``close``, ``is_forming``, ``bar_status``.
    symbol : str
        Instrument name shown in the chart title.
    timeframe : str
        Timeframe label shown in the chart title.
    data_source : str, default 'demo'
        'demo' or 'mt5'.
    is_demo : bool, default True
        When True, chart displays demo data indicator.
    is_stale : bool, default False
        When True, prominent stale-data warning is displayed.
    last_fetch_time : str | None
        Timestamp of the last fetch.
    candle_count : int | None
        Number of candles in the dataset.
    msm_result : MSMServiceResult | None, optional
        Applied MSM calculation result to render on the chart.

    Returns
    -------
    go.Figure
        A Plotly figure ready for rendering in Dash.
    """
    count = candle_count if candle_count is not None else len(df)
    title_parts = [f"<b>{symbol}</b> ({timeframe})"]

    if is_stale:
        title_parts.append("⚠️ <span style='color: #ff5252;'>STALE DATA — FETCH FAILED</span>")
    elif not is_demo:
        source_label = "MT5 Local Terminal (Manual Refresh)" if data_source.lower() == "mt5" else data_source.upper()
        title_parts.append(f"<span style='color: #4caf50;'>{source_label}</span>")
        title_parts.append(f"Candles: {count}")
        if last_fetch_time:
            title_parts.append(f"Fetched: {last_fetch_time}")
    else:
        title_parts.append("<span style='color: #ff9800;'>⚠️ DEMO DATA — NOT CONNECTED TO MT5</span>")
        title_parts.append(f"Candles: {count}")

    # Build custom hover text distinguishing latest/unconfirmed vs confirmed completed candles
    hover_text = []
    if "is_forming" in df.columns:
        for idx, row in df.iterrows():
            status = " [LATEST BAR — UNCONFIRMED COMPLETION]" if row["is_forming"] else " [COMPLETED]"
            hover_text.append(f"{idx.strftime('%Y-%m-%d %H:%M UTC')}{status}")
    else:
        hover_text = [idx.strftime("%Y-%m-%d %H:%M UTC") for idx in df.index]

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df.index,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                text=hover_text,
                hoverinfo="x+y+text",
                name="OHLC",
            )
        ]
    )

    shapes = []
    annotations = []

    # Highlight latest unconfirmed candle if present
    if "is_forming" in df.columns and len(df) > 0 and df["is_forming"].iloc[-1]:
        last_time = df.index[-1]
        annotations.append(
            dict(
                x=last_time,
                y=df["high"].iloc[-1],
                text="⚡ Latest Bar (Unconfirmed)",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowcolor="#ffd54f",
                font=dict(color="#ffd54f", size=10),
                yshift=10,
            )
        )

    # -----------------------------------------------------------------------
    # MSM Overlays (Confirmed Highs/Lows, Last Support/Resistance, Tentative)
    # -----------------------------------------------------------------------
    if msm_result is not None:
        if getattr(msm_result, "error", None):
            title_parts.append(f"<span style='color: #ff5252;'>MSM: {msm_result.error}</span>")
        elif getattr(msm_result, "snapshot", None) is not None:
            snapshot = msm_result.snapshot
            title_parts.append(
                f"<span style='color: #00e5ff;'>MSM: {snapshot.trend_status} "
                f"({len(snapshot.confirmed_pairs)} pairs)</span>"
            )

            pairs = snapshot.confirmed_pairs
            points_for_path = []

            # 1. Starting candle annotation
            start_dt = msm_result.context.start_candle_time
            if start_dt in df.index:
                row_at_start = df.loc[start_dt]
                y_pos = float(row_at_start["low"]) if msm_result.context.direction.value == "UPWARD" else float(row_at_start["high"])
                annotations.append(
                    dict(
                        x=start_dt,
                        y=y_pos,
                        text=f"📍 MSM Start ({msm_result.context.direction.value})",
                        showarrow=True,
                        arrowhead=2,
                        arrowsize=1,
                        arrowcolor="#29b6f6",
                        font=dict(color="#29b6f6", size=10),
                        yshift=-15 if msm_result.context.direction.value == "UPWARD" else 15,
                    )
                )

            # 2. Confirmed Highs (R10.3: direct pair_index)
            if pairs:
                x_highs = [p.high.candle_open_time for p in pairs]
                y_highs = [p.high.price for p in pairs]
                text_highs = [f"H{p.pair_index}" for p in pairs]
                hover_highs = []
                for p in pairs:
                    h = p.high
                    id_time_str = h.identified_time.strftime("%Y-%m-%d %H:%M UTC") if h.identified_time else "Unknown"
                    conf_time_str = h.confirmed_time.strftime("%Y-%m-%d %H:%M UTC") if h.confirmed_time else "Unknown"
                    hover_highs.append(
                        f"<b>Confirmed Swing High (Pair #{p.pair_index})</b><br>"
                        f"Price: {h.price:.4f}<br>"
                        f"Source Candle: {h.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Index: {h.candle_index})<br>"
                        f"Identified: {id_time_str} (Bar: {h.identified_bar_index})<br>"
                        f"Confirmed: {conf_time_str} (Bar: {h.confirmed_bar_index})"
                    )
                    points_for_path.append((h.candle_open_time, h.price))

                fig.add_trace(
                    go.Scatter(
                        x=x_highs,
                        y=y_highs,
                        mode="markers+text",
                        name="Confirmed High",
                        marker=dict(symbol="triangle-up", size=13, color="#00e676", line=dict(width=1, color="#ffffff")),
                        text=text_highs,
                        textposition="top center",
                        textfont=dict(color="#00e676", size=11, family="Segoe UI, sans-serif"),
                        hovertext=hover_highs,
                        hoverinfo="text",
                    )
                )

                # 3. Confirmed Lows (R10.3: direct pair_index)
                x_lows = [p.low.candle_open_time for p in pairs]
                y_lows = [p.low.price for p in pairs]
                text_lows = [f"L{p.pair_index}" for p in pairs]
                hover_lows = []
                for p in pairs:
                    low = p.low
                    id_time_str = low.identified_time.strftime("%Y-%m-%d %H:%M UTC") if low.identified_time else "Unknown"
                    conf_time_str = low.confirmed_time.strftime("%Y-%m-%d %H:%M UTC") if low.confirmed_time else "Unknown"
                    hover_lows.append(
                        f"<b>Confirmed Swing Low (Pair #{p.pair_index})</b><br>"
                        f"Price: {low.price:.4f}<br>"
                        f"Source Candle: {low.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Index: {low.candle_index})<br>"
                        f"Identified: {id_time_str} (Bar: {low.identified_bar_index})<br>"
                        f"Confirmed: {conf_time_str} (Bar: {low.confirmed_bar_index})"
                    )
                    points_for_path.append((low.candle_open_time, low.price))

                fig.add_trace(
                    go.Scatter(
                        x=x_lows,
                        y=y_lows,
                        mode="markers+text",
                        name="Confirmed Low",
                        marker=dict(symbol="triangle-down", size=13, color="#ff5252", line=dict(width=1, color="#ffffff")),
                        text=text_lows,
                        textposition="bottom center",
                        textfont=dict(color="#ff5252", size=11, family="Segoe UI, sans-serif"),
                        hovertext=hover_lows,
                        hoverinfo="text",
                    )
                )

            # 4. Market Structure Path (interconnecting swing points chronologically)
            if len(points_for_path) >= 2:
                points_for_path.sort(key=lambda pt: pt[0])
                fig.add_trace(
                    go.Scatter(
                        x=[pt[0] for pt in points_for_path],
                        y=[pt[1] for pt in points_for_path],
                        mode="lines",
                        name="Market Structure",
                        line=dict(color="#00b0ff", width=2, dash="dashdot"),
                        hoverinfo="skip",
                    )
                )

            last_chart_time = df.index[-1]

            # 5. Last Support indicator (R10.4)
            if snapshot.last_support is not None:
                supp = snapshot.last_support
                id_supp_str = supp.identified_time.strftime("%Y-%m-%d %H:%M UTC") if supp.identified_time else "Unknown"
                conf_supp_str = supp.confirmed_time.strftime("%Y-%m-%d %H:%M UTC") if supp.confirmed_time else "Unknown"
                supp_hover = (
                    f"<b>Last Structural Support</b><br>"
                    f"Price: {supp.price:.4f}<br>"
                    f"Source Candle: {supp.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Index: {supp.candle_index})<br>"
                    f"Identified: {id_supp_str} (Bar #{supp.identified_bar_index})<br>"
                    f"Confirmed: {conf_supp_str} (Bar #{supp.confirmed_bar_index})"
                )
                fig.add_trace(
                    go.Scatter(
                        x=[supp.candle_open_time],
                        y=[supp.price],
                        mode="markers+text",
                        name="Last Support",
                        marker=dict(symbol="line-ew", size=14, color="#76ff03", line=dict(width=2, color="#76ff03")),
                        text=[f"Last Support ({supp.price:.2f})"],
                        textposition="bottom right",
                        textfont=dict(color="#76ff03", size=10),
                        hovertext=[supp_hover],
                        hoverinfo="text",
                    )
                )
                shapes.append(
                    dict(
                        type="line",
                        x0=supp.candle_open_time,
                        y0=supp.price,
                        x1=last_chart_time,
                        y1=supp.price,
                        line=dict(color="#76ff03", width=1.5, dash="dash"),
                    )
                )

            # 6. Last Resistance indicator (R10.4)
            if snapshot.last_resistance is not None:
                res = snapshot.last_resistance
                id_res_str = res.identified_time.strftime("%Y-%m-%d %H:%M UTC") if res.identified_time else "Unknown"
                conf_res_str = res.confirmed_time.strftime("%Y-%m-%d %H:%M UTC") if res.confirmed_time else "Unknown"
                res_hover = (
                    f"<b>Last Structural Resistance</b><br>"
                    f"Price: {res.price:.4f}<br>"
                    f"Source Candle: {res.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Index: {res.candle_index})<br>"
                    f"Identified: {id_res_str} (Bar #{res.identified_bar_index})<br>"
                    f"Confirmed: {conf_res_str} (Bar #{res.confirmed_bar_index})"
                )
                fig.add_trace(
                    go.Scatter(
                        x=[res.candle_open_time],
                        y=[res.price],
                        mode="markers+text",
                        name="Last Resistance",
                        marker=dict(symbol="line-ew", size=14, color="#ff1744", line=dict(width=2, color="#ff1744")),
                        text=[f"Last Resistance ({res.price:.2f})"],
                        textposition="top right",
                        textfont=dict(color="#ff1744", size=10),
                        hovertext=[res_hover],
                        hoverinfo="text",
                    )
                )
                shapes.append(
                    dict(
                        type="line",
                        x0=res.candle_open_time,
                        y0=res.price,
                        x1=last_chart_time,
                        y1=res.price,
                        line=dict(color="#ff1744", width=1.5, dash="dash"),
                    )
                )

            # 7. Tentative Level
            if snapshot.tentative_point is not None:
                tent = snapshot.tentative_point
                id_time_str = tent.identified_time.strftime("%Y-%m-%d %H:%M UTC") if tent.identified_time else "Unknown"
                tent_hover = (
                    f"<b>Tentative Swing Level (Pending Break)</b><br>"
                    f"Price: {tent.price:.4f}<br>"
                    f"Source Candle: {tent.candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Index: {tent.candle_index})<br>"
                    f"Identified: {id_time_str} (Bar: {tent.identified_bar_index})<br>"
                    f"Status: Waiting for Candle Body Break"
                )
                fig.add_trace(
                    go.Scatter(
                        x=[tent.candle_open_time],
                        y=[tent.price],
                        mode="markers+text",
                        name="Tentative Level",
                        marker=dict(symbol="diamond-open", size=13, color="#ffd600", line=dict(width=2, color="#ffd600")),
                        text=["Tentative"],
                        textposition="top right",
                        textfont=dict(color="#ffd600", size=11),
                        hovertext=[tent_hover],
                        hoverinfo="text",
                    )
                )

                shapes.append(
                    dict(
                        type="line",
                        x0=tent.candle_open_time,
                        y0=tent.price,
                        x1=last_chart_time,
                        y1=tent.price,
                        line=dict(color="#ffd600", width=1.5, dash="dot"),
                    )
                )

    fig.update_layout(
        title=" | ".join(title_parts),
        yaxis_title="Price",
        xaxis_title="Time (UTC)",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=580,
        margin=dict(l=60, r=30, t=60, b=40),
        shapes=shapes,
        annotations=annotations,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
    )

    return fig


def create_empty_chart(message: str, title: str = "No Chart Data") -> go.Figure:
    """Return an empty figure displaying *message* as an annotation.

    Used when no data exists or an error occurred.
    """
    fig = go.Figure()
    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=580,
        margin=dict(l=60, r=30, t=60, b=40),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="#ff9800"),
                align="center",
            )
        ],
    )
    return fig
