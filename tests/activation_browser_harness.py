"""Verification harness and infrastructure for controlled activation browser validation.

Provides controllable server handles with explicit socket and thread assertions,
context-level exact-origin request firewalls, server-side network socket guards,
and audit watchers for Milestone 28 controlled browser validation.
"""

from __future__ import annotations

from contextlib import contextmanager
import dataclasses
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import socket
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
import urllib.parse
from werkzeug.serving import make_server

import pandas as pd
from dash import Dash, Input, Output, dcc, html
from playwright.sync_api import BrowserContext, Page, Request, Response, Route

from aladeen.app import create_app
from aladeen.data.contract import BarStatus
from aladeen.data.mt5_adapter import MT5ConnectionState
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    CoverageStatus,
    RearmController,
)
from aladeen.ui.activation_inspection import (
    CANONICAL_UNRESOLVED_BANNER,
    build_activation_inspection_elements,
)
from tests.test_activation_dashboard_integration import make_snapshot_from_fixture

logger = logging.getLogger("activation_browser_harness")

PROD_PORT = 8068
HARNESS_PORT = 8069
PROD_URL = f"http://127.0.0.1:{PROD_PORT}"
HARNESS_URL = f"http://127.0.0.1:{HARNESS_PORT}"
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PROD_PORT}", f"http://127.0.0.1:{HARNESS_PORT}"}


class ControlledServerHandle:
    """Controllable Werkzeug server handle with fail-verifiable startup, shutdown, and port audit."""

    def __init__(self, app: Dash, host: str, port: int, label: str):
        self.host = host
        self.port = port
        self.label = label
        self.app = app
        self.server: Optional[Any] = None
        self.thread: Optional[threading.Thread] = None
        self._is_running = False

    def start(self) -> None:
        """Starts server thread and asserts socket binding within timeout."""
        logger.info(f"Starting {self.label} on http://{self.host}:{self.port}...")
        try:
            self.server = make_server(self.host, self.port, self.app.server, threaded=True)
        except SystemExit as se:
            raise RuntimeError(f"{self.label} failed to bind to {self.host}:{self.port} (port occupied or forbidden)") from se

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self._is_running = True

        deadline = time.time() + 5.0
        bound = False
        while time.time() < deadline:
            try:
                with socket.create_connection((self.host, self.port), timeout=0.2):
                    bound = True
                    logger.info(f"✓ {self.label} bound and listening on port {self.port}")
                    break
            except OSError:
                time.sleep(0.05)

        if not bound:
            self.stop()
            raise RuntimeError(f"{self.label} failed to bind and listen on {self.host}:{self.port} within deadline")

    def stop(self) -> None:
        """Shuts down server, closes socket, asserts thread termination, and asserts port release."""
        if not self._is_running:
            return
        logger.info(f"Stopping {self.label} on port {self.port}...")

        # 1. Shutdown HTTP serving loop
        if self.server is not None:
            try:
                self.server.shutdown()
            except Exception as e:
                logger.error(f"Error calling shutdown on {self.label}: {e}")

            # 2. Explicitly close listening server socket
            try:
                self.server.server_close()
            except Exception as e:
                logger.error(f"Error closing socket on {self.label}: {e}")

        # 3. Join thread and assert thread termination
        if self.thread is not None:
            self.thread.join(timeout=4.0)
            assert not self.thread.is_alive(), f"{self.label} thread failed to terminate within 4.0s timeout"

        # 4. Explicitly assert port is released (connecting must raise OSError)
        deadline = time.time() + 4.0
        released = False
        while time.time() < deadline:
            try:
                with socket.create_connection((self.host, self.port), timeout=0.2):
                    time.sleep(0.05)
            except OSError:
                released = True
                logger.info(f"✓ Port {self.port} ({self.label}) cleanly released")
                break

        self._is_running = False
        if not released:
            raise RuntimeError(f"Port {self.port} ({self.label}) remained bound after teardown")


