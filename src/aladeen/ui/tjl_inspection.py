"""TJL (Trend Joining Level) inspection panel element generation.

Renders read-only inspection cards, tables, and transition audits:
- Engine Status card (Direction, Epoch, Set ID, Outgoing Cancellation Intent)
- Current Eligible Set table with explicit availability timestamps and non-execution disclaimers
- All Labeled Zones table with structural provenance and membership badges
- Lifecycle Transition History table detailing transitions, timestamps, and cancelled sets
- Separate display of Authoritative Processed Bar vs Latest Received Input
- Distinct labeling of Unresolved Ambiguity as "Last Authoritative Evidence — Not Freshly Eligible"

Scope Boundary:
---------------
Read-only presentation only. Strictly zero order execution, zero MT5 trading calls,
zero zone activations, zero usage ledger, zero tap tracking, and zero trade entry signals.
"""

from __future__ import annotations

from typing import Any
from dash import html

from aladeen.strategy import TJLLabel, TJLSnapshot


def build_tjl_inspection_elements(msm_result: Any) -> list[html.Div]:
    """Build TJL inspection HTML components from *msm_result*.

    Parameters
    ----------
    msm_result : Any
        MSM service result containing optional tjl_snapshot.

    Returns
    -------
    list[html.Div]
        Dash HTML components rendering the TJL inspection section.
    """
    elements: list[html.Div] = []
    tjl_snap = getattr(msm_result, "tjl_snapshot", None)
    if tjl_snap is None or not isinstance(tjl_snap, TJLSnapshot):
        return elements

    curr_set = tjl_snap.current_eligible_set

    # 1. Badge & Engine Status Card
    if tjl_snap.is_unresolved:
        badge_bg, badge_fg = "#b71c1c", "#ef9a9a"
        badge_text = "UNRESOLVED AMBIGUITY (LAST AUTHORITATIVE EVIDENCE)"
    elif curr_set is not None:
        badge_bg, badge_fg = "#1b5e20", "#a5d6a7"
        badge_text = f"ELIGIBLE SET ACTIVE ({curr_set.set_id})"
    elif tjl_snap.all_labeled_zones:
        badge_bg, badge_fg = "#e65100", "#ffb74d"
        badge_text = f"LABELS ONLY ({len(tjl_snap.all_labeled_zones)} ZONES)"
    else:
        badge_bg, badge_fg = "#212121", "#9e9e9e"
        badge_text = "AWAITING STRUCTURE"

    badge = html.Span(
        badge_text,
        id="tjl-status-badge",
        style={
            "padding": "3px 8px",
            "borderRadius": "4px",
            "background": badge_bg,
            "color": badge_fg,
            "fontWeight": "bold",
            "fontSize": "11px",
        },
    )

    dir_str = tjl_snap.direction.value if tjl_snap.direction is not None else "None"
    id_details = [
        html.Span([html.B("Engine ID: "), html.Code(tjl_snap.source_engine_id, style={"color": "#00e5ff"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Feed / TF: "), html.Span(f"{tjl_snap.symbol_feed_id} ({tjl_snap.source_timeframe})", style={"color": "#90caf9"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Direction: "), html.Span(dir_str, style={"color": "#ff80ab", "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Structural Epoch: "), html.Span(str(tjl_snap.structural_epoch), style={"color": "#b388ff", "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span([html.B("Current Set ID: "), html.Span(curr_set.set_id if curr_set else "None", style={"color": "#00e676" if curr_set else "#ffd54f", "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc"}),
        html.Span(
            [
                html.B("Outgoing Cancel Intent: "),
                html.Span(
                    "YES" if tjl_snap.outgoing_cancellation_intent else "NO",
                    id="tjl-outgoing-cancel-intent-badge",
                    style={"color": "#ff5252" if tjl_snap.outgoing_cancellation_intent else "#aaa", "fontWeight": "bold"},
                ),
            ],
            style={"fontSize": "12px", "color": "#ccc"},
        ),
    ]

    diag_children = []
    if tjl_snap.unresolved_diagnostic:
        diag_children.append(
            html.P(
                f"Diagnostic: {tjl_snap.unresolved_diagnostic} [Last Authoritative Evidence Retained]",
                id="tjl-diagnostic-message",
                style={"fontSize": "12px", "color": "#ff9800", "margin": "4px 0 0 0", "fontWeight": "bold"},
            )
        )

    progress_bar = html.Div(
        id="tjl-progress-container",
        style={"fontSize": "11px", "color": "#888", "marginTop": "4px"},
        children=[
            html.Span(f"Authoritative Processed Bar: #{tjl_snap.last_processed_index}", id="tjl-processed-index", style={"color": "#80d8ff"}),
            html.Span(" | "),
            html.Span(f"Latest Received Input: Bar #{tjl_snap.last_received_index}", id="tjl-received-index", style={"color": "#ffb74d"}),
        ],
    )

    elements.append(
        html.Div(
            id="tjl-status-card",
            style={
                "background": "#161626",
                "border": "1px solid #2a2a44",
                "borderRadius": "6px",
                "padding": "10px 14px",
                "marginBottom": "14px",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "8px"},
                    children=[
                        html.H5("🔗 Trend Joining Level (TJL) Status & Eligible Set", style={"color": "#00e5ff", "margin": 0}),
                        badge,
                    ],
                ),
                html.Div(
                    style={"display": "flex", "gap": "14px", "alignItems": "center", "flexWrap": "wrap", "marginBottom": "4px"},
                    children=id_details,
                ),
                *diag_children,
                progress_bar,
            ],
        )
    )

    # 2. Current Eligible Set Detailed Table
    if curr_set is not None:
        if curr_set.eligibility_available_time is not None:
            avail_str = curr_set.eligibility_available_time.strftime("%Y-%m-%d %H:%M UTC")
            avail_color = "#80d8ff"
        else:
            avail_str = "Unknown (Pending candle completion — no retroactive eligible interval plotted)"
            avail_color = "#ffb74d"

        fp_tuple = curr_set.fingerprint.to_tuple()
        fp_str = f"({fp_tuple[0]}, {fp_tuple[1]}, CH:{fp_tuple[2]}, CL:{fp_tuple[3]}, P3:{fp_tuple[4]})"
        p3_info = f"Bar #{curr_set.p3_source_index} ({curr_set.p3_open_time.strftime('%Y-%m-%d %H:%M UTC')}) @ {curr_set.p3_price:.4f}"

        set_header_children = [
            html.Span([html.B("Set Fingerprint: "), html.Code(fp_str, style={"color": "#b388ff"})], style={"fontSize": "12px", "color": "#ccc"}),
            html.Span([html.B("Tentative P3 Anchor: "), html.Span(p3_info, style={"color": "#ffd54f"})], style={"fontSize": "12px", "color": "#ccc"}),
            html.Span([html.B("Eligibility Available: "), html.Span(avail_str, id="tjl-current-set-avail-time", style={"color": avail_color, "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc"}),
        ]
        if tjl_snap.is_unresolved:
            set_header_children.append(
                html.Span("[Last Authoritative Evidence — Frozen Pending Resolution]", style={"color": "#ff5252", "fontSize": "11px", "fontWeight": "bold"})
            )

        set_header_info = html.Div(
            style={"display": "flex", "gap": "16px", "alignItems": "center", "flexWrap": "wrap", "marginBottom": "8px"},
            children=set_header_children,
        )

        zone_rows = []
        for z in [curr_set.tjl1_zone, curr_set.tjl2_zone]:
            price_str = f"{z.lower_price:.4f} – {z.upper_price:.4f}" if not z.is_line else f"{z.lower_price:.4f}"
            geom_str = "Line (Thickness 0)" if z.is_line else "Box / Area"
            role_color = "#00e676" if z.label == TJLLabel.TJL1 else "#ab47bc"
            lid_str = f"({z.level_id.symbol_feed_id}, {z.level_id.source_timeframe}, {z.level_id.source_open_time.strftime('%H:%M')}, {z.level_id.side.value})"

            conf_str = (
                z.confirmed_time.strftime("%Y-%m-%d %H:%M UTC")
                if z.confirmed_time is not None
                else f"Unknown (Source Bar #{z.source_candle_index})"
            )

            zone_rows.append(
                html.Tr(
                    style={"borderBottom": "1px solid #232338", "fontSize": "12px", "color": "#e0e0e0"},
                    children=[
                        html.Td(
                            html.Span(
                                z.label.value,
                                style={
                                    "padding": "2px 6px",
                                    "borderRadius": "3px",
                                    "background": "#004d40" if z.label == TJLLabel.TJL1 else "#4a148c",
                                    "color": role_color,
                                    "fontSize": "11px",
                                    "fontWeight": "bold",
                                },
                            ),
                            style={"padding": "6px 12px"},
                        ),
                        html.Td(price_str, style={"padding": "6px 12px", "fontWeight": "bold", "color": role_color}),
                        html.Td(geom_str, style={"padding": "6px 12px", "color": "#aaa"}),
                        html.Td(html.Code(lid_str, style={"color": "#90caf9"}), style={"padding": "6px 12px"}),
                        html.Td(f"{z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Bar #{z.source_candle_index})", style={"padding": "6px 12px"}),
                        html.Td(conf_str, style={"padding": "6px 12px"}),
                        html.Td(
                            html.Span(
                                "STRUCTURAL SET ONLY — NOT ORDER EXECUTION",
                                style={"fontSize": "10px", "color": "#888", "fontStyle": "italic"},
                            ),
                            style={"padding": "6px 12px"},
                        ),
                    ],
                )
            )

        elements.append(
            html.Div(
                id="tjl-current-set-panel",
                style={"marginBottom": "16px"},
                children=[
                    html.H5(f"🎯 Current Eligible TJL Set: {curr_set.set_id}", style={"color": "#00e676", "margin": "12px 0 6px 0"}),
                    set_header_info,
                    html.Table(
                        id="tjl-current-set-table",
                        children=[
                            html.Thead(
                                html.Tr(
                                    style={"background": "#1e1e30", "color": "#a0a0b8", "fontSize": "12px", "textAlign": "left"},
                                    children=[
                                        html.Th("Role", style={"padding": "8px 12px"}),
                                        html.Th("Price Bounds", style={"padding": "8px 12px"}),
                                        html.Th("Geometry", style={"padding": "8px 12px"}),
                                        html.Th("Stable Level ID", style={"padding": "8px 12px"}),
                                        html.Th("Source Candle (UTC)", style={"padding": "8px 12px"}),
                                        html.Th("Confirmed At (UTC)", style={"padding": "8px 12px"}),
                                        html.Th("Boundary Scope", style={"padding": "8px 12px"}),
                                    ],
                                )
                            ),
                            html.Tbody(zone_rows),
                        ],
                        style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c"},
                    ),
                ],
            )
        )
    else:
        # Informational note when no current eligible set
        no_set_reason = (
            "Confirmed structural labels exist, but no active Point 3 has qualified an eligible set."
            if tjl_snap.all_labeled_zones
            else "Awaiting directional structure initialization or recovering from CHOCH reset."
        )
        elements.append(
            html.Div(
                id="tjl-no-current-set-panel",
                style={
                    "background": "#181824",
                    "border": "1px dashed #333348",
                    "borderRadius": "6px",
                    "padding": "10px 14px",
                    "marginBottom": "16px",
                    "color": "#aaa",
                    "fontSize": "12px",
                },
                children=[
                    html.B("Current Eligible Set: None. "),
                    html.Span(no_set_reason),
                ],
            )
        )

    # 3. All Labeled Zones Table
    if tjl_snap.all_labeled_zones:
        curr_lids = {curr_set.tjl1_zone.level_id, curr_set.tjl2_zone.level_id} if curr_set else set()
        hist_lids = {z.level_id for h in tjl_snap.historical_sets for z in [h.tjl1_zone, h.tjl2_zone]}

        labeled_rows = []
        for z in tjl_snap.all_labeled_zones:
            price_str = f"{z.lower_price:.4f} – {z.upper_price:.4f}" if not z.is_line else f"{z.lower_price:.4f}"
            geom_str = "Line (Thickness 0)" if z.is_line else "Box / Area"
            lid_str = f"({z.level_id.symbol_feed_id}, {z.level_id.source_timeframe}, {z.level_id.source_open_time.strftime('%H:%M')}, {z.level_id.side.value})"
            conf_str = (
                z.confirmed_time.strftime("%Y-%m-%d %H:%M UTC")
                if z.confirmed_time is not None
                else f"Unknown (Source Bar #{z.source_candle_index})"
            )

            if z.level_id in curr_lids:
                status_badge = html.Span("CURRENT SET", style={"padding": "2px 6px", "borderRadius": "3px", "background": "#1b5e20", "color": "#a5d6a7", "fontSize": "10px", "fontWeight": "bold"})
            elif z.level_id in hist_lids:
                status_badge = html.Span("HISTORICAL", style={"padding": "2px 6px", "borderRadius": "3px", "background": "#37474f", "color": "#cfd8dc", "fontSize": "10px", "fontWeight": "bold"})
            else:
                status_badge = html.Span("LABELED ONLY", style={"padding": "2px 6px", "borderRadius": "3px", "background": "#e65100", "color": "#ffe082", "fontSize": "10px", "fontWeight": "bold"})

            labeled_rows.append(
                html.Tr(
                    style={"borderBottom": "1px solid #232338", "fontSize": "12px", "color": "#e0e0e0"},
                    children=[
                        html.Td(z.label.value, style={"padding": "6px 12px", "fontWeight": "bold"}),
                        html.Td(price_str, style={"padding": "6px 12px"}),
                        html.Td(geom_str, style={"padding": "6px 12px", "color": "#aaa"}),
                        html.Td(html.Code(lid_str, style={"color": "#90caf9"}), style={"padding": "6px 12px"}),
                        html.Td(f"{z.source_candle_open_time.strftime('%Y-%m-%d %H:%M UTC')} (Bar #{z.source_candle_index})", style={"padding": "6px 12px"}),
                        html.Td(conf_str, style={"padding": "6px 12px"}),
                        html.Td(status_badge, style={"padding": "6px 12px"}),
                    ],
                )
            )

        elements.append(
            html.Div(
                id="tjl-all-labels-panel",
                style={"marginBottom": "16px"},
                children=[
                    html.H5("🏷️ All Labeled TJL Zones (Structural Provenance)", style={"color": "#b388ff", "margin": "12px 0 6px 0"}),
                    html.Table(
                        id="tjl-all-labels-table",
                        children=[
                            html.Thead(
                                html.Tr(
                                    style={"background": "#1e1e30", "color": "#a0a0b8", "fontSize": "12px", "textAlign": "left"},
                                    children=[
                                        html.Th("Role", style={"padding": "8px 12px"}),
                                        html.Th("Price Bounds", style={"padding": "8px 12px"}),
                                        html.Th("Geometry", style={"padding": "8px 12px"}),
                                        html.Th("Stable Level ID", style={"padding": "8px 12px"}),
                                        html.Th("Source Candle (UTC)", style={"padding": "8px 12px"}),
                                        html.Th("Confirmed At (UTC)", style={"padding": "8px 12px"}),
                                        html.Th("Set Membership", style={"padding": "8px 12px"}),
                                    ],
                                )
                            ),
                            html.Tbody(labeled_rows),
                        ],
                        style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c"},
                    ),
                ],
            )
        )

    # 4. Lifecycle Transition History Table
    if tjl_snap.transition_history:
        history_rows = []
        for idx, tr in enumerate(tjl_snap.transition_history, start=1):
            t_type = tr.transition_type.value if hasattr(tr.transition_type, "value") else str(tr.transition_type)
            set_id = tr.current_set.set_id if tr.current_set else "None"
            cancel_str = f"CANCEL {tr.outgoing_cancelled_set_id}" if tr.outgoing_cancellation_intent else "—"
            cancel_color = "#ff5252" if tr.outgoing_cancellation_intent else "#888"

            time_str = tr.transition_time.strftime("%Y-%m-%d %H:%M UTC") if tr.transition_time else "—"

            history_rows.append(
                html.Tr(
                    style={"borderBottom": "1px solid #232338", "fontSize": "12px", "color": "#e0e0e0"},
                    children=[
                        html.Td(f"#{idx}", style={"padding": "6px 12px", "color": "#aaa"}),
                        html.Td(
                            html.Span(
                                t_type,
                                style={
                                    "padding": "2px 6px",
                                    "borderRadius": "3px",
                                    "background": "#263238",
                                    "color": "#80d8ff",
                                    "fontSize": "10px",
                                    "fontWeight": "bold",
                                },
                            ),
                            style={"padding": "6px 12px"},
                        ),
                        html.Td(f"{time_str} (Bar #{tr.transition_candle_index})", style={"padding": "6px 12px"}),
                        html.Td(html.B(set_id, style={"color": "#00e676" if set_id != "None" else "#888"}), style={"padding": "6px 12px"}),
                        html.Td(html.Span(cancel_str, style={"color": cancel_color, "fontWeight": "bold" if tr.outgoing_cancellation_intent else "normal"}), style={"padding": "6px 12px"}),
                        html.Td(str(len(tr.newly_labeled_zones)), style={"padding": "6px 12px"}),
                        html.Td(tr.diagnostic or "—", style={"padding": "6px 12px", "color": "#bbb", "fontSize": "11px"}),
                    ],
                )
            )

        elements.append(
            html.Div(
                id="tjl-history-panel",
                style={"marginBottom": "16px"},
                children=[
                    html.H5("📜 TJL Lifecycle Transition History", style={"color": "#00e5ff", "margin": "12px 0 6px 0"}),
                    html.Table(
                        id="tjl-history-table",
                        children=[
                            html.Thead(
                                html.Tr(
                                    style={"background": "#1e1e30", "color": "#a0a0b8", "fontSize": "12px", "textAlign": "left"},
                                    children=[
                                        html.Th("#", style={"padding": "8px 12px"}),
                                        html.Th("Transition Type", style={"padding": "8px 12px"}),
                                        html.Th("Transition Candle", style={"padding": "8px 12px"}),
                                        html.Th("Resulting Set", style={"padding": "8px 12px"}),
                                        html.Th("Outgoing Cancellation", style={"padding": "8px 12px"}),
                                        html.Th("New Zones", style={"padding": "8px 12px"}),
                                        html.Th("Diagnostic", style={"padding": "8px 12px"}),
                                    ],
                                )
                            ),
                            html.Tbody(history_rows),
                        ],
                        style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c"},
                    ),
                ],
            )
        )

    # 5. TJL Scope Disclaimer Box
    elements.append(
        html.Div(
            "ℹ️ TJL Scope boundary: Structural Set Only — Downstream activation/ledger not present. "
            "Pure read-only market structure calculation. Zero order execution, zero MT5 trading calls, zero account modification.",
            id="tjl-scope-disclaimer",
            style={
                "fontSize": "11px",
                "color": "#888",
                "marginTop": "8px",
                "marginBottom": "16px",
                "border": "1px solid #232338",
                "padding": "6px 10px",
                "borderRadius": "4px",
                "background": "#12121c",
            },
        )
    )

    return elements
