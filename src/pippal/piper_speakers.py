"""Safe parsing and selection helpers for multi-speaker Piper voices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import VOICES_DIR

_MAX_METADATA_BYTES = 2_000_000


def load_speaker_id_map(
    voice: str,
    *,
    voices_dir: Path = VOICES_DIR,
) -> dict[str, int]:
    if not voice.endswith(".onnx") or Path(voice).name != voice:
        return {}
    metadata = voices_dir / f"{voice}.json"
    try:
        if metadata.stat().st_size > _MAX_METADATA_BYTES:
            return {}
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, RecursionError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_map = payload.get("speaker_id_map")
    count = payload.get("num_speakers")
    if (
        not isinstance(raw_map, dict)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
    ):
        return {}

    speakers: dict[str, int] = {}
    for raw_label, raw_id in raw_map.items():
        if not isinstance(raw_label, (str, int)) or isinstance(raw_label, bool):
            continue
        if not isinstance(raw_id, int) or isinstance(raw_id, bool):
            continue
        label = str(raw_label).strip()
        if label and 0 <= raw_id < count:
            speakers[label] = raw_id
    return speakers


def valid_speaker_id(
    voice: str,
    value: Any,
    *,
    voices_dir: Path = VOICES_DIR,
) -> int | None:
    valid_ids = set(load_speaker_id_map(voice, voices_dir=voices_dir).values())
    if len(valid_ids) <= 1 or isinstance(value, bool):
        return None
    if isinstance(value, int):
        selected = value
    elif isinstance(value, str):
        normalized = value.strip()
        if len(normalized) > 20 or not normalized.isdecimal():
            return None
        try:
            selected = int(normalized)
        except ValueError:
            return None
    else:
        return None
    return selected if selected in valid_ids else None


def selected_speaker_id(
    config: dict[str, Any],
    voice: str,
    *,
    voices_dir: Path = VOICES_DIR,
) -> int | None:
    selections = config.get("piper_speaker_ids")
    if not isinstance(selections, dict):
        return None
    return valid_speaker_id(voice, selections.get(voice), voices_dir=voices_dir)
