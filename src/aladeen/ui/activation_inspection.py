"""Activation inspection panel element generation for Read-Only Dashboard.

Renders read-only inspection cards, tables, and provenance diagnostics:
- Mandatory non-execution disclaimer banner: "LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL"
- Unresolved ambiguity banner: "LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"
- Context header: Engine ID, symbol, sequence domain, source TF, mapped confirmation TF
- Coverage & observation gating summary (CoverageStatus enum, observation count diagnostic)
- Active Members & Activations table (INACTIVE_ELIGIBLE, PENDING_ACTIVATION, REARMED_PENDING, INACTIVE_INELIGIBLE)
- Rearm Controllers table (CANCELLED_EXTERNAL_ENTRY, OUT_OF_ZONE_ARMED, generation_seq = 2)
- Terminal Activation History table (bounded display with total count, multi-tier deterministic sort)
- Dedicated cancellation timestamp column ("Unknown") vs sequence column ("#<seq>")

Scope Boundary:
---------------
Pure presentation projection only. Strictly zero order execution, zero MT5 trading calls,
zero live account modification, zero confirmation arbitration, zero usage ledger writes,
and zero trade entry signals. Never invokes process_event(), register_source_members(),
reset(), or synchronizer.sync().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple
from dash import html

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CoverageStatus,
    RearmController,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
)
from aladeen.strategy.tjl_types import TJLSnapshot


# Friendly labels for raw domain blocked reasons
BLOCKED_REASON_LABELS = {
    "UNKNOWN_AVAILABILITY_TIMING": "Unknown Availability Timing",
    "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED": "Usage Evidence Uncertain (Fail-Closed)",
    "COVERAGE_INCOMPLETE": "Coverage Incomplete",
    "COVERAGE_UNCERTAIN": "Coverage Uncertain",
    "BLOCKED_UNKNOWN_ORDER": "Blocked Unknown Order",
}

CANONICAL_UNRESOLVED_BANNER = "LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"
DISCLAIMER_TEXT = "LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL"
DISCLAIMER_SUBTEXT = " — Pure read-only presentation. No order execution, trading, or arbitration active."
AWAITING_CONTEXT_TEXT = "Awaiting activation context"


def _format_datetime(dt: Optional[datetime]) -> str:
    """Formats datetime as ISO UTC string or returns 'Unknown'."""
    if dt is None:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_price(price: Optional[float]) -> str:
    """Precision-preserving float price string."""
    if price is None:
        return "—"
    return f"{price:.4f}"


def build_activation_inspection_elements(
    msm_result: Any = None,
    *,
    activation_snapshot: Optional[ActivationSnapshot] = None,
    tjl_snapshot: Optional[TJLSnapshot] = None,
    last_synced_transition_index: Optional[int] = None,
    exact_observation_count: Optional[int] = None,
) -> List[html.Div]:
    """Pure functional presentation projection building activation dashboard inspection components.

    Parameters
    ----------
    msm_result : Any, optional
        MSMServiceResult carrying optional activation_snapshot and tjl_snapshot.
    activation_snapshot : Optional[ActivationSnapshot], optional
        Direct immutable snapshot override for testing.
    tjl_snapshot : Optional[TJLSnapshot], optional
        Direct immutable TJL snapshot override for testing.
    last_synced_transition_index : Optional[int], optional
        Authoritative synchronizer cursor index.
    exact_observation_count : Optional[int], optional
        Authoritative observation count diagnostic.

    Returns
    -------
    List[html.Div]
        Dash HTML components rendering the activation inspection section.
    """
    # 1. Parameter extraction & fallback
    if activation_snapshot is None and msm_result is not None:
        activation_snapshot = getattr(msm_result, "activation_snapshot", None)
    if tjl_snapshot is None and msm_result is not None:
        tjl_snapshot = getattr(msm_result, "tjl_snapshot", None)
    if last_synced_transition_index is None and msm_result is not None:
        last_synced_transition_index = getattr(msm_result, "last_synced_transition_index", None)
    if exact_observation_count is None and msm_result is not None:
        exact_observation_count = getattr(msm_result, "exact_observation_count", None)

    # 2. Diagnostic fallback if context is missing
    if activation_snapshot is None:
        return [
            html.Div(
                [
                    html.P(
                        AWAITING_CONTEXT_TEXT,
                        id="activation-awaiting-context",
                        style={"color": "#9e9e9e", "fontStyle": "italic", "fontSize": "12px", "padding": "8px 0"},
                    )
                ],
                id="activation-inspection-container",
            )
        ]

    container_children: List[html.Div] = []

    # 3. Mandatory Non-Execution Disclaimer Banner
    disclaimer_banner = html.Div(
        [
            html.Span(
                f"⚠️ {DISCLAIMER_TEXT}",
                id="activation-disclaimer-badge",
                style={"color": "#ffd54f", "fontWeight": "bold", "fontSize": "12px", "letterSpacing": "0.5px"},
            ),
            html.Span(
                DISCLAIMER_SUBTEXT,
                style={"color": "#bbb", "fontSize": "11px", "marginLeft": "6px"},
            ),
        ],
        id="activation-disclaimer-banner",
        style={
            "background": "#2c2607",
            "border": "1px solid #ffb300",
            "borderRadius": "4px",
            "padding": "6px 12px",
            "marginBottom": "10px",
        },
    )
    container_children.append(disclaimer_banner)

    # 4. Canonical Unresolved Diagnostic Banner
    is_unresolved = False
    proc_bar_idx = -1
    recv_bar_idx = -1
    unres_diag = None

    if tjl_snapshot is not None:
        is_unresolved = tjl_snapshot.is_unresolved
        proc_bar_idx = tjl_snapshot.last_processed_index
        recv_bar_idx = tjl_snapshot.last_received_index
        unres_diag = tjl_snapshot.unresolved_diagnostic
    elif msm_result is not None:
        is_unresolved = getattr(msm_result, "is_unresolved", False)
        proc_bar_idx = getattr(msm_result, "last_processed_index", -1)
        recv_bar_idx = getattr(msm_result, "last_received_index", -1)
        unres_diag = getattr(msm_result, "unresolved_diagnostic", None)

    if is_unresolved:
        unresolved_banner = html.Div(
            [
                html.Div(
                    CANONICAL_UNRESOLVED_BANNER,
                    id="activation-unresolved-banner-text",
                    style={"fontWeight": "bold", "color": "#ff5252", "fontSize": "12px"},
                ),
                html.Div(
                    [
                        html.Span(
                            f"Processed Bar #{proc_bar_idx}",
                            id="activation-unresolved-processed-bar",
                            style={"color": "#fff", "marginRight": "12px"},
                        ),
                        html.Span(
                            f"Latest Received Bar #{recv_bar_idx}",
                            id="activation-unresolved-received-bar",
                            style={"color": "#ffa726", "marginRight": "12px"},
                        ),
                        html.Span(
                            f"Diagnostic: {unres_diag}" if unres_diag else "",
                            style={"color": "#bbb"},
                        ),
                    ],
                    style={"fontSize": "11px", "marginTop": "4px"},
                ),
            ],
            id="activation-unresolved-banner",
            style={
                "background": "#370b0b",
                "border": "1px solid #d32f2f",
                "borderRadius": "4px",
                "padding": "8px 12px",
                "marginBottom": "10px",
            },
        )
        container_children.append(unresolved_banner)

    # 5. G1 Context & G8 Synchronization Status Card
    mapped_conf_tf = activation_snapshot.confirmation_timeframe
    expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(activation_snapshot.source_timeframe, "—")

    cov_status = activation_snapshot.coverage_status
    if cov_status == CoverageStatus.COMPLETE:
        cov_bg, cov_fg = "#1b5e20", "#a5d6a7"
        cov_text = "COVERAGE COMPLETE"
    elif cov_status == CoverageStatus.INCOMPLETE:
        cov_bg, cov_fg = "#e65100", "#ffb74d"
        cov_text = "COVERAGE INCOMPLETE"
    else:
        cov_bg, cov_fg = "#b71c1c", "#ef9a9a"
        cov_text = "COVERAGE UNCERTAIN"

    cov_badge = html.Span(
        cov_text,
        id="activation-coverage-badge",
        style={
            "padding": "2px 8px",
            "borderRadius": "4px",
            "background": cov_bg,
            "color": cov_fg,
            "fontWeight": "bold",
            "fontSize": "11px",
            "marginLeft": "10px",
        },
    )

    ctx_items = [
        html.Span([html.B("Engine ID: "), html.Code(activation_snapshot.engine_id, style={"color": "#00e5ff"})], style={"fontSize": "12px", "color": "#ccc", "marginRight": "16px"}),
        html.Span([html.B("Symbol: "), html.Span(activation_snapshot.symbol, style={"color": "#90caf9"})], style={"fontSize": "12px", "color": "#ccc", "marginRight": "16px"}),
        html.Span([html.B("Source TF: "), html.Span(activation_snapshot.source_timeframe, id="activation-source-tf", style={"color": "#ff80ab", "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc", "marginRight": "16px"}),
        html.Span([html.B("Mapped Confirmation TF: "), html.Span(mapped_conf_tf, id="activation-confirmation-tf", style={"color": "#b388ff", "fontWeight": "bold"})], style={"fontSize": "12px", "color": "#ccc", "marginRight": "16px"}),
        html.Span([html.B("Sequence Feed: "), html.Code(activation_snapshot.sequence_domain.feed_id, style={"color": "#80cbc4"})], style={"fontSize": "12px", "color": "#ccc", "marginRight": "16px"}),
        html.Span([html.B("Run ID: "), html.Code(activation_snapshot.sequence_domain.run_id, style={"color": "#ce93d8"})], style={"fontSize": "12px", "color": "#ccc"}),
        cov_badge,
    ]

    sync_details = []
    if exact_observation_count is not None:
        sync_details.append(html.Span(f"Exact Observations Processed: {exact_observation_count}", id="activation-obs-count-diag", style={"color": "#00e676", "fontWeight": "bold", "marginRight": "16px"}))
    if activation_snapshot.last_processed_sequence is not None:
        sync_details.append(html.Span(f"Engine Last Seq: #{activation_snapshot.last_processed_sequence}", style={"color": "#aaa", "marginRight": "16px"}))
    if activation_snapshot.last_processed_timestamp is not None:
        sync_details.append(html.Span(f"Engine Last Time: {_format_datetime(activation_snapshot.last_processed_timestamp)}", style={"color": "#aaa", "marginRight": "16px"}))
    if last_synced_transition_index is not None:
        sync_details.append(html.Span(f"Synced Transition Index: #{last_synced_transition_index}", style={"color": "#aaa"}))

    context_card = html.Div(
        [
            html.Div(ctx_items, style={"display": "flex", "flexWrap": "wrap", "alignItems": "center"}),
            html.Div(
                [
                    html.P(
                        "Confirmation TF is metadata mapping only; no confirmation arbitration active.",
                        id="activation-arbitration-disclaimer",
                        style={"fontSize": "11px", "color": "#888", "margin": "4px 0 0 0"},
                    ),
                    html.Div(sync_details, style={"fontSize": "11px", "marginTop": "4px", "display": "flex", "flexWrap": "wrap"}) if sync_details else html.Div(),
                ]
            ),
        ],
        id="activation-context-card",
        style={
            "background": "#1a1a2e",
            "border": "1px solid #282846",
            "borderRadius": "4px",
            "padding": "10px 14px",
            "marginBottom": "12px",
        },
    )
    container_children.append(context_card)

    # 6. G2 Membership & G3 Active Activations Table
    active_rows = []
    # Collect all member keys from current_members and active_activations
    all_keys = set(activation_snapshot.current_members.keys()) | set(activation_snapshot.active_activations.keys())

    def _key_sort_tuple(mk: str) -> Tuple[str, str]:
        if mk in activation_snapshot.current_members:
            m = activation_snapshot.current_members[mk]
            return (m.set_id, m.role)
        rec = activation_snapshot.active_activations[mk]
        return (rec.set_id, rec.role)

    sorted_keys = sorted(all_keys, key=_key_sort_tuple)

    for mk in sorted_keys:
        member: Optional[SourceMemberReference] = activation_snapshot.current_members.get(mk)
        rec: Optional[ActivationRecord] = activation_snapshot.active_activations.get(mk)

        set_id = member.set_id if member else (rec.set_id if rec else "None")
        role = member.role if member else (rec.role if rec else "None")
        state_str = rec.state.value if rec is not None else "UNREGISTERED"
        gen_seq = rec.generation_seq if rec is not None else 0
        first_touch_time_str = _format_datetime(rec.first_touch_time) if rec and rec.first_touch_time else "—"
        first_touch_price_str = _format_price(rec.first_touch_price) if rec and rec.first_touch_price else "—"
        obs_id_str = rec.trigger_observation_id if rec and rec.trigger_observation_id else "—"
        prior_act_id_str = rec.prior_activation_id if rec and rec.prior_activation_id else "—"
        usage_str = rec.usage_evidence_status.value if rec else (member.usage_evidence_status.value if member else "UNKNOWN")
        raw_blocked = rec.blocked_reason if rec and rec.blocked_reason else None
        friendly_blocked = BLOCKED_REASON_LABELS.get(raw_blocked, raw_blocked) if raw_blocked else "—"

        if raw_blocked:
            blocked_cell_children = [
                html.Span(friendly_blocked, style={"fontWeight": "bold"}),
                html.Span(f" [{raw_blocked}]", style={"fontSize": "9px", "color": "#888", "marginLeft": "4px"}),
            ]
        else:
            blocked_cell_children = [html.Span("—")]

        # Badge styling based on state and gating
        if rec is not None:
            if rec.state == ActivationState.PENDING_ACTIVATION:
                if rec.usage_evidence_status == UsageEvidenceStatus.UNKNOWN or raw_blocked == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED":
                    badge_bg, badge_fg = "#b71c1c", "#ef9a9a"
                    badge_text = "UNKNOWN (FAIL-CLOSED)"
                else:
                    badge_bg, badge_fg = "#004d40", "#80cbc4"
                    badge_text = "PENDING ACTIVATION"
            elif rec.state == ActivationState.REARMED_PENDING:
                badge_bg, badge_fg = "#1a237e", "#9fa8da"
                badge_text = f"REARMED PENDING (GEN {rec.generation_seq})"
            elif rec.state == ActivationState.INACTIVE_ELIGIBLE:
                badge_bg, badge_fg = "#1b5e20", "#a5d6a7"
                badge_text = "ELIGIBLE (UNTOUCHED)"
            elif rec.state == ActivationState.INACTIVE_INELIGIBLE:
                if raw_blocked == "UNKNOWN_AVAILABILITY_TIMING":
                    badge_bg, badge_fg = "#424242", "#bdbdbd"
                    badge_text = "INELIGIBLE (UNKNOWN AVAILABILITY)"
                elif raw_blocked == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED":
                    badge_bg, badge_fg = "#b71c1c", "#ef9a9a"
                    badge_text = "INELIGIBLE (UNKNOWN USAGE)"
                else:
                    badge_bg, badge_fg = "#424242", "#bdbdbd"
                    badge_text = "INACTIVE_INELIGIBLE"
            else:
                badge_bg, badge_fg = "#212121", "#9e9e9e"
                badge_text = state_str
        else:
            badge_bg, badge_fg = "#212121", "#9e9e9e"
            badge_text = "UNREGISTERED"

        status_badge = html.Span(
            badge_text,
            style={
                "padding": "2px 6px",
                "borderRadius": "3px",
                "background": badge_bg,
                "color": badge_fg,
                "fontWeight": "bold",
                "fontSize": "10px",
            },
        )

        if member is not None:
            bounds_str = f"[{member.lower_edge:.4f}, {member.upper_edge:.4f}]" + (" (Line)" if member.is_line else "")
            avail_str = _format_datetime(member.eligibility_available_time)
        elif rec is not None:
            bounds_str = f"[{rec.lower_edge:.4f}, {rec.upper_edge:.4f}]"
            avail_str = "—"
        else:
            bounds_str = "—"
            avail_str = "—"

        active_rows.append(
            html.Tr(
                [
                    html.Td(set_id, style={"fontWeight": "bold", "color": "#00e676"}),
                    html.Td(role, style={"color": "#90caf9"}),
                    html.Td(html.Code(mk, style={"fontSize": "10px", "color": "#b388ff"})),
                    html.Td(bounds_str, style={"color": "#ddd", "fontFamily": "monospace"}),
                    html.Td(avail_str, style={"color": "#aaa", "fontSize": "11px"}),
                    html.Td(status_badge),
                    html.Td(str(gen_seq), style={"textAlign": "center", "color": "#ff80ab"}),
                    html.Td(first_touch_time_str, style={"color": "#aaa", "fontSize": "11px"}),
                    html.Td(first_touch_price_str, style={"fontFamily": "monospace", "color": "#ffb74d"}),
                    html.Td(obs_id_str, style={"fontFamily": "monospace", "color": "#80cbc4"}),
                    html.Td(prior_act_id_str, style={"fontSize": "10px", "color": "#aaa"}),
                    html.Td(usage_str, style={"fontSize": "11px", "color": "#a5d6a7" if usage_str == "UNUSED" else "#ef9a9a"}),
                    html.Td(blocked_cell_children, style={"fontSize": "10px", "color": "#ffa726" if raw_blocked else "#666"}),
                ],
                style={"borderBottom": "1px solid #1a1a2e"},
            )
        )

    active_table_header = html.Thead(
        html.Tr(
            [
                html.Th("Set ID"),
                html.Th("Role"),
                html.Th("Member Key"),
                html.Th("Price Bounds"),
                html.Th("Available Time"),
                html.Th("Lifecycle State"),
                html.Th("Gen"),
                html.Th("First Touch Time"),
                html.Th("First Touch Price"),
                html.Th("Trigger Obs"),
                html.Th("Prior Act ID"),
                html.Th("Usage Evidence"),
                html.Th("Blocked Reason"),
            ],
            style={"background": "#0d0d1a", "color": "#00e5ff", "fontSize": "11px", "textAlign": "left"},
        )
    )

    active_section = html.Div(
        [
            html.H5(
                f"🎯 Active Eligible Members & Activations ({len(active_rows)} current members)",
                style={"color": "#00e5ff", "margin": "12px 0 6px 0", "fontSize": "13px"},
            ),
            html.Table(
                [active_table_header, html.Tbody(active_rows)],
                id="activation-active-table",
                style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c", "fontSize": "11px"},
            ) if active_rows else html.P("No active members registered in current snapshot.", style={"color": "#888", "fontSize": "11px", "fontStyle": "italic"}),
        ],
        style={"marginBottom": "16px"},
    )
    container_children.append(active_section)

    # 7. G6 Rearm Controllers Table
    rearm_controllers = activation_snapshot.rearm_controllers
    if rearm_controllers:
        sorted_ctrls = sorted(rearm_controllers.values(), key=lambda c: (c.member_key, c.prior_activation_id))
        ctrl_rows = []
        for ctrl in sorted_ctrls:
            if ctrl.rearm_armed:
                badge_bg, badge_fg = "#1565c0", "#90caf9"
                badge_text = "ARMED FOR RETOUCH"
                status_display = "Armed (Outside Zone)"
            else:
                badge_bg, badge_fg = "#4e342e", "#d7ccc8"
                badge_text = "CANCELLED (AWAITING DEPARTURE)"
                status_display = "Awaiting Departure Outside Zone"

            ctrl_status_badge = html.Span(
                badge_text,
                style={"padding": "2px 6px", "borderRadius": "3px", "background": badge_bg, "color": badge_fg, "fontWeight": "bold", "fontSize": "10px"},
            )

            ctrl_rows.append(
                html.Tr(
                    [
                        html.Td(html.Code(ctrl.member_key, style={"color": "#b388ff", "fontSize": "10px"})),
                        html.Td(ctrl.prior_activation_id, style={"fontSize": "10px", "color": "#aaa"}),
                        html.Td(f"Gen {ctrl.generation_seq}", style={"color": "#ff80ab", "textAlign": "center"}),
                        html.Td(ctrl_status_badge),
                        html.Td(status_display, style={"color": "#90caf9", "fontSize": "11px"}),
                        html.Td("YES" if ctrl.rearm_armed else "NO", style={"fontWeight": "bold", "color": "#00e676" if ctrl.rearm_armed else "#ff5252"}),
                        html.Td(ctrl.last_observed_position or "Unknown", style={"color": "#ffb74d", "fontSize": "11px"}),
                        html.Td(_format_datetime(ctrl.cancellation_time), style={"color": "#aaa", "fontSize": "11px"}),
                        html.Td(f"#{ctrl.cancellation_sequence_ref}" if ctrl.cancellation_sequence_ref is not None else "—", style={"fontFamily": "monospace", "color": "#80cbc4"}),
                    ],
                    style={"borderBottom": "1px solid #1a1a2e"},
                )
            )

        ctrl_table_header = html.Thead(
            html.Tr(
                [
                    html.Th("Member Key"),
                    html.Th("Prior Activation ID"),
                    html.Th("Next Gen"),
                    html.Th("Controller Badge"),
                    html.Th("Rearm Status"),
                    html.Th("Armed"),
                    html.Th("Last Observed Pos"),
                    html.Th("Cancellation Time"),
                    html.Th("Seq Ref"),
                ],
                style={"background": "#0d0d1a", "color": "#00e5ff", "fontSize": "11px", "textAlign": "left"},
            )
        )

        ctrl_section = html.Div(
            [
                html.H5(
                    f"🔄 Rearm Controllers ({len(rearm_controllers)} active controllers)",
                    style={"color": "#00e5ff", "margin": "12px 0 6px 0", "fontSize": "13px"},
                ),
                html.Table(
                    [ctrl_table_header, html.Tbody(ctrl_rows)],
                    id="activation-rearm-table",
                    style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c", "fontSize": "11px"},
                ),
            ],
            style={"marginBottom": "16px"},
        )
        container_children.append(ctrl_section)

    # 8. G7 Terminal Activation History Table (Bounded DOM Display with Deterministic Sort)
    term_activations = activation_snapshot.terminal_activations
    total_term_count = len(term_activations)
    if total_term_count > 0:
        # Multi-tier deterministic sort:
        min_date = datetime.min.replace(tzinfo=timezone.utc)
        sorted_terminal = sorted(
            term_activations,
            key=lambda rec: (
                rec.cancellation_sequence_ref is not None,
                rec.cancellation_sequence_ref or 0,
                rec.cancellation_time is not None,
                rec.cancellation_time or min_date,
                rec.activation_id,
            ),
            reverse=True,
        )

        # Bounded DOM display: top 50 records to preserve client-side performance
        display_terminal = sorted_terminal[:50]
        term_rows = []

        for rec in display_terminal:
            reason_str = rec.cancellation_reason.value if rec.cancellation_reason is not None else "—"
            cancellation_time_str = _format_datetime(rec.cancellation_time)
            cancellation_seq_str = f"#{rec.cancellation_sequence_ref}" if rec.cancellation_sequence_ref is not None else "—"
            touch_time_str = _format_datetime(rec.first_touch_time) if rec.first_touch_time else "—"

            term_rows.append(
                html.Tr(
                    [
                        html.Td(html.Code(rec.activation_id, style={"fontSize": "10px", "color": "#00e5ff"})),
                        html.Td(html.Code(rec.member_key, style={"fontSize": "10px", "color": "#b388ff"})),
                        html.Td(rec.state.value, style={"color": "#ef5350", "fontWeight": "bold"}),
                        html.Td(str(rec.generation_seq), style={"textAlign": "center", "color": "#ff80ab"}),
                        html.Td(touch_time_str, style={"color": "#aaa", "fontSize": "11px"}),
                        html.Td(reason_str, style={"color": "#ffa726", "fontSize": "11px"}),
                        html.Td(cancellation_time_str, style={"color": "#aaa", "fontSize": "11px"}),
                        html.Td(cancellation_seq_str, style={"fontFamily": "monospace", "color": "#80cbc4"}),
                    ],
                    style={"borderBottom": "1px solid #1a1a2e"},
                )
            )

        term_table_header = html.Thead(
            html.Tr(
                [
                    html.Th("Activation ID"),
                    html.Th("Member Key"),
                    html.Th("Terminal State"),
                    html.Th("Gen"),
                    html.Th("First Touch Time"),
                    html.Th("Cancellation Reason"),
                    html.Th("Cancellation Time"),
                    html.Th("Seq Ref"),
                ],
                style={"background": "#0d0d1a", "color": "#00e5ff", "fontSize": "11px", "textAlign": "left"},
            )
        )

        display_note = f" (Showing latest {len(display_terminal)} of {total_term_count} records)" if total_term_count > 50 else ""
        term_section = html.Div(
            [
                html.H5(
                    f"📜 Terminal Activation History ({total_term_count} total records){display_note}",
                    id="activation-history-heading",
                    style={"color": "#00e5ff", "margin": "12px 0 6px 0", "fontSize": "13px"},
                ),
                html.Table(
                    [term_table_header, html.Tbody(term_rows)],
                    id="activation-history-table",
                    style={"width": "100%", "borderCollapse": "collapse", "background": "#12121c", "fontSize": "11px"},
                ),
            ],
            style={"marginBottom": "16px"},
        )
        container_children.append(term_section)

    return [
        html.Div(
            container_children,
            id="activation-inspection-container",
            style={"background": "#0a0a14", "padding": "12px", "borderRadius": "6px", "border": "1px solid #1a1a2e", "marginTop": "14px"},
        )
    ]
