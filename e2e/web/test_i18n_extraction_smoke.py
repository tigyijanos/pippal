"""Tier-1 served smoke for the T-104 core string EXTRACTION (issue #125).

Distinct from ``test_i18n_boot.py`` (which covers only the T-101 engine +
static chrome): this file boots each *extracted* core surface on the English
default and proves two things, oracle-first against ``webui/i18n/en.json``:

  1. No ``⟦key⟧`` fallback marker leaks into any surface's DOM — every key a
     renderer calls really exists in the shipped catalog (issue AC).
  2. A sample of freshly-extracted DYNAMIC strings (rendered by JS through
     ``window.t()``, not the static-chrome ``data-i18n`` path) equals its
     catalog value byte-for-byte — so the extraction is genuinely sourced
     from the catalog, and the English rendering is unchanged.

These are NEW assertions (no pre-existing test is modified); the byte-identical
guarantee for the ~162 legacy literal assertions is proven by the unchanged
pre-i18n suite passing as-is.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect

WEBUI = Path(__file__).resolve().parents[2] / "webui"
MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"


def _en() -> dict:
    return json.loads((WEBUI / "i18n" / "en.json").read_text("utf-8"))


def _boot(page: Page, app_url: str, view: str) -> None:
    page.goto(f"{app_url}/index.html?view={view}")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )
    expect(page.locator("body")).to_have_attribute("data-ready", view, timeout=15000)


def _assert_no_marker(page: Page, view: str) -> None:
    content = page.content()
    assert MARKER_OPEN not in content, f"⟦ marker leaked on {view}"
    assert MARKER_CLOSE not in content, f"⟧ marker leaked on {view}"


def test_extraction_no_marker_all_surfaces(page: Page, app_url: str, step):
    for view in ("settings", "voices", "onboarding", "overlay", "notices"):
        _boot(page, app_url, view)
        _assert_no_marker(page, view)
        step.check(f"'{view}' surface: extracted, no ⟦key⟧ marker in the DOM")


def test_settings_dynamic_strings_from_catalog(page: Page, app_url: str, step):
    en = _en()
    _boot(page, app_url, "settings")
    # Dynamic (window.t) strings, asserted against the catalog oracle.
    expect(page.get_by_test_id("promo-get-pro")).to_have_text(en["promo.get_pro"])
    expect(page.get_by_test_id("settings-manage-voices")).to_have_text(
        en["settings.voice.install_voices"]
    )
    expect(page.get_by_test_id("settings-diag-open")).to_have_text(
        en["settings.diag.open"]
    )
    expect(page.get_by_test_id("settings-view-licences")).to_have_text(
        en["settings.notices.view"]
    )
    step.check("settings dynamic strings render byte-identical to en.json")


def test_voices_dynamic_strings_from_catalog(page: Page, app_url: str, step):
    en = _en()
    _boot(page, app_url, "voices")
    expect(page.locator("#brand-name")).to_have_text(en["voices.window_title"])
    # A voice row Install button + empty-filter message both come via t().
    page.get_by_test_id("vm-status").select_option("Installed")
    expect(page.get_by_test_id("vm-empty")).to_have_text(en["voices.empty"])
    step.check("voice-manager dynamic strings render byte-identical to en.json")


def test_onboarding_dynamic_strings_from_catalog(page: Page, app_url: str, step):
    en = _en()
    # Fresh profile has no piper.exe -> missing_piper readiness branch.
    _boot(page, app_url, "onboarding")
    expect(page.get_by_test_id("onboarding-title")).to_have_text(
        en["onboarding.title.missing_piper"]
    )
    expect(page.get_by_test_id("onboarding-close")).to_have_text(
        en["onboarding.btn.close"]
    )
    step.check("onboarding dynamic strings render byte-identical to en.json")
