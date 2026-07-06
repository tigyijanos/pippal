"""Sentence-by-sentence playback loop.

Drives one chunk at a time: synthesise, play, watch for seek/pause/
cancel, advance. Uses `winsound` for audio and reports state via the
overlay attached to the engine.

Lives outside `pippal.engine` so the engine module stays focused on
public-API + state ownership; the loop machinery is verbose enough to
deserve its own file."""

from __future__ import annotations

import logging
import tempfile
import threading
import time
import uuid
import wave
import winsound
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from . import plugins
from .config import DEFAULT_CONFIG
from .engines.base import TTSBackend
from .i18n import t as _t
from .paths import TEMP_DIR
from .text_utils import split_sentences
from .timing import (
    CHUNK_DEADLINE_PAD_S,
    PAUSE_POLL_S,
    PLAYBACK_POLL_S,
    PREFETCH_DRAIN_S,
)
from .wav_utils import safe_unlink, wav_duration

if TYPE_CHECKING:  # pragma: no cover
    from .engine import TTSEngine


# ---------------------------------------------------------------------------
# Structured playback diagnostics (Pro-agnostic, privacy-by-construction)
# ---------------------------------------------------------------------------
#
# WHY THIS LIVES IN CORE: the user's diagnostics Trace was empty on a real
# read because only the Pro Kokoro backend emitted any diag event — the
# DEFAULT Piper engine and this core playback loop (the path EVERY engine
# goes through) emitted ZERO events.  So a real read under Trace produced no
# genuine playback/synth event for any non-Kokoro engine.
#
# LEAK-SAFE BY CONSTRUCTION: core must NOT import or depend on an optional
# external diagnostics module.  Instead this emits a plain stdlib ``logging``
# record on a DEDICATED logger name with METADATA-ONLY structured fields
# carried in ``extra`` — never the read text.  The log message body is the
# empty string, so even an optional redaction layer (which blanks legacy
# record messages) has nothing to scrub.  An optional diagnostics handler
# (when installed on the root logger at trace/error) recognises this dedicated
# logger + the ``diag_evt`` marker and surfaces it as a structured,
# non-``legacy`` event, re-whitelisting every field through its own privacy
# guard.  When no optional handler is attached (the public core app, or
# diagnostics off) this is a cheap no-op: the record propagates to a root
# logger with no diag handler and is dropped.
#
# The fields are strictly metadata: chunk character COUNT (an int, never the
# text), chunk index/total, and the engine NAME (an enum-like id such as
# "piper"/"kokoro").  No document content can flow through here.
_PLAYBACK_DIAG_LOGGER_NAME = "pippal.playback"
_PLAYBACK_DIAG_LOGGER = logging.getLogger(_PLAYBACK_DIAG_LOGGER_NAME)

# The structured-event name a real chunk-start emits.  A consumer (Pro
# diagnostics) keys off this value; it is duplicated as a constant there.
PLAYBACK_DIAG_EVT_CHUNK = "playback.chunk"


def emit_playback_chunk_diag(
    *, char_count: int, chunk_index: int, chunk_total: int, engine: str | None
) -> None:
    """Emit a metadata-only structured ``playback.chunk`` diagnostic.

    Fired when a real chunk genuinely begins playing so that Trace contains a
    real playback event for EVERY engine (the default Piper read included),
    not just the Pro Kokoro path.

    Privacy: only the chunk's character COUNT, its index/total and the engine
    id are emitted — NEVER the read text.  The log message body is empty.
    This never raises: diagnostics must never break playback.
    """
    try:
        if not _PLAYBACK_DIAG_LOGGER.isEnabledFor(logging.DEBUG):
            # No handler wants DEBUG records (e.g. no Pro trace handler
            # installed) — skip the makeRecord cost entirely.
            return
        extra = {
            "diag_evt": PLAYBACK_DIAG_EVT_CHUNK,
            "char_count": int(char_count),
            "chunk_index": int(chunk_index),
            "chunk_total": int(chunk_total),
        }
        if engine:
            extra["engine"] = str(engine)
        _PLAYBACK_DIAG_LOGGER.debug("", extra=extra)
    except Exception:
        pass


