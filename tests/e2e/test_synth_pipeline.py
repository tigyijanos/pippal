"""End-to-end tests for the synthesis pipeline.

Headless on Windows. We drive the real ``PiperBackend.synthesize``
against the real piper.exe, then verify the WAV output is a real
audio file (right magic header, plausible duration, non-silent).

A separate test optionally decodes the WAV with faster-whisper to
confirm the audio actually contains the words PipPal was asked to
say. That's the expensive end of the spectrum — guarded by the
``e2e_asr`` mark so a fast CI run can skip it.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from pippal.engines.piper import PiperBackend
from tests._synth_asr_oracle import (
    ANCHORS,
    MAX_WORD_ERROR_RATE,
    MIN_ORDERED_ANCHORS,
    SYNTHESIS_PROMPT,
    normalize_words,
    ordered_anchor_count,
    passes_asr_oracle,
    word_error_rate,
)


def _wav_duration_seconds(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    return frames / rate if rate else 0.0


def _wav_rms(p: Path) -> float:
    """Crude amplitude check — non-silent audio has measurable RMS."""
    import audioop

    with wave.open(str(p), "rb") as w:
        sample_width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    return audioop.rms(frames, sample_width) if frames else 0.0


@pytest.mark.e2e
class TestSynthesisPipeline:
    """The bare-bones happy path: PipPal asks Piper to say a phrase,
    Piper writes a WAV, the WAV looks right."""

    def test_short_phrase_produces_valid_wav(
        self,
        piper_config: dict,
        tmp_path: Path,
    ) -> None:
        backend = PiperBackend(piper_config)
        out = tmp_path / "hello.wav"
        ok = backend.synthesize("Hello world from PipPal.", out)
        assert ok, "PiperBackend.synthesize returned False"
        assert out.exists(), "WAV file was not written"
        assert out.stat().st_size > 1024, f"WAV file suspiciously small: {out.stat().st_size} bytes"

    def test_wav_has_plausible_duration(
        self,
        piper_config: dict,
        tmp_path: Path,
    ) -> None:
        backend = PiperBackend(piper_config)
        out = tmp_path / "duration.wav"
        backend.synthesize("This sentence has eight syllables in it.", out)
        d = _wav_duration_seconds(out)
        # Rough envelope: 8 syllables * 0.15-0.4 s/syllable = 1.2-3.2 s.
        # Allow a little slop on either side for prosody / model quirks.
        assert 0.8 < d < 5.0, f"unexpected synth duration: {d:.2f} s"

    def test_wav_is_not_silent(
        self,
        piper_config: dict,
        tmp_path: Path,
    ) -> None:
        backend = PiperBackend(piper_config)
        out = tmp_path / "amp.wav"
        backend.synthesize("Hello.", out)
        rms = _wav_rms(out)
        # A piper synth at default settings sits well above 100 RMS.
        # We keep the threshold conservative — the point is "is there
        # audio at all", not "is it loud enough".
        assert rms > 50, f"WAV looks silent (RMS {rms})"

    def test_multi_chunk_synth_and_concat(
        self,
        piper_config: dict,
        tmp_path: Path,
    ) -> None:
        """An article-shaped input gets sentence-split into multiple
        chunks. Each chunk is synthesised through the real piper.exe;
        ``concat_wavs`` then welds them into one WAV. Catches three
        layered regressions in one shot:

        - sentence splitter drops or duplicates a sentence
        - chunk-by-chunk synth doesn't agree on sample rate / width
        - concat helper truncates or doubles the length

        We assert the merged duration matches the sum of chunk
        durations within 5 % — concat is meant to preserve total time.
        """
        from pippal.text_utils import split_sentences
        from pippal.wav_utils import concat_wavs, wav_duration

        # split_sentences groups shorter sentences into chunks up to
        # the 400-char cap. Repeat the body so the input overflows
        # the cap and concat sees ≥2 inputs — that's enough to
        # exercise the multi-WAV concat path (single-input concat
        # is a separate code branch we already cover in unit tests).
        body = (
            "Hello there. This is a longer test message. "
            "It has multiple sentences. The sentence splitter must "
            "handle them all cleanly. End of message. "
        )
        text = body * 4
        chunks = split_sentences(text)
        assert len(chunks) >= 2, f"need ≥2 chunks for concat, got {len(chunks)}"

        backend = PiperBackend(piper_config)
        chunk_paths: list[Path] = []
        for i, c in enumerate(chunks):
            p = tmp_path / f"chunk_{i:02d}.wav"
            assert backend.synthesize(c, p), f"chunk {i} synth failed"
            chunk_paths.append(p)

        merged = tmp_path / "merged.wav"
        concat_wavs(chunk_paths, merged)
        assert merged.exists() and merged.stat().st_size > 1024

        total = sum(wav_duration(p) for p in chunk_paths)
        joined = wav_duration(merged)
        assert total > 0
        assert abs(joined - total) / total < 0.05, (
            f"merged duration drifted from sum of chunks: merged={joined:.2f}s sum={total:.2f}s"
        )

    def test_length_scale_changes_duration(
        self,
        piper_config: dict,
        tmp_path: Path,
    ) -> None:
        """``length_scale`` is the user-facing speed knob inverse —
        2.0 means *slower*, 0.6 *faster*. The synth duration should
        track it."""
        text = "The quick brown fox jumps over the lazy dog."

        slow = tmp_path / "slow.wav"
        PiperBackend({**piper_config, "length_scale": 1.5}).synthesize(text, slow)

        fast = tmp_path / "fast.wav"
        PiperBackend({**piper_config, "length_scale": 0.7}).synthesize(text, fast)

        d_slow = _wav_duration_seconds(slow)
        d_fast = _wav_duration_seconds(fast)
        assert d_slow > d_fast, (
            f"length_scale=1.5 should be slower than 0.7, got slow={d_slow:.2f}s fast={d_fast:.2f}s"
        )


@pytest.mark.e2e
@pytest.mark.e2e_asr
class TestSynthesisASRRoundTrip:
    """Heavier check: synthesise → transcribe with whisper → verify
    the words come back. Catches regressions in the *content* of the
    audio, not just its file shape.

    Marked separately so a fast headless CI tier can skip it."""

    def test_synth_decodes_to_known_phrase(
        self,
        piper_config: dict,
        tmp_path: Path,
    ) -> None:
        whisper = pytest.importorskip("faster_whisper")

        out = tmp_path / "asr.wav"
        synthesized = PiperBackend(piper_config).synthesize(SYNTHESIS_PROMPT, out)

        assert synthesized, "Piper synthesis failed"
        assert out.exists(), "Piper reported success without creating the WAV"
        assert out.stat().st_size > 1_024, "Synthesized WAV is unexpectedly small"

        duration = _wav_duration_seconds(out)
        rms = _wav_rms(out)
        assert 2 < duration < 15, f"Unexpected synthesized duration: {duration:.3f}s"
        assert rms > 50, f"Synthesized WAV is effectively silent: RMS={rms:.1f}"

        model = whisper.WhisperModel(
            "tiny.en",
            device="cpu",
            compute_type="int8",
        )
        segments, _info = model.transcribe(
            str(out),
            language="en",
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        decoded = " ".join(segment.text for segment in segments).strip()
        normalized_tokens = normalize_words(decoded)
        measured_wer = word_error_rate(decoded)
        recovered_anchors = ordered_anchor_count(decoded)

        assert passes_asr_oracle(decoded), (
            f"Synthesis ASR oracle failed: decoded={decoded!r}; "
            f"normalized_tokens={list(normalized_tokens)!r}; "
            f"word_error_rate={measured_wer:.3f}; "
            f"maximum_word_error_rate={MAX_WORD_ERROR_RATE}; "
            f"ordered_anchor_count={recovered_anchors}; "
            f"minimum_ordered_anchors={MIN_ORDERED_ANCHORS}; "
            f"anchors={list(ANCHORS)!r}"
        )
