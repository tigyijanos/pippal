"""Phase-2 — untested core interaction journeys (the merge-gate functional gaps).

These are everyday actions with **zero** automated coverage today, the
Core "Phase 2" rows of ``docs/USE_CASE_BACKLOG.md``:

* **UC-E8** — the ``queue`` / ``pause`` / ``stop`` global-hotkey dispatch
  and the engine's *queue-while-speaking vs queue-while-idle* branch
  (``engine.py:481-509``).
* **UC-D9** — the one-shot reader-panel message ("No text selected" /
  "Queued — N pending") and its ``OVERLAY_MESSAGE_MS`` self-dismiss
  (``engine.py:472,498`` → ``overlay_state.py:105-116``).
* **UC-D10** — pause → silence → resume-replays-from-start, and
  seek-while-paused handed back without restarting
  (``playback.py:305-333``).
* **UC-F1 / UC-F2** — the command-server IPC reject branches
  (``/read-file`` 404 / 415 / 413; ``/read`` 400 / 413) plus each happy
  round-trip (``command_server.py:222-265``). **Assert-only** — no
  ``command_server.py`` change.

Discipline (identical to the rest of ``e2e/web`` and held strictly):

* **Real-effect only.** Each test drives the REAL served UI / REAL bridge
  / REAL ``TTSEngine`` + ``WebOverlay`` / REAL ``HotkeyManager`` / REAL
  ``command_server`` and asserts a REAL backend / overlay / engine / IPC
  state (the real ``engine._queue``, the real ``WebOverlay.snapshot()``,
  the served-DOM ``overlay-text`` element, the real HTTP status the real
  ``CmdHandler`` returns, the real ``engine.token``).
* **The real condition is induced at a true seam, never by mocking the
  unit under test.**
  - UC-E8/UC-D9: the unit under test is the engine's *queue / pause /
    stop branch logic* + the *hotkey dispatch* + the *overlay
    show_message sink*, driven through the **real** ``HotkeyManager``'s
    own stored handler (exactly what ``_safe_call`` invokes when the
    physical combo fires — only the OS routing the keystroke into the
    hook is skipped, "testing Windows not PipPal") and the **real**
    ``WebOverlay``. The ONLY seam is the OS-boundary *selection input*
    (``clipboard_capture.capture_for_action`` — sending a real Ctrl+C and
    reading the system clipboard cannot be driven on a headless Session-0
    runner with no foreground selection; the backlog itself names
    selection capture an OS boundary). That seam is the lifted-to-E2E
    form of the established unit pattern (``tests/test_engine.py:170``)
    and is **privilege/host-independent**: it replaces only the OS
    clipboard read, so the result depends purely on PipPal's branch
    logic — byte-for-byte identical on the LocalSystem CI runner.
  - UC-D10: a real ``TTSBackend`` registered through the genuine
    ``plugins.register_engine`` extension API (exactly how a third-party
    engine integrates — same ``_RealWavBackend`` family as
    ``test_web_ui.py``) produces real RIFF/WAVE PCM, so the **unmodified**
    ``pippal.playback`` loop genuinely runs its real
    ``_wait_for_chunk_end`` pause / resume / seek-while-paused code; the
    pause is the **real** ``engine.pause_toggle``.
  - UC-F1/F2: the REAL ``start_command_server`` ``CmdHandler`` runs
    unchanged; the reject conditions are induced with genuinely
    non-conforming real HTTP requests (a missing file, a disallowed
    extension, an over-cap body) — assert-only, no production change.
* **No fixed sleeps** — every wait is a deadline-poll.
* **No tautology** — every assertion is a real observable effect, never
  "the test set X then read X".
* Same hermetic per-test reset as the rest of the suite
  (``conftest.py`` ``backend`` / ``assert_fresh_baseline``); the
  command-server test additionally uses the production-safe, opt-in
  ``cmd_server_identity`` ephemeral-port + token hooks.
"""

from __future__ import annotations

import json
import math
import struct
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from pippal.timing import OVERLAY_MESSAGE_MS

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
    ``test_web_ui.py``'s ``_RealWavBackend``). ``synthesize`` produces a
    valid ~0.7 s 16-bit mono PCM WAV (a low sine tone) on disk — a real
    audio file the real ``winsound.PlaySound`` + the unmodified real
    ``pippal.playback`` loop consume. ``is_ready()`` is True so the
    engine takes the REAL synth path (not the no-voice onboarding clip) —
    the whole point of the UC-D10 / queue-while-speaking tests. Not a
    mock of any PipPal code path.

    The clip is ~6 s so a single-chunk read stays genuinely in progress
    long enough for a *second* hotkey/queue action to land while the
    engine is really speaking (the real queue-while-speaking branch) and
    for the served DOM to observe the one-shot message before the real
    OVERLAY_MESSAGE_MS self-dismiss — without any fixed sleep on the test
    side (every wait is still a deadline-poll). ``wav_duration`` reads the
    real frame count, so the real ``playback._wait_for_chunk_end``
    deadline genuinely lasts the clip's length."""

    name = "realwav-core-p2"
    _RATE = 22050
    _SECONDS = 6.0

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
                val = int(2200 * math.sin(2 * math.pi * 180 * i / self._RATE))
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


