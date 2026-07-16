from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pippal.engines.piper import PiperBackend
from pippal.piper_speakers import load_speaker_id_map, valid_speaker_id
from pippal.web_ui import bridge as bridge_mod
from pippal.web_ui import bridge_piper_speakers as speaker_bridge_mod
from pippal.web_ui.bridge import PipPalBridge

VOICE = "en_US-libritts-high.onnx"


def _install_test_voice(root: Path, speakers: dict[str, int]) -> None:
    (root / VOICE).write_bytes(b"model")
    (root / f"{VOICE}.json").write_text(
        json.dumps({"num_speakers": len(speakers), "speaker_id_map": speakers}),
        encoding="utf-8",
    )


def test_speaker_metadata_and_ids_fail_closed_on_malformed_input(
    tmp_path: Path,
) -> None:
    assert load_speaker_id_map("../outside.onnx", voices_dir=tmp_path) == {}

    metadata = tmp_path / f"{VOICE}.json"
    metadata.write_text("[" * 1200 + "]" * 1200, encoding="utf-8")
    assert load_speaker_id_map(VOICE, voices_dir=tmp_path) == {}

    _install_test_voice(tmp_path, {"19": 0, "26": 1})
    assert valid_speaker_id(VOICE, "9" * 5000, voices_dir=tmp_path) is None


def test_piper_passes_saved_speaker_for_multi_speaker_voice(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from pippal.engines import piper as piper_mod

    _install_test_voice(tmp_path, {"19": 0, "26": 1, "39": 2})
    exe = tmp_path / "piper.exe"
    exe.write_bytes(b"exe")
    calls: list[list[str]] = []

    def _run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        Path(command[command.index("--output_file") + 1]).write_bytes(b"wav")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(piper_mod, "VOICES_DIR", tmp_path)
    monkeypatch.setattr(piper_mod, "PIPER_DIR", tmp_path)
    monkeypatch.setattr(piper_mod, "PIPER_EXE", exe)
    monkeypatch.setattr(piper_mod.subprocess, "run", _run)

    backend = PiperBackend({"voice": VOICE, "piper_speaker_ids": {VOICE: 2}})
    assert backend.synthesize("hello", tmp_path / "out.wav") is True
    assert calls[0][calls[0].index("--speaker") + 1] == "2"


def test_piper_ignores_saved_speaker_for_single_speaker_voice(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from pippal.engines import piper as piper_mod

    _install_test_voice(tmp_path, {"default": 0})
    exe = tmp_path / "piper.exe"
    exe.write_bytes(b"exe")
    calls: list[list[str]] = []

    def _run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        Path(command[command.index("--output_file") + 1]).write_bytes(b"wav")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(piper_mod, "VOICES_DIR", tmp_path)
    monkeypatch.setattr(piper_mod, "PIPER_DIR", tmp_path)
    monkeypatch.setattr(piper_mod, "PIPER_EXE", exe)
    monkeypatch.setattr(piper_mod.subprocess, "run", _run)

    backend = PiperBackend({"voice": VOICE, "piper_speaker_ids": {VOICE: 99}})
    assert backend.synthesize("hello", tmp_path / "out.wav") is True
    assert "--speaker" not in calls[0]


def test_piper_ignores_invalid_saved_speaker_for_current_voice(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from pippal.engines import piper as piper_mod

    _install_test_voice(tmp_path, {"19": 0, "26": 1})
    exe = tmp_path / "piper.exe"
    exe.write_bytes(b"exe")
    calls: list[list[str]] = []

    def _run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(command)
        Path(command[command.index("--output_file") + 1]).write_bytes(b"wav")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(piper_mod, "VOICES_DIR", tmp_path)
    monkeypatch.setattr(piper_mod, "PIPER_DIR", tmp_path)
    monkeypatch.setattr(piper_mod, "PIPER_EXE", exe)
    monkeypatch.setattr(piper_mod.subprocess, "run", _run)

    backend = PiperBackend({"voice": VOICE, "piper_speaker_ids": {VOICE: 99}})
    assert backend.synthesize("hello", tmp_path / "out.wav") is True
    assert "--speaker" not in calls[0]


def test_bridge_searches_installed_speakers_without_returning_all_904(
    tmp_path: Path, monkeypatch: Any
) -> None:
    speakers = {str(1000 + index): index for index in range(904)}
    _install_test_voice(tmp_path, speakers)
    monkeypatch.setattr(speaker_bridge_mod.paths, "VOICES_DIR", tmp_path)
    config = {"piper_speaker_ids": {VOICE: 26}}
    bridge = PipPalBridge(SimpleNamespace(reset_backend=lambda: None), config)

    state = bridge.get_piper_speakers(VOICE, "1026")

    assert state["total"] == 904
    assert state["selected"] == 26
    assert state["speakers"] == [{"id": 26, "label": "1026"}]
    assert state["truncated"] is False


def test_bridge_keeps_selected_speaker_visible_outside_first_page(
    tmp_path: Path, monkeypatch: Any
) -> None:
    speakers = {str(1000 + index): index for index in range(904)}
    _install_test_voice(tmp_path, speakers)
    monkeypatch.setattr(speaker_bridge_mod.paths, "VOICES_DIR", tmp_path)
    bridge = PipPalBridge(
        SimpleNamespace(reset_backend=lambda: None),
        {"piper_speaker_ids": {VOICE: 0}},
    )

    state = bridge.get_piper_speakers(VOICE, "", 612)

    assert state["selected"] == 612
    assert len(state["speakers"]) == 50
    assert state["speakers"][0] == {"id": 612, "label": "1612"}

    invalid = bridge.get_piper_speakers(VOICE, "", 999)
    assert invalid["selected"] is None


def test_bridge_persists_valid_speaker_for_voice_and_resets_backend(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _install_test_voice(tmp_path, {"19": 0, "26": 1, "39": 2})
    monkeypatch.setattr(speaker_bridge_mod.paths, "VOICES_DIR", tmp_path)
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(bridge_mod, "save_config", lambda value: saved.append(dict(value)))

    class _Engine:
        reset_calls = 0

        def reset_backend(self) -> None:
            self.reset_calls += 1

    engine = _Engine()
    config = {"voice": VOICE, "piper_speaker_ids": {"other.onnx": 4}}
    bridge = PipPalBridge(engine, config)

    result = bridge.set_piper_speaker(VOICE, 2)

    assert result["ok"] is True
    assert config["piper_speaker_ids"] == {"other.onnx": 4, VOICE: 2}
    assert saved[-1]["piper_speaker_ids"] == config["piper_speaker_ids"]
    assert engine.reset_calls == 1


def test_bridge_rejects_invalid_speaker_without_mutating_config(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _install_test_voice(tmp_path, {"19": 0, "26": 1})
    monkeypatch.setattr(speaker_bridge_mod.paths, "VOICES_DIR", tmp_path)
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(bridge_mod, "save_config", lambda value: saved.append(dict(value)))
    engine = SimpleNamespace(reset_backend=lambda: saved.append({"reset": True}))
    config = {"voice": VOICE, "piper_speaker_ids": {VOICE: 0}}
    bridge = PipPalBridge(engine, config)

    result = bridge.set_piper_speaker(VOICE, 99)
    float_result = bridge.set_piper_speaker(VOICE, 1.5)

    assert result == {"ok": False, "code": "invalid_speaker"}
    assert float_result == {"ok": False, "code": "invalid_speaker"}
    assert config == {"voice": VOICE, "piper_speaker_ids": {VOICE: 0}}
    assert saved == []
