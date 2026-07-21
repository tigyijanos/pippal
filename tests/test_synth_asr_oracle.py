"""Pure controls for the synthesis ASR oracle."""

from __future__ import annotations

import pytest

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

BOUNDED_NOISE = (
    "quick brown, fox, jumps over the lazy doll. Seven people carry blue "
    "boxes across a quiet garden."
)
WRONG_SPEECH = (
    "The train arrives at the station before midnight. Please close the red "
    "door and turn off the kitchen light."
)
WER_PASS_ANCHOR_FAIL = (
    "The fast tan animal leaps over the lazy dog. Seven people carried blue "
    "boxes across the quiet garden."
)
ANCHOR_PASS_WER_FAIL = "quick brown fox jumps lazy dog seven people"


def test_prompt_and_anchor_contract() -> None:
    assert len(normalize_words(SYNTHESIS_PROMPT)) == 18
    assert len(ANCHORS) == 11
    assert len(set(ANCHORS)) == len(ANCHORS)
    assert set(ANCHORS) <= set(normalize_words(SYNTHESIS_PROMPT))
    assert MAX_WORD_ERROR_RATE == 0.35
    assert MIN_ORDERED_ANCHORS == 8


def test_exact_prompt_passes_both_gates() -> None:
    assert word_error_rate(SYNTHESIS_PROMPT) == 0.0
    assert ordered_anchor_count(SYNTHESIS_PROMPT) == 11
    assert passes_asr_oracle(SYNTHESIS_PROMPT)


def test_bounded_noise_passes_without_aliases() -> None:
    assert word_error_rate(BOUNDED_NOISE) < MAX_WORD_ERROR_RATE
    assert ordered_anchor_count(BOUNDED_NOISE) >= MIN_ORDERED_ANCHORS
    assert passes_asr_oracle(BOUNDED_NOISE)


@pytest.mark.parametrize(
    "transcript",
    [
        "",
        "a low world from pick pound.",
        "a low world from pit pal.",
        WRONG_SPEECH,
    ],
)
def test_wrong_or_empty_transcripts_fail(transcript: str) -> None:
    assert not passes_asr_oracle(transcript)


def test_empty_and_measured_wrong_speech_metrics() -> None:
    assert word_error_rate("") == 1.0
    assert ordered_anchor_count("") == 0
    assert word_error_rate(WRONG_SPEECH) > MAX_WORD_ERROR_RATE
    assert ordered_anchor_count(WRONG_SPEECH) == 0


def test_reversed_anchors_fail_ordered_gate() -> None:
    reversed_anchors = " ".join(reversed(ANCHORS))
    assert ordered_anchor_count(reversed_anchors) < MIN_ORDERED_ANCHORS
    assert not passes_asr_oracle(reversed_anchors)


def test_anchor_gate_can_fail_when_wer_passes() -> None:
    assert word_error_rate(WER_PASS_ANCHOR_FAIL) == pytest.approx(4 / 18)
    assert ordered_anchor_count(WER_PASS_ANCHOR_FAIL) == 7
    assert not passes_asr_oracle(WER_PASS_ANCHOR_FAIL)


def test_wer_gate_can_fail_when_anchor_gate_passes() -> None:
    assert word_error_rate(ANCHOR_PASS_WER_FAIL) == pytest.approx(10 / 18)
    assert ordered_anchor_count(ANCHOR_PASS_WER_FAIL) == 8
    assert not passes_asr_oracle(ANCHOR_PASS_WER_FAIL)
