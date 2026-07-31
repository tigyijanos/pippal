from __future__ import annotations

import re
from email.errors import (
    FirstHeaderLineIsContinuationDefect,
    InvalidHeaderDefect,
    MisplacedEnvelopeHeaderDefect,
    MissingHeaderBodySeparatorDefect,
)
from http.client import HTTPMessage

HTTP_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_FORBIDDEN_FIELD_VALUE_CTL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_STRUCTURAL_DEFECTS = (
    FirstHeaderLineIsContinuationDefect,
    InvalidHeaderDefect,
    MisplacedEnvelopeHeaderDefect,
    MissingHeaderBodySeparatorDefect,
)


def has_invalid_http_headers(headers: HTTPMessage) -> bool:
    """Return whether parsed fields violate HTTP header syntax."""
    if headers.get_unixfrom() is not None:
        return True
    if any(isinstance(defect, _STRUCTURAL_DEFECTS) for defect in headers.defects):
        return True
    return any(
        re.fullmatch(HTTP_TOKEN, name) is None
        or _FORBIDDEN_FIELD_VALUE_CTL.search(value) is not None
        for name, value in headers.raw_items()
    )
