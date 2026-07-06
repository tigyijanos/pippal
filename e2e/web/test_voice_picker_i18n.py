"""Voice-picker i18n regression suite (issue #148).

The voice-model downloader previously rendered English language names
(``LOCALE_TO_NAME`` via the bridge) and RAW quality codes
(``high``/``medium``/``low``/``x_low``) regardless of the active UI language.
These tests pin the localised behaviour:

* the quality filter shows LOCALISED labels while option VALUES stay the raw
  Piper codes the filter logic + ``select_option()`` key off;
* the ``voices.row.meta`` line interpolates the localised quality label, not
  the raw code;
* the language filter renders localised display names (``Intl.DisplayNames``
  in the active language) for known locales.

Asserted against the shipped catalog for the active language (never a
hardcoded literal), so the suite stays language-agnostic per T-301. Driven in
German via ``?lang=`` so a regression back to raw codes / English names fails
here.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect

_WEBUI = Path(__file__).resolve().parents[2] / "webui"
DE = json.loads((_WEBUI / "i18n" / "de.json").read_text("utf-8"))


def _goto_voices_de(page: Page, app_url: str, step=None) -> None:
    if step is not None:
        step("open voices surface in German (?lang=de)")
    page.goto(f"{app_url}/index.html?view=voices&lang=de")
    # Generous readiness budget: the voices surface fetches the catalogue
    # async and this suite runs many Playwright tests in one loaded process.
    expect(page.locator("body")).to_have_attribute(
        "data-ready", "voices", timeout=30000
    )


def test_quality_filter_labels_localised(
    page: Page, app_url: str, backend, step
):
    """Quality filter option labels are localised; VALUES stay raw codes."""
    _goto_voices_de(page, app_url, step)
    for value, key in (
        ("high", "voices.filter.quality_high"),
        ("medium", "voices.filter.quality_medium"),
        ("low", "voices.filter.quality_low"),
        ("x_low", "voices.filter.quality_x_low"),
    ):
        opt = page.locator(
            f'[data-testid="vm-quality"] option[value="{value}"]'
        )
        expect(opt).to_have_text(DE[key])
    step.check(
        "quality options render localised labels while values stay raw codes"
    )


def test_row_meta_uses_localised_quality(
    page: Page, app_url: str, backend, step
):
    """The per-voice meta line interpolates the localised quality label,
    not the raw Piper code (so a German UI never shows 'high')."""
    _goto_voices_de(page, app_url, step)
    cat = backend["bridge"].get_voice_catalogue()
    # Find a real voice whose quality maps to a localised label and assert its
    # row meta shows the localised term rather than the raw code.
    a_high = next((v for v in cat["voices"] if v["quality"] == "high"), None)
    assert a_high is not None, "curated catalogue always ships a 'high' voice"
    meta = page.locator(f'[data-testid="vm-rows"]').get_by_text(
        DE["voices.filter.quality_high"], exact=False
    )
    expect(meta.first).to_be_visible()
    step.check("row meta shows localised quality label (not the raw code)")


def test_language_filter_uses_display_names(
    page: Page, app_url: str, backend, step
):
    """Language filter renders localised display names via Intl.DisplayNames
    in the active language — for German, en_US must NOT show the bridge's raw
    English 'English (US)' label but the German 'Englisch'-prefixed name."""
    _goto_voices_de(page, app_url, step)
    cat = backend["bridge"].get_voice_catalogue()
    codes = {lang["code"] for lang in cat["languages"]}
    assert "en_US" in codes, "catalogue always ships an en_US voice"
    opt = page.locator('[data-testid="vm-language"] option[value="en_US"]')
    label = opt.text_content() or ""
    # Intl.DisplayNames(['de'], {type:'language'}).of('en-US') → "Englisch (…)".
    assert label.lower().startswith("englisch"), (
        f"expected a German display name for en_US, got {label!r}"
    )
    step.check("language options render localised Intl.DisplayNames labels")
