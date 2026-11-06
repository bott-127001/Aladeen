"""TJL (Trend Joining Level) chart overlay construction.

Renders read-only structural overlays for Trend Joining Levels on the candlestick chart:
- Current Eligible Set (solid green #00e676 for TJL1, purple #ab47bc for TJL2_A_PLUS)
- Historical Sets (slate gray #78909c, dot dash pattern, strictly filtered by replacement/cancellation record)
- Labels Only (amber/orange #ffb74d, dash pattern, awaiting set formation)
- Exact zero-width geometry rendered strictly as lines (y0 == y1) without artificial widening
- Strict availability timing: unknown availability omits time-extended eligible shapes
- Frozen unresolved evidence: bounded at authoritative processed bar, not extended across unresolved receipts
- Honest hover tooltips carrying mandatory non-execution disclaimers

Scope Boundary:
---------------
Read-only visualization only. Strictly zero order execution, zero MT5 trading calls,
zero zone activations, zero usage ledger, zero tap tracking, and zero trade entry signals.
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import plotly.graph_objects as go

from aladeen.strategy import CurrentEligibleSet, TJLLabel, TJLSnapshot, TJLTransitionType, TJLZone


def resolve_authoritative_endpoint(
    df: pd.DataFrame,
    msm_result: Any,
    last_processed_index: int | None,
) -> tuple[Any | None, Any | None]:
    """Resolves authoritative candle open_time and close_time by explicit source ID mapping.

    Never treats last_processed_index as a DataFrame row offset.
    Supports arbitrary, sparse, and decreasing source candle IDs.

    Returns
    -------
    tuple[Any | None, Any | None]
        (open_time, close_time). If the authoritative source candle cannot be found
        in msm_result.candles or df, returns (None, None).
    """
    if last_processed_index is None or last_processed_index < 0:
        return None, None

    # 1. Search explicit StrategyCandle records from calculation result
    candles = getattr(msm_result, "candles", None)
    if candles:
        for c in candles:
            if getattr(c, "index", None) == last_processed_index:
                open_t = getattr(c, "open_time", None)
                close_t = getattr(c, "close_time", None)
                return open_t, close_t

    # 2. Search explicit 'index' column in DataFrame view
    if "index" in df.columns:
        matched = df[df["index"] == last_processed_index]
        if not matched.empty:
            open_t = matched.index[0]
            close_t = matched["close_time"].iloc[0] if "close_time" in matched.columns else None
            if close_t is not None and pd.isna(close_t):
                close_t = None
            return open_t, close_t

    return None, None


def apply_tjl_overlays(
    fig: go.Figure,
    df: pd.DataFrame,
    msm_result: Any,
    shapes: list[dict],
    last_chart_time: Any,
    *,
    show_tjl_zones: bool | None = None,
    show_tjl_current_set: bool | None = None,
    show_tjl_historical_sets: bool | None = None,
    show_tjl_labels: bool | None = None,
) -> None:
    """Build and apply TJL overlay shapes and hover traces to *fig* and *shapes*.

    Parameters
    ----------
    fig : go.Figure
        Target Plotly figure to which hover traces are added.
    df : pd.DataFrame
        OHLC DataFrame of current chart view.
    msm_result : Any
        MSM service result containing optional tjl_snapshot and context.
    shapes : list[dict]
        Target layout shapes collection being populated for the chart.
    last_chart_time : Any
        Timestamp of the rightmost candle on the chart.
    """
    tjl_snap = getattr(msm_result, "tjl_snapshot", None)
    if tjl_snap is None or not isinstance(tjl_snap, TJLSnapshot):
        return

    ctx = getattr(msm_result, "context", None)
    if show_tjl_zones is None:
        show_tjl_zones = getattr(ctx, "show_tjl_zones", True) if ctx else True
    if show_tjl_current_set is None:
        show_tjl_current_set = getattr(ctx, "show_tjl_current_set", True) if ctx else True
    if show_tjl_historical_sets is None:
        show_tjl_historical_sets = getattr(ctx, "show_tjl_historical_sets", True) if ctx else True
    if show_tjl_labels is None:
        show_tjl_labels = getattr(ctx, "show_tjl_labels", True) if ctx else True

    if not show_tjl_zones:
        return

    # -------------------------------------------------------------
    # 0. Lifecycle Classification (Independent of Display Toggles)
    # -------------------------------------------------------------
    curr_set = tjl_snap.current_eligible_set
    curr_level_ids = set()
    curr_role_level_ids = set()
    if curr_set is not None:
        curr_level_ids.add(curr_set.tjl1_zone.level_id)
        curr_level_ids.add(curr_set.tjl2_zone.level_id)
        curr_role_level_ids.add((curr_set.tjl1_zone.level_id, curr_set.tjl1_zone.label))
        curr_role_level_ids.add((curr_set.tjl2_zone.level_id, curr_set.tjl2_zone.label))

    # Pre-compute historical sets unconditionally
    hist_level_ids = set()
    hist_role_level_ids = set()
    historical_entries: list[tuple[CurrentEligibleSet, Any, str]] = []

    for h_set in tjl_snap.historical_sets:
        # Invariant 1: Exclude the current set by identity!
        if curr_set is not None and h_set.set_id == curr_set.set_id:
            continue

        # Invariant 2: Filter by actual lifecycle termination record.
        cancel_tr = next(
            (tr for tr in tjl_snap.transition_history if tr.outgoing_cancelled_set_id == h_set.set_id),
            None,
        )
        if cancel_tr is None:
            continue

        hist_level_ids.add(h_set.tjl1_zone.level_id)
        hist_level_ids.add(h_set.tjl2_zone.level_id)
        hist_role_level_ids.add((h_set.tjl1_zone.level_id, h_set.tjl1_zone.label))
        hist_role_level_ids.add((h_set.tjl2_zone.level_id, h_set.tjl2_zone.label))

        if cancel_tr.transition_type == TJLTransitionType.CHOCH_INVALIDATION:
            status_desc = "Historical Structural Set — CHOCH Invalidated"
        else:
            status_desc = "Historical Structural Set — Superseded by Replacement"

        historical_entries.append((h_set, cancel_tr, status_desc))

    # Pre-compute labels-only zones unconditionally
    labels_only_zones: list[TJLZone] = []
    if tjl_snap.all_labeled_zones:
        for z in tjl_snap.all_labeled_zones:
            # Skip if zone currently serves in active current set with this contextual role
            if (z.level_id, z.label) in curr_role_level_ids:
                continue
            # Skip if this zone was part of a terminated historical set with this contextual role
            if (z.level_id, z.label) in hist_role_level_ids:
                continue
            labels_only_zones.append(z)

    # -------------------------------------------------------------
    # 1. Historical Superseded / Cancelled Sets Rendering
    # -------------------------------------------------------------
    if show_tjl_historical_sets:
        for h_set, cancel_tr, status_desc in historical_entries:
            t_term = cancel_tr.transition_time
            if t_term is None:
                # Termination occurred but timestamp is unknown:
                # Never fall back to chart endpoint as eligibility endpoint!
                # Omit time-extended shape; render compact source reference.
                for z in [h_set.tjl1_zone, h_set.tjl2_zone]:
                    role_str = z.label.value if hasattr(z.label, "value") else str(z.label)
                    mid_y = (z.lower_price + z.upper_price) / 2.0
                    hover_text = (
                        f"<b>Historical TJL Source Reference: {role_str} [{status_desc} — Termination Timestamp Unknown]</b><br>"
                        f"Set ID: {h_set.set_id}<br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Availability: Unknown (no retroactive eligible interval plotted)"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[z.source_candle_open_time],
                            y=[mid_y],
                            mode="markers",
                            name=f"Historical TJL Source: {h_set.set_id} ({role_str})",
                            marker=dict(symbol="circle-open", size=6, color="#78909c"),
                            hovertext=[hover_text],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
            elif h_set.eligibility_available_time is not None:
                # Known start and known termination: render bounded historical eligible interval
                x0_zone = h_set.eligibility_available_time
                x1_zone = max(x0_zone, t_term)
                avail_label = f"Eligible Period: {x0_zone.strftime('%Y-%m-%d %H:%M UTC')} to {t_term.strftime('%Y-%m-%d %H:%M UTC')}"

                for z in [h_set.tjl1_zone, h_set.tjl2_zone]:
                    border_color = "#78909c"
                    fill_color = "rgba(120, 144, 156, 0.08)"
                    role_str = z.label.value if hasattr(z.label, "value") else str(z.label)
                    shape_name = f"tjl_zone_historical_{role_str.lower()}"

                    is_zero_width = z.is_line or (z.lower_price == z.upper_price)
                    if is_zero_width:
                        shapes.append(
                            dict(
                                type="line",
                                name=shape_name,
                                x0=x0_zone,
                                x1=x1_zone,
                                y0=z.lower_price,
                                y1=z.lower_price,
                                line=dict(color=border_color, width=1, dash="dot"),
                            )
                        )
                    else:
                        shapes.append(
                            dict(
                                type="rect",
                                name=shape_name,
                                x0=x0_zone,
                                x1=x1_zone,
                                y0=z.lower_price,
                                y1=z.upper_price,
                                fillcolor=fill_color,
                                line=dict(color=border_color, width=1, dash="dot"),
                            )
                        )

                    mid_y = (z.lower_price + z.upper_price) / 2.0
                    hover_text = (
                        f"<b>Historical TJL: {role_str} [{status_desc}]</b><br>"
                        f"Set ID: {h_set.set_id}<br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if is_zero_width else ''}<br>"
                        f"Level ID: {z.level_id.to_tuple()}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Direction: {h_set.direction.value}<br>"
                        f"{avail_label}"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[x0_zone, x1_zone],
                            y=[mid_y, mid_y],
                            mode="lines",
                            name=f"Historical TJL: {h_set.set_id} ({role_str})",
                            line=dict(color=border_color, width=1, dash="dot"),
                            hovertext=[hover_text, hover_text],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
            else:
                # Unknown start availability: omit time-extended interval
                for z in [h_set.tjl1_zone, h_set.tjl2_zone]:
                    role_str = z.label.value if hasattr(z.label, "value") else str(z.label)
                    mid_y = (z.lower_price + z.upper_price) / 2.0
                    hover_text = (
                        f"<b>Historical TJL Source Reference: {role_str} [{status_desc} — Start Availability Unknown]</b><br>"
                        f"Set ID: {h_set.set_id}<br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Availability: Unknown (no retroactive eligible interval plotted)"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[z.source_candle_open_time],
                            y=[mid_y],
                            mode="markers",
                            name=f"Historical TJL Source: {h_set.set_id} ({role_str})",
                            marker=dict(symbol="circle-open", size=6, color="#78909c"),
                            hovertext=[hover_text],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )

    # -------------------------------------------------------------
    # 2. Confirmed Labels without Active Set (Labels Only) Rendering
    # -------------------------------------------------------------
    if show_tjl_labels:
        for z in labels_only_zones:
            x0_zone = z.confirmed_time or z.source_candle_open_time
            x1_zone = max(last_chart_time, x0_zone)
            border_color = "#ffb74d"
            fill_color = "rgba(255, 183, 77, 0.12)"
            role_str = z.label.value if hasattr(z.label, "value") else str(z.label)
            shape_name = f"tjl_zone_label_{role_str.lower()}"

            is_zero_width = z.is_line or (z.lower_price == z.upper_price)
            if is_zero_width:
                shapes.append(
                    dict(
                        type="line",
                        name=shape_name,
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
                        name=shape_name,
                        x0=x0_zone,
                        x1=x1_zone,
                        y0=z.lower_price,
                        y1=z.upper_price,
                        fillcolor=fill_color,
                        line=dict(color=border_color, width=1.5, dash="dash"),
                    )
                )

            mid_y = (z.lower_price + z.upper_price) / 2.0
            conf_avail_label = (
                f"Confirmed at: {z.confirmed_time.strftime('%Y-%m-%d %H:%M UTC')}"
                if z.confirmed_time is not None
                else f"Confirmation: Unknown (Source Bar #{z.source_candle_index})"
            )
            hover_text = (
                f"<b>TJL Labeled Zone: {role_str} [Structural Label Only — Awaiting Set Formation]</b><br>"
                f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if is_zero_width else ''}<br>"
                f"Level ID: {z.level_id.to_tuple()}<br>"
                f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                f"{conf_avail_label}"
            )
            fig.add_trace(
                go.Scatter(
                    x=[x0_zone, x1_zone],
                    y=[mid_y, mid_y],
                    mode="lines",
                    name=f"TJL Label: {role_str}",
                    line=dict(color=border_color, width=1.5, dash="dash"),
                    hovertext=[hover_text, hover_text],
                    hoverinfo="text",
                    showlegend=False,
                )
            )

    # -------------------------------------------------------------
    # 3. Current Eligible Set (or Frozen Last Authoritative Evidence)
    # -------------------------------------------------------------
    if show_tjl_current_set and curr_set is not None:
        is_unres = bool(tjl_snap.is_unresolved)

        for z in [curr_set.tjl1_zone, curr_set.tjl2_zone]:
            role_str = z.label.value if hasattr(z.label, "value") else str(z.label)
            is_tjl1 = (z.label == TJLLabel.TJL1)
            border_color = "#00e676" if is_tjl1 else "#ab47bc"
            fill_color = "rgba(0, 230, 118, 0.18)" if is_tjl1 else "rgba(171, 71, 188, 0.18)"
            shape_name = f"tjl_zone_current_{role_str.lower()}"
            is_zero_width = z.is_line or (z.lower_price == z.upper_price)
            mid_y = (z.lower_price + z.upper_price) / 2.0

            if is_unres:
                # Unresolved ambiguity: Frozen Last Authoritative Evidence
                # Do NOT extend eligibility claim across unresolved receipts!
                status_header = f"Current Set: {curr_set.set_id} ({role_str}) [Last Authoritative Evidence — Frozen Pending Resolution]"

                # Resolve authoritative endpoint through explicit source ID mapping (never by row offset!)
                auth_open_t, auth_close_t = resolve_authoritative_endpoint(
                    df, msm_result, tjl_snap.last_processed_index
                )
                t_auth = auth_close_t if auth_close_t is not None else auth_open_t

                if curr_set.eligibility_available_time is not None and t_auth is not None and t_auth >= curr_set.eligibility_available_time:
                    x0_zone = curr_set.eligibility_available_time
                    x1_zone = t_auth
                    avail_label = (
                        f"Availability: Frozen at Bar #{tjl_snap.last_processed_index} "
                        f"({t_auth.strftime('%Y-%m-%d %H:%M UTC')}) — no eligibility extension across unresolved receipts"
                    )

                    if is_zero_width:
                        shapes.append(
                            dict(
                                type="line",
                                name=shape_name,
                                x0=x0_zone,
                                x1=x1_zone,
                                y0=z.lower_price,
                                y1=z.lower_price,
                                line=dict(color=border_color, width=2, dash="dash"),
                            )
                        )
                    else:
                        shapes.append(
                            dict(
                                type="rect",
                                name=shape_name,
                                x0=x0_zone,
                                x1=x1_zone,
                                y0=z.lower_price,
                                y1=z.upper_price,
                                fillcolor=fill_color,
                                line=dict(color=border_color, width=2, dash="dash"),
                            )
                        )

                    hover_text = (
                        f"<b>{status_header}</b><br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if is_zero_width else ''}<br>"
                        f"Level ID: {z.level_id.to_tuple()}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Direction: {curr_set.direction.value} | Epoch: {tjl_snap.structural_epoch}<br>"
                        f"Fingerprint: {curr_set.fingerprint.to_tuple()}<br>"
                        f"{avail_label}"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[x0_zone, x1_zone],
                            y=[mid_y, mid_y],
                            mode="lines",
                            name=f"Current TJL Set: {curr_set.set_id} ({role_str})",
                            line=dict(color=border_color, width=2, dash="dash"),
                            hovertext=[hover_text, hover_text],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
                else:
                    # Missing, invalid, or window-excluded authoritative endpoint:
                    # Never fall back to last_chart_time! Omit time-extended shape and render compact source marker.
                    source_hover = (
                        f"<b>{status_header} — Authoritative Endpoint Unavailable</b><br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if is_zero_width else ''}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Authoritative Bar Index: #{tjl_snap.last_processed_index}<br>"
                        f"Availability: Authoritative endpoint unavailable (no retroactive or extended eligible interval plotted)"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[z.source_candle_open_time],
                            y=[mid_y],
                            mode="markers",
                            name=f"Current TJL Source: {curr_set.set_id} ({role_str})",
                            marker=dict(symbol="diamond", size=7, color=border_color),
                            hovertext=[source_hover],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )

            else:
                # Resolved Active Eligible Set
                if curr_set.eligibility_available_time is not None:
                    x0_zone = curr_set.eligibility_available_time
                    x1_zone = max(last_chart_time, x0_zone)
                    avail_label = f"Available from: {curr_set.eligibility_available_time.strftime('%Y-%m-%d %H:%M UTC')}"

                    if is_zero_width:
                        shapes.append(
                            dict(
                                type="line",
                                name=shape_name,
                                x0=x0_zone,
                                x1=x1_zone,
                                y0=z.lower_price,
                                y1=z.lower_price,
                                line=dict(color=border_color, width=2),
                            )
                        )
                    else:
                        shapes.append(
                            dict(
                                type="rect",
                                name=shape_name,
                                x0=x0_zone,
                                x1=x1_zone,
                                y0=z.lower_price,
                                y1=z.upper_price,
                                fillcolor=fill_color,
                                line=dict(color=border_color, width=2),
                            )
                        )

                    hover_text = (
                        f"<b>Current Eligible Set: {curr_set.set_id} ({role_str}) [Structural Set Only — Downstream activation/ledger not present]</b><br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if is_zero_width else ''}<br>"
                        f"Level ID: {z.level_id.to_tuple()}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Direction: {curr_set.direction.value} | Epoch: {tjl_snap.structural_epoch}<br>"
                        f"Fingerprint: {curr_set.fingerprint.to_tuple()}<br>"
                        f"{avail_label}"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[x0_zone, x1_zone],
                            y=[mid_y, mid_y],
                            mode="lines",
                            name=f"Current TJL Set: {curr_set.set_id} ({role_str})",
                            line=dict(color=border_color, width=2),
                            hovertext=[hover_text, hover_text],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
                else:
                    # Unknown availability in resolved state: omit time-extended shape
                    source_hover = (
                        f"<b>Current Set Source Reference: {role_str} [Source Geometry — Availability Unknown, Not Time-Extended]</b><br>"
                        f"Set ID: {curr_set.set_id} | Direction: {curr_set.direction.value}<br>"
                        f"Price: {z.lower_price:.4f} – {z.upper_price:.4f}{' (Line)' if is_zero_width else ''}<br>"
                        f"Source Candle: Bar #{z.source_candle_index} ({z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')})<br>"
                        f"Availability: Unknown (no retroactive eligible interval plotted)"
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=[z.source_candle_open_time],
                            y=[mid_y],
                            mode="markers",
                            name=f"Current TJL Source: {role_str}",
                            marker=dict(symbol="diamond", size=7, color=border_color),
                            hovertext=[source_hover],
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )
