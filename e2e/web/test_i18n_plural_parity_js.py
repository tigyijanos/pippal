"""T-304 JS↔Python plural PARITY, run in the served app context.

The shared vector table ``tests/fixtures/plural_parity.json`` (T-102) was
captured from ``Intl.PluralRules`` and is already asserted against the Python
resolver in ``tests/test_i18n_engine.py``. This closes the loop the T-101
review asked for: it runs the SAME fixture through ``Intl.PluralRules`` *in
the live browser* (via ``page.evaluate`` on the real served frontend) and
proves a three-way agreement for EVERY vector —

    fixture category  ==  browser Intl.PluralRules  ==  pippal.i18n.cldr_plural

so the JS and Python UIs can never select a different CLDR category for the
same count on the same screen (design §10). The browser leg guards against
an Intl/V8 drift from the captured fixture; the Python leg is the genuine
cross-runtime parity.

Oracle-first: the categories come from the shared fixture and the two live
runtimes, never a hardcoded expectation. The boundary vectors the issue AC
names (uk 1/2/5/11/21/22, zh-CN any->other, en 1/2, pt-BR 0/1) are asserted
present so a truncated fixture cannot pass hollow.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page

from pippal import i18n

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "plural_parity.json"

# Boundary vectors the issue AC calls out — must exist in the fixture so the
# parity assertion is not vacuously green on a truncated table. (uk 21 -> one
# is CLDR-correct: i%10==1 & i%100!=11; the issue prose's "21->few" is an
# error we defer from — the fixture + Intl + Python all agree on "one".)
REQUIRED_BOUNDARIES = {
    ("uk", 1): "one",
    ("uk", 2): "few",
    ("uk", 5): "many",
    ("uk", 11): "many",
    ("uk", 21): "one",
    ("uk", 22): "few",
    ("zh-CN", 5): "other",
    ("en", 1): "one",
    ("en", 2): "other",
    ("pt-BR", 0): "one",
    ("pt-BR", 1): "one",
}


def _vectors() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    vectors = data["vectors"]
    assert vectors, "plural_parity.json has no vectors"
    return vectors


def test_fixture_contains_the_ac_boundary_vectors(step):
    """Guard: the shared fixture still carries every boundary the AC names."""
    vectors = _vectors()
    index = {(v["lang"], v["n"]): v["category"] for v in vectors}
    for (lang, n), expected in REQUIRED_BOUNDARIES.items():
        assert index.get((lang, n)) == expected, (
            f"fixture boundary {lang}/{n} == {index.get((lang, n))!r}, "
            f"expected {expected!r}"
        )
    step.check(f"all {len(REQUIRED_BOUNDARIES)} AC boundary vectors present in the fixture")


def test_js_intl_and_python_agree_on_every_vector(page: Page, app_url: str, backend, step):
    vectors = _vectors()

    # Boot the real served frontend so Intl.PluralRules runs in the genuine
    # app context (not a bare Node), matching the runtime i18n.js uses.
    page.goto(f"{app_url}/index.html?view=settings")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-i18n-ready')",
        timeout=15000,
    )
    step(f"served app booted; evaluating {len(vectors)} plural vectors in-browser")

    # One batched evaluate: compute the browser Intl category for every vector.
    js_categories = page.evaluate(
        """(vectors) => vectors.map(
            v => new Intl.PluralRules(v.lang).select(v.n)
        )""",
        vectors,
    )
    assert len(js_categories) == len(vectors)

    js_mismatch: list[str] = []
    py_mismatch: list[str] = []
    for vector, js_cat in zip(vectors, js_categories):
        lang, n, expected = vector["lang"], vector["n"], vector["category"]
        if js_cat != expected:
            js_mismatch.append(f"{lang}/{n}: browser Intl {js_cat!r} != fixture {expected!r}")
        py_cat = i18n.cldr_plural(lang, n)
        if py_cat != expected:
            py_mismatch.append(f"{lang}/{n}: python {py_cat!r} != fixture {expected!r}")

    assert not js_mismatch, "browser Intl.PluralRules drifted from the fixture:\n" + "\n".join(js_mismatch)
    step.check(f"browser Intl.PluralRules matches all {len(vectors)} fixture vectors")

    assert not py_mismatch, "pippal.i18n.cldr_plural drifted from the fixture:\n" + "\n".join(py_mismatch)
    step.check(f"pippal.i18n.cldr_plural matches all {len(vectors)} fixture vectors")
    step.check("three-way parity: fixture == browser Intl == Python cldr_plural")
