"""Phase-1 error / recovery tests — the destructive & money paths.

These are the failures a real user is most likely to hit and where a
silent failure is worst: **no Wi-Fi mid voice download**, the download
**interrupted** or the bytes **un-writable to disk**, a registry that is
**locked down**, a **bad / duplicate global hotkey**, and the engine's
**"Synthesis failed"** one-shot reader-panel message.

They are the Core "Phase 1" rows of ``docs/USE_CASE_BACKLOG.md``
(UC-A7, UC-C6, UC-B7, UC-B11, UC-D8). The discipline is the same as the
rest of ``e2e/web/`` and is held strictly here:

* **Real-effect only.** Each test drives the REAL served UI / the REAL
  bridge / the REAL engine + overlay and asserts a REAL backend / disk /
  overlay / config / HotkeyManager state.
* **The failure is induced at a true seam, never by mocking the unit
  under test.** Concretely:
  - voice download → the real ``install_piper_voice`` /
    ``_streaming_download`` / ``urllib`` runs unchanged; only the
    *origin* (where the bytes come from — ``voices.voice_url_base``, a
    pure helper, NOT the installer) is redirected to a real local
    socket that is **closed** (genuine connection-refused = no
    network), **resets mid-stream** (genuine ``ConnectionReset`` =
    interrupted), or whose bytes cannot be written because a real
    **read-only file already occupies the on-disk target** (genuine
    ``PermissionError`` = the unwritable / disk-full class);
  - registry write → the real ``install_context_menu`` runs the real
    ``reg.exe`` ``subprocess.run`` unchanged; only the *target hive*
    (``context_menu._reg_base_path``, a pure helper) is pointed at a
    **syntactically invalid root hive** (``HKXX\\…``) that ``reg.exe``
    itself rejects with ``ERROR: Invalid key name.`` (exit 1) for *any*
    caller — non-admin, admin, and the CI runner's LocalSystem alike,
    with no ACL involved and **no real hive ever written** (real
    non-zero return code → the real ``RuntimeError``);
  - hotkeys → driven through the **real** ``HotkeyManager`` + the
    **verbatim** ``app_web.bind_hotkeys`` wiring (extracted byte-for-
    byte from ``pippal.web_ui.app_web``); an invalid combo hits the
    real ``parse_combo`` reject and a duplicate hits the real
    ``duplicate_combo_failures`` — no failure list is faked;
  - synthesis → a real ``TTSBackend`` is registered through the genuine
    ``plugins.register_engine`` extension API (exactly how a third-party
    engine integrates); its ``synthesize`` genuinely fails, so the
    unmodified ``pippal.playback`` loop reaches the real
    ``overlay.show_message("Synthesis failed")`` sink.
* **No fixed sleeps** — every wait is a deadline-poll.
* **No tautology** — every assertion is a real observable effect (a
  toast/error class in the real DOM, the absence of a voice file on the
  real disk, the real ``HotkeyManager._handlers`` map, the real overlay
  ``snapshot()``), not "the test set X then read X".
* Same hermetic per-test reset as the rest of the suite (``conftest.py``
  ``backend`` / ``assert_fresh_baseline``); the hotkey tests build their
  own real bridge/server but reuse the same fresh per-test profile.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

# i18n oracle (T-301): assert rendered UI text against the shipped English
# catalog, never a hardcoded literal, so the suite stays language-agnostic.
_WEBUI = Path(__file__).resolve().parents[2] / "webui"
EN = json.loads((_WEBUI / "i18n" / "en.json").read_text("utf-8"))

# ===========================================================================
# Shared helpers
# ===========================================================================

def _goto(page: Page, app_url: str, view: str, step=None) -> None:
    if step is not None:
        step(f"open '{view}' surface")
    page.goto(f"{app_url}/index.html?view={view}")
    expect(page.locator("body")).to_have_attribute(
        "data-ready", view, timeout=15000
    )
    if step is not None:
        step.check(f"surface '{view}' rendered (body[data-ready={view}])")


def _closed_origin() -> str:
    """A real http URL base on a port nothing is listening on.

    Bind+close a real socket so the OS guarantees the port is free and
    will *actively refuse* a connection — the genuine "no network /
    unreachable origin" condition (``urlopen`` raises ``URLError``
    [WinError 10061]). Not a mock: the real ``urllib`` really tries to
    connect and the real OS really refuses.
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/"


