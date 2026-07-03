"""Web-frontend application composition — PipPal's only entry point.

Load config, build the real ``TTSEngine``, register the native global
hotkeys, build the native pystray tray — and host the **windows** as
pywebview (WebView2) windows serving the static UI in ``webui/``.

System tray + global hotkey are native: ``pystray`` and ``keyboard``.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any

import pystray

from .. import plugins
from ..command_server import (
    probe_running_instance,
    resolve_candidate_port,
    start_command_server,
)
from ..config import load_config
from ..engine import TTSEngine
from ..history import load_history, save_history
from ..onboarding import should_show_activation_panel
from ..paths import PIPER_EXE, ensure_dirs
from ..tray import make_tray_icon
from .bridge import PipPalBridge
from .overlay_window import OverlayWindowController
from .server import start_web_ui_server
from .startup_toast import show_startup_toast
from .windows import WebWindowManager


def _selected_piper_missing(config: dict[str, Any]) -> bool:
    engine_name = str(config.get("engine") or "piper").lower()
    return engine_name == "piper" and not PIPER_EXE.exists()


def _signal_running_instance_to_show(port: int | None = None) -> bool:
    """Tell the already-running instance to OPEN + foreground its window.

    POSTs /settings to the running instance IPC (wired to
    windows.raise_window("settings")).
    Returns True iff HTTP 200; False on any failure.

    *port* is the already-resolved candidate port from
    :func:`~pippal.command_server.resolve_candidate_port`.  When omitted
    the resolution is repeated here (covers legacy callers).
    """
    import urllib.error
    import urllib.request

    if port is None:
        port = resolve_candidate_port()

    url = f"http://127.0.0.1:{port}/settings"
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def _foreground_running_window_win32() -> bool:
    """Best-effort Win32 foreground of the already-running PipPal window.

    Used as a fallback when the IPC signal cannot be delivered.  Uses
    ``EnumWindows`` to find a top-level visible window whose title contains
    "PipPal" that belongs to a DIFFERENT process (not the current second
    instance), then calls ``ShowWindow(SW_RESTORE)`` +
    ``BringWindowToTop`` + ``SetForegroundWindow``.

    Windows-only; wraps everything in try/except and returns False on any
    failure or on non-Windows platforms.  The caller must never rely on
    the return value for correctness — this is purely best-effort UX.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import ctypes.wintypes
        import os as _os

        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        current_pid = _os.getpid()
        found_hwnd: list[int] = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPARAM,
        )

        def _enum_callback(hwnd: int, _lparam: int) -> bool:
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "pippal" not in buf.value.lower():
                    return True
                pid = ctypes.wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == current_pid:
                    return True  # skip our own windows
                found_hwnd.append(hwnd)
                return False  # stop once we have one match
            except Exception:
                return True  # keep enumerating on any error

        user32.EnumWindows(WNDENUMPROC(_enum_callback), 0)

        if not found_hwnd:
            return False

        hwnd = found_hwnd[0]
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def build_tray_menu(
    *,
    engine: Any,
    config: dict[str, Any],
    windows: Any,
    hotkey_manager: Any,
) -> tuple[pystray.Menu, dict[str, Any]]:
    """Compose the native pystray menu the web app runs in the tray.

    Factored out of :func:`main` so the *exact same* menu and
    callables can be exercised head-less by the integration suite (a
    ``pystray.MenuItem`` is callable — ``item(icon)`` is precisely the
    dispatch a real tray click performs, minus the OS pixel rendering).

    Returns ``(menu, primitives)``; ``primitives`` exposes the bound
    callables (``quit_action``, ``history_submenu``, ...) so a test can
    assert their real effect without re-deriving them. ``main`` only
    consumes ``menu`` — behaviour is unchanged.
    """

    def quit_action(icon: Any, _item: Any) -> None:
        engine.stop()
        try:
            hotkey_manager.unregister_all()
            hotkey_manager.stop()
        except Exception:
            pass
        try:
            icon.stop()
        except Exception:
            pass
        windows.shutdown()

    def replay_handler(text: str) -> Callable[[Any, Any], None]:
        return lambda _i, _it: engine.replay_text(text)

    def history_submenu() -> list[pystray.MenuItem]:
        items = engine.get_history()
        if not items:
            return [pystray.MenuItem("(empty)", lambda _i, _it: None, enabled=False)]
        out = []
        for t in items[:10]:
            preview = t.replace("\n", " ").strip()
            if len(preview) > 70:
                preview = preview[:67] + "…"
            out.append(pystray.MenuItem(preview, replay_handler(t)))
        out.append(pystray.Menu.SEPARATOR)
        out.append(
            pystray.MenuItem("Clear history", lambda _i, _it: engine.clear_history())
        )
        return out

    menu = pystray.Menu(
        pystray.MenuItem("Recent", pystray.Menu(history_submenu)),
        pystray.MenuItem("First-run check", lambda _i, _it: windows.open("onboarding")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Settings…",
            lambda _i, _it: windows.open("settings"),
            default=True,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_action),
    )
    primitives = {
        "quit_action": quit_action,
        "history_submenu": history_submenu,
        "replay_handler": replay_handler,
    }
    return menu, primitives


