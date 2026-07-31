from __future__ import annotations

import json
from http.client import HTTPConnection
from typing import Any

import pytest

from pippal.web_ui.server import start_web_ui_server

# fmt: off
JSON = "application/json"


class RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []

    def mutate(self, *args: Any) -> dict[str, str]:
        self.calls.append(("mutate", list(args)))
        return {"result": "mutated"}

    def read_secret(self, *args: Any) -> dict[str, str]:
        self.calls.append(("read_secret", list(args)))
        return {"secret": "SECRET-MARKER"}


@pytest.fixture
def bridge_server():
    bridge = RecordingBridge()
    server, port = start_web_ui_server(bridge, port=0)  # type: ignore[arg-type]
    try:
        yield bridge, port
    finally:
        server.shutdown()
        server.server_close()


def _authority(port: int) -> str:
    return f"127.0.0.1:{port}"


def _valid_headers(port: int) -> list[tuple[str, str]]:
    return [("Host", _authority(port)), ("Content-Type", JSON)]


def _request(port: int, headers: list[tuple[str, str]], *, bridge_method: str = "mutate", body: bytes | None = None, http_method: str = "POST") -> tuple[int, list[tuple[str, str]], bytes]:
    payload = body if body is not None else json.dumps({"method": bridge_method, "args": ["value"]}).encode()
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    connection.putrequest(http_method, "/bridge", skip_host=True)
    for name, value in headers:
        connection.putheader(name, value)
    if not any(name.lower() == "content-length" for name, _ in headers):
        connection.putheader("Content-Length", str(len(payload)))
    connection.endheaders(payload)
    response = connection.getresponse()
    result = response.status, response.getheaders(), response.read()
    connection.close()
    return result


def _assert_rejected(bridge_server, status: int, headers: list[tuple[str, str]], *, method="mutate") -> bytes:
    bridge, port = bridge_server
    bridge.calls.clear()
    actual, _, body = _request(port, headers, bridge_method=method)
    assert actual == status
    assert bridge.calls == []
    return body


def test_bridge_rejects_missing_host_without_dispatch(bridge_server):
    _assert_rejected(bridge_server, 400, [("Content-Type", JSON)])


@pytest.mark.parametrize("values", [["exact", "bad"], ["bad", "exact"], ["exact", "exact"]])
def test_bridge_rejects_duplicate_host_without_dispatch(bridge_server, values):
    _, port = bridge_server
    hosts = [("Host", _authority(port) if value == "exact" else "evil.test") for value in values]
    _assert_rejected(bridge_server, 400, [*hosts, ("Content-Type", JSON)])


@pytest.mark.parametrize("host", ["localhost:{port}", "127.0.0.1:1", "127.0.0.1", "evil.test:{port}"])
def test_bridge_rejects_noncanonical_host_without_dispatch(bridge_server, host):
    _, port = bridge_server
    _assert_rejected(bridge_server, 400, [("Host", host.format(port=port)), ("Content-Type", JSON)])


@pytest.mark.parametrize("host", ["127.0.0.1:{port}, evil.test", "user@127.0.0.1:{port}"])
def test_bridge_rejects_malformed_host_without_dispatch(bridge_server, host):
    _, port = bridge_server
    _assert_rejected(bridge_server, 400, [("Host", host.format(port=port)), ("Content-Type", JSON)])


def test_bridge_rejects_null_origin_without_dispatch(bridge_server):
    _, port = bridge_server
    _assert_rejected(bridge_server, 403, [*_valid_headers(port), ("Origin", "null")])


@pytest.mark.parametrize("origin", ["https://127.0.0.1:{port}", "http://evil.test", "http://127.0.0.1:1"])
def test_bridge_rejects_cross_origin_without_dispatch(bridge_server, origin):
    _, port = bridge_server
    _assert_rejected(bridge_server, 403, [*_valid_headers(port), ("Origin", origin.format(port=port))])


@pytest.mark.parametrize("origin", ["http://127.0.0.1:{port}/", "http://127.0.0.1:{port}, http://evil.test"])
def test_bridge_rejects_malformed_origin_without_dispatch(bridge_server, origin):
    _, port = bridge_server
    _assert_rejected(bridge_server, 403, [*_valid_headers(port), ("Origin", origin.format(port=port))])


@pytest.mark.parametrize("values", [["exact", "bad"], ["bad", "exact"], ["exact", "exact"]])
def test_bridge_rejects_duplicate_origin_without_dispatch(bridge_server, values):
    _, port = bridge_server
    origins = [("Origin", f"http://{_authority(port)}" if value == "exact" else "http://evil.test") for value in values]
    _assert_rejected(bridge_server, 403, [*_valid_headers(port), *origins])


