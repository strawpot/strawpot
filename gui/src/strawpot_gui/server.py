"""Server launcher — single-instance check, uvicorn start, browser open."""

import json
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import click
import uvicorn

DEFAULT_PORT = 8741
DEFAULT_HOST = "127.0.0.1"


def _port_in_use(host: str, port: int) -> bool:
    """Check if a port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _is_strawpot_gui(host: str, port: int) -> bool:
    """Check if the existing listener is a StrawPot GUI instance."""
    try:
        url = f"http://{host}:{port}/api/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def main(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> None:
    """Entry point for ``strawpot-gui`` and ``strawpot gui``."""
    if _port_in_use(host, port):
        if _is_strawpot_gui(host, port):
            url = f"http://{host}:{port}"
            click.echo(f"StrawPot GUI already running at {url}")
            webbrowser.open(url)
            return
        else:
            click.echo(
                f"Error: port {port} is already in use by another process.",
                err=True,
            )
            sys.exit(1)

    url = f"http://{host}:{port}"
    click.echo(f"Starting StrawPot GUI at {url}")

    def _open_when_ready() -> None:
        """Poll the health endpoint, then open the browser."""
        for _ in range(30):
            time.sleep(0.5)
            if _is_strawpot_gui(host, port):
                webbrowser.open(url)
                return

    threading.Thread(target=_open_when_ready, daemon=True).start()

    from strawpot_gui.app import create_app

    app = create_app(host=host, port=port)
    uvicorn.run(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=5)
