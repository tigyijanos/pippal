"""Benchmarks for the disk-touching helpers: config / history JSON
round-trip, WAV concatenation, and the tray-icon factory's first-paint.

These are the operations whose cost matters when the user opens
Settings or when the tray-tick reaches for a fresh icon."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pippal import config, history, tray, wav_utils

pytestmark = pytest.mark.benchmark(group="io")


# ---------------------------------------------------------------------------
# config / history JSON round-trip
# ---------------------------------------------------------------------------

def test_config_load_when_missing(benchmark, tmp_path: Path):
    """Common case: first launch on a new machine — config.json
    doesn't exist yet, ``load_config`` returns the layered defaults."""
    p = tmp_path / "config.json"
    benchmark(config.load_config, p)


def test_config_load_existing(benchmark, tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "voice": "en_US-ljspeech-high.onnx",
        "length_scale": 0.95,
    }), encoding="utf-8")
    benchmark(config.load_config, p)


def test_config_save(benchmark, tmp_path: Path):
    cfg = dict(config.DEFAULT_CONFIG)
    cfg["voice"] = "en_US-ljspeech-high.onnx"
    p = tmp_path / "config.json"
    # Same path every round — that's actually what production does
    # (Settings → Save overwrites). os.replace is part of the cost
    # we want to measure.
    benchmark(config.save_config, cfg, p)


def test_history_round_trip(benchmark, tmp_path: Path):
    p = tmp_path / "history.json"
    items = [f"selection-text-{i}" for i in range(20)]

    def round_trip():
        history.save_history(items, p)
        return history.load_history(p)

    benchmark(round_trip)


# ---------------------------------------------------------------------------
# WAV utilities
# ---------------------------------------------------------------------------

def _write_silent_wav(path: Path, ms: int = 100) -> None:
    """Tiny 100 ms 22050 Hz mono silence WAV — enough for the wav-utils
    helpers to chew on without bloating the bench."""
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00" * (22050 * ms // 1000 * 2))


def test_wav_duration(benchmark, tmp_path: Path):
    p = tmp_path / "silence.wav"
    _write_silent_wav(p)
    benchmark(wav_utils.wav_duration, p)


def test_wav_concat_3_chunks(benchmark, tmp_path: Path):
    """Realistic Save-as-WAV export: 3 sentence-sized chunks, ~100 ms
    each, concatenated into one output. Output is overwritten each
    round; that's the same code path the exporter uses."""
    inputs = []
    for i in range(3):
        p = tmp_path / f"chunk_{i}.wav"
        _write_silent_wav(p, ms=100)
        inputs.append(p)
    out = tmp_path / "joined.wav"
    benchmark(wav_utils.concat_wavs, inputs, out)


# ---------------------------------------------------------------------------
# Tray icon factory
# ---------------------------------------------------------------------------

def test_tray_icon_first_paint(benchmark):
    """Tray-tick fires every ~400 ms and asks for the icon. The first
    paint is the slow one (Pillow load + resize); the subsequent
    cached lookups are nearly free."""
    def first_paint():
        tray._icon_cache.clear()
        return tray.make_tray_icon(speaking=False)

    benchmark(first_paint)


def test_tray_icon_cached(benchmark):
    """Steady-state tray-tick path: cache hit, no Pillow work."""
    tray.make_tray_icon(speaking=False)  # warm
    benchmark(tray.make_tray_icon, False)
