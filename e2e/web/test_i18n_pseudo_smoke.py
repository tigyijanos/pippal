"""Tier-1 served Playwright PSEUDO-LOCALE smoke (T-305, issue #128).

Boots the real served UI in the build-only ``en-XA`` pseudo-locale and proves
two things a real translation pass would otherwise only reveal much later:

1. **Hardcoded-string leaks.** Every ``en-XA`` string is accented and wrapped
   in ``[!! … !!]`` delimiters. So every ``[data-i18n]``-bearing element must
   render a bracketed/accented value — a plain-ASCII English word left on a
   surface is a string that bypassed ``t()`` and never got a catalog key.
   (Also asserts NO ``⟦key⟧`` missing-marker leaks — every touched key exists
   in the pseudo catalog.)

2. **Width overflow.** The pseudo strings carry ~40 % padding (worst-case
   German-plus widths). Driven through the REAL overlay loading panel at its
   production 560 px width, the panel must absorb every padded line WITHOUT a
   horizontal blow-out (``scrollWidth <= clientWidth`` on the panel; ``#root``
   width unchanged), even where the label itself clips with an ellipsis.

The pseudo-locale is loaded via the documented host-injection seam
(``window.__PIPPAL_LANG__``) — the same synchronous override the desktop host
uses and ``test_i18n_boot.py`` exercises for arbitrary tags — because ``en-XA``
is a build-only catalog deliberately kept out of ``SUPPORTED_LANGS`` (and thus
out of the JS supported-tag normalisation). The catalog file itself is served
statically like any other, so ``i18n.js`` fetches ``i18n/en-XA.json`` under the
anti-FOUC cloak exactly as it would for a shipped language.

Oracle-first: the loading keys come from the shipped ``en.json`` (independent
of the JS source), the pseudo signature comes from the committed ``en-XA.json``
generator contract, and the width pass/fail is a geometric measurement of the
real panel element.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

WEBUI = Path(__file__).resolve().parents[2] / "webui"
PSEUDO_LANG = "en-XA"
OPEN_DELIM = "[!! "
CLOSE_DELIM = " !!]"
MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"

# Production overlay window size — window_lifecycle.py WINDOW_SPECS["overlay"].
OVERLAY_W = 560
OVERLAY_H = 200
EPS = 1.0


def _en_catalog() -> dict:
    return json.loads((WEBUI / "i18n" / "en.json").read_text("utf-8"))


def _inject_pseudo(page: Page) -> None:
    """Seed the host-injected language global BEFORE any page script runs, so
    i18n.js resolves ``en-XA`` synchronously and fetches i18n/en-XA.json."""
    page.add_init_script(f"window.__PIPPAL_LANG__ = {json.dumps(PSEUDO_LANG)};")


def _wait_i18n_ready(page: Page) -> None:
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )


def _boot(page: Page, app_url: str, view: str) -> None:
    _inject_pseudo(page)
    page.goto(f"{app_url}/index.html?view={view}")
    expect(page.locator("body")).to_have_attribute("data-ready", view, timeout=15000)
    _wait_i18n_ready(page)


# ---------------------------------------------------------------------------
# AC3 — every data-i18n element renders a pseudo value (no hardcoded leak)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("view", ["settings", "onboarding"])
def test_pseudo_boot_every_data_i18n_element_is_pseudo(
    page: Page, app_url: str, step, view: str
):
    _boot(page, app_url, view)

    assert page.evaluate("document.documentElement.lang") == PSEUDO_LANG
    step.check(f"{view}: booted in the pseudo-locale (document.lang == {PSEUDO_LANG!r})")

    # No missing-key marker anywhere: every touched key exists in en-XA.
    content = page.content()
    assert MARKER_OPEN not in content and MARKER_CLOSE not in content, (
        f"{view}: ⟦key⟧ missing-marker leaked in the pseudo boot"
    )
    step.check(f"{view}: no ⟦key⟧ marker in the DOM")

    # Every [data-i18n] element's filled text must be a pseudo string (starts
    # with the [!! delimiter). A plain-ASCII value here = a string that
    # bypassed t() / was never keyed.
    report = page.evaluate(
        """(open) => {
            const els = Array.from(document.querySelectorAll('[data-i18n]'));
            const leaks = [];
            for (const el of els) {
                const txt = (el.textContent || '').trim();
                if (txt && !txt.startsWith(open)) {
                    leaks.push({ key: el.getAttribute('data-i18n'), text: txt });
                }
            }
            return { total: els.length, leaks };
        }""",
        OPEN_DELIM,
    )
    assert report["total"] > 0, f"{view}: no [data-i18n] elements found to check"
    assert not report["leaks"], (
        f"{view}: {len(report['leaks'])} data-i18n element(s) rendered a "
        f"non-pseudo (hardcoded/untranslated) value: {report['leaks']}"
    )
    step.check(
        f"{view}: all {report['total']} [data-i18n] elements render a pseudo value"
    )


def test_pseudo_chrome_is_accented_not_english(page: Page, app_url: str, step):
    """A concrete, key-specific oracle: the close-button title is pseudo-
    translated (accented + bracketed), NOT the English 'Close' — proving the
    served pseudo catalog is genuinely wired through t()."""
    _boot(page, app_url, "settings")
    close = page.get_by_test_id("window-close")
    title = close.get_attribute("title")
    assert title and title.startswith(OPEN_DELIM) and title.endswith(CLOSE_DELIM)
    assert "Close" not in title, f"close title is un-accented English: {title!r}"
    assert any(ord(ch) > 127 for ch in title), "close title has no accented glyph"
    step.check(f"close-button title is pseudo-translated: {title!r}")


# ---------------------------------------------------------------------------
# AC4 — the +40% padded loading lines never blow out the overlay panel width
# ---------------------------------------------------------------------------


def _loading_keys() -> list[str]:
    keys = sorted(k for k in _en_catalog() if k.startswith("overlay.loading."))
    assert len(keys) == 14, f"expected 14 overlay.loading.* keys, got {len(keys)}"
    return keys


def _boot_overlay_thinking(page: Page, app_url: str, backend) -> None:
    _inject_pseudo(page)
    page.set_viewport_size({"width": OVERLAY_W, "height": OVERLAY_H})
    page.goto(f"{app_url}/index.html?view=overlay")
    expect(page.locator("body")).to_have_attribute("data-ready", "overlay", timeout=15000)
    _wait_i18n_ready(page)
    assert page.evaluate("document.documentElement.lang") == PSEUDO_LANG
    backend["overlay"].set_state("thinking")
    page.wait_for_selector(".reader-loading-label", state="attached", timeout=15000)


def test_pseudo_overlay_loading_panel_never_overflows(
    page: Page, app_url: str, backend, step
):
    keys = _loading_keys()
    _boot_overlay_thinking(page, app_url, backend)
    step(f"overlay booted at {OVERLAY_W}x{OVERLAY_H}px in {PSEUDO_LANG}, state=thinking")

    measurements = page.evaluate(
        """(keys) => {
            const label = document.querySelector('.reader-loading-label');
            const box = label.parentElement;         // .reader-loading
            const root = document.getElementById('root');
            const rootBefore = root.getBoundingClientRect().width;
            const out = [];
            for (const key of keys) {
                const value = window.t(key);
                label.textContent = value;
                // Reading these forces a synchronous reflow.
                out.push({
                    key, value,
                    labelClient: label.clientWidth,
                    labelScroll: label.scrollWidth,
                    boxClient: box.clientWidth,
                    boxScroll: box.scrollWidth,
                    rootClient: root.clientWidth,
                    rootScroll: root.scrollWidth,
                    rootWidth: root.getBoundingClientRect().width,
                    viewportW: window.innerWidth,
                });
            }
            return { rootBefore, rows: out };
        }""",
        keys,
    )

    rows = measurements["rows"]
    assert len(rows) == 14, rows
    en = _en_catalog()

    panel_overflows = []
    unstable = []
    not_padded = []
    for m in rows:
        # Panel-level containment: neither the loading box nor #root may grow a
        # horizontal scroll (that would be a layout blow-out).
        if m["boxScroll"] > m["boxClient"] + EPS or m["rootScroll"] > m["rootClient"] + EPS:
            panel_overflows.append((m["key"], m["boxScroll"], m["boxClient"]))
        # #root must not exceed the physical overlay window width.
        if m["rootWidth"] > m["viewportW"] + EPS:
            panel_overflows.append((m["key"], "root>viewport", m["rootWidth"]))
        # #root width is stable under every line (no widening).
        if abs(m["rootWidth"] - measurements["rootBefore"]) > EPS:
            unstable.append((m["key"], m["rootWidth"]))
        # The padding is real: every pseudo line is wider (more chars) than its
        # English source — this is the worst-case width the panel just absorbed.
        if not (m["value"].startswith(OPEN_DELIM) and len(m["value"]) > len(en[m["key"]])):
            not_padded.append((m["key"], m["value"]))

    assert not panel_overflows, (
        f"overlay panel overflowed horizontally under padded pseudo text "
        f"(scrollWidth > clientWidth): {panel_overflows}"
    )
    step.check("all 14 padded loading lines: panel scrollWidth <= clientWidth")

    assert not unstable, (
        f"#root width changed under padded pseudo text (blow-out): {unstable}"
    )
    step.check(
        f"#root stayed {measurements['rootBefore']:.0f}px within the "
        f"{OVERLAY_W}px window for every line"
    )

    # The +40% padding is doing its job: every pseudo line is a genuine
    # worst-case width stress (wider than English), not a no-op.
    assert not not_padded, (
        f"pseudo loading lines not wider than English (padding missing): {not_padded}"
    )
    step.check("all 14 pseudo loading lines are wider than English (real width stress)")