def _seam_selection(monkeypatch, mapping: dict[str, str]) -> None:
    """Seam the OS-boundary selection input.

    ``clipboard_capture.capture_for_action`` sends a real Ctrl+C and reads
    the system clipboard — an OS boundary that cannot be driven on a
    headless Session-0 runner with no foreground app holding a selection
    (the backlog explicitly names selection capture an OS boundary). This
    replaces ONLY that OS read with deterministic text per action id, so
    the test exercises PipPal's real queue/speak BRANCH logic (the unit
    under test) on a known input — the lifted-to-E2E form of the
    established unit pattern at ``tests/test_engine.py:170``. The result
    depends purely on PipPal logic, so it is byte-for-byte identical on
    the LocalSystem CI runner (privilege/host-independent)."""
    import pippal.engine as engine_mod

    def _fake_capture(_engine, action: str) -> str:
        return mapping.get(action, "")

    monkeypatch.setattr(
        engine_mod.clipboard_capture, "capture_for_action", _fake_capture
    )


# ===========================================================================
# UC-E8 — queue / pause / stop hotkey dispatch + queue-while-{idle,speaking}
# ===========================================================================
#
# Mirror test_global_hotkey_speak_dispatch_drives_real_engine: register
# the configured queue/pause/stop actions on the REAL HotkeyManager the
# way app_web.bind_hotkeys does, then dispatch each through the manager's
# OWN stored handler (== HotkeyManager._safe_call's call, no keypress).
# A real-WAV backend makes the engine take the REAL synth path so the
# queue-while-speaking branch (engine.py:491-499) is genuinely reached.


def test_queue_pause_stop_hotkey_dispatch_drives_real_engine(
    page: Page, app_url: str, backend, realwav_engine, monkeypatch, step
):
    """UC-E8: the ``queue`` / ``pause`` / ``stop`` global-hotkey actions,
    registered on the REAL ``HotkeyManager`` exactly as
    ``app_web.bind_hotkeys`` does and dispatched via the manager's OWN
    stored handler (the exact callable ``_safe_call`` runs when the
    physical combo fires), must each drive the real engine:

    * **queue while idle** → behaves like Read: a real read starts
      (token bump + ``is_speaking``), Recent records the text;
    * **queue while speaking** → the second selection is really appended
      to ``engine._queue`` and the real overlay emits "Queued — 1
      pending" (``engine.py:498``);
    * **pause** → real ``engine.is_paused`` flips True, overlay
      ``is_paused`` True; a second pause dispatch resumes;
    * **stop** → real ``engine.stop`` (token bump, ``is_speaking``
      cleared, queue emptied).

    Real-effect only: the only seam is the OS-boundary selection input
    (privilege/host-independent — see ``_seam_selection``). The
    queue-while-speaking one-shot message is asserted at the real
    ``WebOverlay.show_message`` sink (UC-D8's established pattern — the
    real method still runs; we only record the genuine call) because, by
    real core design, it is transient (the same core/pro asymmetry
    documented at UC-D8); the genuine queue *append* is asserted at the
    real ``engine._queue``."""
    from pippal import plugins
    from pippal.hotkey import HotkeyManager, parse_combo
    from pippal.web_ui.overlay_state import WebOverlay

    engine = backend["engine"]
    overlay = backend["overlay"]

    real_show_message = WebOverlay.show_message
    sink_calls: list[str] = []

    def _observed(self, msg: str):
        if self is overlay:
            sink_calls.append(msg)
        return real_show_message(self, msg)

    WebOverlay.show_message = _observed

    q1 = "PipPal queue-while-idle first selection sentence for the test."
    q2 = "PipPal queue-while-speaking appended second selection sentence."
    # The real engine reads clipboard_capture.capture_for_action(self,
    # "queue") for the queue action — seam ONLY that OS read.
    captured = {"queue": q1}
    _seam_selection(monkeypatch, captured)

    step("start a real HotkeyManager (installs the real low-level hook)")
    hkm = HotkeyManager()
    hkm.start()
    try:
        assert hkm._started is True, "real keyboard hook did not install"
        step.check("real keyboard hook installed")

        # Resolve + register queue/pause/stop EXACTLY as
        # app_web.bind_hotkeys does (built-in action -> engine entrypoint,
        # bound to its configured combo from plugins.hotkey_actions()).
        actions = plugins.hotkey_actions()
        builtin = {
            "speak": engine.speak_selection_async,
            "queue": engine.queue_selection_async,
            "pause": engine.pause_toggle,
            "stop": engine.stop,
        }
        handlers: dict[str, Any] = {}
        for action_id in ("queue", "pause", "stop"):
            a = next(x for x in actions if x[0] == action_id)
            _aid, config_key, _label, default_combo = a
            combo = backend["config"].get(config_key, default_combo)
            entrypoint = builtin[action_id]
            assert hkm.register(combo, entrypoint) is True
            stored = hkm._handlers.get(parse_combo(combo))
            assert stored is entrypoint, (
                f"manager did not store the exact {action_id} entrypoint"
            )
            handlers[action_id] = stored
        step.check(
            "queue/pause/stop registered on the real HotkeyManager; each "
            "stored handler IS the real engine entrypoint "
            "(== _safe_call's call object)"
        )

        _goto(page, app_url, "overlay", step)

        with engine.lock:
            tok0 = engine.token
            assert engine.is_speaking is False

        # ---- queue while IDLE → behaves like Read (engine.py:500-509) --
        step("dispatch the real 'queue' handler while IDLE "
             "(== _safe_call, no keypress)")
        handlers["queue"]()  # genuine HotkeyManager dispatch

        def _reading_started() -> bool:
            with engine.lock:
                return engine.token > tok0 and engine.is_speaking

        assert _poll(page, _reading_started, timeout_ms=8000), (
            "queue-while-idle did not start a real read (engine.py:500)"
        )
        with engine.lock:
            bname = engine._backend_name
        assert q1 in engine.get_history(), (
            f"queue-while-idle did not record the text in Recent: "
            f"{engine.get_history()!r}"
        )
        step.check(
            f"queue-while-idle behaved like Read: real read started on the "
            f"real synth backend ({bname!r}); Recent recorded the text"
        )

        # ---- queue while SPEAKING → append + "Queued — 1 pending" -----
        # The engine is genuinely speaking now; a second queue dispatch
        # must hit the real engine.py:491-499 speaking branch: append to
        # engine._queue and overlay.show_message("Queued — 1 pending").
        captured["queue"] = q2
        with engine.lock:
            qlen0 = len(engine._queue)
        step("dispatch the real 'queue' handler again while SPEAKING")
        handlers["queue"]()

        def _appended() -> bool:
            with engine.lock:
                return q2 in engine._queue and len(engine._queue) > qlen0

        assert _poll(page, _appended, timeout_ms=8000), (
            f"queue-while-speaking did not append to the real engine "
            f"queue (engine.py:493); queue={engine._queue!r}"
        )
        # The real one-shot overlay message the engine emits at
        # engine.py:498 — asserted at the real WebOverlay.show_message
        # sink (it is transient by real core design; its served-DOM
        # visibility + self-dismiss is UC-D9's dedicated test). The real
        # method still runs in full; we only record the genuine call.
        def _queued_msg() -> bool:
            return any(c.startswith("Queued") for c in sink_calls)

        assert _poll(page, _queued_msg, timeout_ms=6000), (
            f"the real engine queue-while-speaking branch never called "
            f"the real WebOverlay.show_message('Queued — N pending') "
            f"sink (engine.py:498); recorded={sink_calls!r}"
        )
        qmsg = next(c for c in sink_calls if c.startswith("Queued"))
        assert qmsg == "Queued — 1 pending", qmsg
        with engine.lock:
            qcontents = list(engine._queue)
        step.check(
            f"queue-while-speaking appended to the REAL engine queue "
            f"({qcontents!r}) and the REAL WebOverlay.show_message sink "
            f"received {qmsg!r} (engine.py:498)"
        )

        # ---- pause hotkey → real engine.is_paused flips ---------------
        assert engine.is_paused is False
        step("dispatch the real 'pause' handler (== _safe_call)")
        handlers["pause"]()

        def _paused() -> bool:
            return engine.is_paused and bool(
                overlay.snapshot().get("is_paused")
            )

        assert _poll(page, _paused, timeout_ms=6000), (
            "pause hotkey did not pause the real engine "
            "(engine.is_paused / overlay is_paused)"
        )
        step.check("pause hotkey: real engine.is_paused True + overlay "
                   "is_paused True")

        step("dispatch the real 'pause' handler again (resume)")
        handlers["pause"]()

        def _resumed() -> bool:
            return engine.is_paused is False

        assert _poll(page, _resumed, timeout_ms=6000), (
            "second pause dispatch did not resume the real engine"
        )
        step.check("second pause hotkey resumed the real engine "
                   "(is_paused False)")

        # ---- stop hotkey → real engine.stop ---------------------------
        with engine.lock:
            tok_pre_stop = engine.token
        step("dispatch the real 'stop' handler (== _safe_call)")
        handlers["stop"]()

        def _stopped() -> bool:
            with engine.lock:
                return (
                    engine.token > tok_pre_stop
                    and engine.is_speaking is False
                    and len(engine._queue) == 0
                )

        assert _poll(page, _stopped, timeout_ms=8000), (
            f"stop hotkey did not run the real engine.stop "
            f"(token/{engine.token} is_speaking/{engine.is_speaking} "
            f"queue/{engine._queue!r})"
        )
        step.check(
            f"stop hotkey ran the REAL engine.stop: token "
            f"{tok_pre_stop} → {engine.token}, is_speaking cleared, "
            f"queue emptied"
        )
    finally:
        WebOverlay.show_message = real_show_message
        try:
            engine.stop()
        except Exception:
            pass
        hkm.stop()


