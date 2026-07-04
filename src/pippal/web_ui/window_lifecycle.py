"""Window lifecycle operations for the PipPal web UI.

Extracted from ``windows.py`` so that it stays under the line-count guard
and remains directly file-path-loadable by the regression test harness
(which loads ``windows.py`` via :func:`importlib.util.spec_from_file_location`
with a synthetic module name and therefore has NO package context).

Each function takes the :class:`WebWindowManager` instance as its first
argument (``mgr``) and reads/writes its state (``mgr._windows``,
``mgr._lock``, ``mgr._bridge``, ...) and calls back into the manager's
own methods exactly as the original methods did via ``self``.  No
behaviour change — only the ``self`` receiver became an explicit ``mgr``
parameter so the bodies live in a sibling module.

``windows.py`` calls these through a lazy ``_lifecycle()`` shim (absolute
import with a file-path fallback) so the file-path loader still works.

Behaviour preserved: DWM corner wiring, overlay no-activate on cold create
and re-show, overlay re-anchor, overlay never-destroy in ``hide``,
load_url on re-open, hide-not-destroy surfaces.
"""

from __future__ import annotations

from typing import Any

import webview

_SURFACES: dict[str, dict[str, Any]] = {
    "settings": {
        "title": "PipPal",
        "title_key": "window.settings.title",
        "width": 600,
        "height": 760,
    },
    "voices": {
        "title": "Voices",
        "title_key": "window.voices.title",
        "width": 820,
        "height": 640,
    },
    "onboarding": {
        "title": "PipPal",
        "title_key": "window.onboarding.title",
        "width": 540,
        "height": 560,
    },
    "notices": {
        "title": "PipPal - Open-source licences",
        "title_key": "window.notices.title",
        "width": 760,
        "height": 620,
    },
    # The reader overlay / mini-player is a NORMAL opaque frameless window
    # — built the same way as the Settings window (solid dark background
    # #13151c, no transparency machinery, fully clickable).
    #
    # The overlay uses the normal opaque frameless approach: dragging via
    # pywebview-drag-region on the header, fully clickable, stable layout.
    # Dimensions sized for comfortable mini-player use:
    #   width:  560 px — transport buttons + label with breathing room.
    #   height: 200 px — header(44px) + body(flex) + footer(40px) + padding.
    "overlay": {
        "title": "PipPal",
        "title_key": "window.overlay.title",
        "width": 560,
        "height": 200,
        "on_top": True,
        "frameless": True,
        "easy_drag": False,  # drag handled by .pywebview-drag-region in header
    },
}


def _window_title(spec: dict[str, Any]) -> str:
    """Resolve a surface's native window title through the i18n catalog.

    Falls back to the English literal in ``spec["title"]`` when the i18n
    engine is unavailable or the key is missing. The import is deliberately
    lazy + absolute (never a top-level ``from ..i18n`` relative import) so
    this module stays loadable via ``windows.py``'s file-path loader, which
    imports it with a synthetic name and NO package context.
    """
    default = spec.get("title", "PipPal")
    key = spec.get("title_key")
    if not key:
        return default
    try:
        from pippal.i18n import MARKER_OPEN, t

        rendered = t(key)
    except Exception:
        return default
    if not rendered or rendered.startswith(MARKER_OPEN):
        return default
    return rendered


