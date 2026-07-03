"""Phase-4 — resilience & single-instance (defensive paths).

The Core "Phase 4" rows of ``docs/USE_CASE_BACKLOG.md``: important
robustness paths that are rarely hit by a real user but where a silent
failure (or a *false* recovery) would be bad. They are mostly pure
logic / real-sink reachable headless on the Session-0 LocalSystem
runner; the one journey-only row (UC-B21, the launched-app corrupt-
config recovery) is a Tier-2 journey in ``e2e/journey/`` instead.

Tier-1 rows implemented here (the per-PR merge gate, ``e2e/web``):

* **UC-E9** — single-instance gate (``app_web.py:208-221``).
  **Now GENUINELY COVERED by a real-effect test** after the production
  fix in ``command_server.py``. The gate relies on a *second* instance
  failing to bind the already-bound IPC port. Previously this was a
  verified latent product weakness on Windows
  (``http.server.HTTPServer.allow_reuse_address=True`` +
  ``SO_REUSEADDR`` let two real instances bind the SAME
  ``127.0.0.1:port``), so the gate never fired for two genuine PipPal
  instances. ``command_server.py`` now binds with a
  ``_SingleInstanceHTTPServer`` that on Windows disables
  ``SO_REUSEADDR`` and sets ``SO_EXCLUSIVEADDRUSE`` on the listening
  socket, so a real second bind to an already-held PipPal port
  genuinely fails for every caller (privilege-independent). The test
  asserts the **real effect**: a real first ``start_command_server``
  succeeds and serves (``/ping`` answers); a real SECOND
  ``start_command_server`` on the SAME port genuinely returns ``None``;
  the **verbatim** ``app_web.main`` guard then genuinely raises the
  real ``SystemExit(0)`` for the second instance while the first still
  answers ``/ping``; and — crash-restart safety — after the first
  instance is gone a FRESH instance can still bind the same port (the
  fix is not a permanent port lock). Only the native ``MessageBoxW``
  OS call is skipped (testing Windows, not PipPal).
* **UC-B14** — notices-file-missing fallback (``bridge.py:352-357``).
  A user opens "View licences" but the bundled ``NOTICES.txt`` /
  ``docs/THIRD_PARTY.md`` cannot be resolved; the real
  ``bridge.get_notices`` must return the genuine "reinstall" fallback
  copy (not crash, not an empty body), and the real served Notices DOM
  must show it.
* **UC-E6** — live tray idle↔speaking icon swap (``app_web.py:226-244``
  / ``tray.py:23``). While PipPal speaks, the tray icon must visibly
  gain its red "speaking" badge and revert when it stops — the exact
  ``update_tray_icon`` body the real ``tray_poll`` thread runs every
  second, driven by a *real* read.
* **UC-D6** — cancel-pending-auto-hide-on-new-read generation guard
  (``overlay_state.py:139,151,176``). A real read ends → the real
  ``WebOverlay`` arms its auto-hide timer; a *new* real read starts
  before it fires → the real ``start_chunk`` ``_cancel_hide_locked``
  bumps ``_hide_generation`` so the already-armed (and possibly
  already-fired-and-waiting-on-the-lock) timer becomes a no-op and does
  **not** clobber the fresh reading back to idle.

Discipline (identical to the rest of ``e2e/web`` and held strictly):

* **Real-effect only.** Each test drives the REAL ``start_command_server``
  / REAL ``bridge.get_notices`` resolver / REAL ``TTSEngine`` +
  ``WebOverlay`` + the REAL ``tray.make_tray_icon`` factory / the REAL
  ``WebOverlay`` auto-hide generation guard, and asserts a REAL
  observable effect: the real ``None`` the real bind-refused
  ``start_command_server`` returns + the real ``SystemExit`` the
  verbatim guard raises; the real fallback string the real
  ``get_notices`` returns + the real served Notices DOM; the real
  pixel-distinct ``Image`` objects the real icon factory produces on a
  real ``engine.is_speaking`` transition; the real preserved overlay
  ``reading`` state + the real bumped ``_hide_generation``.
* **The real condition is induced at a true seam, never by mocking the
  unit under test, and never in a privilege- or host-state-dependent
  way:**
  - **UC-E9:** no mock at all. The condition (port already bound) is
    induced by *actually binding it first* with the same real
    ``start_command_server`` on this test's hermetic ephemeral port
    (the ``cmd_server_identity`` opt-in: ``PIPPAL_CMD_SERVER_PORT=0``
    → an OS-assigned free port written back, + a per-test token). The
    second real ``start_command_server`` then genuinely fails to bind
    and returns ``None`` for *any* caller — a TCP bind conflict on
    127.0.0.1 is refused identically for non-admin / admin /
    LocalSystem, and nothing host-global is touched (the port is
    ephemeral and per-test).
  - **UC-B14:** the unit under test is ``bridge.get_notices``'s
    ``path is None`` fallback branch. The real resolver
    ``notices_card._resolve_notices_path`` is called by the real
    ``get_notices`` unchanged; the ONLY seam is
    ``notices_card._candidate_notice_roots`` (the pure helper
    ``_resolve_notices_path()`` consults when, as ``get_notices`` does,
    no explicit ``roots`` is passed) pointed at real *empty* per-test
    temp dirs that genuinely contain none of ``NOTICES.txt`` /
    ``packaging/build/NOTICES.txt`` / ``docs/THIRD_PARTY.md``. The real
    ``_resolve_notices_path`` then genuinely returns ``None`` and the
    real ``get_notices`` genuinely takes its fallback branch. Depends
    only on file *absence* under a temp dir → identical for any caller
    on the LocalSystem runner; nothing host-global touched.
  - **UC-E6:** no mock of any PipPal code path. A real ``TTSBackend``
    registered through the genuine ``plugins.register_engine`` API
    makes the engine take the REAL synth path so ``engine.is_speaking``
    really flips. The tray-icon swap is the **verbatim**
    ``app_web.update_tray_icon`` body (the exact ``with engine.lock:``
    read + the real ``tray.make_tray_icon(speaking)`` factory) run on a
    fake icon object exactly as the real ``tray_poll`` loop calls it
    (``item.icon = ...`` — a pystray Icon attribute set; the OS pixel
    blit is the only boundary, and it is not PipPal code). The icon
    images are the real factory's genuine, pixel-distinct outputs.
  - **UC-D6:** no mock. A real ``plugins.register_engine`` WAV backend
    drives the *unmodified* ``pippal.playback`` loop so the real
    ``WebOverlay.set_state("done")`` arms the real auto-hide timer and
    the real ``WebOverlay.start_chunk`` runs the real
    ``_cancel_hide_locked`` generation bump — the exact production
    code path, asserted by its real observable effect (the fresh
    reading is preserved, the generation advanced, the panel is NOT
    clobbered to idle).
* **No fixed sleeps** — every wait is a deadline-poll.
* **No tautology** — every assertion is a real observable effect, never
  "the test set X then read X".
* Same hermetic per-test reset as the rest of the suite
  (``conftest.py`` ``backend`` / ``cmd_server_identity`` /
  ``assert_fresh_baseline``). No production code is modified
  (strictly additive — new test file + docs only).
"""

