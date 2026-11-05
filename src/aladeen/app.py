"""Application entry point.

Creates and configures the Dash application.
Run with:  python -m aladeen.app [--debug] [--port PORT]
"""

from __future__ import annotations

import argparse
import sys
from dash import Dash

from aladeen.ui.layout import build_layout, register_callbacks


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
    app.layout = build_layout()
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
