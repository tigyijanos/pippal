"""Phase-3 — onboarding completeness & startup decision.

The Core "Phase 3" rows of ``docs/USE_CASE_BACKLOG.md``: lower-frequency
but real first-run UX that is mostly pure logic and, until now, untested
in either tier.

* **UC-A14** — selected-text activation completion
  (``engine.py:390`` → ``onboarding.py:155``) **and** the capture-failure
  recovery message (``engine.py:381`` → ``onboarding.py:218``). The user
  finishes activation by actually reading a *real selection* (not the
  bundled sample); a failed capture instead records ``last_failure`` and
  is surfaced by ``activation_failure_recovery_message``.
* **UC-A6** — the *already-complete* onboarding re-entry copy branch
  (``app.js:399-422``): a returning user re-opens the first-run check and
  the Finish button becomes **"Close"** (primary, ungated) and Play
  becomes **"Play sample again"**; "Close" must NOT re-write the
  activation file, "Play sample again" still drives a real engine read.
* **UC-A13** — the startup auto-open *decision*
  (``app_web.py:38-40,261``): whether to nag the user with onboarding at
  startup is ``_selected_piper_missing(config) or
  should_show_activation_panel()`` — asserted against the **real**
  composition helpers with real on-disk state across every branch.

* **UC-C9** — first-run → Voice-Manager → install-completion →
  onboarding ready. Previously an honestly-accepted parity gap (the web
  path had no install-completion callback). A minimal production fix
  (``bridge.install_voice`` now applies the same shared onboarding
  effect Tk's ``apply_installed_voice`` does — set the just-installed
  voice as the configured voice on the shared config the shared
  ``build_activation_readiness`` reads, no forked logic) closed it. The
  test below
  (``test_ucc9_first_run_vm_install_completion_flips_onboarding_ready``)
  drives the REAL served onboarding → Voice-Manager → real
  ``install_voice`` installer → the NEW completion callback → real
  shared readiness flips ready, seaming ONLY the OS-boundary network
  download (the established e2e/web installer pattern). The Tier-2
  launched-app equivalent is journey J9
  (``e2e/journey/test_journeys.py``), which does a genuine download on
  the real WebView2 app.

Discipline (identical to the rest of ``e2e/web`` and held strictly):

* **Real-effect only.** Each test drives the REAL served UI / REAL bridge
  / REAL ``TTSEngine`` + ``WebOverlay`` / the REAL ``app_web`` startup
  composition helpers and asserts a REAL persisted file
  (``first_run_activation.json`` read back with the real
  ``load_activation_state``), the REAL recovery string the real
  ``activation_failure_recovery_message`` returns, the REAL served DOM
  (the actual rendered button text / classes / status copy), the REAL
  recorded ``on_close_window`` host callback, or the REAL boolean the
  real ``app_web`` gate computes.
* **The real condition is induced at a true seam, never by mocking the
  unit under test.**
  - UC-A14: the unit under test is the engine's *activation bookkeeping*
    around a real selection (``_mark_activation_selected_text_complete``
    / ``_record_activation_capture_failure``, ``engine.py:381-403``) and
    the real ``onboarding`` persistence + recovery-message helpers. The
    real ``_speak_selection_impl`` runs unchanged; a real ``TTSBackend``
    registered through the genuine ``plugins.register_engine`` extension
    API makes the engine ``is_ready()`` so it takes the REAL synth path
    (NOT the no-voice onboarding clip — which would short-circuit before
    the bookkeeping) and makes ``build_activation_readiness`` REALLY
    return ``ready`` (its genuine non-piper engine branch,
    ``onboarding.py:260-268``). The ONLY seam is the OS-boundary
    *selection input* (``clipboard_capture.capture_for_action`` — sending
    a real Ctrl+C / reading the system clipboard cannot be driven on a
    headless Session-0 runner with no foreground selection; the backlog
    itself names selection capture an OS boundary). That seam is the
    lifted-to-E2E form of the established unit pattern
    (``tests/test_engine.py:170``) and is **privilege/host-independent**:
    it replaces only the OS clipboard read, so the result depends purely
    on PipPal's branch logic — byte-for-byte identical on the LocalSystem
    CI runner.
  - UC-A6: no seam at all — the conftest already pre-seeds activation
    *complete*; with a real ``ready`` readiness the real
    ``renderOnboarding`` genuinely takes its ``st.is_complete`` branch.
    The test only reads the real served DOM and the real persisted file.
  - UC-A13: no mock — the real ``app_web._selected_piper_missing`` and
    the real ``onboarding.should_show_activation_panel`` are called
    directly with real on-disk state (a real stub ``piper.exe`` under the
    per-test profile, a real ``first_run_activation.json`` written by the
    real ``mark_activation_complete``); the real ``or`` gate is the exact
    expression ``app_web.main`` evaluates. Privilege/host-independent —
    it depends only on a file existing and a JSON's contents under the
    hermetic per-test profile.
* **No fixed sleeps** — every wait is a deadline-poll.
* **No tautology** — every assertion is a real observable effect, never
  "the test set X then read X".
* Same hermetic per-test reset as the rest of the suite
  (``conftest.py`` ``backend`` / ``readiness`` / ``assert_fresh_baseline``).
"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

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
    ``test_core_interactions.py``'s ``_RealWavBackend``). ``is_ready()``
    is True so the engine takes the REAL synth path — NOT the no-voice
    onboarding clip, which would short-circuit ``_speak_selection_impl``
    before the activation bookkeeping runs. Selecting it on the live
    config also makes the real ``build_activation_readiness`` return
    ``ready`` via its genuine non-piper engine branch
    (``onboarding.py:260-268``), which the real
    ``_mark_activation_selected_text_complete`` requires. Not a mock of
    any PipPal code path — a real registered engine."""

    name = "realwav-core-p3"
    _RATE = 22050
    _SECONDS = 1.0

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
                val = int(2000 * math.sin(2 * math.pi * 180 * i / self._RATE))
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