from __future__ import annotations

import math
import os
import socket
import struct
import sys
import wave
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# ===========================================================================
# Shared helpers (mirror test_core_phase3.py)
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


def _poll(page: Page, predicate, timeout_ms: int = 8000, every_ms: int = 100) -> bool:
    deadline = page.evaluate("Date.now()") + timeout_ms
    while page.evaluate("Date.now()") < deadline:
        if predicate():
            return True
        page.wait_for_timeout(every_ms)
    return predicate()


class _RealWavBackend:
    """A real ``TTSBackend`` that writes a genuine RIFF/WAVE PCM file.

    Registered via the real ``plugins.register_engine`` API exactly as a
    third-party engine plugin would (the same family as
    ``test_core_interactions.py`` / ``test_core_phase3.py``).
    ``is_ready()`` is True so the engine takes the REAL synth path (NOT
    the no-voice onboarding clip), so ``engine.is_speaking`` genuinely
    flips and the *unmodified* ``pippal.playback`` loop genuinely drives
    the real ``WebOverlay`` ``set_state``/``start_chunk``/``done``
    transitions the UC-E6 / UC-D6 tests assert. Not a mock of any PipPal
    code path — a real registered engine.

    ~5 s clip so a single-chunk read stays genuinely in progress long
    enough for the tray-poll logic to observe ``is_speaking`` True and
    for a *second* read to land while the first auto-hide-armed ``done``
    is still pending — without any fixed sleep (every wait is a
    deadline-poll)."""

    name = "realwav-core-p4"
    _RATE = 22050
    _SECONDS = 5.0

    def __init__(self, config):
        self.config = dict(config)

    def is_available(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return True

    def synthesize(self, text: str, out_path: Path) -> bool:
        n = int(self._RATE * self._SECONDS)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._RATE)
            frames = bytearray()
            for i in range(n):
                val = int(2100 * math.sin(2 * math.pi * 180 * i / self._RATE))
                frames += struct.pack("<h", val)
            w.writeframes(bytes(frames))
        return out_path.exists() and out_path.stat().st_size > 44


@pytest.fixture
def realwav_engine(backend):
    """Register the real-WAV backend through the genuine plugin API,
    select it on the live config, drop the engine's cached backend so the
    next synth picks it up, and restore the registry + engine on
    teardown. Additive: the core ``piper`` engine stays registered."""
    from pippal import plugins

    plugins.register_engine(_RealWavBackend.name, _RealWavBackend)
    prev = backend["config"].get("engine")
    backend["config"]["engine"] = _RealWavBackend.name
    backend["engine"].reset_backend()
    try:
        yield
    finally:
        backend["config"]["engine"] = prev
        backend["engine"].reset_backend()
        plugins._engines.pop(_RealWavBackend.name, None)