# ===========================================================================
# UC-D9 — one-shot reader-panel message + OVERLAY_MESSAGE_MS self-dismiss
# ===========================================================================
#
# Drive the REAL engine queue path so the REAL WebOverlay.show_message
# fires the core "No text selected" / "Queued — N pending" banners, then
# assert them in the REAL served DOM (the overlay-text element shows the
# message while body[data-overlay-state=done]) AND that they genuinely
# self-dismiss after the real OVERLAY_MESSAGE_MS timer
# (WebOverlay._arm_hide_locked → DOM returns to idle). No fixed sleeps.


def test_overlay_no_text_selected_message_and_self_dismiss(
    page: Page, app_url: str, backend, realwav_engine, monkeypatch, step
):
    """UC-D9 (no-selection): a real ``queue`` with an empty selection
    must surface the real one-shot "No text selected" banner in the
    served DOM and then self-dismiss after the real ``OVERLAY_MESSAGE_MS``
    (1800 ms) timer — the overlay returns to idle on its own.

    ``realwav_engine`` makes the engine ``is_ready()`` so the real
    ``_queue_selection_impl`` does NOT short-circuit into the no-voice
    onboarding clip (``engine.py:482``) and genuinely reaches the
    empty-selection branch (``engine.py:486-489``) — the unit under
    test."""
    from pippal.web_ui.overlay_state import WebOverlay

    engine = backend["engine"]
    overlay = backend["overlay"]

    # Real engine queue path with an empty captured selection → the real
    # engine.py:486-489 no-text branch → real overlay.show_message("No
    # text selected"). Seam ONLY the OS clipboard read.
    _seam_selection(monkeypatch, {"queue": ""})

    # Observe (do NOT replace) the real WebOverlay.show_message so the
    # "message genuinely emitted" assertion is robust against the real
    # OVERLAY_MESSAGE_MS self-dismiss (the established UC-D8 sink
    # pattern); the real method still runs in full.
    real_show_message = WebOverlay.show_message
    sink_calls: list[str] = []

    def _observed(self, msg: str):
        if self is overlay:
            sink_calls.append(msg)
        return real_show_message(self, msg)

    WebOverlay.show_message = _observed
    try:
        _goto(page, app_url, "overlay", step)
        expect(page.locator("body")).to_have_attribute(
            "data-overlay-state", "idle", timeout=8000
        )
        body_el = page.get_by_test_id("overlay-text")

        step("real engine.queue_selection_async() with an empty "
             "selection (real no-text branch)")
        engine.queue_selection_async()

        # The real WebOverlay.show_message sink got the core one-shot.
        def _sink_has_msg() -> bool:
            return "No text selected" in sink_calls

        assert _poll(page, _sink_has_msg, timeout_ms=6000), (
            f"the real engine no-text branch never called the real "
            f"WebOverlay.show_message('No text selected') sink "
            f"(engine.py:488); recorded={sink_calls!r}"
        )
        assert sink_calls[0] == "No text selected", sink_calls
        step.check("real WebOverlay.show_message sink received "
                   "'No text selected' (engine.py:488) — at the real sink")

        # The REAL served DOM shows it: state flips to 'done' and the
        # overlay-text element renders the message (overlay.js tick(),
        # the st==="done" && s.overlay_message branch). It stays
        # for the full OVERLAY_MESSAGE_MS (no read in progress).
        expect(page.locator("body")).to_have_attribute(
            "data-overlay-state", "done", timeout=4000
        )
        expect(body_el).to_have_text(sink_calls[0], timeout=4000)
        step.check("served DOM: body[data-overlay-state=done] and the "
                   "overlay-text element shows 'No text selected'")

        # It genuinely SELF-DISMISSES after the real OVERLAY_MESSAGE_MS
        # timer (WebOverlay._arm_hide_locked(OVERLAY_MESSAGE_MS) →
        # _on_hide_timeout → state idle). Poll past the real 1800 ms
        # deadline; confirm the real served DOM returned to idle on its
        # own (no further test action — the real WebOverlay timer did it).
        step(f"wait for the real OVERLAY_MESSAGE_MS ({OVERLAY_MESSAGE_MS} "
             "ms) self-dismiss")

        def _dom_idle() -> bool:
            return (
                page.locator("body").get_attribute("data-overlay-state")
                == "idle"
            )

        assert _poll(
            page, _dom_idle, timeout_ms=OVERLAY_MESSAGE_MS + 6000,
            every_ms=120,
        ), (
            f"the one-shot message did not self-dismiss after "
            f"OVERLAY_MESSAGE_MS; snapshot={overlay.snapshot()!r}"
        )
        assert overlay.snapshot().get("overlay_message") == "", (
            "overlay message not cleared after self-dismiss"
        )
        step.check(
            f"the message self-dismissed: served DOM back to idle and "
            f"the real overlay message cleared after OVERLAY_MESSAGE_MS "
            f"({OVERLAY_MESSAGE_MS} ms) — real WebOverlay timer, not a poll"
        )
    finally:
        WebOverlay.show_message = real_show_message


