"""Controlled browser race and publication verification tests using Playwright.

Covers R14.1 - R14.4 publication invariants executed against the live Dash application:
- Case A: Different-context requests (A: H4, B: D1 completed and accepted, stale A arrives last,
          gate rejects A, D1 retained, MSM overlay calculated and applied on D1).
- Case B: Same-context Refresh (Refresh A issued, Refresh B completed and accepted, stale Refresh A arrives,
          gate rejects A, Refresh B retained).
- Case C: Stale failure (Request B accepted, stale candidate A arrives with connection loss failure,
          gate rejects entire envelope, no loss trigger published, connection badge remains connected,
          shared adapter not disconnected, next candidate envelope carries connection_event: null).

Validates zero browser page errors throughout.
"""

from __future__ import annotations

import functools
import json
import logging
import threading
import time
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright

from aladeen.app import create_app
from aladeen.data.contract import BarStatus
from aladeen.data.mt5_adapter import MT5ConnectionError, MT5ConnectionState

# Auto-flush stdout
print = functools.partial(print, flush=True)

SERVER_PORT = 8058
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"


def _make_mock_candles(n: int = 15, base_price: float = 1.100, tf_freq: str = "4h") -> pd.DataFrame:
    """Generate contract-compliant candle DataFrame."""
    times = pd.date_range("2026-10-01", periods=n, freq=tf_freq, tz="UTC")
    return pd.DataFrame(
        {
            "open": [base_price + i * 0.001 for i in range(n)],
            "high": [base_price + 0.005 + i * 0.001 for i in range(n)],
            "low": [base_price - 0.005 + i * 0.001 for i in range(n)],
            "close": [base_price + 0.002 + i * 0.001 for i in range(n)],
            "is_forming": [False] * (n - 1) + [True],
            "is_latest_bar": [False] * (n - 1) + [True],
            "bar_status": [BarStatus.CONFIRMED_COMPLETED.value] * (n - 1) + [BarStatus.UNCONFIRMED_LATEST.value],
        },
        index=times,
    )


class ControllableMockAdapter:
    """Mock adapter supporting controlled concurrency for testing browser races."""

    def __init__(self):
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        self.symbols = ["EURUSD", "GBPUSD"]
        self.disconnect_call_count = 0
        self.lock = threading.Lock()
        self.fetch_history: list[dict[str, Any]] = []

    def is_package_installed(self) -> bool:
        return True

    def connect(self) -> MT5ConnectionState:
        self.connection_state = MT5ConnectionState.CONNECTED_TO_BROKER
        return self.connection_state

    def disconnect(self) -> None:
        self.connection_state = MT5ConnectionState.DISCONNECTED
        self.disconnect_call_count += 1

    def get_connection_state(self) -> MT5ConnectionState:
        return self.connection_state

    def is_broker_connected(self) -> bool:
        return self.connection_state == MT5ConnectionState.CONNECTED_TO_BROKER

    def get_symbols(self) -> list[str]:
        return self.symbols

    def fetch_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        with self.lock:
            self.fetch_history.append({"symbol": symbol, "timeframe": timeframe, "count": count, "time": time.time()})

        freq = "1d" if timeframe == "D1" else ("1h" if timeframe == "H1" else "4h")
        base = 1.200 if timeframe == "D1" else (1.150 if timeframe == "H1" else 1.100)
        return _make_mock_candles(count, base_price=base, tf_freq=freq)