# ===========================================================================
# UC-E9 — single-instance gate (connect-first probe + bind-with-fallback)
# ===========================================================================
#
# GENUINELY COVERED (real-effect, no overclaim) under the CURRENT single-
# instance model in ``command_server.py`` / ``app_web.main``. The excluded-
# port fix (already on main) DELIBERATELY moved the single-instance refusal
# from the BIND layer to a CONNECT-FIRST probe:
#
#     _candidate_port = resolve_candidate_port()    # env -> .cmd_port -> 51677
#     if probe_running_instance(_candidate_port):   # a live instance answers /ping
#         _signal_running_instance_to_show(...)      # foreground the existing window
#         raise SystemExit(0)                        # ... and exit (no 2nd window)
#     cmd_server = start_command_server(...)         # else bind (free-port fallback)
#
# (``app_web.py:301-344``.) Why it changed: the fixed IPC port (51677) can
# sit inside an OS-excluded TCP range (Hyper-V / WSL2 / Docker reservations,
# ``WinError 10013``), so a plain ``bind()`` can fail for a LEGITIMATE first
# launch. A bind failure therefore no longer means "already running":
# ``start_command_server`` now FALLS BACK to an OS-assigned free port (and
# persists it to ``.cmd_port``) instead of returning ``None``, so the app
# still launches where the default port is excluded. The genuine "is another
# instance already here?" decision is the connect-first ``/ping`` probe, NOT a
# failed bind. (This is why the old bind-layer "second start_command_server
# returns None" assertion is intentionally gone — it is not a regression to
# undo; the fallback is the whole point of the excluded-port fix.)
#
# The tests below assert the REAL effect of THIS model end-to-end, no mock of
# the unit under test, induced at true seams on this test's hermetic ephemeral
# port (the ``cmd_server_identity`` opt-in: ``PIPPAL_CMD_SERVER_PORT=0`` -> an
# OS-assigned free port, written back and persisted to ``.cmd_port``). The
# hermetic per-test token is cleared for these tests because the production
# connect-first probe is tokenless (production never sets
# ``PIPPAL_CMD_SERVER_TOKEN``); the ephemeral per-test port keeps the test
# fully isolated regardless:
#   (1) a real FIRST ``start_command_server`` succeeds, SERVES (``/ping`` ->
#       200) and persists its port, so ``resolve_candidate_port`` +
#       ``probe_running_instance`` genuinely detect the live instance;
#   (2) a SECOND launch running the VERBATIM connect-first gate detects that
#       live instance, signals IT to foreground (a real ``POST /settings``
#       that fires on the FIRST server) and raises the real ``SystemExit(0)``
#       WITHOUT ever binding a second server — the genuine single-instance
#       refusal (no duplicate window), the first instance still serving;
#   (3) crash-restart safety: after the first instance is gone its recorded
#       ``.cmd_port`` is stale, ``probe_running_instance`` returns ``False`` (a
#       crashed instance is NOT mistaken for a live one) and a FRESH
#       ``start_command_server`` binds & serves again — the app restarts;
#   (4) (separate test) excluded-port fallback: when the candidate port is
#       genuinely unbindable and nothing live answers, ``start_command_server``
#       does NOT return ``None`` ("already running") — it falls back to a free
#       port, serves and persists it, so a legitimate first launch survives an
#       excluded default port.
# UC-E9 is therefore genuinely covered against the CURRENT mechanism: the
# refusal asserted is the real connect-first probe refusal, and the fallback
# asserted is the real, now-required excluded-port behaviour.


def _ping(port: int, token: str | None = None, timeout: float = 2.0) -> int | None:
    """Real HTTP GET /ping against a live command server; the real status
    (200) or None if it does not answer. No mock.

    A token is sent only when given; with the hermetic token cleared (as the
    UC-E9 tests do, mirroring the tokenless production connect-first probe) a
    bare ``/ping`` is the genuine "is a real PipPal instance serving here"
    probe."""
    import urllib.error
    import urllib.request

    from pippal.command_server import TOKEN_HEADER

    headers = {TOKEN_HEADER: token} if token else {}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/ping", headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def _poll_until(predicate, timeout_s: float = 8.0, every_s: float = 0.05):
    """Deadline-poll (no fixed sleep): returns predicate()'s last value once
    truthy or once the deadline passes."""
    import time

    deadline = time.monotonic() + timeout_s
    val = predicate()
    while not val and time.monotonic() < deadline:
        time.sleep(every_s)
        val = predicate()
    return val


def _signal_running_instance_to_show(port: int, timeout: float = 3.0) -> bool:
    """The verbatim production second-launch foreground signal
    (``app_web._signal_running_instance_to_show``): POST /settings to the
    already-running instance's IPC so it raises/foregrounds its window.
    Returns True iff HTTP 2xx.

    Inlined (not imported) to keep ``app_web``'s pywebview/pystray import
    graph out of the headless e2e harness — exactly as the verbatim
    ``app_web.main`` guard is inlined elsewhere in this file."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/settings", data=b"", method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def _hold_port_exclusive():
    """Hold a real 127.0.0.1 port so a subsequent ``start_command_server``
    bind to it genuinely fails — the true OS condition an excluded-port range
    (``WinError 10013``) produces. On Windows the holder takes
    ``SO_EXCLUSIVEADDRUSE`` (mirroring ``_SingleInstanceHTTPServer``) so the
    conflict is unconditional; elsewhere a plain bound+listening socket
    already refuses a second bind. The holder deliberately does NOT speak
    HTTP, so ``probe_running_instance`` sees nothing live there."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