class WaitResult(Enum):
    """Outcome of waiting for one chunk's playback."""

    COMPLETED = "completed"  # natural end of chunk
    SEEKED = "seeked"  # user requested prev/next/replay
    RETRYABLE = "retryable"  # playback fallback failed; keep current chunk
    CANCELLED = "cancelled"  # stop() bumped the token


@dataclass(slots=True)
class PlaybackSession:
    """One run of `play_one` — owns the per-call state so the playback
    loop can pass it around instead of dragging seven parameters."""

    chunks: list[str]
    chunk_paths: list[Path]
    backend: TTSBackend | None = None
    prefetch_threads: dict[int, threading.Thread] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level flows
# ---------------------------------------------------------------------------


def synthesize_and_play(
    engine: TTSEngine,
    text: str,
    my_token: int,
    backend: TTSBackend | None = None,
) -> None:
    """Play `text`, then drain `engine._queue`. Tokens guard cancellation."""
    play_one(engine, text, my_token, backend=backend)
    while True:
        with engine.lock:
            if my_token != engine.token:
                return
            if not engine._queue:
                engine.is_speaking = False
                break
            next_text = engine._queue.pop(0)
        engine._remember(next_text)
        play_one(engine, next_text, my_token, backend=backend)
    ov = engine._overlay()
    if ov is not None:
        ov.set_state("done")


def play_one(
    engine: TTSEngine,
    text: str,
    my_token: int,
    backend: TTSBackend | None = None,
) -> None:
    """Drive the per-text playback loop. Returns when the text has
    finished playing, the user cancelled, or synthesis failed."""
    chunks = split_sentences(plugins.apply_text_transforms(text))
    if not chunks:
        return
    # Pin a single backend for the whole text. Without this, a mid-text
    # mood change (apply_mood -> reset_backend) would cause the next
    # chunk to use a fresh backend with a new voice, swapping the
    # speaker mid-paragraph. Translate already passes its own one-off
    # backend, so respect that.
    if backend is None:
        backend = engine._get_backend()
    session = PlaybackSession(
        chunks=chunks,
        chunk_paths=_chunk_paths(my_token, len(chunks)),
        backend=backend,
    )

    if not _prepare_first_chunk(engine, session, my_token):
        return

    idx = 0
    while idx < len(session.chunks):
        if engine._is_cancelled(my_token):
            _cancel_exit(session)
            return

        with engine.lock:
            engine._chunk_idx = idx
            engine._skip_to = None

        if not _ensure_chunk_ready(engine, session, idx):
            # _ensure_chunk_ready bailed. Distinguish a SUPERSESSION (a
            # navigation arrived mid-synth and set _skip_to to a new target)
            # from a genuine synth FAILURE / hung-prefetch (no pending nav).
            # Supersession is *defined* by _skip_to being set, so honour it:
            # jump the loop to the settled target instead of blindly stepping
            # to idx + 1. Without this, the final settled target reached via
            # the supersede path is never driven to _play_chunk ->
            # set_state("reading") and the overlay stays stuck in "thinking"
            # (is_synthesizing never clears) — the rapid-Forward wedge.
            with engine.lock:
                pending = engine._skip_to
                if pending is not None:
                    pending = max(0, min(len(session.chunks) - 1, pending))
                    engine._skip_to = None
            if pending is not None:
                idx = pending
            else:
                idx += 1
            continue
        if engine._is_cancelled(my_token):
            _cancel_exit(session)
            return

        _kick_prefetch(engine, session, idx + 1)
        next_idx = _play_chunk(engine, session, idx, my_token)
        if next_idx is None:
            return  # cancelled — _play_chunk already cleaned up
        idx = next_idx

    with engine.lock:
        if my_token == engine.token:
            engine._chunks = []
            engine._chunk_paths = []
    _cancel_exit(session)


# ---------------------------------------------------------------------------
# Per-chunk helpers
# ---------------------------------------------------------------------------


def _chunk_paths(my_token: int, count: int) -> list[Path]:
    """Return fresh temp paths for one playback session.

    ``my_token`` is only process-local and starts from 0 after restart,
    so include a session nonce to avoid replaying stale WAVs that were
    left behind by a crash or failed cleanup in a previous process.
    """
    session_id = uuid.uuid4().hex
    return [TEMP_DIR / f"out_{my_token}_{session_id}_{i}.wav" for i in range(count)]


