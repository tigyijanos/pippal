"""Completeness + quality oracle for the T-105 core catalogs (issue #126).

Five non-English catalogs (``zh-CN``, ``de``, ``hu``, ``uk``, ``pt-BR``) are
translated from ``webui/i18n/en.json``. This module is the machine-checkable
half of the "proper, official" bar: it asserts INDEPENDENT oracles — the en
catalog (key set + placeholders + plural shape) and the actual runtime CLDR
resolver (``pippal.i18n.cldr_plural``) — never the translations' own wording.

Checks per language:
  * exact key set == en (no missing, no extra);
  * placeholder parity per key (``{name}`` set identical to en);
  * plural objects carry EXACTLY the CLDR categories the *engine* can emit for
    that language (uk one/few/many/other, zh-CN other, de/hu/pt-BR one/other),
    and the ``_plural`` count placeholder appears in every category string;
  * plural/scalar shape matches en (a plural key stays plural, a scalar stays
    scalar);
  * no value is empty and none contains the ``⟦``/``⟧`` fallback marker;
  * no value equals its en counterpart except an explicit, justified allowlist
    (brand strings, international unit symbols, an id-format line, and a few
    legitimately identical native words);
  * ``_meta`` declares the right ``lang`` (== filename), a non-empty native
    ``name``, and ``fallback == "en"``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pippal.i18n import cldr_plural

I18N_DIR = Path(__file__).resolve().parents[1] / "webui" / "i18n"
NON_EN = ["zh-CN", "de", "hu", "uk", "pt-BR"]
PLACEHOLDER = re.compile(r"\{(\w+)\}")
MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"

# Native endonyms the catalogs must self-declare in _meta.name.
NATIVE_NAMES = {
    "zh-CN": "简体中文",
    "de": "Deutsch",
    "hu": "Magyar",
    "uk": "Українська",
    "pt-BR": "Português (Brasil)",
}

# (lang, key) pairs whose translation may legitimately EQUAL the English value.
# Every entry is deliberate; anything else equalling en is a translation gap.
#   Global rows (all langs): brand names, international unit symbols, and the
#   technical id-format meta line where the "id:" field label stays verbatim.
#   Per-language rows: native software conventions that ARE the English word.
_GLOBAL_EQUALS_EN = {
    "about.link.github",          # brand "GitHub"
    "window.settings.title",      # brand "PipPal" (voices/notices titles DO translate)
    "window.onboarding.title",    # brand "PipPal"
    "window.overlay.title",       # brand "PipPal"
    "settings.panel.auto_hide_unit",  # "ms" — international unit symbol
    "settings.panel.distance_unit",   # "px" — international unit symbol
    "voices.row.meta",            # "id: {id}   ·   {quality}" — id-format line
}
_PER_LANG_EQUALS_EN = {
    ("de", "settings.voice.engine_label"),   # "Engine" — standard DE audio/TTS term
    ("de", "voices.filter.status_label"),    # "Status" — standard DE term
    ("de", "about.link.reddit"),             # "Community" — established DE loanword
    ("pt-BR", "voices.filter.status_label"),  # "Status" — standard pt-BR term
}


def _load(lang: str) -> dict:
    return json.loads((I18N_DIR / f"{lang}.json").read_text("utf-8"))


EN = _load("en")
EN_KEYS = {k for k in EN if k != "_meta"}


def _leaves(value) -> dict:
    """Map a catalog value to {category-or-None: string}. Plural objects expose
    one entry per CLDR category (dropping the ``_plural`` marker); scalars use
    the ``None`` key."""
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k != "_plural"}
    return {None: value}


def _placeholders(value) -> set[str]:
    out: set[str] = set()
    for text in _leaves(value).values():
        out |= set(PLACEHOLDER.findall(text))
    return out


def _engine_categories(lang: str) -> set[str]:
    """The category set the RUNTIME resolver can emit for ``lang`` — the oracle
    for how a plural object must be shaped. Integers surface one/few/many; a
    couple of fractions surface the ``other`` bucket (uk, and the trivial langs
    where 'other' is the plural)."""
    samples: list[float] = [*range(0, 201), 0.5, 1.5, 2.5]
    return {cldr_plural(lang, n) for n in samples}


@pytest.fixture(scope="module")
def catalogs() -> dict[str, dict]:
    return {lang: _load(lang) for lang in NON_EN}


@pytest.mark.parametrize("lang", NON_EN)
def test_key_set_matches_en_exactly(lang: str, catalogs):
    keys = {k for k in catalogs[lang] if k != "_meta"}
    assert keys - EN_KEYS == set(), f"{lang}: keys not in en: {sorted(keys - EN_KEYS)}"
    assert EN_KEYS - keys == set(), f"{lang}: keys missing vs en: {sorted(EN_KEYS - keys)}"


@pytest.mark.parametrize("lang", NON_EN)
def test_placeholder_parity_per_key(lang: str, catalogs):
    cat = catalogs[lang]
    mismatches = {
        k: (sorted(_placeholders(EN[k])), sorted(_placeholders(cat[k])))
        for k in EN_KEYS
        if _placeholders(EN[k]) != _placeholders(cat[k])
    }
    assert not mismatches, f"{lang}: placeholder mismatches {mismatches}"


@pytest.mark.parametrize("lang", NON_EN)
def test_plural_shape_and_categories(lang: str, catalogs):
    cat = catalogs[lang]
    expected = _engine_categories(lang)
    for k in EN_KEYS:
        en_is_plural = isinstance(EN[k], dict)
        lang_is_plural = isinstance(cat[k], dict)
        assert en_is_plural == lang_is_plural, (
            f"{lang}: {k} plural/scalar shape differs from en "
            f"(en_plural={en_is_plural}, {lang}_plural={lang_is_plural})"
        )
        if not lang_is_plural:
            continue
        obj = cat[k]
        assert "_plural" in obj, f"{lang}: {k} plural object missing _plural marker"
        count_name = obj["_plural"]
        cats = {kk for kk in obj if kk != "_plural"}
        assert cats == expected, (
            f"{lang}: {k} plural categories {sorted(cats)} != CLDR {sorted(expected)}"
        )
        for c in cats:
            assert "{" + count_name + "}" in obj[c], (
                f"{lang}: {k}[{c}] must interpolate the count placeholder "
                f"{{{count_name}}}"
            )


@pytest.mark.parametrize("lang", NON_EN)
def test_no_marker_and_no_empty_values(lang: str, catalogs):
    cat = catalogs[lang]
    for k in EN_KEYS:
        for cat_name, text in _leaves(cat[k]).items():
            where = k if cat_name is None else f"{k}[{cat_name}]"
            assert text.strip(), f"{lang}: {where} is empty/whitespace"
            assert MARKER_OPEN not in text and MARKER_CLOSE not in text, (
                f"{lang}: {where} contains a ⟦⟧ fallback marker: {text!r}"
            )


@pytest.mark.parametrize("lang", NON_EN)
def test_translated_not_equal_en_outside_allowlist(lang: str, catalogs):
    cat = catalogs[lang]
    offenders = []
    for k in EN_KEYS:
        if k in _GLOBAL_EQUALS_EN or (lang, k) in _PER_LANG_EQUALS_EN:
            continue
        en_leaves = _leaves(EN[k])
        for cat_name, text in _leaves(cat[k]).items():
            en_text = en_leaves.get(cat_name, en_leaves.get("other"))
            if text == en_text:
                offenders.append(k if cat_name is None else f"{k}[{cat_name}]")
    assert not offenders, (
        f"{lang}: values equal to en without allowlist justification: "
        f"{sorted(set(offenders))}"
    )


@pytest.mark.parametrize("lang", NON_EN)
def test_overlay_loading_within_width_budget(lang: str, catalogs):
    """Character-level width oracle for the whimsical overlay loading lines: no
    translated ``overlay.loading.*`` value may exceed the English length + 20 %
    (chars). The overlay panel is ~560 px and these lines rotate in place, so
    German/pt-BR expansion is the layout risk. This locks the budget in the
    catalog; T-106 adds pixel-level (scrollWidth) guards on top."""
    cat = catalogs[lang]
    overflows = {}
    for k in EN_KEYS:
        if not k.startswith("overlay.loading."):
            continue
        budget = len(EN[k]) * 1.2
        length = len(cat[k])
        if length > budget:
            overflows[k] = (length, round(budget, 1))
    assert not overflows, (
        f"{lang}: overlay loading lines over en+20% budget "
        f"(len, budget): {overflows}"
    )


@pytest.mark.parametrize("lang", NON_EN)
def test_meta_block(lang: str, catalogs):
    meta = catalogs[lang].get("_meta", {})
    assert meta.get("lang") == lang, f"{lang}: _meta.lang != filename tag"
    assert meta.get("fallback") == "en", f"{lang}: _meta.fallback must be 'en'"
    assert meta.get("name") == NATIVE_NAMES[lang], (
        f"{lang}: _meta.name should be the native endonym {NATIVE_NAMES[lang]!r}"
    )


def test_allowlist_is_tight():
    """Every allowlist entry must actually equal en today — a stale entry that
    no longer matches means the allowlist is masking nothing (or the wrong
    thing) and should be pruned."""
    for lang in NON_EN:
        cat = _load(lang)
        for key in _GLOBAL_EQUALS_EN:
            if isinstance(EN[key], dict):
                continue
            assert cat[key] == EN[key], (
                f"stale global allowlist {key}: {lang} no longer equals en"
            )
        for al_lang, key in _PER_LANG_EQUALS_EN:
            if al_lang != lang:
                continue
            assert cat[key] == EN[key], (
                f"stale allowlist ({al_lang}, {key}): no longer equals en"
            )