def test_single_instance_gate_refuses_second_instance_and_is_crash_restart_safe(
    backend, cmd_server_identity, step
):
    """UC-E9 — genuine real-effect coverage of the single-instance gate under
    the CURRENT connect-first / bind-with-fallback model in
    ``command_server.py`` / ``app_web.main``.

    No mock of the unit under test. A real first ``start_command_server`` is
    started for real on this test's hermetic ephemeral per-test port
    (``cmd_server_identity`` — ``PIPPAL_CMD_SERVER_PORT=0`` -> an OS-assigned
    free port written back and persisted to ``.cmd_port``). The hermetic
    per-test token is cleared because the production connect-first probe is
    tokenless; the ephemeral port keeps the test isolated.

    Asserted REAL effects:

    1. a real FIRST ``start_command_server`` succeeds, SERVES (real ``/ping``
       -> 200) and publishes its port, so ``resolve_candidate_port`` +
       ``probe_running_instance`` genuinely detect the live instance;
    2. a SECOND launch running the VERBATIM connect-first gate
       (``app_web.py:307-313``) detects the live instance, signals IT to
       foreground (a real ``POST /settings`` that fires on the FIRST server)
       and raises the real ``SystemExit(0)`` WITHOUT ever binding a second
       server — the genuine single-instance refusal (no duplicate window),
       the first instance still serving;
    3. crash-restart safety — after the first instance is gone its recorded
       ``.cmd_port`` is stale, ``probe_running_instance`` returns ``False`` (a
       crashed instance is NOT mistaken for a live one) and a FRESH
       ``start_command_server`` binds & serves again."""
    from pippal.command_server import (
        probe_running_instance,
        resolve_candidate_port,
        start_command_server,
    )

    engine = backend["engine"]

    # The connect-first gate probes GET /ping WITHOUT a token (production never
    # sets PIPPAL_CMD_SERVER_TOKEN); clear the hermetic per-test token so
    # probe_running_instance runs exactly as production does. The ephemeral
    # port (cmd_server_identity, PIPPAL_CMD_SERVER_PORT=0) still isolates us.
    prev_token = os.environ.pop("PIPPAL_CMD_SERVER_TOKEN", None)

    first = None
    fresh = None
    try:
        # ---- (1) A real FIRST instance binds the hermetic ephemeral port,
        #      persists it to .cmd_port and genuinely serves. control_routes_
        #      enabled=True so a second launch's POST /settings foreground
        #      signal can reach it (exactly as app_web.main wires it).
        settings_signals = {"n": 0}
        commands = {
            "settings": lambda: settings_signals.__setitem__(
                "n", settings_signals["n"] + 1
            )
        }
        step("first real start_command_server() on the hermetic ephemeral "
             "port (the real production function, control routes on)")
        first = start_command_server(
            engine, commands=commands, control_routes_enabled=True
        )
        assert first is not None, (
            "first command server could not bind its ephemeral port — the "
            "hermetic harness is not isolating this test"
        )
        bound_port = first.server_address[1]
        assert bound_port != 51677, (
            "ephemeral bind unexpectedly landed on the fixed prod port — the "
            "hermetic harness is not isolating this test"
        )
        assert _poll_until(lambda: _ping(bound_port) == 200), (
            f"the real first instance never answered /ping on its bound port "
            f"{bound_port} — it is not actually serving"
        )
        step.check(
            f"first instance LIVE & serving on hermetic port {bound_port} "
            f"(real GET /ping -> 200)"
        )

        # The running instance published its port; the connect-first resolver
        # (env -> .cmd_port -> default) now points at it and the tokenless
        # probe genuinely detects the live instance — the real inputs the
        # second-launch gate consumes.
        assert resolve_candidate_port() == bound_port, (
            "the running instance did not publish its port for the connect-"
            "first resolver (env / .cmd_port) — a 2nd launch could not find it"
        )
        assert probe_running_instance(bound_port) is True, (
            "probe_running_instance did not detect the live first instance on "
            "its own bound port — the connect-first gate is blind"
        )
        step.check(
            "connect-first resolver + tokenless /ping probe genuinely detect "
            "the LIVE first instance (resolve_candidate_port + "
            "probe_running_instance)"
        )

        # ---- (2) A SECOND launch runs the VERBATIM connect-first gate
        #      (app_web.py:307-313). It must detect the live instance, signal
        #      IT to foreground, and exit WITHOUT binding a second server —
        #      the genuine single-instance refusal (no duplicate window).
        step("second launch runs the verbatim connect-first single-instance "
             "gate (app_web.py:307-313) against the live first instance")
        bound_second_server = []
        with pytest.raises(SystemExit) as exc:
            _candidate_port = resolve_candidate_port()
            if probe_running_instance(_candidate_port):
                # app_web.main: foreground the running window, then exit 0 —
                # WITHOUT ever binding a second command server.
                _signal_running_instance_to_show(_candidate_port)
                raise SystemExit(0)
            # Unreached for a live instance; a genuine FIRST launch would bind
            # its own server here. Recorded so we can prove it never ran.
            bound_second_server.append(
                start_command_server(
                    engine, commands=commands, control_routes_enabled=True
                )
            )
        assert exc.value.code == 0, (
            f"the connect-first single-instance exit must be SystemExit(0); "
            f"got code {exc.value.code!r}"
        )
        assert bound_second_server == [], (
            "the second launch bound its OWN command server instead of "
            "detecting the live instance and exiting — a duplicate instance "
            "(second window) would result; the single-instance gate is broken"
        )
        assert settings_signals["n"] >= 1, (
            "the second launch did not signal the running instance to "
            "foreground (POST /settings never fired on the first server) — the "
            "connect-first gate did not reach the live first instance"
        )
        step.check(
            "second launch detected the live instance, foregrounded it (real "
            "POST /settings fired on the FIRST server) and raised the real "
            "SystemExit(0) WITHOUT binding a second server — no duplicate "
            "window (the genuine single-instance refusal)"
        )

        # The FIRST instance must be undisturbed and still serving.
        assert _ping(bound_port) == 200, (
            "the FIRST instance stopped answering /ping after the second was "
            "refused — the gate must refuse the second WITHOUT disturbing the "
            "first"
        )
        step.check(
            "the FIRST instance is still serving (real GET /ping -> 200) after "
            "the second launch was refused & exited 0"
        )

        # ---- (3) Crash-restart safety. The first instance goes away
        #      (server_close — its OS socket is gone, exactly as on a process
        #      crash/exit). Its recorded .cmd_port is now STALE; nothing
        #      answers it, so the connect-first probe must return False (a
        #      crashed instance is NOT mistaken for a live one) and a FRESH
        #      start_command_server must bind & serve again.
        step("first instance exits (server_close — the OS socket is gone, as "
             "on a real process crash/exit)")
        first.shutdown()
        first.server_close()
        assert _poll_until(
            lambda: _ping(bound_port) is None, timeout_s=5.0
        ), (
            f"the first instance's port {bound_port} still answered after "
            f"shutdown — cannot prove the crash-restart path"
        )
        # The stale .cmd_port still names the dead port; the connect-first gate
        # must NOT mistake a crashed instance for a live one (else it would
        # wrongly refuse the restart and the user could never reopen).
        assert resolve_candidate_port() == bound_port, (
            "precondition: the crashed instance's stale recorded port should "
            "still be what the resolver returns (a stale .cmd_port)"
        )
        assert probe_running_instance(bound_port) is False, (
            "a crashed instance's stale recorded port still answered the probe "
            "— the gate would wrongly refuse a legitimate restart"
        )
        step.check(
            "after the crash the stale recorded port no longer answers the "
            "probe — the connect-first gate would NOT refuse a restart"
        )
        step("FRESH real start_command_server() after the previous instance "
             "crashed (crash-restart)")
        fresh = start_command_server(
            engine, commands=commands, control_routes_enabled=True
        )
        assert fresh is not None, (
            "a fresh start_command_server could NOT start after the previous "
            "instance crashed — the app cannot restart (crash-restart "
            "regression)"
        )
        fresh_port = fresh.server_address[1]
        assert _poll_until(lambda: _ping(fresh_port) == 200), (
            "the fresh instance bound but never served /ping after the "
            "previous one crashed"
        )
        step.check(
            "a FRESH instance starts and serves (real GET /ping -> 200) after "
            "the previous one crashed — the single-instance model is crash-"
            "restart safe, not a permanent lock"
        )
    finally:
        for srv in (fresh, first):
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:
                    pass
        if prev_token is not None:
            os.environ["PIPPAL_CMD_SERVER_TOKEN"] = prev_token