def _prepare_first_chunk(
    engine: TTSEngine,
    session: PlaybackSession,
    my_token: int,
) -> bool:
    """Synth the first chunk synchronously so playback starts fast.
    Publishes session state under engine.lock for the mini-player."""
    if not engine._synthesize(session.chunks[0], session.chunk_paths[0], backend=session.backend):
        ov = engine._overlay()
        if ov is not None:
            ov.show_message(_t("overlay.msg.synthesis_failed"))
        return False
    if engine._is_cancelled(my_token):
        safe_unlink(session.chunk_paths[0])
        return False
    with engine.lock:
        engine._chunks = session.chunks
        engine._chunk_paths = session.chunk_paths
        engine._chunk_idx = 0
        engine._skip_to = None
    return True


def _ensure_chunk_ready(
    engine: TTSEngine,
    session: PlaybackSession,
    idx: int,
) -> bool:
    """Block until session.chunk_paths[idx] is a usable WAV. Waits on
    any in-flight prefetch first to avoid two writers racing on the
    same file. Returns False if synth failed or a prefetch is still
    alive after the timeout (refusing to race on the same path)."""
    wav_path = session.chunk_paths[idx]
    existing = session.prefetch_threads.get(idx)
    if existing is not None and existing.is_alive():
        existing.join(timeout=20)
        if existing.is_alive():
            # Prefetch is still writing. Don't start a second writer on
            # the same wav_path — a hung synth here means the user gets
            # a "skipped" chunk, which is better than a corrupt one.
            # Leave the handle in the dict so a later seek-back to this
            # idx will re-join the same writer instead of orphaning it.
            return False
    # Join finished (or there was no prefetch) — drop the dead handle.
    session.prefetch_threads.pop(idx, None)
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        # Genuine cache MISS: a real synth must run, so announce the loader
        # via the authoritative synth event. (A cache HIT skips this entirely,
        # so the loader never shows for an already-prefetched chunk — the
        # "loader longer than the load" symptom.)
        ov = engine._overlay()
        if ov is not None and hasattr(ov, "begin_synth"):
            ov.begin_synth()
        # Cancel-on-navigate: if the user pressed forward/back again while we
        # were about to synth (or during it), this target is now stale. Abort
        # so the loop can advance to the new target instead of wedging behind a
        # blocking synth. ``_synth_superseded`` is the cooperative cancel hook
        # the engine exposes (checks _skip_to / token against this idx).
        if engine._synth_superseded(target_idx=idx):
            if ov is not None and hasattr(ov, "end_synth"):
                ov.end_synth()
            return False
        if not engine._synthesize(session.chunks[idx], wav_path, backend=session.backend):
            safe_unlink(wav_path)
            if ov is not None and hasattr(ov, "end_synth"):
                ov.end_synth()
            return False
        # The synth may have completed AFTER a navigation arrived — re-check so
        # we don't play a stale target the user already skipped past.
        if engine._synth_superseded(target_idx=idx):
            if ov is not None and hasattr(ov, "end_synth"):
                ov.end_synth()
            return False
    return True


def _kick_prefetch(
    engine: TTSEngine,
    session: PlaybackSession,
    target_idx: int,
) -> None:
    """Start synthesising chunk `target_idx` in the background if nobody
    else already is."""
    if target_idx >= len(session.chunks):
        return
    p = session.chunk_paths[target_idx]
    if p.exists() and p.stat().st_size > 0:
        return
    existing = session.prefetch_threads.get(target_idx)
    if existing is not None and existing.is_alive():
        return
    t = threading.Thread(
        target=engine._synthesize,
        args=(session.chunks[target_idx], p, session.backend),
        daemon=True,
    )
    t.start()
    session.prefetch_threads[target_idx] = t


