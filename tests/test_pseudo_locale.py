"""Oracle-first tests for the ``en-XA`` pseudo-locale (T-305, issue #128).

Two independent oracles guard the generator and the discovery exclusion:

* the committed ``webui/i18n/en-XA.json`` must be exactly what
  ``tools/gen_pseudo_locale.py`` produces from the current ``en.json`` (a
  staleness diff — the artifact can never silently drift from English);
* every English string must be transformed (accented + bracketed) with its
  ``{placeholder}`` / ``<html>`` / plural structure preserved — an untouched
  plain-ASCII value would be a generator bug that hides a hardcoded-string leak
  in the smoke run;
* the pseudo-locale must stay OUT of ``SUPPORTED_LANGS`` (and thus the picker)
  while remaining loadable via ``load_catalog``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEBUI_I18N = ROOT / "webui" / "i18n"
sys.path.insert(0, str(ROOT / "tools"))

import gen_pseudo_locale as gen  # noqa: E402

from pippal import i18n  # noqa: E402

MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"
_PLACEHOLDER = re.compile(r"\{[^}]*\}")
_HTML_TAG = re.compile(r"<[^>]*>")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def _en() -> dict:
    return json.loads((WEBUI_I18N / "en.json").read_text("utf-8"))


def _en_xa() -> dict:
    return json.loads((WEBUI_I18N / "en-XA.json").read_text("utf-8"))


# ---------------------------------------------------------------------------
# AC1 — the generator produces a valid, fully transformed catalog
# ---------------------------------------------------------------------------


def test_committed_en_xa_is_not_stale() -> None:
    """The committed catalog is byte-identical to a fresh generation from the
    current ``en.json`` — regenerating must be a no-op (``--check`` passes)."""
    rendered = gen.render()
    current = (WEBUI_I18N / "en-XA.json").read_text("utf-8")
    assert current == rendered, (
        "webui/i18n/en-XA.json is stale — run: python tools/gen_pseudo_locale.py"
    )
    assert gen.main(["--check"]) == 0


def test_en_xa_has_every_key_from_en() -> None:
    en, xa = _en(), _en_xa()
    assert set(xa) == set(en), "en-XA must have exactly the en key set"


def test_meta_is_hidden_and_falls_back_to_en() -> None:
    meta = _en_xa()["_meta"]
    assert meta["hidden"] is True
    assert meta["lang"] == "en-XA"
    assert meta["fallback"] == "en"


def _iter_string_pairs(en: dict, xa: dict):
    """Yield ``(key, en_value, xa_value)`` for every leaf string, descending
    into plural objects (skipping ``_meta`` and the ``_plural`` count-key)."""
    for key, en_val in en.items():
        if key == "_meta":
            continue
        xa_val = xa[key]
        if isinstance(en_val, str):
            yield key, en_val, xa_val
        elif isinstance(en_val, dict):
            for cat, en_cat in en_val.items():
                if cat == "_plural":
                    assert xa_val[cat] == en_cat, f"{key}: _plural key changed"
                    continue
                yield f"{key}.{cat}", en_cat, xa_val[cat]


def test_every_value_is_pseudo_transformed() -> None:
    """No value survives as untouched plain ASCII: each is wrapped in the
    ``[!! … !!]`` delimiters, differs from the English source, and carries at
    least one non-ASCII accented glyph. No ⟦ ⟧ marker leaks in."""
    en, xa = _en(), _en_xa()
    untouched: list[str] = []
    for key, en_val, xa_val in _iter_string_pairs(en, xa):
        if not en_val:  # empty strings have nothing to translate
            assert xa_val == en_val
            continue
        if not (
            xa_val.startswith(gen.OPEN_DELIM)
            and xa_val.endswith(gen.CLOSE_DELIM)
            and xa_val != en_val
            and any(ord(ch) > 127 for ch in xa_val)
        ):
            untouched.append(key)
        assert MARKER_OPEN not in xa_val and MARKER_CLOSE not in xa_val, (
            f"{key}: missing-key marker leaked into a pseudo value"
        )
    assert not untouched, f"values left untransformed (plain ASCII): {untouched}"


def test_placeholders_and_html_preserved_verbatim() -> None:
    """``{placeholder}`` tokens and ``<html>`` tags are never accented, so the
    pseudo runtime interpolates and renders markup exactly like English."""
    en, xa = _en(), _en_xa()
    for key, en_val, xa_val in _iter_string_pairs(en, xa):
        for token in _PLACEHOLDER.findall(en_val):
            assert token in xa_val, f"{key}: placeholder {token!r} not preserved"
        for tag in _HTML_TAG.findall(en_val):
            assert tag in xa_val, f"{key}: html tag {tag!r} not preserved"


def test_padding_expands_width_by_about_40_percent() -> None:
    """A representative string gains ~40 % width from the accented padding
    run (the worst-case width the overlay guard must survive)."""
    body = "Warming up the vocal cords"
    out = gen.pseudo(body)
    inner = out[len(gen.OPEN_DELIM) : -len(gen.CLOSE_DELIM)]
    accented, _, pad = inner.rpartition(" ")
    assert len(pad) == round(len(accented) * gen.PAD_RATIO)
    assert not _ASCII_LETTER.search(pad), "padding must be all-accented, no ASCII"


# ---------------------------------------------------------------------------
# AC2 — en-XA is absent from SUPPORTED_LANGS / the picker, yet loadable
# ---------------------------------------------------------------------------


def test_en_xa_absent_from_supported_langs() -> None:
    """The pseudo-locale never enters SUPPORTED_LANGS (so the Settings picker,
    which derives from it, never lists it) — the shipped set stays the six."""
    langs = i18n.discover_langs(WEBUI_I18N)
    assert "en-XA" not in langs
    assert set(langs) == {"en", "zh-CN", "de", "hu", "uk", "pt-BR"}
    assert "en-XA" not in i18n.SUPPORTED_LANGS


def test_en_xa_is_still_loadable_by_load_catalog() -> None:
    """Being hidden from discovery does NOT make it unloadable: a served
    ``?lang``/host-injected boot can still read the catalog by tag."""
    i18n.clear_catalog_cache()
    cat = i18n.load_catalog("en-XA", catalog_directory=WEBUI_I18N)
    assert cat.get("_meta", {}).get("lang") == "en-XA"
    assert cat["chrome.close"].startswith(gen.OPEN_DELIM)


def test_hidden_flag_excludes_only_hidden_catalogs(tmp_path: Path) -> None:
    """``discover_langs`` honours ``_meta.hidden`` generically: a normal
    catalog is discovered, a hidden one is not."""
    (tmp_path / "en.json").write_text('{"_meta":{"lang":"en"}}', encoding="utf-8")
    (tmp_path / "de.json").write_text('{"_meta":{"lang":"de"}}', encoding="utf-8")
    (tmp_path / "en-XA.json").write_text(
        '{"_meta":{"lang":"en-XA","hidden":true}}', encoding="utf-8"
    )
    langs = i18n.discover_langs(tmp_path)
    assert "de" in langs
    assert "en-XA" not in langs


@pytest.mark.parametrize("hidden_value", [False, None])
def test_non_hidden_meta_is_discovered(tmp_path: Path, hidden_value) -> None:
    meta = {"lang": "xx"}
    if hidden_value is not None:
        meta["hidden"] = hidden_value
    (tmp_path / "xx.json").write_text(
        json.dumps({"_meta": meta}), encoding="utf-8"
    )
    assert "xx" in i18n.discover_langs(tmp_path)