def run_controlled_races():
    print("=== STARTING CONTROLLED BROWSER RACE VERIFICATION ===")
    mock_adapter = ControllableMockAdapter()
    app = create_app(adapter=mock_adapter)

    # Disable werkzeug logging clutter
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    server_thread = threading.Thread(
        target=lambda: app.run(debug=False, host="127.0.0.1", port=SERVER_PORT, threaded=True),
        daemon=True,
    )
    server_thread.start()
    time.sleep(2)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: print(f"  [BROWSER {msg.type.upper()}] {msg.text}") if msg.type in ("error", "warning") else None)

        # -------------------------------------------------------------------
        # SETUP: Launch page and Connect MT5
        # -------------------------------------------------------------------
        print("\n--- Setup: Launch and Connect MT5 ---")
        page.goto(SERVER_URL)
        page.wait_for_selector("#source-banner")
        print("  Page loaded.")

        # Connect MT5
        page.locator("#connect-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#connection-badge') && document.querySelector('#connection-badge').innerText.includes('Connected to Broker')",
            timeout=5000,
        )
        print("  MT5 Connected.")

        # Switch data source to MT5
        page.locator("#data-source-selector input[value='mt5']").check()
        time.sleep(0.5)

        # Select symbol EURUSD
        page.locator("#symbol-selector").click()
        page.wait_for_selector(".dash-dropdown-option")
        page.locator(".dash-dropdown-option").filter(has_text="EURUSD").click()
        time.sleep(0.5)

        # Wait for initial EURUSD H4 data to settle
        page.wait_for_function(
            "() => { const s = window.sessionStorage.getItem('market-data-store'); if (!s) return false; const d = JSON.parse(s); return d && d.symbol === 'EURUSD' && d.timeframe === 'H4'; }",
            timeout=5000,
        )
        initial_store = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        initial_req = json.loads(page.evaluate("() => window.sessionStorage.getItem('active-request-store')"))
        print(f"  Initial MT5 state settled: EURUSD H4 (Token: {initial_req['token']}).")

        # -------------------------------------------------------------------
        # CASE A: Different-Context Requests Race (H4 delayed, D1 completed, H4 arrives last)
        # -------------------------------------------------------------------
        print("\n--- Case A: Different-Context Race (A: H4 -> B: D1 completed -> delayed A arrives last) ---")

        token_a = initial_req["token"]
        stale_a_snapshot = dict(initial_store)  # H4 snapshot

        # Step A1: User selects D1 (Request B)
        print("  Step A1: Issuing Request B by selecting timeframe D1...")
        page.locator("#timeframe-selector").click()
        page.wait_for_selector(".dash-dropdown-option")
        page.locator(".dash-dropdown-option").filter(has_text="D1").click()

        # Step A2: Wait for Request B (D1) to complete and be accepted
        page.wait_for_function(
            "() => { const s = window.sessionStorage.getItem('market-data-store'); if (!s) return false; const d = JSON.parse(s); return d && d.symbol === 'EURUSD' && d.timeframe === 'D1'; }",
            timeout=5000,
        )
        page.wait_for_function(
            "() => document.querySelector('#status-area') && document.querySelector('#status-area').innerText.includes('TF: D1')",
            timeout=5000,
        )
        store_after_b = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        active_req_b = json.loads(page.evaluate("() => window.sessionStorage.getItem('active-request-store')"))
        status_after_b = page.locator("#status-area").inner_text()

        print(f"  Request B accepted: TF={store_after_b['timeframe']}, Rev={store_after_b['revision_id']}, Token={store_after_b['request_token']}")
        print(f"  Status Area: {status_after_b}")
        assert store_after_b["timeframe"] == "D1"
        assert store_after_b["request_token"] == active_req_b["token"]
        assert "TF: D1" in status_after_b

        # Step A3: Delayed Candidate Envelope A arrives LAST at the browser acceptance gate
        print("  Step A3: Delivering delayed Candidate Envelope A (H4) to market-candidate-envelope-store...")
        stale_envelope_a = {
            "request_token": token_a,
            "snapshot": stale_a_snapshot,
            "connection_event": None,
        }
        page.evaluate(
            "(env) => window.dash_clientside.set_props('market-candidate-envelope-store', { data: env })",
            stale_envelope_a,
        )
        time.sleep(0.5)

        # Step A4: Verify Acceptance Gate REJECTED stale A; market-data-store REMAINS D1!
        store_after_delayed_a = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        status_after_delayed_a = page.locator("#status-area").inner_text()
        print(f"  Store after delayed A arrived: TF={store_after_delayed_a['timeframe']}, Token={store_after_delayed_a['request_token']}")
        print(f"  Status Area after delayed A: {status_after_delayed_a}")

        assert store_after_delayed_a["timeframe"] == "D1", "Stale Request A reverted market-data-store!"
        assert store_after_delayed_a["request_token"] == active_req_b["token"], "Stale Request A corrupted active token!"
        assert "TF: D1" in status_after_delayed_a, "Status area reverted to H4!"
        print("  [PASS] Case A publication invariant: Stale A rejected by CLIENTSIDE_ACCEPTANCE_GATE_JS; D1 retained.")

        # Step A5: Edit/apply MSM controls and verify MSM calculates using Request B (D1)!
        print("  Step A5: Applying MSM overlay to verify consumer calculates using D1...")
        page.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.3)
        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)
        page.locator("#msm-start-candle-dropdown").click()
        page.wait_for_selector(".dash-dropdown-option")
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)
        page.locator("#msm-apply-btn").click()

        page.wait_for_function(
            "() => document.querySelector('#msm-edit-status') && document.querySelector('#msm-edit-status').innerText.includes('Applied: UPWARD')",
            timeout=5000,
        )
        applied_store = json.loads(page.evaluate("() => window.sessionStorage.getItem('msm-applied-store')"))
        msm_status_text = page.locator("#msm-edit-status").inner_text()
        print(f"  Applied MSM store: TF={applied_store.get('timeframe')}, Status: {msm_status_text}")
        assert applied_store["timeframe"] == "D1", "MSM applied on wrong timeframe!"
        print("  [PASS] Case A MSM verification: MSM correctly applied using D1.")

        # -------------------------------------------------------------------
        # CASE B: Same-Context Refresh Race (Refresh A issued, Refresh B accepted, stale A arrives last)
        # -------------------------------------------------------------------
        print("\n--- Case B: Same-Context Refresh Race (Refresh A -> Refresh B accepted -> stale Refresh A arrives) ---")

        # Step B1: Click Refresh (Refresh A)
        print("  Step B1: Triggering Refresh A...")
        page.locator("#refresh-btn").click()
        time.sleep(0.3)
        req_ref_a = json.loads(page.evaluate("() => window.sessionStorage.getItem('active-request-store')"))
        token_ref_a = req_ref_a["token"]
        print(f"  Refresh A Token: {token_ref_a}")

        # Capture snapshot of Refresh A
        time.sleep(0.5)
        store_ref_a = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))

        # Step B2: Click Refresh again (Refresh B)
        print("  Step B2: Triggering newer Refresh B...")
        page.locator("#refresh-btn").click()
        page.wait_for_function(
            f"() => {{ const s = window.sessionStorage.getItem('active-request-store'); if (!s) return false; return JSON.parse(s).token !== '{token_ref_a}'; }}",
            timeout=5000,
        )
        req_ref_b = json.loads(page.evaluate("() => window.sessionStorage.getItem('active-request-store')"))
        token_ref_b = req_ref_b["token"]
        print(f"  Refresh B Token: {token_ref_b}")

        # Wait for Refresh B to be accepted
        page.wait_for_function(
            f"() => {{ const s = window.sessionStorage.getItem('market-data-store'); if (!s) return false; return JSON.parse(s).request_token === '{token_ref_b}'; }}",
            timeout=5000,
        )
        store_after_ref_b = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        print(f"  Accepted store after Refresh B: Rev={store_after_ref_b['revision_id']}, Token={store_after_ref_b['request_token']}")
        assert store_after_ref_b["request_token"] == token_ref_b

        # Step B3: Delayed Candidate Envelope A arrives LAST
        print("  Step B3: Delivering delayed Candidate Envelope A to acceptance gate...")
        stale_envelope_ref_a = {
            "request_token": token_ref_a,
            "snapshot": dict(store_ref_a, revision_id="rev-stale-ref-a"),
            "connection_event": None,
        }
        page.evaluate(
            "(env) => window.dash_clientside.set_props('market-candidate-envelope-store', { data: env })",
            stale_envelope_ref_a,
        )
        time.sleep(0.5)

        # Step B4: Verify Acceptance Gate REJECTED stale Refresh A; Refresh B REMAINS!
        store_after_stale_ref_a = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        print(f"  Store after delayed Refresh A: Rev={store_after_stale_ref_a['revision_id']}, Token={store_after_stale_ref_a['request_token']}")
        assert store_after_stale_ref_a["request_token"] == token_ref_b, "Stale Refresh A corrupted active token!"
        assert store_after_stale_ref_a["revision_id"] != "rev-stale-ref-a", "Stale Refresh A overwritten market-data-store!"
        print("  [PASS] Case B publication invariant: Stale Refresh A rejected; Refresh B retained.")

        # -------------------------------------------------------------------
        # CASE C: Stale Failure Invariant (Request B accepted, stale A arrives with connection failure)
        # -------------------------------------------------------------------
        print("\n--- Case C: Stale Failure Race (Request B accepted -> stale A arrives with connection loss) ---")

        # Step C1: Issue Request B (Switch timeframe to H1)
        print("  Step C1: Switching timeframe to H1 (Request B)...")
        page.locator("#timeframe-selector").click()
        page.wait_for_selector(".dash-dropdown-option")
        page.locator(".dash-dropdown-option").filter(has_text="H1").click()

        page.wait_for_function(
            "() => { const s = window.sessionStorage.getItem('market-data-store'); if (!s) return false; const d = JSON.parse(s); return d && d.timeframe === 'H1'; }",
            timeout=5000,
        )
        store_c_b = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        active_req_c_b = json.loads(page.evaluate("() => window.sessionStorage.getItem('active-request-store')"))
        badge_before_fail = page.locator("#connection-badge").inner_text()
        print(f"  Request B (H1) accepted: Token={store_c_b['request_token']}, Badge: {badge_before_fail}")
        assert store_c_b["timeframe"] == "H1"
        assert "Connected to Broker" in badge_before_fail

        initial_disconnect_calls = mock_adapter.disconnect_call_count

        # Step C2: Stale Candidate Envelope A arrives with CONNECTION_ERROR and loss event
        print("  Step C2: Delivering stale candidate envelope A with connection loss event...")
        stale_failed_envelope = {
            "request_token": "req-obsolete-stale-id",
            "snapshot": {
                "revision_id": "rev-stale-fail",
                "data_source": "mt5",
                "symbol": "EURUSD",
                "timeframe": "H4",
                "candle_count": 0,
                "timestamp_utc": "2026-10-01 00:00:00 UTC",
                "fetch_status": "CONNECTION_ERROR",
                "error_message": "MT5 Terminal Disconnected",
                "broker_connected": False,
                "request_token": "req-obsolete-stale-id",
                "candles_data": [],
            },
            "connection_event": {
                "type": "connection_loss",
                "error": "MT5 Terminal Disconnected",
                "timestamp": "2026-10-01 00:00:00 UTC",
            },
        }
        page.evaluate(
            "(env) => window.dash_clientside.set_props('market-candidate-envelope-store', { data: env })",
            stale_failed_envelope,
        )
        time.sleep(0.5)

        # Invariant Assertions:
        # 1. No connection loss trigger published in browser
        loss_trigger_data = page.evaluate("() => window.sessionStorage.getItem('connection-loss-trigger')")
        print(f"  connection-loss-trigger in browser after stale failure: {loss_trigger_data}")
        assert loss_trigger_data is None or loss_trigger_data == "null", "Stale connection failure was erroneously published!"

        # 2. Connection badge remains Connected to Broker
        badge_after_fail = page.locator("#connection-badge").inner_text()
        print(f"  Connection badge after stale failure: {badge_after_fail}")
        assert "Connected to Broker" in badge_after_fail, "Stale failure corrupted connection badge!"

        # 3. Market-data-store remains Request B (H1)
        store_after_stale_fail = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-data-store')"))
        print(f"  Market data store after stale failure: TF={store_after_stale_fail['timeframe']}, Token={store_after_stale_fail['request_token']}")
        assert store_after_stale_fail["timeframe"] == "H1"
        assert store_after_stale_fail["request_token"] == active_req_c_b["token"]

        # 4. Shared adapter session was NOT disconnected by stale fetch work
        print(f"  Adapter disconnect calls: {mock_adapter.disconnect_call_count} (initial: {initial_disconnect_calls})")
        assert mock_adapter.disconnect_call_count == initial_disconnect_calls, "Stale fetch mutated shared adapter state!"
        assert mock_adapter.get_connection_state() == MT5ConnectionState.CONNECTED_TO_BROKER

        # 5. Next candidate carries connection_event: null
        print("  Step C3: Triggering next refresh to verify candidate envelope carries connection_event: null...")
        page.locator("#refresh-btn").click()
        time.sleep(1.0)

        envelope_data = json.loads(page.evaluate("() => window.sessionStorage.getItem('market-candidate-envelope-store')"))
        print(f"  Next candidate envelope: token={envelope_data.get('request_token')}, connection_event={envelope_data.get('connection_event')}")
        assert envelope_data["connection_event"] is None, "Next candidate did not carry connection_event: null!"
        print("  [PASS] Case C publication invariant: Stale failure rejected, no side effects, next envelope carries null event.")

        # -------------------------------------------------------------------
        # Zero Browser Errors Check
        # -------------------------------------------------------------------
        print("\n--- Browser Error Check ---")
        print(f"  Total uncaught page errors captured: {len(page_errors)}")
        if page_errors:
            for err in page_errors:
                print(f"    ERROR: {err}")
        assert len(page_errors) == 0, f"Found browser page errors: {page_errors}"
        print("  [PASS] Zero browser page errors confirmed.")

        browser.close()

    print("\n=== ALL CONTROLLED BROWSER RACE TESTS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    run_controlled_races()
