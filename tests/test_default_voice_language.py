"""First-run default voice matches the UI language (#154).

The onboarding "Install default voice" action must resolve a voice for the
active UI language, fall back to the curated English default when the catalog
has none, and the readiness copy must name that language instead of a
hardcoded "English".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pippal import onboarding, voices


@pytest.fixture(autouse=True)
def _restore_language():
    """Keep the module-global active language from leaking between tests."""
    from pippal import i18n

    original = i18n.get_language()
    try:
        yield
    finally:
        i18n.set_language(original)


# ---------------------------------------------------------------------------
# Resolver: UI language -> mapped catalog voice id
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("lang", "expected_id"),
    [
        ("en", "en_US-ryan-high"),
        ("de", "de_DE-thorsten-high"),
        ("hu", "hu_HU-anna-medium"),
        ("uk", "uk_UA-ukrainian_tts-medium"),
        ("zh-CN", "zh_CN-huayan-medium"),
        ("pt-BR", "pt_BR-faber-medium"),
    ],
)
def test_default_voice_for_language_maps_ui_language(lang: str, expected_id: str) -> None:
    voice = voices.default_voice_for_language(lang)
    assert voice is not None
    assert voice["id"] == expected_id


def test_every_preferred_default_voice_exists_in_catalog() -> None:
    ids = {v["id"] for v in voices.KNOWN_VOICES}
    for voice_id in voices.PREFERRED_DEFAULT_VOICE.values():
        assert voice_id in ids, voice_id


def test_absent_language_returns_none_for_english_fallback() -> None:
    # A language with no Piper voice in the catalog resolves to None so the
    # caller can fall back to the curated English default.
    assert voices.default_voice_for_language("ja") is None
    assert voices.default_voice_for_language("") is None
    assert voices.default_voice_for_language(None) is None


def test_derives_by_locale_prefix_without_override() -> None:
    # French has no override entry but is in the catalog by prefix.
    voice = voices.default_voice_for_language("fr")
    assert voice is not None
    assert voice["lang"] == "fr_FR"


# ---------------------------------------------------------------------------
# default_piper_voice() honours the active UI language, English fallback
# ---------------------------------------------------------------------------
def test_default_piper_voice_follows_active_language() -> None:
    with patch("pippal.onboarding.get_language", return_value="zh-CN"):
        voice = onboarding.default_piper_voice()
    assert voice["id"] == "zh_CN-huayan-medium"


def test_default_piper_voice_falls_back_to_english() -> None:
    with patch("pippal.onboarding.get_language", return_value="ja"):
        voice = onboarding.default_piper_voice()
    assert f"{voice['id']}.onnx" == onboarding.DEFAULT_CONFIG["voice"]


# ---------------------------------------------------------------------------
# Install request targets the mapped voice id (Tier-1 AC)
# ---------------------------------------------------------------------------
def test_install_default_voice_targets_language_voice() -> None:
    from pippal import i18n
    from pippal.web_ui.bridge import PipPalBridge

    i18n.set_language("zh-CN")
    bridge = PipPalBridge(MagicMock(), {})

    captured: dict[str, object] = {}

    def _fake_install(voice):
        captured["voice"] = voice
        return f"{voice['id']}.onnx"

    with patch("pippal.voice_install.install_piper_voice", side_effect=_fake_install):
        result = bridge.install_default_voice()

    assert captured["voice"]["id"] == "zh_CN-huayan-medium"
    assert result["installed"] == "zh_CN-huayan-medium.onnx"
    assert bridge.config["voice"] == "zh_CN-huayan-medium.onnx"


def test_install_default_voice_english_fallback_unchanged() -> None:
    from pippal import i18n
    from pippal.web_ui.bridge import PipPalBridge

    i18n.set_language("ja")  # no Piper voice -> English default
    bridge = PipPalBridge(MagicMock(), {})

    captured: dict[str, object] = {}

    def _fake_install(voice):
        captured["voice"] = voice
        return f"{voice['id']}.onnx"

    with patch("pippal.voice_install.install_piper_voice", side_effect=_fake_install):
        bridge.install_default_voice()

    assert f"{captured['voice']['id']}.onnx" == onboarding.DEFAULT_CONFIG["voice"]


# ---------------------------------------------------------------------------
# Onboarding copy is parameterised (no hardcoded "English")
# ---------------------------------------------------------------------------
def _missing_voice_readiness(tmp_path):
    piper_exe = tmp_path / "piper.exe"
    piper_exe.write_bytes(b"exe")
    return onboarding.build_activation_readiness(
        {
            "engine": "piper",
            "voice": "en_US-ryan-high.onnx",
            "hotkey_speak": "windows+shift+r",
        },
        piper_exe=piper_exe,
        voices_dir=tmp_path / "voices",
    )


def test_missing_voice_copy_is_byte_identical_for_english(tmp_path) -> None:
    with patch("pippal.onboarding.get_language", return_value="en"):
        readiness = _missing_voice_readiness(tmp_path)
    assert readiness.message == (
        "No local voice is installed yet. Install the default English voice "
        "so PipPal can speak offline. Download size: about 120 MB."
    )


def test_missing_voice_copy_names_the_language(tmp_path) -> None:
    with patch("pippal.onboarding.get_language", return_value="zh-CN"):
        readiness = _missing_voice_readiness(tmp_path)
    assert "中文" in readiness.message
    assert "English" not in readiness.message