@contextmanager
def managed_servers(*servers: ControlledServerHandle) -> Iterator[List[ControlledServerHandle]]:
    """Context manager guaranteeing startup error recovery and clean multi-server teardown."""
    started: List[ControlledServerHandle] = []
    try:
        for s in servers:
            s.start()
            started.append(s)
        yield started
    finally:
        errors = []
        for s in reversed(started):
            try:
                s.stop()
            except Exception as e:
                errors.append(e)
        if errors:
            raise RuntimeError(f"Errors occurred during server teardown: {errors}")


class ContextSecurityFirewall:
    """Exact-origin request interception installed on Playwright BrowserContext before any navigation."""

    def __init__(self, allowed_origins: Set[str]):
        self.allowed_origins = allowed_origins
        self.blocked_requests: List[Dict[str, str]] = []

    def attach(self, context: BrowserContext) -> None:
        """Installs route interception across all pages created within the browser context."""
        def handle_route(route: Route) -> None:
            req_url = route.request.url
            # Allow browser internal data/about protocols
            if req_url.startswith("data:") or req_url == "about:blank":
                route.continue_()
                return

            parsed = urllib.parse.urlsplit(req_url)
            exact_origin = f"{parsed.scheme}://{parsed.netloc}"

            if exact_origin in self.allowed_origins:
                route.continue_()
            else:
                self.blocked_requests.append({
                    "url": req_url,
                    "origin": exact_origin,
                    "method": route.request.method,
                })
                logger.warning(f"BLOCKED UNAUTHORIZED REQUEST: {req_url} (origin {exact_origin})")
                route.abort("blockedbyclient")

        context.route("**/*", handle_route)

    def assert_clean(self) -> None:
        """Asserts that zero unauthorized requests were attempted."""
        assert len(self.blocked_requests) == 0, f"Unauthorized external requests blocked: {self.blocked_requests}"


@contextmanager
def install_server_socket_guard(allowed_hosts: Set[str]) -> Iterator[List[str]]:
    """Monkeypatches socket.socket.connect to fail-fast on any external connection attempt."""
    orig_connect = socket.socket.connect
    violations: List[str] = []

    def guarded_connect(sock_self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, (tuple, list)) else address
        if str(host) not in allowed_hosts:
            violation_msg = f"Unauthorized socket connection attempt to {address}"
            violations.append(violation_msg)
            raise PermissionError(violation_msg)
        return orig_connect(sock_self, address)

    socket.socket.connect = guarded_connect
    try:
        yield violations
    finally:
        socket.socket.connect = orig_connect


