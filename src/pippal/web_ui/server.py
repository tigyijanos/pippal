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
import re
import sys
import threading
import time
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

_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_MAX_BRIDGE_BODY_BYTES = 2 * 1024 * 1024
_BRIDGE_BODY_READ_TIMEOUT_SECONDS = 1.0


def _public_methods(bridge: PipPalBridge) -> set[str]:
    return {
        name for name in dir(bridge) if not name.startswith("_") and callable(getattr(bridge, name))
    }


def _is_json_content_type(value: str) -> bool:
    """Return whether *value* is a valid application/json media type."""
    quoted_value = r'"(?:[\t !#-\[\]-~\x80-\xff]|\\[\t -~\x80-\xff])*"'
    pattern = (
        rf"(?P<type>{_TOKEN})/(?P<subtype>{_TOKEN})"
        rf"(?:[ \t]*;[ \t]*{_TOKEN}=(?:{_TOKEN}|{quoted_value}))*"
    )
    parsed = re.fullmatch(pattern, value.strip(" \t"))
    return (
        parsed is not None
        and parsed["type"].casefold() == "application"
        and parsed["subtype"].casefold() == "json"
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

    def _bridge_rejection_status(self) -> int | None:
        port = self.server.server_address[1]
        authority = f"127.0.0.1:{port}"

        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].strip(" \t") != authority:
            return 400

        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0].strip(" \t") != f"http://{authority}"):
            return 403
        fetch_sites = self.headers.get_all("Sec-Fetch-Site", [])
        if any(value.strip().casefold() == "cross-site" for value in fetch_sites):
            return 403

        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) != 1 or not _is_json_content_type(content_types[0]):
            return 415
        return None

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/bridge":
            self.send_error(404)
            return
        rejection_status = self._bridge_rejection_status()
        # The email-based parser reports MIME-only defects for a bare
        # multipart Content-Type; that request still belongs to the exact 415
        # media-type path. Structural defects on an otherwise valid request,
        # or ignored header lines retained as payload, are ambiguous framing.
        if self.headers.get_payload() or (self.headers.defects and rejection_status != 415):
            self.close_connection = True
            self.send_error(400)
            return
        if self.headers.get_all("Transfer-Encoding", []):
            self.close_connection = True
            self.send_error(400)
            return
        content_lengths = self.headers.get_all("Content-Length", [])
        if len(content_lengths) != 1:
            self.close_connection = True
            self.send_error(400)
            return
        raw_length = content_lengths[0].strip(" \t")
        if re.fullmatch(r"[0-9]+", raw_length) is None:
            self.close_connection = True
            self.send_error(400)
            return
        normalized_length = raw_length.lstrip("0") or "0"
        max_length = str(_MAX_BRIDGE_BODY_BYTES)
        if len(normalized_length) > len(max_length) or (
            len(normalized_length) == len(max_length) and normalized_length > max_length
        ):
            self.close_connection = True
            self.send_error(413, "payload too large")
            return
        length = int(normalized_length)
        # A response followed by a close while POST bytes are still pending can
        # surface as a Windows socket reset. Read the validated, bounded body
        # without re-reading any bytes before emitting a guard rejection.
        previous_timeout = self.connection.gettimeout()
        deadline = time.monotonic() + _BRIDGE_BODY_READ_TIMEOUT_SECONDS
        body = bytearray()
        read_failed = False
        try:
            while len(body) < length:
                remaining_timeout = deadline - time.monotonic()
                if remaining_timeout <= 0:
                    read_failed = True
                    break
                self.connection.settimeout(remaining_timeout)
                try:
                    chunk = self.rfile.read1(min(length - len(body), 64 * 1024))
                except (OSError, ValueError):
                    read_failed = True
                    break
                if not chunk:
                    read_failed = True
                    break
                body.extend(chunk)
        finally:
            self.connection.settimeout(previous_timeout)
        if read_failed or len(body) != length:
            self.close_connection = True
            self.send_error(400, "bad JSON")
            return
        if rejection_status is not None:
            self.close_connection = True
            self.send_error(rejection_status)
            return
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
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
