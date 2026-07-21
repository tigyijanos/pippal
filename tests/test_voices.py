from __future__ import annotations

from pathlib import Path

import pytest

from pippal import voices


class TestVoiceUrlBase:
    def test_en_us(self):
        v: voices.PiperVoice = {
            "id": "en_US-ljspeech-high", "lang": "en_US",
            "name": "ljspeech", "quality": "high", "label": "x",
        }
        assert voices.voice_url_base(v) == (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "en/en_US/ljspeech/high/"
        )

    def test_hu_hu(self):
        v: voices.PiperVoice = {
            "id": "hu_HU-anna-medium", "lang": "hu_HU",
            "name": "anna", "quality": "medium", "label": "x",
        }
        assert voices.voice_url_base(v) == (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "hu/hu_HU/anna/medium/"
        )


def test_voice_filename():
    v: voices.PiperVoice = {
        "id": "en_US-ljspeech-high", "lang": "en_US",
        "name": "ljspeech", "quality": "high", "label": "x",
    }
    assert voices.voice_filename(v) == "en_US-ljspeech-high.onnx"


class TestCatalogLicenseHygiene:
    """#157: NC / research-only voices must not be offered; the new
    public-domain EN default must be present."""

    def test_nc_and_research_voices_not_offered(self):
        ids = {v["id"] for v in voices.KNOWN_VOICES}
        assert "en_US-ryan-high" not in ids
        assert "en_US-ryan-medium" not in ids
        assert "en_US-lessac-high" not in ids

    def test_public_domain_default_is_offered(self):
        ids = {v["id"] for v in voices.KNOWN_VOICES}
        assert "en_US-ljspeech-high" in ids

    def test_preferred_en_default_is_ljspeech(self):
        assert voices.PREFERRED_DEFAULT_VOICE["en"] == "en_US-ljspeech-high"


def test_is_installed_voice_requires_model_and_sidecar(tmp_path: Path):
    (tmp_path / "ready.onnx").write_bytes(b"model")
    (tmp_path / "ready.onnx.json").write_text("{}", encoding="utf-8")
    (tmp_path / "orphan.onnx").write_bytes(b"model")

    assert voices.is_installed_voice("ready.onnx", voices_dir=tmp_path) is True
    assert voices.is_installed_voice("orphan.onnx", voices_dir=tmp_path) is False
    assert voices.is_installed_voice("(no voice installed)", voices_dir=tmp_path) is False
    assert voices.is_installed_voice("../ready.onnx", voices_dir=tmp_path) is False


class TestKnownVoicesShape:
    def test_required_keys(self):
        for v in voices.KNOWN_VOICES:
            assert {"id", "lang", "name", "quality", "label"} <= set(v.keys())

    def test_locale_format(self):
        for v in voices.KNOWN_VOICES:
            # `xx_XX` shape (lower_UPPER)
            lang = v["lang"]
            parts = lang.split("_")
            assert len(parts) == 2
            assert parts[0].islower()
            assert parts[1].isupper()


class TestLangToPiper:
    def test_hungarian_maps_to_hu_hu(self):
        assert voices.LANG_TO_PIPER["Hungarian"] == ["hu_HU"]

    def test_english_lists_us_then_gb(self):
        assert voices.LANG_TO_PIPER["English"] == ["en_US", "en_GB"]


class TestFindPiperVoiceForLanguage:
    def test_finds_matching_voice(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Stub installed_voices() to a controlled list. NOTE (#157):
        # ``en_US-ryan-high`` is no longer in the offered catalog, but an
        # already-installed copy must still resolve/play — this asserts that
        # resolution keys off installed files, not catalog membership.
        monkeypatch.setattr(
            voices, "installed_voices",
            lambda: ["hu_HU-anna-medium.onnx", "en_US-ryan-high.onnx"],
        )
        assert voices.find_piper_voice_for_language("Hungarian") == "hu_HU-anna-medium.onnx"
        assert voices.find_piper_voice_for_language("English") == "en_US-ryan-high.onnx"

    def test_returns_none_when_unmatched(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(voices, "installed_voices", lambda: ["en_US-ryan-high.onnx"])
        assert voices.find_piper_voice_for_language("Hungarian") is None

    def test_unknown_language(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(voices, "installed_voices", lambda: ["en_US-ryan-high.onnx"])
        assert voices.find_piper_voice_for_language("Klingon") is None

    def test_priority_order(self, monkeypatch: pytest.MonkeyPatch):
        # When both en_US and en_GB are installed, en_US wins (priority order).
        monkeypatch.setattr(
            voices, "installed_voices",
            lambda: ["en_GB-alan-medium.onnx", "en_US-ryan-high.onnx"],
        )
        assert voices.find_piper_voice_for_language("English") == "en_US-ryan-high.onnx"
