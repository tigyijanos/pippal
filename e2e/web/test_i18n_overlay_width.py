"""Tier-1 served Playwright PIXEL width-guard for the whimsical overlay
loading messages (T-106 / issue #127).

Context
-------
T-104 moved the 14 ``LOADING_MESSAGES`` in ``webui/js/overlay.js`` from
hardcoded English literals to catalog keys (``overlay.loading.*``), and
T-105 translated all 14 into the five non-English catalogs and added the
*character*-level budget guard (``overlay.loading.*`` ≤ en + 20 % chars,
``tests/test_i18n_catalogs.py``).

Characters are a proxy. The real oracle is PIXELS: the reader overlay is a
fixed 560 × 200 px frameless popup (``window_lifecycle.py`` ``overlay``
spec), and the rotating loading line renders inside a flex-centred
``.reader-loading-label`` capped at ``max-width: 92%``. This suite renders
the ACTUAL overlay surface at that production width, drives the REAL overlay
state into ``thinking`` through the backend, and — for EACH of the six
shipped languages and EACH of the 14 loading values — measures the rendered
``.reader-loading-label`` and asserts the text FITS without being clipped
(``scrollWidth <= clientWidth``). No sleeps: every wait is event-driven.

It also proves the OVERFLOW-SAFE fallback for hypothetical future overlong
translations: a deliberately gigantic string must degrade gracefully
(clipped with an ellipsis, ``max-width`` capped) WITHOUT widening the
560 px panel or breaking the layout.

Oracle-first: the loading keys come from the shipped ``en.json`` catalog
(independent of the JS source), the per-language values come from the live
``window.t()`` runtime, and the pass/fail is a geometric measurement of the
real element — never a mirror of the app's own code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

WEBUI = Path(__file__).resolve().parents[2] / "webui"

# Production overlay window size — window_lifecycle.py WINDOW_SPECS["overlay"].
# The panel is width:100% of this window, so rendering at this viewport
# reproduces the real ~560 px surface the user sees.
OVERLAY_W = 560
OVERLAY_H = 200

# The six shipped languages (issue #127 "Languages"): en + 5 catalogs.
LANGS = ["en", "de", "hu", "uk", "zh-CN", "pt-BR"]

# Sub-pixel tolerance for the fit comparison (browser rounds fractional
# text metrics to whole CSS pixels for client/scrollWidth).
EPS = 1.0


def _en_catalog() -> dict:
    return json.loads((WEBUI / "i18n" / "en.json").read_text("utf-8"))


def _loading_keys() -> list[str]:
    """The 14 overlay loading keys, sourced from the shipped en catalog —
    the independent oracle for WHICH keys must render within budget."""
    keys = sorted(k for k in _en_catalog() if k.startswith("overlay.loading."))
    assert len(keys) == 14, f"expected 14 overlay.loading.* keys, got {len(keys)}"
    return keys


def _wait_i18n_ready(page: Page) -> None:
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )


def _open_overlay_loading(page: Page, app_url: str, backend, lang: str) -> None:
    """Render the real overlay surface at production width in ``lang`` and
    drive the REAL backend overlay state into ``thinking`` so the served
    ``overlay.js`` tick() builds the ``.reader-loading-label`` in normal
    document flow — exactly the production loading path. Event-driven: we
    wait for the label element, never sleep."""
    page.set_viewport_size({"width": OVERLAY_W, "height": OVERLAY_H})
    page.goto(f"{app_url}/index.html?view=overlay&lang={lang}")
    expect(page.locator("body")).to_have_attribute("data-ready", "overlay", timeout=15000)
    _wait_i18n_ready(page)
    assert page.evaluate("document.documentElement.lang") == lang, (
        f"?lang={lang} must resolve as the active language"
    )
    # Real production event: a cache-miss synth announces the loading state.
    backend["overlay"].set_state("thinking")
    # tick() polls engine_state and injects the loader; wait for it to appear.
    page.wait_for_selector(".reader-loading-label", state="attached", timeout=15000)


# ---------------------------------------------------------------------------
# The pixel oracle — every loading line fits the overlay at production width.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_overlay_loading_lines_fit_at_production_width(
    page: Page, app_url: str, backend, step, lang: str
):
    keys = _loading_keys()
    _open_overlay_loading(page, app_url, backend, lang)
    step(f"overlay rendered at {OVERLAY_W}x{OVERLAY_H} px, lang={lang!r}, state=thinking")

    # One atomic evaluate: JS is single-threaded, so the 120 ms tick() cannot
    # interleave and overwrite the label between our set and our measurement.
    measurements = page.evaluate(
        """(keys) => {
            const label = document.querySelector('.reader-loading-label');
            const box = label.parentElement;               // .reader-loading
            const out = [];
            for (const key of keys) {
                const value = window.t(key);
                label.textContent = value;
                // Reading these forces a synchronous reflow.
                const clientWidth = label.clientWidth;      // capped @ max-width
                const scrollWidth = label.scrollWidth;      // full content width
                const boxWidth = box.clientWidth;
                out.push({
                    key, value, clientWidth, scrollWidth, boxWidth,
                    // 92% is the .reader-loading-label max-width budget.
                    cap: boxWidth * 0.92,
                });
            }
            return out;
        }""",
        keys,
    )

    assert len(measurements) == 14, measurements
    overflows = []
    max_util = 0.0
    max_util_key = None
    for m in measurements:
        # scrollWidth > clientWidth means the browser had to clip the text
        # (the line did NOT fit the 92% budget) — the overlay AC failure.
        if m["scrollWidth"] > m["clientWidth"] + EPS:
            overflows.append((m["key"], m["value"], m["scrollWidth"], m["clientWidth"]))
        # Utilisation vs the hard max-width cap; scrollWidth is the true
        # content width whether or not the browser clipped it.
        util = m["scrollWidth"] / m["cap"] if m["cap"] else 0.0
        if util > max_util:
            max_util, max_util_key = util, m["key"]

    assert not overflows, (
        f"{lang}: {len(overflows)} loading line(s) overflow the overlay "
        f"(scrollWidth > clientWidth) at {OVERLAY_W}px: {overflows}"
    )
    step.check(
        f"{lang}: all 14 loading lines fit (scrollWidth<=clientWidth); "
        f"peak {max_util * 100:.1f}% of the 92% cap on {max_util_key!r}"
    )


def test_overlay_loading_en_values_match_catalog_no_regression(
    page: Page, app_url: str, backend, step
):
    """English no-regression oracle (issue AC): the overlay renders each
    loading line from the shipped en.json catalog byte-for-byte — the
    T-104 key migration preserved the English strings — and every line
    fits the production-width panel."""
    en = _en_catalog()
    keys = _loading_keys()
    _open_overlay_loading(page, app_url, backend, "en")

    rendered = page.evaluate(
        """(keys) => {
            const label = document.querySelector('.reader-loading-label');
            const out = {};
            for (const key of keys) {
                label.textContent = window.t(key);
                out[key] = {
                    value: label.textContent,
                    fits: label.scrollWidth <= label.clientWidth + 1,
                };
            }
            return out;
        }""",
        keys,
    )
    mismatches = {k: rendered[k]["value"] for k in keys if rendered[k]["value"] != en[k]}
    assert not mismatches, f"en overlay loading values drifted from catalog: {mismatches}"
    step.check("en: all 14 loading lines render byte-identically to en.json")

    unfit = [k for k in keys if not rendered[k]["fits"]]
    assert not unfit, f"en loading lines that do not fit the overlay: {unfit}"
    step.check("en: all 14 loading lines fit the production-width overlay")


# ---------------------------------------------------------------------------
# Overflow-safe fallback — a future overlong translation degrades gracefully.
# ---------------------------------------------------------------------------


def test_overlay_loading_overlong_string_degrades_gracefully(
    page: Page, app_url: str, backend, step
):
    """Guard for future languages: a translation far longer than any shipped
    value must NOT break the overlay layout. The ``.reader-loading-label``
    CSS safeguard (``max-width: 92%`` + ``overflow: hidden`` +
    ``text-overflow: ellipsis`` + ``white-space: nowrap``) must clip it with
    an ellipsis while the 560 px panel keeps its exact width."""
    _open_overlay_loading(page, app_url, backend, "en")
    overlong = "Reticulating the impossibly verbose polysyllabic phonemes " * 6

    result = page.evaluate(
        """(overlong) => {
            const label = document.querySelector('.reader-loading-label');
            const root = document.getElementById('root');
            const box = label.parentElement;              // .reader-loading
            const rootBefore = root.getBoundingClientRect().width;
            const boxBefore = box.clientWidth;
            label.textContent = overlong;
            const cs = getComputedStyle(label);
            return {
                clientWidth: label.clientWidth,
                scrollWidth: label.scrollWidth,
                cap: box.clientWidth * 0.92,
                overflow: cs.overflow,
                textOverflow: cs.textOverflow,
                whiteSpace: cs.whiteSpace,
                rootBefore, rootAfter: root.getBoundingClientRect().width,
                boxBefore, boxAfter: box.clientWidth,
                viewportW: window.innerWidth,
            };
        }""",
        overlong,
    )

    # 1. The overlong string genuinely overflows its budget (ellipsis engaged).
    assert result["scrollWidth"] > result["clientWidth"] + EPS, (
        "the deliberately overlong string should overflow the label's content box"
    )
    step.check("overlong string overflows the content box (scrollWidth > clientWidth)")

    # 2. The safeguard caps the visible label at the 92% max-width budget.
    assert result["clientWidth"] <= result["cap"] + EPS, (
        f"label clientWidth {result['clientWidth']} exceeded the 92% cap "
        f"{result['cap']:.1f} — max-width safeguard missing"
    )
    assert result["overflow"] == "hidden", f"overflow must be hidden, got {result['overflow']!r}"
    assert result["textOverflow"] == "ellipsis", (
        f"text-overflow must be ellipsis, got {result['textOverflow']!r}"
    )
    assert result["whiteSpace"] == "nowrap", (
        f"white-space must be nowrap, got {result['whiteSpace']!r}"
    )
    step.check("overflow:hidden + text-overflow:ellipsis + max-width cap all in effect")

    # 3. The panel layout is untouched: the overlong text never widened the
    #    560 px window (no horizontal blow-out).
    assert result["rootAfter"] == result["rootBefore"], (
        f"overlay #root width changed under overlong text "
        f"({result['rootBefore']} -> {result['rootAfter']})"
    )
    assert result["boxAfter"] == result["boxBefore"], (
        f".reader-loading width changed under overlong text "
        f"({result['boxBefore']} -> {result['boxAfter']})"
    )
    assert result["rootAfter"] <= result["viewportW"] + EPS, (
        f"overlay #root ({result['rootAfter']}) wider than the {OVERLAY_W}px window"
    )
    step.check(
        f"panel layout stable: #root stayed {result['rootAfter']}px "
        f"within the {OVERLAY_W}px window (no overflow blow-out)"
    )
