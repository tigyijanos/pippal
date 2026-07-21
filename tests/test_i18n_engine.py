"""Oracle-first tests for the core Python i18n engine (T-102, issue #123).

The oracles here are INDEPENDENT of the implementation:
- Plurals are checked against ``Intl.PluralRules`` output captured in
  ``tests/fixtures/plural_parity.json`` (the same file the JS side, T-101,
  consumes) so the two runtimes are guaranteed to agree on the same screen.
- Fallback / interpolation / discovery are checked against synthetic catalogs
  written into ``tmp_path`` — no dependency on the real shipped catalog content
  (which T-104 fills in later) and no dependency on the CI machine's locale.

Regenerate the parity fixture (needs Node with Intl):

    node -e 'const L=["en","de","hu","uk","zh-CN","pt-BR"],
    N=[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,20,21,22,23,24,25,100,101,111,1000,1.5,2.5],
    v=[];for(const l of L){const p=new Intl.PluralRules(l);for(const n of N)
    v.push({lang:l,n,category:p.select(n)})}require("fs").writeFileSync(
    "tests/fixtures/plural_parity.json",JSON.stringify(
    {source:"Intl.PluralRules",languages:L,vectors:v},null,2))'
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pippal import i18n

FIXTURE = Path(__file__).parent / "fixtures" / "plural_parity.json"


# --------------------------------------------------------------------------
# CLDR plural resolver — parity with Intl.PluralRules
# --------------------------------------------------------------------------
def _parity_vectors() -> list[tuple[str, float, str]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [(v["lang"], v["n"], v["category"]) for v in data["vectors"]]


@pytest.mark.parametrize(("lang", "n", "expected"), _parity_vectors())
def test_cldr_plural_matches_intl_pluralrules(lang: str, n: float, expected: str) -> None:
    """Every (lang, n) vector from Intl.PluralRules is reproduced by cldr_plural."""
    assert i18n.cldr_plural(lang, n) == expected


def test_uk_boundary_spotchecks() -> None:
    """Ukrainian is the hard 4-form case; pin the boundaries explicitly.

    NOTE: issue #123 AC lists ``n=21 -> few``, but Intl.PluralRules (the
    binding parity oracle per design §10) returns ``one`` for 21 in Ukrainian
    (21 uses the singular agreement form). We follow the oracle; the AC value
    is a transcription slip flagged to the PO.
    """
    assert i18n.cldr_plural("uk", 1) == "one"
    assert i18n.cldr_plural("uk", 2) == "few"
    assert i18n.cldr_plural("uk", 5) == "many"
    assert i18n.cldr_plural("uk", 11) == "many"
    assert i18n.cldr_plural("uk", 21) == "one"  # NOT "few" — CLDR-correct
    assert i18n.cldr_plural("uk", 22) == "few"
    assert i18n.cldr_plural("uk", 1.5) == "other"  # fractions -> other


def test_zh_has_no_plurals() -> None:
    for n in (0, 1, 2, 5, 11, 21, 100, 1.5):
        assert i18n.cldr_plural("zh-CN", n) == "other"


def test_simple_one_other_languages() -> None:
    for lang in ("en", "de", "hu"):
        assert i18n.cldr_plural(lang, 1) == "one"
        assert i18n.cldr_plural(lang, 0) == "other"
        assert i18n.cldr_plural(lang, 2) == "other"
        assert i18n.cldr_plural(lang, 1.5) == "other"


def test_pt_br_zero_and_one_are_one() -> None:
    assert i18n.cldr_plural("pt-BR", 0) == "one"
    assert i18n.cldr_plural("pt-BR", 1) == "one"
    assert i18n.cldr_plural("pt-BR", 2) == "other"
    assert i18n.cldr_plural("pt-BR", 1.5) == "one"  # integer part 1 -> one


def test_integral_float_matches_int() -> None:
    """1.0 must behave like 1 (JS Number parity)."""
    assert i18n.cldr_plural("en", 1.0) == i18n.cldr_plural("en", 1) == "one"
    assert i18n.cldr_plural("uk", 2.0) == i18n.cldr_plural("uk", 2) == "few"


def test_unknown_language_defaults_to_one_other() -> None:
    assert i18n.cldr_plural("fr", 1) == "one"
    assert i18n.cldr_plural("fr", 2) == "other"


def test_cldr_plural_non_numeric_count_degrades_to_other() -> None:
    """A bad count must degrade to ``other``, never raise (t() surface safety)."""
    assert i18n.cldr_plural("en", "abc") == "other"
    assert i18n.cldr_plural("en", None) == "other"
    assert i18n.cldr_plural("uk", object()) == "other"
    # A numeric string still resolves normally.
    assert i18n.cldr_plural("en", "1") == "one"


# --------------------------------------------------------------------------
# Catalog fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    """A synthetic 2-language catalog dir (en + de) with plural + interp keys."""
    en = {
        "_meta": {"lang": "en", "name": "English", "fallback": "en"},
        "footer.save": "Save",
        "footer.cancel": "Cancel",
        "greeting": "Hello, {name}!",
        "items.count": {
            "_plural": "count",
            "one": "{count} item",
            "other": "{count} items",
        },
    }
    de = {
        "_meta": {"lang": "de", "name": "Deutsch", "fallback": "en"},
        "footer.save": "Speichern",
        # NOTE: "footer.cancel" and "greeting" intentionally absent -> fall to en.
        "items.count": {
            "_plural": "count",
            "one": "{count} Element",
            "other": "{count} Elemente",
        },
    }
    (tmp_path / "en.json").write_text(json.dumps(en), encoding="utf-8")
    (tmp_path / "de.json").write_text(json.dumps(de), encoding="utf-8")
    i18n.clear_catalog_cache()
    return tmp_path


# --------------------------------------------------------------------------
# t() — fallback chain
# --------------------------------------------------------------------------
def test_t_uses_active_language(catalog: Path) -> None:
    assert i18n.t("footer.save", lang="de", catalog_directory=catalog) == "Speichern"


def test_t_falls_back_to_english(catalog: Path) -> None:
    # Present in en only -> a de lookup must resolve via the en fallback.
    assert i18n.t("footer.cancel", lang="de", catalog_directory=catalog) == "Cancel"


def test_t_missing_key_returns_marker(catalog: Path) -> None:
    out = i18n.t("does.not.exist", lang="de", catalog_directory=catalog)
    assert out == f"{i18n.MARKER_OPEN}does.not.exist{i18n.MARKER_CLOSE}"
    assert out == "⟦does.not.exist⟧"


def test_t_fallback_chain_full(catalog: Path) -> None:
    # active -> en -> marker, all three legs in one test.
    assert i18n.t("footer.save", lang="de", catalog_directory=catalog) == "Speichern"  # active
    assert i18n.t("greeting", {"name": "Ada"}, lang="de", catalog_directory=catalog) == (
        "Hello, Ada!"
    )  # en fallback
    assert "⟦" in i18n.t("nope", lang="de", catalog_directory=catalog)  # marker


# --------------------------------------------------------------------------
# t() — interpolation + plural
# --------------------------------------------------------------------------
def test_interpolation_named_placeholder(catalog: Path) -> None:
    assert i18n.t("greeting", {"name": "Ada"}, lang="en", catalog_directory=catalog) == (
        "Hello, Ada!"
    )


def test_interpolation_missing_placeholder_is_safe(catalog: Path) -> None:
    # A missing param must never raise; the placeholder is left literal.
    assert i18n.t("greeting", {}, lang="en", catalog_directory=catalog) == "Hello, {name}!"


def test_plural_selection_singular(catalog: Path) -> None:
    assert i18n.t("items.count", {"count": 1}, lang="en", catalog_directory=catalog) == "1 item"


def test_plural_selection_plural(catalog: Path) -> None:
    assert i18n.t("items.count", {"count": 5}, lang="en", catalog_directory=catalog) == "5 items"


def test_plural_uses_resolved_catalog_language(catalog: Path) -> None:
    assert i18n.t("items.count", {"count": 1}, lang="de", catalog_directory=catalog) == (
        "1 Element"
    )
    assert i18n.t("items.count", {"count": 3}, lang="de", catalog_directory=catalog) == (
        "3 Elemente"
    )


def test_t_plural_bad_count_is_safe(catalog: Path) -> None:
    """A non-numeric / None count must not crash t(); it picks the ``other`` form."""
    assert i18n.t("items.count", {"count": "abc"}, lang="en", catalog_directory=catalog) == (
        "abc items"
    )
    assert i18n.t("items.count", {"count": None}, lang="en", catalog_directory=catalog) == (
        "None items"
    )
    # Count placeholder entirely absent -> defaults to 0 -> other, no raise.
    assert i18n.t("items.count", {}, lang="en", catalog_directory=catalog) == "{count} items"


# --------------------------------------------------------------------------
# SUPPORTED_LANGS — dynamic discovery (no hardcoded list)
# --------------------------------------------------------------------------
def test_discover_langs_english_first_on_empty_dir(tmp_path: Path) -> None:
    assert i18n.discover_langs(tmp_path) == ["en"]


def test_adding_dummy_catalog_extends_supported_langs(tmp_path: Path) -> None:
    """Dropping xx.json in makes ``xx`` supported with NO code edit (AC)."""
    (tmp_path / "en.json").write_text('{"_meta":{"lang":"en"}}', encoding="utf-8")
    assert "xx" not in i18n.discover_langs(tmp_path)
    # Add a brand-new language purely by creating a catalog file.
    (tmp_path / "xx.json").write_text('{"_meta":{"lang":"xx"}}', encoding="utf-8")
    langs = i18n.discover_langs(tmp_path)
    assert "xx" in langs
    assert langs[0] == "en"  # English always leads the fallback chain


@pytest.mark.parametrize(
    "malicious",
    ["../../etc/passwd", "a/b", "..\\..\\windows\\win.ini", "..", "en/../de", ""],
)
def test_load_catalog_rejects_path_traversal(tmp_path: Path, malicious: str) -> None:
    """A lang with separators or ``..`` returns {} without escaping the catalog dir."""
    # Plant a file OUTSIDE the catalog dir that a traversal could otherwise read.
    outside = tmp_path.parent / "secret.json"
    outside.write_text('{"_meta": {"lang": "secret"}}', encoding="utf-8")
    try:
        catalog_dir = tmp_path / "i18n"
        catalog_dir.mkdir()
        i18n.clear_catalog_cache()
        assert i18n.load_catalog(malicious, catalog_directory=catalog_dir) == {}
    finally:
        outside.unlink(missing_ok=True)


def test_private_underscore_files_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "_plural_parity.json").write_text("{}", encoding="utf-8")
    (tmp_path / "de.json").write_text('{"_meta":{"lang":"de"}}', encoding="utf-8")
    langs = i18n.discover_langs(tmp_path)
    assert "de" in langs
    assert "_plural_parity" not in langs


def test_module_supported_langs_includes_shipped_en() -> None:
    # The real shipped catalog dir seeds at least English.
    assert "en" in i18n.SUPPORTED_LANGS


def test_shipped_catalogs_support_all_six_languages() -> None:
    """All six 0.3.1 languages ship as (skeleton) catalogs so discovery — and
    therefore the Settings picker (T-103) — sees the full set on merged main,
    even before T-105 fills the translations."""
    assert set(i18n.SUPPORTED_LANGS) == {"en", "zh-CN", "de", "hu", "uk", "pt-BR"}
    # English always leads (universal fallback).
    assert i18n.SUPPORTED_LANGS[0] == "en"


def test_shipped_non_en_catalogs_are_populated_and_declare_en_fallback() -> None:
    """Each shipped non-en catalog is now FULLY populated (T-105 filled the
    translations) and still chains to en, so any not-yet-added key falls back to
    English. (Pre-T-105 this asserted _meta-only skeletons; T-105 fills them.)"""
    en_keys = {k for k in i18n.load_catalog("en") if not k.startswith("_")}
    for lang in ("zh-CN", "de", "hu", "uk", "pt-BR"):
        catalog = i18n.load_catalog(lang)
        meta = catalog.get("_meta") or {}
        assert meta.get("lang") == lang
        assert meta.get("fallback") == "en"
        # Catalog now carries the full en key set (completeness is asserted in
        # detail by tests/test_i18n_catalogs.py).
        lang_keys = {k for k in catalog if not k.startswith("_")}
        assert lang_keys == en_keys
        # Fallback chain still reaches en.
        assert i18n._fallback_chain(lang, None)[-1] == "en"


def test_skeleton_de_lookup_falls_back_to_en_value(tmp_path: Path) -> None:
    """Mirrors the shipped shape (en holds the string, de is a _meta-only
    skeleton): a de lookup returns the en value via the fallback chain."""
    (tmp_path / "en.json").write_text(
        json.dumps({"_meta": {"lang": "en", "fallback": "en"}, "footer.save": "Save"}),
        encoding="utf-8",
    )
    (tmp_path / "de.json").write_text(
        json.dumps({"_meta": {"lang": "de", "fallback": "en"}}),
        encoding="utf-8",
    )
    i18n.clear_catalog_cache()
    assert i18n.t("footer.save", lang="de", catalog_directory=tmp_path) == "Save"


# --------------------------------------------------------------------------
# System-language detection (monkeypatched locale — never reads CI locale)
# --------------------------------------------------------------------------
SIX = ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pt", "pt-BR"),  # bare pt -> chosen variant
        ("pt-PT", "pt-BR"),  # other pt region -> pt-BR (only supported pt)
        ("zh-Hans", "zh-CN"),  # script subtag -> zh-CN
        ("zh", "zh-CN"),  # bare zh -> zh-CN
        ("zh-Hans-CN", "zh-CN"),
        ("de-DE", "de"),  # region -> bare supported tag
        ("en-US", "en"),
        ("uk-UA", "uk"),
        ("pt-BR", "pt-BR"),  # exact match
        ("fi", "en"),  # unsupported -> en
        ("fr-FR", "en"),  # unsupported -> en
        ("", "en"),  # no locale -> en
    ],
)
def test_detect_system_language(monkeypatch: pytest.MonkeyPatch, raw: str, expected: str) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: raw)
    assert i18n.detect_system_language(SIX) == expected


def test_detect_falls_back_to_en_when_locale_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "")
    assert i18n.detect_system_language(SIX) == "en"


# --------------------------------------------------------------------------
# resolve_language — the seam T-103's `language` config key plugs into
# --------------------------------------------------------------------------
def test_resolve_language_explicit_config_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "de-DE")
    # Explicit user pick overrides the system language.
    assert i18n.resolve_language("uk", SIX) == "uk"


def test_resolve_language_empty_config_uses_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "de-DE")
    assert i18n.resolve_language("", SIX) == "de"  # Auto/system
    assert i18n.resolve_language(None, SIX) == "de"


def test_resolve_language_unsupported_config_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "hu-HU")
    # An unsupported explicit value is ignored -> system -> hu.
    assert i18n.resolve_language("fr", SIX) == "hu"


def test_resolve_language_unsupported_everywhere_is_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "fi-FI")
    assert i18n.resolve_language("", SIX) == "en"


# --------------------------------------------------------------------------
# Active-language global (live updates for on-demand strings)
# --------------------------------------------------------------------------
def test_set_and_get_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "en-US")
    original = i18n.get_language()
    try:
        assert i18n.set_language("de", SIX) == "de"
        assert i18n.get_language() == "de"
        # Empty -> Auto/system resolution.
        assert i18n.set_language("", SIX) == "en"
        assert i18n.get_language() == "en"
    finally:
        i18n.set_language(original, SIX)