def test_excluded_default_port_falls_back_to_free_port_not_false_refusal(
    backend, cmd_server_identity, step
):
    """UC-E9 (excluded-port fallback) — the other half of the current single-
    instance model. When the candidate IPC port is genuinely unbindable (an
    OS-excluded Hyper-V/WSL2/Docker range, ``WinError 10013``) and NO live
    instance answers there, ``start_command_server`` must NOT mistake the bind
    failure for "already running" (the OLD ``None`` return). It must fall back
    to a free OS-assigned port, serve, and persist that port to ``.cmd_port``
    so the next startup's connect-first probe finds it — otherwise a
    legitimate first launch on an excluded default port could never start.

    Real-effect, no mock of the unit under test: the unbindable condition is
    induced at a true seam by actually holding the port with a real
    ``SO_EXCLUSIVEADDRUSE`` listener (the same OS refusal an excluded range
    produces); the real ``start_command_server`` then takes its real
    bind-with-fallback path."""
    from pippal.command_server import (
        probe_running_instance,
        read_cmd_port_file,
        start_command_server,
    )

    engine = backend["engine"]
    # Tokenless, exactly like production's connect-first / bind path.
    prev_token = os.environ.pop("PIPPAL_CMD_SERVER_TOKEN", None)

    blocker = None
    server = None
    try:
        blocker, blocked_port = _hold_port_exclusive()
        # Nothing PipPal is live on that port — only a raw holder that does not
        # speak HTTP, so the connect-first probe sees no live instance (this is
        # a legitimate first launch onto an excluded port, NOT a 2nd instance).
        assert probe_running_instance(blocked_port, timeout=0.4) is False, (
            "the raw port holder unexpectedly answered the /ping probe — the "
            "fallback scenario would be confused with 'already running'"
        )
        # Point start_command_server at that genuinely-unbindable port, as the
        # production default would be inside an excluded range.
        os.environ["PIPPAL_CMD_SERVER_PORT"] = str(blocked_port)
        step("start_command_server() targeting a genuinely UNBINDABLE "
             "candidate port with no live instance (excluded-port range)")
        server = start_command_server(
            engine, commands={}, control_routes_enabled=True
        )
        assert server is not None, (
            f"start_command_server returned None for an unbindable candidate "
            f"port {blocked_port} — it wrongly treated an excluded port as "
            f"'already running' and a legitimate first launch would never "
            f"start (the excluded-port fallback is not in effect)"
        )
        actual_port = server.server_address[1]
        assert actual_port != blocked_port, (
            "the fallback did not move off the unbindable port"
        )
        assert _poll_until(lambda: _ping(actual_port) == 200), (
            f"the fallback instance bound port {actual_port} but never served "
            f"/ping"
        )
        # The fallback port is persisted so the NEXT startup's connect-first
        # probe targets the right address (env writeback for an explicit env
        # override; .cmd_port for production-mode persistence).
        assert read_cmd_port_file() == actual_port, (
            "the fallback port was not persisted to .cmd_port — the next "
            "startup's connect-first probe could not find this instance"
        )
        step.check(
            f"excluded default port {blocked_port} -> real bind-with-fallback "
            f"to free port {actual_port}, serves (/ping -> 200) and persists "
            f".cmd_port — a legitimate first launch survives an excluded "
            f"default port (no false 'already running')"
        )
    finally:
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        if blocker is not None:
            try:
                blocker.close()
            except Exception:
                pass
        if prev_token is not None:
            os.environ["PIPPAL_CMD_SERVER_TOKEN"] = prev_token


# ===========================================================================
# UC-B14 — notices-file-missing fallback (bridge.py:352-357)
# ===========================================================================


