from __future__ import annotations

from email.parser import Parser
from http.client import HTTPMessage

import pytest

from pippal.web_ui.bridge_request_headers import has_invalid_http_headers


def _parse(raw: str) -> HTTPMessage:
    return Parser(_class=HTTPMessage).parsestr(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "From attacker\r\nHost: 127.0.0.1\r\n\r\n",
        "Host: 127.0.0.1\r\nFrom attacker\r\nX-After: value\r\n\r\n",
        " continuation\r\nHost: 127.0.0.1\r\n\r\n",
        "Bad@Name: value\r\n\r\n",
        "X-Test: one\r\n two\r\n\r\n",
        "X-Test: a\x00b\r\n\r\n",
        "Content-Type: application/json\r\nTransfer-Encoding : chunked\r\n\r\n",
    ],
)
def test_structurally_invalid_http_headers_are_rejected(raw: str) -> None:
    assert has_invalid_http_headers(_parse(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "Content-Type: multipart/form-data; boundary=foo\r\n\r\n",
        "Content-Type: message/rfc822\r\n\r\n",
        "X-Test: a\tb\r\n\r\n",
        "X-Test: a\x80b\r\n\r\n",
    ],
)
def test_mime_semantics_htab_and_obs_text_are_not_http_structure_errors(raw: str) -> None:
    assert not has_invalid_http_headers(_parse(raw))
