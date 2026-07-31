"""Local static + bridge HTTP server for the web UI.

Serves the static frontend in ``webui/`` and a single JSON endpoint,
``POST /bridge`` ``{ "method": <name>, "args": [...] }``, that invokes
the matching :class:`PipPalBridge` method.

Two consumers:

* the desktop app, when pywebview can't inject ``js_api`` (and as the
  document host for ``webview.create_window(url=...)``);
* the Playwright E2E suite, which points a real browser at this server
  and drives the real DOM against the real backend.

Bound to 127.0.0.1 only. Method names are matched against an explicit
allow-list (public bridge methods, no dunders) so a crafted request
can't reach arbitrary attributes.
"""

from __future__ import annotations

import json
import sys
import threading
from email.message import Message
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .bridge import PipPalBridge


def _resolve_webui_dir() -> Path:
    """Locate the static ``webui/`` directory.

    In a source/editable checkout this is the repo root's ``webui/``
    (``pippal/web_ui/server.py`` -> ``parents[3]``). In a frozen
    PyInstaller onedir bundle the tree is shipped at
    ``<sys._MEIPASS>/webui`` (see ``packaging/pippal.spec`` datas),
    so prefer that location when frozen.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "webui"
        if (frozen / "index.html").exists():
            return frozen
    return Path(__file__).resolve().parents[3] / "webui"


WEBUI_DIR = _resolve_webui_dir()


def _public_methods(bridge: PipPalBridge) -> set[str]:
    return {
        name for name in dir(bridge) if not name.startswith("_") and callable(getattr(bridge, name))
    }


def _is_json_content_type(value: str) -> bool:
    """Return whether *value* is a valid application/json media type."""
    message = Message(policy=default)
    message["Content-Type"] = value
    parsed = message["Content-Type"]
    return (
        not parsed.defects
        and not value.rstrip().endswith(";")
        and parsed.maintype.casefold() == "application"
        and parsed.subtype.casefold() == "json"
    )


class _Handler(SimpleHTTPRequestHandler):
    bridge: PipPalBridge
    allowed: set[str]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEBUI_DIR), **kwargs)

    def log_message(self, *args: Any, **kw: Any) -> None:  # silence
        return

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _accepts_bridge_request(self) -> bool:
        port = self.server.server_address[1]
        authority = f"127.0.0.1:{port}"

        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] != authority:
            self.send_error(400)
            return False

        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] != f"http://{authority}"):
            self.send_error(403)
            return False
        fetch_sites = self.headers.get_all("Sec-Fetch-Site", [])
        if any(value.strip().casefold() == "cross-site" for value in fetch_sites):
            self.send_error(403)
            return False

        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) != 1 or not _is_json_content_type(content_types[0]):
            self.send_error(415)
            return False
        return True

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/bridge":
            self.send_error(404)
            return
        if not self._accepts_bridge_request():
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 2 * 1024 * 1024:
            self.send_error(413, "payload too large")
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_error(400, "bad JSON")
            return
        method = str(data.get("method", ""))
        args = data.get("args") or []
        if not isinstance(args, list):
            self._send_json({"__error__": "args must be a list"}, 400)
            return
        if method not in self.allowed:
            self._send_json({"__error__": f"unknown method: {method}"}, 404)
            return
        try:
            result = getattr(self.bridge, method)(*args)
        except Exception as exc:
            self._send_json({"__error__": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._send_json(result if result is not None else {"ok": True})

    def end_headers(self) -> None:
        # Local-only UI; keep responses uncached so the E2E run always
        # sees the current static assets.
        if self.path.endswith((".js", ".css", ".html")) or self.path in ("/", ""):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


def start_web_ui_server(
    bridge: PipPalBridge,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, int]:
    """Start the static + bridge server on a daemon thread.

    ``port=0`` lets the OS pick a free port (used by the desktop app and
    the E2E fixture). Returns ``(server, actual_port)``.
    """
    handler = type(
        "BoundHandler",
        (_Handler,),
        {"bridge": bridge, "allowed": _public_methods(bridge)},
    )
    srv = ThreadingHTTPServer((host, port), handler)
    actual_port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, actual_port