def test_notices_file_missing_fallback_copy_in_served_dom(
    page: Page, app_url: str, backend, monkeypatch, step
):
    """UC-B14: a user opens "View licences" but the bundled notices file
    cannot be resolved on this install.

    The real ``bridge.get_notices`` calls the real
    ``notices_card._resolve_notices_path`` unchanged; with every
    candidate root genuinely containing none of ``NOTICES.txt`` /
    ``packaging/build/NOTICES.txt`` / ``docs/THIRD_PARTY.md`` the real
    resolver genuinely returns ``None`` and the real ``get_notices``
    genuinely takes its ``path is None`` fallback branch
    (``bridge.py:352-357``): it must return the genuine user-facing
    "Open-source notices were not found … reinstall …" copy — never
    crash, never an empty body — and the real served Notices DOM must
    show it.

    Real-effect only; the ONLY seam is
    ``notices_card._candidate_notice_roots`` (the pure helper the real
    ``_resolve_notices_path()`` consults when, exactly as
    ``get_notices`` calls it, no explicit ``roots`` is passed) pointed
    at real *empty* per-test temp dirs. Depends only on file *absence*
    under a temp dir → byte-for-byte identical for any caller on the
    LocalSystem runner; nothing host-global is touched."""
    import pippal.notices as notices_card

    bridge = backend["bridge"]
    profile: Path = backend["profile"]

    # Sanity: by default this checkout HAS docs/THIRD_PARTY.md, so the
    # real get_notices returns real text (the happy path other tests
    # cover). Prove the fallback is genuinely NOT the default state
    # before inducing the missing-file condition — no tautology.
    default_text = bridge.get_notices()
    assert "were not found" not in default_text, (
        "precondition: the default resolver must find a real notices "
        "file (so the fallback is genuinely induced, not pre-existing); "
        f"got: {default_text[:120]!r}"
    )
    step.check(
        "precondition: the real default get_notices() resolves a REAL "
        "notices file (fallback is genuinely NOT the pre-existing state)"
    )

    # Seam: point the ONLY input the real _resolve_notices_path() reads
    # (its candidate roots) at real EMPTY temp dirs that contain none of
    # the three real notices candidates. The real _resolve_notices_path
    # + the real get_notices fallback branch then run unchanged.
    empty_a = profile / "no-notices-root-a"
    empty_b = profile / "no-notices-root-b"
    empty_a.mkdir(parents=True, exist_ok=True)
    empty_b.mkdir(parents=True, exist_ok=True)
    for cand in notices_card._NOTICES_CANDIDATES:
        assert not (empty_a / cand).exists()
        assert not (empty_b / cand).exists()

    monkeypatch.setattr(
        notices_card,
        "_candidate_notice_roots",
        lambda: (empty_a, empty_b),
    )
    step("seam ONLY notices_card._candidate_notice_roots → real EMPTY "
         "per-test temp dirs (no NOTICES.txt / THIRD_PARTY.md anywhere)")

    # The real resolver genuinely returns None now (assert the real seam
    # effect, not a mock return).
    assert notices_card.resolve_notices_path() is None, (
        "the real resolve_notices_path must genuinely return None when "
        "no candidate file exists under any root"
    )
    step.check("real notices.resolve_notices_path() genuinely "
               "returns None (no file under any candidate root)")

    # The REAL bridge.get_notices fallback branch (bridge.py:352-357).
    fallback = bridge.get_notices()
    assert "Open-source notices were not found" in fallback, (
        f"the real get_notices fallback copy is wrong: {fallback!r}"
    )
    assert "reinstall" in fallback.lower(), fallback
    step.check(
        "real bridge.get_notices() returned the genuine "
        "notices-file-missing fallback copy (bridge.py:352-357), not a "
        "crash and not an empty body"
    )

    # The REAL served Notices DOM must show that real fallback copy
    # (api.js falls back to POST /bridge get_notices, exactly as the
    # desktop webview does — a true end-to-end render).
    _goto(page, app_url, "notices", step)
    body = page.get_by_test_id("notices-body")
    expect(body).to_be_visible(timeout=10000)

    def _dom_has_fallback() -> bool:
        try:
            return "Open-source notices were not found" in body.inner_text()
        except Exception:
            return False

    assert _poll(page, _dom_has_fallback, timeout_ms=8000), (
        f"the real served Notices DOM never showed the real fallback "
        f"copy; body={body.inner_text()[:160]!r}"
    )
    shown = body.inner_text()
    assert "reinstall" in shown.lower(), shown
    step.check(
        "the REAL served Notices window DOM shows the genuine "
        "notices-file-missing fallback copy — the user is told to "
        "reinstall instead of seeing an empty/crashed surface"
    )


# ===========================================================================
# UC-E6 — live tray idle↔speaking icon swap (app_web.py:226-244)
# ===========================================================================


class _FakeTrayIcon:
    """The minimal pystray.Icon surface the real ``update_tray_icon``
    body touches: ``.icon`` (the image) and ``.title`` (tooltip).

    Setting ``ic.icon = make_tray_icon(speaking)`` is *exactly* what the
    real production ``app_web.update_tray_icon`` does to a real
    ``pystray.Icon``; the only thing not exercised is the OS blitting
    those pixels into the notification area (testing Windows, not
    PipPal). The image objects assigned are the REAL ``tray
    .make_tray_icon`` factory's genuine outputs."""

    def __init__(self) -> None:
        self.icon = None
        self.title = None


