"""Tier-1 served Playwright smoke for the T-101 core i18n engine.

Covers the JS-side runtime (``webui/js/i18n.js``) + the ``index.html``
boot wiring only (engine, NOT string extraction — that is T-104):

  * en default boot: ``document.documentElement.lang`` resolves, the
    anti-FOUC cloak is removed, ``window.t`` is callable, and NO
    ``⟦key⟧`` marker appears in the rendered DOM (issue AC).
  * the static chrome (Close / Reset / Cancel / Apply / Save / No / Yes)
    is filled from the shipped ``i18n/en.json`` catalog — asserted
    against that catalog as an INDEPENDENT oracle, never a hardcoded
    English literal, and byte-identical to the pre-i18n HTML.
  * ``?lang=`` override is honoured for the served harness (supported ->
    used; unsupported -> en fallback).
  * host-injected ``window.__PIPPAL_LANG__`` / ``__PIPPAL_CAT__`` drive
    a synchronous translated boot with ``{name}`` interpolation.
  * the fallback chain active-lang -> en -> ``⟦key⟧`` marker.
  * ``Intl.PluralRules`` category selection for en / uk / zh-CN.

Oracle-first: assertions check the catalog / CLDR rules / boot state,
not the engine's own code shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

WEBUI = Path(__file__).resolve().parents[2] / "webui"
MARKER_OPEN = "⟦"  # ⟦  — the "missing translation" marker
MARKER_CLOSE = "⟧"  # ⟧


def _en_catalog() -> dict:
    """The shipped English catalog — the independent oracle for the
    static-chrome fills (tests assert element text == EN[key])."""
    return json.loads((WEBUI / "i18n" / "en.json").read_text("utf-8"))


def _wait_i18n_ready(page: Page) -> None:
    """Wait until i18n.js has applied the catalog + removed the cloak."""
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )


def _boot(page: Page, app_url: str, view: str = "settings") -> None:
    page.goto(f"{app_url}/index.html?view={view}")
    _wait_i18n_ready(page)


def _inject_host_catalog(
    page: Page, lang: str, cat: dict, cat_en: dict | None = None
) -> None:
    """Simulate the desktop host path: seed the pre-load globals BEFORE
    any page script runs (exactly what pywebview injects at window
    creation)."""
    script = (
        f"window.__PIPPAL_LANG__ = {json.dumps(lang)};"
        f"window.__PIPPAL_CAT__ = {json.dumps(cat)};"
    )
    if cat_en is not None:
        script += f"window.__PIPPAL_CAT_EN__ = {json.dumps(cat_en)};"
    page.add_init_script(script)


# ---------------------------------------------------------------------------
# en default boot — the core issue AC
# ---------------------------------------------------------------------------


def test_i18n_boot_en_default_resolves_and_reveals(page: Page, app_url: str, step):
    _boot(page, app_url, "settings")

    lang = page.evaluate("document.documentElement.lang")
    assert lang == "en", f"resolved lang should be en, got {lang!r}"
    step.check(f"document.documentElement.lang == {lang!r}")

    cloaked = page.evaluate(
        "document.documentElement.classList.contains('i18n-cloak')"
    )
    assert cloaked is False, "i18n-cloak class must be removed after boot"
    step.check("anti-FOUC cloak removed (html has no .i18n-cloak)")

    assert page.evaluate("typeof window.t") == "function"
    step.check("window.t is callable")


def test_i18n_boot_no_marker_in_dom_on_en_default(page: Page, app_url: str, step):
    # Every core surface must render clean on the English default — no
    # ⟦key⟧ leakage anywhere.
    for view in ("settings", "voices", "onboarding", "overlay"):
        page.goto(f"{app_url}/index.html?view={view}")
        _wait_i18n_ready(page)
        expect(page.locator("body")).to_have_attribute(
            "data-ready", view, timeout=15000
        )
        content = page.content()
        assert MARKER_OPEN not in content, f"⟦ marker leaked on {view}"
        assert MARKER_CLOSE not in content, f"⟧ marker leaked on {view}"
        step.check(f"'{view}' surface: no ⟦key⟧ marker in the DOM")


def test_i18n_boot_static_chrome_filled_from_catalog(
    page: Page, app_url: str, step
):
    """The static chrome is filled from i18n/en.json (independent oracle)
    and stays byte-identical to the pre-i18n English HTML."""
    page.goto(f"{app_url}/index.html?view=settings")
    _wait_i18n_ready(page)
    en = _en_catalog()

    # textContent fills.
    expect(page.get_by_test_id("settings-reset")).to_have_text(en["footer.reset"])
    expect(page.get_by_test_id("settings-cancel")).to_have_text(en["footer.cancel"])
    expect(page.get_by_test_id("settings-apply")).to_have_text(en["footer.apply"])
    expect(page.get_by_test_id("settings-save")).to_have_text(en["footer.save"])
    expect(page.get_by_test_id("confirm-cancel")).to_have_text(en["confirm.no"])
    expect(page.get_by_test_id("confirm-ok")).to_have_text(en["confirm.yes"])
    step.check("footer + confirm buttons filled from en.json (byte-identical)")

    # Attribute fills: the close button keeps its ✕ glyph but its
    # title/aria-label come from the catalog.
    close = page.get_by_test_id("window-close")
    expect(close).to_have_attribute("title", en["chrome.close"])
    expect(close).to_have_attribute("aria-label", en["chrome.close"])
    glyph = close.inner_text().strip()
    assert glyph == "✕", f"close glyph must stay ✕, got {glyph!r}"
    step.check("close button: title/aria-label from catalog, ✕ glyph preserved")


# ---------------------------------------------------------------------------
# document.lang is set from the RESOLVED language (issue AC)
# ---------------------------------------------------------------------------


def test_i18n_boot_query_param_honoured_for_supported_lang(
    page: Page, app_url: str, step
):
    # ?lang=de is a supported language -> honoured as the resolved lang.
    # Only en.json ships in T-101, so the de catalog 404s and the chrome
    # falls back to en text — but document.lang still reflects the pick.
    page.goto(f"{app_url}/index.html?view=settings&lang=de")
    _wait_i18n_ready(page)

    lang = page.evaluate("document.documentElement.lang")
    assert lang == "de", f"?lang=de must be honoured, got {lang!r}"
    step.check("?lang=de honoured: document.documentElement.lang == 'de'")

    # en fallback keeps the chrome English (no marker) even without a de
    # catalog present.
    en = _en_catalog()
    assert page.evaluate("window.t('chrome.close')") == en["chrome.close"]
    assert MARKER_OPEN not in page.content()
    step.check("missing de catalog falls back to en chrome (no marker)")


def test_i18n_boot_unsupported_query_param_falls_back_to_en(
    page: Page, app_url: str, step
):
    page.goto(f"{app_url}/index.html?view=settings&lang=zz")
    _wait_i18n_ready(page)
    lang = page.evaluate("document.documentElement.lang")
    assert lang == "en", f"unsupported ?lang=zz must fall back to en, got {lang!r}"
    step.check("?lang=zz (unsupported) -> resolved lang 'en'")


# ---------------------------------------------------------------------------
# host-injected catalog: synchronous translated boot + interpolation
# ---------------------------------------------------------------------------


def test_i18n_boot_host_injected_catalog_translates_with_interpolation(
    page: Page, app_url: str, step
):
    cat = {
        "_meta": {"lang": "uk", "name": "Ukrainian", "fallback": "en"},
        "greet.hello": "Привіт, {name}!",
    }
    _inject_host_catalog(page, "uk", cat)
    _boot(page, app_url, "settings")

    assert page.evaluate("document.documentElement.lang") == "uk"
    step.check("host-injected __PIPPAL_LANG__ resolved: document.lang == 'uk'")

    result = page.evaluate("window.t('greet.hello', {name: 'Ada'})")
    assert result == "Привіт, Ada!", result
    step.check("t() used the injected catalog AND interpolated {name} -> 'Ada'")

    # A missing param must leave the literal placeholder (not throw).
    literal = page.evaluate("window.t('greet.hello')")
    assert literal == "Привіт, {name}!", literal
    step.check("missing param leaves the literal {name} placeholder")


def test_i18n_boot_fallback_chain_active_then_en_then_marker(
    page: Page, app_url: str, step
):
    active = {"only.in.active": "ACTIVE"}
    en_fallback = {"only.in.active": "EN-ACTIVE", "only.in.en": "EN-ONLY"}
    _inject_host_catalog(page, "de", active, cat_en=en_fallback)
    _boot(page, app_url, "settings")

    # active wins over en.
    assert page.evaluate("window.t('only.in.active')") == "ACTIVE"
    step.check("t() prefers the active catalog over en")
    # present only in en -> en fallback.
    assert page.evaluate("window.t('only.in.en')") == "EN-ONLY"
    step.check("missing-in-active key falls back to the en catalog")
    # present in neither -> ⟦key⟧ marker.
    assert page.evaluate("window.t('nowhere.key')") == "⟦nowhere.key⟧"
    step.check("key in neither catalog -> ⟦nowhere.key⟧ marker")


# ---------------------------------------------------------------------------
# CLDR plurals via Intl.PluralRules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lang,n,expected",
    [
        # en: one for exactly 1, other otherwise.
        ("en", 1, "one"),
        ("en", 0, "other"),
        ("en", 2, "other"),
        # uk (Slavic, 4 forms): 1->one, 2->few, 5->many.
        ("uk", 1, "one"),
        ("uk", 2, "few"),
        ("uk", 5, "many"),
        # zh-CN: no plural distinction — always other.
        ("zh-CN", 1, "other"),
        ("zh-CN", 5, "other"),
    ],
)
def test_i18n_boot_plural_category_selection(
    page: Page, app_url: str, step, lang: str, n: int, expected: str
):
    # A plural value stores one template per CLDR category; the template
    # is set to the category NAME so the test asserts the SELECTED
    # category directly (independent of the language's own wording).
    cat = {
        "items.count": {
            "_plural": "n",
            "one": "one",
            "few": "few",
            "many": "many",
            "other": "other",
        }
    }
    _inject_host_catalog(page, lang, cat)
    _boot(page, app_url, "settings")

    assert page.evaluate("window.t.diag().hasPluralRules") is True
    got = page.evaluate("window.t('items.count', {n: " + str(n) + "})")
    assert got == expected, (
        f"{lang} n={n}: expected CLDR category {expected!r}, got {got!r}"
    )
    step.check(f"{lang} n={n} -> CLDR category {got!r}")