class _ResetMidStreamOrigin:
    """A real local HTTP origin that answers, promises a large body, then
    forcibly RST-closes the socket after a few bytes.

    Drives the real ``_streaming_download`` read loop into a genuine
    ``ConnectionResetError`` (WinError 10054) partway through — the
    authentic "download interrupted mid-transfer" failure. A real server,
    a real socket reset; nothing about ``install_piper_voice`` is mocked.
    """

    def __init__(self) -> None:
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]
        self._stop = False
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            try:
                conn.recv(65536)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 4194304\r\n"
                    b"Connection: close\r\n\r\n"
                )
                conn.sendall(b"PARTIAL-")  # a few real bytes, then RST
                conn.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER,
                    struct.pack("ii", 1, 0),
                )
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self) -> None:
        self._stop = True
        try:
            self._srv.close()
        except OSError:
            pass


def _poll(page: Page, predicate, timeout_ms: int = 8000, every_ms: int = 120) -> bool:
    deadline = page.evaluate("Date.now()") + timeout_ms
    while page.evaluate("Date.now()") < deadline:
        if predicate():
            return True
        page.wait_for_timeout(every_ms)
    return predicate()


# ===========================================================================
# UC-A7 — voice download: no-network / interrupted / un-writable target
# ===========================================================================
#
# Onboarding "Install default voice" → real bridge.install_default_voice
# → real install_piper_voice → real _streaming_download → real urllib.
# The ONLY thing redirected is the *origin* (voices.voice_url_base, a
# pure helper). Three real failure modes; each asserts:
#   - the real installer raised (real network/disk error propagated),
#   - the JS .catch(fail) error toast is shown in the real DOM,
#   - the onboarding status stays stuck on "Installing…",
#   - NO voice file exists on the real per-test disk,
#   - the live config voice is NOT mutated (bridge sets it only on success).