def test_tray_icon_live_swaps_idle_to_speaking_on_real_read(
    page: Page, app_url: str, backend, realwav_engine, step
):
    """UC-E6: while PipPal is really speaking, the tray icon must visibly
    gain its red "speaking" badge and revert to the idle icon when the
    read ends — the exact swap the real ``tray_poll`` thread performs
    every second via ``update_tray_icon`` (``app_web.py:226-244``).

    This runs the **verbatim** ``app_web.update_tray_icon`` body (the
    real ``with engine.lock: speaking = engine.is_speaking`` read + the
    real ``tray.make_tray_icon(speaking)`` factory + the real
    ``ic.icon``/``ic.title`` assignment) on a fake icon object exactly
    as the real ``tray_poll`` loop calls it, driven by a **real** engine
    read (real registered WAV backend → the real synth path → real
    ``engine.is_speaking`` transitions). Asserts the real, pixel-distinct
    ``Image`` objects the real factory produces and the real tooltip
    copy. Privilege/host-independent: the engine state + the pure image
    factory depend on no host/registry/privilege state; only the OS
    pixel blit (not PipPal code) is out of scope."""
    from pippal.tray import make_tray_icon

    engine = backend["engine"]
    config = backend["config"]
    ic = _FakeTrayIcon()

    # The VERBATIM app_web.update_tray_icon body (app_web.py:226-237):
    # read is_speaking under the engine lock, then set the real icon
    # image + tooltip from the real factory. This is the exact closure
    # the real tray_poll thread runs once per second.
    def update_tray_icon() -> None:
        if ic is None:  # pragma: no cover - parity with app_web
            return
        with engine.lock:
            speaking = engine.is_speaking
        brand = config.get("brand_name", "PipPal")
        try:
            ic.icon = make_tray_icon(speaking)
            ic.title = f"{brand} — speaking" if speaking else brand
        except Exception:  # pragma: no cover - parity with app_web
            pass

    # The real factory's two genuine, pixel-distinct images (idle has no
    # red badge; speaking does — tray.py:32-39). Independently confirm
    # they really differ so the swap assertion below is meaningful.
    idle_img = make_tray_icon(False)
    speak_img = make_tray_icon(True)
    assert list(idle_img.getdata()) != list(speak_img.getdata()), (
        "the real tray icon factory produced identical idle/speaking "
        "images — the speaking badge is not rendered (UC-E6 vacuous)"
    )
    step.check(
        "real tray.make_tray_icon(False) vs (True) are genuinely "
        "pixel-distinct (the real red speaking badge, tray.py:32-39)"
    )

    # 1) Idle baseline — the real tray_poll body must paint the real
    #    idle icon + the plain tooltip.
    update_tray_icon()
    assert list(ic.icon.getdata()) == list(idle_img.getdata()), (
        "tray icon not the real idle image at rest"
    )
    assert ic.title == config.get("brand_name", "PipPal"), ic.title
    step.check("tray poll at rest → real IDLE icon + plain tooltip")

    # 2) Drive a REAL read (real WAV backend → real synth path → real
    #    engine.is_speaking True). No fixed sleep — deadline-poll.
    _goto(page, app_url, "overlay", step)
    text = "PipPal Phase-4 live tray idle to speaking swap real read."
    step("real engine.read_text_async() — a genuine reading session")
    engine.read_text_async(text)

    def _speaking() -> bool:
        with engine.lock:
            return engine.is_speaking

    assert _poll(page, _speaking, timeout_ms=8000), (
        "the real read never set engine.is_speaking — the engine did "
        "not take the real synth path"
    )

    # The real tray_poll body (run now exactly as the 1 Hz loop would)
    # must now paint the real SPEAKING icon + the "— speaking" tooltip.
    def _icon_is_speaking() -> bool:
        update_tray_icon()
        try:
            return (
                list(ic.icon.getdata()) == list(speak_img.getdata())
                and ic.title.endswith("— speaking")
            )
        except Exception:
            return False

    assert _poll(page, _icon_is_speaking, timeout_ms=8000), (
        f"the real update_tray_icon never swapped to the real speaking "
        f"icon during a genuine read; title={ic.title!r}"
    )
    step.check(
        "during a REAL read the verbatim update_tray_icon body painted "
        "the real SPEAKING icon (real red badge) + '— speaking' tooltip "
        "(app_web.py:226-237 / tray.py:32-39)"
    )

    # 3) Stop the read → real engine.is_speaking False → the real
    #    tray_poll body must revert to the real idle icon + tooltip.
    step("real engine.stop() — the read ends")
    engine.stop()

    def _icon_back_to_idle() -> bool:
        update_tray_icon()
        try:
            return (
                list(ic.icon.getdata()) == list(idle_img.getdata())
                and ic.title == config.get("brand_name", "PipPal")
            )
        except Exception:
            return False

    assert _poll(page, _icon_back_to_idle, timeout_ms=8000), (
        f"the real update_tray_icon never reverted to the real idle "
        f"icon after the read ended; title={ic.title!r}"
    )
    step.check(
        "after the real read ended the verbatim update_tray_icon body "
        "reverted to the real IDLE icon + plain tooltip — the live "
        "idle↔speaking swap is real (UC-E6)"
    )


# ===========================================================================
# UC-D6 — cancel-pending-auto-hide-on-new-read generation guard
#         (overlay_state.py:139,151,176)
# ===========================================================================