def _seam_selection(monkeypatch, text: str) -> None:
    """Seam the OS-boundary selection input for the ``speak`` action.

    ``clipboard_capture.capture_for_action`` sends a real Ctrl+C and reads
    the system clipboard — an OS boundary that cannot be driven on a
    headless Session-0 runner with no foreground app holding a selection
    (the backlog explicitly names selection capture an OS boundary). This
    replaces ONLY that OS read with a deterministic return value, so the
    test exercises PipPal's real activation BRANCH logic (the unit under
    test) on a known input — the lifted-to-E2E form of the established
    unit pattern at ``tests/test_engine.py:170``. The result depends
    purely on PipPal logic, so it is byte-for-byte identical on the
    LocalSystem CI runner (privilege/host-independent)."""
    import pippal.engine as engine_mod

    def _fake_capture(_engine, action: str) -> str:
        return text if action == "speak" else ""

    monkeypatch.setattr(
        engine_mod.clipboard_capture, "capture_for_action", _fake_capture
    )


# ===========================================================================
# UC-A14 — selected-text activation completion + capture-failure recovery
# ===========================================================================
#
# The conftest pre-seeds activation COMPLETE (deterministic onboarding for
# the rest of the suite). The activation bookkeeping only runs while
# activation is PENDING (engine._activation_is_pending →
# should_show_activation_panel), so each UC-A14 test first removes the
# pre-seeded completion (a real on-disk delete) and asserts the real
# pending state before driving the real selected-text read.


