"""Piper TTS — out-of-process via the bundled `piper.exe`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..config import DEFAULT_CONFIG
from ..paths import PIPER_DIR, PIPER_EXE, VOICES_DIR
from ..piper_speakers import selected_speaker_id
from ..voices import is_installed_voice
from .base import TTSBackend

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PiperBackend(TTSBackend):
    name = "piper"

    def is_available(self) -> bool:
        return PIPER_EXE.exists()

    def is_ready(self) -> bool:
        # piper.exe alone isn't enough — synth needs the configured
        # .onnx voice and its .onnx.json sidecar in VOICES_DIR. If the
        # saved config points at a stale placeholder/deleted voice,
        # action handlers should play onboarding instead of entering a
        # synth path that is guaranteed to fail.
        voice = str(self.config.get("voice", DEFAULT_CONFIG["voice"]))
        return self.is_available() and is_installed_voice(voice, voices_dir=VOICES_DIR)

    def synthesize(self, text: str, out_path: Path) -> bool:
        voice = str(self.config.get("voice", DEFAULT_CONFIG["voice"]))
        if not is_installed_voice(voice, voices_dir=VOICES_DIR):
            print(f"[piper] missing model or metadata: {VOICES_DIR / voice}", file=sys.stderr)
            return False

        model = VOICES_DIR / voice
        cmd = [
            str(PIPER_EXE),
            "--model", str(model),
            "--output_file", str(out_path),
            "--length_scale", str(self.config.get("length_scale", 1.0)),
            "--noise_scale", str(self.config.get("noise_scale", 0.667)),
            "--noise_w", str(self.config.get("noise_w", 0.8)),
        ]
        speaker_id = selected_speaker_id(self.config, voice, voices_dir=VOICES_DIR)
        if speaker_id is not None:
            cmd.extend(["--speaker", str(speaker_id)])
        try:
            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                cwd=str(PIPER_DIR),
                capture_output=True,
                timeout=180,
                creationflags=_NO_WINDOW,
            )
        except Exception as e:
            print(f"[piper] error: {e}", file=sys.stderr)
            return False
        return (
            proc.returncode == 0
            and out_path.exists()
            and out_path.stat().st_size > 0
        )