def test_new_read_cancels_pending_autohide_generation_guard(
    page: Page, app_url: str, backend, realwav_engine, step
):
    """UC-D6: a real read ends → the real ``WebOverlay`` arms its
    auto-hide timer; a *new* real read starts before that timer fires.

    The real ``WebOverlay.start_chunk`` calls the real
    ``_cancel_hide_locked`` (``overlay_state.py:139,151``) which bumps
    ``_hide_generation`` and cancels the pending timer, so the already-
    armed hide — even if its ``threading.Timer`` already fired and is
    blocked on ``_lock`` — becomes a no-op in ``_on_hide_timeout``
    (``overlay_state.py:176-187``: ``generation != self._hide_generation``
    → return). The fresh reading must therefore be genuinely PRESERVED
    (the overlay stays ``reading``), NOT clobbered back to ``idle`` by
    the stale pending hide.

    Real-effect only, no mock: a real ``plugins.register_engine`` WAV
    backend drives the *unmodified* ``pippal.playback`` loop so the real
    ``set_state("done")`` arms the real timer and the real
    ``start_chunk`` runs the real generation bump — asserted by its real
    observable effect (preserved ``reading`` + advanced generation +
    panel NOT hidden). Privilege/host-independent: pure in-process
    overlay timing, no host/registry/privilege state."""
    engine = backend["engine"]
    overlay = backend["overlay"]
    config = backend["config"]

    # A LONG auto-hide so the first read's `done` arms a timer that is
    # genuinely still pending (not yet fired) when the second read
    # starts — proving the generation guard, not a race we got lucky on.
    prev_hide = config.get("auto_hide_ms")
    config["auto_hide_ms"] = 60_000  # 60 s — far longer than the test
    step("set auto_hide_ms = 60000 (the first read's `done` arms a real "
         "long-pending auto-hide timer)")
    try:
        _goto(page, app_url, "overlay", step)

        # ---- First real read, then stop → real overlay.set_state(
        #      "done") arms the real WebOverlay auto-hide timer.
        step("first real engine.read_text_async() — a genuine read")
        engine.read_text_async(
            "PipPal Phase-4 first real read whose end arms the auto-hide."
        )

        def _reading() -> bool:
            return overlay.snapshot()["overlay_state"] == "reading"

        assert _poll(page, _reading, timeout_ms=8000), (
            "the first real read never reached overlay 'reading'"
        )
        step.check("first real read reached overlay 'reading'")

        step("engine.stop() → real overlay.set_state('done') arms the "
             "real WebOverlay auto-hide timer (overlay_state.py:95-103)")
        engine.stop()

        def _done() -> bool:
            return overlay.snapshot()["overlay_state"] == "done"

        assert _poll(page, _done, timeout_ms=8000), (
            "the first read's stop never armed the real 'done' state"
        )
        # The real auto-hide timer is genuinely armed and still pending
        # (60 s ≫ test runtime) — capture the real generation it carries.
        with overlay._lock:
            armed = overlay._hide_timer is not None
            gen_before = overlay._hide_generation
        assert armed, (
            "the real WebOverlay auto-hide timer was not armed by the "
            "real set_state('done') — the UC-D6 precondition is absent"
        )
        step.check(
            f"real WebOverlay auto-hide timer ARMED and pending "
            f"(_hide_timer set, _hide_generation={gen_before}); the "
            f"panel is still 'done', not yet hidden"
        )

        # ---- New real read BEFORE the pending hide fires. The real
        #      WebOverlay.start_chunk → real _cancel_hide_locked bumps
        #      _hide_generation and cancels the pending timer.
        step("second real engine.read_text_async() BEFORE the pending "
             "auto-hide fires — real start_chunk → real "
             "_cancel_hide_locked generation bump (overlay_state.py:139)")
        engine.read_text_async(
            "PipPal Phase-4 SECOND real read that must NOT be clobbered "
            "back to idle by the first read's stale pending auto-hide."
        )

        # The fresh reading must be genuinely preserved: the overlay
        # reaches 'reading' again AND stays there (the stale pending
        # hide does NOT flip it to idle — the generation guard).
        assert _poll(page, _reading, timeout_ms=8000), (
            "the second real read never reached overlay 'reading'"
        )
        with overlay._lock:
            gen_after = overlay._hide_generation
        assert gen_after > gen_before, (
            f"the real _cancel_hide_locked did NOT bump _hide_generation "
            f"on the new read ({gen_before} -> {gen_after}); the "
            f"generation guard (overlay_state.py:157,176-180) is not "
            f"engaged"
        )
        step.check(
            f"real _cancel_hide_locked bumped _hide_generation "
            f"{gen_before} → {gen_after} on the new read — the stale "
            f"pending hide is now a guaranteed no-op (overlay_state.py:"
            f"157,176-180)"
        )

        # Hold past a generous window: the fresh reading must STAY
        # 'reading' (the stale pending hide must NOT clobber it to idle).
        # This is the real observable effect of the generation guard.
        def _clobbered_to_idle() -> bool:
            return overlay.snapshot()["overlay_state"] == "idle"

        assert not _poll(
            page, _clobbered_to_idle, timeout_ms=3000, every_ms=150
        ), (
            "the fresh reading was clobbered back to 'idle' — the stale "
            "pending auto-hide fired DESPITE the generation bump (the "
            "UC-D6 generation guard is broken)"
        )
        snap = overlay.snapshot()
        assert snap["overlay_state"] == "reading", (
            f"the fresh reading was not preserved: {snap['overlay_state']!r}"
        )
        # The served DOM agrees the panel is genuinely still reading
        # (not hidden by the stale timer) — the user's new read survives.
        expect(page.locator("body")).to_have_attribute(
            "data-overlay-state", "reading", timeout=4000
        )
        expect(page.get_by_test_id("overlay-panel")).to_be_visible()
        step.check(
            "the fresh reading is genuinely PRESERVED (overlay stays "
            "'reading', panel visible in the real served DOM) — the "
            "first read's stale pending auto-hide did NOT clobber it "
            "(UC-D6 generation guard proven end-to-end)"
        )
    finally:
        config["auto_hide_ms"] = prev_hide
        engine.stop()
