"""First-run nudges that don't depend on a working TTS engine.

When the user triggers a synth-driven action and no engine is
actually ready (no voice on disk for the selected backend), we can't
synthesise the standard reply — so we play a pre-recorded WAV that
walks them through Settings → Voice Manager. The recording was made
once with a clean voice and bundled with the install.

The karaoke overlay still gets to render the script alongside the
audio: ``start_chunk(text, duration)`` paces its cursor purely off
the duration we hand it, and the duration we hand it IS the WAV's
length, so the cursor lands on the last word as the audio finishes.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import wave
import winsound
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG
from .i18n import t
from .paths import ASSET_NO_VOICE_WAV, DATA_ROOT, PIPER_EXE, VOICES_DIR
from .voices import KNOWN_VOICES, PiperVoice, installed_voices, voice_filename

# Verbatim text of the bundled WAV. Kept here (next to the path it
# describes) so when we re-record we can update both in one place.
NO_VOICE_SCRIPT: str = (
    "Hi, I'm PipPal — but I can't read anything yet because no voice "
    "is installed. Right-click my icon in the system tray, open "
    "Settings, then Voice Manager. Pick a voice in your language, hit "
    "Install, and I'll be ready in a moment. See you soon."
)

ACTIVATION_STATE_KEY = "first_run_activation"
ACTIVATION_STATE_FILENAME = "first_run_activation.json"
COMPLETION_METHODS = frozenset({"sample", "selected_text"})

READINESS_READY = "ready"
READINESS_MISSING_PIPER = "missing_piper"
READINESS_MISSING_VOICE = "missing_voice"

# SELECTED_TEXT_CAPTURE_FAILURE is a cross-module STATUS SENTINEL: engine.py
# records it as the activation last_failure and the value is compared for
# equality across modules/tests, so it stays a stable English constant (it is
# surfaced to the user only wrapped by activation_failure_recovery_message,
# whose template IS catalog-sourced with a {failure} placeholder).
SELECTED_TEXT_CAPTURE_FAILURE = "No selected text was captured."


@dataclass(frozen=True)
class FirstRunActivationState:
    completed_at: str | None = None
    completed_with: str | None = None
    last_failure: str | None = None

    @property
    def is_complete(self) -> bool:
        return bool(
            self.completed_at and self.completed_with in COMPLETION_METHODS
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            ACTIVATION_STATE_KEY: {
                "completed_at": self.completed_at,
                "completed_with": self.completed_with,
                "last_failure": self.last_failure,
            }
        }


@dataclass(frozen=True)
class FirstRunReadiness:
    status: str
    engine_label: str
    voice_label: str
    hotkey_label: str
    can_play_sample: bool
    message: str

    @property
    def is_ready(self) -> bool:
        return self.status == READINESS_READY


def activation_state_path(data_root: Path = DATA_ROOT) -> Path:
    return data_root / ACTIVATION_STATE_FILENAME


def _state_from_payload(payload: Any) -> FirstRunActivationState:
    if not isinstance(payload, dict):
        return FirstRunActivationState()
    raw = payload.get(ACTIVATION_STATE_KEY, payload)
    if not isinstance(raw, dict):
        return FirstRunActivationState()
    completed_at = raw.get("completed_at")
    completed_with = raw.get("completed_with")
    last_failure = raw.get("last_failure")
    if not isinstance(completed_at, str):
        completed_at = None
    if completed_with not in COMPLETION_METHODS:
        completed_with = None
    if not isinstance(last_failure, str):
        last_failure = None
    if not completed_at or not completed_with:
        completed_at = None
        completed_with = None
    return FirstRunActivationState(
        completed_at=completed_at,
        completed_with=completed_with,
        last_failure=last_failure,
    )


def load_activation_state(path: Path | None = None) -> FirstRunActivationState:
    state_path = path or activation_state_path()
    if not state_path.exists():
        return FirstRunActivationState()
    try:
        return _state_from_payload(json.loads(state_path.read_text("utf-8")))
    except Exception:
        return FirstRunActivationState()


def save_activation_state(
    state: FirstRunActivationState,
    path: Path | None = None,
) -> None:
    state_path = path or activation_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".part")
    tmp.write_text(
        json.dumps(state.to_payload(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(str(tmp), str(state_path))


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def mark_activation_complete(
    completed_with: str,
    *,
    path: Path | None = None,
    completed_at: str | None = None,
) -> FirstRunActivationState:
    if completed_with not in COMPLETION_METHODS:
        allowed = ", ".join(sorted(COMPLETION_METHODS))
        raise ValueError(f"completed_with must be one of: {allowed}")
    state = FirstRunActivationState(
        completed_at=completed_at or _utc_timestamp(),
        completed_with=completed_with,
        last_failure=None,
    )
    save_activation_state(state, path=path)
    return state


def record_activation_failure(
    failure: str,
    *,
    path: Path | None = None,
) -> FirstRunActivationState:
    current = load_activation_state(path=path)
    state = FirstRunActivationState(
        completed_at=current.completed_at,
        completed_with=current.completed_with,
        last_failure=str(failure or "").strip() or None,
    )
    save_activation_state(state, path=path)
    return state


def should_show_activation_panel(path: Path | None = None) -> bool:
    return not load_activation_state(path=path).is_complete


def format_hotkey(combo: object) -> str:
    text = str(combo or "").strip()
    if not text:
        return t("onboarding.hotkey.not_configured")
    labels = {
        "control": "Ctrl",
        "ctrl": "Ctrl",
        "shift": "Shift",
        "alt": "Alt",
        "windows": "Win",
        "win": "Win",
        "super": "Win",
    }
    parts: list[str] = []
    for raw_part in text.split("+"):
        part = raw_part.strip().lower()
        if not part:
            continue
        parts.append(labels.get(part, part.upper() if len(part) == 1 else part.title()))
    return "+".join(parts) if parts else t("onboarding.hotkey.not_configured")


def activation_sample_text(hotkey_label: str) -> str:
    return t(
        "onboarding.sample_text",
        {"hotkey": hotkey_label or t("onboarding.sample_hotkey_default")},
    )


def activation_failure_recovery_message(
    failure: str | None,
    hotkey_label: str,
) -> str | None:
    failure = str(failure or "").strip()
    if not failure:
        return None
    hotkey = hotkey_label or t("onboarding.sample_hotkey_default")
    return t("onboarding.recovery", {"failure": failure, "hotkey": hotkey})


def _display_voice_name(filename: str | None) -> str:
    name = Path(filename or "").name
    if name.endswith(".onnx"):
        name = name[:-5]
    return name or t("onboarding.readiness.voice_not_installed")


def default_piper_voice() -> PiperVoice:
    """Return the curated Piper voice that matches the Core default config."""
    configured_voice = str(DEFAULT_CONFIG["voice"])
    for voice in KNOWN_VOICES:
        if voice_filename(voice) == configured_voice:
            return voice
    raise RuntimeError(f"Default Piper voice is not in the curated catalogue: {configured_voice}")


def build_activation_readiness(
    config: dict[str, Any],
    *,
    piper_exe: Path = PIPER_EXE,
    voices_dir: Path = VOICES_DIR,
) -> FirstRunReadiness:
    engine_name = str(config.get("engine") or DEFAULT_CONFIG["engine"]).lower()
    hotkey_label = format_hotkey(
        config.get("hotkey_speak") or DEFAULT_CONFIG["hotkey_speak"]
    )

    if engine_name != "piper":
        return FirstRunReadiness(
            status=READINESS_READY,
            engine_label=engine_name,
            voice_label=t("onboarding.readiness.engine_selected_label"),
            hotkey_label=hotkey_label,
            can_play_sample=True,
            message=t("onboarding.readiness.engine_selected_ready"),
        )

    configured_voice = str(config.get("voice") or DEFAULT_CONFIG["voice"] or "")
    voices = installed_voices(voices_dir=voices_dir)
    selected_voice = configured_voice if configured_voice in voices else None
    selected_voice = selected_voice or (voices[0] if voices else configured_voice)

    if not Path(piper_exe).exists():
        return FirstRunReadiness(
            status=READINESS_MISSING_PIPER,
            engine_label=t("onboarding.readiness.engine_missing"),
            voice_label=_display_voice_name(selected_voice),
            hotkey_label=hotkey_label,
            can_play_sample=False,
            message=t("onboarding.readiness.missing_piper"),
        )

    if not voices:
        return FirstRunReadiness(
            status=READINESS_MISSING_VOICE,
            engine_label=t("onboarding.readiness.engine_ready"),
            voice_label=t("onboarding.readiness.voice_not_installed"),
            hotkey_label=hotkey_label,
            can_play_sample=False,
            message=t("onboarding.readiness.missing_voice"),
        )

    return FirstRunReadiness(
        status=READINESS_READY,
        engine_label=t("onboarding.readiness.engine_ready"),
        voice_label=_display_voice_name(selected_voice),
        hotkey_label=hotkey_label,
        can_play_sample=True,
        message=t("onboarding.readiness.ready"),
    )


def is_default_engine_ready(
    *,
    piper_exe: Path = PIPER_EXE,
    voices_dir: Path = VOICES_DIR,
) -> bool:
    """True when Piper can synthesize with at least one local voice.

    Plugin-registered engines make their own readiness call via
    ``backend.is_available()``; this helper only covers the public
    package's own engine.
    """
    return Path(piper_exe).exists() and bool(installed_voices(voices_dir=voices_dir))


def _wav_duration_s(path) -> float:
    """Wall-clock length of a PCM WAV in seconds. Returns 0.0 if the
    header is unreadable — caller falls back to a coarse estimate."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
        return frames / rate if rate else 0.0
    except Exception:
        return 0.0