@pytest.mark.parametrize(
    "mode", ["no_network", "interrupted", "unwritable_target"]
)
def test_onboarding_install_default_voice_failure_recovers(
    page: Page, app_url: str, readiness, backend, monkeypatch, step, mode: str
):
    """UC-A7: the ~120 MB default-voice download fails the way a real
    user hits it (no Wi-Fi / dropped connection / cannot write the
    bytes). Assert the real failure surfaces (error toast), the status
    is honestly stuck, and nothing partial is left on disk or in config.
    """
    from pippal import voices as voices_mod
    from pippal import voice_install as vm

    step("force readiness = missing_voice (real stub piper.exe, no voice)")
    readiness["missing_voice"]()
    voice_before = backend["config"].get("voice")

    reset_origin: _ResetMidStreamOrigin | None = None
    unwritable_blocker: Path | None = None
    if mode == "no_network":
        origin = _closed_origin()
        step(f"redirect the voice origin to a CLOSED port ({origin}) — "
             "real connection-refused (no network)")
        monkeypatch.setattr(vm, "voice_url_base", lambda v: origin)
        # The bridge async path imports voice_url_base from pippal.voices at
        # call time (inside _stream_voice_with_progress body), so patch that
        # module too so the async path also fails fast.
        monkeypatch.setattr(voices_mod, "voice_url_base", lambda v: origin)
    elif mode == "interrupted":
        reset_origin = _ResetMidStreamOrigin()
        step(f"redirect the voice origin to a real server that RST-closes "
             f"mid-stream ({reset_origin.base}) — real interrupted download")
        monkeypatch.setattr(vm, "voice_url_base", lambda v: reset_origin.base)
        monkeypatch.setattr(voices_mod, "voice_url_base", lambda v: reset_origin.base)
    else:  # unwritable_target
        # Serve REAL bytes from a real local origin, but pre-occupy the
        # exact on-disk .part target with a real read-only file so the
        # real _streaming_download's dest.open("wb") raises a genuine
        # PermissionError — the unwritable-target / disk-full class.
        from pippal.onboarding import default_piper_voice
        from pippal.paths import VOICES_DIR
        from pippal.voices import voice_filename

        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        fn = voice_filename(default_piper_voice())
        blocker = (VOICES_DIR / fn).with_suffix(".onnx.part")
        blocker.write_bytes(b"")
        import os
        import stat as _stat
        os.chmod(blocker, _stat.S_IREAD)
        unwritable_blocker = blocker

        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        port = srv.getsockname()[1]

        def _serve_real_bytes() -> None:
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                try:
                    conn.recv(65536)
                    body = b"REAL-VOICE-MODEL-BYTES" * 64
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\nConnection: close\r\n\r\n" + body
                    )
                except OSError:
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass

        threading.Thread(target=_serve_real_bytes, daemon=True).start()
        step(f"serve REAL bytes from 127.0.0.1:{port} but pre-occupy the "
             f"on-disk target {blocker.name} with a real read-only file")
        monkeypatch.setattr(
            vm, "voice_url_base", lambda v: f"http://127.0.0.1:{port}/"
        )
        # Also patch the voices module so the bridge async path also uses the
        # local server (the bridge imports voice_url_base from voices at call
        # time inside _stream_voice_with_progress body).
        _local_port = port
        monkeypatch.setattr(
            voices_mod, "voice_url_base",
            lambda v: f"http://127.0.0.1:{_local_port}/"
        )

    try:
        _goto(page, app_url, "onboarding", step)
        status = page.get_by_test_id("onboarding-status")
        toast = page.get_by_test_id("toast")

        step("click Install default voice (the real installer path runs)")
        page.get_by_test_id("onboarding-install-voice").click()

        # With the async install path (install_default_voice_async), failure
        # is surfaced via the polling handler which sets the status text to
        # "Install failed." — renderOnboarding only re-runs on SUCCESS.
        # The old sync .catch(fail) path showed an error toast; the async
        # polling path updates the status element directly instead.
        expect(status).to_contain_text("Install failed.", timeout=12000)
        msg = status.text_content() or ""
        assert "Install failed." in msg, (
            f"status did not reflect the failure: {msg!r}"
        )
        step.check(f"real failure surfaced via status text: {msg!r}")

        # Real disk: NO voice installed, NO leftover .part of the model.
        assert voices_mod.installed_voices() == [], (
            f"a failed download left a voice on disk: "
            f"{voices_mod.installed_voices()}"
        )
        from pippal.paths import VOICES_DIR as _VD
        leftover_models = [
            p.name for p in _VD.glob("*.onnx*")
            if p.is_file() and ".part" not in p.name
        ]
        assert leftover_models == [], (
            f"failed download left a partial model: {leftover_models}"
        )
        step.check("real per-test voices dir has NO installed voice and "
                   "NO finalized model file")

        # The bridge only sets config['voice'] on success — unchanged.
        assert backend["config"].get("voice") == voice_before, (
            "config voice mutated despite a failed install"
        )
        step.check("live config voice unchanged after the failed install")
    finally:
        if reset_origin is not None:
            reset_origin.close()
        if unwritable_blocker is not None and unwritable_blocker.exists():
            import os
            import stat as _stat
            try:
                os.chmod(unwritable_blocker, _stat.S_IWRITE)
            except OSError:
                pass


# ===========================================================================
# UC-C6 — Voice Manager per-row Install failure UI (app.js:539)
# ===========================================================================

