"""Tier-1 served Playwright oracle for T-107 — the web UI must boot in the
PERSISTED / resolved language (``config.language``), not ``navigator.language``.

These drive the REAL served frontend (``webui/`` + the real bridge server) and
the REAL ``get_config`` / ``save_config`` bridge path — the language reaches
the page by i18n.js consulting the bridge, NOT by a ``?lang=`` test override
(that override is exercised separately in ``test_i18n_boot.py``). German chrome
is asserted against the shipped ``de.json`` catalog as an INDEPENDENT oracle.

Cross-runtime agreement is asserted directly: because the backend runs
IN-PROCESS with the browser, ``pippal.i18n.get_language()`` is the live Python
active language, and it must equal ``document.documentElement.lang`` after a
Settings change.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect

WEBUI = Path(__file__).resolve().parents[2] / "webui"
MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"


def _de_catalog() -> dict:
    return json.loads((WEBUI / "i18n" / "de.json").read_text("utf-8"))


def _wait_ready(page: Page) -> None:
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )


# ---------------------------------------------------------------------------
# AC1 — config.language="de" (en OS) boots German on every surface, no override
# ---------------------------------------------------------------------------


def test_boot_de_from_config_via_bridge_not_lang_override(
    page: Page, app_url: str, backend, step
):
    # Persist the German pick into the REAL backend config (the bridge reads
    # self.config live). The page URL carries NO ?lang= — the language must
    # arrive via i18n.js consulting get_config over /bridge.
    backend["config"]["language"] = "de"
    step("set backend config.language='de' (no ?lang= on the URL)")

    page.goto(f"{app_url}/index.html?view=settings")
    _wait_ready(page)

    lang = page.evaluate("document.documentElement.lang")
    assert lang == "de", f"boot lang should be de via get_config, got {lang!r}"
    step.check("document.documentElement.lang == 'de' (from config, not ?lang)")

    de = _de_catalog()
    assert page.evaluate("window.t('chrome.close')") == de["chrome.close"]
    step.check("chrome renders the German de.json value (no en fallback)")

    content = page.content()
    assert MARKER_OPEN not in content and MARKER_CLOSE not in content
    step.check("no ⟦key⟧ marker leaked in the German boot")


def test_boot_de_applies_to_every_surface(
    page: Page, app_url: str, backend, step
):
    backend["config"]["language"] = "de"
    for view in ("settings", "voices", "onboarding", "overlay"):
        page.goto(f"{app_url}/index.html?view={view}")
        _wait_ready(page)
        expect(page.locator("body")).to_have_attribute(
            "data-ready", view, timeout=15000
        )
        lang = page.evaluate("document.documentElement.lang")
        assert lang == "de", f"{view}: expected de, got {lang!r}"
        assert MARKER_OPEN not in page.content(), f"⟦ marker on {view}"
        step.check(f"'{view}' surface boots German (document.lang == 'de')")


# ---------------------------------------------------------------------------
# AC2 — Auto ("") preserves the existing served behaviour (navigator -> en)
# ---------------------------------------------------------------------------


def test_boot_auto_preserves_navigator_fallback(
    page: Page, app_url: str, backend, step
):
    # Fresh profile: config.language == "" (Auto). The bridge returns no
    # explicit pick, so resolution falls through to navigator.language (the
    # Playwright default en-US) -> en. Existing served behaviour preserved.
    assert backend["config"].get("language", "") == ""
    page.goto(f"{app_url}/index.html?view=settings")
    _wait_ready(page)
    lang = page.evaluate("document.documentElement.lang")
    assert lang == "en", f"Auto should resolve en here, got {lang!r}"
    step.check("Auto ('') boots en (navigator fallback preserved)")


# ---------------------------------------------------------------------------
# AC3 + AC4 — Settings change + reload applies, and both runtimes agree
# ---------------------------------------------------------------------------


def test_language_change_then_reload_applies_and_runtimes_agree(
    page: Page, app_url: str, backend, step
):
    from pippal import i18n

    # Boot on Auto/en first.
    page.goto(f"{app_url}/index.html?view=settings")
    expect(page.locator("body")).to_have_attribute(
        "data-ready", "settings", timeout=15000
    )
    assert page.evaluate("document.documentElement.lang") == "en"
    step.check("initial boot: en")

    # Pick German through the REAL picker -> real save_config -> set_language.
    step("select German in the Settings language picker")
    page.get_by_test_id("settings-language").select_option("de")
    expect(page.get_by_test_id("toast")).to_contain_text("Language")

    # The Python runtime aligned immediately (cross-runtime agreement source).
    def _py_de() -> bool:
        return i18n.get_language() == "de"

    deadline = page.evaluate("Date.now()") + 4000
    while page.evaluate("Date.now()") < deadline and not _py_de():
        page.wait_for_timeout(50)
    assert _py_de(), "Python get_language() did not become 'de' after save_config"
    step.check("Python get_language() == 'de' after the picker save")

    # Reload (no ?lang=) — the persisted pick now drives the boot via the
    # bridge consult, so the surface re-renders in German.
    page.reload()
    _wait_ready(page)
    dom_lang = page.evaluate("document.documentElement.lang")
    assert dom_lang == "de", f"reload should boot de, got {dom_lang!r}"
    step.check("reload applies the new language: document.lang == 'de'")

    # AC3: cross-runtime agreement — Python active lang == DOM lang.
    assert i18n.get_language() == dom_lang == "de"
    step.check("cross-runtime agreement: Python get_language() == DOM lang == 'de'")

    de = _de_catalog()
    assert page.evaluate("window.t('chrome.close')") == de["chrome.close"]
    assert MARKER_OPEN not in page.content()
    step.check("reloaded chrome is German with no ⟦key⟧ marker")