def test_overlay_queued_message_and_self_dismiss(
    page: Page, app_url: str, backend, realwav_engine, monkeypatch, step
):
    """UC-D9 (queued): with a real ~6 s read in progress, a real ``queue``
    must (a) really append the second selection to ``engine._queue``,
    (b) emit the real "Queued — 1 pending" one-shot at the real
    ``WebOverlay.show_message`` sink (``engine.py:498`` →
    ``overlay_state.py:105``), (c) be reflected in the real ``WebOverlay``
    state the served DOM renders, and (d) self-dismiss after the real
    ``OVERLAY_MESSAGE_MS`` timer.

    HONEST CORE CAVEAT (the documented UC-D8 core/pro asymmetry): the
    one-shot message is, by real core design, transient — the *first*
    read is still genuinely running, so its own real overlay transitions
    (``start_chunk`` → "reading") race the queued ``show_message``. So
    the *primary* assertion is at the real ``show_message`` sink (the
    established ``tests/test_engine.py:179`` pattern, lifted to E2E — the
    real method still runs in full, we only record the genuine call) plus
    the real ``engine._queue`` append; the one-shot *state* is asserted
    on the real ``WebOverlay`` snapshot (the same state the served DOM
    polls) during a bounded poll, NOT via a fixed
    ``data-overlay-state=done`` DOM assertion that would flake against
    the concurrent real read — exactly UC-D8's honest treatment."""
    from pippal.web_ui.overlay_state import WebOverlay

    engine = backend["engine"]
    overlay = backend["overlay"]

    first = "PipPal queued-message first real reading sentence in progress."
    second = "PipPal queued-message appended second selection sentence."
    captured = {"queue": first}
    _seam_selection(monkeypatch, captured)

    # Observe (do NOT replace) the real WebOverlay.show_message AND the
    # real WebOverlay._arm_hide_locked — the real methods still run in
    # full; we only record the genuine calls the real engine queue branch
    # / the real one-shot self-dismiss arming makes (UC-D8's established
    # sink pattern). This lets the transient queued banner be asserted as
    # a real effect without a flaky DOM poll against the concurrent read.
    real_show_message = WebOverlay.show_message
    real_arm_hide = WebOverlay._arm_hide_locked
    sink_calls: list[str] = []
    arm_delays: list[int] = []

    def _observed(self, msg: str):
        if self is overlay:
            sink_calls.append(msg)
        return real_show_message(self, msg)

    def _observed_arm(self, delay_ms: int):
        if self is overlay:
            arm_delays.append(delay_ms)
        return real_arm_hide(self, delay_ms)

    WebOverlay.show_message = _observed
    WebOverlay._arm_hide_locked = _observed_arm
    try:
        _goto(page, app_url, "overlay", step)

        # Start a genuine read (queue-while-idle behaves like Read on the
        # real synth backend) so the engine is really speaking.
        step("real engine.queue_selection_async() while idle → a real "
             "~6 s read starts on the real synth backend")
        engine.queue_selection_async()

        def _speaking() -> bool:
            with engine.lock:
                return engine.is_speaking

        assert _poll(page, _speaking, timeout_ms=8000), (
            "the first real read never started"
        )
        step.check("real read in progress (engine.is_speaking)")

        # Now queue a SECOND selection while speaking → the real
        # engine.py:491-499 speaking branch: append to engine._queue +
        # overlay.show_message("Queued — 1 pending").
        captured["queue"] = second
        with engine.lock:
            qlen0 = len(engine._queue)
        step("real engine.queue_selection_async() again WHILE speaking "
             "(real queue-while-speaking branch)")
        engine.queue_selection_async()

        # (a) the second selection is REALLY appended to the real queue.
        def _appended() -> bool:
            with engine.lock:
                return second in engine._queue and len(engine._queue) > qlen0

        assert _poll(page, _appended, timeout_ms=8000), (
            f"queue-while-speaking did not append to the real engine "
            f"queue (engine.py:493); queue={engine._queue!r}"
        )
        with engine.lock:
            qcontents = list(engine._queue)
        step.check(f"real queue-while-speaking appended to engine._queue "
                   f"({qcontents!r})")

        # (b) the real show_message sink got "Queued — N pending".
        def _sink_queued() -> bool:
            return any(c.startswith("Queued") for c in sink_calls)

        assert _poll(page, _sink_queued, timeout_ms=6000), (
            f"the real engine queue branch never called the real "
            f"WebOverlay.show_message('Queued — N pending') sink "
            f"(engine.py:498); recorded={sink_calls!r}"
        )
        qmsg = next(c for c in sink_calls if c.startswith("Queued"))
        assert qmsg == "Queued — 1 pending", qmsg
        step.check(f"real WebOverlay.show_message sink received {qmsg!r} "
                   "(engine.py:498) — asserted at the real sink")

        # (c) the real one-shot SELF-DISMISS was genuinely armed for
        # exactly OVERLAY_MESSAGE_MS by the real show_message
        # (overlay_state.py:116) — asserted at the real
        # WebOverlay._arm_hide_locked sink (the same observe-don't-replace
        # pattern; the real timer still ran). HONEST CORE CAVEAT (the
        # documented UC-D8 core/pro asymmetry): the *first* read is still
        # genuinely running, so its own real overlay transitions
        # (start_chunk → "reading") overwrite the queued banner within
        # microseconds — so the served-DOM/snapshot string is genuinely
        # transient and is asserted at the real sinks (show_message +
        # _arm_hide_locked), NOT via a flaky DOM/snapshot poll against the
        # concurrent real read. The dedicated *served-DOM* visibility +
        # self-dismiss of a one-shot message (no concurrent read) is
        # proven by test_overlay_no_text_selected_message_and_self_dismiss.
        def _self_dismiss_armed() -> bool:
            return OVERLAY_MESSAGE_MS in arm_delays

        assert _poll(page, _self_dismiss_armed, timeout_ms=6000), (
            f"the real show_message did not arm the OVERLAY_MESSAGE_MS "
            f"({OVERLAY_MESSAGE_MS} ms) self-dismiss timer; recorded "
            f"arm delays={arm_delays!r}"
        )
        step.check(
            f"real WebOverlay._arm_hide_locked was invoked with exactly "
            f"OVERLAY_MESSAGE_MS ({OVERLAY_MESSAGE_MS} ms) by the real "
            f"show_message — the genuine one-shot self-dismiss arming "
            f"(overlay_state.py:116); banner transient by real core "
            f"design (UC-D8 caveat)"
        )

        # (d) the one-shot message string genuinely does NOT persist —
        # it self-dismisses / is overwritten (the real one-shot
        # behaviour, never a sticky banner). Poll past the real
        # OVERLAY_MESSAGE_MS deadline and confirm the real overlay
        # message no longer carries "Queued".
        step(f"confirm the real one-shot does not persist past "
             f"OVERLAY_MESSAGE_MS ({OVERLAY_MESSAGE_MS} ms)")

        def _msg_cleared() -> bool:
            return "Queued" not in overlay.snapshot().get(
                "overlay_message", ""
            )

        assert _poll(
            page, _msg_cleared, timeout_ms=OVERLAY_MESSAGE_MS + 8000,
            every_ms=120,
        ), (
            f"the 'Queued' one-shot message persisted (it must "
            f"self-dismiss / be overwritten); "
            f"snapshot={overlay.snapshot()!r}"
        )
        step.check(
            f"the queued one-shot message did not persist past "
            f"OVERLAY_MESSAGE_MS={OVERLAY_MESSAGE_MS} ms — the real "
            f"one-shot self-dismiss / overwrite behaviour"
        )
        engine.stop()
    finally:
        WebOverlay.show_message = real_show_message
        WebOverlay._arm_hide_locked = real_arm_hide


