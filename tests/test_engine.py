"""Smoke tests for TTSEngine state — exercises the synchronous helpers
that don't require a working winsound / external engine / clipboard."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pippal import onboarding
from pippal.engine import TTSEngine
from pippal.engines.piper import PiperBackend


@pytest.fixture()
def engine() -> TTSEngine:
    root = MagicMock()
    config: dict[str, Any] = {"engine": "piper"}
    return TTSEngine(root, config, overlay_ref=lambda: None)


class TestHistory:
    def test_attach_and_get(self, engine: TTSEngine):
        engine.attach_history(["a", "b", "c"], save_callback=None)
        assert engine.get_history() == ["a", "b", "c"]

    def test_attach_copies_input(self, engine: TTSEngine):
        original = ["a"]
        engine.attach_history(original, None)
        original.append("b")
        assert engine.get_history() == ["a"]

    def test_clear_history_calls_save(self, engine: TTSEngine):
        seen: list[list[str]] = []
        engine.attach_history(["a"], save_callback=seen.append)
        engine.clear_history()
        assert engine.get_history() == []
        assert seen == [[]]

    def test_remember_dedupes_and_caps(self, engine: TTSEngine):
        engine.attach_history([f"t{i}" for i in range(15)], None)
        engine._remember("new")
        h = engine.get_history()
        assert h[0] == "new"
        assert len(h) <= 12  # MAX_HISTORY

    def test_remember_empty_is_noop(self, engine: TTSEngine):
        engine.attach_history(["a"], None)
        engine._remember("")
        engine._remember("   ")
        assert engine.get_history() == ["a"]

    def test_remember_strips_whitespace(self, engine: TTSEngine):
        engine.attach_history([], None)
        engine._remember("  hello  ")
        assert engine.get_history() == ["hello"]

    def test_read_text_impl_records_recent_history(self, engine: TTSEngine):
        saves: list[list[str]] = []
        engine.attach_history([], saves.append)
        with patch.object(engine, "_maybe_play_onboarding", return_value=False), \
             patch("pippal.engine.winsound.PlaySound"), \
             patch("pippal.engine.playback.synthesize_and_play") as synth:
            engine._read_text_impl("  recent text from command server  ")

        assert engine.get_history() == ["recent text from command server"]
        assert saves == [["recent text from command server"]]
        assert engine.is_speaking is True
        synth.assert_called_once()
        assert synth.call_args.args[1] == "recent text from command server"

    def test_replay_text_impl_does_not_create_new_history_item(
        self, engine: TTSEngine,
    ):
        saves: list[list[str]] = []
        engine.attach_history(["existing"], saves.append)
        with patch.object(engine, "_maybe_play_onboarding", return_value=False), \
             patch("pippal.engine.winsound.PlaySound"), \
             patch("pippal.engine.playback.synthesize_and_play"):
            engine._replay_text_impl("manual replay text")

        assert engine.get_history() == ["existing"]
        assert saves == []


class TestQueue:
    def test_default_zero(self, engine: TTSEngine):
        assert engine.queue_length() == 0


class TestPauseToggle:
    def test_no_op_when_not_speaking(self, engine: TTSEngine):
        # Should not flip _is_paused when nothing is playing.
        engine.pause_toggle()
        assert engine._is_paused is False

    def test_toggles_only_after_speaking_set(self, engine: TTSEngine):
        engine.is_speaking = True
        engine.pause_toggle()
        assert engine._is_paused is True
        engine.pause_toggle()
        assert engine._is_paused is False


class TestResetBackend:
    def test_clears_cache(self, engine: TTSEngine):
        engine._backend = MagicMock()
        engine._backend_name = "piper"
        engine.reset_backend()
        assert engine._backend is None
        assert engine._backend_name is None


class TestTokenCancellation:
    """`stop()` must signal in-flight workers via the generation token.
    These pin the cancellation invariant so a future refactor that
    forgets to bump or check the token blows up loudly."""

    def test_is_cancelled_false_for_current_token(self, engine: TTSEngine):
        with engine.lock:
            current = engine.token
        assert not engine._is_cancelled(current)

    def test_stop_cancels_old_tokens(self, engine: TTSEngine):
        with engine.lock:
            old = engine.token
        engine.stop()
        assert engine._is_cancelled(old)

    def test_each_top_level_action_bumps_token(self, engine: TTSEngine):
        # Top-level actions bump the token so any in-flight worker
        # self-cancels. We can't run the whole async chain in a unit
        # test, but we CAN check the bump.
        with engine.lock:
            t0 = engine.token
        engine.stop()
        with engine.lock:
            assert engine.token > t0

    def test_stop_clears_is_speaking(self, engine: TTSEngine):
        # Regression: synthesize_and_play's cancel-exit returns without
        # clearing is_speaking, so stop() must do it itself or the tray
        # icon would lie about playback state until the next speak.
        engine.is_speaking = True
        engine.stop()
        assert engine.is_speaking is False


class TestActivationState:
    def test_empty_selected_text_records_first_run_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        overlay = MagicMock()
        engine = TTSEngine(
            MagicMock(),
            {"engine": "piper"},
            overlay_ref=lambda: overlay,
        )
        failures: list[str] = []

        def record_failure(failure: str) -> onboarding.FirstRunActivationState:
            failures.append(failure)
            return onboarding.FirstRunActivationState(last_failure=failure)

        monkeypatch.setattr(engine, "_maybe_play_onboarding", lambda: False)
        monkeypatch.setattr("pippal.engine.winsound.PlaySound", lambda *_: None)
        monkeypatch.setattr(
            "pippal.engine.clipboard_capture.capture_for_action",
            lambda *_: "",
        )
        monkeypatch.setattr("pippal.engine.should_show_activation_panel", lambda: True)
        monkeypatch.setattr("pippal.engine.record_activation_failure", record_failure)

        engine._speak_selection_impl()

        assert failures == [onboarding.SELECTED_TEXT_CAPTURE_FAILURE]
        overlay.show_message.assert_called_once_with("No text selected")

    def test_selected_text_read_marks_first_run_complete(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        engine = TTSEngine(
            MagicMock(),
            {"engine": "piper"},
            overlay_ref=lambda: None,
        )
        completions: list[str] = []
        played: list[str] = []
        readiness = onboarding.FirstRunReadiness(
            status=onboarding.READINESS_READY,
            engine_label="Piper engine: ready",
            voice_label="en_US-ljspeech-high",
            hotkey_label="Win+Shift+R",
            can_play_sample=True,
            message="Local voice check is ready.",
        )

        def mark_complete(completed_with: str) -> onboarding.FirstRunActivationState:
            completions.append(completed_with)
            return onboarding.FirstRunActivationState(
                completed_at="2026-05-14T18:05:00Z",
                completed_with=completed_with,
            )

        monkeypatch.setattr(engine, "_maybe_play_onboarding", lambda: False)
        monkeypatch.setattr("pippal.engine.winsound.PlaySound", lambda *_: None)
        monkeypatch.setattr(
            "pippal.engine.clipboard_capture.capture_for_action",
            lambda *_: "selected text",
        )
        monkeypatch.setattr("pippal.engine.should_show_activation_panel", lambda: True)
        monkeypatch.setattr("pippal.engine.build_activation_readiness", lambda _config: readiness)
        monkeypatch.setattr("pippal.engine.mark_activation_complete", mark_complete)
        monkeypatch.setattr(
            "pippal.engine.playback.synthesize_and_play",
            lambda _engine, text, _token: played.append(text),
        )

        engine._speak_selection_impl()

        assert completions == ["selected_text"]
        assert played == ["selected text"]
        assert engine.is_speaking is True

    def test_selected_text_read_waits_for_ready_first_run_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        engine = TTSEngine(
            MagicMock(),
            {"engine": "piper"},
            overlay_ref=lambda: None,
        )
        completions: list[str] = []
        played: list[str] = []

        readiness = onboarding.FirstRunReadiness(
            status=onboarding.READINESS_MISSING_VOICE,
            engine_label="Piper engine: ready",
            voice_label="not installed",
            hotkey_label="Win+Shift+R",
            can_play_sample=False,
            message="No local voice is installed yet.",
        )

        monkeypatch.setattr(engine, "_maybe_play_onboarding", lambda: False)
        monkeypatch.setattr("pippal.engine.winsound.PlaySound", lambda *_: None)
        monkeypatch.setattr(
            "pippal.engine.clipboard_capture.capture_for_action",
            lambda *_: "selected text",
        )
        monkeypatch.setattr("pippal.engine.should_show_activation_panel", lambda: True)
        monkeypatch.setattr("pippal.engine.build_activation_readiness", lambda _config: readiness)
        monkeypatch.setattr(
            "pippal.engine.mark_activation_complete",
            lambda completed_with: completions.append(completed_with),
        )
        monkeypatch.setattr(
            "pippal.engine.playback.synthesize_and_play",
            lambda _engine, text, _token: played.append(text),
        )

        engine._speak_selection_impl()

        assert completions == []
        assert played == ["selected text"]


class TestBackendCacheRequestedName:
    """When the user requests an extension-supplied engine but it's
    unavailable, the factory falls back to Piper. The cache is keyed
    against the *requested* engine, so subsequent calls don't
    re-instantiate the fallback every chunk."""

    def test_unavailable_engine_fallback_caches_against_requested_name(self):
        from pathlib import Path

        from pippal import plugins
        from pippal.engine import TTSEngine
        from pippal.engines.base import TTSBackend

        class _FakeEngine(TTSBackend):
            name = "fake-engine"

            def is_available(self) -> bool:
                return False

            def synthesize(self, text: str, out_path: Path) -> bool:
                return False

        engine = TTSEngine(MagicMock(), {"engine": "fake-engine"}, lambda: None)
        plugins.register_engine("fake-engine", _FakeEngine)
        try:
            backend1 = engine._get_backend()
            backend2 = engine._get_backend()
        finally:
            plugins._engines.pop("fake-engine", None)
        assert backend1 is backend2  # cached, not re-built every call
        assert isinstance(backend1, PiperBackend)
        # Cache key is the *requested* name so subsequent calls don't
        # re-resolve and re-warn.
        assert engine._backend_name == "fake-engine"


class TestCaptureSelectionReleasesModifiers:
    def test_releases_configured_combo_plus_universals(self, engine: TTSEngine):
        with patch("pippal.clipboard_capture.keyboard") as kb, \
             patch("pippal.clipboard_capture.pyperclip") as cb, \
             patch("pippal.clipboard_capture.time.sleep"):  # don't actually wait
            cb.paste.return_value = "captured-text"
            cb.copy.return_value = None
            engine._capture_selection("ctrl+shift+x")
            released = {c.args[0] for c in kb.release.call_args_list}
        # Configured combo keys
        assert {"ctrl", "shift", "x"} <= released
        # Universal modifier set always released even if combo is empty
        assert {"alt", "super"} <= released

    def test_handles_empty_combo(self, engine: TTSEngine):
        with patch("pippal.clipboard_capture.keyboard") as kb, \
             patch("pippal.clipboard_capture.pyperclip") as cb, \
             patch("pippal.clipboard_capture.time.sleep"):
            cb.paste.return_value = "captured"
            engine._capture_selection("")
            released = {c.args[0] for c in kb.release.call_args_list}
        assert {"ctrl", "shift", "alt", "super"} <= released


class TestSeekOverlayInstantFeedback:
    """seek() must update the overlay to the TARGET chunk's text +
    'thinking' state IMMEDIATELY — before synthesis — so backward
    navigation feels instant even when the WAV is not cached (fix #281.5).

    RED on the un-patched engine: overlay is only updated after the
    blocking re-synthesis inside the playback loop, not in seek() itself.
    GREEN after the fix: seek() calls start_chunk + set_state before
    returning."""

    def _make_engine_with_overlay(self) -> tuple[TTSEngine, MagicMock]:
        overlay = MagicMock()
        engine = TTSEngine(
            MagicMock(),
            {"engine": "piper"},
            overlay_ref=lambda: overlay,
        )
        return engine, overlay

    def _seed_chunks(self, engine: TTSEngine, chunks: list[str]) -> None:
        """Inject mini-player state as if play_one already started."""
        with engine.lock:
            engine._chunks = chunks
            engine._chunk_idx = 2  # currently on chunk 2

    def test_seek_backward_shows_target_text_immediately(self) -> None:
        """Backward seek must call start_chunk with the TARGET text
        (chunk index 1) before synthesis of any kind happens."""
        engine, overlay = self._make_engine_with_overlay()
        chunks = ["first sentence.", "second sentence.", "third sentence."]
        self._seed_chunks(engine, chunks)

        with patch("pippal.engine.winsound.PlaySound"):
            engine.seek(-1)  # target = chunk idx 1

        # start_chunk must have been called with the target text
        overlay.start_chunk.assert_called_once()
        call_args = overlay.start_chunk.call_args
        # First positional arg is the chunk text
        assert call_args.args[0] == "second sentence."

    def test_seek_backward_shows_thinking_state_immediately(self) -> None:
        """Backward seek must call set_state('thinking') immediately,
        signalling the loading indicator before re-synthesis."""
        engine, overlay = self._make_engine_with_overlay()
        chunks = ["first sentence.", "second sentence.", "third sentence."]
        self._seed_chunks(engine, chunks)

        with patch("pippal.engine.winsound.PlaySound"):
            engine.seek(-1)

        overlay.set_state.assert_called_with("thinking")

    def test_seek_noop_when_no_chunks(self) -> None:
        """seek() with no chunks must not call overlay at all (no state)."""
        engine, overlay = self._make_engine_with_overlay()
        # _chunks is empty by default

        with patch("pippal.engine.winsound.PlaySound"):
            engine.seek(-1)

        overlay.start_chunk.assert_not_called()
        overlay.set_state.assert_not_called()

    def test_seek_forward_shows_target_text_immediately(self) -> None:
        """Forward seek also benefits: next chunk text shown immediately."""
        engine, overlay = self._make_engine_with_overlay()
        chunks = ["first sentence.", "second sentence.", "third sentence."]
        self._seed_chunks(engine, chunks)

        with patch("pippal.engine.winsound.PlaySound"):
            engine.seek(+1)  # target = chunk idx 3, clamped to 2

        overlay.start_chunk.assert_called_once()
        call_args = overlay.start_chunk.call_args
        assert call_args.args[0] == "third sentence."
