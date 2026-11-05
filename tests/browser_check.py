"""Browser verification script using Playwright.

Tests actual browser flow:
connect -> fetch -> change timeframe -> disconnect -> reconnect
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

        # Switch data source to MT5
        print("2. Switching Data Source to MT5...")
        page.locator("input[value='mt5']").check()
        page.wait_for_function(
            "() => document.querySelector('#source-banner') && document.querySelector('#source-banner').innerText.includes('MT5 DISCONNECTED')",
            timeout=10000,
        )
        banner_text = page.locator("#source-banner").inner_text()
        print(f"   Banner after selecting MT5: {banner_text}")
        assert "MT5 DISCONNECTED" in banner_text

        # Connect MT5
        print("3. Clicking Connect MT5...")
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
        assert "MT5 CONNECTED" in banner_text or "MT5 TERMINAL READY" in banner_text
        assert "Source: MT5 Terminal" in status_text

        # Click Refresh
        print("4. Clicking Refresh...")
        page.locator("#refresh-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#status-area') && document.querySelector('#status-area').innerText.includes('Source: MT5 Terminal')",
            timeout=10000,
        )
        status_text = page.locator("#status-area").inner_text()
        print(f"   Status after refresh: {status_text}")
        assert "Source: MT5 Terminal" in status_text

        # Change Timeframe to H1
        print("5. Changing Timeframe to H1...")
        page.locator("#timeframe-selector").click()
        page.locator(".dash-dropdown-option").filter(has_text="H1").click()
        page.wait_for_function(
            "() => document.querySelector('#status-area') && document.querySelector('#status-area').innerText.includes('TF: H1')",
            timeout=10000,
        )
        status_text = page.locator("#status-area").inner_text()
        print(f"   Status after TF change: {status_text}")
        assert "TF: H1" in status_text

        # Disconnect MT5
        print("6. Clicking Disconnect...")
        page.locator("#disconnect-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#connection-badge') && document.querySelector('#connection-badge').innerText.includes('Disconnected')",
            timeout=10000,
        )
        page.wait_for_function(
            "() => document.querySelector('#status-area') && document.querySelector('#status-area').innerText.includes('MT5 Disconnected')",
            timeout=10000,
        )
        badge_text = page.locator("#connection-badge").inner_text()
        banner_text = page.locator("#source-banner").inner_text()
        status_text = page.locator("#status-area").inner_text()
        print(f"   Badge: {badge_text}")
        print(f"   Banner: {banner_text}")
        print(f"   Status: {status_text}")
        assert "Disconnected" in badge_text
        assert "MT5 DISCONNECTED" in banner_text
        assert "MT5 Disconnected" in status_text

        # Reconnect MT5
        print("7. Reconnecting MT5...")
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
        print(f"   Badge: {badge_text}")
        print(f"   Banner: {banner_text}")
        assert "Connected" in badge_text or "Terminal Ready" in badge_text
        assert "MT5 CONNECTED" in banner_text or "MT5 TERMINAL READY" in banner_text

        browser.close()
        print("\nALL BROWSER FLOW STEPS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