@pytest.mark.parametrize("include_origin", [False, True])
def test_bridge_rejects_cross_site_fetch_metadata_without_dispatch(bridge_server, include_origin):
    _, port = bridge_server
    headers = _valid_headers(port)
    if include_origin:
        headers.append(("Origin", f"http://{_authority(port)}"))
    headers.append(("Sec-Fetch-Site", "cross-site"))
    _assert_rejected(bridge_server, 403, headers)


def test_bridge_rejects_missing_content_type_without_dispatch(bridge_server):
    _, port = bridge_server
    _assert_rejected(bridge_server, 415, [("Host", _authority(port))])


@pytest.mark.parametrize("media_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "application/octet-stream"])
def test_bridge_rejects_non_json_content_types_without_dispatch(bridge_server, media_type):
    _, port = bridge_server
    _assert_rejected(bridge_server, 415, [("Host", _authority(port)), ("Content-Type", media_type)])


def test_bridge_rejects_malformed_content_type_without_dispatch(bridge_server):
    _, port = bridge_server
    _assert_rejected(bridge_server, 415, [("Host", _authority(port)), ("Content-Type", "application/json, text/plain")])


@pytest.mark.parametrize("values", [[JSON, "text/plain"], ["text/plain", JSON], [JSON, JSON]])
def test_bridge_rejects_duplicate_content_type_without_dispatch(bridge_server, values):
    _, port = bridge_server
    _assert_rejected(bridge_server, 415, [("Host", _authority(port)), *(("Content-Type", value) for value in values)])


def test_wrong_host_cannot_read_bridge_result(bridge_server):
    body = _assert_rejected(bridge_server, 400, [("Host", "evil.test"), ("Content-Type", JSON)], method="read_secret")
    assert b"SECRET-MARKER" not in body


def test_hostile_origin_cannot_read_bridge_result(bridge_server):
    _, port = bridge_server
    body = _assert_rejected(bridge_server, 403, [*_valid_headers(port), ("Origin", "http://evil.test")], method="read_secret")
    assert b"SECRET-MARKER" not in body


def test_bridge_accepts_same_origin_json_and_dispatches(bridge_server):
    bridge, port = bridge_server
    status, _, body = _request(port, [*_valid_headers(port), ("Origin", f"http://{_authority(port)}"), ("Sec-Fetch-Site", "same-origin")])
    assert (status, json.loads(body), bridge.calls) == (200, {"result": "mutated"}, [("mutate", ["value"])])


def test_bridge_accepts_no_origin_json_native_helper_and_dispatches(bridge_server):
    bridge, port = bridge_server
    status, _, body = _request(port, _valid_headers(port))
    assert (status, json.loads(body), bridge.calls) == (200, {"result": "mutated"}, [("mutate", ["value"])])


def test_bridge_accepts_json_charset_parameter_and_dispatches(bridge_server):
    bridge, port = bridge_server
    status, _, _ = _request(port, [("Host", _authority(port)), ("Content-Type", "application/json; charset=utf-8")])
    assert (status, bridge.calls) == (200, [("mutate", ["value"])])


def test_bridge_responses_never_emit_acao(bridge_server):
    _, port = bridge_server
    cases = [_valid_headers(port), [("Host", "evil.test"), ("Content-Type", JSON)], [*_valid_headers(port), ("Origin", "null")], [("Host", _authority(port)), ("Content-Type", "text/plain")]]
    for headers in cases:
        _, response_headers, _ = _request(port, headers)
        assert all(name.lower() != "access-control-allow-origin" for name, _ in response_headers)


def test_bridge_options_does_not_enable_cors(bridge_server):
    bridge, port = bridge_server
    status, headers, _ = _request(port, [*_valid_headers(port), ("Origin", f"http://{_authority(port)}"), ("Access-Control-Request-Method", "POST")], http_method="OPTIONS")
    assert status // 100 != 2
    assert all(name.lower() != "access-control-allow-origin" for name, _ in headers)
    assert bridge.calls == []


@pytest.mark.parametrize("body,extra_headers,status", [(b'{"method":"unknown","args":[]}', [], 404), (b'{"method":"mutate","args":{"x":1}}', [], 400), (b"not-json", [], 400), (b"{}", [("Content-Length", str(2 * 1024 * 1024 + 1))], 413)])
def test_bridge_preserves_existing_post_policy_errors(bridge_server, body, extra_headers, status):
    bridge, port = bridge_server
    actual, _, _ = _request(port, [*_valid_headers(port), *extra_headers], body=body)
    assert actual == status
    assert bridge.calls == []
