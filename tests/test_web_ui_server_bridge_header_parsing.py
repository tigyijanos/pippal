from __future__ import annotations

import json
import socket

import pytest

from tests.test_web_ui_server_bridge_drain import _wait_for_request
from tests.test_web_ui_server_bridge_drain import tracked_server as tracked_server
from tests.test_web_ui_server_bridge_framing import _request, _valid_headers


@pytest.mark.parametrize("raw_header", [b"Bad@Name: value\r\n", b"X-Test: one\r\n two\r\n"])
def test_bridge_rejects_invalid_http_header_syntax_without_reading(
    tracked_server,
    raw_header: bytes,
) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    request = (
        (
            f"POST /bridge HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
        ).encode()
        + raw_header
        + b"Connection: close\r\n\r\n"
        + body
    )

    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.settimeout(3)
    try:
        client.sendall(request)
        response = client.recv(4096)
    finally:
        client.close()

    _wait_for_request(server)
    assert response.startswith(b"HTTP/1.0 400 ")
    assert server.error_observations[-1] == (400, 0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


@pytest.mark.parametrize(
    "browser_header",
    [
        ("Origin", "http://evil.test"),
        ("Sec-Fetch-Site", "cross-site"),
    ],
)
def test_rejected_browser_multipart_body_drains_before_403(
    tracked_server,
    browser_header: tuple[str, str],
) -> None:
    bridge, server, port = tracked_server
    body = b"--foo\r\nContent-Disposition: form-data; name=x\r\n\r\nvalue\r\n--foo--\r\n"
    headers = _valid_headers(port, str(len(body)))
    headers[1] = ("Content-Type", "multipart/form-data; boundary=foo")

    status, _ = _request(port, [*headers, browser_header], body)

    _wait_for_request(server)
    assert status == 403
    assert server.error_observations[-1] == (403, len(body), [len(body)])  # type: ignore[attr-defined]
    assert bridge.calls == []


def test_originless_message_rfc822_body_drains_before_415(tracked_server) -> None:
    bridge, server, port = tracked_server
    body = b"From: sender@example.test\r\nTo: reader@example.test\r\n\r\npayload"
    headers = _valid_headers(port, str(len(body)))
    headers[1] = ("Content-Type", "message/rfc822")

    status, _ = _request(port, headers, body)

    _wait_for_request(server)
    assert status == 415
    assert server.error_observations[-1] == (415, len(body), [len(body)])  # type: ignore[attr-defined]
    assert bridge.calls == []
