#!/usr/bin/env python3
"""Start Arize Phoenix observability server.

This script launches the Phoenix server on localhost:6006.
Phoenix provides a local-first observability platform for LLM applications.

Usage:
    python scripts/start_phoenix.py

    Or in background:
    python scripts/start_phoenix.py &

The server will be available at http://localhost:6006

Teaching note: Phoenix is used for local development (Articles 1-5).
In production (Article 6+), we migrate to LangFuse for:
- Hosted infrastructure
- User feedback loops
- Prompt versioning
- Team collaboration

Phoenix advantages for development:
- Zero configuration
- Runs locally (no data leaves your machine)
- Beautiful UI for trace visualization
- Free and open source
"""

import sys
import time
from importlib.util import find_spec
from pathlib import Path

# Add project root to path
# This is necessary to import from src/ when running as a script
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import get_settings  # noqa: E402


def check_phoenix_installed() -> bool:
    """Check if Phoenix is installed."""
    return find_spec("phoenix") is not None


def start_phoenix() -> None:
    """Start Phoenix server."""
    if not check_phoenix_installed():
        print("Error: Arize Phoenix not installed")
        print("Install with: uv add arize-phoenix")
        print("Or: pip install arize-phoenix")
        sys.exit(1)

    settings = get_settings()

    # Extract host and port from Phoenix URL
    # Format: http://localhost:6006
    url_parts = settings.phoenix_url.replace("http://", "").replace("https://", "")
    if ":" in url_parts:
        host, port = url_parts.split(":")
    else:
        host = url_parts
        port = "6006"

    print(f"Starting Phoenix server on {host}:{port}")
    print(f"Web UI: {settings.phoenix_url}")
    print(f"OTLP endpoint: {settings.phoenix_collector_endpoint}")
    print("\nPress Ctrl+C to stop\n")

    try:
        # Launch Phoenix
        # Phoenix can be launched programmatically
        import phoenix as px

        # Launch Phoenix server
        session = px.launch_app(host=host, port=int(port))

        if session:
            print(f"Phoenix server running at: {session.url}")
            print("\nKeep this terminal open to maintain the server...")
            print("Press Ctrl+C to stop")

            # Keep running
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n\nShutting down Phoenix server...")
                if hasattr(session, "close"):
                    session.close()
                print("Phoenix server stopped")
        else:
            print("Error: Failed to start Phoenix server")
            sys.exit(1)

    except Exception as e:
        print(f"Error starting Phoenix: {e}")
        sys.exit(1)


if __name__ == "__main__":
    start_phoenix()