def _play_chunk(
    engine: TTSEngine,
    session: PlaybackSession,
    idx: int,
    my_token: int,
) -> int | None:
    """Play `session.chunks[idx]` and wait for completion. Returns the
    next idx to play, or None if cancelled."""
    chunks = session.chunks
    wav_path = session.chunk_paths[idx]
    dur = wav_duration(wav_path)

    # Arm the overlay's "reading" state and publish karaoke word timings
    # BEFORE attempting winsound playback so the overlay always transitions
    # to "reading" with chunk_text populated even if audio output fails
    # (e.g. no audio device, format mismatch, exclusive-mode lock).
    # Without this, a PlaySound exception caused the overlay to stay stuck
    # in "loading" and jump directly to "done" — the karaoke window was
    # always empty/black on any read that couldn't play audio.
    ov = engine._overlay()
    if ov is not None:
        # Re-assert "reading" on EVERY chunk entry, not just idx 0. A seek
        # (engine.seek) flips the overlay to "thinking" to show the loader
        # while the target chunk may re-synthesise; without this unconditional
        # re-assert, a forward/back to any non-zero chunk left the overlay
        # stuck in "thinking"/loading forever (the BIG multi-page nav wedge).
        # ``start_chunk`` clears the synth flag (audio-ready event) so the
        # loader hides as soon as this chunk's audio is about to play.
        ov.set_state("reading")
        offset = _karaoke_offset_s(engine)
        ov.start_chunk(chunks[idx], dur, idx, len(chunks), offset_s=offset)

    try:
        winsound.PlaySound(
            str(wav_path),
            winsound.SND_FILENAME | winsound.SND_ASYNC,
        )
    except Exception:
        safe_unlink(wav_path)
        return idx + 1

    # A real chunk is now genuinely playing — emit a metadata-only structured
    # playback diagnostic so Trace records a real playback event for EVERY
    # engine on the real read path (the default Piper read included), not only
    # the Pro Kokoro synth path.  char_count is a length only; the read text
    # never leaves this process via diagnostics.
    backend = session.backend
    emit_playback_chunk_diag(
        char_count=len(chunks[idx]),
        chunk_index=idx,
        chunk_total=len(chunks),
        engine=getattr(backend, "name", None) if backend is not None else None,
    )

    result = _wait_for_chunk_end(
        engine,
        my_token,
        dur,
        wav_path,
        chunks,
        idx,
    )
    if result is WaitResult.CANCELLED:
        _cancel_exit(session)
        return None
    if result is WaitResult.SEEKED:
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        with engine.lock:
            target = engine._skip_to
            engine._skip_to = None
        if target is not None:
            return max(0, min(len(chunks) - 1, target))
    if result is WaitResult.RETRYABLE:
        return idx

    safe_unlink(wav_path)
    return idx + 1


