"""Unit oracle for T-103: the ``language`` config key, the standalone
language resolver, and the ``get_config`` language view.

These assert an INDEPENDENT oracle (the design-doc §5.3 precedence rules
and the flat-config round-trip contract), never mirror the implementation.
The full i18n engine (T-101/T-102) supersedes ``i18n_fallback`` at runtime;
this ticket only guarantees the config seam + picker wiring stand alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pippal import config
from pippal import i18n_fallback as fb
from pippal.web_ui import i18n_view
from pippal.web_ui.i18n_view import language_config_view

_CANONICAL = ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]


class TestLanguageConfigKey:
    def test_default_config_has_empty_language(self):
        # "" is the Auto/system sentinel (design §5.3); key must be present.
        assert "language" in config.DEFAULT_CONFIG
        assert config.DEFAULT_CONFIG["language"] == ""

    def test_language_round_trips_to_disk(self, tmp_path: Path):
        # Picking a concrete language persists it via the existing seam.
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["language"] = "de"
        config.save_config(cfg, path=p)
        assert json.loads(p.read_text("utf-8"))["language"] == "de"
        assert config.load_config(path=p)["language"] == "de"

    def test_auto_is_the_empty_default(self, tmp_path: Path):
        # Auto == default "" → layered-save drops it (no override on disk),
        # and the EFFECTIVE (loaded) config still reports language == "".
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["language"] = "de"
        config.save_config(cfg, path=p)
        assert config.load_config(path=p)["language"] == "de"

        cfg["language"] = ""  # switch back to Auto
        config.save_config(cfg, path=p)
        assert "language" not in json.loads(p.read_text("utf-8"))
        assert config.load_config(path=p)["language"] == ""


class TestResolveLanguage:
    def test_explicit_supported_pick_wins(self):
        # An explicit user pick is permanent — system locale is ignored.
        assert fb.resolve_language("de", system_locale="uk-UA") == "de"

    def test_absent_follows_supported_system_locale(self):
        # Auto ("") + a supported system locale → that language.
        assert fb.resolve_language("", system_locale="de-DE") == "de"
        assert fb.resolve_language("", system_locale="hu-HU") == "hu"

    def test_absent_unsupported_system_falls_back_to_en(self):
        assert fb.resolve_language("", system_locale="fr-FR") == "en"
        assert fb.resolve_language("", system_locale="") == "en"

    def test_bare_tag_maps_to_shipped_variant(self):
        # Bare "pt"/"zh" map onto the concrete catalogs we ship (§1/§5.3).
        assert fb.resolve_language("", system_locale="pt") == "pt-BR"
        assert fb.resolve_language("", system_locale="zh") == "zh-CN"
        assert fb.resolve_language("", system_locale="zh-Hans-CN") == "zh-CN"

    def test_unsupported_explicit_pick_falls_through_to_system(self):
        # A stale/unsupported explicit tag is treated as Auto, not honoured.
        assert fb.resolve_language("xx", system_locale="uk-UA") == "uk"

    def test_absent_uses_the_monkeypatched_system_source(self, monkeypatch):
        # "default absent → follows the (mocked) system locale" without
        # passing system_locale explicitly: the OS source is monkeypatched.
        monkeypatch.setattr(fb, "_system_locale", lambda: "uk-UA")
        assert fb.resolve_language("") == "uk"
        monkeypatch.setattr(fb, "_system_locale", lambda: "fr-FR")
        assert fb.resolve_language("") == "en"


class TestSupportedLangs:
    def test_six_core_languages_in_order(self):
        assert fb.SUPPORTED_LANGS == ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]

    def test_native_names_are_endonyms(self):
        assert fb.native_name("en") == "English"
        assert fb.native_name("de") == "Deutsch"
        assert fb.native_name("hu") == "Magyar"
        assert fb.native_name("zh-CN") == "简体中文"
        assert fb.native_name("uk") == "Українська"
        assert fb.native_name("pt-BR") == "Português (Brasil)"

    def test_unknown_tag_names_itself(self):
        # A not-yet-named 7th language still appears (labelled by its tag).
        assert fb.native_name("xx") == "xx"


class TestLanguageConfigView:
    def test_view_adds_resolved_and_supported(self):
        cfg = dict(config.DEFAULT_CONFIG)
        view = language_config_view(cfg)
        # Raw stored value preserved; resolved + options added.
        assert view["language"] == ""
        assert view["language_resolved"] in fb.SUPPORTED_LANGS
        assert [o["tag"] for o in view["supported_languages"]] == fb.SUPPORTED_LANGS
        assert {"tag": "de", "name": "Deutsch"} in view["supported_languages"]

    def test_explicit_language_is_resolved_verbatim(self):
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["language"] = "de"
        view = language_config_view(cfg)
        assert view["language"] == "de"
        assert view["language_resolved"] == "de"

    def test_view_does_not_mutate_input(self):
        cfg = dict(config.DEFAULT_CONFIG)
        language_config_view(cfg)
        assert "language_resolved" not in cfg
        assert "supported_languages" not in cfg

    def test_picker_order_is_canonical_regardless_of_resolver(self, monkeypatch):
        # The real engine (T-102) ships SUPPORTED_LANGS alphabetically; the
        # view must still emit the canonical design order so the picker (and
        # its e2e order assert) is stable across the T-102 merge.
        monkeypatch.setattr(
            i18n_view, "SUPPORTED_LANGS", ["de", "en", "hu", "pt-BR", "uk", "zh-CN"]
        )
        view = language_config_view(dict(config.DEFAULT_CONFIG))
        assert [o["tag"] for o in view["supported_languages"]] == _CANONICAL

    def test_unknown_tag_is_appended_sorted(self, monkeypatch):
        # A future 7th/8th language (not in the canonical list) is appended
        # after the canonical set, sorted among themselves.
        monkeypatch.setattr(
            i18n_view, "SUPPORTED_LANGS", ["zz", "de", "en", "aa"]
        )
        view = language_config_view(dict(config.DEFAULT_CONFIG))
        assert [o["tag"] for o in view["supported_languages"]] == [
            "en", "de", "aa", "zz",
        ]


@pytest.mark.parametrize(
    "system,expected",
    [
        ("de-DE", "de"),
        ("uk-UA", "uk"),
        ("pt-PT", "pt-BR"),
        ("es-ES", "en"),
    ],
)
def test_resolve_language_table(system: str, expected: str):
    assert fb.resolve_language("", system_locale=system) == expected