def play_no_voice_clip(overlay: Any | None = None) -> float:
    """Play the bundled "I can't read anything yet, install a voice"
    clip asynchronously and start the karaoke overlay alongside.

    Returns the WAV's wall-clock duration so the caller can schedule
    its own end-of-clip cleanup (overlay hide, is_speaking flip, etc.).
    Returns 0.0 when the WAV is absent — e.g. a stripped-down dev
    install with no onboarding folder.
    """
    if not ASSET_NO_VOICE_WAV.exists():
        print(
            f"[onboarding] no-voice clip missing at {ASSET_NO_VOICE_WAV}",
            file=sys.stderr,
        )
        return 0.0

    # Drive the karaoke cursor off the WAV's actual duration so its
    # last-word landing matches the audio's last syllable. If reading
    # the WAV header fails for any reason, fall back to a 14s default
    # — close to the recorded clip and better than no overlay at all.
    duration_s = _wav_duration_s(ASSET_NO_VOICE_WAV) or 14.0

    if overlay is not None:
        try:
            # Only "thinking" and "reading" actually show the overlay
            # (set_state hides it for any other value); plain "speaking"
            # was wrong and silently hid the panel. ``reading`` puts it
            # in karaoke-cursor mode, which is what start_chunk feeds.
            overlay.set_state("reading")
            overlay.start_chunk(NO_VOICE_SCRIPT, duration_s, idx=0, total=1)
        except Exception as exc:
            # never block the audio cue.
            print(f"[onboarding] overlay sync failed: {exc}", file=sys.stderr)

    # SND_FILENAME so PlaySound doesn't try to interpret the path as a
    # registry alias. SND_ASYNC so the action handler returns
    # immediately. SND_NODEFAULT so a missing WAV at this point would
    # fail silently rather than play the Windows default beep.
    flags = (
        winsound.SND_FILENAME
        | winsound.SND_ASYNC
        | winsound.SND_NODEFAULT
    )

    def _play() -> None:
        try:
            winsound.PlaySound(str(ASSET_NO_VOICE_WAV), flags)
        except Exception as exc:
            # crash an action handler over an onboarding nicety.
            print(f"[onboarding] PlaySound failed: {exc}", file=sys.stderr)

    threading.Thread(target=_play, daemon=True).start()
    return duration_s