def main() -> None:
    ensure_dirs()
    config = load_config()

    if _selected_piper_missing(config):
        print(
            f"piper.exe missing at {PIPER_EXE}; run setup.ps1 or "
            "switch engine in Settings.",
            file=sys.stderr,
        )

    # ----- Backend -----
    overlay = OverlayWindowController(config)
    engine = TTSEngine(config=config, root=_NullRoot(), overlay_ref=lambda: overlay)
    engine.attach_history(load_history(), save_history)

    # ----- Hotkeys (native HotkeyManager) -----
    from ..hotkey import HotkeyManager, duplicate_combo_failures

    hotkey_manager = HotkeyManager()
    hotkey_manager.start()
    import atexit

    atexit.register(hotkey_manager.stop)

    builtin_handlers = {
        "speak": engine.speak_selection_async,
        "queue": engine.queue_selection_async,
        "pause": engine.pause_toggle,
        "stop": engine.stop,
    }

    def _resolve_handler(action_id: str):
        if action_id in builtin_handlers:
            return builtin_handlers[action_id]
        ext = plugins.get_plugin_action(action_id)
        if ext is not None:
            return lambda aid=action_id: engine.dispatch_plugin_action(aid)
        legacy = getattr(engine, f"speak_{action_id}_async", None)
        return legacy if callable(legacy) else None

    def bind_hotkeys() -> list[tuple[str, str, str]]:
        hotkey_manager.unregister_all()
        actions = plugins.hotkey_actions()
        failures = duplicate_combo_failures(config, actions)
        dup = {aid for aid, _c, _r in failures}
        for action_id, key, _label, default_combo in actions:
            if action_id in dup:
                continue
            combo = config.get(key, default_combo)
            fn = _resolve_handler(action_id)
            if not combo or fn is None:
                continue
            hotkey_manager.register(combo, fn)
        for combo, reason in hotkey_manager.failures():
            aid = next(
                (a for a, k, _l, _d in actions if config.get(k, _d) == combo),
                "?",
            )
            failures.append((aid, combo, reason))
        return failures

    bind_hotkeys()

    # ----- Bridge + local static/JSON server -----
    windows = WebWindowManager()
    bridge = PipPalBridge(
        engine,
        config,
        overlay,
        on_open_settings=lambda: windows.open("settings"),
        on_open_voice_manager=lambda: windows.open("voices"),
        on_open_notices=lambda: windows.open("notices"),
        on_close_window=lambda: windows.close(
            windows.surface_for_window(bridge._active_webview_window()) or "settings"
        ),
        on_hotkey_change=bind_hotkeys,
        on_engine_change=engine.reset_backend,
    )
    _server, port = start_web_ui_server(bridge)
    base_url = f"http://127.0.0.1:{port}"
    windows.configure(base_url, bridge)

    # Wire the overlay window controller so state transitions open/hide the
    # overlay window so state transitions open/hide it. The callbacks run on
    # engine / playback / auto-hide-timer threads -- same context as the
    # other on_open_* callbacks -- and are deduplicated by the controller.
    overlay.set_window_callbacks(
        on_show=lambda: windows.open("overlay"),
        on_hide=lambda: windows.hide("overlay"),
    )
    windows.set_overlay_controller(overlay)

    # ----- Local IPC / single-instance gate -----
    #
    # CONNECT-FIRST: probe the candidate port (env → .cmd_port → default
    # 51677) before trying to bind.  This distinguishes a genuine live
    # instance from a bind failure caused by an OS-excluded port range
    # (Hyper-V / WSL2 / Docker reserve ranges, WinError 10013 WSAEACCES).
    _candidate_port = resolve_candidate_port()
    if probe_running_instance(_candidate_port):
        # A live PipPal instance responded — do the existing foreground
        # behaviour and exit without ever trying to bind.
        if not _signal_running_instance_to_show(_candidate_port):
            _foreground_running_window_win32()
        raise SystemExit(0)

    command_callbacks = {
        "settings": lambda: windows.raise_window("settings"),
        "stop": engine.stop,
        "pause": engine.pause_toggle,
        "prev": engine.prev_chunk,
        "replay": engine.replay_chunk,
        "next": engine.next_chunk,
        "voice-manager": lambda: windows.open("voices"),
        "first-run-check": lambda: windows.raise_window("onboarding"),
    }
    # BIND-WITH-FALLBACK: start_command_server tries the default/env port
    # and falls back to a free OS-assigned port if bind fails — it does NOT
    # return None due to an excluded-port error.  The actually-bound port is
    # persisted to .cmd_port so the next startup's connect-first probe finds
    # it.  None is only returned if even the free-port bind fails (rare).
    #
    # control_routes_enabled=True is required so that a second-launch's
    # _signal_running_instance_to_show() can POST /settings and trigger
    # windows.raise_window("settings").  Without this flag POST /settings
    # returns 404 and the foreground signal silently fails.  All control
    # routes are bound to 127.0.0.1 only so local-only exposure is correct.
    cmd_server = start_command_server(
        engine, commands=command_callbacks, control_routes_enabled=True
    )
    if cmd_server is None:
        # Belt-and-suspenders: if we still can't bind any port, try to
        # activate whatever might be running (could be a race) and exit.
        if not _signal_running_instance_to_show(_candidate_port):
            _foreground_running_window_win32()
        raise SystemExit(0)

    # ----- Tray (native pystray) -----
    tray: dict[str, Any] = {"icon": None}

    def update_tray_icon() -> None:
        ic = tray.get("icon")
        if ic is None:
            return
        with engine.lock:
            speaking = engine.is_speaking
        brand = config.get("brand_name", "PipPal")
        try:
            ic.icon = make_tray_icon(speaking)
            ic.title = f"{brand} — speaking" if speaking else brand
        except Exception:
            pass

    def tray_poll() -> None:
        while True:
            update_tray_icon()
            threading.Event().wait(1.0)

    threading.Thread(target=tray_poll, daemon=True).start()

    menu, _tray_primitives = build_tray_menu(
        engine=engine,
        config=config,
        windows=windows,
        hotkey_manager=hotkey_manager,
    )
    icon = pystray.Icon(
        "pippal",
        make_tray_icon(False),
        config.get("brand_name", "PipPal"),
        menu,
    )
    tray["icon"] = icon
    icon.run_detached()

    # Show a brief "running in background" tray balloon once at startup.
    # Fires ~200 ms after the tray icon is ready; silently skipped in CI
    # (PIPPAL_NO_STARTUP_NOTIFICATION=1) and on any display error.
    show_startup_toast(icon)

    if _selected_piper_missing(config) or should_show_activation_panel():
        windows.open("onboarding")

    # pywebview MUST own the main thread. windows.run() blocks here until
    # the last window closes / shutdown() is called.
    try:
        windows.run()
    finally:
        try:
            icon.stop()
        except Exception:
            pass