def make_window(mgr: Any, surface: str, *, hidden: bool = False) -> Any:
    spec = _SURFACES.get(surface, _SURFACES["settings"])
    url = f"{mgr._base_url}/index.html?view={surface}"
    position = mgr._window_position(surface, spec)
    kwargs: dict[str, Any] = {
        "title": _window_title(spec),
        "url": url,
        "width": spec["width"],
        "height": spec["height"],
        "js_api": mgr._bridge,
        "frameless": spec.get("frameless", True),
        "easy_drag": spec.get("easy_drag", False),
    }
    if hidden:
        # Start the window HIDDEN so the pywebview GUI loop has a window to
        # keep alive WITHOUT popping a visible surface.  Used by run() on a
        # normal (already-activated) launch so the app starts straight to
        # the tray (the startup toast tells the user where it is); the tray
        # "Settings…" item / hotkeys later show() this same hidden window.
        kwargs["hidden"] = True
    if not spec.get("transparent"):
        kwargs["background_color"] = "#13151c"
    if position is not None:
        kwargs.update(position)
    if spec.get("on_top") and not hidden:
        # Only carry the TOPMOST band on NON-hidden windows.  The pre-warmed
        # overlay is created hidden=True at startup; setting on_top on a hidden
        # window means the live HWND is already TOPMOST, and the z-order shuffle
        # in bring_to_foreground can surface the hidden overlay causing an empty
        # pop.  Deferring on_top to the visible-show path means the pre-warmed
        # overlay starts with normal z-order and is only pinned topmost when a
        # genuine read shows it.
        kwargs["on_top"] = True
    if spec.get("transparent"):
        kwargs["transparent"] = True
    # Note: pywebview ≥6.x does not expose a `parent` kwarg on
    # create_window; child-window z-order is managed by the OS on
    # Windows for windows in the same process without explicit
    # parent wiring.  The kwarg was removed to prevent a
    # TypeError → HTTP 500 when secondary-window openers are called via
    # the bridge server.
    win = webview.create_window(**kwargs)

    # Lifecycle trace (metadata-only): which surface was opened.  Non-blocking;
    # no-op when diagnostics are off.  ``surface`` is a fixed identifier
    # ("settings"/"overlay"/...), never user content.
    try:
        from pippal.diag_trace import lifecycle_event

        lifecycle_event("window_opened", surface=str(surface))
    except Exception:
        pass

    if spec.get("transparent"):
        # The WebView2 ``DefaultBackgroundColor = Transparent`` that
        # pywebview applies for ``transparent=True`` does NOT make the
        # WinForms host Form transparent — the host paints an opaque
        # #f0f0f0 rectangle behind the panel.  Apply a Win32 layered
        # colour-key to the host HWND once the native window exists so
        # the empty host area genuinely shows the desktop through.
        # Wired on both ``shown`` and ``loaded`` (idempotent) because
        # ``native``/``Handle`` is only valid after creation.
        def _apply_transparency() -> None:
            mgr._apply_layered_colorkey(win)

        # ``shown`` fires when the host HWND is realised; ``loaded``
        # fires after the page loads.  Wire both (idempotent) so the
        # key is applied as soon as the native handle is valid and is
        # re-asserted after any backend repaint on load.
        try:
            win.events.shown += _apply_transparency
        except Exception:
            pass
        try:
            win.events.loaded += _apply_transparency
        except Exception:
            pass
    else:
        # Apply Win11 DWM rounded corners to all non-transparent frameless
        # windows (overlay, settings, voices, etc.).  Windows 11 auto-rounds
        # FRAMED windows via DWM, but FRAMELESS windows need an explicit
        # DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        # call to get consistent rounded corners on all Win11 builds.
        def _apply_round_corners() -> None:
            mgr._apply_dwm_round_corners(win)

        try:
            win.events.shown += _apply_round_corners
        except Exception:
            pass

    if surface == "settings":

        def _closing() -> bool:
            if mgr._explicit_close:
                return True
            # Flush position to disk on close so the last user-chosen
            # position survives across launches.
            mgr._persist_window_position(surface, win, flush=True)
            try:
                win.hide()
            except Exception:
                pass
            return False

        win.events.closing += _closing

        # pywebview ≥5.0 exposes moved/resized events on Window.events.
        # Update in-memory position only — disk flush happens in _closing
        # so drag/resize doesn't trigger hundreds of disk writes.
        def _moved() -> None:
            try:
                mgr._persist_window_position(surface, win, flush=False)
            except Exception:
                pass

        def _resized() -> None:
            try:
                mgr._persist_window_position(surface, win, flush=False)
            except Exception:
                pass

        try:
            win.events.moved += _moved
        except Exception:
            pass
        try:
            win.events.resized += _resized
        except Exception:
            pass

    if surface == "overlay" and not hidden:
        # ISSUE 2 — on the COLD create (a real action trigger) the overlay
        # must appear WITHOUT stealing the foreground (create_window shows it
        # activated). Re-assert no-activate once the native HWND is realised
        # so even a first-ever read keeps the user's app in the foreground
        # (#265 belt-and-braces). Best-effort; never break window creation.
        #
        # IMPORTANT: this handler is intentionally skipped when hidden=True
        # (the pre-warm path in run()). In real WebView2 the ``shown`` event
        # fires even for a window created with hidden=True, so attaching
        # _overlay_no_activate unconditionally would call _show_no_activate
        # on the hidden pre-warmed window at startup and pop an empty overlay
        # before any action is triggered. The re-show path (open() →
        # mgr._show_no_activate(existing) at ~line 305) already ensures the
        # no-activate show for every real read/AI/WAV trigger, so this
        # handler is only needed on a non-hidden cold create.
        def _overlay_no_activate() -> None:
            try:
                mgr._show_no_activate(win)
            except Exception:
                pass

        try:
            win.events.shown += _overlay_no_activate
        except Exception:
            pass

    def _closed(s: str = surface) -> None:
        with mgr._lock:
            mgr._windows.pop(s, None)

    win.events.closed += _closed
    return win


