"""JS <-> Python bridge for the web UI.

Every method here maps onto the EXISTING backend; none of them change
backend behaviour. The same object is exposed two ways:

* as a pywebview ``js_api`` object (desktop) — methods callable as
  ``window.pywebview.api.<name>(...)``;
* over a localhost JSON POST (served / E2E mode) — see
  :mod:`pippal.web_ui.server`.

Window-opening methods (``open_settings_window`` etc.) call back into
the host app through callbacks injected at construction so onboarding
can launch Settings / Voice Manager exactly like the Tk flow does.
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from typing import Any

from .. import __version__, plugins
from ..config import _layered_defaults, save_config
from ..context_menu import (
    context_menu_status,
    install_context_menu,
    uninstall_context_menu,
)
from ..i18n import t as _t
from ..onboarding import (
    activation_sample_text,
    build_activation_readiness,
    default_piper_voice,
    load_activation_state,
    mark_activation_complete,
)
from ..paths import VOICES_DIR
from ..voices import installed_voices, locale_name, voice_filename
from .bridge_diag_settings import DiagSettingsBridgeMixin
from .i18n_view import language_config_view
from .overlay_state import WebOverlay


class PipPalBridge(DiagSettingsBridgeMixin):
    """Backend facade the web frontend talks to.

    ``engine`` is the real :class:`pippal.engine.TTSEngine`. ``overlay``
    is a :class:`WebOverlay` (or the Tk overlay) the engine already
    drives. ``host`` carries optional callbacks the windows need.
    """

    def __init__(
        self,
        engine: Any,
        config: dict[str, Any],
        overlay: WebOverlay | None = None,
        *,
        on_open_settings: Callable[[], None] | None = None,
        on_open_voice_manager: Callable[[], None] | None = None,
        on_open_notices: Callable[[], None] | None = None,
        on_close_window: Callable[[], None] | None = None,
        on_hotkey_change: Callable[[], list[tuple[str, str, str]] | None] | None = None,
        on_engine_change: Callable[[], None] | None = None,
    ) -> None:
        self.engine = engine
        self.config = config
        self.overlay = overlay
        self._on_open_settings = on_open_settings
        self._on_open_voice_manager = on_open_voice_manager
        self._on_open_notices = on_open_notices
        self._on_close_window = on_close_window
        self._on_hotkey_change = on_hotkey_change
        self._on_engine_change = on_engine_change
        self._install_lock = threading.Lock()
        # Async voice install task registry (progress + cancel).
        self._voice_task_lock = threading.Lock()
        self._voice_tasks: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Config (pippal.config — unchanged)
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        # Augment with the resolved UI language + picker options (i18n §5.3).
        return language_config_view(self.config)

    def get_defaults(self) -> dict[str, Any]:
        return _layered_defaults()

    def get_engines(self) -> list[str]:
        return sorted(plugins.engines().keys()) or ["piper"]

    def get_hotkey_actions(self) -> list[list[str]]:
        # (action_id, config_key, label, default_combo) — same source
        # the Tk Hotkeys card iterates.
        return [list(a) for a in plugins.hotkey_actions()]

    def about_info(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "links": [
                {"key": "website", "text": _t("about.link.website"), "url": "https://pippal.bugfactory.hu"},
                {
                    "key": "github",
                    "text": _t("about.link.github"),
                    "url": "https://github.com/bug-factory-kft/pippal",
                },
                {
                    "key": "licence",
                    "text": _t("about.link.licence"),
                    "url": "https://github.com/bug-factory-kft/pippal/blob/main/LICENSE.md",
                },
                {
                    "key": "privacy",
                    "text": _t("about.link.privacy"),
                    "url": "https://github.com/bug-factory-kft/pippal/blob/main/docs/PRIVACY.md",
                },
                {
                    "key": "terms",
                    "text": _t("about.link.terms"),
                    "url": "https://github.com/bug-factory-kft/pippal/blob/main/docs/TERMS.md",
                },
                {
                    "key": "reddit",
                    "text": _t("about.link.reddit"),
                    "url": "https://www.reddit.com/r/PipPalApp/",
                },
            ],
        }

    def save_config(
        self,
        values: dict[str, Any],
        close: bool = False,
    ) -> dict[str, Any]:
        """Persist form values: validate engine, normalise hotkeys,
        rebind hotkeys, drop the cached backend so the next synth picks
        up the new config."""
        candidate = dict(self.config)
        values = dict(values or {})

        eng = str(values.pop("engine", candidate.get("engine", "piper"))).lower()
        candidate["engine"] = eng

        if "voice" in values:
            candidate["voice"] = values.pop("voice")
        if "length_scale" in values:
            candidate["length_scale"] = round(float(values.pop("length_scale")), 3)

        hotkey_keys = {a[1] for a in plugins.hotkey_actions()}
        for key, value in values.items():
            if isinstance(value, str):
                value = value.strip()
                if key in hotkey_keys or key.startswith("hotkey_"):
                    value = value.lower()
            candidate[key] = value

        save_config(candidate)

        prev_hotkeys = {k: self.config.get(k, "") for k in hotkey_keys}
        self.config.clear()
        self.config.update(candidate)

        result: dict[str, Any] = {"ok": True, "config": dict(self.config)}

        # Re-activate the resolved UI language so on-demand Python surfaces
        # (toasts, native titles) render in the new language immediately, and
        # so any web window opened/reloaded next boots in it (T-107; design
        # §5.5 — the tray menu, built once at startup, stays restart-required).
        # ``language_resolved`` is echoed back so the frontend knows the
        # concrete tag a reload will boot in.
        try:
            from ..i18n import get_language, set_language

            set_language(candidate.get("language", ""))
            result["language_resolved"] = get_language()
        except Exception:
            pass

        hotkeys_changed = any(prev_hotkeys.get(k, "") != candidate.get(k, "") for k in hotkey_keys)
        if hotkeys_changed and self._on_hotkey_change is not None:
            try:
                failures = self._on_hotkey_change() or []
            except Exception as exc:  # pragma: no cover - defensive
                result["hotkey_failures"] = [["?", "?", str(exc)]]
            else:
                result["hotkey_failures"] = [list(f) for f in failures]

        if self._on_engine_change is not None:
            try:
                self._on_engine_change()
            except Exception:
                pass
        else:
            # No host hook (served/E2E mode): drop backend cache so next synth
            # honours the new config — same effect as on_engine_change hook.
            try:
                self.engine.reset_backend()
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # Voices (pippal.voices / pippal.voice_install)
    # ------------------------------------------------------------------

    def get_installed_voices(self) -> list[str]:
        return installed_voices()

    def get_voice_catalogue(self) -> dict[str, Any]:
        installed = set(installed_voices())
        catalogue = sorted(
            plugins.voices(),
            key=lambda v: (locale_name(v["lang"]), v["id"]),
        )
        voices = [
            {
                "id": v["id"],
                "lang": v["lang"],
                "name": v["name"],
                "quality": v["quality"],
                "label": v["label"],
                "installed": voice_filename(v) in installed,
            }
            for v in catalogue
        ]
        langs = sorted({v["lang"] for v in catalogue}, key=locale_name)
        return {
            "voices": voices,
            "languages": [{"code": c, "name": locale_name(c)} for c in langs],
        }

    def _voice_by_id(self, voice_id: str) -> Any:
        for v in plugins.voices():
            if v["id"] == voice_id:
                return v
        raise RuntimeError(f"unknown voice: {voice_id}")

    def install_voice(self, voice_id: str) -> dict[str, Any]:
        from ..voice_install import install_piper_voice

        with self._install_lock:
            v = self._voice_by_id(voice_id)
            filename = install_piper_voice(v)
        # Set the installed voice on the shared config dict so onboarding's
        # readiness check flips to ready immediately after install.
        self.config["voice"] = filename
        try:
            self.engine.reset_backend()
        except Exception:
            pass
        return {"ok": True, "installed": filename}

    def _stream_voice_with_progress(
        self,
        voice: Any,
        is_cancelled: Any,
        set_progress: Any,
    ) -> str:
        """Download a Piper voice pair (.onnx + .onnx.json) in chunks.

        Reports progress via ``set_progress(pct=..., status=...)``, checks
        ``is_cancelled()`` on every chunk.  Uses atomic ``.part`` rename so
        a partial download never leaves broken files in place.
        """
        import os as _os
        import urllib.request as _urlreq

        from ..timing import DOWNLOAD_TIMEOUT_S
        from ..voice_install import _encode_download_url
        from ..voices import voice_filename, voice_url_base

        filename = voice_filename(voice)
        base = voice_url_base(voice)
        label = voice.get("label", filename) if isinstance(voice, dict) else filename
        onnx_dest = VOICES_DIR / filename
        json_dest = VOICES_DIR / f"{filename}.json"
        onnx_part = VOICES_DIR / f"{filename}.part"
        json_part = VOICES_DIR / f"{filename}.json.part"
        VOICES_DIR.mkdir(parents=True, exist_ok=True)

        _CHUNK = 1 << 16  # 64 KB

        def _cleanup() -> None:
            for p in (onnx_part, json_part):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

        def _download_one(url: str, dest: Any, base_pct: float, span: float, dlabel: str) -> None:
            url = _encode_download_url(url)
            set_progress(status=_t("voice.status.downloading", {"label": dlabel}))
            with _urlreq.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as resp, \
                    open(str(dest), "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                while True:
                    if is_cancelled():
                        raise InterruptedError("cancelled")
                    buf = resp.read(_CHUNK)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if total > 0:
                        set_progress(pct=base_pct + span * downloaded / total)
            if _os.path.getsize(str(dest)) == 0:
                raise RuntimeError(f"empty response for {dlabel}")

        try:
            _download_one(base + filename, onnx_part, 0.0, 80.0, label)
            if is_cancelled():
                _cleanup()
                raise InterruptedError("cancelled")
            _download_one(base + f"{filename}.json", json_part, 80.0, 18.0, "metadata")
            if is_cancelled():
                _cleanup()
                raise InterruptedError("cancelled")
        except Exception:
            _cleanup()
            raise

        _os.replace(str(onnx_part), str(onnx_dest))
        _os.replace(str(json_part), str(json_dest))
        return filename

    def _start_voice_install_async(
        self,
        voice_getter: Callable[[], dict[str, Any]],
        *,
        start_msg: str | None = None,
    ) -> dict[str, Any]:
        """Internal: start a voice download on a background thread; return task_id.

        ``voice_getter`` is called on the thread to resolve the voice dict.
        Returns ``{"ok": True, "task_id": str}`` immediately.
        """
        import uuid

        if start_msg is None:
            start_msg = _t("voice.status.starting")
        task_id = uuid.uuid4().hex
        with self._voice_task_lock:
            self._voice_tasks[task_id] = {
                "running": True, "pct": 0.0, "status": start_msg,
                "error": "", "done": False, "cancelled": False, "installed": None,
            }

        def _is_cancelled() -> bool:
            with self._voice_task_lock:
                return bool(self._voice_tasks.get(task_id, {}).get("cancelled"))

        def _set(pct: float | None = None, status: str | None = None) -> None:
            with self._voice_task_lock:
                t = self._voice_tasks.get(task_id)
                if t is None:
                    return
                if pct is not None:
                    t["pct"] = max(0.0, min(100.0, float(pct)))
                if status is not None:
                    t["status"] = status

        def _run() -> None:
            try:
                voice = voice_getter()
                filename = self._stream_voice_with_progress(voice, _is_cancelled, _set)
                self.config["voice"] = filename
                try:
                    save_config(self.config)
                except Exception:
                    pass
                try:
                    self.engine.reset_backend()
                except Exception:
                    pass
                _set(pct=100.0, status=_t("voice.status.done"))
                with self._voice_task_lock:
                    t = self._voice_tasks.get(task_id, {})
                    t["installed"] = filename
                    t["done"] = True
                    t["running"] = False
            except Exception as exc:
                cancelled = _is_cancelled()
                with self._voice_task_lock:
                    t = self._voice_tasks.get(task_id, {})
                    if t is not None:
                        t["error"] = str(exc)
                        t["status"] = _t("voice.status.cancelled") if cancelled else _t("voice.status.failed", {"error": str(exc)[:200]})
                        t["cancelled"] = cancelled
                        t["done"] = True
                        t["running"] = False

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "task_id": task_id}

    def install_voice_async(self, voice_id: str) -> dict[str, Any]:
        """Start a named Piper voice install on a background thread.

        Returns ``{"ok": True, "task_id": str}`` immediately.  Poll progress
        via :meth:`voice_install_status`; cancel via
        :meth:`cancel_voice_install`.  Back-compat: if the caller doesn't
        find a ``task_id`` in the response it should fall back to the sync
        :meth:`install_voice`.
        """
        return self._start_voice_install_async(lambda: self._voice_by_id(voice_id))

    def install_default_voice_async(self) -> dict[str, Any]:
        """Start the default Piper voice install on a background thread.

        Returns ``{"ok": True, "task_id": str}`` immediately.  Poll progress
        via :meth:`voice_install_status`; cancel via
        :meth:`cancel_voice_install`.  Back-compat: sync
        :meth:`install_default_voice` remains for callers that don't handle
        a task_id.
        """
        return self._start_voice_install_async(
            default_piper_voice, start_msg=_t("voice.status.downloading_default")
        )

    def voice_install_status(self, task_id: str) -> dict[str, Any]:
        """Return current state of a background voice install task.

        Returns a copy of the task dict, or ``{"done": True, "error":
        "task not found"}`` if the id is unknown.
        """
        with self._voice_task_lock:
            t = self._voice_tasks.get(task_id)
            if t is None:
                return {"done": True, "error": "task not found", "running": False}
            return dict(t)

    def cancel_voice_install(self, task_id: str) -> dict[str, Any]:
        """Signal a background voice install to cancel (sets flag; async)."""
        with self._voice_task_lock:
            t = self._voice_tasks.get(task_id)
            if t is None:
                return {"ok": False, "error": "task not found"}
            if not t["running"]:
                return {"ok": True, "was_running": False}
            t["cancelled"] = True
        return {"ok": True, "was_running": True}

    def remove_voice(self, voice_id: str) -> dict[str, Any]:
        v = self._voice_by_id(voice_id)
        for f in (
            VOICES_DIR / f"{v['id']}.onnx",
            VOICES_DIR / f"{v['id']}.onnx.json",
        ):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            self.engine.reset_backend()
        except Exception:
            pass
        return {"ok": True}

    def install_default_voice(self) -> dict[str, Any]:
        from ..voice_install import install_piper_voice

        with self._install_lock:
            filename = install_piper_voice(default_piper_voice())
        self.config["voice"] = filename
        try:
            self.engine.reset_backend()
        except Exception:
            pass
        return {"ok": True, "installed": filename}

    # ------------------------------------------------------------------
    # Windows integration (pippal.context_menu — unchanged)
    # ------------------------------------------------------------------

    def context_menu_status(self) -> str:
        return context_menu_status()

    def install_context_menu(self) -> str:
        install_context_menu()
        return context_menu_status()

    def remove_context_menu(self) -> str:
        uninstall_context_menu()
        return context_menu_status()

    # ------------------------------------------------------------------
    # Onboarding (pippal.onboarding — unchanged)
    # ------------------------------------------------------------------

    def get_readiness(self) -> dict[str, Any]:
        rd = build_activation_readiness(self.config)
        return {
            "status": rd.status,
            "engine_label": rd.engine_label,
            "voice_label": rd.voice_label,
            "hotkey_label": rd.hotkey_label,
            "can_play_sample": rd.can_play_sample,
            "message": rd.message,
            "sample_text": activation_sample_text(rd.hotkey_label),
        }

    def get_activation_state(self) -> dict[str, Any]:
        st = load_activation_state()
        return {
            "is_complete": st.is_complete,
            "completed_with": st.completed_with,
            "last_failure": st.last_failure,
        }

    def play_sample(self) -> dict[str, Any]:
        rd = build_activation_readiness(self.config)
        self.engine.read_text_async(activation_sample_text(rd.hotkey_label))
        return {"ok": True}

    def mark_activation_complete(self) -> dict[str, Any]:
        mark_activation_complete("sample")
        return {"ok": True}

    # ------------------------------------------------------------------
    # Reading / engine
    # ------------------------------------------------------------------

    def read_text(self, text: str) -> dict[str, Any]:
        self.engine.read_text_async(str(text or ""))
        return {"ok": True}

    def overlay_action(self, tag: str) -> dict[str, Any]:
        if tag == "close":
            self.engine.stop()
        elif tag == "prev":
            self.engine.prev_chunk()
        elif tag == "replay":
            self.engine.replay_chunk()
        elif tag == "next":
            self.engine.next_chunk()
        elif tag == "pause":
            self.engine.pause_toggle()
        else:
            raise RuntimeError(f"unknown overlay action: {tag}")
        return {"ok": True}

    def engine_state(self) -> dict[str, Any]:
        snap: dict[str, Any] = {
            "brand_name": self.config.get("brand_name", "PipPal"),
            "karaoke_offset_ms": int(self.config.get("karaoke_offset_ms", 0) or 0),
        }
        if self.overlay is not None and hasattr(self.overlay, "snapshot"):
            snap.update(self.overlay.snapshot())
        with self.engine.lock:
            snap["is_speaking"] = bool(self.engine.is_speaking)
            # Read _is_paused directly (not via property) to avoid a deadlock:
            # the is_paused property acquires engine.lock, which we already hold.
            snap["is_paused"] = bool(self.engine._is_paused)
            snap["backend_name"] = self.engine._backend_name
            backend_cls = self.engine._backend_cls
            snap["backend_class"] = backend_cls.__name__ if backend_cls is not None else None
            snap["chunk_count"] = len(self.engine._chunks)
            snap["chunk_paths"] = [str(p) for p in self.engine._chunk_paths]
            snap["queue_length"] = len(self.engine._queue)
        return snap

    def get_history(self) -> list[str]:
        return self.engine.get_history()

    # ------------------------------------------------------------------
    # Notices (pippal.notices resolver)
    # ------------------------------------------------------------------

    def get_notices(self) -> str:
        from ..notices import resolve_notices_path

        path = resolve_notices_path()
        if path is None:
            return _t("notices.not_found")
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:  # pragma: no cover - defensive
            return _t("notices.read_error", {"path": str(path), "error": str(exc)})

    # ------------------------------------------------------------------
    # Window control (host callbacks)
    # ------------------------------------------------------------------

    def open_settings_window(self) -> dict[str, Any]:
        if self._on_open_settings is not None:
            self._on_open_settings()
        return {"ok": True}

    def open_voice_manager_window(self) -> dict[str, Any]:
        if self._on_open_voice_manager is not None:
            self._on_open_voice_manager()
        return {"ok": True}

    def open_notices_window(self) -> dict[str, Any]:
        if self._on_open_notices is not None:
            self._on_open_notices()
        return {"ok": True}

    def close_window(self) -> dict[str, Any]:
        if self._on_close_window is not None:
            self._on_close_window()
        return {"ok": True}

    def open_url(self, url: str) -> dict[str, Any]:
        webbrowser.open(str(url))
        return {"ok": True}
