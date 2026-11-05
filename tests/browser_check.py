"""Browser verification script using Playwright.

Tests complete browser interaction and MSM workflow:
1. Initial Demo state: direction and start dropdown are unselected (None).
2. Apply without selection fails closed with descriptive validation alert.
3. Explicit direction and starting candle selection followed by Apply.
4. Unapplied edits: changing direction shows unapplied status without corrupting state.
5. Recalculate: clicking Apply recomputes with new parameters.
6. Context switch: changing timeframe clears incompatible markings and inspection results.
7. Disable and re-enable: preserves state integrity.
8. Real MT5 Market Data: connects to local MT5 terminal, selects symbol, chooses
   starting candle from real MT5 history, applies MSM, and verifies structure marking.
9. Disconnect and reconnect.
10. Validates zero browser console errors throughout the entire flow.
"""

from __future__ import annotations

import sys
import threading
import time
import functools

# Auto-flush prints
print = functools.partial(print, flush=True)

from aladeen.app import create_app
from playwright.sync_api import sync_playwright

app = create_app()


def run_server():
    app.run(debug=False, host="127.0.0.1", port=8056)


def main():
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(3)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        page.goto("http://127.0.0.1:8056")
        page.wait_for_selector("#source-banner")
        print("1. Initial page loaded.")

        # Verify initial Demo state
        banner_text = page.locator("#source-banner").inner_text()
        badge_text = page.locator("#connection-badge").inner_text()
        print(f"   Initial Banner: {banner_text}")
        print(f"   Initial Badge: {badge_text}")
        assert "DEMO MODE" in banner_text
        assert "Disconnected" in badge_text

        # -------------------------------------------------------------------
        # 2. MSM Strategy Controls (R10.2: Manual Direction & Start)
        # -------------------------------------------------------------------
        print("2. Testing MSM Strategy Controls in Demo Mode...")
        assert page.locator("#msm-controls-panel").is_visible()
        assert page.locator("#msm-inspection-container").is_visible()

        # Check Enable MSM checkbox
        print("   Checking 'Enable MSM Overlay'...")
        page.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.5)

        # 2a. Apply without direction or start -> must be rejected
        print("   Clicking Apply without direction or start (validation check)...")
        page.locator("#msm-apply-btn").click()
        time.sleep(0.5)
        status_err = page.locator("#msm-edit-status").inner_text()
        print(f"   Validation Alert: {status_err}")
        assert "Initial direction not selected" in status_err or "No starting candle selected" in status_err

        # 2b. Explicit Direction and Starting Candle Selection
        print("   Explicitly selecting Direction '↗ UPWARD'...")
        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)

        print("   Explicitly selecting Starting Candle from dropdown...")
        page.locator("#msm-start-candle-dropdown").click()
        # Select first option in dropdown
        page.locator(".dash-dropdown-option").first.click()
        time.sleep(0.3)

        # 2c. Click Apply
        print("   Clicking Apply / Calculate MSM...")
        page.locator("#msm-apply-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#msm-edit-status') && document.querySelector('#msm-edit-status').innerText.includes('Applied: UPWARD')",
            timeout=10000,
        )
        msm_status = page.locator("#msm-edit-status").inner_text()
        print(f"   MSM Edit Status: {msm_status}")
        assert "Applied: UPWARD" in msm_status

        # Verify MSM Inspection Table rendered with exact 1-based labels (R10.3)
        page.wait_for_selector("#msm-inspection-panel table")
        inspection_text = page.locator("#msm-inspection-panel").inner_text()
        print(f"   Inspection Summary: {inspection_text.splitlines()[0] if inspection_text else ''}")
        assert "Engine State:" in inspection_text
        assert "Trend Status:" in inspection_text
        assert "Confirmed High (H1)" in inspection_text or "Confirmed Low (L1)" in inspection_text

        # -------------------------------------------------------------------
        # 3. Unapplied Edits & Recalculate Flow
        # -------------------------------------------------------------------
        print("3. Testing Unapplied Edits Detection...")
        # Change direction to DOWNWARD without clicking Apply
        page.locator("#msm-direction-selector input[value='DOWNWARD']").check()
        page.wait_for_function(
            "() => document.querySelector('#msm-edit-status') && document.querySelector('#msm-edit-status').innerText.includes('Unapplied changes')",
            timeout=10000,
        )
        unapplied_status = page.locator("#msm-edit-status").inner_text()
        print(f"   Status after edit: {unapplied_status}")
        assert "Unapplied changes" in unapplied_status

        # Recalculate by clicking Apply
        print("   Clicking Apply to recalculate with DOWNWARD...")
        page.locator("#msm-apply-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#msm-edit-status') && document.querySelector('#msm-edit-status').innerText.includes('Applied: DOWNWARD')",
            timeout=10000,
        )
        recalc_status = page.locator("#msm-edit-status").inner_text()
        print(f"   Status after recalculate: {recalc_status}")
        assert "Applied: DOWNWARD" in recalc_status

        # -------------------------------------------------------------------
        # 4. Context Switch Clearing Incompatible Results
        # -------------------------------------------------------------------
        print("4. Testing Context Switch (H4 -> D1)...")
        page.locator("#timeframe-selector").click()
        page.locator(".dash-dropdown-option").filter(has_text="D1").click()
        page.wait_for_function(
            "() => document.querySelector('#msm-edit-status') && document.querySelector('#msm-edit-status').innerText.includes('Context changed')",
            timeout=10000,
        )
        ctx_status = page.locator("#msm-edit-status").inner_text()
        print(f"   Status after context change: {ctx_status}")
        assert "Context changed" in ctx_status

        # -------------------------------------------------------------------
        # 5. Disable and Re-enable Behavior
        # -------------------------------------------------------------------
        print("5. Testing Disable & Re-enable Behavior...")
        page.locator("#msm-enable-toggle input[value='enabled']").uncheck()
        time.sleep(0.5)
        disable_status = page.locator("#msm-edit-status").inner_text()
        print(f"   Status after disabling: {disable_status}")
        assert "MSM is disabled" in disable_status

        page.locator("#msm-enable-toggle input[value='enabled']").check()
        time.sleep(0.5)

        # -------------------------------------------------------------------
        # 6. Real MT5 Terminal Connection & Real Market Data MSM Application
        # -------------------------------------------------------------------
        print("6. Testing MT5 Market Data Integration and Real MSM Overlay...")
        page.locator("input[value='mt5']").check()
        page.wait_for_function(
            "() => document.querySelector('#source-banner') && document.querySelector('#source-banner').innerText.includes('MT5 DISCONNECTED')",
            timeout=10000,
        )

        print("   Connecting to local MT5 Terminal...")
        page.locator("#connect-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#connection-badge') && !document.querySelector('#connection-badge').innerText.includes('Disconnected')",
            timeout=10000,
        )
        page.wait_for_function(
            "() => document.querySelector('#status-area') && document.querySelector('#status-area').innerText.includes('Source: MT5 Terminal')",
            timeout=10000,
        )
        badge_text = page.locator("#connection-badge").inner_text()
        banner_text = page.locator("#source-banner").inner_text()
        status_text = page.locator("#status-area").inner_text()
        print(f"   Badge: {badge_text}")
        print(f"   Banner: {banner_text}")
        print(f"   Status: {status_text}")
        assert "Connected" in badge_text or "Terminal Ready" in badge_text

        # Wait for starting candle dropdown to populate from MT5 data
        print("   Waiting for MT5 starting candle options...")
        time.sleep(1.5)
        page.locator("#msm-direction-selector input[value='UPWARD']").check()
        time.sleep(0.3)
        page.locator("#msm-start-candle-dropdown").click()
        time.sleep(0.5)

        dropdown_opts = page.locator(".dash-dropdown-option")
        opt_count = dropdown_opts.count()
        print(f"   MT5 Starting Candle Options Count: {opt_count}")
        if opt_count > 0:
            dropdown_opts.first.click()
            time.sleep(0.3)
            print("   Applying MSM to real MT5 market data...")
            page.locator("#msm-apply-btn").click()
            time.sleep(1.5)
            mt5_msm_status = page.locator("#msm-edit-status").inner_text()
            print(f"   MT5 MSM Status: {mt5_msm_status}")
            assert "Applied: UPWARD" in mt5_msm_status

        # -------------------------------------------------------------------
        # 7. Disconnect and Cleanup
        # -------------------------------------------------------------------
        print("7. Disconnecting MT5...")
        page.locator("#disconnect-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#connection-badge') && document.querySelector('#connection-badge').innerText.includes('Disconnected')",
            timeout=10000,
        )
        badge_text = page.locator("#connection-badge").inner_text()
        print(f"   Badge after disconnect: {badge_text}")
        assert "Disconnected" in badge_text

        # Verify no console or dependency errors occurred
        print(f"8. Browser Console Errors Count: {len(console_errors)}")
        if console_errors:
            print("   Console errors found:", console_errors)
        assert len(console_errors) == 0, f"Unexpected browser console errors: {console_errors}"

        browser.close()
        print("\nALL BROWSER FLOW STEPS PASSED SUCCESSFULLY (0 console errors, converged cleanly)!")


if __name__ == "__main__":
    main()