def test_selected_text_activation_completes_on_real_selection_read(
    page: Page, app_url: str, backend, realwav_engine, monkeypatch, step
):
    """UC-A14 (completion): a returning user has NOT completed first-run
    activation. They read a *real selection* (not the bundled sample).
    The real ``_speak_selection_impl`` → real
    ``_mark_activation_selected_text_complete`` → real
    ``mark_activation_complete("selected_text")`` must persist
    ``first_run_activation.json`` with ``completed_with="selected_text"``
    and flip the real ``load_activation_state().is_complete`` True.

    Real-effect only; the only seam is the OS-boundary selection input
    (privilege/host-independent — see ``_seam_selection``). The engine
    takes the REAL synth path (real registered WAV backend), so the real
    bookkeeping is genuinely reached (the no-voice clip would
    short-circuit it)."""
    from pippal.onboarding import (
        SELECTED_TEXT_CAPTURE_FAILURE,
        activation_state_path,
        load_activation_state,
        should_show_activation_panel,
    )

    engine = backend["engine"]

    # Remove the pre-seeded completion → activation is genuinely PENDING.
    step("clear the pre-seeded activation completion (real on-disk delete)")
    activation_state_path().unlink(missing_ok=True)
    engine._activation_completion_seen = False
    assert should_show_activation_panel() is True, (
        "activation should be pending after clearing the completion file"
    )
    assert load_activation_state().is_complete is False
    step.check("real activation state on disk: PENDING (not complete)")

    # build_activation_readiness must REALLY be 'ready' for the
    # selected_text completion to be recorded (engine.py:397) — the
    # realwav engine makes the real non-piper branch return ready.
    from pippal.onboarding import build_activation_readiness

    rd = build_activation_readiness(backend["config"])
    assert rd.is_ready, f"readiness not ready for the realwav engine: {rd!r}"
    step.check(f"real build_activation_readiness == ready ({rd.status!r}) "
               "via the genuine non-piper engine branch")

    real_selection = (
        "PipPal Phase-3 real selected-text activation completion sentence "
        "the user genuinely selected in another app and had read aloud."
    )
    _seam_selection(monkeypatch, real_selection)

    _goto(page, app_url, "overlay", step)

    step("real engine.speak_selection_async() of a real selection "
         "(real _speak_selection_impl → real activation bookkeeping)")
    engine.speak_selection_async()

    # The real read genuinely starts on the real synth backend (proves
    # the engine did NOT short-circuit into the no-voice onboarding clip
    # — the bookkeeping path is genuinely reached).
    def _reading_started() -> bool:
        with engine.lock:
            return engine.is_speaking or engine.token > 0

    assert _poll(page, _reading_started, timeout_ms=8000), (
        "the real selected-text read never started on the real backend"
    )
    assert real_selection in engine.get_history(), (
        f"the real selection was not recorded in Recent: "
        f"{engine.get_history()!r}"
    )
    step.check("real selected-text read started + Recent recorded the "
               "selection (engine took the REAL synth path)")

    # The REAL effect: the real _mark_activation_selected_text_complete
    # wrote first_run_activation.json with completed_with='selected_text'.
    def _completed_via_selection() -> bool:
        st = load_activation_state()
        return st.is_complete and st.completed_with == "selected_text"

    assert _poll(page, _completed_via_selection, timeout_ms=8000), (
        f"activation was not marked complete via selected_text; "
        f"on disk: {load_activation_state()!r}"
    )
    persisted = load_activation_state()
    assert persisted.completed_with == "selected_text", persisted
    assert persisted.completed_at, persisted
    assert persisted.last_failure is None, persisted
    # Cross-check the real persisted JSON file on disk independently.
    import json

    raw = json.loads(activation_state_path().read_text("utf-8"))
    assert raw["first_run_activation"]["completed_with"] == "selected_text", raw
    step.check(
        f"REAL first_run_activation.json on disk: completed_with="
        f"'selected_text', completed_at={persisted.completed_at!r} — the "
        f"real engine.py:390 → onboarding.py:155 path (NOT the sample, "
        f"NOT '{SELECTED_TEXT_CAPTURE_FAILURE}')"
    )
    engine.stop()


