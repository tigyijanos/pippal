"""Tier-1 served Playwright per-language BOOT SMOKE for T-304 (issue #339).

For all six shipped languages × every core surface, boot the REAL served
frontend via ``?lang=<tag>`` and assert the three boot invariants the issue
AC names:

  1. ``document.documentElement.lang`` equals the seeded language tag;
  2. NO ``⟦key⟧`` fallback marker leaks anywhere in the rendered DOM
     (the surface rendered every key it asked for, in every language);
  3. one known translated string per surface renders the value taken FROM
     the shipped catalog — a language-INDEPENDENT oracle: the expected text
     is read from ``webui/i18n/<lang>.json`` (never a hardcoded literal),
     and the runtime ``window.t`` output is asserted equal to it. For the
     surfaces whose anchor is a persistent visible heading, the catalog
     value is additionally asserted present in the rendered ``innerText``,
     proving the surface actually painted a translated string.

This complements the existing single-language boot suites (``test_i18n_boot
.py`` = en + ?lang override shape; ``test_i18n_boot_language.py`` = the
config-driven German boot) by sweeping the FULL language × surface matrix —
the piece those files intentionally leave to this parametrized smoke.

Oracle-first: the per-language expectations come from the shipped JSON
catalogs, so a wrong translation, an en-fallback leak, or a missing key all
fail here without the test ever mirroring the app's own strings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page

WEBUI = Path(__file__).resolve().parents[2] / "webui"
MARKER_OPEN = "⟦"  # ⟦  — the "missing translation" marker
MARKER_CLOSE = "⟧"  # ⟧

# The six shipped languages, canonical picker order (issue "Languages").
LANGS = ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]

# Per surface: the sampled catalog keys whose rendered value is asserted, and
# whether the anchor is a persistent visible heading we can also require in the
# painted innerText. settings/voices/notices show a stable heading regardless
# of backend state; onboarding's copy depends on the live readiness state and
# the overlay's body is engine-state-driven, so those two are asserted through
# the runtime ``window.t`` against the catalog only (the no-marker sweep still
# proves their DOM rendered cleanly).
SURFACES: dict[str, dict] = {
    "settings": {
        "anchors": ["settings.about.title", "settings.speech.title"],
        "dom": True,
    },
    "voices": {
        "anchors": ["voices.filter.search_label", "voices.filter.lang_label"],
        "dom": True,
    },
    "notices": {
        "anchors": ["notices.window_title"],
        "dom": True,
    },
    "onboarding": {
        "anchors": ["onboarding.title.missing_piper", "onboarding.subtitle.missing_piper"],
        "dom": False,
    },
    "overlay": {
        "anchors": ["overlay.loading.breathe"],
        "dom": False,
    },
}


def _catalog(lang: str) -> dict:
    return json.loads((WEBUI / "i18n" / f"{lang}.json").read_text("utf-8"))


def _expected(lang: str, key: str) -> str:
    """Independent oracle: the catalog value for ``key`` in ``lang`` with the
    real fallback chain (lang -> en). All sampled anchors ship in every
    catalog, so this is the translated value; the fallback keeps the oracle
    honest if a future anchor were en-only."""
    value = _catalog(lang).get(key)
    if value is None:
        value = _catalog("en").get(key)
    assert isinstance(value, str), f"anchor {key!r} missing from en catalog"
    return value


def _wait_ready(page: Page, surface: str) -> None:
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )
    page.wait_for_function(
        "(s) => document.body.getAttribute('data-ready') === s",
        arg=surface,
        timeout=15000,
    )


_MATRIX = [(surface, lang) for surface in SURFACES for lang in LANGS]


@pytest.mark.parametrize(
    ("surface", "lang"),
    _MATRIX,
    ids=[f"{s}-{lang}" for s, lang in _MATRIX],
)
def test_surface_boots_in_language(
    page: Page, app_url: str, backend, step, surface: str, lang: str
):
    spec = SURFACES[surface]
    page.goto(f"{app_url}/index.html?view={surface}&lang={lang}")
    _wait_ready(page, surface)
    step(f"{surface!r} booted with ?lang={lang}")

    # 1. The resolved boot language is the seeded tag.
    dom_lang = page.evaluate("document.documentElement.lang")
    assert dom_lang == lang, f"{surface}/{lang}: document.lang == {dom_lang!r}"
    step.check(f"document.documentElement.lang == {lang!r}")

    # 2. No ⟦key⟧ fallback marker leaked anywhere on the surface.
    content = page.content()
    assert MARKER_OPEN not in content, f"⟦ marker leaked on {surface}/{lang}"
    assert MARKER_CLOSE not in content, f"⟧ marker leaked on {surface}/{lang}"
    step.check("no ⟦key⟧ marker in the rendered DOM")

    # 3. Each sampled key renders the catalog value (independent oracle).
    # textContent (not innerText) so a CSS ``text-transform: uppercase`` on a
    # card title cannot mask the raw catalog value we are matching against.
    body_text = page.evaluate("document.body.textContent") if spec["dom"] else ""
    for key in spec["anchors"]:
        expected = _expected(lang, key)
        got = page.evaluate("(k) => window.t(k)", key)
        assert got == expected, (
            f"{surface}/{lang}: window.t({key!r}) == {got!r}, "
            f"catalog expects {expected!r}"
        )
        if spec["dom"]:
            assert expected in body_text, (
                f"{surface}/{lang}: catalog value for {key!r} ({expected!r}) "
                f"not painted in the surface innerText"
            )
    step.check(
        f"{len(spec['anchors'])} sampled key(s) render the {lang!r} catalog value"
        + (" (verified in painted innerText)" if spec["dom"] else "")
    )
