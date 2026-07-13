from __future__ import annotations

import json
from pathlib import Path

from pippal import config, voices

LEGACY_DEFAULT_VOICE = "en_US-ryan-high.onnx"


def _use_empty_voices_dir(monkeypatch, tmp_path: Path) -> Path:
    voices_dir = tmp_path / "voices"
    monkeypatch.setattr(config, "VOICES_DIR", voices_dir)
    return voices_dir


def _install_voice(voices_dir: Path, filename: str) -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / filename).write_bytes(b"model")
    (voices_dir / f"{filename}.json").write_text("{}", encoding="utf-8")


class TestDefaultConfig:
    def test_has_required_keys(self):
        # Built-in keys only — extension-supplied config keys are
        # contributed by their plugin via ``plugins.register_defaults``,
        # not part of this static dict.
        for key in (
            "engine", "voice",
            "length_scale", "noise_scale",
            "hotkey_speak", "hotkey_stop",
        ):
            assert key in config.DEFAULT_CONFIG, f"missing default for {key}"

    def test_engine_is_piper_by_default(self):
        assert config.DEFAULT_CONFIG["engine"] == "piper"

    def test_brand_name_is_pippal(self):
        assert config.DEFAULT_CONFIG["brand_name"] == "PipPal"


class TestLoadConfig:
    # `load_config` returns the LAYERED defaults (DEFAULT_CONFIG plus
    # whatever any optional extension plugin has registered). We compare
    # against `_layered_defaults()` rather than `DEFAULT_CONFIG` so the
    # tests stay correct in extension-loaded environments.

    def test_returns_defaults_when_file_missing(self, tmp_path: Path, monkeypatch):
        _use_empty_voices_dir(monkeypatch, tmp_path)
        cfg = config.load_config(path=tmp_path / "nope.json")
        assert cfg == config._layered_defaults()
        # Result is a fresh dict, not the same object.
        assert cfg is not config.DEFAULT_CONFIG

    def test_overlays_user_values_on_defaults(self, tmp_path: Path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"voice": "custom.onnx"}), encoding="utf-8")
        cfg = config.load_config(path=p)
        assert cfg["voice"] == "custom.onnx"
        # Other keys still default
        assert cfg["engine"] == config.DEFAULT_CONFIG["engine"]

    def test_invalid_json_falls_back_to_defaults(self, tmp_path: Path, monkeypatch):
        _use_empty_voices_dir(monkeypatch, tmp_path)
        p = tmp_path / "config.json"
        p.write_text("{not valid", encoding="utf-8")
        cfg = config.load_config(path=p)
        assert cfg == config._layered_defaults()

    def test_non_dict_payload_falls_back(self, tmp_path: Path, monkeypatch):
        _use_empty_voices_dir(monkeypatch, tmp_path)
        p = tmp_path / "config.json"
        p.write_text(json.dumps(["a", "b"]), encoding="utf-8")
        cfg = config.load_config(path=p)
        assert cfg == config._layered_defaults()


class TestLegacyImplicitVoiceCompatibility:
    def test_empty_config_uses_complete_legacy_voice_when_default_is_missing(
        self, tmp_path: Path, monkeypatch
    ):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        config_path = tmp_path / "config.json"
        config_path.write_text("{}", encoding="utf-8")

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == LEGACY_DEFAULT_VOICE

    def test_missing_config_uses_complete_legacy_voice_when_default_is_missing(
        self, tmp_path: Path, monkeypatch
    ):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)

        loaded = config.load_config(path=tmp_path / "missing.json")

        assert loaded["voice"] == LEGACY_DEFAULT_VOICE

    def test_invalid_config_uses_complete_legacy_voice_when_default_is_missing(
        self, tmp_path: Path, monkeypatch
    ):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        config_path = tmp_path / "config.json"
        config_path.write_text("{not valid", encoding="utf-8")

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == LEGACY_DEFAULT_VOICE

    def test_non_dict_config_uses_complete_legacy_voice_when_default_is_missing(
        self, tmp_path: Path, monkeypatch
    ):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        config_path = tmp_path / "config.json"
        config_path.write_text("[]", encoding="utf-8")

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == LEGACY_DEFAULT_VOICE

    def test_explicit_voice_always_wins(self, tmp_path: Path, monkeypatch):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"voice": "custom.onnx"}), encoding="utf-8")

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == "custom.onnx"

    def test_complete_current_default_prevents_legacy_fallback(
        self, tmp_path: Path, monkeypatch
    ):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        _install_voice(voices_dir, str(config.DEFAULT_CONFIG["voice"]))
        config_path = tmp_path / "config.json"
        config_path.write_text("{}", encoding="utf-8")

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == config.DEFAULT_CONFIG["voice"]

    def test_incomplete_legacy_voice_does_not_qualify(self, tmp_path: Path, monkeypatch):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        voices_dir.mkdir(parents=True)
        (voices_dir / LEGACY_DEFAULT_VOICE).write_bytes(b"model")
        config_path = tmp_path / "config.json"
        config_path.write_text("{}", encoding="utf-8")

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == config.DEFAULT_CONFIG["voice"]

    def test_runtime_voice_root_is_used(self, tmp_path: Path, monkeypatch):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        host_voices_dir = tmp_path / "host-voices"
        _install_voice(host_voices_dir, str(config.DEFAULT_CONFIG["voice"]))
        monkeypatch.setattr(voices, "VOICES_DIR", host_voices_dir)

        loaded = config.load_config(path=tmp_path / "missing.json")

        assert loaded["voice"] == LEGACY_DEFAULT_VOICE

    def test_load_does_not_modify_valid_config(self, tmp_path: Path, monkeypatch):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        config_path = tmp_path / "config.json"
        original = b'{\n  "language": "en"\n}\n'
        config_path.write_bytes(original)

        loaded = config.load_config(path=config_path)

        assert loaded["voice"] == LEGACY_DEFAULT_VOICE
        assert config_path.read_bytes() == original

    def test_save_persists_selected_legacy_fallback(self, tmp_path: Path, monkeypatch):
        voices_dir = _use_empty_voices_dir(monkeypatch, tmp_path)
        _install_voice(voices_dir, LEGACY_DEFAULT_VOICE)
        config_path = tmp_path / "config.json"
        config_path.write_text("{}", encoding="utf-8")

        loaded = config.load_config(path=config_path)
        loaded["language"] = "de"
        config.save_config(loaded, path=config_path)

        assert json.loads(config_path.read_text("utf-8"))["voice"] == LEGACY_DEFAULT_VOICE