def open(mgr: Any, surface: str) -> None:
    """Show a surface, focusing it if already open. Thread-safe.

    For all surfaces the existing window is shown in-place without any
    URL navigation.  Data is refreshed via ``window.__pippalRefresh``
    (registered in main.js during boot) which re-renders only the DOM
    without re-running wireFooter(), so button listeners survive
    hide->show cycles intact.

    This supersedes the nonce-reload (``load_url(&_t=<ms>)``) approach,
    which was a documented pywebview anti-pattern: ``load_url`` tears
    down the ``js_api`` bridge and causes a blank/empty window on reopen.
    The bridge SURVIVES ``hide()->show()`` without reload.

    Data freshness is preserved: ``__pippalRefresh`` re-fetches
    ``get_config()`` / etc. on every reopen.

    The overlay branch is byte-unchanged (already no-reload).
    """
    spec = _SURFACES.get(surface, _SURFACES["settings"])
    _reopened = False

    with mgr._lock:
        existing = mgr._windows.get(surface)
        if existing is not None:
            try:
                if surface != "overlay":
                    # No-reload reopen: the bridge survives hide()->show();
                    # load_url breaks it.  In-place refresh is fired below.
                    pass
                else:
                    # Overlay re-anchor: the reader overlay re-opens at its
                    # default active-screen anchor, not the user-dragged
                    # position.  _window_position() is only consulted on first
                    # creation (_make_window); on this re-show path the live
                    # window still carries the dragged coordinates, so we
                    # explicitly MOVE it back before showing.  The move runs
                    # before _show_no_activate so it never steals the
                    # foreground: move() only repositions; the subsequent
                    # SW_SHOWNOACTIVATE keeps the user's app focused.
                    anchor = mgr._overlay_position(spec)
                    if anchor is not None:
                        try:
                            existing.move(anchor["x"], anchor["y"])
                        except Exception:
                            # move() is best-effort; a failure must never
                            # block the overlay re-show.
                            pass
                existing.show()
                existing.restore()
                # Non-overlay: kick the in-place data refresh hook
                # registered during boot.  Mirroring the overlay kick;
                # guarded (&&) so it is a no-op if not yet registered.
                # Swallow exceptions -- evaluate_js is best-effort.
                if surface != "overlay":
                    try:
                        existing.evaluate_js(
                            "window.__pippalRefresh"
                            " && window.__pippalRefresh()"
                        )
                    except Exception:
                        pass
                # For the overlay, immediately re-assert a topmost no-activate
                # state so the pop does not steal the foreground: the user's
                # app keeps focus while the overlay shows the loader.
                # show()/restore() above keep pywebview's own window state;
                # _show_no_activate then drops the foreground steal via Win32.
                if surface == "overlay":
                    mgr._show_no_activate(existing)
                    # Trigger-driven JS fast-kick: immediately after re-showing
                    # the overlay, call the guarded global that forces
                    # _setTickRate(true) + a synchronous tick() so the JS poll
                    # notices the new engine state INSTANTLY instead of waiting
                    # up to 2000 ms for the next slow idle heartbeat.  The guard
                    # (&&) makes it a no-op if overlay JS hasn't rendered yet or
                    # the function is absent — always safe to evaluate.
                    try:
                        existing.evaluate_js(
                            "window.__pippalOverlayKick"
                            " && window.__pippalOverlayKick()"
                        )
                    except Exception:
                        # evaluate_js is best-effort; a failure must never
                        # block the overlay re-show.  The slow poll is the
                        # fallback.
                        pass
                # Re-assert the layered colour-key on every re-show of a
                # transparent surface: the WebView2 repaint on show/restore
                # can drop the host's layered transparency.
                if spec.get("transparent"):
                    mgr._schedule_transparency(existing)
                # Mark the reopen path taken.  Return is deferred to
                # OUTSIDE the lock so we can wait for load completion
                # without risking deadlock on _closed/_closing handlers.
                _reopened = True
            except Exception:
                mgr._windows.pop(surface, None)

    if _reopened:
        return

    if not mgr._started:
        win = mgr._make_window(surface)
        with mgr._lock:
            mgr._windows[surface] = win
        if spec.get("transparent"):
            mgr._schedule_transparency(win)
        return

    win = mgr._make_window(surface)
    with mgr._lock:
        mgr._windows[surface] = win
    if spec.get("transparent"):
        mgr._schedule_transparency(win)


def hide(mgr: Any, surface: str) -> None:
    """Hide a surface's window without destroying it. Thread-safe.

    Used by the overlay auto-hide path: the reader window is hidden
    (not destroyed) on idle so the next read can re-show it instantly
    and the live page (and its CDP target) survives. Falls back to
    destroy if the platform window can't hide.

    The OVERLAY is the exception to the fall-through: the overlay window
    is frequently the foreground / last live pywebview window; destroying
    it takes the GUI loop's last window with it and the WHOLE app
    disappears.  For the overlay we NEVER destroy on a failed hide: we
    keep the window object in the live set and swallow the hide error.
    Other surfaces keep the original destroy fall-through (a transient
    settings window is safe to tear down).  This guarantees at least one
    window always keeps the GUI loop alive across reading cycles."""
    with mgr._lock:
        win = mgr._windows.get(surface)
    if win is None:
        return
    try:
        win.hide()
    except Exception:
        if surface == "overlay":
            # NEVER destroy the overlay: it is (typically) the foreground /
            # last live window and destroying it kills the pywebview GUI loop.
            # Keep it in the live-window set and swallow the hide failure.
            return
        try:
            win.destroy()
        except Exception:
            pass
        with mgr._lock:
            mgr._windows.pop(surface, None)


