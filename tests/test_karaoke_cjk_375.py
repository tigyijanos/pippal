"""Regression test for #375: karaoke word highlighting on CJK (Chinese)
text.

Root cause: ``text_utils.iter_word_spans`` tokenised on whitespace (``\\S+``).
Chinese/Japanese are written without inter-word spaces, so an entire CJK
sentence collapsed into ONE token -> ONE karaoke segment -> no progressive
highlight (the fade never advanced).

Fix: segment contiguous unspaced-CJK (Han + Japanese kana) runs per
character, while keeping whitespace-tokenised behaviour byte-identical for
spaced scripts (en/de/hu/uk...).

Run with:
    python -m pytest tests/test_karaoke_cjk_375.py -v
"""

from __future__ import annotations

import re

from pippal.text_utils import iter_word_spans
from pippal.web_ui.overlay_state import _word_timings

# A short Chinese sentence: "Hello, world. Today the weather is nice."
ZH_TEXT = "你好世界今天天气很好"
# Japanese (kana + kanji) — also unspaced.
JA_TEXT = "こんにちは世界"


class TestCjkSegmentation:
    def test_chinese_yields_multiple_segments(self):
        spans = list(iter_word_spans(ZH_TEXT))
        # Each Han character is its own karaoke unit.
        assert len(spans) == len(ZH_TEXT)
        assert [m.group() for m in spans] == list(ZH_TEXT)

    def test_japanese_kana_and_kanji_segmented(self):
        spans = list(iter_word_spans(JA_TEXT))
        assert len(spans) == len(JA_TEXT)

    def test_mixed_latin_and_cjk(self):
        # Latin runs stay whole; CJK runs split per character.
        spans = [m.group() for m in iter_word_spans("AI你好")]
        assert spans == ["AI", "你", "好"]


class TestSpacedScriptsUnchanged:
    """Zero-regression: for scripts that use spaces, the segmentation must
    be byte-identical to the historical ``\\S+`` behaviour."""

    OLD = re.compile(r"\S+")

    def _old(self, text: str) -> list[str]:
        return [m.group() for m in self.OLD.finditer(text)]

    def test_english_identical(self):
        text = "The quick brown fox, jumps!"
        assert [m.group() for m in iter_word_spans(text)] == self._old(text)

    def test_german_identical(self):
        text = "Der schnelle braune Fuchs springt über den Zaun."
        assert [m.group() for m in iter_word_spans(text)] == self._old(text)

    def test_ukrainian_identical(self):
        text = "Швидка бура лисиця стрибає через ледачого пса."
        assert [m.group() for m in iter_word_spans(text)] == self._old(text)

    def test_hungarian_identical(self):
        text = "A gyors barna róka átugorja a lusta kutyát."
        assert [m.group() for m in iter_word_spans(text)] == self._old(text)


class TestProgressiveHighlightTimings:
    def test_chinese_has_progressive_word_timings(self):
        words = _word_timings(ZH_TEXT, duration=5.0)
        # More than one highlight segment (the bug produced exactly one).
        assert len(words) > 1
        assert len(words) == len(ZH_TEXT)
        # Timings are progressive: monotonically non-decreasing, each
        # segment starts where usable time has advanced, ends after it
        # starts, and the last ends within the clip.
        prev_ts = -1.0
        for w in words:
            assert w["ts"] >= prev_ts
            assert w["te"] >= w["ts"]
            prev_ts = w["ts"]
        assert words[0]["ts"] < words[-1]["ts"]
        assert words[-1]["te"] <= 5.0

    def test_english_timings_unchanged_shape(self):
        words = _word_timings("Hello there world", duration=3.0)
        assert [w["word"] for w in words] == ["Hello", "there", "world"]
