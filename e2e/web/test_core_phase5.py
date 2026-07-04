"""PipPal Tier-1 real-effect E2E — Phase-5 partial-row closure.

The Core **Phase 5** Tier-1 rows of ``docs/USE_CASE_BACKLOG.md``: close
the three remaining **partial** rows where they are genuinely coverable
without a production change, at a true seam, with a real observable
effect, privilege/host-independently. (Phase-5's Tier-2 breadth — the
J7 right-click round-trip and J8 pause/replay/skip journeys on the real
launched app — is in ``e2e/journey/test_journey_phase5.py``.)

Rows closed here (Tier-1, the per-PR merge gate lane):

* **UC-B2** — *engine-switch-with-missing-piper consequence.* The
  switch *persistence* was already covered
  (``test_settings_engine_and_voice_selection_persists``); the
  **partial** was the *consequence*: switching the engine to ``piper``
  while no real ``piper.exe`` exists makes the real
  ``build_activation_readiness`` return ``missing_piper`` (reading is
  paused / engine falls back), and switching to a non-piper engine
  flips it back to ``ready`` via the genuine non-piper branch
  (``onboarding.py:260-268``). This test drives the **real served
  Settings UI** ``settings-engine`` select → real
  ``bridge.save_config`` → asserts the real persisted ``engine`` AND
  the real ``build_activation_readiness(config)`` /
  ``bridge.get_readiness()`` consequence. No seam — it depends only on
  whether a ``piper.exe`` file exists under the hermetic per-test
  profile + a config value, identical for any caller (Session-0
  LocalSystem included). Code: ``bridge.py:120-136,268-278``;
  ``onboarding.py:249-309``.

* **UC-E1** — *replay a specific Recent item + the empty-state item.*
  The Recent submenu + Clear were covered; the **partial** was that
  ``replay_handler`` (``app_web.py:76``) replaying a *specific* item
  and the disabled ``(empty)`` item were not *individually* asserted as
  real effects. This test builds the **verbatim** pystray menu
  ``app_web.build_tray_menu`` ships, with a **real**
  ``plugins.register_engine`` WAV backend selected so the engine is
  genuinely ``is_ready()`` and the real ``_replay_text_impl`` does NOT
  short-circuit into the no-voice onboarding clip — so invoking the
  real ``replay_handler`` closure for a *specific* history entry drives
  the *unmodified* ``pippal.playback`` loop and the **exact replayed
  text** genuinely lands in the real ``WebOverlay`` (asserted via the
  real served ``bridge.engine_state()`` ``chunk_text`` — a
  text-specific real effect, not a generic token bump), and the
  disabled ``(empty)`` item's real attributes are asserted on a fresh
  profile. The only thing skipped is the OS painting the native menu
  (testing Windows, not PipPal). Privilege/host-independent (a
  registered in-process engine + the real menu callable). Code:
  ``app_web.py:76-93``; ``engine.py:532-550``.

* **UC-E7** — *global-hotkey repeat-dedup / physical-modifier edge.*
  Handler dispatch → real engine was covered; the **partial** was the
  repeat-dedup + physical-modifier match logic in the real
  ``HotkeyManager._on_event`` (``hotkey.py:293-358``). This test feeds
  the **real** ``_on_event`` the *exact* synthetic event objects the
  ``keyboard`` low-level hook passes (``.name`` / ``.event_type``) —
  the established "drive the real handler, skip only the OS routing the
  keystroke into the hook" pattern — for a combo with **no modifiers**
  (so the real ``_physical_modifiers()`` ``GetAsyncKeyState`` read is
  deterministically empty in an automated context where no key is
  physically held — privilege/host-independent: nothing is held on the
  Session-0 runner) and asserts the real observable effects: the first
  ``down`` dispatches the real handler exactly once and returns
  ``False`` (suppress); held-key repeat ``down`` events do NOT re-fire
  the handler and stay suppressed; ``up`` returns ``True`` and clears
  the real ``_held_non_mod`` / ``_suppressed_non_mod`` state; a
  *different* unregistered key passes through (``True``) and never
  fires the handler. The genuine secure-desktop ghost-modifier
  *transition* itself stays an OS boundary (it needs a real UAC /
  secure-desktop switch — already unit-noted and recorded honestly);
  the dedup + exact-match half is fully real-effect here. Code:
  ``hotkey.py:293-358``.

No production code is modified (strictly additive — this new test file
+ docs only). Every condition is induced at a true seam, asserts a real
observable effect, and is privilege/host-independent — never a mock of
the unit under test, never a fixed-sleep sync, never a skip/xfail.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from pippal.hotkey import HotkeyManager, parse_combo
from pippal.web_ui.app_web import build_tray_menu

# ---------------------------------------------------------------------------
# Shared helpers (mirror the established Tier-1 patterns verbatim)
# ---------------------------------------------------------------------------


def _goto(page: Page, app_url: str, view: str, step=None) -> None:
    if step is not None:
        step(f"open '{view}' surface ({app_url}/index.html?view={view})")
    page.goto(f"{app_url}/index.html?view={view}")
    expect(page.locator("body")).to_have_attribute(
        "data-ready", view, timeout=15000
    )
    if step is not None:
        step.check(f"surface '{view}' rendered (body[data-ready={view}])")


def _deadline_poll(page: Page, predicate, *, timeout_ms: int, what: str):
    """Deadline-poll a predicate using the page clock (no fixed sleep —
    the same robustness pattern the rest of e2e/web uses)."""
    deadline = page.evaluate("Date.now()") + timeout_ms
    last = None
    while page.evaluate("Date.now()") < deadline:
        last = predicate()
        if last:
            return last
        page.wait_for_timeout(100)
    raise AssertionError(
        f"deadline-poll timed out after {timeout_ms}ms waiting for "
        f"{what} (last={last!r})"
    )


class _RealWavBackend:
    """A real ``TTSBackend`` registered via the genuine
    ``plugins.register_engine`` API (the same family as
    ``test_core_phase4.py`` / ``test_core_interactions.py``).
    ``is_ready()`` True so the engine takes the REAL synth path (NOT the
    no-voice onboarding clip), so the *unmodified* ``pippal.playback``
    loop genuinely runs and the real ``WebOverlay`` ``start_chunk``
    genuinely records the exact text. Not a mock of any PipPal code
    path — a real registered engine. A short clip so a single read
    completes quickly without any fixed sleep."""

    name = "realwav-core-p5"
    _RATE = 22050
    _SECONDS = 0.6

    def __init__(self, config: dict[str, Any]) -> None:
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
    select it on the live config, drop the engine's cached backend so
    the next synth picks it up, restore on teardown. Additive: the core
    ``piper`` engine stays registered (mirrors the Phase-4 fixture)."""
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