def _tail_wav_from_elapsed(wav_path: Path, elapsed_s: float) -> tuple[Path, float] | None:
    """Create a temporary WAV containing only frames after `elapsed_s`."""
    try:
        with wave.open(str(wav_path), "rb") as src:
            params = src.getparams()
            frame_rate = src.getframerate()
            total_frames = src.getnframes()
            start_frame = max(0, min(total_frames, int(elapsed_s * frame_rate)))
            remaining_frames = total_frames - start_frame
            if remaining_frames <= 0:
                return None
            src.setpos(start_frame)
            frames = src.readframes(remaining_frames)
    except (OSError, wave.Error):
        return None

    try:
        tail_file = tempfile.NamedTemporaryFile(
            prefix=f"{wav_path.stem}_tail_",
            suffix=".wav",
            dir=wav_path.parent,
            delete=False,
        )
    except OSError:
        return None
    tail_path = Path(tail_file.name)
    tail_file.close()
    try:
        with wave.open(str(tail_path), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(frames)
    except (OSError, wave.Error):
        safe_unlink(tail_path)
        return None

    return tail_path, remaining_frames / frame_rate


def _wait_for_chunk_end(
    engine: TTSEngine,
    my_token: int,
    dur: float,
    wav_path: Path,
    chunks: list[str],
    idx: int,
) -> WaitResult:
    """Block until the chunk finishes, the user seeks, or playback is
    cancelled. Cleanup of files and prefetch threads happens at the
    `_play_chunk` cancel branch via `_cancel_exit`."""
    deadline = time.time() + dur + CHUNK_DEADLINE_PAD_S
    playback_started_at = time.monotonic()
    resume_tail_path: Path | None = None
    ov = engine._overlay()

    def purge_audio() -> None:
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def cleanup_resume_tail(*, purge_first: bool = False) -> None:
        nonlocal resume_tail_path
        if resume_tail_path is None:
            return
        if purge_first:
            purge_audio()
        safe_unlink(resume_tail_path)
        resume_tail_path = None

    def restart_original_chunk() -> bool:
        nonlocal deadline, playback_started_at
        cleanup_resume_tail(purge_first=True)
        try:
            winsound.PlaySound(
                str(wav_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC,
            )
        except Exception:
            return False
        if ov is not None:
            offset = _karaoke_offset_s(engine)
            ov.start_chunk(chunks[idx], dur, idx, len(chunks), offset_s=offset)
        playback_started_at = time.monotonic()
        deadline = time.time() + dur + CHUNK_DEADLINE_PAD_S
        return True

    while time.time() < deadline:
        if engine._is_cancelled(my_token):
            purge_audio()
            cleanup_resume_tail()
            return WaitResult.CANCELLED
        with engine.lock:
            if engine._skip_to is not None:
                cleanup_resume_tail(purge_first=True)
                return WaitResult.SEEKED
            paused = engine._is_paused
        if paused:
            elapsed_s = max(0.0, min(dur, time.monotonic() - playback_started_at))
            # Hold; pause_toggle silenced audio and froze the overlay.
            while True:
                if engine._is_cancelled(my_token):
                    purge_audio()
                    cleanup_resume_tail()
                    return WaitResult.CANCELLED
                with engine.lock:
                    if not engine._is_paused or engine._skip_to is not None:
                        break
                time.sleep(PAUSE_POLL_S)
            # If the user pressed prev/next while paused, hand the seek
            # back WITHOUT restarting playback.
            with engine.lock:
                if engine._skip_to is not None:
                    cleanup_resume_tail(purge_first=True)
                    return WaitResult.SEEKED
            # Resumed: continue from the remaining WAV frames instead of
            # replaying the full chunk from the beginning when possible.
            tail = _tail_wav_from_elapsed(wav_path, elapsed_s)
            if tail is None:
                if not restart_original_chunk():
                    return WaitResult.RETRYABLE
                continue
            cleanup_resume_tail(purge_first=True)
            resume_tail_path, remaining_dur = tail
            try:
                winsound.PlaySound(
                    str(resume_tail_path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )
            except Exception:
                if not restart_original_chunk():
                    return WaitResult.RETRYABLE
                continue
            if ov is not None:
                # Single source of truth for resume-elapsed: hand the
                # audio tail's ``elapsed_s`` to the overlay clock directly
                # via ``resume_elapsed_s`` (NOT folded into ``offset_s``).
                # ``set_paused(False)`` no longer rebases ``_chunk_start``,
                # so this is the only rebase on resume — the double-reset
                # race that restarted the karaoke highlight from word 0 is
                # gone, and the highlight stays within one word of audio.
                ov.start_chunk(
                    chunks[idx],
                    remaining_dur,
                    idx,
                    len(chunks),
                    offset_s=_karaoke_offset_s(engine),
                    resume_elapsed_s=elapsed_s,
                )
            playback_started_at = time.monotonic() - elapsed_s
            deadline = time.time() + remaining_dur + CHUNK_DEADLINE_PAD_S
            continue
        time.sleep(PLAYBACK_POLL_S)
    cleanup_resume_tail()
    return WaitResult.COMPLETED


def _karaoke_offset_s(engine: TTSEngine) -> float:
    """How far the karaoke timer is shifted into the future to compensate
    for winsound startup latency."""
    return (
        float(
            engine.config.get("karaoke_offset_ms", DEFAULT_CONFIG["karaoke_offset_ms"]),
        )
        / 1000.0
    )


def _cleanup_chunk_paths(paths: list[Path]) -> None:
    for p in paths:
        safe_unlink(p)


def _cancel_exit(session: PlaybackSession) -> None:
    """Drain any in-flight prefetch threads (best-effort, short timeout)
    before unlinking chunk files. Without the drain, a running prefetch
    could write a wav to TEMP_DIR after we've already cleaned up,
    leaving an orphan until the next process restart."""
    for t in list(session.prefetch_threads.values()):
        if t.is_alive():
            t.join(timeout=PREFETCH_DRAIN_S)
    session.prefetch_threads.clear()
    _cleanup_chunk_paths(session.chunk_paths)