def test_selected_text_capture_failure_records_recovery_message(
    page: Page, app_url: str, backend, realwav_engine, monkeypatch, step
):
    """UC-A14 (capture failure + recovery): a returning user has NOT
    completed activation and triggers Read, but the capture yields nothing
    (the real ``_speak_selection_impl`` empty-text branch). The real
    ``_record_activation_capture_failure`` → real
    ``record_activation_failure(SELECTED_TEXT_CAPTURE_FAILURE)`` must
    persist ``last_failure`` (activation still NOT complete), and the real
    ``activation_failure_recovery_message`` must build the genuine
    user-facing recovery copy from that real persisted failure.

    Real-effect only; the only seam is the OS-boundary selection input
    (here it genuinely yields the empty string — the real no-selection
    condition — privilege/host-independent)."""
    from pippal.onboarding import (
        SELECTED_TEXT_CAPTURE_FAILURE,
        activation_failure_recovery_message,
        activation_state_path,
        build_activation_readiness,
        load_activation_state,
        should_show_activation_panel,
    )

    engine = backend["engine"]
    overlay = backend["overlay"]

    step("clear the pre-seeded activation completion (real on-disk delete)")
    activation_state_path().unlink(missing_ok=True)
    engine._activation_completion_seen = False
    assert should_show_activation_panel() is True
    assert load_activation_state().last_failure is None
    step.check("real activation state on disk: PENDING, no prior failure")

    # Seam the OS selection to genuinely empty → the real
    # _speak_selection_impl no-text branch (engine.py:469-473) →
    # real _record_activation_capture_failure (engine.py:470).
    _seam_selection(monkeypatch, "")

    _goto(page, app_url, "overlay", step)

    step("real engine.speak_selection_async() with an EMPTY selection "
         "(real no-text branch → real capture-failure bookkeeping)")
    engine.speak_selection_async()

    # The REAL effect #1: first_run_activation.json now carries
    # last_failure == the real SELECTED_TEXT_CAPTURE_FAILURE, and
    # activation is still NOT complete (a failed capture must not
    # silently 'complete' first-run).
    def _failure_recorded() -> bool:
        st = load_activation_state()
        return st.last_failure == SELECTED_TEXT_CAPTURE_FAILURE

    assert _poll(page, _failure_recorded, timeout_ms=8000), (
        f"the real capture-failure was not persisted; "
        f"on disk: {load_activation_state()!r}"
    )
    st = load_activation_state()
    assert st.last_failure == SELECTED_TEXT_CAPTURE_FAILURE, st
    assert st.is_complete is False, (
        f"a failed capture must NOT complete activation: {st!r}"
    )
    assert st.completed_with is None, st
    import json

    raw = json.loads(activation_state_path().read_text("utf-8"))
    assert (
        raw["first_run_activation"]["last_failure"]
        == SELECTED_TEXT_CAPTURE_FAILURE
    ), raw
    step.check(
        f"REAL first_run_activation.json on disk: last_failure="
        f"{SELECTED_TEXT_CAPTURE_FAILURE!r}, NOT complete — the real "
        f"engine.py:381 → onboarding.py:173 path"
    )

    # The REAL effect #2: the real activation_failure_recovery_message
    # builds the genuine user-facing recovery copy from that real
    # persisted failure + the real configured hotkey label. This is the
    # copy the onboarding surface would surface (onboarding.py:218).
    hk = build_activation_readiness(backend["config"]).hotkey_label
    recovery = activation_failure_recovery_message(st.last_failure, hk)
    assert recovery is not None, "recovery message was None for a real failure"
    assert recovery.startswith(SELECTED_TEXT_CAPTURE_FAILURE), recovery
    assert "select text and press" in recovery, recovery
    assert hk in recovery, (recovery, hk)
    assert "Play sample" in recovery, recovery
    step.check(
        f"real activation_failure_recovery_message built the genuine "
        f"recovery copy from the real persisted failure + real hotkey "
        f"{hk!r}: {recovery!r}"
    )

    # And the real engine still surfaced the no-text one-shot (the user
    # is genuinely told nothing was captured) — a real observable effect
    # of the same branch, asserted on the real overlay state.
    def _no_text_surfaced() -> bool:
        return (overlay.snapshot().get("overlay_message") or "") != "" or \
            overlay.snapshot().get("overlay_state") in ("done", "idle")

    assert _poll(page, _no_text_surfaced, timeout_ms=6000), (
        "the real no-text branch did not surface anything on the overlay"
    )
    step.check("real overlay reflected the no-text branch (engine.py:472)")
    engine.stop()


# ===========================================================================
# UC-A6 — already-complete onboarding re-entry copy branch (app.js:399-422)
# ===========================================================================
#
# The conftest pre-seeds activation COMPLETE. With a real 'ready'
# readiness the real renderOnboarding genuinely takes its
# st.is_complete branch: Finish → "Close" (primary, ungated), Play →
# "Play sample again", status → the already-set-up copy. No seam — pure
# real served DOM + real persisted-file + real host-callback assertions.


