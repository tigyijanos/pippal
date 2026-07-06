#!/usr/bin/env python3
"""Python-side user-facing-string *sink* detection for the i18n linter (T-208).

Split out of ``i18n_lint_lib.py`` purely to keep that file under the repo
line-count guard (the same reason the lib was split from ``i18n_lint.py``).

This module is pure regex + bracket bookkeeping: it answers "is the string
literal that starts at this line-prefix flowing into a user-facing Python
sink?" and nothing else. The prose / technical heuristics that decide whether
the *value* is real copy stay in the lib, so this file has no dependency on it
(and no import cycle).

Three Python sink classes are recognised, extending the JS text sinks:

``message``   — ``<expr>.show_message(<literal>)`` overlay copy (ai_runner /
                exporter / tray_items). The leading ``.`` keeps a bare
                ``def show_message(`` definition out of scope.
``passthrough`` — a bridge response-dict field (``"status"``/``"message"``/
                ``"error"``/``"detail"``/``"label"``/``"title"``/``"summary"``)
                OR a ``raise <...Error/Exception>(...)`` whose text a bridge
                surfaces verbatim via ``str(exc)`` (e.g. document_export ->
                bridge_export). Scoped per-file by the caller, since the same
                dict keys are innocuous outside a bridge-surfaced return.

Multi-line calls (``show_message(\n    "...")`` and the ``raise X(\n    stage,\n
"...")`` form used in document_export) are handled by a small carried-context
pass that tracks which sink call is still open on each line via balanced
parentheses (string/comment contents blanked out first so inner punctuation
does not fool the counter).
"""

from __future__ import annotations

import re

# A string whose line-prefix ENDS with an open ``.show_message(`` call (``[^)]*``
# = the call has not closed again before the string).
_PY_SHOW_MESSAGE = re.compile(r"\.show_message\s*\([^)]*$")
# A bridge response-dict field: the prefix ends with ``"<field>":`` (plus an
# optional ``r``/``f`` string-prefix) right before the value literal.
_PY_DICT_FIELD = re.compile(
    r"""["'](?:status|message|error|detail|label|title|summary)["']\s*:\s*[rf]{0,2}$"""
)
# A still-open ``raise <SomethingError|Exception|Warning>(`` call: covers both
# the single-arg ``raise ValueError("prose")`` and the 2nd-arg
# ``raise DocumentExportError("stage", "prose")`` forms.
_PY_RAISE = re.compile(r"\braise\s+\w*(?:Error|Exception|Warning)\s*\([^)]*$")
# Openers for the multi-line carried-context pass.
_PY_SHOW_OPENER = re.compile(r"\.show_message\s*\(")
_PY_RAISE_OPENER = re.compile(r"\braise\s+\w*(?:Error|Exception|Warning)\s*\(")


def _strip_strings_and_comment(line: str) -> str:
    """Blank out string contents and a trailing ``#`` comment so that ``(``/``)``
    counting for the carried-context pass is not fooled by parentheses or quotes
    that live inside a literal."""
    out: list[str] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in "\"'":
            quote = c
            i += 1
            while i < n and line[i] != quote:
                if line[i] == "\\":
                    i += 2
                    continue
                i += 1
            i += 1  # skip the closing quote (or run past EOL for an open literal)
            continue
        if c == "#":
            break
        out.append(c)
        i += 1
    return "".join(out)


def carried_sinks(lines: list[str]) -> list[str]:
    """For each line index, the sink kind (``"show_message"``/``"raise"``/``""``)
    of a *multi-line* sink call opened on an earlier line and still open here.

    The opener line itself carries ``""`` (its own on-line string is matched by
    the prefix regexes); only the continuation lines carry the kind."""
    carried = [""] * len(lines)
    open_kind, depth = "", 0
    for idx, line in enumerate(lines):
        carried[idx] = open_kind
        bare = _strip_strings_and_comment(line)
        if open_kind:
            depth += bare.count("(") - bare.count(")")
            if depth <= 0:
                open_kind, depth = "", 0
            continue
        m = _PY_SHOW_OPENER.search(bare) or _PY_RAISE_OPENER.search(bare)
        if not m:
            continue
        tail = bare[m.start():]
        d = tail.count("(") - tail.count(")")
        if d > 0:
            open_kind = "show_message" if ".show_message" in m.group(0) else "raise"
            depth = d
    return carried


def classify(prefix: str, carried_kind: str, *, dict_scope: bool, raise_scope: bool) -> str:
    """Return the sink category (``"message"`` / ``"passthrough"`` / ``""``) for a
    string given its line-prefix and the multi-line ``carried_kind`` for its line.

    ``dict_scope`` / ``raise_scope`` are the caller's per-file gates: the dict
    and raise sinks only apply inside bridge-surfaced modules, where their text
    reaches the user; elsewhere the same shapes are internal and ignored."""
    if _PY_SHOW_MESSAGE.search(prefix):
        return "message"
    if raise_scope and _PY_RAISE.search(prefix):
        return "passthrough"
    if dict_scope and _PY_DICT_FIELD.search(prefix):
        return "passthrough"
    if prefix.strip() == "":
        if carried_kind == "show_message":
            return "message"
        if carried_kind == "raise" and raise_scope:
            return "passthrough"
    return ""
