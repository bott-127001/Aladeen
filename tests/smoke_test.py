import threading
import time
import urllib.request
from aladeen.app import create_app

def run_startup_smoke_test():
    app = create_app()
    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=8051, debug=False),
        daemon=True
    )
    server.start()
    time.sleep(2)

    # Test GET /
    with urllib.request.urlopen("http://127.0.0.1:8051/") as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        body = resp.read().decode("utf-8")
        assert "Aladeen / TopG" in body
        print("Root / returned 200 OK with title")

    # Test GET /_dash-layout
    with urllib.request.urlopen("http://127.0.0.1:8051/_dash-layout") as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        layout = resp.read().decode("utf-8")
        assert "main-chart" in layout
        assert "data-source-selector" in layout
        assert "connection-badge" in layout
        print("_dash-layout returned 200 OK with expected component IDs")

    print("Smoke test PASSED!")

if __name__ == "__main__":
    run_startup_smoke_test()
