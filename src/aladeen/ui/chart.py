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

from aladeen.strategy import Direction, ISSLifecycleStatus


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

            # 8. Unresolved Boundary Representation
            if getattr(msm_result, "is_unresolved", False):
                unres_idx = getattr(msm_result, "unresolved_candle_index", None)
                unres_diag = getattr(msm_result, "unresolved_diagnostic", None)
                last_proc = getattr(msm_result, "last_processed_index", -1)
                last_rec = getattr(msm_result, "last_received_index", -1)
                title_parts.append(
                    f"<span style='color: #ff9800;'>⚠️ INTEGRATED UNRESOLVED — Last authoritative state (Bar #{last_proc}, received through Bar #{last_rec})</span>"
                )
                if unres_diag is not None:
                    unres_time = unres_diag.candle_open_time
                    if unres_time in df.index:
                        shapes.append(
                            dict(
                                type="line",
                                x0=unres_time,
                                x1=unres_time,
                                y0=0,
                                y1=1,
                                yref="paper",
                                line=dict(color="#ff9800", width=2, dash="dash"),
                            )
                        )
                        annotations.append(
                            dict(
                                x=unres_time,
                                y=1.0,
                                yref="paper",
                                text=f"⚠️ Unresolved: Last authoritative state (Bar #{last_proc})",
                                showarrow=False,
                                font=dict(color="#ff9800", size=10),
                                bgcolor="#2e1a00",
                                bordercolor="#ff9800",
                            )
                        )

            # 9. CHOCH Confirmation Markers & Structural Zones
            ctx = getattr(msm_result, "context", None)
            show_markers = getattr(ctx, "show_choch_markers", True) if ctx else True
            show_zones = getattr(ctx, "show_choch_zones", True) if ctx else True
            choch_events = getattr(msm_result, "confirmed_choch_events", ())

            if choch_events:
                # Add confirmed CHOCH summary to title
                if not getattr(msm_result, "is_unresolved", False):
                    title_parts.append(f"<span style='color: #ff4081;'>CHOCH: {len(choch_events)} confirmed</span>")

                for ev in choch_events:
                    c2_time = ev.c2_open_time
                    is_bear = "BEARISH" in ev.choch_type.value
                    m_color = "#ff4081" if is_bear else "#00e5ff"
                    m_sym = "triangle-down" if is_bear else "triangle-up"
                    m_pos = "bottom center" if is_bear else "top center"

                    if ev.confirmation_time is not None:
                        conf_avail_marker_str = f"Confirmed At: {ev.confirmation_time.strftime('%Y-%m-%d %H:%M UTC')} (Candle Close)"
                    else:
                        conf_avail_marker_str = f"Confirmation Availability: Unknown — confirmed on completion of candle Bar #{ev.c2_candle_index}"

                    if show_markers:
                        c2_y = float(df.loc[c2_time, "close"]) if c2_time in df.index else ev.broken_level_price
                        choch_hover = (
                            f"<b>Confirmed CHOCH ({ev.choch_type.value}) [Candle-Anchored Marker]</b><br>"
                            f"Broken Level: {ev.broken_level_type} @ {ev.broken_level_price:.4f} (Bar #{ev.broken_level_source_index})<br>"
                            f"Qualifying Candle c1: Bar #{ev.c1_candle_index} (Open: {ev.c1_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                            f"Qualifying Candle c2 (Anchor): Bar #{ev.c2_candle_index} (Open: {ev.c2_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                            f"{conf_avail_marker_str}<br>"
                            f"Point 3: Bar #{ev.point_3_source_index} (Open: {ev.point_3_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                            f"New Direction: {ev.new_direction.value}"
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=[c2_time],
                                y=[c2_y],
                                mode="markers+text",
                                name=f"CHOCH ({'BEAR' if is_bear else 'BULL'})",
                                marker=dict(symbol=m_sym, size=15, color=m_color, line=dict(width=2, color="#ffffff")),
                                text=[f"CHOCH ({'BEAR' if is_bear else 'BULL'})"],
                                textposition=m_pos,
                                textfont=dict(color=m_color, size=11, family="Segoe UI, sans-serif"),
                                hovertext=[choch_hover],
                                hoverinfo="text",
                            )
                        )

                    if show_zones:
                        # R24: Zone shapes and hover traces begin strictly at ev.confirmation_time.
                        # Never use ev.c2_open_time as the availability boundary.
                        # If confirmation_time is None (unknown), omit time-extended availability zones.
                        if ev.confirmation_time is not None:
                            x0_zone = ev.confirmation_time
                            conf_avail_label = f"Structural zone available from: {ev.confirmation_time.strftime('%Y-%m-%d %H:%M UTC')}"
                            # Ensure right boundary is never earlier than left boundary (x1 >= x0)
                            # If confirmation occurs beyond last plotted candle-open timestamp, x1_zone = max(last_chart_time, x0_zone)
                            x1_zone = max(last_chart_time, x0_zone)

                            for z in ev.zones:
                                z_type_str = z.zone_type.value if hasattr(z.zone_type, "value") else str(z.zone_type)
                                if "SBR" in z_type_str:
                                    border_color, fill_color = "#ff5252", "rgba(255, 82, 82, 0.15)"
                                elif "RBS" in z_type_str:
                                    border_color, fill_color = "#00e676", "rgba(0, 230, 118, 0.15)"
                                elif "QML" in z_type_str:
                                    border_color, fill_color = "#b388ff", "rgba(179, 136, 255, 0.15)"
                                elif "TOP" in z_type_str:
                                    border_color, fill_color = "#ff7043", "rgba(255, 112, 67, 0.15)"
                                else:
                                    border_color, fill_color = "#26a69a", "rgba(38, 166, 154, 0.15)"

                                if z.is_line:
                                    shapes.append(
                                        dict(
                                            type="line",
                                            x0=x0_zone,
                                            x1=x1_zone,
                                            y0=z.lower_price,
                                            y1=z.lower_price,
                                            line=dict(color=border_color, width=1.5, dash="dash"),
                                        )
                                    )
                                else:
                                    shapes.append(
                                        dict(
                                            type="rect",
                                            x0=x0_zone,
                                            x1=x1_zone,
                                            y0=z.lower_price,
                                            y1=z.upper_price,
                                            fillcolor=fill_color,
                                            line=dict(color=border_color, width=1),
                                        )
                                    )

                                mid_y = (z.lower_price + z.upper_price) / 2.0
                                hover_z = (
                                    f"<b>Zone: {z_type_str}</b><br>"
                                    f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if z.is_line else ''}<br>"
                                    f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                                    f"{conf_avail_label}"
                                )
                                fig.add_trace(
                                    go.Scatter(
                                        x=[x0_zone, x1_zone],
                                        y=[mid_y, mid_y],
                                        mode="lines",
                                        name=f"Zone: {z_type_str}",
                                        line=dict(color=border_color, width=1, dash="dot"),
                                        hovertext=[hover_z, hover_z],
                                        hoverinfo="text",
                                        showlegend=False,
                                    )
                                )

            # 10. ISS Structural Overlays, Confirmation Markers & Zones
            iss_snap = getattr(msm_result, "iss_snapshot", None)
            confirmed_iss_events = getattr(msm_result, "confirmed_iss_events", ())
            show_iss_markers = getattr(ctx, "show_iss_markers", True) if ctx else True
            show_iss_zones = getattr(ctx, "show_iss_zones", True) if ctx else True
            show_iss_points = getattr(ctx, "show_iss_points", True) if ctx else True

            if iss_snap is not None:
                # Add ISS lifecycle status summary to title
                status_val = iss_snap.lifecycle_status.value if hasattr(iss_snap.lifecycle_status, "value") else str(iss_snap.lifecycle_status)
                title_parts.append(
                    f"<span style='color: #a7ffeb;'>ISS: {status_val} ({len(confirmed_iss_events)} confirmed)</span>"
                )

                # Frozen boundary guidelines (when boundary is captured)
                b = iss_snap.captured_boundary
                if b is not None and iss_snap.lifecycle_status in (
                    ISSLifecycleStatus.ELIGIBLE_SEARCH,
                    ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
                    ISSLifecycleStatus.CONFIRMED,
                ):
                    b_x0 = df.index[0]
                    b_x1 = last_chart_time
                    shapes.append(
                        dict(
                            type="line",
                            x0=b_x0,
                            x1=b_x1,
                            y0=b.min_price,
                            y1=b.min_price,
                            line=dict(color="#26a69a", width=1, dash="dot"),
                        )
                    )
                    shapes.append(
                        dict(
                            type="line",
                            x0=b_x0,
                            x1=b_x1,
                            y0=b.max_price,
                            y1=b.max_price,
                            line=dict(color="#26a69a", width=1, dash="dot"),
                        )
                    )

                # Internal structural points
                if show_iss_points:
                    # In ELIGIBLE_SEARCH or CONFIRMED: render visible internal points
                    if iss_snap.lifecycle_status in (
                        ISSLifecycleStatus.ELIGIBLE_SEARCH,
                        ISSLifecycleStatus.CONFIRMED,
                    ):
                        for pt in iss_snap.internal_points:
                            pt_time = pt.candle_open_time
                            if pt_time in df.index:
                                is_high_pt = "H" in pt.role or "CH" in pt.role
                                pt_sym = "circle" if pt.is_confirmed else "circle-open"
                                pt_color = "#69f0ae" if is_high_pt else "#ffab91"
                                pt_pos = "top center" if is_high_pt else "bottom center"
                                pt_hover = (
                                    f"<b>Internal Point {pt.point_number} ({pt.role})</b><br>"
                                    f"Price: {pt.body_edge_price:.4f} (Bar #{pt.source_candle_index})<br>"
                                    f"Status: {'Confirmed' if pt.is_confirmed else 'Tentative'}<br>"
                                    f"Inside Boundary: {pt.is_inside_boundary}"
                                )
                                fig.add_trace(
                                    go.Scatter(
                                        x=[pt_time],
                                        y=[pt.body_edge_price],
                                        mode="markers+text",
                                        name=f"Internal {pt.role}",
                                        marker=dict(symbol=pt_sym, size=9, color=pt_color, line=dict(width=1.5, color="#ffffff")),
                                        text=[f"P{pt.point_number}:{pt.role}"],
                                        textposition=pt_pos,
                                        textfont=dict(color=pt_color, size=10),
                                        hovertext=[pt_hover],
                                        hoverinfo="text",
                                        showlegend=False,
                                    )
                                )

                    # In OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY: render attempted points and ongoing tracking points separately
                    elif iss_snap.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY:
                        if iss_snap.attempted_points:
                            for pt in iss_snap.attempted_points:
                                pt_time = pt.candle_open_time
                                if pt_time in df.index:
                                    pt_hover = (
                                        f"<b>Attempted Point {pt.point_number} ({pt.role}) [Tracking Only — Not Eligible]</b><br>"
                                        f"Price: {pt.body_edge_price:.4f} (Bar #{pt.source_candle_index})<br>"
                                        f"Status: Attempted Sequence Retained for Audit"
                                    )
                                    fig.add_trace(
                                        go.Scatter(
                                            x=[pt_time],
                                            y=[pt.body_edge_price],
                                            mode="markers+text",
                                            name="Attempted (Tracking Only)",
                                            marker=dict(symbol="x", size=8, color="#9e9e9e"),
                                            text=[f"Att-P{pt.point_number}"],
                                            textposition="top center",
                                            textfont=dict(color="#9e9e9e", size=9),
                                            hovertext=[pt_hover],
                                            hoverinfo="text",
                                            showlegend=False,
                                        )
                                    )

                        if iss_snap.tracking_points:
                            for pt in iss_snap.tracking_points:
                                pt_time = pt.candle_open_time
                                if pt_time in df.index:
                                    pt_hover = (
                                        f"<b>Ongoing Tracking Point {pt.point_number} ({pt.role}) [Tracking Only — Not Eligible]</b><br>"
                                        f"Price: {pt.body_edge_price:.4f} (Bar #{pt.source_candle_index})"
                                    )
                                    fig.add_trace(
                                        go.Scatter(
                                            x=[pt_time],
                                            y=[pt.body_edge_price],
                                            mode="markers",
                                            name="Tracking Swing (Tracking Only)",
                                            marker=dict(symbol="diamond-dot", size=7, color="#78909c"),
                                            hovertext=[pt_hover],
                                            hoverinfo="text",
                                            showlegend=False,
                                        )
                                    )

            # Confirmed ISS Confirmation Markers & Zones
            if confirmed_iss_events:
                candles_seq = getattr(msm_result, "candles", ())
                for ev in confirmed_iss_events:
                    c_conf_idx = ev.confirmation_candle_index
                    conf_candles = [c for c in candles_seq if c.index == c_conf_idx]
                    conf_candle = conf_candles[0] if conf_candles else None
                    conf_time = conf_candle.open_time if conf_candle else None

                    if show_iss_markers and conf_time is not None and conf_time in df.index:
                        is_bearish_main = ev.main_direction == Direction.DOWNWARD
                        m_sym = "star"
                        m_color = "#64ffda" if is_bearish_main else "#ffd740"
                        m_pos = "top center" if is_bearish_main else "bottom center"

                        if ev.confirmation_time is not None:
                            conf_avail_str = f"Confirmed At: {ev.confirmation_time.strftime('%Y-%m-%d %H:%M UTC')} (Candle Close)"
                        else:
                            conf_avail_str = f"Confirmation Availability: Unknown — confirmed on completion of candle Bar #{ev.confirmation_candle_index}"

                        iss_hover = (
                            f"<b>Confirmed ISS Event [Structural Event — Not Order Entry Signal]</b><br>"
                            f"Candidate ID: {ev.candidate_id}<br>"
                            f"Main Direction: {ev.main_direction.value}<br>"
                            f"Confirmation Candle: Bar #{ev.confirmation_candle_index} (Open: {conf_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                            f"Completion Close: {ev.completion_close_price:.4f}<br>"
                            f"Frozen Boundary: [{ev.captured_boundary.min_price:.4f}, {ev.captured_boundary.max_price:.4f}]<br>"
                            f"{conf_avail_str}<br>"
                            f"Level 3 Zone: {ev.level_3_zone.zone_type.value} [{ev.level_3_zone.lower_price:.4f}, {ev.level_3_zone.upper_price:.4f}]<br>"
                            f"Level 4 Zone: {ev.level_4_zone.zone_type.value} [{ev.level_4_zone.lower_price:.4f}, {ev.level_4_zone.upper_price:.4f}]"
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=[conf_time],
                                y=[ev.completion_close_price],
                                mode="markers+text",
                                name="ISS Confirmed",
                                marker=dict(symbol=m_sym, size=14, color=m_color, line=dict(width=1.5, color="#ffffff")),
                                text=["ISS"],
                                textposition=m_pos,
                                textfont=dict(color=m_color, size=11, family="Segoe UI, sans-serif"),
                                hovertext=[iss_hover],
                                hoverinfo="text",
                            )
                        )

                    # Zones
                    if show_iss_zones:
                        for z in [ev.level_3_zone, ev.level_4_zone]:
                            if z.confirmation_availability_time is not None:
                                x0_zone = z.confirmation_availability_time
                                conf_avail_label = f"Structural zone available from: {z.confirmation_availability_time.strftime('%Y-%m-%d %H:%M UTC')}"
                                x1_zone = max(last_chart_time, x0_zone)
                                z_type_str = z.zone_type.value if hasattr(z.zone_type, "value") else str(z.zone_type)

                                if "RBS" in z_type_str or "BUYING" in z_type_str:
                                    border_color, fill_color = "#00e676", "rgba(0, 230, 118, 0.15)"
                                else:
                                    border_color, fill_color = "#ff5252", "rgba(255, 82, 82, 0.15)"

                                if z.is_line:
                                    shapes.append(
                                        dict(
                                            type="line",
                                            x0=x0_zone,
                                            x1=x1_zone,
                                            y0=z.lower_price,
                                            y1=z.lower_price,
                                            line=dict(color=border_color, width=1.5, dash="dash"),
                                        )
                                    )
                                else:
                                    shapes.append(
                                        dict(
                                            type="rect",
                                            x0=x0_zone,
                                            x1=x1_zone,
                                            y0=z.lower_price,
                                            y1=z.upper_price,
                                            fillcolor=fill_color,
                                            line=dict(color=border_color, width=1),
                                        )
                                    )

                                mid_y = (z.lower_price + z.upper_price) / 2.0
                                hover_z = (
                                    f"<b>ISS Zone: {z_type_str} [Structural Zone — Not Order Execution]</b><br>"
                                    f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if z.is_line else ''}<br>"
                                    f"Source Candle: Bar #{z.source_candle_index} (Point {z.source_point_number}: {z.source_point_role})<br>"
                                    f"{conf_avail_label}"
                                )
                                fig.add_trace(
                                    go.Scatter(
                                        x=[x0_zone, x1_zone],
                                        y=[mid_y, mid_y],
                                        mode="lines",
                                        name=f"ISS Zone: {z_type_str}",
                                        line=dict(color=border_color, width=1, dash="dot"),
                                        hovertext=[hover_z, hover_z],
                                        hoverinfo="text",
                                        showlegend=False,
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
