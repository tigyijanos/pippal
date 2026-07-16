"""Web bridge mixin for bounded, voice-scoped Piper speaker selection."""

from __future__ import annotations

from typing import Any

from .. import paths
from ..piper_speakers import (
    load_speaker_id_map,
    selected_speaker_id,
    valid_speaker_id,
)

_RESULT_LIMIT = 50


class PiperSpeakersBridgeMixin:
    """Expose installed multi-speaker metadata without trusting the client."""

    def get_piper_speakers(
        self,
        voice: str,
        query: str = "",
        selected_id: Any = None,
    ) -> dict[str, Any]:
        voice = str(voice)
        speakers = load_speaker_id_map(voice, voices_dir=paths.VOICES_DIR)
        needle = str(query or "").strip().casefold()
        matches = [
            {"id": speaker_id, "label": label}
            for label, speaker_id in speakers.items()
            if not needle or needle in label.casefold() or needle == str(speaker_id).casefold()
        ]
        selected = (
            selected_speaker_id(
                self.config,
                voice,
                voices_dir=paths.VOICES_DIR,
            )
            if selected_id is None
            else valid_speaker_id(
                voice,
                selected_id,
                voices_dir=paths.VOICES_DIR,
            )
        )
        visible = matches[:_RESULT_LIMIT]
        if not needle and selected is not None and all(item["id"] != selected for item in visible):
            selected_entry = next(
                (
                    {"id": speaker_id, "label": label}
                    for label, speaker_id in speakers.items()
                    if speaker_id == selected
                ),
                None,
            )
            if selected_entry is not None:
                visible = [selected_entry, *visible[: _RESULT_LIMIT - 1]]
        return {
            "total": len(speakers),
            "selected": selected,
            "speakers": visible,
            "truncated": len(matches) > _RESULT_LIMIT,
        }

    def set_piper_speaker(self, voice: str, speaker_id: Any) -> dict[str, Any]:
        voice = str(voice)
        selected = valid_speaker_id(voice, speaker_id, voices_dir=paths.VOICES_DIR)
        if selected is None:
            return {"ok": False, "code": "invalid_speaker"}
        current = self.config.get("piper_speaker_ids")
        selections = dict(current) if isinstance(current, dict) else {}
        selections[voice] = selected
        return self.save_config({"piper_speaker_ids": selections})