class ControllableActivationMockAdapter:
    """Offline test adapter ensuring zero MT5 process or external network dependencies."""

    def __init__(self) -> None:
        self.connection_state: MT5ConnectionState = MT5ConnectionState.CONNECTED_TO_BROKER
        self.live_broker_invocations: int = 0

    def is_package_installed(self) -> bool:
        return True

    def connect(self) -> MT5ConnectionState:
        return self.connection_state

    def get_connection_state(self) -> MT5ConnectionState:
        return self.connection_state

    def disconnect(self) -> None:
        pass

    def get_market_data(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "H1",
        count: int = 100,
        status_filter: Optional[Any] = None,
        max_age_seconds: Optional[float] = None,
    ) -> pd.DataFrame:
        if symbol not in ("EURUSD", "GBPUSD", "XAUUSD", "DEMO_EURUSD", "DEMO_GBPUSD", "DEMO_XAUUSD"):
            self.live_broker_invocations += 1
            raise RuntimeError(f"Unsanctioned live symbol requested: {symbol}")
        return self._generate_synthetic_df(symbol=symbol, timeframe=timeframe, count=count)

    def order_send(self, *args: Any, **kwargs: Any) -> Any:
        self.live_broker_invocations += 1
        raise PermissionError("ORDER EXECUTION STRICTLY PROHIBITED IN DASHBOARD SCOPE")

    def _generate_synthetic_df(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        step = timedelta(hours=1 if "H" in timeframe else (4 if timeframe == "H4" else 5))
        records = []
        base_p = 1.1350 if "EUR" in symbol else (1.2750 if "GBP" in symbol else 2650.0)
        for i in range(count):
            t = base_time + i * step
            p = base_p + (i % 10) * 0.0010
            records.append(
                {
                    "time": t,
                    "open": p,
                    "high": p + 0.0020,
                    "low": p - 0.0020,
                    "close": p + 0.0005,
                    "tick_volume": 100,
                    "spread": 1,
                    "real_volume": 0,
                    "bar_status": BarStatus.CLOSED.value if i < count - 1 else BarStatus.FORMING.value,
                }
            )
        df = pd.DataFrame(records)
        df["index"] = list(range(len(df)))
        return df


class BrowserAuditWatcher:
    """Full-lifecycle audit monitor attached to pages and contexts for comprehensive error and callback auditing."""

    def __init__(self) -> None:
        self.console_errors: List[Dict[str, str]] = []
        self.page_errors: List[str] = []
        self.failed_callback_responses: List[Dict[str, Any]] = []
        self.failed_callback_requests: List[Dict[str, Any]] = []

    def attach_context(self, context: BrowserContext, label: str) -> None:
        """Attaches page auditing through context page events before navigation can complete."""
        def on_page(page: Page) -> None:
            page_label = f"{label}-SpawnedTab"
            self.attach(page, page_label)

        context.on("page", on_page)

    def attach(self, page: Page, label: str) -> None:
        """Attaches console, pageerror, requestfailed, and response event listeners to a page."""
        def on_console(msg: Any) -> None:
            if msg.type == "error":
                text = msg.text
                # Filter strictly benign browser 404 for missing favicon
                if "favicon.ico" in text:
                    return
                # Do not blanket suppress net::ERR_ABORTED; only filter if specifically about favicon
                self.console_errors.append({"page": label, "text": text})

        def on_page_error(err: Any) -> None:
            self.page_errors.append(f"[{label}] {str(err)}")

        def on_response(response: Response) -> None:
            url = response.url
            if "/_dash-update-component" in url:
                if response.status != 200:
                    self.failed_callback_responses.append({
                        "page": label,
                        "url": url,
                        "status": response.status,
                    })

        def on_request_failed(request: Request) -> None:
            url = request.url
            if "/_dash-update-component" in url:
                failure = request.failure
                failure_text = str(failure) if failure else ""
                # Narrowly distinguish expected navigation cancellations if any
                if "NS_BINDING_ABORTED" in failure_text:
                    logger.info(f"Ignored benign navigation abort for callback: {url}")
                    return
                self.failed_callback_requests.append({
                    "page": label,
                    "url": url,
                    "failure": failure_text,
                })

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

    def assert_clean(self) -> None:
        """Asserts zero console errors, zero page errors, zero non-200 responses, and zero failed callback requests."""
        assert len(self.console_errors) == 0, f"Encountered browser console errors: {self.console_errors}"
        assert len(self.page_errors) == 0, f"Encountered uncaught page errors: {self.page_errors}"
        assert len(self.failed_callback_responses) == 0, f"Encountered failed Dash callback responses: {self.failed_callback_responses}"
        assert len(self.failed_callback_requests) == 0, f"Encountered failed Dash callback requests (no response): {self.failed_callback_requests}"


def configure_and_apply_msm(
    page: Page, timeframe: Optional[str] = None, direction: str = "UPWARD"
) -> None:
    """Configures MSM calculation mode, direction, start candle, and applies."""
    page.locator("#msm-enable-toggle input[value='enabled']").check()
    time.sleep(0.2)
    page.locator("#strategy-calculation-mode input[value='INTEGRATED_MSM_CHOCH_TJL']").check()
    time.sleep(0.2)
    page.locator(f"#msm-direction-selector input[value='{direction}']").check()
    time.sleep(0.2)
    if timeframe:
        page.locator("#timeframe-selector").click()
        time.sleep(0.3)
        page.locator(f".dash-dropdown-option:has-text('{timeframe}')").click()
        time.sleep(2.0)
    page.locator("#msm-start-candle-dropdown").click()
    time.sleep(0.5)
    page.locator(".dash-dropdown-option").first.wait_for(state="visible", timeout=10000)
    page.locator(".dash-dropdown-option").first.click()
    time.sleep(0.3)
    page.locator("#msm-apply-btn").click()
    page.wait_for_selector("#activation-inspection-container", timeout=10000)


def _create_fixture_harness_app(fixtures: Dict[str, Any]) -> Dash:
    """Builds a local visual Dash harness to project offline acceptance scenarios."""
    app = Dash("activation_fixture_harness")
    scenario_options = []
    for k, v in fixtures.items():
        cat = v.get("evidence_category", "unknown")
        if k == "dash_act_13_unresolved_source_snapshot":
            scenario_options.append({"label": f"Scenario 13: {k} (SYNTHETIC SNAPSHOT PROJECTION)", "value": k})
        else:
            scenario_options.append({"label": f"{cat}: {k}", "value": k})

    scenario_options.append({
        "label": "Custom: History 50+ Record Display Limit (Bounded at 50)",
        "value": "custom_history_50_plus_limit",
    })
    scenario_options.append({
        "label": "Custom: Synchronization-Error Diagnostic Banner Display",
        "value": "custom_sync_error_diagnostic",
    })

    app.layout = html.Div(
        [
            html.H3("🔬 Activation Dashboard Visual Acceptance Fixture Harness", style={"color": "#00e5ff"}),
            html.Div(
                "🔬 LOCAL VISUAL FIXTURE HARNESS — PURE PRESENTATION PROJECTION OF PRE-CONSTRUCTED SYNTHETIC SNAPSHOT FIXTURES (NOT LIVE STRATEGY ENGINE EXECUTION)",
                id="harness-synthetic-notice",
                style={"padding": "8px", "background": "#1a237e", "color": "#e8eaf6", "fontWeight": "bold", "fontSize": "11px", "marginBottom": "12px", "borderRadius": "4px"},
            ),
            html.Div(
                [
                    html.Label("Select Offline Acceptance Scenario:", style={"color": "#aaa", "marginRight": "10px"}),
                    dcc.Dropdown(
                        id="scenario-selector",
                        options=scenario_options,
                        value=None,
                        clearable=False,
                        style={"width": "500px", "color": "#000"},
                    ),
                    html.Div(id="harness-current-scenario", style={"display": "none"}, children=""),
                ],
                style={"marginBottom": "16px"},
            ),
            html.Div(id="harness-output-container"),
        ],
        style={"padding": "16px", "background": "#0e1117", "minHeight": "100vh", "color": "#eee", "fontFamily": "sans-serif"},
    )

    @app.callback(
        Output("harness-output-container", "children"),
        Output("harness-current-scenario", "children"),
        Input("scenario-selector", "value"),
    )
    def render_scenario_projection(scenario_key: Optional[str]) -> Tuple[Any, str]:
        if not scenario_key:
            return html.Div("Select a scenario to project."), ""
        if scenario_key == "custom_history_50_plus_limit":
            base_act_snap, _ = make_snapshot_from_fixture(fixtures["dash_act_07_source_cancellation"])
            terminal_list = []
            for i in range(75):
                rec = ActivationRecord(
                    activation_id=f"ACT_HIST_{i:03d}",
                    engine_id=base_act_snap.engine_id,
                    symbol=base_act_snap.symbol,
                    source_timeframe=base_act_snap.source_timeframe,
                    confirmation_timeframe=base_act_snap.confirmation_timeframe,
                    set_id="SET_HIST",
                    role="TJL_FIRST_BEARISH_LEVEL",
                    level_id=None,
                    lower_edge=1.1300 + i * 0.0001,
                    upper_edge=1.1310 + i * 0.0001,
                    state=ActivationState.CANCELLED_SOURCE_CHOCH,
                    first_touch_time=datetime(2026, 10, 1, 8, 15, tzinfo=timezone.utc),
                    first_touch_price=1.1305,
                    trigger_observation_id=f"OBS_{i:03d}",
                    prior_activation_id=None,
                    rearm_armed=False,
                    last_observed_position=None,
                    usage_evidence_status=None,
                    cancellation_reason=CancellationReason.SOURCE_CHOCH,
                    cancellation_time=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=i),
                    cancellation_sequence_ref=100 + i,
                    generation_seq=1,
                    terminal=True,
                    blocked_reason=None,
                )
                terminal_list.append(rec)
            act_snap = dataclasses.replace(
                base_act_snap,
                terminal_activations=tuple(terminal_list),
            )
            elements = build_activation_inspection_elements(activation_snapshot=act_snap)
            return elements, scenario_key

        elif scenario_key == "custom_sync_error_diagnostic":
            base_act_snap, base_tjl_snap = make_snapshot_from_fixture(fixtures["dash_act_02_first_exact_touch"])
            elements = build_activation_inspection_elements(
                activation_snapshot=base_act_snap,
                tjl_snapshot=base_tjl_snap,
                last_synced_transition_index=15,
                activation_error="Synchronization Diagnostic: TJL cursor mismatch between transition index 15 and 16.",
            )
            return elements, scenario_key

        fixture_data = fixtures.get(scenario_key)
        if not fixture_data:
            return html.Div(f"Unknown scenario key: {scenario_key}"), scenario_key

        act_snap, tjl_snap = make_snapshot_from_fixture(fixture_data)
        elements = build_activation_inspection_elements(
            activation_snapshot=act_snap,
            tjl_snapshot=tjl_snap,
            last_synced_transition_index=fixture_data.get("last_synced_transition_index"),
            activation_error=fixture_data.get("activation_error"),
        )
        return elements, scenario_key

    return app


