"""Application entry point.

Creates and configures the Dash application.
Run with:  python -m aladeen.app [--debug] [--port PORT]
"""

from __future__ import annotations

import argparse
import sys
from typing import Any
from dash import Dash

from aladeen.ui.layout import build_layout, register_callbacks

DASHBOARD_INDEX_STRING = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <script>
        (function() {
            function checkClonedTab() {
                try {
                    var raw = sessionStorage.getItem('dashboard-session-id-store');
                    if (raw) {
                        var parsed;
                        try { parsed = JSON.parse(raw); } catch(e) { parsed = raw; }
                        var sid = (parsed && typeof parsed === 'object') ? parsed.data : parsed;
                        if (sid && typeof sid === 'string') {
                            if (window.name === 'dashboard_tab_' + sid) {
                                return; // Same-tab reload: retain identity
                            }
                            // Cloned tab via window.open() or browser tab duplication:
                            // Generate fresh unique session ID to enforce independent-tab isolation
                            var freshId = 'session_' + (window.crypto && crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 16) : Math.random().toString(16).slice(2, 18));
                            window.name = 'dashboard_tab_' + freshId;
                            var newPayload = (parsed && typeof parsed === 'object') ? Object.assign({}, parsed, {data: freshId}) : freshId;
                            sessionStorage.setItem('dashboard-session-id-store', JSON.stringify(newPayload));
                        }
                    }
                } catch(e) {}
            }
            checkClonedTab();
            var claimAttempts = 0;
            var claimTimer = setInterval(function() {
                claimAttempts++;
                try {
                    var raw = sessionStorage.getItem('dashboard-session-id-store');
                    if (raw) {
                        var parsed;
                        try { parsed = JSON.parse(raw); } catch(e) { parsed = raw; }
                        var sid = (parsed && typeof parsed === 'object') ? parsed.data : parsed;
                        if (sid && typeof sid === 'string' && !window.name) {
                            window.name = 'dashboard_tab_' + sid;
                            clearInterval(claimTimer);
                        }
                    }
                } catch(e) {}
                if (claimAttempts > 30) clearInterval(claimTimer);
            }, 100);
        })();
        </script>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


def create_app(adapter: Any = None) -> Dash:
    """Build and return a configured Dash application instance.

    The app defaults to demo fixtures and does not require MT5 to be
    installed or running to launch.
    """
    app = Dash(
        __name__,
        title="Aladeen / TopG",
        update_title="Loading…",
    )
    app.index_string = DASHBOARD_INDEX_STRING
    app.layout = build_layout
    register_callbacks(app, adapter=adapter)
    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Aladeen / TopG Trading Dashboard")
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable Dash development debug mode (default: False)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1 - localhost only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port to listen on (default: 8050)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the development server on localhost."""
    args = parse_args(argv)
    app = create_app()
    app.run(debug=args.debug, host=args.host, port=args.port)


if __name__ == "__main__":
    main(sys.argv[1:])
