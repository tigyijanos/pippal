from __future__ import annotations

import json
from pathlib import Path

import pytest

from pippal import onboarding


def _install_voice(voices_dir: Path, filename: str) -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / filename).write_bytes(b"voice")
    (voices_dir / f"{filename}.json").write_text("{}", encoding="utf-8")


def test_missing_activation_state_is_incomplete(tmp_path: Path) -> None:
    state_path = tmp_path / "first_run_activation.json"

    state = onboarding.load_activation_state(path=state_path)

    assert state.is_complete is False
    assert onboarding.should_show_activation_panel(path=state_path) is True


def test_mark_activation_complete_writes_contract_payload(tmp_path: Path) -> None:
    state_path = tmp_path / "first_run_activation.json"

    state = onboarding.mark_activation_complete(
        "sample",
        path=state_path,
        completed_at="2026-05-14T18:00:00Z",
    )

    assert state.is_complete is True
    assert json.loads(state_path.read_text("utf-8")) == {
        "first_run_activation": {
            "completed_at": "2026-05-14T18:00:00Z",
            "completed_with": "sample",
            "last_failure": None,
        }
    }
    assert onboarding.should_show_activation_panel(path=state_path) is False


def test_rejects_unknown_completion_method(tmp_path: Path) -> None:
    state_path = tmp_path / "first_run_activation.json"

    with pytest.raises(ValueError, match="completed_with"):
        onboarding.mark_activation_complete("dialog_close", path=state_path)

    assert state_path.exists() is False


def test_record_activation_failure_does_not_complete(tmp_path: Path) -> None:
    state_path = tmp_path / "first_run_activation.json"

    state = onboarding.record_activation_failure("No sound", path=state_path)

    assert state.is_complete is False
    assert state.last_failure == "No sound"
    assert onboarding.load_activation_state(path=state_path).last_failure == "No sound"


def test_selected_text_completion_clears_previous_failure(tmp_path: Path) -> None:
    state_path = tmp_path / "first_run_activation.json"
    onboarding.record_activation_failure(
        onboarding.SELECTED_TEXT_CAPTURE_FAILURE,
        path=state_path,
    )

    state = onboarding.mark_activation_complete(
        "selected_text",
        path=state_path,
        completed_at="2026-05-14T18:05:00Z",
    )

    assert state.is_complete is True
    assert state.completed_with == "selected_text"
    assert state.last_failure is None
    assert onboarding.should_show_activation_panel(path=state_path) is False


def test_activation_failure_recovery_message_includes_retry_path() -> None:
    message = onboarding.activation_failure_recovery_message(
        onboarding.SELECTED_TEXT_CAPTURE_FAILURE,
        "Win+Shift+R",
    )

    assert message is not None
    assert onboarding.SELECTED_TEXT_CAPTURE_FAILURE in message
    assert "Win+Shift+R" in message
    assert "Play sample" in message


def test_format_hotkey_uses_user_facing_names() -> None:
    assert onboarding.format_hotkey("windows+shift+r") == "Win+Shift+R"
    assert onboarding.format_hotkey("control + alt + delete") == "Ctrl+Alt+Delete"
    assert onboarding.format_hotkey("") == "Not configured"


def test_default_piper_voice_matches_core_default_config() -> None:
    voice = onboarding.default_piper_voice()

    assert f"{voice['id']}.onnx" == onboarding.DEFAULT_CONFIG["voice"]


def test_readiness_reports_missing_piper(tmp_path: Path) -> None:
    voices_dir = tmp_path / "voices"

    readiness = onboarding.build_activation_readiness(
        {
            "engine": "piper",
            "voice": "en_US-ljspeech-high.onnx",
            "hotkey_speak": "windows+shift+r",
        },
        piper_exe=tmp_path / "missing" / "piper.exe",
        voices_dir=voices_dir,
    )

    assert readiness.status == onboarding.READINESS_MISSING_PIPER
    assert readiness.can_play_sample is False
    assert readiness.hotkey_label == "Win+Shift+R"
    assert "Reading is paused" in readiness.message


def test_readiness_reports_missing_voice(tmp_path: Path) -> None:
    piper_exe = tmp_path / "piper.exe"
    piper_exe.write_bytes(b"exe")
    voices_dir = tmp_path / "voices"

    readiness = onboarding.build_activation_readiness(
        {
            "engine": "piper",
            "voice": "en_US-ljspeech-high.onnx",
            "hotkey_speak": "windows+shift+r",
        },
        piper_exe=piper_exe,
        voices_dir=voices_dir,
    )

    assert readiness.status == onboarding.READINESS_MISSING_VOICE
    assert readiness.voice_label == "not installed"
    assert readiness.can_play_sample is False


def test_readiness_reports_ready_with_installed_voice(tmp_path: Path) -> None:
    piper_exe = tmp_path / "piper.exe"
    piper_exe.write_bytes(b"exe")
    voices_dir = tmp_path / "voices"
    _install_voice(voices_dir, "en_US-ljspeech-high.onnx")

    readiness = onboarding.build_activation_readiness(
        {
            "engine": "piper",
            "voice": "en_US-ljspeech-high.onnx",
            "hotkey_speak": "windows+shift+r",
        },
        piper_exe=piper_exe,
        voices_dir=voices_dir,
    )

    assert readiness.status == onboarding.READINESS_READY
    assert readiness.voice_label == "en_US-ljspeech-high"
    assert readiness.hotkey_label == "Win+Shift+R"
    assert readiness.can_play_sample is True


def test_already_installed_removed_voice_still_plays(tmp_path: Path) -> None:
    """A voice no longer offered in the catalog (#157 removed ryan/lessac)
    must keep working when the user already has it installed and configured.
    The readiness/play path resolves the config voice filename directly and
    must NOT gate on catalog membership."""
    from pippal import voices

    removed_voice = "en_US-ryan-high.onnx"
    # Guard: this voice is intentionally absent from the offered catalog.
    assert removed_voice.removesuffix(".onnx") not in {
        v["id"] for v in voices.KNOWN_VOICES
    }

    piper_exe = tmp_path / "piper.exe"
    piper_exe.write_bytes(b"exe")
    voices_dir = tmp_path / "voices"
    _install_voice(voices_dir, removed_voice)

    readiness = onboarding.build_activation_readiness(
        {
            "engine": "piper",
            "voice": removed_voice,
            "hotkey_speak": "windows+shift+r",
        },
        piper_exe=piper_exe,
        voices_dir=voices_dir,
    )

    assert readiness.status == onboarding.READINESS_READY
    assert readiness.voice_label == "en_US-ryan-high"
    assert readiness.can_play_sample is True


def test_default_engine_ready_requires_piper_exe_and_voice(tmp_path: Path) -> None:
    piper_exe = tmp_path / "piper.exe"
    voices_dir = tmp_path / "voices"

    assert onboarding.is_default_engine_ready(piper_exe=piper_exe, voices_dir=voices_dir) is False

    _install_voice(voices_dir, "en_US-ljspeech-high.onnx")

    assert onboarding.is_default_engine_ready(piper_exe=piper_exe, voices_dir=voices_dir) is False

    piper_exe.write_bytes(b"exe")

    assert onboarding.is_default_engine_ready(piper_exe=piper_exe, voices_dir=voices_dir) is True
