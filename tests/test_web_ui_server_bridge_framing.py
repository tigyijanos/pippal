from __future__ import annotations

import json
import socket
import time
from http.client import HTTPConnection

import pytest

from tests.test_web_ui_server_bridge_drain import MAX_BODY_BYTES
from tests.test_web_ui_server_bridge_drain import tracked_server as tracked_server


def _request(
    port: int,
    headers: list[tuple[str, str]],
    body: bytes | None,
) -> tuple[int, dict[str, str]]:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    connection.putrequest("POST", "/bridge", skip_host=True)
    for name, value in headers:
        connection.putheader(name, value)
    connection.endheaders(body)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders())
    response.read()
    connection.close()
    return result


def _valid_headers(port: int, length: str) -> list[tuple[str, str]]:
    return [
        ("Host", f"127.0.0.1:{port}"),
        ("Content-Type", "application/json"),
        ("Content-Length", length),
    ]


@pytest.mark.parametrize("transfer_encoding", ["chunked", "identity", "gzip, chunked", ""])
def test_bridge_rejects_any_transfer_encoding_without_read_or_dispatch(
    tracked_server,
    transfer_encoding: str,
) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    status, headers = _request(
        port,
        [*_valid_headers(port, str(len(body))), ("Transfer-Encoding", transfer_encoding)],
        body,
    )

    assert status == 400
    assert headers["Connection"].casefold() == "close"
    assert server.error_observations[-1] == (400, 0, [])  # type: ignore[attr-defined]
    assert server.read_observations[-1] == (0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


def test_partial_hostile_bridge_body_has_bounded_server_read(tracked_server) -> None:
    bridge, server, port = tracked_server
    declared_length = 1024
    request = (
        f"POST /bridge HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Origin: http://evil.test\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {declared_length}\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + b'{"method":'

    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.settimeout(3)
    started = time.monotonic()
    try:
        client.sendall(request)
        try:
            response = client.recv(4096)
        except TimeoutError:
            pytest.fail("bridge handler did not bound its partial-body read")
    finally:
        elapsed = time.monotonic() - started
        client.close()

    assert elapsed < 3
    assert response.startswith(b"HTTP/1.0 400 ")
    assert server.error_observations[-1][0] == 400  # type: ignore[attr-defined]
    assert bridge.calls == []


def test_very_large_decimal_content_length_is_413_without_reading(tracked_server) -> None:
    bridge, server, port = tracked_server
    huge_length = "1" + ("0" * 4_999)
    status, _ = _request(port, _valid_headers(port, huge_length), None)

    assert status == 413
    assert server.error_observations[-1] == (413, 0, [])  # type: ignore[attr-defined]
    assert server.read_observations[-1] == (0, [])  # type: ignore[attr-defined]
    assert bridge.calls == []


def test_long_zero_padded_content_length_remains_valid(tracked_server) -> None:
    bridge, server, port = tracked_server
    body = json.dumps({"method": "mutate", "args": ["value"]}).encode()
    padded_length = ("0" * 5_000) + str(len(body))
    status, _ = _request(port, _valid_headers(port, padded_length), body)

    assert status == 200
    assert server.read_observations[-1] == (len(body), [len(body)])  # type: ignore[attr-defined]
    assert bridge.calls == [["value"]]


def test_deeply_nested_json_returns_400_without_dispatch(tracked_server) -> None:
    bridge, server, port = tracked_server
    body = (b"[" * 20_000) + (b"]" * 20_000)
    assert len(body) < MAX_BODY_BYTES

    status, _ = _request(port, _valid_headers(port, str(len(body))), body)

    assert status == 400
    assert server.error_observations[-1] == (400, len(body), [len(body)])  # type: ignore[attr-defined]
    assert bridge.calls == []