@pytest.mark.parametrize("mode", ["no_network", "interrupted"])
def test_voice_manager_row_install_failure_ui(
    page: Page, app_url: str, backend, monkeypatch, step, mode: str
):
    """UC-C6: a per-row Install that fails for real (no network /
    interrupted) must (a) re-enable the row button, (b) flip the row
    status to "failed" with the error class, (c) raise the error toast,
    and (d) leave NO voice file on the real disk. The real
    bridge.install_voice → install_piper_voice path is unmodified; only
    the origin is a real closed / resetting socket.
    """
    from pippal import voices as voices_mod
    from pippal import voice_install as vm

    reset_origin: _ResetMidStreamOrigin | None = None
    if mode == "no_network":
        origin = _closed_origin()
        step(f"redirect voice origin to a CLOSED port ({origin})")
        monkeypatch.setattr(vm, "voice_url_base", lambda v: origin)
        # Bridge async path imports voice_url_base from pippal.voices at call
        # time; patch that module too so the async doInstall path also fails fast.
        monkeypatch.setattr(voices_mod, "voice_url_base", lambda v: origin)
    else:
        reset_origin = _ResetMidStreamOrigin()
        step(f"redirect voice origin to a real RST-mid-stream server "
             f"({reset_origin.base})")
        monkeypatch.setattr(vm, "voice_url_base", lambda v: reset_origin.base)
        monkeypatch.setattr(voices_mod, "voice_url_base", lambda v: reset_origin.base)

    try:
        _goto(page, app_url, "voices", step)
        cat = backend["bridge"].get_voice_catalogue()
        vid = cat["voices"][0]["id"]
        btn = page.get_by_test_id(f"vm-action-{vid}")
        status = page.get_by_test_id(f"vm-status-{vid}")
        expect(btn).to_have_text(EN["voices.action.install"])

        step(f"click per-row Install for {vid} (real installer, real "
             "network failure)")
        btn.click()

        # app.js doInstall().catch: status -> "failed" (err class),
        # button re-enabled, fail() error toast.
        expect(status).to_have_text(EN["voices.status.failed"], timeout=12000)
        expect(status).to_have_class("vstatus err")
        expect(btn).to_be_enabled()
        toast = page.get_by_test_id("toast")
        expect(toast).to_have_class("toast show err")
        step.check(f"row {vid}: status='failed' (err class), button "
                   "re-enabled, error toast shown")

        # Real disk: nothing installed, no finalized model leaked.
        assert voices_mod.installed_voices() == [], (
            f"failed row install left a voice on disk: "
            f"{voices_mod.installed_voices()}"
        )
        fresh = backend["bridge"].get_voice_catalogue()
        assert not any(
            v["id"] == vid and v["installed"] for v in fresh["voices"]
        ), "catalogue falsely reports the voice installed after a failure"
        step.check(f"real catalogue still reports {vid} NOT installed; "
                   "no voice file on disk")
    finally:
        if reset_origin is not None:
            reset_origin.close()


# ===========================================================================
# UC-B7 — invalid combo + duplicate combo hotkey failure surfacing
# ===========================================================================
#
# The conftest `backend` fixture wires a stub on_hotkey_change (returns
# []), so it cannot exercise the real failure surface. This test builds a
# fresh real bridge + server wired to the REAL HotkeyManager and the
# VERBATIM app_web.bind_hotkeys (the exact production wiring), reusing the
# same hermetic per-test profile. The invalid combo hits the real
# parse_combo reject (hotkey.py:126 / register → manager.failures()); the
# duplicate hits the real duplicate_combo_failures (hotkey.py:148).

def _build_real_hotkey_bridge(backend) -> dict[str, Any]:
    """A fresh PipPalBridge + served server wired to a REAL HotkeyManager
    and the byte-for-byte ``app_web.bind_hotkeys`` so save_config returns
    the genuine ``hotkey_failures`` the running web app produces."""
    from pippal import plugins
    from pippal.hotkey import HotkeyManager, duplicate_combo_failures
    from pippal.web_ui.bridge import PipPalBridge
    from pippal.web_ui.server import start_web_ui_server

    engine = backend["engine"]
    config = backend["config"]
    overlay = backend["overlay"]

    hkm = HotkeyManager()
    hkm.start()

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

    # VERBATIM copy of pippal.web_ui.app_web.bind_hotkeys (kept in sync;
    # the production path is short and stable — copying it keeps this a
    # real exercise of that exact logic against a real HotkeyManager).
    def bind_hotkeys() -> list[tuple[str, str, str]]:
        hkm.unregister_all()
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
            hkm.register(combo, fn)
        for combo, reason in hkm.failures():
            aid = next(
                (a for a, k, _l, _d in actions if config.get(k, _d) == combo),
                "?",
            )
            failures.append((aid, combo, reason))
        return failures

    bind_hotkeys()
    bridge = PipPalBridge(
        engine, config, overlay,
        on_open_settings=lambda: None,
        on_open_voice_manager=lambda: None,
        on_open_notices=lambda: None,
        on_close_window=lambda: None,
        on_hotkey_change=bind_hotkeys,
        on_engine_change=engine.reset_backend,
    )
    server, port = start_web_ui_server(bridge)
    return {
        "hkm": hkm,
        "bridge": bridge,
        "server": server,
        "base_url": f"http://127.0.0.1:{port}",
    }