def verify_server_lifecycle_failure_injection() -> None:
    """Verifies that ControlledServerHandle and managed_servers cleanly release resources on failure."""
    print("\n--- FAILURE-INJECTION VERIFICATION: Server Lifecycle & Recovery ---")
    dummy_app = Dash("dummy_test_app")
    dummy_app.layout = html.Div("Dummy")

    # 1. Verify single server start, stop, socket release, and thread termination
    s = ControlledServerHandle(dummy_app, "127.0.0.1", 8098, "Test Server")
    s.start()
    assert s._is_running is True
    assert s.thread is not None and s.thread.is_alive()
    s.stop()
    assert s._is_running is False
    assert not s.thread.is_alive()
    print("   ✓ Single server lifecycle verified: startup, socket binding, thread join, and port release.")

    # 2. Verify managed_servers startup failure cleans up prior started server on collision
    s1 = ControlledServerHandle(dummy_app, "127.0.0.1", 8098, "Test Server 1")
    occupied_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied_sock.bind(("127.0.0.1", 0))
    occupied_port = occupied_sock.getsockname()[1]
    occupied_sock.listen(1)

    try:
        s2 = ControlledServerHandle(dummy_app, "127.0.0.1", occupied_port, "Test Server 2 (Colliding)")
        failed = False
        try:
            with managed_servers(s1, s2):
                pass
        except Exception:
            failed = True
        assert failed is True, "managed_servers must fail if a server cannot bind"
        assert s1._is_running is False, "Server 1 must be cleanly stopped if Server 2 fails to start"
        print("   ✓ Startup failure recovery verified: Server 1 cleanly stopped when Server 2 startup failed.")
    finally:
        occupied_sock.close()

    # 3. Verify managed_servers teardown when an exception occurs INSIDE the managed body
    s3 = ControlledServerHandle(dummy_app, "127.0.0.1", 8097, "Test Server 3")
    s4 = ControlledServerHandle(dummy_app, "127.0.0.1", 8096, "Test Server 4")
    body_exception_raised = False
    try:
        with managed_servers(s3, s4):
            assert s3._is_running is True
            assert s4._is_running is True
            raise AssertionError("Simulated test assertion failure inside browser execution body")
    except AssertionError as ae:
        body_exception_raised = True
        assert "Simulated test assertion failure" in str(ae)

    assert body_exception_raised is True, "Assertion error must propagate out of managed_servers"
    assert s3._is_running is False, "Server 3 must be cleanly stopped after exception in body"
    assert s4._is_running is False, "Server 4 must be cleanly stopped after exception in body"
    assert not s3.thread.is_alive(), "Server 3 thread must be joined after exception in body"
    assert not s4.thread.is_alive(), "Server 4 thread must be joined after exception in body"
    print("   ✓ Failure inside managed body verified: all running servers cleanly stopped and joined on assertion failure.")