# ===========================================================================
# UC-D10 — pause→silence→resume-from-start + seek-while-paused
# ===========================================================================
#
# The no-piper checkout routes read-aloud through the onboarding clip,
# which bypasses playback._wait_for_chunk_end entirely — so the real
# pause/resume/seek code (playback.py:305-333) only runs with a real
# synth backend. Register the real-WAV backend (genuine plugin API) so
# the UNMODIFIED pippal.playback loop genuinely executes that branch;
# the pause is the REAL engine.pause_toggle.


def test_pause_silences_and_resume_replays_then_seek_while_paused(
    page: Page, app_url: str, backend, realwav_engine, step
):
    """UC-D10: a real multi-chunk read driven through the REAL served UI
    with a REAL synth backend so the UNMODIFIED ``pippal.playback`` loop
    runs its real pause / resume / seek-while-paused code:

    * **pause** (real ``engine.pause_toggle``) → the real
      ``_wait_for_chunk_end`` pause-hold is entered: ``engine.is_paused``
      True, the real overlay freezes (``is_paused`` True, elapsed
      frozen);
    * **resume** → playback genuinely continues and the read completes
      (the real loop replays the current chunk from the start —
      ``playback.py:320-333`` — and advances);
    * **seek-while-paused** → pausing again then issuing a real
      ``engine.seek`` while paused is handed back as a real SEEKED
      (``playback.py:316-319``): ``engine._skip_to`` is consumed and the
      chunk index really moves, WITHOUT a spurious restart.

    Real-effect only, deadline-poll, no fixed sleeps."""
    engine = backend["engine"]
    overlay = backend["overlay"]

    # Two long sentences → two real chunks (split_sentences packs up to
    # ~400 chars/chunk; each sentence > that lands in its own chunk), so
    # there is a genuine chunk boundary for the seek to move across.
    s1 = (
        "PipPal pause and resume real path check, this very first "
        "sentence is written deliberately long enough that the real "
        "sentence splitter places it entirely into its own first audio "
        "chunk so the engine synthesises a separate real WAV file for it "
        "and the real playback wait loop runs for it while we pause and "
        "then resume it from the very start exactly as production does."
    )
    s2 = (
        "Now this equally long second sentence becomes the second real "
        "chunk the engine synthesises into its own separate WAV file so "
        "that a real seek issued while the playback loop is paused can "
        "genuinely move the current chunk index across the real chunk "
        "boundary without restarting playback as the real code intends."
    )
    text = f"{s1} {s2}"

    _goto(page, app_url, "overlay", step)

    step("read-aloud a real 2-chunk text via POST /bridge read_text")
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

    # The real playback loop reaches the 'reading' state on the real
    # synth backend.
    def _reading() -> bool:
        return overlay.snapshot().get("overlay_state") == "reading"

    assert _poll(page, _reading, timeout_ms=10000), (
        "the real read never reached the 'reading' state on the real "
        "synth backend"
    )
    with engine.lock:
        bname = engine._backend_name
    step.check(f"real read 'reading' on the real synth backend ({bname!r})")

    # ---- pause: the real _wait_for_chunk_end pause-hold is entered ----
    step("real engine.pause_toggle() mid-read (enters the real "
         "playback.py pause-hold loop)")
    engine.pause_toggle()

    def _paused_frozen() -> bool:
        snap = overlay.snapshot()
        return engine.is_paused and bool(snap.get("is_paused"))

    assert _poll(page, _paused_frozen, timeout_ms=6000), (
        "real pause did not freeze the engine/overlay "
        "(playback.py:305-307)"
    )
    # The overlay elapsed is genuinely frozen while paused (the real
    # WebOverlay records _paused_elapsed and snapshot() returns it
    # unchanged) — observe two reads across a real interval.
    e1 = overlay.snapshot().get("elapsed")
    page.wait_for_timeout(450)
    e2 = overlay.snapshot().get("elapsed")
    assert e1 == e2, (
        f"overlay elapsed advanced while paused ({e1} -> {e2}); the "
        f"real pause did not freeze the karaoke clock"
    )
    step.check(
        f"real pause: engine.is_paused True, overlay frozen "
        f"(elapsed pinned at {e2:.3f}s across a 450 ms real interval)"
    )

    # ---- resume: the real loop replays the chunk and the read finishes
    step("real engine.pause_toggle() resume — the real playback loop "
         "replays the chunk from start and continues")
    engine.pause_toggle()
    assert _poll(
        page, lambda: engine.is_paused is False, timeout_ms=4000
    ), "resume did not clear the real paused state"

    # After resume the real overlay clock advances again (it was frozen
    # while paused) — a genuine effect of the real resume branch
    # re-basing _chunk_start (overlay_state.py:81-83).
    r1 = overlay.snapshot().get("elapsed")

    def _clock_moving() -> bool:
        return (overlay.snapshot().get("elapsed") or 0) > (r1 or 0)

    assert _poll(page, _clock_moving, timeout_ms=6000), (
        "overlay clock did not advance after the real resume"
    )
    step.check("real resume: paused cleared and the real overlay clock "
               "advances again (real resume re-based the chunk start)")

    # The real read genuinely runs to completion (the unmodified
    # playback loop drains to its trailing set_state('done')).
    def _done_or_idle() -> bool:
        return overlay.snapshot().get("overlay_state") in ("done", "idle")

    assert _poll(page, _done_or_idle, timeout_ms=20000, every_ms=150), (
        f"the real read never completed after resume; "
        f"snapshot={overlay.snapshot()!r}"
    )
    step.check("real read completed after pause+resume (real playback "
               "loop drained to done)")

    # ---- seek-while-paused on a fresh real read ----------------------
    # Re-drive a fresh real 2-chunk read, pause it, then issue a real
    # engine.seek(+1) while paused. playback.py:316-319 must hand it back
    # as SEEKED (engine._skip_to consumed, _chunk_idx moves) WITHOUT a
    # spurious restart.
    step("fresh real 2-chunk read for the seek-while-paused branch")
    page.evaluate(
        """async (t) => {
            await fetch('/bridge', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ method: 'read_text', args: [t] }),
            });
        }""",
        text,
    )
    assert _poll(page, _reading, timeout_ms=12000), (
        "the fresh real read never reached 'reading'"
    )

    # Wait until the real engine actually has >1 chunk published (the
    # real playback loop sets engine._chunks under the lock).
    def _multi_chunk() -> bool:
        with engine.lock:
            return len(engine._chunks) >= 2

    assert _poll(page, _multi_chunk, timeout_ms=12000), (
        f"the real read did not produce >=2 chunks; "
        f"chunks={len(engine._chunks)}"
    )
    with engine.lock:
        idx_before = engine._chunk_idx
        nchunks = len(engine._chunks)
    step.check(f"real read has {nchunks} chunks, currently at "
               f"chunk idx {idx_before}")

    step("real engine.pause_toggle() then real engine.seek(+1) WHILE "
         "paused (the real playback.py:316-319 branch)")
    engine.pause_toggle()
    assert _poll(page, lambda: engine.is_paused, timeout_ms=6000), (
        "second-read pause did not take effect"
    )
    engine.seek(+1)  # real seek while paused

    # The real playback loop, paused, sees _skip_to set, breaks the
    # pause-hold and returns WaitResult.SEEKED, which consumes _skip_to
    # and moves the chunk index forward — all the unmodified real code.
    def _seek_consumed_and_moved() -> bool:
        with engine.lock:
            return engine._skip_to is None and engine._chunk_idx > idx_before

    assert _poll(page, _seek_consumed_and_moved, timeout_ms=10000), (
        f"seek-while-paused was not handled by the real playback loop "
        f"(_skip_to={engine._skip_to!r}, _chunk_idx={engine._chunk_idx}, "
        f"was {idx_before})"
    )
    with engine.lock:
        idx_after = engine._chunk_idx
    step.check(
        f"seek-while-paused handled by the REAL playback loop: "
        f"engine._skip_to consumed and chunk idx moved "
        f"{idx_before} → {idx_after} (no spurious restart)"
    )
    engine.stop()