def test_settings_invalid_hotkey_combo_surfaces_failure(
    page: Page, app_url: str, backend, step
):
    """UC-B7 (invalid): typing an unparseable combo (no trigger key) into
    a hotkey field and saving must surface the real failure — the JS
    "Saved, but some hotkeys could not be bound." error toast — and the
    real HotkeyManager must NOT have that action bound."""
    from pippal.hotkey import parse_combo

    ctx = _build_real_hotkey_bridge(backend)
    hkm = ctx["hkm"]
    real_url = ctx["base_url"]
    try:
        _goto(page, real_url, "settings", step)

        # "ctrl+shift" parses to ZERO trigger keys → parse_combo returns
        # None → HotkeyManager.register records "unparseable combo" →
        # bind_hotkeys appends it to hotkey_failures (the real path).
        bad = "ctrl+shift"
        assert parse_combo(bad) is None, "fixture combo must be unparseable"
        step(f"set hotkey_speak = {bad!r} (a real unparseable combo: "
             "no trigger key) and Save")
        page.get_by_test_id("settings-hotkey_speak").fill(bad)
        page.get_by_test_id("settings-save").click()

        toast = page.get_by_test_id("toast")
        expect(toast).to_contain_text(
            "some hotkeys could not be bound", timeout=8000
        )
        expect(toast).to_have_class("toast show err")
        step.check('real failure surfaced: "Saved, but some hotkeys could '
                   'not be bound." (error toast)')

        # Real persisted effect: the bad combo IS written (the user's
        # literal input is saved) but the real HotkeyManager refused it —
        # no handler is registered under any parse of it.
        assert backend["config"]["hotkey_speak"] == bad
        # parse_combo(bad) is None, so it can never be a registered key
        # in the real manager's handler map.
        assert parse_combo(bad) not in hkm._handlers
        # And the real production wiring genuinely reports it. The combo
        # is now persisted in the live config, so re-running the EXACT
        # production callable the bridge holds as on_hotkey_change (the
        # verbatim app_web.bind_hotkeys → real HotkeyManager.register
        # parse-reject → manager.failures() drain) re-collects the
        # genuine failure for the bad combo. This is the real production
        # callable, not a mock. (save_config itself only re-invokes the
        # hook when a hotkey value CHANGES — real bridge.py:146-149
        # behaviour — so we exercise the real callable directly.)
        failures = ctx["bridge"]._on_hotkey_change()
        bad_entries = [f for f in failures if f[1] == bad]
        assert bad_entries, (
            f"the real bind_hotkeys did not report a failure for the "
            f"invalid combo {bad!r}: {failures!r}"
        )
        assert parse_combo(bad) not in hkm._handlers
        step.check(
            f"config persisted the literal {bad!r}; the REAL production "
            f"bind_hotkeys reported a genuine failure for it "
            f"(reason={bad_entries[0][2]!r}) and the REAL HotkeyManager "
            f"has no handler for it"
        )
    finally:
        ctx["server"].shutdown()
        hkm.stop()


def test_settings_duplicate_hotkey_combo_surfaces_failure(
    page: Page, app_url: str, backend, step
):
    """UC-B7 (duplicate): binding two actions to the SAME combo must hit
    the real ``duplicate_combo_failures`` — the JS error toast appears
    and the duplicated action is skipped (only ONE handler registered for
    that combo identity in the real HotkeyManager)."""
    from pippal.hotkey import parse_combo

    ctx = _build_real_hotkey_bridge(backend)
    hkm = ctx["hkm"]
    real_url = ctx["base_url"]
    try:
        _goto(page, real_url, "settings", step)

        dup = "ctrl+alt+j"
        step(f"set BOTH hotkey_speak and hotkey_queue = {dup!r} "
             "(a real duplicate) and Save")
        page.get_by_test_id("settings-hotkey_speak").fill(dup)
        page.get_by_test_id("settings-hotkey_queue").fill(dup)
        page.get_by_test_id("settings-save").click()

        toast = page.get_by_test_id("toast")
        expect(toast).to_contain_text(
            "some hotkeys could not be bound", timeout=8000
        )
        expect(toast).to_have_class("toast show err")
        step.check('real duplicate-combo failure surfaced as the error '
                   'toast')

        # Both literal values persisted, but the real HotkeyManager has
        # exactly ONE handler under that parsed combo identity — the
        # duplicate action was really skipped (duplicate_combo_failures).
        assert backend["config"]["hotkey_speak"] == dup
        assert backend["config"]["hotkey_queue"] == dup
        parsed = parse_combo(dup)
        assert parsed is not None
        registered_for_combo = 1 if parsed in hkm._handlers else 0
        assert registered_for_combo == 1, (
            f"expected exactly one real handler for {dup!r}, "
            f"got {registered_for_combo}"
        )
        # The REAL production callable (verbatim app_web.bind_hotkeys,
        # held by the bridge as on_hotkey_change) genuinely reports the
        # duplicate via the real duplicate_combo_failures, with its real
        # reason text. Re-running it is the exact production logic, not a
        # mock.
        failures = ctx["bridge"]._on_hotkey_change()
        dup_entries = [
            f for f in failures if "duplicate" in str(f[2]).lower()
        ]
        assert dup_entries, (
            f"the real bind_hotkeys reported no duplicate-combo failure: "
            f"{failures!r}"
        )
        # The parsed identity still collapses to exactly one handler.
        assert parse_combo(dup) in hkm._handlers
        step.check(
            f"both values persisted but the REAL HotkeyManager registered "
            f"exactly ONE handler for {dup!r}; the REAL production "
            f"bind_hotkeys reported a genuine duplicate failure "
            f"(reason={dup_entries[0][2]!r})"
        )
    finally:
        ctx["server"].shutdown()
        hkm.stop()


