"""PipPal — Diagnostics / Logging backend (core, no upload).

Privacy-safe structured logging. Text content NEVER appears in logs.
Two privacy layers: whitelist-only API (metadata keys only) and a
RedactingFilter that drops message bodies for non-diag records.
File I/O is off the hot path via a background QueueListener thread.
Log files: ``pippal-YYYY-MM-DD.log`` under DIAG_DIR.
"""

from __future__ import annotations

import io
import logging
import re
import traceback
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from .diag_async import AsyncDiagTransport, DailyFileHandler, JSONLFormatter
from .diag_async import log_path_for as _log_path_for
from .diag_core_bridge import core_record_payload
from .paths import DATA_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DIAG_DIR: Path = DATA_ROOT / "diagnostics"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DIAG_LEVELS = ("off", "error", "trace")
DIAG_RETENTION_DAYS: int = 14
DIAG_MAX_TOTAL_BYTES: int = 20 * 1024 * 1024  # 20 MB

# ---------------------------------------------------------------------------
# Event-name constants
# ---------------------------------------------------------------------------

EVT_DOC_IMPORT = "document.import"
EVT_SYNTH_START = "synth.start"
EVT_SYNTH_STOP = "synth.stop"
EVT_PLAYBACK_CHUNK = "playback.chunk"
EVT_EXPORT = "export"
EVT_APP_START = "app.start"
EVT_APP_EXIT = "app.exit"
EVT_DOC_IMPORT_ERROR = "document.import.error"
EVT_AI_ACTION_ERROR = "ai.action.error"
EVT_AI_ACTION = "ai.action"
EVT_OLLAMA_REQUEST = "ollama.request"
EVT_JS = "js"

# ---------------------------------------------------------------------------
# Whitelist (THE privacy guard — Layer 1)
# ---------------------------------------------------------------------------

ALLOWED_META_KEYS: frozenset[str] = frozenset(
    {
        "char_count",
        "byte_size",
        "word_count",
        "page_count",
        "section_count",
        "duration_ms",
        "queue_size",
        "item_count",
        "retry_count",
        "chunk_index",
        "chunk_total",
        "http_status",
        "src_format",
        "encoding",
        "engine",
        "voice_lang",
        "action",
        "error_type",
        "stage",
        "ok",
        "cancelled",
        "sample_rate",
        "model_present",
        # bridge-call / lifecycle instrumentation (metadata-only)
        "method",
        "phase",
        "surface",
        # JS-side diagnostics
        "detail",
        # Session-start system metadata
        "os_platform", "python_version",
        "pippal_version", "pywebview_version",
    }
)

# Keys in this set may carry a str value, but ONLY if it matches
# _ENUM_VALUE_RE and is <= 64 chars.
ENUM_STRING_KEYS: frozenset[str] = frozenset(
    {"src_format", "encoding", "engine", "voice_lang", "action", "error_type", "stage"}
)

# Safe-value regex for enum strings: no spaces, no underscores, no free text.
_ENUM_VALUE_RE = re.compile(r"^[A-Za-z0-9.:+\-]{1,64}$")

# Keys whose value is a CODE IDENTIFIER (method name, lifecycle phase, version string).
IDENTIFIER_STRING_KEYS: frozenset[str] = frozenset({
    "method", "phase", "surface", "detail",
    "os_platform", "python_version",
    "pippal_version", "pywebview_version",
})
_IDENTIFIER_VALUE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# Regex for valid event names
_EVENT_NAME_RE = re.compile(r"^[A-Za-z0-9._:+\-]{1,64}$")

_NUMERIC_TYPES = (int, float, bool)

_DIAG_LOGGER_NAME = "pippal.diagnostics"
_DIAG_LOGGER = logging.getLogger(_DIAG_LOGGER_NAME)

# Sentinel attribute set on LogRecords that came through diag.event.
_DIAG_FIELDS_ATTR = "diag_fields"

# Marker attached to our file handler so we can find/remove it.
_HANDLER_MARKER = "_pippal_diag_handler"

_JSONLFormatter = JSONLFormatter


def log_path_for(day: date) -> Path:
    """Return the log file path for the given UTC date (under DIAG_DIR)."""
    return _log_path_for(DIAG_DIR, day)


# ---------------------------------------------------------------------------
# RedactingFilter — Layer 2 privacy guard
# ---------------------------------------------------------------------------


