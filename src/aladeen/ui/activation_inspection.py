"""Activation inspection panel element generation for Read-Only Dashboard.

Renders read-only inspection cards, tables, and provenance diagnostics:
- Mandatory non-execution disclaimer banner: "LIFECYCLE OBSERVATION ONLY — NOT AN ENTRY SIGNAL"
- Unresolved ambiguity banner: "LAST AUTHORITATIVE EVIDENCE — SOURCE UNRESOLVED"
- Context header: Engine ID, symbol, sequence domain, source TF, mapped confirmation TF
- Coverage & observation gating summary (CoverageStatus enum, observation count diagnostic)
- Registered Members & Lifecycle Activations table:
  * Orthogonal Lifecycle State (PENDING_ACTIVATION, REARMED_PENDING, INACTIVE_ELIGIBLE, REGISTERED (CONTROLLER-MANAGED))
  * Explicit Evidence Gating & Eligibility (independent of lifecycle state)
  * Identity fields: Activation ID, Physical Level ID, Physical Side, Set ID, Role, Member Key
- Rearm Controllers table (CANCELLED_EXTERNAL_ENTRY, OUT_OF_ZONE_ARMED, generation_seq = 2)
- Terminal Activation History table:
  * Identity fields: Activation ID, Set ID, Role, Physical Level ID, Member Key
  * Bounded display of up to 50 records with total count indicator
  * Multi-tier deterministic sort (cancellation seq desc, cancellation time desc, activation ID asc)
  * Value-preserving price strings and UTC timestamps with subsecond precision and diagnostics

Scope Boundary:
---------------
Pure presentation projection only. Strictly zero order execution, zero MT5 trading calls,
zero live account modification, zero confirmation arbitration, zero usage ledger writes,
and zero trade entry signals. Never invokes process_event(), register_source_members(),
reset(), or synchronizer.sync().
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
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


def _format_datetime(dt: Optional[Any]) -> str:
    """Preserves supplied precision, converts valid aware values to UTC, and emits clear diagnostics.

    Rules:
    - None -> 'Unknown'
    - Not datetime -> f'[INVALID_TIMESTAMP:{dt!r}]'
    - Naive datetime (tzinfo is None) -> f'[NAIVE_TIMESTAMP:{dt.isoformat()}]' (no fabricated UTC)
    - Aware datetime -> converted to UTC via astimezone(timezone.utc); retains microseconds if non-zero.
    """
    if dt is None:
        return "Unknown"
    if not isinstance(dt, datetime):
        return f"[INVALID_TIMESTAMP:{dt!r}]"
    if dt.tzinfo is None:
        return f"[NAIVE_TIMESTAMP:{dt.isoformat()}]"

    dt_utc = dt.astimezone(timezone.utc)
    if dt_utc.microsecond > 0:
        return dt_utc.strftime("%Y-%m-%d %H:%M:%S.%f UTC")
    return dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_price(price: Optional[Any]) -> str:
    """Value-preserving price formatter without lossy 4-decimal rounding or float truncation."""
    if price is None:
        return "—"
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return f"[INVALID_PRICE:{price!r}]"
    if not math.isfinite(price):
        return str(price)

    # Format with up to 8 decimal places, preserving precision while padding to at least 4 decimals
    s = f"{price:.8f}".rstrip("0")
    if s.endswith("."):
        s += "0000"
    else:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) < 4:
            s = f"{parts[0]}.{parts[1].ljust(4, '0')}"
    return s


def _parse_member_key(member_key: str) -> Tuple[str, str]:
    """Safely extracts set_id and role from canonical length-prefixed MK[<len>:<set_id>][<len>:<role>]."""
    if not member_key.startswith("MK["):
        return (member_key, "—")
    try:
        content = member_key[2:]
        parts = []
        idx = 0
        while idx < len(content):
            if content[idx] != "[":
                break
            colon = content.find(":", idx)
            if colon == -1:
                break
            length = int(content[idx + 1:colon])
            val_start = colon + 1
            val_end = val_start + length
            val = content[val_start:val_end]
            parts.append(val)
            idx = val_end + 1
        if len(parts) >= 2:
            return parts[0], parts[1]
    except Exception:
        pass
    return (member_key, "—")


def _format_level_id(level_id: Any) -> str:
    """Formats physical level identifier cleanly or returns dash."""
    if level_id is None:
        return "—"
    if hasattr(level_id, "normalized_id"):
        return str(level_id.normalized_id)
    return str(level_id)


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

    # 2. Diagnostic fallback if context is missing or invalid
    if activation_snapshot is None or not isinstance(activation_snapshot, ActivationSnapshot):
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
    unresolved_diagnostic_text = None
    last_processed_idx = -1
    last_received_idx = -1

    if tjl_snapshot is not None and getattr(tjl_snapshot, "is_unresolved", False):
        is_unresolved = True
        unresolved_diagnostic_text = getattr(tjl_snapshot, "unresolved_diagnostic", "Source structure ambiguous")
        last_processed_idx = getattr(tjl_snapshot, "last_processed_index", -1)
        last_received_idx = getattr(tjl_snapshot, "last_received_index", -1)
    elif msm_result is not None and getattr(msm_result, "is_unresolved", False):
        is_unresolved = True
        diag = getattr(msm_result, "unresolved_diagnostic", None)
        unresolved_diagnostic_text = str(diag) if diag else "Source structure ambiguous"
        last_processed_idx = getattr(msm_result, "last_processed_index", -1)
        last_received_idx = getattr(msm_result, "last_received_index", -1)

    if is_unresolved:
        unresolved_banner = html.Div(
            [
                html.Div(
                    [
                        html.Span(
                            f"🛑 {CANONICAL_UNRESOLVED_BANNER}",
                            id="activation-unresolved-banner",
                            style={"color": "#ef5350", "fontWeight": "bold", "fontSize": "12px"},
                        ),
                        html.Span(
                            f" — Authoritative state frozen at Bar #{last_processed_idx} (received through Bar #{last_received_idx}). Diagnostic: {unresolved_diagnostic_text}",
                            style={"color": "#ffcdd2", "fontSize": "11px", "marginLeft": "6px"},
                        ),
                    ]
                )
            ],
            id="activation-unresolved-container",
            style={
                "background": "#370c0c",
                "border": "1px solid #d32f2f",
                "borderRadius": "4px",
                "padding": "8px 12px",
                "marginBottom": "10px",
            },
        )
        container_children.append(unresolved_banner)

    # 5. Context, Sequence Domain, and Observation Gating Summary Card
    conf_tf = activation_snapshot.confirmation_timeframe
    expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(activation_snapshot.source_timeframe, "M1")
    coverage_status = activation_snapshot.coverage_status

    coverage_colors = {
        CoverageStatus.COMPLETE: ("#1b5e20", "#a5d6a7"),
        CoverageStatus.INCOMPLETE: ("#e65100", "#ffcc80"),
        CoverageStatus.UNCERTAIN: ("#b71c1c", "#ef9a9a"),
    }
    cov_bg, cov_fg = coverage_colors.get(coverage_status, ("#424242", "#bdbdbd"))

    seq_dom_str = f"{activation_snapshot.sequence_domain.feed_id}:{activation_snapshot.sequence_domain.run_id}"

    # Observation count indicator
    obs_count_display = []
    if exact_observation_count is not None:
        obs_count_display.append(
            html.Span(
                f"Exact Observations Processed: {exact_observation_count}",
                id="activation-observation-count",
                style={"color": "#00e5ff", "marginRight": "12px", "fontFamily": "monospace"},
            )
        )

    # Sync cursor display
    sync_details = []
    if last_synced_transition_index is not None:
        sync_details.append(
            html.Span(
                f"TJL Synced Transition Index: #{last_synced_transition_index}",
                id="activation-sync-cursor",
                style={"color": "#80cbc4", "marginRight": "12px", "fontFamily": "monospace"},
            )
        )
    if activation_snapshot.last_processed_sequence is not None:
        sync_details.append(
            html.Span(
                f"Engine Last Processed Seq: #{activation_snapshot.last_processed_sequence}",
                id="activation-engine-seq",
                style={"color": "#ce93d8", "marginRight": "12px", "fontFamily": "monospace"},
            )
        )
    if activation_snapshot.last_processed_timestamp is not None:
        sync_details.append(
            html.Span(
                f"Last Processed Time: {_format_datetime(activation_snapshot.last_processed_timestamp)}",
                id="activation-last-time",
                style={"color": "#aaa", "marginRight": "12px"},
            )
        )

    context_card = html.Div(
        [
            html.Div(
                [
                    html.Span(f"Engine: {activation_snapshot.engine_id}", style={"fontWeight": "bold", "color": "#00e5ff", "marginRight": "16px"}),
                    html.Span(f"Symbol: {activation_snapshot.symbol}", style={"color": "#fff", "marginRight": "16px"}),
                    html.Span(f"Source TF: {activation_snapshot.source_timeframe}", style={"color": "#fff", "marginRight": "16px"}),
                    html.Span(
                        [
                            html.Span("Mapped Confirmation TF: ", style={"color": "#aaa"}),
                            html.Span(conf_tf, id="activation-confirmation-tf", style={"fontWeight": "bold", "color": "#ffb74d"}),
                            html.Span(f" (Rule: {expected_conf_tf})", style={"fontSize": "10px", "color": "#888", "marginLeft": "4px"}),
                        ],
                        style={"marginRight": "16px"},
                    ),
                    html.Span(
                        [
                            html.Span("Sequence Domain: ", style={"color": "#aaa"}),
                            html.Code(seq_dom_str, id="activation-sequence-domain", style={"color": "#b388ff", "fontSize": "11px"}),
                        ],
                        style={"marginRight": "16px"},
                    ),
                    html.Span(
                        coverage_status.value,
                        id="activation-coverage-badge",
                        style={
                            "background": cov_bg,
                            "color": cov_fg,
                            "padding": "2px 8px",
                            "borderRadius": "3px",
                            "fontWeight": "bold",
                            "fontSize": "10px",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "6px"},
            ),
            html.Div(
                [
                    html.Div(obs_count_display, style={"fontSize": "11px", "marginTop": "6px", "display": "flex", "flexWrap": "wrap"}) if obs_count_display else html.Div(),
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

    # 6. Registered Members & Lifecycle Activations Table
    active_rows = []
    # Collect all member keys from current_members, active_activations, and rearm_controllers
    all_keys = set(activation_snapshot.current_members.keys()) | set(activation_snapshot.active_activations.keys()) | set(activation_snapshot.rearm_controllers.keys())

    def _key_sort_tuple(mk: str) -> Tuple[str, str]:
        if mk in activation_snapshot.current_members:
            m = activation_snapshot.current_members[mk]
            return (m.set_id, m.role)
        if mk in activation_snapshot.active_activations:
            rec = activation_snapshot.active_activations[mk]
            return (rec.set_id, rec.role)
        return _parse_member_key(mk)

    sorted_keys = sorted(all_keys, key=_key_sort_tuple)

    for mk in sorted_keys:
        member: Optional[SourceMemberReference] = activation_snapshot.current_members.get(mk)
        rec: Optional[ActivationRecord] = activation_snapshot.active_activations.get(mk)
        ctrl: Optional[RearmController] = activation_snapshot.rearm_controllers.get(mk)

        if member is not None:
            set_id, role = member.set_id, member.role
        elif rec is not None:
            set_id, role = rec.set_id, rec.role
        else:
            set_id, role = _parse_member_key(mk)
        level_id_obj = (rec.level_id if rec and rec.level_id else None) or (member.level_id if member and member.level_id else None)
        level_id_str = _format_level_id(level_id_obj)
        side_str = member.side if member else (getattr(level_id_obj, "side", None) or "—")
        if hasattr(side_str, "value"):
            side_str = str(side_str.value)

        act_id_str = rec.activation_id if rec is not None else ("None (Controller-Managed)" if ctrl is not None else "None (Registered)")
        gen_seq = rec.generation_seq if rec is not None else (ctrl.generation_seq if ctrl is not None else 0)
        first_touch_time_str = _format_datetime(rec.first_touch_time) if rec and rec.first_touch_time else "—"
        first_touch_price_str = _format_price(rec.first_touch_price) if rec and rec.first_touch_price is not None else "—"
        obs_id_str = rec.trigger_observation_id if rec and rec.trigger_observation_id else "—"
        prior_act_id_str = rec.prior_activation_id if rec and rec.prior_activation_id else (ctrl.prior_activation_id if ctrl and ctrl.prior_activation_id else "—")
        usage_str = rec.usage_evidence_status.value if rec else (member.usage_evidence_status.value if member else "UNKNOWN")
        raw_blocked = rec.blocked_reason if rec and rec.blocked_reason else None

        # --- A. Orthogonal Lifecycle State Badge ---
        if rec is not None:
            if rec.state == ActivationState.PENDING_ACTIVATION:
                lifecycle_bg, lifecycle_fg = "#004d40", "#80cbc4"
                lifecycle_text = "PENDING ACTIVATION"
            elif rec.state == ActivationState.REARMED_PENDING:
                lifecycle_bg, lifecycle_fg = "#1a237e", "#9fa8da"
                lifecycle_text = f"REARMED PENDING (GEN {rec.generation_seq})"
            elif rec.state == ActivationState.INACTIVE_ELIGIBLE:
                lifecycle_bg, lifecycle_fg = "#1b5e20", "#a5d6a7"
                lifecycle_text = "ELIGIBLE (UNTOUCHED)"
            elif rec.state == ActivationState.INACTIVE_INELIGIBLE:
                lifecycle_bg, lifecycle_fg = "#424242", "#bdbdbd"
                lifecycle_text = "INACTIVE_INELIGIBLE"
            else:
                lifecycle_bg, lifecycle_fg = "#212121", "#9e9e9e"
                lifecycle_text = rec.state.value
        elif ctrl is not None:
            if ctrl.rearm_armed:
                lifecycle_bg, lifecycle_fg = "#1565c0", "#90caf9"
                lifecycle_text = "CONTROLLER-MANAGED (ARMED)"
            else:
                lifecycle_bg, lifecycle_fg = "#4e342e", "#d7ccc8"
                lifecycle_text = "CONTROLLER-MANAGED (AWAITING DEPARTURE)"
        elif member is not None:
            lifecycle_bg, lifecycle_fg = "#2e3b4e", "#b0bec5"
            lifecycle_text = "REGISTERED (UNACTIVATED)"
        else:
            lifecycle_bg, lifecycle_fg = "#212121", "#9e9e9e"
            lifecycle_text = "UNREGISTERED"

        lifecycle_badge = html.Span(
            lifecycle_text,
            style={
                "padding": "2px 6px",
                "borderRadius": "3px",
                "background": lifecycle_bg,
                "color": lifecycle_fg,
                "fontWeight": "bold",
                "fontSize": "10px",
            },
        )

        # --- B. Orthogonal Evidence Gating & Eligibility Badge ---
        # Coverage check
        if coverage_status == CoverageStatus.INCOMPLETE:
            gating_bg, gating_fg = "#e65100", "#ffcc80"
            gating_text = "COVERAGE INCOMPLETE [COVERAGE_INCOMPLETE]"
        elif coverage_status == CoverageStatus.UNCERTAIN:
            gating_bg, gating_fg = "#b71c1c", "#ef9a9a"
            gating_text = "COVERAGE UNCERTAIN [COVERAGE_UNCERTAIN]"
        # Usage check
        elif usage_str == "UNKNOWN" or raw_blocked == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED":
            gating_bg, gating_fg = "#b71c1c", "#ef9a9a"
            gating_text = "USAGE UNCERTAIN (FAIL-CLOSED) [USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED]"
        elif usage_str == "USED":
            gating_bg, gating_fg = "#d32f2f", "#ffcdd2"
            gating_text = "USAGE BLOCKED (USED) [USAGE_ALREADY_USED]"
        elif raw_blocked == "UNKNOWN_AVAILABILITY_TIMING":
            gating_bg, gating_fg = "#616161", "#e0e0e0"
            gating_text = "UNKNOWN AVAILABILITY [UNKNOWN_AVAILABILITY_TIMING]"
        elif raw_blocked:
            gating_bg, gating_fg = "#ff6f00", "#ffe082"
            friendly = BLOCKED_REASON_LABELS.get(raw_blocked, raw_blocked)
            gating_text = f"{friendly} [{raw_blocked}]"
        else:
            gating_bg, gating_fg = "#1b5e20", "#a5d6a7"
            gating_text = "EVIDENCE VALID (READY)"

        gating_badge = html.Span(
            gating_text,
            style={
                "padding": "2px 6px",
                "borderRadius": "3px",
                "background": gating_bg,
                "color": gating_fg,
                "fontWeight": "bold",
                "fontSize": "10px",
            },
        )

        # Price bounds display
        if member is not None:
            bounds_str = f"[{_format_price(member.lower_edge)}, {_format_price(member.upper_edge)}]" + (" (Line)" if member.is_line else "")
            avail_str = _format_datetime(member.eligibility_available_time)
        elif rec is not None:
            bounds_str = f"[{_format_price(rec.lower_edge)}, {_format_price(rec.upper_edge)}]"
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
                    html.Td(html.Code(act_id_str, style={"fontSize": "10px", "color": "#00e5ff"})),
                    html.Td(html.Code(level_id_str, style={"fontSize": "10px", "color": "#ffd54f"})),
                    html.Td(side_str, style={"color": "#80cbc4", "fontSize": "11px"}),
                    html.Td(bounds_str, style={"color": "#ddd", "fontFamily": "monospace"}),
                    html.Td(avail_str, style={"color": "#aaa", "fontSize": "11px"}),
                    html.Td(lifecycle_badge),
                    html.Td(gating_badge),
                    html.Td(str(gen_seq), style={"textAlign": "center", "color": "#ff80ab"}),
                    html.Td(first_touch_time_str, style={"color": "#aaa", "fontSize": "11px"}),
                    html.Td(first_touch_price_str, style={"fontFamily": "monospace", "color": "#ffb74d"}),
                    html.Td(obs_id_str, style={"fontFamily": "monospace", "color": "#80cbc4"}),
                    html.Td(prior_act_id_str, style={"fontSize": "10px", "color": "#aaa"}),
                    html.Td(usage_str, style={"fontSize": "11px", "color": "#a5d6a7" if usage_str == "UNUSED" else "#ef9a9a"}),
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
                html.Th("Activation ID"),
                html.Th("Level ID"),
                html.Th("Side"),
                html.Th("Price Bounds"),
                html.Th("Available Time"),
                html.Th("Lifecycle State"),
                html.Th("Evidence Gating"),
                html.Th("Gen"),
                html.Th("First Touch Time"),
                html.Th("First Touch Price"),
                html.Th("Trigger Obs"),
                html.Th("Prior Act ID"),
                html.Th("Usage Evidence"),
            ],
            style={"background": "#0d0d1a", "color": "#00e5ff", "fontSize": "11px", "textAlign": "left"},
        )
    )

    active_section = html.Div(
        [
            html.H5(
                f"🎯 Registered Members & Lifecycle Activations ({len(active_rows)} registered/active members)",
                id="activation-active-heading",
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

    # 7. Rearm Controllers Table
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
                    id="activation-rearm-heading",
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

    # 8. Terminal Activation History Table (Bounded DOM Display of up to 50 records)
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
            level_id_str = _format_level_id(rec.level_id)

            term_rows.append(
                html.Tr(
                    [
                        html.Td(html.Code(rec.activation_id, style={"fontSize": "10px", "color": "#00e5ff"})),
                        html.Td(rec.set_id, style={"color": "#00e676", "fontWeight": "bold"}),
                        html.Td(rec.role, style={"color": "#90caf9"}),
                        html.Td(html.Code(level_id_str, style={"fontSize": "10px", "color": "#ffd54f"})),
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
                    html.Th("Set ID"),
                    html.Th("Role"),
                    html.Th("Level ID"),
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
