from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from pippal.web_ui.server import _Handler

MAX_BODY_BYTES = 2 * 1024 * 1024


class _Bridge:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def mutate(self, *args: Any) -> dict[str, bool]:
        self.calls.append(list(args))
        return {"ok": True}


class _ReadTracker:
    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self.calls: list[int] = []
        self.methods: list[str] = []
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self.calls.append(len(data))
        self.methods.append("read")
        self.bytes_read += len(data)
        return data

    def read1(self, size: int = -1) -> bytes:
        data = self._stream.read1(size)
        self.calls.append(len(data))
        self.methods.append("read1")
        self.bytes_read += len(data)
        return data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _TrackingHandler(_Handler):
    def do_POST(self) -> None:
        tracker = _ReadTracker(self.rfile)
        self.rfile = tracker
        try:
            super().do_POST()
        finally:
            self.server.read_observations.append((tracker.bytes_read, tracker.calls))  # type: ignore[attr-defined]
            self.server.read_methods.append(tracker.methods)  # type: ignore[attr-defined]

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        tracker = self.rfile
        self.server.error_observations.append(  # type: ignore[attr-defined]
            (code, tracker.bytes_read, list(tracker.calls))
        )
        super().send_error(code, message, explain)


@pytest.fixture
def tracked_server():
    bridge = _Bridge()
    handler = type(
        "BoundTrackingHandler",
        (_TrackingHandler,),
        {"bridge": bridge, "allowed": {"mutate"}},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.error_observations = []  # type: ignore[attr-defined]
    server.read_observations = []  # type: ignore[attr-defined]
    server.read_methods = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield bridge, server, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(
    port: int,
    headers: list[tuple[str, str]],
    body: bytes | None,
) -> int:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    connection.putrequest("POST", "/bridge", skip_host=True)
    for name, value in headers:
        connection.putheader(name, value)
    connection.endheaders(body)
    response = connection.getresponse()
    status = response.status
    response.read()
    connection.close()
    return status


@pytest.mark.parametrize(
    "guard,expected_status", [("host", 400), ("origin", 403), ("fetch", 403), ("content-type", 415)]
)
def test_rejected_bridge_body_is_consumed_before_error_emission(
    tracked_server,
    guard: str,
    expected_status: int,
) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    headers = [
        ("Host", f"127.0.0.1:{port}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if guard == "host":
        headers[0] = ("Host", "evil.test")
    elif guard == "origin":
        headers.append(("Origin", "http://evil.test"))
    elif guard == "fetch":
        headers.append(("Sec-Fetch-Site", "cross-site"))
    else:
        headers[1] = ("Content-Type", "text/plain")

    assert _request(port, headers, body) == expected_status
    assert server.error_observations[-1] == (expected_status, len(body), [len(body)])  # type: ignore[attr-defined]
    assert bridge.calls == []


@pytest.mark.parametrize(
    "length_headers",
    [
        [],
        [("Content-Length", "1"), ("Content-Length", "1")],
        [("Content-Length", "nope")],
        [("Content-Length", "-1")],
    ],
)
def test_bridge_rejects_invalid_content_length_without_reading(
    tracked_server,
    length_headers: list[tuple[str, str]],
) -> None:
    bridge, server, port = tracked_server
    headers = [("Host", f"127.0.0.1:{port}"), ("Content-Type", "application/json"), *length_headers]
    assert _request(port, headers, None) == 400
    assert server.error_observations[-1] == (400, 0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


def test_oversized_header_only_bridge_request_returns_413_without_reading(tracked_server) -> None:
    bridge, server, port = tracked_server
    headers = [
        ("Host", f"127.0.0.1:{port}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(MAX_BODY_BYTES + 1)),
    ]
    assert _request(port, headers, None) == 413
    assert server.error_observations[-1] == (413, 0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


def test_accepted_bridge_body_is_read_once_and_dispatched_from_buffer(tracked_server) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    headers = [
        ("Host", f"127.0.0.1:{port}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    assert _request(port, headers, body) == 200
    assert server.read_observations[-1] == (len(body), [len(body)])  # type: ignore[attr-defined]
    assert server.read_methods[-1] == ["read1"]  # type: ignore[attr-defined]
    assert bridge.calls == [["value"]]