class TestSaveConfig:
    def test_round_trip(self, tmp_path: Path):
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["voice"] = "new.onnx"
        config.save_config(cfg, path=p)
        loaded = config.load_config(path=p)
        assert loaded["voice"] == "new.onnx"

    def test_writes_unicode(self, tmp_path: Path):
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["brand_name"] = "Pípal árvíztűrő"
        config.save_config(cfg, path=p)
        loaded = config.load_config(path=p)
        assert loaded["brand_name"] == "Pípal árvíztűrő"

    def test_atomic_replace_failure_keeps_original(self, tmp_path: Path,
                                                    monkeypatch):
        # If os.replace raises after the temp write, the original file
        # must still be intact (atomicity invariant). Pre-create a known
        # config, monkey-patch os.replace to raise, attempt to save a
        # new one, and verify the old contents survive.
        import os as _os

        p = tmp_path / "config.json"
        config.save_config({**config.DEFAULT_CONFIG, "voice": "v1.onnx"}, path=p)

        def boom(*_a, **_kw):
            raise OSError("disk full")

        monkeypatch.setattr(_os, "replace", boom)
        try:
            config.save_config({**config.DEFAULT_CONFIG, "voice": "v2.onnx"},
                                path=p)
        except OSError:
            pass  # fine — atomic write surfaces the error
        loaded = config.load_config(path=p)
        assert loaded["voice"] == "v1.onnx"

    def test_unknown_extension_key_survives_round_trip(self, tmp_path: Path):
        # Regression for the missing-DEFAULT_CONFIG-key bug: unknown
        # extension-owned keys must survive even when they are not in
        # DEFAULT_CONFIG.
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["extension_feature_key"] = "warm"
        config.save_config(cfg, path=p)
        loaded = config.load_config(path=p)
        assert loaded["extension_feature_key"] == "warm"


class TestLayeredSave:
    """Stage 1.G: save_config writes only the keys whose value differs
    from the current layered defaults. Defaults that round-trip
    unchanged stay out of config.json so the file stays small and a
    plugin uninstall doesn't strand its defaults on disk."""

    def test_unchanged_default_is_not_persisted(self, tmp_path: Path):
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)  # identical to defaults
        config.save_config(cfg, path=p)
        # File contains an empty object — no overrides to record.
        assert json.loads(p.read_text("utf-8")) == {}
        # But load still returns the full effective config.
        loaded = config.load_config(path=p)
        assert loaded["engine"] == config.DEFAULT_CONFIG["engine"]

    def test_only_modified_keys_are_persisted(self, tmp_path: Path):
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["voice"] = "custom.onnx"
        cfg["extension_feature_key"] = "warm"
        config.save_config(cfg, path=p)
        on_disk = json.loads(p.read_text("utf-8"))
        assert on_disk == {
            "voice": "custom.onnx",
            "extension_feature_key": "warm",
        }

    def test_unknown_keys_preserved_through_save(self, tmp_path: Path):
        # If an extension once wrote a key we don't recognise because
        # it is currently uninstalled, save_config must keep it so a
        # later reinstall finds the value still there. Without this
        # protection, a Settings save would silently delete extension
        # state.
        p = tmp_path / "config.json"
        cfg = dict(config.DEFAULT_CONFIG)
        cfg["custom_extension_key"] = "user-set value"
        config.save_config(cfg, path=p)
        on_disk = json.loads(p.read_text("utf-8"))
        assert on_disk["custom_extension_key"] == "user-set value"