def verify_isolation_guards_negative_controls(browser: Any) -> None:
    """Verifies that ContextSecurityFirewall and install_server_socket_guard reject prohibited access."""
    print("\n--- NEGATIVE CONTROLS: Isolation Guards Rejection Verification ---")

    # 1. Negative control for ContextSecurityFirewall
    test_firewall = ContextSecurityFirewall({"http://127.0.0.1:8068"})
    test_ctx = browser.new_context()
    test_firewall.attach(test_ctx)
    test_page = test_ctx.new_page()

    # Attempt to route to a disallowed near-match origin (unauthorized local port 8070)
    blocked_navigation = False
    try:
        test_page.goto("http://127.0.0.1:8070/api/test", timeout=3000)
    except Exception as e:
        blocked_navigation = True
        err_msg = str(e).lower()
        assert "err_blocked_by_client" in err_msg or "net::err_failed" in err_msg or "blockedbyclient" in err_msg

    assert blocked_navigation is True, "Firewall must abort request to unauthorized port 8070"
    assert len(test_firewall.blocked_requests) == 1, "Blocked request must be recorded in firewall audit"
    assert test_firewall.blocked_requests[0]["origin"] == "http://127.0.0.1:8070"

    # Attempt to route to an external domain (example.com)
    try:
        test_page.goto("http://example.com/unauthorized", timeout=3000)
    except Exception as e:
        err_msg = str(e).lower()
        assert "err_blocked_by_client" in err_msg or "net::err_failed" in err_msg or "blockedbyclient" in err_msg

    assert len(test_firewall.blocked_requests) == 2
    assert test_firewall.blocked_requests[1]["origin"] == "http://example.com"
    test_ctx.close()
    print("   ✓ ContextSecurityFirewall negative controls verified: unauthorized port 8070 and external domain blocked before navigation.")

    # 2. Negative control for install_server_socket_guard
    underlying_calls: List[Any] = []
    real_orig_connect = socket.socket.connect

    def mock_underlying_connect(self: socket.socket, address: Any) -> None:
        underlying_calls.append(address)

    # Monkeypatch the base connect target to avoid actual network traffic during negative test
    socket.socket.connect = mock_underlying_connect
    try:
        with install_server_socket_guard({"127.0.0.1", "localhost"}) as violations:
            dummy_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # A) Prohibited external destination
            prohibited_rejected = False
            try:
                dummy_s.connect(("8.8.8.8", 53))
            except PermissionError as pe:
                prohibited_rejected = True
                assert "Unauthorized socket connection attempt to ('8.8.8.8', 53)" in str(pe)

            assert prohibited_rejected is True, "Socket guard must raise PermissionError for prohibited IP"
            assert len(violations) == 1
            assert len(underlying_calls) == 0, "Prohibited address must never reach underlying connect"

            # B) Permitted local destination
            dummy_s.connect(("127.0.0.1", 8068))
            assert len(violations) == 1  # Unchanged
            assert len(underlying_calls) == 1
            assert underlying_calls[0] == ("127.0.0.1", 8068)
            dummy_s.close()
    finally:
        socket.socket.connect = real_orig_connect

    # C) Verify guard restoration after an exception inside the managed context
    exception_raised = False
    try:
        with install_server_socket_guard({"127.0.0.1"}):
            raise ValueError("Forced error inside socket guard context")
    except ValueError:
        exception_raised = True

    assert exception_raised is True
    # Verify socket.socket.connect is restored to real_orig_connect
    assert socket.socket.connect == real_orig_connect, "Socket guard must be cleanly restored even on exception"
    print("   ✓ install_server_socket_guard negative controls verified: prohibited destination blocked from connect, allowed host passed, clean restoration on exception.")