class _RecordingWindows:
    """Headless stand-in for ``WebWindowManager`` (verbatim from
    ``test_tray_hotkey_integration.py`` — ``open`` calls
    ``webview.create_window``, a real GUI window with no headless
    equivalent; the genuine, testable tray contract is *which surface
    the item asks to open*)."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.shutdown_calls = 0

    def open(self, surface: str) -> None:
        self.opened.append(surface)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeIcon:
    """Stand-in for the ``pystray.Icon`` pystray passes as the first
    positional arg into a menu-item action (verbatim from
    ``test_tray_hotkey_integration.py``)."""

    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


def _flatten(menu: Any) -> list[Any]:
    import pystray

    return [it for it in menu.items if it is not pystray.Menu.SEPARATOR]


def _find_item(menu: Any, text_prefix: str) -> Any:
    for item in _flatten(menu):
        if str(item.text).startswith(text_prefix):
            return item
    raise AssertionError(
        f"tray item starting {text_prefix!r} not found; "
        f"have {[i.text for i in _flatten(menu)]}"
    )


# ===========================================================================
# UC-B2 — engine-switch-with-missing-piper consequence (Settings → readiness)
# ===========================================================================


def test_engine_switch_missing_piper_changes_real_readiness_consequence(
    page: Page, app_url: str, backend, step
):
    """Switching the TTS engine in the **real served Settings UI** must
    not only persist — it must change the real *consequence* the user
    feels: with ``engine=piper`` and no real ``piper.exe`` the genuine
    ``build_activation_readiness`` returns ``missing_piper`` (reading
    paused / engine falls back); switching to a non-piper engine flips
    the real readiness back to ``ready`` via the genuine non-piper
    branch. This is the exact UC-B2 ``partial`` gap: the *switch path
    persists* was covered; the *readiness/fallback consequence* was not
    asserted. No seam — depends only on a ``piper.exe`` file existing
    under the hermetic per-test profile + a config value (identical for
    any caller incl. the Session-0 LocalSystem runner).
    """
    from pippal import plugins
    from pippal.onboarding import build_activation_readiness
    from pippal.paths import PIPER_EXE

    config = backend["config"]
    bridge = backend["bridge"]

    with step.group(
        "UC-B2.0 precondition: this checkout has NO real piper.exe — so "
        "engine=piper genuinely yields the missing_piper consequence "
        "(not a tautology / pre-arranged state)"
    ):
        assert not Path(PIPER_EXE).exists(), (
            f"a real piper.exe exists at {PIPER_EXE} — UC-B2 needs the "
            f"genuine missing-piper consequence; the precondition is not "
            f"met (would be a tautology)"
        )
        step.check(f"no real piper.exe at {PIPER_EXE} (genuine missing state)")

    with step.group(
        "UC-B2.1 user switches engine to 'piper' in the real served "
        "Settings UI → it must persist AND the real readiness "
        "consequence must become missing_piper (reading paused / engine "
        "falls back)"
    ):
        _goto(page, app_url, "settings", step)
        step("select settings-engine = piper and click Save")
        page.get_by_test_id("settings-engine").select_option("piper")
        page.get_by_test_id("settings-save").click()
        expect(page.get_by_test_id("toast")).to_contain_text("Saved")
        step.check('real served Settings Save → toast "Saved"')

        # Real persisted effect (the live config the engine reads).
        assert config["engine"] == "piper", config.get("engine")
        step.check("live config engine == 'piper' (real persisted switch)")

        # THE UC-B2 consequence: the real readiness function, run for
        # real against the real on-disk state, returns missing_piper.
        rd = build_activation_readiness(config)
        assert rd.status == "missing_piper", (
            f"engine=piper with no real piper.exe must yield "
            f"missing_piper readiness; got {rd.status!r}"
        )
        # And the SAME consequence is what the real served bridge the UI
        # consults reports (get_readiness drives the onboarding surface).
        served = bridge.get_readiness()
        assert served["status"] == "missing_piper", served
        assert "Piper engine" in served["engine_label"], served
        assert not served["can_play_sample"], (
            "missing_piper must disable Play sample (reading paused) — "
            f"served readiness still allows it: {served}"
        )
        step.check(
            "real build_activation_readiness AND served "
            "bridge.get_readiness() == 'missing_piper', can_play_sample "
            "False (reading paused — the real engine-fallback consequence "
            "the UC-B2 partial said was unasserted)"
        )

    with step.group(
        "UC-B2.2 user switches to a non-piper engine → the real "
        "readiness consequence must flip to 'ready' via the genuine "
        "non-piper branch (onboarding.py:260-268) — proves the switch "
        "changes the consequence both ways, not just persists"
    ):
        # Register a real non-piper engine via the genuine plugin API so
        # the engine_name != 'piper' branch is reached for real (no mock
        # of the readiness logic — its real non-piper branch runs).
        plugins.register_engine(_RealWavBackend.name, _RealWavBackend)
        try:
            _goto(page, app_url, "settings", step)
            step(f"select settings-engine = {_RealWavBackend.name} and Save")
            page.get_by_test_id("settings-engine").select_option(
                _RealWavBackend.name
            )
            page.get_by_test_id("settings-save").click()
            expect(page.get_by_test_id("toast")).to_contain_text("Saved")

            assert config["engine"] == _RealWavBackend.name, config.get(
                "engine"
            )
            rd2 = build_activation_readiness(config)
            assert rd2.status == "ready", (
                f"a non-piper engine must take the genuine non-piper "
                f"ready branch (onboarding.py:260-268); got {rd2.status!r}"
            )
            served2 = bridge.get_readiness()
            assert served2["status"] == "ready", served2
            assert served2["can_play_sample"] is True, served2
            step.check(
                f"engine={_RealWavBackend.name}: real readiness flipped "
                "to 'ready' (non-piper branch), can_play_sample True — "
                "the switch changes the real consequence BOTH ways"
            )
        finally:
            plugins._engines.pop(_RealWavBackend.name, None)
            config["engine"] = "piper"
            backend["engine"].reset_backend()


# ===========================================================================
# UC-E1 — replay a SPECIFIC Recent item + the empty-state item
# ===========================================================================


def test_tray_recent_replay_specific_item_and_empty_state_real_effect(
    page: Page, app_url: str, backend, realwav_engine, step
):
    """The tray Recent submenu's ``replay_handler`` (``app_web.py:76``)
    must replay the **specific** clicked entry's text — and the
    no-history ``(empty)`` item must be a genuine disabled placeholder.
    UC-E1's ``partial`` was exactly that these two were not
    *individually* asserted as real effects (the existing test bundles
    them and only checks a generic token bump, which ``stop()`` would
    also satisfy).

    With a **real** ``plugins.register_engine`` WAV backend selected
    (``realwav_engine``) the engine is genuinely ``is_ready()`` so the
    real ``_replay_text_impl`` does NOT short-circuit into the no-voice
    onboarding clip — invoking the real ``replay_handler`` closure for a
    *specific* entry drives the *unmodified* ``pippal.playback`` loop
    and the **exact replayed text** genuinely lands in the real
    ``WebOverlay`` (asserted via the real served ``bridge
    .engine_state()`` ``chunk_text`` — a text-specific real effect, not
    a generic token bump). Privilege/host-independent (a registered
    in-process engine + the real menu callable).
    """
    from pippal.history import load_history, save_history

    engine = backend["engine"]
    bridge = backend["bridge"]

    windows = _RecordingWindows()
    hkm = HotkeyManager()
    hkm.start()
    step("build the verbatim pystray menu app_web.build_tray_menu ships")
    menu, _primitives = build_tray_menu(
        engine=engine,
        config=backend["config"],
        windows=windows,
        hotkey_manager=hkm,
    )
    try:
        recent = _find_item(menu, "Recent")
        assert recent.submenu is not None

        with step.group(
            "UC-E1.1 fresh profile: the Recent submenu's no-history item "
            "must be the genuine disabled '(empty)' placeholder "
            "(individually asserted — app_web.py:82)"
        ):
            empty_items = list(recent.submenu.items)
            assert [i.text for i in empty_items] == ["(empty)"], (
                f"empty Recent submenu is not the single '(empty)' row: "
                f"{[i.text for i in empty_items]}"
            )
            assert empty_items[0].enabled is False, (
                "the '(empty)' Recent item must be disabled (a real "
                "non-actionable placeholder), got enabled=True"
            )
            # Invoking it is a real no-op: it must not drive the engine
            # and must not open any window.
            with engine.lock:
                tok_pre_empty = engine.token
            empty_items[0](_FakeIcon())
            with engine.lock:
                assert engine.token == tok_pre_empty, (
                    "the disabled '(empty)' item drove the engine "
                    "(token changed) — it must be an inert placeholder"
                )
            assert windows.opened == []
            step.check(
                "fresh profile: Recent shows exactly one disabled "
                "'(empty)' item; invoking it is a genuine no-op (engine "
                "untouched, no window opened)"
            )

        with step.group(
            "UC-E1.2 populate Recent via the REAL history persistence "
            "the app uses at startup, then invoke the SPECIFIC second "
            "entry's real replay_handler → the EXACT replayed text must "
            "reach the real engine/overlay (text-specific, not a generic "
            "token bump)"
        ):
            entry_one = "Phase five recent entry ALPHA — the first one."
            entry_two = "Phase five recent entry BRAVO — replay exactly me."
            step("save_history([2]) + engine.attach_history (real startup path)")
            save_history([entry_one, entry_two])
            engine.attach_history(load_history(), save_history)

            # pystray re-evaluates a callable submenu on every open — the
            # real builder now enumerates the live history.
            items = list(recent.submenu.items)
            texts = [i.text for i in items]
            assert entry_one in texts and entry_two in texts, texts
            assert "Clear history" in texts, texts
            step.check(
                "real Recent submenu re-enumerated both live history "
                "entries + the Clear item"
            )

            with engine.lock:
                tok_before = engine.token
            step(
                "invoke the SPECIFIC second entry's real replay_handler "
                "closure exactly as a pystray click does"
            )
            _find_item(recent.submenu, entry_two)(_FakeIcon())

            # THE UC-E1 real effect: the EXACT replayed text reaches the
            # real engine and the real WebOverlay (not merely a token
            # bump). Assert the text-specific observable via the same
            # served bridge.engine_state() the desktop UI uses.
            def _replayed_text_landed() -> bool:
                snap = bridge.engine_state()
                ct = (snap.get("chunk_text") or "").strip()
                # Wait until the SPECIFIC entry's text has ACTUALLY landed.
                # The old `... or ct in entry_two` clause was True for an
                # empty chunk_text ("" is a substring of everything), so the
                # poll could return before the real async read populated the
                # overlay — the downstream `"BRAVO" in chunk_text` assert
                # then flaked. Require the distinctive leading segment.
                return entry_two.split(" — ")[0] in ct

            _deadline_poll(
                page,
                _replayed_text_landed,
                timeout_ms=12000,
                what="the EXACT replayed text to land in the real overlay",
            )
            snap = bridge.engine_state()
            with engine.lock:
                tok_after = engine.token
            assert tok_after > tok_before, (
                "replay_handler did not reach the real engine "
                f"(token {tok_before} -> {tok_after})"
            )
            chunk_text = (snap.get("chunk_text") or "").strip()
            assert "BRAVO" in chunk_text, (
                f"the engine is reading the WRONG text — replay_handler "
                f"must replay the SPECIFIC clicked entry "
                f"({entry_two!r}); overlay chunk_text={chunk_text!r}"
            )
            assert "ALPHA" not in chunk_text, (
                f"the first entry's text leaked into the read — "
                f"replay_handler bound the wrong closure variable; "
                f"chunk_text={chunk_text!r}"
            )
            step.check(
                f"the SPECIFIC entry's real replay_handler drove the real "
                f"engine (token {tok_before}->{tok_after}) and the EXACT "
                f"text reached the real WebOverlay (chunk_text contains "
                f"'BRAVO', not 'ALPHA') — text-specific real effect"
            )
            engine.stop()

        with step.group(
            "UC-E1.3 replaying a recent item must NOT itself record a "
            "new duplicate Recent entry (replay_text != read_text — the "
            "genuine replay contract) and must open no window"
        ):
            # replay_text intentionally does NOT _remember (only
            # read_text does); the history must be unchanged by a replay.
            hist_after = engine.get_history()
            assert hist_after == [entry_one, entry_two], (
                f"replaying a Recent item changed the history "
                f"{hist_after!r} — replay must not re-record (only "
                f"read_text remembers)"
            )
            assert windows.opened == [], (
                f"Recent replay opened a window {windows.opened!r} — it "
                f"must not"
            )
            step.check(
                "Recent history unchanged by the replay (replay_text does "
                "not _remember) and no window opened — the genuine replay "
                "contract"
            )
    finally:
        try:
            engine.stop()
        except Exception:
            pass
        hkm.stop()


# ===========================================================================
# UC-E7 — global-hotkey repeat-dedup / physical-modifier match edge logic
# ===========================================================================


class _Ev:
    """The exact shape the ``keyboard`` low-level hook passes into
    ``HotkeyManager._on_event`` — a ``.name`` + ``.event_type``. The
    only thing skipped vs a physical press is the OS routing the
    keystroke into the hook (testing Windows, not PipPal); the real
    ``_on_event`` logic runs verbatim."""

    def __init__(self, name: str, event_type: str) -> None:
        self.name = name
        self.event_type = event_type


def test_hotkey_repeat_dedup_and_exact_match_real_effect(
    page: Page, app_url: str, backend, step
):
    """Drive the **real** ``HotkeyManager._on_event`` (``hotkey.py:293
    -358``) — the repeat-dedup + exact-match logic the UC-E7 ``partial``
    named as journey-untested — with the *exact* synthetic event objects
    the ``keyboard`` hook passes, for a combo with **no modifiers** so
    the real ``_physical_modifiers()`` ``GetAsyncKeyState`` read is
    deterministically empty in this automated context (nothing is
    physically held on the Session-0 runner — privilege/host
    -independent).

    Asserts the real observable effects of the genuine code path:

    * first ``down`` of the registered trigger → the real handler is
      dispatched **exactly once** (off the real ``_safe_call`` thread)
      and ``_on_event`` returns ``False`` (SUPPRESS — only this exact
      combo);
    * held-key **repeat** ``down`` events (Windows fires ~30 ms while
      held) → the real handler is **not** re-fired and the event stays
      suppressed (``False``) — the genuine repeat-dedup contract;
    * ``up`` → returns ``True`` (pass-through) and the real
      ``_held_non_mod`` / ``_suppressed_non_mod`` state is cleared;
    * a **different**, unregistered trigger key → ``_on_event`` returns
      ``True`` (pass-through to the foreground app) and the handler is
      never fired (the strict exact-match guarantee).

    Only the OS *delivering* the keystroke into the hook is skipped; the
    decision logic is the real production code. The genuine
    secure-desktop ghost-modifier *transition* itself (a real UAC /
    secure-desktop switch making ``GetAsyncKeyState`` disagree with the
    hook stream) remains an OS boundary — already unit-noted and
    recorded honestly; the dedup + exact-match half is real-effect here.
    """
    from pippal.hotkey import _physical_modifiers

    hits: list[int] = []

    def _handler() -> None:
        hits.append(1)

    # An obscure trigger with NO modifiers: parse_combo('f24') ->
    # (frozenset(), 'f24'). With no modifier physically held (automated
    # context) the real _physical_modifiers() returns frozenset(), so
    # the real (mods_now, name) lookup matches deterministically — no
    # host/privilege dependence.
    combo = "f24"
    trigger = "f24"

    hkm = HotkeyManager()
    hkm.start()
    try:
        with step.group(
            "UC-E7.0 precondition: no modifier is physically held in "
            "this automated context, so the real _physical_modifiers() "
            "GetAsyncKeyState read is deterministically empty "
            "(privilege/host-independent match)"
        ):
            assert _physical_modifiers() == frozenset(), (
                f"a modifier is physically held ({_physical_modifiers()}) "
                f"— UC-E7 needs the deterministic no-modifier match; an "
                f"automated runner holds nothing"
            )
            assert parse_combo(combo) == (frozenset(), trigger), parse_combo(
                combo
            )
            step.check(
                "real _physical_modifiers() == frozenset(); "
                f"parse_combo({combo!r}) == (frozenset(), {trigger!r})"
            )

        step(f"register the real handler on the modifier-free combo {combo!r}")
        assert hkm.register(combo, _handler) is True
        # The manager stored the exact handler under the parsed identity
        # — the same object _safe_call runs when the combo fires.
        assert hkm._handlers.get(parse_combo(combo)) is _handler
        step.check("real HotkeyManager stored the exact handler object")

        with step.group(
            "UC-E7.1 first physical 'down' → the real _on_event must "
            "dispatch the handler exactly once and SUPPRESS (return "
            "False — only this exact combo)"
        ):
            ret = hkm._on_event(_Ev(trigger, "down"))
            assert ret is False, (
                f"first down of a registered combo must SUPPRESS "
                f"(_on_event -> False); got {ret!r}"
            )
            # Handler dispatches off a real daemon thread — deadline-poll
            # (no fixed sleep).
            _deadline_poll(
                page,
                lambda: len(hits) >= 1,
                timeout_ms=6000,
                what="the real handler to fire once on the first down",
            )
            assert hits == [1], f"handler fired {len(hits)} times, want 1"
            # Real internal state: the trigger is now held + suppressed.
            with hkm._lock:
                assert trigger in hkm._held_non_mod
                assert trigger in hkm._suppressed_non_mod
            step.check(
                "first 'down' → real handler fired exactly once, "
                "_on_event returned False (suppress), trigger recorded "
                "held+suppressed"
            )

        with step.group(
            "UC-E7.2 held-key REPEAT 'down' events (Windows auto-repeat) "
            "→ the real handler must NOT re-fire and the event must stay "
            "suppressed (the genuine repeat-dedup contract, "
            "hotkey.py:331-332)"
        ):
            for i in range(5):
                ret = hkm._on_event(_Ev(trigger, "down"))
                assert ret is False, (
                    f"repeat #{i} of a suppressed held combo must STAY "
                    f"suppressed (_on_event -> False); got {ret!r}"
                )
            # Give any (erroneous) extra dispatch a real chance to land,
            # then assert it genuinely did NOT — the dedup held.
            page.wait_for_timeout(400)
            assert hits == [1], (
                f"the real handler re-fired on held-key repeat "
                f"(fired {len(hits)} times) — the repeat-dedup in "
                f"_on_event is broken / not exercised"
            )
            step.check(
                "5 repeat 'down' events stayed suppressed (False) and the "
                "real handler did NOT re-fire (still exactly 1) — genuine "
                "repeat-dedup"
            )

        with step.group(
            "UC-E7.3 a DIFFERENT unregistered trigger key → the real "
            "_on_event must pass it through (return True) and never fire "
            "our handler (the strict exact-match guarantee, "
            "hotkey.py:338-339)"
        ):
            ret_other_down = hkm._on_event(_Ev("f23", "down"))
            ret_other_up = hkm._on_event(_Ev("f23", "up"))
            assert ret_other_down is True, (
                f"an unregistered key's down must pass through "
                f"(_on_event -> True); got {ret_other_down!r}"
            )
            assert ret_other_up is True, ret_other_up
            assert hits == [1], (
                f"an unregistered key fired our handler (hits={hits}) — "
                f"exact-match is broken"
            )
            step.check(
                "unregistered 'f23' down/up both passed through (True) "
                "and never fired our handler — strict exact-match holds"
            )

        with step.group(
            "UC-E7.4 'up' of the registered trigger → the real _on_event "
            "must pass through (True) and clear the real held/suppressed "
            "state so the NEXT physical press fires again (hotkey.py:352"
            "-356)"
        ):
            ret_up = hkm._on_event(_Ev(trigger, "up"))
            assert ret_up is True, (
                f"'up' must pass through (_on_event -> True); got "
                f"{ret_up!r}"
            )
            with hkm._lock:
                assert trigger not in hkm._held_non_mod, (
                    "'up' did not clear _held_non_mod — a stale held key "
                    "would block / mis-handle the next press"
                )
                assert trigger not in hkm._suppressed_non_mod
            step.check(
                "'up' returned True and cleared real _held_non_mod / "
                "_suppressed_non_mod (next press starts clean)"
            )

        with step.group(
            "UC-E7.5 a fresh physical press AFTER the 'up' → the real "
            "handler must fire again exactly once (proves the dedup is "
            "per-press, not a permanent latch)"
        ):
            ret = hkm._on_event(_Ev(trigger, "down"))
            assert ret is False, ret
            _deadline_poll(
                page,
                lambda: len(hits) >= 2,
                timeout_ms=6000,
                what="the real handler to fire again on a fresh press",
            )
            assert hits == [1, 1], (
                f"a fresh press after 'up' did not fire exactly once more "
                f"(hits={hits}) — dedup must be per-physical-press"
            )
            hkm._on_event(_Ev(trigger, "up"))
            step.check(
                "a fresh press after 'up' fired the real handler again "
                "exactly once — the repeat-dedup is per-press, not a "
                "permanent latch"
            )
    finally:
        hkm.stop()
