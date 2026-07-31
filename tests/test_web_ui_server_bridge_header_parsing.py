from __future__ import annotations

import json
import socket

import pytest

from tests.test_web_ui_server_bridge_drain import _wait_for_request
from tests.test_web_ui_server_bridge_drain import tracked_server as tracked_server
from tests.test_web_ui_server_bridge_framing import _request, _valid_headers


def _raw_bridge_request(
    port: int,
    body: bytes,
    *,
    first_header: bytes = b"",
    extra_header: bytes = b"",
) -> bytes:
    request = (
        b"POST /bridge HTTP/1.1\r\n"
        + first_header
        + (
            f"Host: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
        ).encode()
        + extra_header
        + b"Connection: close\r\n\r\n"
        + body
    )
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.settimeout(3)
    try:
        client.sendall(request)
        return client.recv(4096)
    finally:
        client.close()


@pytest.mark.parametrize("raw_header", [b"Bad@Name: value\r\n", b"X-Test: one\r\n two\r\n"])
def test_bridge_rejects_invalid_http_header_syntax_without_reading(
    tracked_server,
    raw_header: bytes,
) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    response = _raw_bridge_request(port, body, extra_header=raw_header)

    _wait_for_request(server)
    assert response.startswith(b"HTTP/1.0 400 ")
    assert server.error_observations[-1] == (400, 0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


@pytest.mark.parametrize("position", ["first", "middle"])
def test_bridge_rejects_envelope_header_lines_without_reading(
    tracked_server,
    position: str,
) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    envelope = b"From attacker\r\n"
    kwargs = {"first_header": envelope} if position == "first" else {"extra_header": envelope}

    response = _raw_bridge_request(port, body, **kwargs)

    _wait_for_request(server)
    assert response.startswith(b"HTTP/1.0 400 ")
    assert server.error_observations[-1] == (400, 0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


@pytest.mark.parametrize("control", [b"\x00", b"\x08", b"\x0b", b"\x7f"])
def test_bridge_rejects_forbidden_field_value_controls_without_reading(
    tracked_server,
    control: bytes,
) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    response = _raw_bridge_request(port, body, extra_header=b"X-Test: a" + control + b"b\r\n")

    _wait_for_request(server)
    assert response.startswith(b"HTTP/1.0 400 ")
    assert server.error_observations[-1] == (400, 0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


@pytest.mark.parametrize("allowed", [b"\t", b"\x80"])
def test_bridge_allows_htab_and_obs_text_in_field_values(tracked_server, allowed: bytes) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    response = _raw_bridge_request(port, body, extra_header=b"X-Test: a" + allowed + b"b\r\n")

    _wait_for_request(server)
    assert response.startswith(b"HTTP/1.0 200 ")
    assert server.read_observations[-1] == (len(body), [len(body)])  # type: ignore[attr-defined]
    assert bridge.calls == [["value"]]


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