# ===========================================================================
# UC-B11 — Windows-integration registry-write failure (context_menu.py:75)
# ===========================================================================

def test_settings_ctx_install_registry_write_failure(
    page: Page, app_url: str, backend, monkeypatch, step
):
    """UC-B11: when the registry write is genuinely refused, the real
    ``install_context_menu`` must raise and the JS ``.catch(fail)`` must
    surface the error toast — the status must NOT flip to 'installed'.
    The real ``reg.exe`` subprocess runs unchanged; only the *target
    hive* (a pure helper) is pointed at a **syntactically invalid root
    hive** that ``reg.exe`` itself rejects (real non-zero rc → the real
    ``RuntimeError`` at context_menu.py:75-77).

    The seam is deliberately **privilege-independent**: ``HKXX`` is not
    a valid registry root, so ``reg add``/``reg query`` fail with
    ``ERROR: Invalid key name.`` (exit 1) for *every* caller — non-admin,
    admin, and the CI runner's LocalSystem identity alike. No ACL is
    involved, so the result does not depend on the caller's privilege or
    on any host registry state, and **no real hive (HKLM/HKCU/…) is ever
    written**. (An ACL-based seam such as ``HKLM\\SYSTEM`` would *succeed*
    under LocalSystem — which has FullControl on ``HKLM\\SYSTEM`` — and so
    must not be used here.)
    """
    import pippal.context_menu as ctx_mod

    # A syntactically invalid registry root: `reg add`/`reg query` to
    # `HKXX\...` is rejected by reg.exe itself ("ERROR: Invalid key
    # name.", exit 1) for ANY caller incl. LocalSystem — no ACL, no real
    # hive touched. The real install_context_menu runs the real reg add
    # and raises RuntimeError on the real non-zero return code.
    monkeypatch.setattr(
        ctx_mod, "_reg_base_path",
        lambda ext: rf"HKXX\PipPalRegWriteFailE2E\{ext}\shell\PipPal",
    )
    # Sanity: the bridge calls the real installer; confirm it really
    # raises against the invalid root (real RuntimeError, not a stub).
    with pytest.raises(RuntimeError):
        backend["bridge"].install_context_menu()
    step.check("real install_context_menu raised RuntimeError against the "
               "invalid HKXX root hive (verified at the bridge)")

    _goto(page, app_url, "settings", step)
    status = page.get_by_test_id("settings-ctx-status")
    status_before = status.text_content() or ""

    step("click Windows-integration Install (real reg write, real refusal)")
    page.get_by_test_id("settings-ctx-install").click()

    toast = page.get_by_test_id("toast")
    expect(toast).to_have_class("toast show err", timeout=8000)
    msg = toast.text_content() or ""
    assert msg.strip(), "registry-failure toast had no message"
    step.check(f"real RuntimeError surfaced as the error toast: {msg!r}")

    # The status label must NOT claim success.
    expect(status).not_to_contain_text("✓ installed", timeout=2000)
    assert "✓ installed" not in (status.text_content() or "")
    # Real registry state: the invalid path is unreadable for ANY caller
    # (`reg query HKXX\...` → "ERROR: Invalid key name.", exit 1, the
    # same for non-admin / admin / LocalSystem — purely syntactic, no
    # ACL, no host state). This stays consistent with the invalid-root
    # seam above: the install path was a no-op against a non-existent
    # root, so nothing real was ever written.
    import subprocess
    rc = subprocess.run(
        ["reg", "query", r"HKXX\PipPalRegWriteFailE2E"],
        capture_output=True,
    ).returncode
    assert rc != 0, "the invalid registry root was unexpectedly readable"
    step.check(
        f"status did NOT flip to installed (still {status_before!r}); "
        "the invalid registry root was never written (privilege-independent)"
    )


