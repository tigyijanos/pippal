"""E2E test fixtures.

These tests use the real ``piper.exe`` binary plus a real voice
model. They run on a self-hosted Windows runner so the Windows-only
parts of PipPal (subprocess + file I/O against piper.exe, winsound
playback path) are exercised against actual artefacts.

The fixtures expect the runner to have these env vars set:

  PIPPAL_PIPER_EXE     absolute path to piper.exe
  PIPPAL_VOICE_DIR     directory containing the test voice's .onnx
                       and .onnx.json files
  PIPPAL_TEST_VOICE    the .onnx filename to test against
                       (default: en_US-ljspeech-high.onnx)

The CI workflow downloads piper.exe + a voice model into a cached
location and exports these vars before invoking pytest.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def piper_exe() -> Path:
    raw = os.environ.get("PIPPAL_PIPER_EXE")
    if not raw:
        pytest.skip("PIPPAL_PIPER_EXE not set; e2e tests need a real piper.exe")
    p = Path(raw)
    if not p.exists():
        pytest.fail(f"PIPPAL_PIPER_EXE points at non-existent file: {p}")
    return p


@pytest.fixture(scope="session")
def voice_dir() -> Path:
    raw = os.environ.get("PIPPAL_VOICE_DIR")
    if not raw:
        pytest.skip("PIPPAL_VOICE_DIR not set")
    p = Path(raw)
    if not p.is_dir():
        pytest.fail(f"PIPPAL_VOICE_DIR is not a directory: {p}")
    return p


@pytest.fixture(scope="session")
def test_voice(voice_dir: Path) -> str:
    name = os.environ.get("PIPPAL_TEST_VOICE", "en_US-ljspeech-high.onnx")
    if not (voice_dir / name).exists():
        pytest.fail(f"Test voice not found: {voice_dir / name}")
    return name


@pytest.fixture
def piper_config(piper_exe: Path, voice_dir: Path, test_voice: str,
                  monkeypatch: pytest.MonkeyPatch) -> dict:
    """Backend config + monkey-patched paths so PiperBackend resolves
    against the runner's installed piper.exe / voice model rather than
    the package's default lookup.

    ``pippal.engines.piper`` does ``from ..paths import PIPER_EXE,
    VOICES_DIR``, so the names bound there are independent of the
    original module. Patching only ``pippal.paths`` would leave the
    backend reading the stale defaults — patch both modules to be
    safe."""
    from pippal import paths
    from pippal.engines import piper as piper_mod

    for mod in (paths, piper_mod):
        monkeypatch.setattr(mod, "PIPER_EXE", piper_exe, raising=False)
        monkeypatch.setattr(mod, "PIPER_DIR", piper_exe.parent, raising=False)
        monkeypatch.setattr(mod, "VOICES_DIR", voice_dir, raising=False)
    return {
        "voice": test_voice,
        "length_scale": 1.0,
        "noise_scale": 0.667,
        "noise_w": 0.8,
    }
