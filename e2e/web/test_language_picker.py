"""Tier-1 served e2e for T-103 — the Settings language picker.

Drives the REAL served frontend (``webui/`` + the real bridge server) with
stable ``data-testid`` selectors and asserts REAL backend effects: the
picker options come from the real ``get_config`` supported-language set,
selecting a language persists through the real ``save_config`` seam to
``config.json`` + the live config, and Auto clears the pin. No mocks, no
literal-English assertions on translatable chrome — native language labels
are endonyms (identical in every UI language) so asserting them is
language-agnostic. Every test runs against a freshly reset app (see
``conftest.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect


def _config_on_disk(profile: Path) -> dict:
    cfg = profile / "config.json"
    return json.loads(cfg.read_text("utf-8")) if cfg.exists() else {}


def _goto_settings(page: Page, app_url: str, step=None) -> None:
    if step is not None:
        step("open 'settings' surface")
    page.goto(f"{app_url}/index.html?view=settings")
    expect(page.locator("body")).to_have_attribute(
        "data-ready", "settings", timeout=15000
    )


def test_language_picker_renders_auto_plus_six_endonyms(
    page: Page, app_url: str, backend, step
):
    """The picker renders Auto + one option per supported catalog, each
    labelled in its OWN language, driven by the real get_config set."""
    supported = backend["bridge"].get_config()["supported_languages"]
    tags = [o["tag"] for o in supported]
    assert tags == ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]
    step.check(f"real get_config supported_languages == {tags}")

    _goto_settings(page, app_url, step)
    sel = page.get_by_test_id("settings-language")
    expect(sel).to_be_visible()
    options = sel.locator("option")
    # Auto + 6 languages == 7 options.
    expect(options).to_have_count(7)
    step.check("picker renders 7 options (Auto + 6 languages)")

    labels = options.all_inner_texts()
    assert labels[0].strip() == "Auto (system)"
    for endonym in ("English", "简体中文", "Deutsch", "Magyar",
                    "Українська", "Português (Brasil)"):
        assert endonym in labels, f"missing endonym {endonym!r} in {labels!r}"
    step.check("each language shown in its own language (endonym labels)")

    # Restart-required hint for the tray (design §5.5), keyed for i18n.
    hint = page.get_by_test_id("settings-language-hint")
    expect(hint).to_have_attribute("data-i18n", "settings.lang.tray_hint")
    expect(hint).to_contain_text("restart")
    step.check("tray restart hint present with data-i18n key")


def test_language_picker_defaults_to_auto(page: Page, app_url: str, step):
    """Fresh profile has no language pin → the picker sits on Auto ("")."""
    _goto_settings(page, app_url, step)
    expect(page.get_by_test_id("settings-language")).to_have_value("")
    step.check("fresh profile: picker value == '' (Auto)")


def test_selecting_language_persists_via_save_config(
    page: Page, app_url: str, backend, step
):
    """Selecting German persists ``language: "de"`` to config.json + the
    live config through the real save_config seam, and get_config then
    resolves the concrete tag."""
    _goto_settings(page, app_url, step)
    step("select German in the language picker")
    page.get_by_test_id("settings-language").select_option("de")
    expect(page.get_by_test_id("toast")).to_contain_text("Language")

    def _persisted() -> bool:
        return _config_on_disk(backend["profile"]).get("language") == "de"

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _persisted():
        page.wait_for_timeout(50)
    assert _persisted(), "language 'de' was not persisted to config.json"
    assert backend["config"]["language"] == "de"
    # The resolved view the JS renders in now reports the concrete tag.
    assert backend["bridge"].get_config()["language_resolved"] == "de"
    step.check("language 'de' persisted to disk + live config; resolved == 'de'")


def test_selecting_auto_clears_the_language_pin(
    page: Page, app_url: str, backend, step
):
    """After picking a language, selecting Auto clears the pin: the
    override leaves config.json and the effective language returns to ""
    (Auto), so resolution falls back to system/en."""
    _goto_settings(page, app_url, step)
    step("pick German, then switch back to Auto (system)")
    page.get_by_test_id("settings-language").select_option("de")
    expect(page.get_by_test_id("toast")).to_contain_text("Language")

    def _de() -> bool:
        return _config_on_disk(backend["profile"]).get("language") == "de"

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _de():
        page.wait_for_timeout(50)
    assert _de()

    page.get_by_test_id("settings-language").select_option("")

    def _auto() -> bool:
        return "language" not in _config_on_disk(backend["profile"])

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _auto():
        page.wait_for_timeout(50)
    assert _auto(), "Auto did not clear the language pin from config.json"
    assert backend["config"]["language"] == ""
    step.check("Auto cleared the pin: config.json has no language, live == ''")
