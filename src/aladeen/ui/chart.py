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
    is_demo: bool = True,
) -> go.Figure:
    """Create a Plotly candlestick figure from OHLC *df*.

    Parameters
    ----------
    df:
        DataFrame with a DatetimeIndex and columns ``open``, ``high``,
        ``low``, ``close``.
    symbol:
        Instrument name shown in the chart title.
    timeframe:
        Timeframe label shown in the chart title.
    is_demo:
        When True, the chart title includes a demo-data warning.

    Returns
    -------
    go.Figure
        A Plotly figure ready for rendering in Dash.
    """
    title_parts = [f"{symbol} — {timeframe}"]
    if is_demo:
        title_parts.append("⚠️ DEMO DATA — NOT CONNECTED TO MT5")

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df.index,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="OHLC",
            )
        ]
    )

    fig.update_layout(
        title=" | ".join(title_parts),
        yaxis_title="Price",
        xaxis_title="Time",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=560,
        margin=dict(l=60, r=30, t=60, b=40),
    )

    return fig


def create_empty_chart(message: str) -> go.Figure:
    """Return an empty figure displaying *message* as an annotation.

    Used when no fixture data exists for the requested combination.
    """
    fig = go.Figure()
    fig.update_layout(
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
                font=dict(size=18, color="#ff9800"),
            )
        ],
    )
    return fig