class _NullRoot:
    """Stand-in for the Tk root the engine takes for thread hops.

    The engine calls ``root.after(ms, fn)`` to bounce work onto the Tk
    UI thread. ``WebOverlay`` is thread-safe and owns its OWN auto-hide
    timer, so an ``ms == 0`` immediate hop runs inline (same net effect
    as the engine's thread-hop). A ``ms > 0`` call is a genuinely
    *delayed* callback — running it inline would fire it immediately
    (this is exactly the ``auto_hide_ms`` regression). So a timed call
    schedules a real ``threading.Timer`` and exposes ``after_cancel``
    matching Tk's cancellable ``after`` ids.
    """

    def __init__(self) -> None:
        self._timers: dict[int, threading.Timer] = {}
        self._next_id = 1

    def after(self, ms: int, fn=None, *args: Any) -> str | None:
        if fn is None:
            return None
        if not ms or ms <= 0:
            try:
                fn(*args)
            except Exception:
                pass
            return None
        tid = self._next_id
        self._next_id += 1

        def _run() -> None:
            self._timers.pop(tid, None)
            try:
                fn(*args)
            except Exception:
                pass

        t = threading.Timer(ms / 1000.0, _run)
        t.daemon = True
        self._timers[tid] = t
        t.start()
        return str(tid)

    def after_cancel(self, tid: str | None) -> None:
        if tid is None:
            return
        try:
            t = self._timers.pop(int(tid), None)
        except (TypeError, ValueError):
            return
        if t is not None:
            t.cancel()


if __name__ == "__main__":
    main()
