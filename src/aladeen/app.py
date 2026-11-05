"""Application entry point.

Creates and configures the Dash application.
Run with:  python -m aladeen.app
"""

from __future__ import annotations

from dash import Dash

from aladeen.ui.layout import build_layout, register_callbacks


def create_app() -> Dash:
    """Build and return a configured Dash application instance.

    The app uses demo fixtures and does not require MT5 to be installed
    or running.
    """
    app = Dash(
        __name__,
        title="Aladeen / TopG",
        update_title="Loading…",
    )
    app.layout = build_layout()
    register_callbacks(app)
    return app


def main() -> None:
    """Run the development server on localhost."""
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=8050)


if __name__ == "__main__":
    main()
