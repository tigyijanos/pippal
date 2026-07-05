"""Behavioral i18n oracle for the core overlay ``show_message`` strings (#145).

T-104 keyed the web-UI render surfaces but missed three Python-side overlay
messages that ``show_message`` pushes into the reader panel in BOTH core and
Pro: ``engine.py`` "No text selected" (x2) and "Queued - {count} pending", and
``playback.py`` "Synthesis failed". This module asserts INDEPENDENT oracles:

  * the new keys exist in ``en.json`` byte-identical to the pre-extraction
    literals (so the default English surface is unchanged);
  * ``t()`` is evaluated *at call time* - flipping the active language BEFORE
    the engine/playback call makes the overlay render the translated string
    (a compile-time-captured literal could never do this);
  * the ``overlay.msg.queued`` CLDR plural resolves through the shipped
    resolver for a representative count.

Catalog completeness/parity for these keys is covered by
``tests/test_i18n_catalogs.py``; this file locks the *wiring*.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pippal import engine as engine_mod
from pippal import onboarding
from pippal import playback as playback_mod
from pippal.engine import TTSEngine
from pippal.i18n import get_language, set_language, t

I18N_DIR = Path(__file__).resolve().parents[1] / "webui" / "i18n"
EN = json.loads((I18N_DIR / "en.json").read_text("utf-8"))


@pytest.fixture(autouse=True)
def _restore_language():
    saved = get_language()
    try:
        yield
    finally:
        set_language(saved)


def test_en_values_byte_identical_to_pre_extraction_literals():
    assert EN["overlay.msg.no_text_selected"] == "No text selected"
    assert EN["overlay.msg.synthesis_failed"] == "Synthesis failed"
    queued = EN["overlay.msg.queued"]
    assert isinstance(queued, dict) and queued["_plural"] == "count"
    assert queued["other"] == "Queued — {count} pending"


def test_queued_plural_interpolates_count():
    set_language("en")
    assert t("overlay.msg.queued", {"count": 3}) == "Queued — 3 pending"


def test_speak_selection_renders_no_text_selected_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
):
    overlay = MagicMock()
    tts = TTSEngine(MagicMock(), {"engine": "piper"}, overlay_ref=lambda: overlay)
    monkeypatch.setattr(tts, "_maybe_play_onboarding", lambda: False)
    monkeypatch.setattr(engine_mod.winsound, "PlaySound", lambda *_: None)
    monkeypatch.setattr(
        engine_mod.clipboard_capture, "capture_for_action", lambda *_: ""
    )
    monkeypatch.setattr(engine_mod, "should_show_activation_panel", lambda: True)
    monkeypatch.setattr(
        engine_mod,
        "record_activation_failure",
        lambda failure: onboarding.FirstRunActivationState(last_failure=failure),
    )

    set_language("de")
    tts._speak_selection_impl()

    overlay.show_message.assert_called_once_with(
        t("overlay.msg.no_text_selected", lang="de")
    )
    # The German surface must actually differ from English (real translation).
    assert overlay.show_message.call_args.args[0] != "No text selected"


def test_synthesis_failed_renders_at_call_time():
    overlay = MagicMock()
    engine = MagicMock()
    engine._overlay.return_value = overlay
    engine._synthesize.return_value = False  # force the failure branch
    session = MagicMock()

    set_language("de")
    ok = playback_mod._prepare_first_chunk(engine, session, my_token=1)

    assert ok is False
    overlay.show_message.assert_called_once_with(
        t("overlay.msg.synthesis_failed", lang="de")
    )
    assert overlay.show_message.call_args.args[0] != "Synthesis failed"