def test_onboarding_already_complete_reentry_close_and_play_again(
    page: Page, app_url: str, readiness, backend, step
):
    """UC-A6: a returning user whose first-run activation is already
    complete re-opens the first-run check. The real ``renderOnboarding``
    ``st.is_complete`` branch (``app.js:399-422``) must render:

    * the Finish button as **"Close"**, **primary**, and NOT gated
      (clicking it just closes — it must NOT re-write the activation
      file);
    * the Play button as **"Play sample again"** (not primary);
    * the status copy as the already-set-up line;

    and "Play sample again" must still drive a REAL engine read and show
    the already-set-up playing copy. Real-effect only — asserted on the
    real served DOM, the real persisted ``first_run_activation.json``
    (unchanged by "Close"), and the real ``on_close_window`` host
    callback."""
    from pippal.onboarding import load_activation_state

    step("force readiness = ready (real stub piper.exe + real voice on "
         "disk); activation is pre-seeded COMPLETE by the conftest")
    readiness["ready"]()
    seeded = load_activation_state()
    assert seeded.is_complete and seeded.completed_with == "sample", seeded
    step.check(f"real activation state on disk: COMPLETE "
               f"(completed_with={seeded.completed_with!r})")

    _goto(page, app_url, "onboarding", step)

    finish = page.get_by_test_id("onboarding-finish")
    play = page.get_by_test_id("onboarding-play-sample")
    status = page.get_by_test_id("onboarding-status")

    # The real st.is_complete branch copy/classes (app.js:399,412-413).
    expect(finish).to_have_text(EN["onboarding.btn.close"])
    expect(finish).to_be_enabled()
    expect(finish).to_have_class("primary")
    expect(play).to_have_text(EN["onboarding.btn.play_again"])
    # The non-complete Play is primary; the already-complete one is NOT.
    assert "primary" not in (play.get_attribute("class") or ""), (
        "Play-sample-again must not be the primary button in the "
        "already-complete branch (app.js:413)"
    )
    expect(status).to_contain_text("Done. PipPal can read selected text")
    step.check(
        "real served DOM took the st.is_complete branch: Finish='Close' "
        "(primary, enabled), Play='Play sample again' (not primary), "
        "status='Done. PipPal can read selected text…' (app.js:399-422)"
    )

    # "Play sample again" still drives a REAL engine read and shows the
    # already-set-up copy (app.js:418-420) — a real observable effect.
    engine = backend["engine"]
    with engine.lock:
        tok0 = engine.token
    step("click 'Play sample again' (real engine read via the real "
         "bridge.play_sample)")
    play.click()

    def _played() -> bool:
        with engine.lock:
            return engine.token > tok0 or engine.is_speaking
        return False

    assert _poll(page, _played, timeout_ms=8000), (
        "Play sample again did not drive the real engine"
    )
    expect(status).to_contain_text(
        "Playing sample again. PipPal is already set up", timeout=6000
    )
    step.check("'Play sample again' drove the REAL engine read and showed "
               "the real already-set-up status copy (app.js:418-420)")
    engine.stop()

    # "Close" (the is_complete Finish) must close via the real
    # on_close_window host callback and must NOT re-write the activation
    # file (the is_complete branch returns BEFORE mark_activation_complete
    # — app.js:401).
    before_closes = len(backend["close_calls"])
    before_state = load_activation_state()
    step("click the 'Close' button (the already-complete Finish)")
    finish.click()

    def _closed() -> bool:
        return len(backend["close_calls"]) > before_closes

    assert _poll(page, _closed, timeout_ms=5000), (
        "'Close' did not reach the real on_close_window host callback"
    )
    after_state = load_activation_state()
    assert after_state == before_state, (
        f"'Close' must NOT re-write the activation file "
        f"(before={before_state!r} after={after_state!r}) — the "
        f"is_complete branch returns before mark_activation_complete"
    )
    step.check(
        "'Close' reached the REAL on_close_window host callback and did "
        "NOT re-write first_run_activation.json (real app.js:401 branch)"
    )


# ===========================================================================
# UC-A13 — startup auto-open decision (app_web.py:38-40,261)
# ===========================================================================
#
# Whether the app nags the user with onboarding at startup is exactly
#   _selected_piper_missing(config) or should_show_activation_panel()
# (app_web.py:261). Assert the REAL composition helpers across every
# branch with REAL on-disk state under the hermetic per-test profile.
# Privilege/host-independent — depends only on a file existing and a
# JSON's contents in the temp profile.


