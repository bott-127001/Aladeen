"""Candlestick chart construction.

Builds a Plotly candlestick figure from an OHLC DataFrame.
No strategy overlays are added here — this module is purely chart rendering.
"""

from __future__ import annotations

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
) -> go.Figure:
    """Create a Plotly candlestick figure from OHLC *df*.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with a DatetimeIndex and columns ``open``, ``high``,
        ``low``, ``close``, and optional ``is_forming``.
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

    # Highlight latest unconfirmed candle if present
    shapes = []
    annotations = []
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

    fig.update_layout(
        title=" | ".join(title_parts),
        yaxis_title="Price",
        xaxis_title="Time (UTC)",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=560,
        margin=dict(l=60, r=30, t=60, b=40),
        shapes=shapes,
        annotations=annotations,
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
        height=560,
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