class RedactingFilter(logging.Filter):
    """Passes all records through; redaction happens in DailyFileHandler.emit() on a copy."""

    def filter(self, record: logging.LogRecord) -> bool:
        return True


def _make_redacted_copy(record: logging.LogRecord) -> logging.LogRecord:
    """Return a shallow copy of *record* with message body scrubbed.

    Called in DailyFileHandler.emit() so the original LogRecord is never
    modified and other handlers still see the real message.
    """
    import copy

    rec = copy.copy(record)

    if hasattr(rec, _DIAG_FIELDS_ATTR):
        return rec

    core_payload = core_record_payload(
        rec,
        allowed_keys=ALLOWED_META_KEYS,
        event_name_re=_EVENT_NAME_RE,
        build_payload=_build_diag_payload,
    )
    if core_payload is not None:
        setattr(rec, _DIAG_FIELDS_ATTR, core_payload)
        rec.msg = ""
        rec.args = ()
        rec.exc_info = None
        rec.exc_text = None
        return rec

    rec.msg = ""
    rec.args = ()
    rec.exc_info = None
    rec.exc_text = None
    return rec


# ---------------------------------------------------------------------------
# Per-day file handler factory
# ---------------------------------------------------------------------------


def _DailyFileHandler(level: int = logging.NOTSET) -> DailyFileHandler:
    """Build the listener-owned daily file handler with injected deps."""
    return DailyFileHandler(
        diag_dir_getter=lambda: DIAG_DIR,
        redactor=_make_redacted_copy,
        fields_attr=_DIAG_FIELDS_ATTR,
        retention_days=DIAG_RETENTION_DAYS,
        max_total_bytes=DIAG_MAX_TOTAL_BYTES,
        level=level,
    )


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_current_level: str = "off"

_transport: AsyncDiagTransport = AsyncDiagTransport()


def current_level() -> str:
    """Return the currently active diagnostics level."""
    return _current_level


def flush() -> None:
    """Block until all queued diagnostics records are written to disk."""
    _transport.flush()


# ---------------------------------------------------------------------------
# configure_diagnostics — idempotent (re)configuration
# ---------------------------------------------------------------------------


def configure_diagnostics(level: str) -> None:
    """Install or remove the core diagnostics file handler.

    Idempotent: tears down existing transport then installs a fresh one
    if level != "off". Never creates duplicate handlers.
    """
    global _current_level

    if level not in DIAG_LEVELS:
        level = "off"
    prev_level = _current_level
    _current_level = level

    root = logging.getLogger()

    _remove_diag_handlers(root)

    if level == "off":
        return

    log_level = logging.ERROR if level == "error" else logging.DEBUG

    handler = _DailyFileHandler(level=log_level)
    handler.addFilter(RedactingFilter())
    setattr(handler, _HANDLER_MARKER, True)

    _transport.start(handler, root=root)

    qh = _transport.root_handler
    if qh is not None:
        setattr(qh, _HANDLER_MARKER, True)

    if root.level == logging.NOTSET or root.level > log_level:
        root.setLevel(log_level)

    # Only on a real off->on transition.
    if prev_level == "off":
        emit_session_start()


def _remove_diag_handlers(logger: logging.Logger) -> None:
    """Stop the async transport and remove any installed diag handlers."""
    if _transport.running:
        _transport.stop(root=logger)
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


# ---------------------------------------------------------------------------
# Structured event API — THE privacy guard (Layer 1)
# ---------------------------------------------------------------------------