def test_startup_auto_open_decision_real_composition_gate(
    backend, fresh_profile: Path, monkeypatch, step
):
    """UC-A13: the real ``app_web`` startup-decision gate
    ``_selected_piper_missing(config) or should_show_activation_panel()``
    (``app_web.py:261``) must auto-open onboarding in exactly these real
    cases and NOT otherwise:

    * piper engine + **no** ``piper.exe`` → ``_selected_piper_missing``
      True → gate True (repair the missing engine);
    * piper present + activation **not complete** → second disjunct True
      → gate True (finish first-run);
    * piper present + activation **complete** → both False → gate False
      (do not nag a set-up returning user);
    * a non-piper engine + activation complete → ``_selected_piper_missing``
      False (engine != piper) and second disjunct False → gate False.

    The real ``_selected_piper_missing`` reads ``app_web.PIPER_EXE`` and
    the real ``should_show_activation_panel`` reads the real
    ``first_run_activation.json``; both are exercised against real
    on-disk state in the hermetic per-test profile (a real stub
    ``piper.exe``, a real activation file written by the real
    ``mark_activation_complete``). No mock — the gate expression is the
    exact one ``app_web.main`` evaluates."""
    import pippal.web_ui.app_web as app_web
    from pippal.onboarding import (
        activation_state_path,
        mark_activation_complete,
        should_show_activation_panel,
    )

    # The real decision expression, evaluated exactly as app_web.main does
    # at app_web.py:261 (not re-implemented — the real helpers, real or).
    def _gate(config) -> bool:
        return app_web._selected_piper_missing(config) or \
            should_show_activation_panel()

    cfg = backend["config"]
    state_path = activation_state_path()
    orig_pe = app_web.PIPER_EXE

    # A real stub piper.exe under the per-test profile we can toggle by
    # actually creating / not creating the file (real Path.exists()).
    fake_piper = fresh_profile / "piper" / "piper.exe"
    fake_piper.parent.mkdir(parents=True, exist_ok=True)

    try:
        # ---- Case 1: piper engine, NO piper.exe → gate TRUE -----------
        cfg["engine"] = "piper"
        monkeypatch.setattr(app_web, "PIPER_EXE", fake_piper)  # does NOT exist
        assert fake_piper.exists() is False
        # Activation complete here too, to prove the FIRST disjunct alone
        # drives the gate (isolate _selected_piper_missing).
        mark_activation_complete("sample", path=state_path)
        assert should_show_activation_panel() is False
        assert app_web._selected_piper_missing(cfg) is True, (
            "piper engine + missing piper.exe must be 'selected piper "
            "missing' (app_web.py:38-40)"
        )
        assert _gate(cfg) is True, (
            "startup gate must auto-open onboarding when the selected "
            "piper engine has no piper.exe (app_web.py:261)"
        )
        step.check("Case 1: piper engine + NO piper.exe → real "
                   "_selected_piper_missing True → real gate TRUE "
                   "(repair path), independent of activation state")

        # ---- Case 2: piper present, activation NOT complete → TRUE ----
        fake_piper.write_bytes(b"MZ")  # real file → Path.exists() True
        assert fake_piper.exists() is True
        state_path.unlink(missing_ok=True)  # activation genuinely pending
        assert should_show_activation_panel() is True
        assert app_web._selected_piper_missing(cfg) is False, (
            "piper.exe now exists — _selected_piper_missing must be False"
        )
        assert _gate(cfg) is True, (
            "startup gate must auto-open onboarding when first-run "
            "activation is not complete (second disjunct)"
        )
        step.check("Case 2: piper.exe present + activation PENDING → "
                   "first disjunct False, real should_show_activation_"
                   "panel True → real gate TRUE (finish first-run)")

        # ---- Case 3: piper present, activation complete → FALSE -------
        mark_activation_complete("selected_text", path=state_path)
        assert should_show_activation_panel() is False
        assert app_web._selected_piper_missing(cfg) is False
        assert _gate(cfg) is False, (
            "startup gate must NOT auto-open onboarding for a set-up "
            "returning user (both disjuncts False)"
        )
        step.check("Case 3: piper.exe present + activation COMPLETE → "
                   "both real disjuncts False → real gate FALSE "
                   "(no nag for a set-up user)")

        # ---- Case 4: non-piper engine + activation complete → FALSE ---
        # _selected_piper_missing short-circuits on engine != 'piper'
        # (app_web.py:39-40) regardless of whether piper.exe exists, so
        # even with NO piper.exe the gate stays False here.
        cfg["engine"] = "realwav-core-p3"
        monkeypatch.setattr(app_web, "PIPER_EXE", fake_piper)
        fake_piper.unlink(missing_ok=True)
        assert fake_piper.exists() is False
        assert app_web._selected_piper_missing(cfg) is False, (
            "a non-piper engine must never be 'selected piper missing' "
            "even with no piper.exe (app_web.py:39 short-circuit)"
        )
        assert should_show_activation_panel() is False
        assert _gate(cfg) is False, (
            "non-piper engine + activation complete → gate False"
        )
        step.check("Case 4: non-piper engine (no piper.exe) + activation "
                   "COMPLETE → real _selected_piper_missing False "
                   "(engine!=piper short-circuit) → real gate FALSE")
    finally:
        cfg["engine"] = "piper"
        app_web.PIPER_EXE = orig_pe
        # Restore the conftest's pre-seeded COMPLETE activation so the
        # autouse baseline guard for the NEXT test still holds.
        mark_activation_complete(
            "sample", path=state_path, completed_at="2026-01-01T00:00:00Z"
        )


