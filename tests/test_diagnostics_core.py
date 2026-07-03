"""Additional core-specific diagnostics tests.

Covers:
- collect_logs_zip round-trip
- set_diag_level / list_log_files / delete_logs round-trip
- File retention (naming: pippal-YYYY-MM-DD.log, no 'pro')
- Core has no network upload (static assertion via import check)
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pytest


def _purge_diag_handlers() -> None:
    from pippal.diagnostics import _HANDLER_MARKER

    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _HANDLER_MARKER, False):
            root.removeHandler(h)
            h.close()


@pytest.fixture(autouse=True)
def _isolated_diag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import pippal.diagnostics as diag_mod

    diag_dir = tmp_path / "diagnostics"
    diag_dir.mkdir()
    monkeypatch.setattr(diag_mod, "DIAG_DIR", diag_dir)
    diag_mod._current_level = "off"
    _purge_diag_handlers()
    yield diag_dir
    diag_mod._current_level = "off"
    _purge_diag_handlers()


def test_collect_logs_zip_contains_core_log(_isolated_diag: Path) -> None:
    """collect_logs_zip() includes the log file and uses core naming."""
    from pippal.diagnostics import EVT_APP_START, collect_logs_zip, configure_diagnostics, event

    configure_diagnostics("trace")
    event(EVT_APP_START)

    zip_bytes = collect_logs_zip()
    assert len(zip_bytes) > 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()

    assert any(n.startswith("pippal-") and n.endswith(".log") for n in names)
    assert not any("pro" in n for n in names), (
        "Core zip must not include any 'pro' filenames."
    )


def test_collect_logs_zip_empty_when_no_logs(_isolated_diag: Path) -> None:
    from pippal.diagnostics import collect_logs_zip

    zip_bytes = collect_logs_zip()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        assert zf.namelist() == []


def test_set_diag_level_list_files_delete_round_trip(_isolated_diag: Path) -> None:
    """set_diag_level -> list_log_files -> delete_logs full round-trip."""
    from pippal.diagnostics import (
        EVT_DOC_IMPORT,
        configure_diagnostics,
        delete_logs,
        event,
        list_log_files,
    )

    # Start at off; no files
    assert list_log_files() == []

    # Activate trace and write an event
    configure_diagnostics("trace")
    event(EVT_DOC_IMPORT, char_count=42, ok=True)

    files = list_log_files()
    assert len(files) >= 1
    # Verify naming: core pattern pippal-YYYY-MM-DD.log
    for f in files:
        assert f.name.startswith("pippal-")
        assert f.name.endswith(".log")
        assert "pro" not in f.name

    # Delete all logs
    removed = delete_logs()
    assert removed == len(files)
    assert list_log_files() == []

    # After delete, level stays active but no files exist yet
    configure_diagnostics("off")
    assert list_log_files() == []


def test_log_path_for_naming() -> None:
    """log_path_for uses 'pippal-YYYY-MM-DD.log' (no 'pro')."""
    from pippal.diagnostics import log_path_for

    d = date(2026, 1, 15)
    p = log_path_for(d)
    assert p.name == "pippal-2026-01-15.log"
    assert "pro" not in p.name


def test_collect_logs_zip_tail_truncation(_isolated_diag: Path) -> None:
    """collect_logs_zip() caps each log file to the last 10 MB.

    Writes a synthetic log file that is 11 MB (1 MB over the cap).  The
    zip entry must contain ≤ 10 MB of content and must be the *tail* of
    the original data (i.e. include the final bytes).
    """
    from pippal.diagnostics import _LOG_UPLOAD_MAX_BYTES, collect_logs_zip

    # Build a fake log file: 11 MB of ASCII newline-terminated lines.
    one_mb = 1024 * 1024
    line = b"x" * 1023 + b"\n"  # 1024 bytes per line
    # Total: 11 MB = 11 * 1024 lines
    total_lines = (11 * one_mb) // len(line)
    raw = line * total_lines

    log_file = _isolated_diag / "pippal-2099-01-01.log"
    log_file.write_bytes(raw)

    zip_bytes = collect_logs_zip()
    assert len(zip_bytes) > 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "pippal-2099-01-01.log" in names
        entry = zf.read("pippal-2099-01-01.log")

    # Uploaded portion must not exceed the cap.
    assert len(entry) <= _LOG_UPLOAD_MAX_BYTES, (
        f"Uploaded entry is {len(entry)} bytes, expected ≤ {_LOG_UPLOAD_MAX_BYTES}"
    )
    # Must be the tail — the last byte of the original file must match.
    assert entry[-1:] == raw[-1:], "Uploaded content must end with the tail of the original log"
    # Must start on a clean newline boundary (no partial lines at the start).
    assert entry[:1] != b"x" or entry.startswith(line), (
        "Uploaded content must start at a newline boundary"
    )


def test_no_network_import_in_core_diagnostics_modules() -> None:
    """Core diagnostics modules must not import network/upload libraries.

    This is a static import check: importing the modules and verifying
    no non-stdlib network libraries are loaded as a side effect.
    ``urllib`` is stdlib and may be imported by pytest/pip itself — excluded.
    """
    import sys

    # Import the core diagnostics modules
    import pippal.diag_async
    import pippal.diag_core_bridge
    import pippal.diag_trace
    import pippal.diagnostics  # noqa: F401

    # Only check for non-stdlib HTTP/network packages that would indicate
    # upload code has leaked into core.
    upload_packages = {"requests", "httpx", "httpcore", "aiohttp", "boto3"}
    for mod_name in list(sys.modules):
        base = mod_name.split(".")[0]
        assert base not in upload_packages, (
            f"Core diagnostics imported upload/network package: {mod_name!r}"
        )