def _build_diag_payload(
    name: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Validate and whitelist fields; return the safe payload dict."""
    payload: dict[str, Any] = {}
    dropped: list[str] = []

    for key, value in fields.items():
        if key not in ALLOWED_META_KEYS:
            dropped.append(key)
            continue

        if key in ENUM_STRING_KEYS:
            if not isinstance(value, str):
                dropped.append(key)
                continue
            if not _ENUM_VALUE_RE.match(value):
                dropped.append(key)
                continue
            payload[key] = value
        elif key in IDENTIFIER_STRING_KEYS:
            if not isinstance(value, str):
                dropped.append(key)
                continue
            if not _IDENTIFIER_VALUE_RE.match(value):
                dropped.append(key)
                continue
            payload[key] = value
        elif isinstance(value, _NUMERIC_TYPES):
            payload[key] = value
        else:
            dropped.append(key)

    result: dict[str, Any] = {"evt": name}
    result.update(payload)
    if dropped:
        result["_dropped"] = dropped
    return result


def event(name: str, **fields: Any) -> None:
    """Log a metadata-only structured diagnostic event.

    Only whitelisted scalar metadata is written; any free-form text or
    unknown key is silently dropped.  No-op when diagnostics level is "off".
    """
    if _current_level == "off":
        return

    if not _EVENT_NAME_RE.match(name):
        return

    payload = _build_diag_payload(name, fields)

    record = _DIAG_LOGGER.makeRecord(
        name=_DIAG_LOGGER_NAME,
        level=logging.DEBUG,
        fn="",
        lno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    setattr(record, _DIAG_FIELDS_ATTR, payload)
    _DIAG_LOGGER.handle(record)
    _transport.flush()


def emit_session_start() -> None:
    """Emit app.start with OS/Python/version metadata. No-op when level="off"."""
    if _current_level == "off":
        return
    import platform as _platform
    import sys as _sys

    meta: dict[str, Any] = {}
    try:
        meta["os_platform"] = _platform.platform()[:64]
    except Exception:
        pass
    try:
        meta["python_version"] = _sys.version.split()[0][:64]
    except Exception:
        pass
    from importlib.metadata import version as _iv
    for _p, _k in (
        ("pippal", "pippal_version"),
        ("pywebview", "pywebview_version"),
    ):
        try:
            meta[_k] = _iv(_p)[:64]
        except Exception:
            pass
    event(EVT_APP_START, **meta)


def error_event(
    name: str,
    exc: BaseException | None = None,
    **fields: Any,
) -> None:
    """Log a metadata-only error event at ERROR level.

    Like event() but adds safe traceback frames (file:lineno:func only);
    exception message replaced with "<redacted>" to prevent content leaks.
    No-op when level is "off".
    """
    if _current_level == "off":
        return

    if not _EVENT_NAME_RE.match(name):
        return

    payload = _build_diag_payload(name, fields)

    if exc is not None:
        payload["error_type"] = type(exc).__name__
        tb = exc.__traceback__
        if tb is not None:
            frames = traceback.extract_tb(tb)
            payload["frames"] = [
                f"{frame.filename}:{frame.lineno}:{frame.name}" for frame in frames
            ]
        payload["exc_msg"] = "<redacted>"

    record = _DIAG_LOGGER.makeRecord(
        name=_DIAG_LOGGER_NAME,
        level=logging.ERROR,
        fn="",
        lno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    setattr(record, _DIAG_FIELDS_ATTR, payload)
    _DIAG_LOGGER.handle(record)
    _transport.flush()


# ---------------------------------------------------------------------------
# Maintenance utilities
# ---------------------------------------------------------------------------


def list_log_files() -> list[Path]:
    """Return all diagnostics log files, sorted oldest first."""
    if not DIAG_DIR.exists():
        return []
    return sorted(DIAG_DIR.glob("pippal-*.log"), key=lambda p: p.name)


def delete_logs() -> int:
    """Delete all diagnostics log files.  Returns the count removed."""
    files = list_log_files()
    removed = 0
    for f in files:
        try:
            f.unlink(missing_ok=True)
            removed += 1
        except OSError:
            pass
    return removed


# Maximum bytes taken from the *tail* of each log file when building the
# upload zip.  Keeps the payload bounded even after long sessions.
_LOG_UPLOAD_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB per file


def collect_logs_zip() -> bytes:
    """Return an in-memory zip of all current JSONL log files.

    Each file is capped to its last ``_LOG_UPLOAD_MAX_BYTES`` (10 MB).
    When a file exceeds the cap the tail is trimmed to the next newline
    boundary so no partial JSONL record is included.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in list_log_files():
            data = f.read_bytes()
            if len(data) > _LOG_UPLOAD_MAX_BYTES:
                # Take trailing 10 MB, then advance past the first (likely
                # partial) line so the zip starts on a clean record boundary.
                tail = data[-_LOG_UPLOAD_MAX_BYTES:]
                newline_pos = tail.find(b"\n")
                if newline_pos != -1:
                    tail = tail[newline_pos + 1 :]
                data = tail
            zf.writestr(f.name, data)
    return buf.getvalue()