def surface_for_window(mgr: Any, win: Any) -> str | None:
    """Return the surface name for a pywebview window object, or None."""
    with mgr._lock:
        for surface, w in mgr._windows.items():
            if w is win:
                return surface
    return None


def close(mgr: Any, surface: str) -> None:
    """Close a specific surface window by name. Thread-safe.

    For the ``settings``, ``onboarding``, and ``voices`` surfaces this hides
    the window instead of destroying it so the tray app keeps running and
    can re-open the window on demand (X-button / Finish-setup → tray →
    First-run-check).  All other surfaces are destroyed.

    ``onboarding`` hides so ``windows.open("onboarding")`` can re-show it;
    destroying would require a full ``_make_window`` on each re-open.
    ``voices`` hides for instant WebView2 reuse on next open.
    ``notices`` is destroyed on close (lightweight surface).

    This is the preferred target for ``on_close_window`` wiring so the
    X button in any surface closes *that* window, not the last-opened
    window as the old ``close_active()`` heuristic did.
    """
    with mgr._lock:
        win = mgr._windows.get(surface)
    if win is None:
        return
    if surface in (
        "settings",
        "onboarding",
        # Frequently-used surfaces: hide instead of destroy so the next
        # open() reuses the existing WebView2 window instantly rather than
        # paying 1-2 s for a full WebView2 init on every hotkey press.
        "voices",
    ):
        try:
            win.hide()
        except Exception:
            pass
    else:
        try:
            win.destroy()
        except Exception:
            pass


def close_active(mgr: Any) -> None:
    with mgr._lock:
        wins = list(mgr._windows.items())
    target = None
    for _surface, w in wins:
        try:
            if getattr(w, "gui", None) is not None and w.on_top is False:
                target = w
        except Exception:
            pass
    if target is None and wins:
        target = wins[-1][1]
    if target is not None:
        try:
            target.destroy()
        except Exception:
            pass


def shutdown(mgr: Any) -> None:
    with mgr._lock:
        wins = list(mgr._windows.values())
    mgr._explicit_close = True
    for w in wins:
        try:
            w.destroy()
        except Exception:
            pass
    with mgr._lock:
        mgr._windows.clear()
    try:
        webview.windows.clear()
    except Exception:
        pass


def run(mgr: Any) -> None:
    """Block on the pywebview GUI loop until all windows close.

    On a NORMAL (already-activated) launch the app must start straight to
    the TRAY: no Settings window is popped (the startup tray toast tells
    the user where the app is; the tray menu + global hotkeys open windows
    on demand).  But pywebview needs at least one live window to keep its
    GUI loop alive, so when no surface was opened during startup (e.g.
    first-run onboarding did NOT fire) we create the Settings window HIDDEN
    — the loop stays alive, nothing visible pops, and the tray "Settings…"
    item / a hotkey later show()s this same window.

    First-run / onboarding is unaffected: app_web.main() still calls
    ``open("onboarding")`` before run(), so on first run a window already
    exists in ``mgr._windows`` and this hidden-fallback is skipped.

    PRE-WARM: the reader overlay window is created HIDDEN here at startup
    — mirroring the hidden ``settings`` fallback above — so the FIRST
    ``windows.open("overlay")`` hits the warm show()+``__pippalOverlayKick``
    re-show path instead of a cold ``webview.create_window`` (~1-2 s).
    Created with ``hidden=True`` it NEVER pops visibly at startup.
    The overlay branch of :func:`hide` is hide-not-destroy so the lifecycle
    never destroys it.  Best-effort: a pre-warm failure must never block
    startup; the cold-create path in :func:`open` is the fallback."""
    if not mgr._windows:
        win = mgr._make_window("settings", hidden=True)
        with mgr._lock:
            mgr._windows["settings"] = win

    # Pre-warm the overlay window HIDDEN so the first read shows it warm.
    with mgr._lock:
        overlay_already = "overlay" in mgr._windows
    if not overlay_already:
        try:
            overlay_win = mgr._make_window("overlay", hidden=True)
        except Exception:
            overlay_win = None
        if overlay_win is not None:
            with mgr._lock:
                mgr._windows["overlay"] = overlay_win

    mgr._started = True
    webview.start()
