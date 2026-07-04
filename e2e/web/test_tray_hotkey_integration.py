"""Headless-safe integration tests for the native tray + global hotkey.

The web migration keeps the system tray (``pystray``) and the global
hotkey (``keyboard`` low-level hook) **native and unchanged** — the web
frontend only replaces the *windows*. The original checklist marked
rows 5.2–5.6 as "not E2E-testable" because they have no served DOM.
That is true of the OS's *pixel rendering* and the OS *physically
delivering a keystroke to the hook* — but the tray menu callbacks and
the hotkey-dispatch handler are plain Python callables and ARE testable
head-less, without a desktop and without a DOM.

These tests do exactly that, with the same per-test reset guarantees as
the rest of the web suite (``e2e/web/conftest.py``: a fresh isolated
``PIPPAL_DATA_DIR`` per test, no leaked ``config.json``, the
``assert_fresh_baseline`` autouse guard, a fresh real ``TTSEngine`` +
real bridge + real served server):

* The pystray menu is built by the **exact same** code path the running
  web app uses — :func:`pippal.web_ui.app_web.build_tray_menu` (extracted
  verbatim from ``main`` so the menu and its callables are byte-for-byte
  what ships). A ``pystray.MenuItem`` is callable; ``item(icon)`` is
  precisely the dispatch a real tray click performs (``self._action(
  icon, self)``), minus the OS pixel rendering.

* The global hotkey is driven through the **real**
  :class:`pippal.hotkey.HotkeyManager` (a real low-level keyboard hook is
  installed on the Windows runner) registered with the real
  ``plugins.hotkey_actions()`` + the real engine handler, then dispatched
  via the manager's own stored handler — exactly what
  ``HotkeyManager._safe_call`` invokes when the physical combo fires.
  The only thing skipped is the OS physically routing the keystroke into
  the hook, which is "testing Windows, not PipPal".

The ``windows`` object the tray callbacks talk to is a recording
stand-in for :class:`pippal.web_ui.windows.WebWindowManager` — that
manager's ``open()`` calls ``webview.create_window`` (a real GUI window,
out of scope of a headless runner), so the genuine *tray contract* is
"the item requests surface X open", recorded the same way the existing
suite records the bridge's ``on_open_*`` host callbacks
(``backend['window_opens']``). The web-reachable surface each tray item
opens is *also* asserted to render through the same real served bridge
the Playwright tests use, tying the native callback to a real effect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect

from pippal.hotkey import HotkeyManager, parse_combo
from pippal.web_ui.app_web import build_tray_menu


def _goto(page: Page, app_url: str, view: str, step=None) -> None:
    if step is not None:
        step(f"open '{view}' surface")
    page.goto(f"{app_url}/index.html?view={view}")
    expect(page.locator("body")).to_have_attribute(
        "data-ready", view, timeout=15000
    )
    if step is not None:
        step.check(f"surface '{view}' rendered (body[data-ready={view}])")


class _RecordingWindows:
    """Headless stand-in for ``WebWindowManager``.

    ``WebWindowManager.open`` calls ``webview.create_window`` (a real GUI
    window — no headless equivalent), so the genuine, testable tray
    contract is *which surface the item asks to open* and *that shutdown
    was requested on Quit*. Recorded exactly the way ``conftest.backend``
    records the bridge's ``on_open_settings`` host callbacks.
    """

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.shutdown_calls = 0

    def open(self, surface: str) -> None:
        self.opened.append(surface)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeIcon:
    """Stand-in for the ``pystray.Icon`` pystray passes into a menu-item
    action as the first positional arg. Records ``stop()`` so the Quit
    test can assert the icon-teardown boundary without a real tray."""

    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


def _flatten(menu: Any) -> list[Any]:
    """Real items of a pystray.Menu, separators dropped.

    ``pystray.Menu.SEPARATOR`` is a sentinel ``MenuItem`` instance — drop
    it by identity (its ``.text`` is the renderer's '- - - -' filler, not
    something to match on)."""
    import pystray

    return [item for item in menu.items if item is not pystray.Menu.SEPARATOR]


def _find_item(menu: Any, text_prefix: str) -> Any:
    for item in _flatten(menu):
        if str(item.text).startswith(text_prefix):
            return item
    raise AssertionError(
        f"tray item starting {text_prefix!r} not found; "
        f"have {[i.text for i in _flatten(menu)]}"
    )


def _build_web_tray(backend: dict[str, Any]) -> tuple[Any, dict[str, Any], Any, Any]:
    """The exact pystray menu the running web app builds, wired to this
    test's fresh real engine/config and a recording windows + a real
    HotkeyManager. Returns (menu, primitives, windows, hotkey_manager)."""
    windows = _RecordingWindows()
    hkm = HotkeyManager()
    hkm.start()
    menu, primitives = build_tray_menu(
        engine=backend["engine"],
        config=backend["config"],
        windows=windows,
        hotkey_manager=hkm,
    )
    return menu, primitives, windows, hkm


# ===========================================================================
# 5.2 — Tray "Settings…" menu item callback
# ===========================================================================

def test_tray_settings_item_opens_settings_surface(
    page: Page, app_url: str, backend, step
):
    """The real tray 'Settings…' item, invoked exactly as a pystray
    click does (``item(icon)`` → ``action(icon, item)``), requests the
    Settings surface — and that surface really renders through the same
    served bridge the Playwright suite drives (the 7 settings cards)."""
    step("build the real pystray menu (app_web.build_tray_menu)")
    menu, _prim, windows, hkm = _build_web_tray(backend)
    try:
        item = _find_item(menu, "Settings")
        # 'Settings…' is the tray's default (left-click) item.
        assert item.default is True
        step.check("found real tray 'Settings…' item (it is the default item)")

        assert windows.opened == []
        step("invoke the tray item exactly as a pystray click does")
        item(_FakeIcon())  # genuine pystray dispatch
        # Real effect: the native callback asked the window manager to
        # open the Settings surface (same contract app_web wires to
        # WebWindowManager.open).
        assert windows.opened == ["settings"]
        step.check("tray callback requested the Settings surface (windows.open)")

        # …and that surface is real: it renders through the same served
        # bridge the Playwright tests use (cf. test_settings_renders_
        # nine_cards / row 2.0).
        _goto(page, app_url, "settings", step)
        expect(page.locator(".card-title")).to_have_count(9)
        expect(page.get_by_test_id("settings-save")).to_be_visible()
        step.check("Settings surface renders for real through the served bridge "
                   "(9 cards + Save)")
    finally:
        hkm.stop()


# ===========================================================================
# 5.3 — Tray "First-run check" / onboarding menu item callback
# ===========================================================================

def test_tray_first_run_item_opens_onboarding_surface(
    page: Page, app_url: str, backend, step
):
    """The real tray 'First-run check' item, invoked as pystray would,
    requests the onboarding surface — which really renders through the
    same served bridge (title + status + skip/close button)."""
    step("build the real pystray menu")
    menu, _prim, windows, hkm = _build_web_tray(backend)
    try:
        item = _find_item(menu, "First-run check")

        assert windows.opened == []
        step("invoke the tray 'First-run check' item (genuine pystray dispatch)")
        item(_FakeIcon())
        assert windows.opened == ["onboarding"]
        step.check("tray callback requested the onboarding surface")

        _goto(page, app_url, "onboarding", step)
        expect(page.get_by_test_id("onboarding-title")).to_be_visible()
        expect(page.get_by_test_id("onboarding-status")).to_be_visible()
        skip = page.locator(
            '[data-testid="onboarding-skip"], [data-testid="onboarding-close"]'
        )
        expect(skip.first).to_be_visible()
        step.check("onboarding surface renders for real (title/status/skip)")
    finally:
        hkm.stop()


# ===========================================================================
# 5.1 — Tray "Recent" submenu + "Clear history" via the real tray builder
# ===========================================================================

def test_tray_recent_submenu_and_clear_real_effect(
    page: Page, app_url: str, backend, step
):
    """Drive the tray 'Recent' submenu through the *actual* pystray menu
    the web app builds. A real ``pippal.history`` round-trip populates
    the engine the way the app does at startup; the submenu builder
    (re-evaluated by pystray every open) enumerates ``engine
    .get_history()``; invoking the real 'Clear history' menu item runs
    ``engine.clear_history()`` which empties BOTH the in-memory list and
    the real ``history.json`` on disk — the precise effect of the tray
    item, exercised through the tray callable itself.
    """
    import pippal.history as history_mod
    from pippal.history import load_history, save_history

    engine = backend["engine"]
    step("build the real pystray menu the web app ships")
    menu, _prim, windows, hkm = _build_web_tray(backend)
    try:
        recent = _find_item(menu, "Recent")
        assert recent.submenu is not None

        # Empty profile: the submenu shows the disabled "(empty)" row.
        empty_items = list(recent.submenu.items)
        assert [i.text for i in empty_items] == ["(empty)"]
        assert empty_items[0].enabled is False
        step.check("fresh profile: Recent submenu shows the disabled '(empty)' row")

        # Populate via the REAL history persistence the app uses at
        # startup (engine.attach_history(load_history(), save_history)).
        step("save_history([2 entries]) + engine.attach_history (real startup path)")
        save_history(["First recent entry", "Second recent entry"])
        engine.attach_history(load_history(), save_history)

        # pystray re-evaluates a callable submenu on every open — the
        # real builder now enumerates the live history.
        items = list(recent.submenu.items)
        texts = [i.text for i in items]
        assert "First recent entry" in texts
        assert "Second recent entry" in texts
        assert "Clear history" in texts
        step.check("real Recent submenu re-enumerated the 2 live history entries")

        # Invoke a recent entry exactly as a tray click would → real
        # engine.replay_text (token bump is a real engine effect; no
        # piper here so it routes through the onboarding clip).
        with engine.lock:
            tok_before = engine.token
        step("invoke the 'First recent entry' submenu item (real tray click)")
        _find_item(recent.submenu, "First recent entry")(_FakeIcon())
        deadline = page.evaluate("Date.now()") + 5000
        while page.evaluate("Date.now()") < deadline:
            with engine.lock:
                if engine.token > tok_before:
                    break
            page.wait_for_timeout(100)
        with engine.lock:
            assert engine.token > tok_before, "replay did not reach engine"
        step.check(f"recent entry reached engine.replay_text (token > {tok_before})")
        engine.stop()

        # 'Clear history' tray item → engine.clear_history(): empties
        # memory AND rewrites the real history.json on disk to [].
        step("invoke the real 'Clear history' submenu item")
        _find_item(recent.submenu, "Clear history")(_FakeIcon())
        assert engine.get_history() == []
        assert backend["bridge"].get_history() == []
        assert json.loads(
            Path(history_mod.HISTORY_PATH).read_text("utf-8")
        ) == []
        assert windows.opened == []  # Recent never opens a window
        step.check(
            "Clear history emptied memory + bridge + history.json on disk; "
            "Recent opened no window"
        )
    finally:
        hkm.stop()


# ===========================================================================
# 5.4 — Tray "Quit" menu item callback (OS-exit boundary stubbed)
# ===========================================================================

def test_tray_quit_item_runs_full_teardown_sequence(
    page: Page, app_url: str, backend, step
):
    """The real tray 'Quit' callback (``app_web``'s ``quit_action``) must
    run the documented shutdown sequence: stop the engine (token bump +
    not speaking), unregister + stop the global hotkey hook, stop the
    tray icon, and request the window manager shutdown. The only stubbed
    boundary is the icon-stop / window-manager teardown (the recording
    ``_FakeIcon`` / ``_RecordingWindows``); the engine + the REAL
    ``HotkeyManager`` are genuine. It must NOT terminate pytest.
    """
    engine = backend["engine"]
    step("build the real pystray menu + real HotkeyManager")
    menu, _prim, windows, hkm = _build_web_tray(backend)
    try:
        # Real hook installed (Windows runner). Register the real speak
        # combo so 'Quit' has something genuine to unregister/stop.
        assert hkm._started is True
        hkm.register("windows+shift+r", engine.speak_selection_async)
        assert hkm._hook_handle is not None
        step.check("real keyboard hook installed + windows+shift+r registered")

        # Make the engine genuinely "speaking" so quit's engine.stop()
        # has a real state transition to perform (token++ + is_speaking
        # cleared) — drive it through the real served bridge read flow.
        step('read-aloud via the served bridge so the engine is genuinely '
             'speaking before Quit')
        page.goto(f"{app_url}/index.html?view=overlay")
        expect(page.locator("body")).to_have_attribute(
            "data-ready", "overlay", timeout=15000
        )
        page.evaluate(
            """async () => {
                const r = await fetch('/bridge', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({
                    method: 'read_text',
                    args: ['PipPal tray quit teardown integration check.'],
                  }),
                });
                return r.ok;
            }"""
        )

        def _engine_active() -> bool:
            with engine.lock:
                return engine.is_speaking

        deadline = page.evaluate("Date.now()") + 8000
        while page.evaluate("Date.now()") < deadline and not _engine_active():
            page.wait_for_timeout(150)
        with engine.lock:
            tok_before = engine.token
            was_speaking = engine.is_speaking
        assert was_speaking, "engine never started; quit-stop would be a no-op"
        step.check(f"engine is genuinely speaking (token={tok_before})")

        quit_item = _find_item(menu, "Quit")
        icon = _FakeIcon()

        # Genuine pystray dispatch of the Quit callback.
        step("invoke the real tray 'Quit' callback (genuine pystray dispatch)")
        quit_item(icon)

        # Documented teardown sequence — all real effects:
        with engine.lock:
            assert engine.token > tok_before, "engine.stop() not called by quit"
            assert engine.is_speaking is False, "engine still speaking after quit"
        step.check("Quit → engine.stop() (token bumped, is_speaking cleared)")
        # Real HotkeyManager fully torn down (hook unhooked, handlers
        # cleared) — exactly what app_web's quit_action does.
        assert hkm._hook_handle is None, "hotkey hook not stopped by quit"
        assert hkm._started is False
        assert hkm._handlers == {}, "hotkey handlers not cleared by quit"
        step.check("Quit → real HotkeyManager unhooked + handlers cleared")
        # icon.stop() and windows.shutdown() were invoked.
        assert icon.stop_calls == 1, "icon.stop() not called by quit"
        assert windows.shutdown_calls == 1, "windows.shutdown() not called"
        step.check("Quit → icon.stop() + windows.shutdown() each called once")

        # And — the whole point — this pytest process is still alive.
        assert page.evaluate("1 + 1") == 2
        step.check("pytest process still alive (Quit did not kill the runner)")
    finally:
        hkm.stop()


# ===========================================================================
# 5.6 — Global hotkey handler DISPATCH (no physical keypress)
# ===========================================================================

def test_global_hotkey_speak_dispatch_drives_real_engine(
    page: Page, app_url: str, backend, step
):
    """Register the configured 'speak' (Read selection) action on the
    REAL ``HotkeyManager`` the way ``app_web.bind_hotkeys`` does, then
    dispatch it through the manager's OWN stored handler — the exact
    callable ``HotkeyManager._safe_call`` invokes when the physical combo
    fires (only the OS routing the keystroke into the hook is skipped,
    which is "testing Windows, not PipPal"). Assert a REAL engine effect:
    this no-``piper.exe`` checkout routes Speak through the engine's
    onboarding clip, which bumps ``engine.token`` and flips
    ``is_speaking`` — a genuine, non-mocked engine state change.
    """
    from pippal import plugins

    engine = backend["engine"]
    step("start a real HotkeyManager (installs the real low-level hook)")
    hkm = HotkeyManager()
    hkm.start()
    try:
        assert hkm._started is True, "real keyboard hook did not install"
        step.check("real keyboard hook installed")

        # Resolve + register exactly as app_web.bind_hotkeys does: the
        # built-in 'speak' action maps to engine.speak_selection_async,
        # bound to its configured combo from plugins.hotkey_actions().
        actions = plugins.hotkey_actions()
        speak = next(a for a in actions if a[0] == "speak")
        action_id, config_key, _label, default_combo = speak
        combo = backend["config"].get(config_key, default_combo)
        builtin = {
            "speak": engine.speak_selection_async,
            "queue": engine.queue_selection_async,
            "pause": engine.pause_toggle,
            "stop": engine.stop,
        }
        speak_entrypoint = builtin[action_id]
        step(f"register the configured 'speak' action on combo {combo!r} "
             "(as app_web.bind_hotkeys does)")
        assert hkm.register(combo, speak_entrypoint) is True

        # The manager keyed the handler by the parsed combo. This is the
        # SAME object _safe_call() runs off the hook thread when the
        # physical Win+Shift+R is detected — invoke that exact handler.
        # (Bound methods are re-created per attribute access, so compare
        # the underlying function + instance, not object identity.)
        handler = hkm._handlers.get(parse_combo(combo))
        assert handler is speak_entrypoint, (
            "manager did not store the exact registered handler object"
        )
        assert (
            handler.__func__ is type(engine).speak_selection_async
            and handler.__self__ is engine
        ), "registered handler is not the real engine speak entrypoint"
        step.check("manager stored the exact real engine speak entrypoint")

        with engine.lock:
            tok_before = engine.token
            assert engine.is_speaking is False

        step("dispatch the manager's OWN stored handler (== _safe_call's call, "
             "no keypress)")
        handler()  # == HotkeyManager._safe_call's call, no keypress

        def _engine_reacted() -> bool:
            with engine.lock:
                return engine.token > tok_before or engine.is_speaking

        deadline = page.evaluate("Date.now()") + 8000
        while page.evaluate("Date.now()") < deadline and not _engine_reacted():
            page.wait_for_timeout(120)
        with engine.lock:
            assert engine.token > tok_before, (
                "hotkey speak dispatch did not reach the real engine "
                "(token unchanged)"
            )
            tok_after = engine.token
        step.check(
            f"hotkey speak dispatch reached the real engine "
            f"(token {tok_before} -> {tok_after})"
        )
        engine.stop()
    finally:
        hkm.stop()