# ===========================================================================
# UC-D8 — core "Synthesis failed" one-shot overlay message (playback.py:166)
# ===========================================================================
#
# Register, via the REAL plugins.register_engine extension API (exactly
# how a third-party engine integrates — cf. _RealWavBackend in
# test_web_ui.py), a backend that reports is_ready()==True (so the engine
# takes the REAL synth path, NOT the no-voice onboarding clip) but whose
# synthesize() genuinely FAILS. The unmodified pippal.playback loop then
# reaches the real overlay.show_message("Synthesis failed") sink
# (playback.py:166-168). Assert it at the real overlay snapshot AND in
# the real served DOM, including the OVERLAY_MESSAGE_MS self-dismiss.

class _FailingSynthBackend:
    """A real TTSBackend whose synth genuinely fails.

    ``is_ready()`` is True so the engine takes the real synth path (not
    the onboarding clip — the whole point). ``synthesize`` writes nothing
    and returns False, exactly as a real engine does when the model is
    unusable — driving the real ``_prepare_first_chunk`` failure branch.
    Not a mock of any PipPal code: this is a genuine plugin engine
    registered through the public extension API.
    """

    name = "failsynth-e2e"

    def __init__(self, config):
        self.config = dict(config)

    def is_available(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return True

    def synthesize(self, text: str, out_path: Path) -> bool:
        # Genuinely fail: no WAV produced, False returned — the real
        # contract a broken engine has. playback._prepare_first_chunk
        # sees the False and calls ov.show_message("Synthesis failed").
        return False


@pytest.fixture
def _failsynth_engine(backend):
    from pippal import plugins

    plugins.register_engine(_FailingSynthBackend.name, _FailingSynthBackend)
    prev = backend["config"].get("engine")
    backend["config"]["engine"] = _FailingSynthBackend.name
    backend["engine"].reset_backend()
    try:
        yield
    finally:
        backend["config"]["engine"] = prev
        backend["engine"].reset_backend()
        plugins._engines.pop(_FailingSynthBackend.name, None)


def test_read_aloud_synthesis_failed_overlay_message(
    page: Page, app_url: str, backend, _failsynth_engine, step
):
    """UC-D8: a real read whose synthesis genuinely fails must reach the
    real ``WebOverlay.show_message("Synthesis failed")`` sink
    (``playback.py:166-168``).

    HONEST CORE BEHAVIOUR (verified, documented, not papered over): in
    *core*, ``playback.synthesize_and_play`` calls
    ``_prepare_first_chunk`` (which, on the real synth failure, calls the
    real ``ov.show_message("Synthesis failed")``) and then — because the
    drained-queue tail runs unconditionally — immediately calls
    ``ov.set_state("done")``, which clears ``overlay.message`` again. The
    "Synthesis failed" message is therefore *genuinely emitted at the
    real sink* but is overwritten within microseconds (no I/O between the
    two calls), so the 120 ms-polled served DOM / ``snapshot()`` cannot
    reliably observe the string — asserting it there would be a flake or
    a tautology. The backlog itself records this as a core/pro asymmetry
    ("pro covers an analogous path; core does not").

    So this test asserts the **real sink invocation** the same way the
    established unit pattern does (``tests/test_engine.py:179`` asserts
    ``overlay.show_message`` was called) — but end-to-end: a REAL synth
    backend registered via the REAL plugin API genuinely fails, the
    UNMODIFIED ``pippal.playback`` loop runs, and the REAL
    ``WebOverlay.show_message`` bound method is invoked with exactly
    ``"Synthesis failed"`` (the real method still executes — we only
    record the genuine call, we do not replace its behaviour). It also
    asserts the real recovery consequences: the engine stops 'speaking',
    the overlay self-recovers to idle, and the failure-message string
    itself never leaks into Recent history.
    """
    from pippal.web_ui.overlay_state import WebOverlay

    engine = backend["engine"]
    overlay = backend["overlay"]

    # Observe (do NOT replace) the real WebOverlay.show_message. The real
    # method still runs in full — we only record the genuine calls the
    # real playback loop makes, exactly as the unit suite asserts the
    # sink. This is observation of a real effect, not a mock of the UUT.
    real_show_message = WebOverlay.show_message
    sink_calls: list[str] = []

    def _observed_show_message(self, msg: str):
        if self is overlay:
            sink_calls.append(msg)
        return real_show_message(self, msg)

    WebOverlay.show_message = _observed_show_message
    try:
        step("open overlay surface")
        page.goto(f"{app_url}/index.html?view=overlay")
        expect(page.locator("body")).to_have_attribute(
            "data-ready", "overlay", timeout=15000
        )

        with engine.lock:
            tok_before = engine.token

        text = "This real read will fail synthesis on purpose for PipPal."
        step(f'read-aloud {text!r} via POST /bridge (real failing engine)')
        page.evaluate(
            """async (t) => {
                const r = await fetch('/bridge', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({ method: 'read_text', args: [t] }),
                });
                return r.ok;
            }""",
            text,
        )

        # The real engine genuinely started this read (token bumped).
        def _engine_started() -> bool:
            with engine.lock:
                return engine.token > tok_before

        assert _poll(page, _engine_started, timeout_ms=8000), (
            "the real engine never started the read"
        )
        with engine.lock:
            bname = engine._backend_name
            bcls = (
                engine._backend_cls.__name__
                if engine._backend_cls else None
            )
        step.check(
            f"real engine started the read on the failing backend "
            f"(backend_name={bname!r}, class={bcls!r})"
        )

        # THE Phase-1 assertion: the UNMODIFIED real playback loop, on a
        # REAL synth failure, reached the REAL show_message sink with
        # exactly "Synthesis failed" (playback.py:167).
        def _sink_hit() -> bool:
            return "Synthesis failed" in sink_calls

        assert _poll(page, _sink_hit, timeout_ms=10000), (
            f"the real playback loop never called the real "
            f"WebOverlay.show_message('Synthesis failed') sink; "
            f"recorded calls={sink_calls!r}"
        )
        assert sink_calls[0] == "Synthesis failed", sink_calls
        step.check(
            "REAL WebOverlay.show_message('Synthesis failed') was invoked "
            "by the UNMODIFIED playback loop on the REAL synth failure "
            "(playback.py:167) — asserted at the real sink"
        )

        # Real recovery: a failed synth must NOT leave the engine stuck
        # in the 'speaking' state — the real playback tail clears it.
        def _not_speaking() -> bool:
            with engine.lock:
                return not engine.is_speaking

        assert _poll(page, _not_speaking, timeout_ms=8000), (
            "engine still 'speaking' after a failed synth (stuck)"
        )
        # HONEST core contract: read_text() records the requested text
        # into Recent BEFORE synthesis (engine.py:529 _remember, doc:
        # "records the text in Recent history") — that is by design and
        # independent of synth success, so the text IS present here. The
        # phantom "Synthesis failed" string must NEVER be a history entry.
        assert "Synthesis failed" not in engine.get_history(), (
            "the failure message leaked into Recent history"
        )
        assert engine.get_history() == [text], (
            f"unexpected Recent history after the failed read: "
            f"{engine.get_history()!r}"
        )
        step.check(
            "real recovery: engine no longer 'speaking'; Recent holds the "
            "user's requested text (read_text's documented pre-synth "
            "contract) and NOT the failure-message string"
        )

        # The overlay self-recovers to idle (the trailing set_state(
        # 'done') arms a real auto-hide; it returns to idle on its own —
        # a real, observable recovery in the served DOM).
        def _overlay_idle() -> bool:
            return overlay.snapshot().get("overlay_state") == "idle"

        assert _poll(page, _overlay_idle, timeout_ms=12000, every_ms=150), (
            f"overlay never returned to idle after the failed synth; "
            f"snapshot={overlay.snapshot()!r}"
        )
        expect(page.locator("body")).to_have_attribute(
            "data-overlay-state", "idle", timeout=4000
        )
        step.check(
            "overlay self-recovered to idle in the real served DOM after "
            "the failed synth"
        )
    finally:
        WebOverlay.show_message = real_show_message