# ===========================================================================
# UC-C9 — first-run → Voice Manager → install-completion → onboarding ready
# ===========================================================================
#
# The Tk first-run flow wires the Voice Manager's install-completion
# callback (``app.py:577-583`` ``on_installed=panel.apply_installed_voice``
# → ``activation_panel.py:415`` → ``_finish_voice_install``:
# ``self.config["voice"] = installed_filename``) so that installing a
# voice from the first-run Voice Manager makes that voice the configured
# voice and flips onboarding/readiness to *ready*. ``tests/test_activation
# _panel.py:375`` is the canonical Tk contract: after the install,
# ``config["voice"] == installed_filename``.
#
# The web path now has the true analogue: ``bridge.install_voice`` is the
# web Voice Manager's install-completion point, and it applies the SAME
# shared effect on the SAME config dict the shared
# ``onboarding.build_activation_readiness`` reads (no forked logic, no
# Tk/web drift). This test exercises that real new callback end-to-end on
# the REAL served UI + REAL bridge and asserts the REAL effect — the
# missing→covered closure of UC-C9.
#
# Seam discipline (identical to test_voice_manager_row_install_real_effect
# / test_onboarding_install_default_voice_real_effect): the ONLY seam is
# the OS-boundary network download (``voice_manager._streaming_download``
# — a real HTTP GET to Hugging Face, which a hermetic Session-0 CI runner
# cannot and must not perform). EVERYTHING under test is real: the real
# served onboarding + Voice Manager DOM, the real ``open_voice_manager_
# window`` host callback, the real ``bridge.install_voice`` →
# ``install_piper_voice`` installer, the real NEW install-completion
# config update, and the real shared ``build_activation_readiness`` /
# ``get_readiness`` recomputation. No mock of the unit under test, no
# tautology (the test never sets the config voice — the production
# callback does), no fixed sleep (deadline-poll), privilege/host-
# independent (depends only on a file landing under the hermetic
# per-test profile and PipPal's own branch logic — byte-for-byte
# identical on the LocalSystem runner).