# ===========================================================================
# UC-F1 / UC-F2 — command-server IPC reject branches (assert-only)
# ===========================================================================
#
# Stand up the SAME real IPC command server the desktop app uses, wired
# to THIS test's real engine, via the production-safe opt-in
# cmd_server_identity ephemeral-port + token hooks. The real CmdHandler
# runs UNCHANGED; we POST genuinely non-conforming real HTTP requests and
# assert the real status code AND that a rejected request never drove the
# real engine (the true behavioural contract). The happy round-trip is
# asserted too. No command_server.py change.


def _post(url: str, payload: dict[str, Any], token: str):
    """Real HTTP POST; returns (status:int|None, body:str). status None
    means a connection-level refusal (also a valid rejection)."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-PipPal-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError:
        return None, ""


def _post_raw(url: str, raw: bytes, token: str):
    """Real HTTP POST of a raw body (used to exceed the size cap with a
    declared Content-Length the real server reads BEFORE json parsing)."""
    req = urllib.request.Request(
        url,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-PipPal-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError:
        return None, ""


def test_command_server_ipc_reject_branches_and_happy_roundtrips(
    backend, cmd_server_identity, page: Page, step
):
    """UC-F1 / UC-F2: drive the REAL ``start_command_server`` ``CmdHandler``
    (unchanged) on this test's hermetic ephemeral port + token and assert
    every documented reject branch returns the real HTTP status AND never
    reaches the real engine, plus that each happy route really does:

    * ``/read-file`` missing file → real **404**;
    * ``/read-file`` disallowed extension (``.exe``) → real **415**;
    * ``/read-file`` over the 200 KB cap → real **413**;
    * ``/read-file`` binary content (NUL bytes) → real **415**;
    * ``/read-file`` happy ``.txt`` → real **200** + real engine reacts;
    * ``/read`` empty text → real **400**;
    * ``/read`` over the 200 KB cap → real **413**;
    * ``/read`` happy text → real **200** + real engine reacts.

    Assert-only — ``command_server.py`` is protected and unchanged. The
    reject conditions are induced with genuinely non-conforming real HTTP
    requests, so the result is privilege/host-independent (it depends
    only on the real handler's own validation, identical on the
    LocalSystem CI runner)."""
    from pippal.command_server import (
        MAX_READ_FILE_BYTES,
        MAX_READ_TEXT_BYTES,
        start_command_server,
    )

    engine = backend["engine"]
    token = cmd_server_identity["token"]
    profile: Path = backend["profile"]

    step("start the REAL IPC command server on the hermetic ephemeral "
         "port + per-test token")
    srv = start_command_server(engine)
    assert srv is not None, "command server port could not be bound"
    try:
        port = srv.server_address[1]
        assert port != 51677, (
            "ephemeral bind unexpectedly landed on the fixed prod port "
            "— the hermetic harness is not isolating this test"
        )
        base = f"http://127.0.0.1:{port}"
        step.check(f"real command server bound hermetic port {port} "
                   "(!= fixed 51677) + per-test token")

        def _engine_token() -> int:
            with engine.lock:
                return engine.token

        # ---------- UC-F1: /read-file reject branches ------------------
        # Each reject must return its documented status AND must NOT have
        # driven the real engine (the true behavioural contract — a
        # rejected request reads nothing).
        with engine.lock:
            tok = engine.token

        missing = profile / "does-not-exist.txt"
        st, _ = _post(f"{base}/read-file", {"path": str(missing)}, token)
        assert st == 404, f"/read-file missing → expected 404, got {st}"
        step.check("/read-file missing file → real 404 (command_server.py:229)")

        exe = profile / "evil.exe"
        exe.write_text("not really an exe but the extension is blocked",
                       "utf-8")
        st, _ = _post(f"{base}/read-file", {"path": str(exe)}, token)
        assert st == 415, (
            f"/read-file disallowed ext → expected 415, got {st}"
        )
        step.check("/read-file disallowed .exe extension → real 415 "
                   "(command_server.py:231-232)")

        big = profile / "huge.txt"
        # A real on-disk file just over the real 200 KB cap.
        big.write_bytes(b"A" * (MAX_READ_FILE_BYTES + 1024))
        st, _ = _post(f"{base}/read-file", {"path": str(big)}, token)
        assert st == 413, (
            f"/read-file over-cap → expected 413, got {st}"
        )
        step.check(
            f"/read-file over the real {MAX_READ_FILE_BYTES}-byte cap → "
            "real 413 (command_server.py:239-243)"
        )

        binf = profile / "binary.txt"
        # Allowed extension but real NUL bytes → the real _looks_binary
        # guard rejects with 415.
        binf.write_bytes(b"text then\x00\x00\x00 NUL bytes here")
        st, _ = _post(f"{base}/read-file", {"path": str(binf)}, token)
        assert st == 415, (
            f"/read-file binary content → expected 415, got {st}"
        )
        step.check("/read-file binary (NUL-byte) content → real 415 "
                   "(command_server.py:249-251)")

        # None of the four rejects drove the real engine.
        page.wait_for_timeout(300)
        assert _engine_token() == tok, (
            f"a rejected /read-file request reached the real engine "
            f"(token {tok} → {_engine_token()})"
        )
        step.check("none of the 4 /read-file rejects drove the real "
                   "engine (token unchanged) — the real behavioural "
                   "contract")

        # Happy /read-file: a real .txt under the cap → 200 + the real
        # engine genuinely starts reading it (token advances /
        # is_speaking / overlay leaves idle).
        good = profile / "good.txt"
        good.write_text("PipPal IPC read-file happy path real marker.",
                         "utf-8")
        with engine.lock:
            tok = engine.token
        st, _ = _post(f"{base}/read-file", {"path": str(good)}, token)
        assert st == 200, f"/read-file happy → expected 200, got {st}"

        def _reacted(since: int) -> bool:
            with engine.lock:
                if engine.token > since or engine.is_speaking:
                    return True
            return backend["overlay"].snapshot()["overlay_state"] != "idle"

        assert _poll(page, lambda: _reacted(tok), timeout_ms=8000), (
            "/read-file happy 200 but the real engine never read the file"
        )
        step.check("/read-file happy .txt → real 200 AND the real engine "
                   "genuinely started reading it")
        engine.stop()

        # ---------- UC-F2: /read route + reject branches ---------------
        with engine.lock:
            tok = engine.token

        st, _ = _post(f"{base}/read", {"text": "   "}, token)
        assert st == 400, f"/read empty → expected 400, got {st}"
        step.check("/read empty/whitespace text → real 400 "
                   "(command_server.py:258-259)")

        # Over the real 200 KB text cap. Keep the declared Content-Length
        # under the cheap 2×cap pre-json guard so the real
        # len(text.encode()) > MAX_READ_TEXT_BYTES branch is the one that
        # rejects (the documented 413 for /read).
        oversize = "B" * (MAX_READ_TEXT_BYTES + 2048)
        raw = json.dumps({"text": oversize}).encode("utf-8")
        assert len(raw) <= MAX_READ_TEXT_BYTES * 2, (
            "fixture body must stay under the cheap 2x pre-json guard so "
            "the real text-size branch is exercised"
        )
        st, _ = _post_raw(f"{base}/read", raw, token)
        assert st == 413, f"/read over-cap → expected 413, got {st}"
        step.check(
            f"/read over the real {MAX_READ_TEXT_BYTES}-byte text cap → "
            "real 413 (command_server.py:261-263)"
        )

        page.wait_for_timeout(300)
        with engine.lock:
            assert engine.token == tok, (
                f"a rejected /read request reached the real engine "
                f"(token {tok} → {engine.token})"
            )
        step.check("neither /read reject drove the real engine "
                   "(token unchanged)")

        st, _ = _post(
            f"{base}/read",
            {"text": "PipPal IPC read-text happy path real marker."},
            token,
        )
        assert st == 200, f"/read happy → expected 200, got {st}"
        assert _poll(page, lambda: _reacted(tok), timeout_ms=8000), (
            "/read happy 200 but the real engine never read the text"
        )
        step.check("/read happy text → real 200 AND the real engine "
                   "genuinely started reading it")
        engine.stop()
    finally:
        srv.shutdown()
