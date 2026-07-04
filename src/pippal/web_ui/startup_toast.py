"""Startup tray notification — shows a brief "running in background" notice.

Displayed once at app launch, ~200 ms after the tray icon appears.  Uses
the existing pystray tray ``Icon`` to show a quiet OS balloon notification
(``icon.notify``).  This avoids spawning an intrusive floating webview
window and requires no additional dependencies (pystray is already a core
dep).

Set the environment variable ``PIPPAL_NO_STARTUP_NOTIFICATION=1`` to
suppress the notification entirely (useful for CI, headless environments).

Any exception inside the helper is silently swallowed so a missing tray
icon or platform limitation never crashes app startup.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from ..i18n import t

# Delay (ms) from tray-icon ready to notification appearing.
_DELAY_MS = 200


def _display_toast(icon: Any = None) -> None:
    """Fire the tray balloon notification if *icon* is available.

    Called from a background thread; any exception is intentionally allowed
    to propagate — the caller (``show_startup_toast``) wraps it in try/except.
    """
    if icon is None:
        return
    icon.notify(t("toast.startup.title"), "PipPal")


def show_startup_toast(icon: Any = None) -> None:
    """Schedule a one-shot startup notification.

    Safe to call on any thread.  Silently skipped when
    ``PIPPAL_NO_STARTUP_NOTIFICATION`` is set in the environment.
    If *icon* is a live pystray ``Icon``, shows a quiet tray balloon.
    If *icon* is ``None``, no-ops.
    Any display error is swallowed so it never crashes app launch.
    """
    if os.environ.get("PIPPAL_NO_STARTUP_NOTIFICATION"):
        return

    def _run() -> None:
        try:
            _display_toast(icon)
        except Exception:
            pass

    t = threading.Timer(_DELAY_MS / 1000.0, _run)
    t.daemon = True
    t.start()
