"""Tier-1 served smoke for the T-105 non-English core catalogs (issue #126).

Boots the settings surface under ``?lang=de`` and ``?lang=hu`` and proves the
translated catalogs actually render, oracle-first against the shipped catalog
files:

  1. ``document.documentElement.lang`` reflects the picked language.
  2. NO ``⟦key⟧`` fallback marker leaks into the DOM (every key a renderer
     touches is present in the language catalog — the completeness guarantee
     visible on a real surface).
  3. The language-card title renders the TRANSLATED value (== ``<lang>.json``
     ``settings.lang.title``), not the English literal — so the catalog is
     genuinely wired through ``t()``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

WEBUI = Path(__file__).resolve().parents[2] / "webui"
MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"


def _catalog(lang: str) -> dict:
    return json.loads((WEBUI / "i18n" / f"{lang}.json").read_text("utf-8"))


def _boot(page: Page, app_url: str, view: str, lang: str) -> None:
    page.goto(f"{app_url}/index.html?view={view}&lang={lang}")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )
    expect(page.locator("body")).to_have_attribute("data-ready", view, timeout=15000)


@pytest.mark.parametrize("lang", ["de", "hu"])
def test_settings_boots_translated_no_marker(page: Page, app_url: str, step, lang: str):
    cat = _catalog(lang)
    _boot(page, app_url, "settings", lang)

    assert page.evaluate("document.documentElement.lang") == lang
    step.check(f"?lang={lang}: document.documentElement.lang == {lang!r}")

    content = page.content()
    assert MARKER_OPEN not in content, f"⟦ marker leaked on settings@{lang}"
    assert MARKER_CLOSE not in content, f"⟧ marker leaked on settings@{lang}"
    step.check(f"settings@{lang}: no ⟦key⟧ marker in the DOM")

    # The language-card title is a .card-title whose text is the TRANSLATED
    # settings.lang.title — asserted against the catalog oracle, not a literal.
    title = cat["settings.lang.title"]
    expect(page.locator(".card-title", has_text=title).first).to_be_visible()
    assert title != "Language", "translated title must differ from the en literal"
    step.check(f"settings@{lang}: language card title == {title!r} (from catalog)")
