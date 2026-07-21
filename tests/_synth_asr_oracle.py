"""Pure scoring helpers for the live synthesis ASR round trip."""

from __future__ import annotations

import re

SYNTHESIS_PROMPT = (
    "The quick brown fox jumps over the lazy dog. Seven people carried blue "
    "boxes across the quiet garden."
)
ANCHORS = (
    "quick",
    "brown",
    "fox",
    "jumps",
    "lazy",
    "dog",
    "seven",
    "people",
    "blue",
    "boxes",
    "garden",
)
MAX_WORD_ERROR_RATE = 0.35
MIN_ORDERED_ANCHORS = 8


def normalize_words(text: str) -> tuple[str, ...]:
    """Return case-folded ASCII alphabetic words from *text*."""
    return tuple(re.findall(r"[a-z]+", text.casefold(), flags=re.ASCII))


_REFERENCE_WORDS = normalize_words(SYNTHESIS_PROMPT)


def _edit_distance(
    reference: tuple[str, ...],
    hypothesis: tuple[str, ...],
) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_word in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_word in enumerate(hypothesis, start=1):
            substitution = previous[hypothesis_index - 1] + (reference_word != hypothesis_word)
            deletion = previous[hypothesis_index] + 1
            insertion = current[hypothesis_index - 1] + 1
            current.append(min(substitution, deletion, insertion))
        previous = current
    return previous[-1]


def word_error_rate(transcript: str) -> float:
    """Measure word-level edit distance against the fixed synthesis prompt."""
    return _edit_distance(_REFERENCE_WORDS, normalize_words(transcript)) / len(_REFERENCE_WORDS)


def ordered_anchor_count(transcript: str) -> int:
    """Count prompt anchors recovered in order using LCS."""
    words = normalize_words(transcript)
    previous = [0] * (len(words) + 1)
    for anchor in ANCHORS:
        current = [0]
        for word_index, word in enumerate(words, start=1):
            if anchor == word:
                current.append(previous[word_index - 1] + 1)
            else:
                current.append(max(previous[word_index], current[-1]))
        previous = current
    return previous[-1]


def passes_asr_oracle(transcript: str) -> bool:
    """Require both whole-phrase fidelity and ordered anchor evidence."""
    return (
        word_error_rate(transcript) <= MAX_WORD_ERROR_RATE
        and ordered_anchor_count(transcript) >= MIN_ORDERED_ANCHORS
    )
