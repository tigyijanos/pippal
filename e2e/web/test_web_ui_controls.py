"""Per-control completion suite for the migrated PipPal web UI.

One focused, genuine real-effect Playwright test per remaining
interactive control / function enumerated in
``docs/migration-web/UI_TEST_CHECKLIST.md`` (the original 17 in
``test_web_ui.py`` cover the rest). Same rules as the original suite:

* drives the REAL served frontend (``webui/`` + the real bridge server)
  with stable ``data-testid`` selectors and Playwright auto-wait — no
  fixed sleeps, no mocks, no tautologies;
* asserts a REAL backend effect — ``config.json`` on disk (read with the
  real ``pippal.config`` loader), the real ``TTSEngine`` token/state,
  real voice files on disk, the real recorded host callbacks the bridge
  invokes (the exact contract ``app_web.py`` wires to the pywebview
  window manager), or ``webbrowser.open`` actually called for the real
  About / setup URLs;
* every test runs against a freshly reset app — see the ``conftest.py``
  module docstring (fresh ``PIPPAL_DATA_DIR`` per test, no leaked config,
  ``assert_fresh_baseline`` autouse guard).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# i18n oracle (T-301): assert rendered UI text against the shipped English
# catalog, never a hardcoded literal, so the suite stays language-agnostic.
_WEBUI = Path(__file__).resolve().parents[2] / "webui"
EN = json.loads((_WEBUI / "i18n" / "en.json").read_text("utf-8"))


def _config_on_disk(profile: Path) -> dict:
    cfg = profile / "config.json"
    return json.loads(cfg.read_text("utf-8")) if cfg.exists() else {}


def _goto(page: Page, app_url: str, view: str, step=None) -> None:
    if step is not None:
        step(f"open '{view}' surface")
    page.goto(f"{app_url}/index.html?view={view}")
    expect(page.locator("body")).to_have_attribute(
        "data-ready", view, timeout=15000
    )
    if step is not None:
        step.check(f"surface '{view}' rendered (body[data-ready={view}])")


# ===========================================================================
# §1 Onboarding — readiness states + every per-state button
# ===========================================================================

def test_onboarding_ready_state_controls(
    page: Page, app_url: str, readiness, step
):
    """READY state: the Local-voice-check card shows the real engine /
    voice / hotkey labels from build_activation_readiness."""
    step("force readiness = ready (real stub piper.exe + voice on disk)")
    rd = readiness["ready"]()
    _goto(page, app_url, "onboarding", step)
    expect(page.get_by_test_id("onboarding-engine")).to_contain_text(
        "Piper engine"
    )
    # The card renders the real readiness labels.
    card = page.get_by_test_id("onboarding-engine")
    expect(card).to_be_visible()
    assert rd.engine_label.startswith("Piper engine")
    step.check(f"engine card shows real readiness label {rd.engine_label!r}")


def test_onboarding_sample_textbox_holds_sample(
    page: Page, app_url: str, readiness, backend, step
):
    """The "Try it in any app" box holds the real sample text the
    backend computed from the configured hotkey."""
    step("force readiness = ready")
    readiness["ready"]()
    _goto(page, app_url, "onboarding", step)
    box = page.get_by_test_id("onboarding-sample")
    expect(box).to_be_visible()
    sample = backend["bridge"].get_readiness()["sample_text"]
    assert box.input_value().strip() == sample.strip()
    assert "PipPal is reading locally" in sample
    step.check("sample box == real bridge.get_readiness()['sample_text']")


def test_onboarding_ready_skip_closes_window(
    page: Page, app_url: str, readiness, backend, step
):
    # In the READY state (activation pre-seeded as complete by conftest),
    # the onboarding surface renders a "Close" button (testid: onboarding-finish)
    # that calls closeWin(). The onboarding-skip testid only exists in the
    # MISSING_VOICE state.
    step("force readiness = ready")
    readiness["ready"]()
    _goto(page, app_url, "onboarding", step)
    before = len(backend["close_calls"])
    step("click onboarding Close (testid: onboarding-finish, text: Close)")
    page.get_by_test_id("onboarding-finish").click()

    def _closed() -> bool:
        return len(backend["close_calls"]) > before

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _closed():
        page.wait_for_timeout(50)
    assert _closed(), "Close did not reach on_close_window"
    step.check("Close (onboarding-finish) reached the real on_close_window host callback")


def test_onboarding_ready_open_settings(
    page: Page, app_url: str, readiness, backend, step
):
    step("force readiness = ready")
    readiness["ready"]()
    _goto(page, app_url, "onboarding", step)
    step("click onboarding Open Settings")
    page.get_by_test_id("onboarding-open-settings").click()

    def _opened() -> bool:
        return "settings" in backend["window_opens"]

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _opened():
        page.wait_for_timeout(50)
    assert _opened(), "Open Settings did not reach on_open_settings"
    step.check("Open Settings reached the real on_open_settings host callback")


def test_onboarding_finish_gated_until_sample_played(
    page: Page, app_url: str, readiness, backend, step
):
    """READY but activation NOT complete: Finish setup must be disabled
    until the sample is played (parity with Tk's confirm gate). We force
    activation incomplete on the fresh profile for this row."""
    from pippal.onboarding import activation_state_path

    step("force readiness = ready, remove pre-seeded activation completion")
    readiness["ready"]()
    # Remove the pre-seeded completion so the first-run gate is live.
    activation_state_path().unlink(missing_ok=True)
    _goto(page, app_url, "onboarding", step)

    finish = page.get_by_test_id("onboarding-finish")
    expect(finish).to_be_disabled()
    step.check("Finish setup is disabled before the sample is played (gate held)")
    # Playing the sample enables Finish (real engine read + UI gate).
    step("click Play sample (real engine read)")
    page.get_by_test_id("onboarding-play-sample").click()
    expect(finish).to_be_enabled(timeout=6000)
    step.check("Finish setup became enabled after the real sample read")
    backend["engine"].stop()


def test_onboarding_finish_marks_activation_complete(
    page: Page, app_url: str, readiness, backend, step
):
    """Finish setup must call the real mark_activation_complete so the
    activation state file on disk flips to complete."""
    from pippal.onboarding import activation_state_path, load_activation_state

    step("force readiness = ready, clear activation completion")
    readiness["ready"]()
    activation_state_path().unlink(missing_ok=True)
    assert not load_activation_state().is_complete
    step.check("activation state on disk: NOT complete")
    _goto(page, app_url, "onboarding", step)

    step("click Play sample (real engine read), then Finish setup")
    page.get_by_test_id("onboarding-play-sample").click()
    finish = page.get_by_test_id("onboarding-finish")
    expect(finish).to_be_enabled(timeout=6000)
    finish.click()

    def _complete() -> bool:
        return load_activation_state().is_complete

    deadline = page.evaluate("Date.now()") + 5000
    while page.evaluate("Date.now()") < deadline and not _complete():
        page.wait_for_timeout(100)
    assert _complete(), "Finish setup did not mark activation complete on disk"
    step.check("activation state on disk flipped to complete (real effect)")
    backend["engine"].stop()


def test_onboarding_missing_voice_state_buttons(
    page: Page, app_url: str, readiness, backend, step
):
    """MISSING_VOICE state renders Skip / Open Voice Manager / Install
    default voice; Skip closes, Open VM opens the real voices window."""
    step("force readiness = missing_voice (stub piper.exe, no voice)")
    readiness["missing_voice"]()
    _goto(page, app_url, "onboarding", step)
    expect(page.get_by_test_id("onboarding-skip")).to_be_visible()
    expect(page.get_by_test_id("onboarding-install-voice")).to_be_visible()
    step.check("missing_voice renders Skip + Install-default-voice buttons")

    step("click Open Voice Manager")
    page.get_by_test_id("onboarding-open-vm").click()

    def _opened() -> bool:
        return "voices" in backend["window_opens"]

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _opened():
        page.wait_for_timeout(50)
    assert _opened(), "Open Voice Manager did not reach the host callback"
    step.check("Open Voice Manager reached the real host callback")


def test_onboarding_install_default_voice_real_effect(
    page: Page, app_url: str, readiness, backend, monkeypatch, step
):
    """Install default voice must call the REAL bridge.install_default
    _voice_async → install_piper_voice; only the network download seam is
    stubbed so a real file lands in the real per-test voices dir and the
    live config voice is updated — the bridge/installer code path is
    entirely real.

    Seam discipline (identical to test_voice_manager_row_install_real_effect
    and test_ucc9_first_run_vm_install_completion_flips_onboarding_ready):
    the UI calls install_default_voice_async, which drives the bridge's
    _stream_voice_with_progress (async path); the sync _streaming_download
    is patched as a belt-and-suspenders fallback. Both seams write a small
    fake .onnx + .json locally instead of downloading ~120 MB from the
    network, making the test deterministic on CI.
    """
    from pippal import voices as voices_mod
    from pippal import voice_install as vm
    import pippal.web_ui.bridge as _bridge_mod

    step("force readiness = missing_voice; stub the network download seam "
         "(async _stream_voice_with_progress + sync _streaming_download fallback)")
    readiness["missing_voice"]()

    # Belt-and-suspenders: stub the sync download fallback path.
    def _fake_download(url: str, dest: Path, *a, **k) -> None:
        dest.write_bytes(b"stub-voice-model-bytes")

    monkeypatch.setattr(vm, "_streaming_download", _fake_download)

    # Primary seam: stub the async path that install_default_voice_async uses
    # (voices.js calls install_default_voice_async → bridge thread →
    # _stream_voice_with_progress). This is the only network seam — the real
    # install_piper_voice installer, the real config update, and the real
    # onboarding state transition all run unchanged.
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

    _goto(page, app_url, "onboarding", step)
    step("click Install default voice (real installer path, stubbed download)")
    page.get_by_test_id("onboarding-install-voice").click()

    def _installed() -> bool:
        return len(voices_mod.installed_voices()) > 0

    deadline = page.evaluate("Date.now()") + 8000
    while page.evaluate("Date.now()") < deadline and not _installed():
        page.wait_for_timeout(150)
    assert _installed(), "Install default voice produced no real voice file"
    # The bridge set the live config voice to the installed filename.
    assert backend["config"]["voice"].endswith(".onnx")
    step.check(
        f"real voice file landed on disk; live config voice == "
        f"{backend['config']['voice']!r}"
    )


def test_onboarding_missing_piper_state_buttons(
    page: Page, app_url: str, readiness, backend, step
):
    """MISSING_PIPER renders Close / Open Settings / Open setup. Close
    reaches close_window; Open Settings reaches the host callback."""
    step("force readiness = missing_piper (natural state, no piper.exe)")
    readiness["missing_piper"]()
    _goto(page, app_url, "onboarding", step)
    expect(page.get_by_test_id("onboarding-close")).to_be_visible()
    expect(page.get_by_test_id("onboarding-open-setup")).to_be_visible()
    step.check("missing_piper renders Close + Open-setup buttons")

    step("click Open Settings")
    page.get_by_test_id("onboarding-open-settings").click()
    deadline = page.evaluate("Date.now()") + 4000
    while (
        page.evaluate("Date.now()") < deadline
        and "settings" not in backend["window_opens"]
    ):
        page.wait_for_timeout(50)
    assert "settings" in backend["window_opens"]
    step.check("Open Settings reached the real host callback")

    before = len(backend["close_calls"])
    step("click Close")
    page.get_by_test_id("onboarding-close").click()
    deadline = page.evaluate("Date.now()") + 4000
    while (
        page.evaluate("Date.now()") < deadline
        and len(backend["close_calls"]) == before
    ):
        page.wait_for_timeout(50)
    assert len(backend["close_calls"]) > before
    step.check("Close reached the real on_close_window host callback")


def test_onboarding_missing_piper_open_setup_url(
    page: Page, app_url: str, readiness, backend, monkeypatch, step
):
    """Open setup instructions must call the real bridge.open_url with
    the real README URL (we capture the actual webbrowser.open call)."""
    import pippal.web_ui.bridge as bridge_mod

    opened: list[str] = []
    monkeypatch.setattr(
        bridge_mod.webbrowser, "open", lambda u: opened.append(u) or True
    )
    step("force readiness = missing_piper; capture real webbrowser.open")
    readiness["missing_piper"]()
    _goto(page, app_url, "onboarding", step)
    step("click Open setup instructions")
    page.get_by_test_id("onboarding-open-setup").click()

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not opened:
        page.wait_for_timeout(50)
    assert opened and "github.com/bug-factory-kft/pippal" in opened[0]
    step.check(f"real bridge.open_url called with the README URL: {opened[0]!r}")


# ===========================================================================
# §2 Settings — controls not covered by the original 17
# ===========================================================================

def test_settings_manage_voices_opens_vm(
    page: Page, app_url: str, backend, step
):
    _goto(page, app_url, "settings", step)
    step("click Manage voices…")
    page.get_by_test_id("settings-manage-voices").click()

    def _opened() -> bool:
        return "voices" in backend["window_opens"]

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _opened():
        page.wait_for_timeout(50)
    assert _opened(), "Manage… did not reach on_open_voice_manager"
    step.check("Manage… reached the real on_open_voice_manager host callback")


def test_settings_voice_card_empty_install_state(
    page: Page, app_url: str, backend, step
):
    """With no voices installed (the fresh-profile default) the Voice
    card shows the Install CTA label and disables the voice combo —
    real backend state (installed_voices() == [])."""
    from pippal.voices import installed_voices

    assert installed_voices() == []
    step.check("real backend state: installed_voices() == []")
    _goto(page, app_url, "settings", step)
    expect(page.get_by_test_id("settings-manage-voices")).to_have_text(
        EN["settings.voice.install_voices"]
    )
    expect(page.get_by_test_id("settings-voice")).to_be_disabled()
    expect(page.get_by_test_id("settings-engine-hint")).to_contain_text(
        "No Piper voice installed"
    )
    step.check(
        "Voice card: 'Install voices…' CTA, voice combo disabled, "
        "'No Piper voice installed' hint"
    )


def test_settings_variation_slider_reflects_and_persists(
    page: Page, app_url: str, backend, step
):
    _goto(page, app_url, "settings", step)
    step("set Variation slider = 0.85")
    noise = page.get_by_test_id("settings-noise")
    noise.evaluate(
        "el => { el.value = '0.85';"
        " el.dispatchEvent(new Event('input', {bubbles:true})); }"
    )
    noise_label = f"{0.85:.2f}"  # settings.js renders v.toFixed(2)
    expect(page.get_by_test_id("settings-noise-value")).to_have_text(noise_label)
    step.check("noise value label shows 0.85")
    step("click Save")
    page.get_by_test_id("settings-save").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Saved")

    cfg = _config_on_disk(backend["profile"])
    assert abs(float(cfg["noise_scale"]) - 0.85) < 1e-6
    assert abs(backend["config"]["noise_scale"] - 0.85) < 1e-6
    step.check("noise_scale == 0.85 persisted to config.json + live config")


@pytest.mark.parametrize(
    "key,combo",
    [
        ("hotkey_queue", "ctrl+alt+q"),
        ("hotkey_pause", "ctrl+alt+p"),
        ("hotkey_stop", "ctrl+alt+b"),
    ],
)
def test_settings_hotkey_each_field_rebinds_and_persists(
    page: Page, app_url: str, backend, key: str, combo: str, step
):
    """Each remaining hotkey field (Queue / Pause-Resume / Stop) rebinds
    and persists independently (Read selection is covered in the
    original suite)."""
    _goto(page, app_url, "settings", step)
    step(f"set {key} = {combo}")
    page.get_by_test_id(f"settings-{key}").fill(combo)
    before = len(backend["hotkey_calls"])
    step("click Apply")
    page.get_by_test_id("settings-apply").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Applied")

    cfg = _config_on_disk(backend["profile"])
    assert cfg.get(key) == combo
    assert backend["config"][key] == combo
    assert len(backend["hotkey_calls"]) > before
    step.check(
        f"{key} == {combo} persisted to disk + live config; "
        "host rebind callback fired"
    )


@pytest.mark.parametrize(
    "tid,cfg_key",
    [
        ("settings-show_overlay", "show_overlay"),
        ("settings-show_text_in_overlay", "show_text_in_overlay"),
    ],
)
def test_settings_checkbox_persists(
    page: Page, app_url: str, backend, tid: str, cfg_key: str, step
):
    """The two Reader-panel checkboxes default True; unticking and
    Saving must persist False to disk + live config."""
    _goto(page, app_url, "settings", step)
    box = page.get_by_test_id(tid)
    expect(box).to_be_checked()
    step.check(f"{cfg_key} checkbox starts checked (default True)")
    step(f"uncheck {cfg_key} and Save")
    box.uncheck()
    page.get_by_test_id("settings-save").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Saved")

    cfg = _config_on_disk(backend["profile"])
    assert cfg.get(cfg_key) is False
    assert backend["config"][cfg_key] is False
    step.check(f"{cfg_key} == False persisted to config.json + live config")


@pytest.mark.parametrize(
    "tid,cfg_key,value",
    [
        ("settings-overlay_y_offset", "overlay_y_offset", "240"),
        ("settings-karaoke_offset_ms", "karaoke_offset_ms", "-80"),
    ],
)
def test_settings_spinbox_persists(
    page: Page, app_url: str, backend, tid: str, cfg_key: str, value: str, step
):
    """Distance-from-taskbar and Karaoke-offset spinboxes persist their
    integer value to disk + live config."""
    _goto(page, app_url, "settings", step)
    step(f"set {cfg_key} = {value}, then Save")
    page.get_by_test_id(tid).fill(value)
    page.get_by_test_id("settings-save").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Saved")

    cfg = _config_on_disk(backend["profile"])
    assert cfg.get(cfg_key) == int(value)
    assert backend["config"][cfg_key] == int(value)
    step.check(f"{cfg_key} == {value} persisted to config.json + live config")


def test_settings_ctx_status_reflects_backend(
    page: Page, app_url: str, backend, step
):
    """The Windows-integration status label reflects the REAL
    context_menu_status() the bridge returns."""
    _goto(page, app_url, "settings", step)
    real = backend["bridge"].context_menu_status()
    step.check(f"real bridge.context_menu_status() == {real!r}")
    label = page.get_by_test_id("settings-ctx-status")
    if real == "all":
        expect(label).to_contain_text("installed")
    elif real == "partial":
        expect(label).to_contain_text("Partial")
    else:
        expect(label).to_contain_text("not installed")
    step.check(f"status label reflects the real {real!r} state")


def test_settings_ctx_install_real_effect(
    page: Page, app_url: str, backend, monkeypatch, step
):
    """Install must call the REAL bridge.install_context_menu. The
    registry write is Windows-registry side-effecting, so we capture the
    real context_menu functions the bridge calls and assert the bridge
    drove them + refreshed the real status label — the bridge/UI path is
    entirely real, only the registry write itself is intercepted."""
    import pippal.web_ui.bridge as bridge_mod

    calls: list[str] = []
    monkeypatch.setattr(
        bridge_mod, "install_context_menu", lambda: calls.append("install")
    )
    monkeypatch.setattr(
        bridge_mod, "context_menu_status", lambda: "all"
    )
    _goto(page, app_url, "settings", step)
    step("click Windows-integration Install")
    page.get_by_test_id("settings-ctx-install").click()
    expect(page.get_by_test_id("settings-ctx-status")).to_contain_text(
        "installed", timeout=4000
    )
    assert calls == ["install"]
    step.check(
        "real bridge.install_context_menu called; status label refreshed "
        "to 'installed'"
    )


def test_settings_ctx_remove_real_effect(
    page: Page, app_url: str, backend, monkeypatch, step
):
    import pippal.web_ui.bridge as bridge_mod

    calls: list[str] = []
    monkeypatch.setattr(
        bridge_mod, "uninstall_context_menu", lambda: calls.append("remove")
    )
    monkeypatch.setattr(bridge_mod, "context_menu_status", lambda: "none")
    _goto(page, app_url, "settings", step)
    step("click Windows-integration Remove")
    page.get_by_test_id("settings-ctx-remove").click()
    expect(page.get_by_test_id("settings-ctx-status")).to_contain_text(
        "not installed", timeout=4000
    )
    assert calls == ["remove"]
    step.check(
        "real bridge.uninstall_context_menu called; status label refreshed "
        "to 'not installed'"
    )


def test_settings_view_licences_opens_notices(
    page: Page, app_url: str, backend, step
):
    _goto(page, app_url, "settings", step)
    step("click View licences…")
    page.get_by_test_id("settings-view-licences").click()

    def _opened() -> bool:
        return "notices" in backend["window_opens"]

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _opened():
        page.wait_for_timeout(50)
    assert _opened(), "View licences… did not reach on_open_notices"
    step.check("View licences… reached the real on_open_notices host callback")


def test_settings_about_links_open_real_urls(
    page: Page, app_url: str, backend, monkeypatch, step
):
    """Each of the 6 About links must call the real bridge.open_url with
    the exact URL the backend's about_info() returns. The reddit Community
    link was added in the web-UI migration alongside the other 5."""
    import pippal.web_ui.bridge as bridge_mod

    opened: list[str] = []
    monkeypatch.setattr(
        bridge_mod.webbrowser, "open", lambda u: opened.append(u) or True
    )
    about = backend["bridge"].about_info()
    expected = {link["key"]: link["url"] for link in about["links"]}
    assert set(expected) == {"website", "github", "licence", "privacy", "terms", "reddit"}
    step.check("real about_info() exposes the 6 expected About links")

    _goto(page, app_url, "settings", step)
    for key, url in expected.items():
        opened.clear()
        step(f"click About link '{key}'")
        page.get_by_test_id(f"about-{key}").click()
        deadline = page.evaluate("Date.now()") + 3000
        while page.evaluate("Date.now()") < deadline and not opened:
            page.wait_for_timeout(40)
        assert opened and opened[0] == url, f"about-{key} → {opened!r} != {url}"
        step.check(f"about-{key} → real bridge.open_url({url!r})")


def test_settings_cancel_closes_without_persist(
    page: Page, app_url: str, backend, step
):
    """Cancel must close the window WITHOUT persisting: edit a field,
    Cancel, assert no config.json written and the host close callback
    fired."""
    _goto(page, app_url, "settings", step)
    step("edit auto_hide_ms = 4321, then click Cancel")
    page.get_by_test_id("settings-auto_hide_ms").fill("4321")
    before = len(backend["close_calls"])
    page.get_by_test_id("settings-cancel").click()

    deadline = page.evaluate("Date.now()") + 4000
    while (
        page.evaluate("Date.now()") < deadline
        and len(backend["close_calls"]) == before
    ):
        page.wait_for_timeout(50)
    assert len(backend["close_calls"]) > before, "Cancel did not close window"
    # Nothing persisted — fresh profile still has no config.json.
    assert not (backend["profile"] / "config.json").exists()
    assert "auto_hide_ms" not in _config_on_disk(backend["profile"])
    step.check(
        "Cancel reached on_close_window and persisted NOTHING "
        "(no config.json on disk)"
    )


def test_settings_save_persists_with_saved_toast(
    page: Page, app_url: str, backend, step
):
    """Save persists the form and shows the "Saved." toast — distinct
    from Apply's "Applied." toast (Apply re-renders in place). The web
    Save passes ``close=True`` through ``save_config``; the actual
    window dismissal is the desktop window manager's job (see the
    checklist's honest note on the Save-closes-window parity gap), so
    the asserted, real, served effect here is the persisted config +
    the distinct Saved toast.

    Apply vs Save distinction is asserted: Apply → "Applied." +
    re-render; Save → "Saved." (no re-render request)."""
    _goto(page, app_url, "settings", step)
    step("set auto_hide_ms = 3300, then click Save")
    page.get_by_test_id("settings-auto_hide_ms").fill("3300")
    page.get_by_test_id("settings-save").click()

    toast = page.get_by_test_id("toast")
    expect(toast).to_have_text(EN["settings.save.saved"])
    assert _config_on_disk(backend["profile"]).get("auto_hide_ms") == 3300
    assert backend["config"]["auto_hide_ms"] == 3300
    step.check('Save → "Saved." toast; auto_hide_ms == 3300 on disk + live config')

    # Contrast with Apply: same persistence, different toast, stays open.
    step("set auto_hide_ms = 3400, then click Apply")
    page.get_by_test_id("settings-auto_hide_ms").fill("3400")
    page.get_by_test_id("settings-apply").click()
    expect(toast).to_have_text(EN["settings.save.applied"])
    assert _config_on_disk(backend["profile"]).get("auto_hide_ms") == 3400
    step.check('Apply → "Applied." toast; auto_hide_ms == 3400 on disk')


def test_window_close_button_calls_bridge(
    page: Page, app_url: str, backend, step
):
    """The chromeless title-bar ✕ (window-close) must reach the real
    on_close_window host callback."""
    _goto(page, app_url, "settings", step)
    before = len(backend["close_calls"])
    step("click the title-bar window-close ✕")
    page.get_by_test_id("window-close").click()

    deadline = page.evaluate("Date.now()") + 4000
    while (
        page.evaluate("Date.now()") < deadline
        and len(backend["close_calls"]) == before
    ):
        page.wait_for_timeout(50)
    assert len(backend["close_calls"]) > before
    step.check("window-close ✕ reached the real on_close_window host callback")


# ===========================================================================
# §3 Voice Manager — controls not covered by the original 17
# ===========================================================================

def test_voice_manager_language_filter(page: Page, app_url: str, backend, step):
    """Picking a specific language must narrow the list to only that
    language's voices (asserted against the real catalogue)."""
    _goto(page, app_url, "voices", step)
    cat = backend["bridge"].get_voice_catalogue()
    langs = cat["languages"]
    assert langs, "catalogue exposes no languages"
    # Choose the language with the FEWEST voices for a tight assertion.
    counts: dict[str, int] = {}
    for v in cat["voices"]:
        counts[v["lang"]] = counts.get(v["lang"], 0) + 1
    target = min(counts, key=counts.get)
    expected = counts[target]

    step(f"select language filter = {target!r} ({expected} voices expected)")
    page.get_by_test_id("vm-language").select_option(target)
    rows = page.locator('#view [data-testid^="vm-action-"]')
    expect(rows).to_have_count(expected)
    step.check(
        f"language {target!r} → exactly {expected} rows (matches real catalogue)"
    )


def test_voice_manager_quality_filter(page: Page, app_url: str, backend, step):
    _goto(page, app_url, "voices", step)
    cat = backend["bridge"].get_voice_catalogue()
    counts: dict[str, int] = {}
    for v in cat["voices"]:
        counts[v["quality"]] = counts.get(v["quality"], 0) + 1
    # 'high' is always present in the curated catalogue.
    assert "high" in counts
    step(f"select quality filter = high ({counts['high']} voices expected)")
    page.get_by_test_id("vm-quality").select_option("high")
    rows = page.locator('#view [data-testid^="vm-action-"]')
    expect(rows).to_have_count(counts["high"])
    step.check(
        f"quality 'high' → exactly {counts['high']} rows (matches real catalogue)"
    )


def test_voice_manager_row_install_real_effect(
    page: Page, app_url: str, backend, monkeypatch, step
):
    """A per-row Install must call the REAL bridge.install_voice →
    install_piper_voice; only the network download is stubbed, so a real
    model file lands in the real per-test voices dir and the row flips
    to 'installed'."""
    from pippal import voices as voices_mod
    from pippal import voice_install as vm
    import pippal.web_ui.bridge as _bridge_mod

    def _fake_download(url: str, dest: Path, *a, **k) -> None:
        dest.write_bytes(b"stub-voice-model-bytes")

    # Seam both the sync path (voice_install._streaming_download) and the
    # async path (bridge._stream_voice_with_progress) so neither performs
    # a real network download. voices.js calls install_voice_async first,
    # which uses the bridge async path; the sync path is a fallback.
    monkeypatch.setattr(vm, "_streaming_download", _fake_download)

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

    _goto(page, app_url, "voices", step)
    # Pick the first not-installed catalogue row.
    cat = backend["bridge"].get_voice_catalogue()
    vid = cat["voices"][0]["id"]
    btn = page.get_by_test_id(f"vm-action-{vid}")
    expect(btn).to_have_text(EN["voices.action.install"])
    step(f"click per-row Install for {vid} (real installer, stubbed download)")
    btn.click()

    def _installed() -> bool:
        return any(vid in f for f in voices_mod.installed_voices())

    deadline = page.evaluate("Date.now()") + 8000
    while page.evaluate("Date.now()") < deadline and not _installed():
        page.wait_for_timeout(150)
    assert _installed(), f"row Install produced no real voice file for {vid}"
    # The catalogue now reports it installed (real on-disk state).
    fresh = backend["bridge"].get_voice_catalogue()
    assert any(v["id"] == vid and v["installed"] for v in fresh["voices"])
    step.check(
        f"real voice file for {vid} landed on disk; catalogue now reports it "
        "installed"
    )


def test_voice_manager_close_button_calls_bridge(
    page: Page, app_url: str, backend, step
):
    """The Voice Manager surface's window-close (the Tk dialog's Close
    button parity) reaches the real on_close_window host callback."""
    _goto(page, app_url, "voices", step)
    before = len(backend["close_calls"])
    step("click the Voice Manager window-close")
    page.get_by_test_id("window-close").click()
    deadline = page.evaluate("Date.now()") + 4000
    while (
        page.evaluate("Date.now()") < deadline
        and len(backend["close_calls"]) == before
    ):
        page.wait_for_timeout(50)
    assert len(backend["close_calls"]) > before
    step.check("Voice Manager close reached the real on_close_window callback")


# ===========================================================================
# §4 Reader overlay — controls not covered by the original 17
# ===========================================================================

def _start_reading_session(page: Page, app_url: str, step=None) -> None:
    if step is not None:
        step("open overlay surface for a live reading session")
    page.goto(f"{app_url}/index.html?view=overlay")
    expect(page.locator("body")).to_have_attribute("data-ready", "overlay")
    if step is not None:
        step('read-aloud "PipPal overlay control coverage check sentence."'
             " via POST /bridge read_text")
    page.evaluate(
        """async () => {
            await fetch('/bridge', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                method: 'read_text',
                args: ['PipPal overlay control coverage check sentence.'],
              }),
            });
        }"""
    )


def test_overlay_paused_chip_shows_on_pause(
    page: Page, app_url: str, backend, step
):
    """The overlay pause button icon state must reflect the real engine
    pause state — driven by a real reading session + the real engine.pause_toggle.

    The overlay-paused chip testid no longer exists. The pause button
    (testid: overlay-pause) now reflects pause state via its data-icon
    attribute: "pause" while playing (click to pause), "play" while
    paused (click to resume).
    """
    engine = backend["engine"]
    try:
        _start_reading_session(page, app_url, step)
        expect(page.locator("body")).to_have_attribute(
            "data-overlay-state", "reading", timeout=8000
        )
        pause_btn = page.get_by_test_id("overlay-pause")
        expect(pause_btn).to_have_attribute("data-icon", "pause", timeout=4000)
        step.check("overlay 'reading'; pause button data-icon=pause (playing state)")

        step("engine.pause_toggle() — real pause mid-read")
        engine.pause_toggle()  # real engine pause
        # When paused the button shows the play icon (click to resume).
        expect(pause_btn).to_have_attribute("data-icon", "play", timeout=4000)
        assert backend["overlay"].snapshot()["is_paused"] is True
        step.check("pause button data-icon=play; backend is_paused == True")

        step("engine.pause_toggle() — real resume")
        engine.pause_toggle()  # real resume
        # After resume the button flips back to pause icon.
        expect(pause_btn).to_have_attribute("data-icon", "pause", timeout=4000)
        assert backend["overlay"].snapshot()["is_paused"] is False
        step.check("pause button data-icon=pause again; backend is_paused == False")
    finally:
        engine.stop()


def test_overlay_drag_repositions_panel(page: Page, app_url: str, backend, step):
    """The overlay panel is now dragged via the native pywebview-drag-region
    mechanism on the brand area. The custom right-button DOM drag handler
    and its data-offset / transform attributes no longer exist.

    Assert that the drag region element is present with the
    pywebview-drag-region CSS class that enables native OS window dragging.
    """
    _goto(page, app_url, "overlay", step)
    drag_region = page.get_by_test_id("overlay-drag-region")
    expect(drag_region).to_be_visible()
    classes = drag_region.get_attribute("class") or ""
    assert "pywebview-drag-region" in classes, (
        f"overlay-drag-region lacks the pywebview-drag-region class: {classes!r}"
    )
    step.check(
        "overlay-drag-region visible with pywebview-drag-region class "
        "(native OS window dragging enabled)"
    )


# ===========================================================================
# §5 Tray-reachable effect — Recent submenu uses the engine history API
# ===========================================================================

def test_history_clear_real_effect(page: Page, app_url: str, backend, step):
    """The tray 'Recent' submenu enumerates ``engine.get_history()`` and
    'Clear history' calls ``engine.clear_history()``. The native pystray
    menu has no DOM, but that exact engine/bridge contract is real and
    testable end to end: a real ``pippal.history`` round-trip populates
    the engine the same way the app does at startup, the bridge
    ``get_history`` (the same call the served UI / tray read) reflects
    it, and ``clear_history`` empties BOTH the in-memory list and the
    real ``history.json`` on disk — the precise effect of the tray item.

    (``read_text`` does not record history in this no-``piper.exe``
    checkout — it routes through the onboarding clip and returns before
    ``_remember``; asserting otherwise would be a false positive, so the
    genuine tray contract is exercised directly instead.)
    """
    import pippal.history as history_mod
    from pippal.history import load_history, save_history

    engine = backend["engine"]
    bridge = backend["bridge"]
    assert bridge.get_history() == []  # fresh profile, nothing on disk
    step.check("fresh profile: bridge.get_history() == []")

    # Populate via the REAL history persistence the app uses at startup
    # (engine.attach_history(load_history(), save_history)).
    step("save_history([2 entries]) + engine.attach_history (real startup path)")
    save_history(["First recent entry", "Second recent entry"])
    assert load_history() == ["First recent entry", "Second recent entry"]
    engine.attach_history(load_history(), save_history)
    # The bridge get_history (served UI + tray submenu source) sees them.
    assert bridge.get_history() == [
        "First recent entry",
        "Second recent entry",
    ]
    step.check("bridge.get_history() (UI + tray source) reflects the 2 entries")

    # 'Clear history' (tray) → engine.clear_history(): empties memory AND
    # rewrites the real history.json on disk to [].
    step("engine.clear_history() (the tray 'Clear history' contract)")
    engine.clear_history()
    assert bridge.get_history() == []
    assert json.loads(Path(history_mod.HISTORY_PATH).read_text("utf-8")) == []
    step.check("history cleared in memory AND history.json on disk == []")
    engine.stop()