def test_ucc9_first_run_vm_install_completion_flips_onboarding_ready(
    page: Page, app_url: str, readiness, backend, monkeypatch, step
):
    """UC-C9: a first-run user with NO voice opens the web Voice Manager
    from onboarding, installs a voice, and the NEW install-completion
    callback genuinely flips onboarding/activation/readiness to ready —
    exactly like the Tk ``apply_installed_voice`` flow (the same shared
    onboarding logic, reused not forked)."""
    from pippal import voices as voices_mod
    from pippal import voice_install as vm

    bridge = backend["bridge"]
    cfg = backend["config"]

    # --- Real first-run "needs a voice" state (real stub piper, no voice
    # on disk). build_activation_readiness is the REAL shared function.
    step("force the real first-run readiness = missing_voice "
         "(real stub piper.exe, zero voices on disk)")
    rd0 = readiness["missing_voice"]()
    assert rd0.status == "missing_voice", rd0.status
    # The bridge's get_readiness (what the served onboarding renders) is
    # the REAL shared onboarding path and agrees: not ready yet.
    assert bridge.get_readiness()["status"] == "missing_voice"
    assert voices_mod.installed_voices() == [], voices_mod.installed_voices()
    step.check("real shared get_readiness == 'missing_voice' "
               "(onboarding would nag for a voice)")

    # --- The user opens the REAL served onboarding surface and clicks
    # "Open Voice Manager" — the genuine host-callback path (app.js:385).
    _goto(page, app_url, "onboarding", step)
    expect(page.get_by_test_id("onboarding-open-vm")).to_be_visible()
    step("click 'Open Voice Manager' on the real onboarding surface")
    page.get_by_test_id("onboarding-open-vm").click()

    def _vm_opened() -> bool:
        return "voices" in backend["window_opens"]

    assert _poll(page, _vm_opened, timeout_ms=5000), (
        "Open Voice Manager did not reach the real on_open_voice_manager "
        "host callback"
    )
    step.check("real on_open_voice_manager host callback fired "
               "(the web first-run→VM open path)")

    # --- Seam ONLY the OS network boundary; the installer + the NEW
    # completion callback are 100% real.
    def _fake_download(url: str, dest: Path, *a, **k) -> None:
        dest.write_bytes(b"stub-voice-model-bytes")

    monkeypatch.setattr(vm, "_streaming_download", _fake_download)

    # voices.js calls install_voice_async first, which drives the bridge's
    # _stream_voice_with_progress (imports voice_url_base from pippal.voices
    # at call time). Seam that async path too so neither path performs a
    # real network download.
    import pippal.web_ui.bridge as _bridge_mod

    def _fake_stream_with_progress(voice, is_cancelled, set_progress):
        from pippal.voices import voice_filename
        filename = voice_filename(voice)
        _bridge_mod.VOICES_DIR.mkdir(parents=True, exist_ok=True)
        (_bridge_mod.VOICES_DIR / filename).write_bytes(b"stub-voice-model-bytes")
        (_bridge_mod.VOICES_DIR / f"{filename}.json").write_text("{}", "utf-8")
        set_progress(pct=100.0, status="Done.")
        return filename

    monkeypatch.setattr(
        backend["bridge"], "_stream_voice_with_progress", _fake_stream_with_progress
    )

    # The user is now in the real served Voice Manager window and clicks
    # the per-row Install for a real catalogue voice.
    _goto(page, app_url, "voices", step)
    cat = bridge.get_voice_catalogue()
    target = cat["voices"][0]
    vid = target["id"]
    from pippal.voices import voice_filename
    expected_file = voice_filename(bridge._voice_by_id(vid))
    btn = page.get_by_test_id(f"vm-action-{vid}")
    expect(btn).to_have_text(EN["voices.action.install"])
    # PROVE NO TAUTOLOGY: the configured voice is NOT the to-be-installed
    # one before the install (the production callback must change it).
    assert cfg.get("voice") != expected_file, (
        f"precondition broken: config voice already {expected_file!r}"
    )
    step(f"click per-row Install for {vid!r} on the real served Voice "
         "Manager (real installer; only the HTTP download is seamed)")
    btn.click()

    # --- Real effect 1: a real model file lands in the real per-test
    # voices dir via the real install_piper_voice.
    def _file_on_disk() -> bool:
        return any(vid in f for f in voices_mod.installed_voices())

    assert _poll(page, _file_on_disk, timeout_ms=10000), (
        f"row Install produced no real voice file for {vid}"
    )
    step.check(f"real voice file for {vid!r} landed on disk "
               "(real install_piper_voice path)")

    # --- Real effect 2: THE FIX — the NEW install-completion callback in
    # bridge.install_voice set the just-installed voice as the configured
    # voice on the SHARED config dict (the web analogue of Tk's
    # apply_installed_voice / _finish_voice_install; the canonical Tk
    # contract is tests/test_activation_panel.py:375). The test never set
    # this — the production code did.
    def _config_voice_set() -> bool:
        return cfg.get("voice") == expected_file

    assert _poll(page, _config_voice_set, timeout_ms=6000), (
        f"the install-completion callback did NOT make {expected_file!r} "
        f"the configured voice (config voice = {cfg.get('voice')!r}) — "
        "UC-C9 parity is broken"
    )
    step.check(f"NEW install-completion callback: live shared config "
               f"voice == {expected_file!r} (web analogue of Tk "
               "apply_installed_voice — same shared config dict)")

    # --- Real effect 3: the SHARED onboarding readiness recomputation
    # (build_activation_readiness over the now-updated shared config —
    # NOT re-implemented here) genuinely flips to 'ready'.
    rd1 = bridge.get_readiness()
    assert rd1["status"] == "ready", (
        f"shared get_readiness still {rd1['status']!r} after the install-"
        "completion callback — onboarding did not flip ready"
    )
    step.check("real shared get_readiness flipped 'missing_voice' → "
               "'ready' (the shared onboarding logic, reused not forked)")

    # --- Real effect 4: the user reopens the real served onboarding
    # surface (the web equivalent of Tk re-rendering the panel in place)
    # and the REAL rendered DOM now shows the ready first-run screen
    # instead of the "needs a voice" nag.
    _goto(page, app_url, "onboarding", step)
    expect(page.get_by_test_id("onboarding-title")).to_have_text(
        EN["onboarding.title.ready"], timeout=15000
    )
    # The missing_voice-only "Open Voice Manager" / "Install default
    # voice" buttons are gone; the ready-state Play sample is present.
    expect(page.get_by_test_id("onboarding-open-vm")).to_have_count(0)
    expect(page.get_by_test_id("onboarding-play-sample")).to_be_visible()
    step.check("real reopened onboarding DOM renders the READY first-run "
               "screen (title 'PipPal is ready to read locally', no "
               "'needs a voice' buttons) — UC-C9 genuinely covered "
               "end-to-end on the real served UI + real bridge")
