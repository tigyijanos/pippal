"""User config — JSON-backed, dict-shaped for backwards compatibility."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .paths import CONFIG_PATH

# All hotkey-driven actions, in user-facing order. Single source of truth
# for the eight global shortcuts: the engine reads from here for
# clipboard-modifier release, the Settings UI iterates it to build the
# Hotkeys card, and `app.py` builds the keyboard / tray menu wiring
# from it. Adding a 9th action means adding ONE row here plus a method
# on `TTSEngine` and a default in `DEFAULT_CONFIG`.

# Hotkey-action metadata used to live here as a module-level tuple
# (HOTKEY_ACTIONS) plus derived views (HOTKEY_KEYS, HOTKEY_FOR_ACTION).
# Stage 1 of the plugin-host refactor moved that single source of truth
# to `pippal.plugins`: the core package self-registers its actions in
# `pippal/_register.py`, extension packages add their own, and consumers
# iterate `plugins.hotkey_actions()`.


DEFAULT_CONFIG: dict[str, Any] = {
    "brand_name": "PipPal",
    "engine": "piper",                      # "piper" | (any plugin-registered)
    "voice": "en_US-ljspeech-high.onnx",    # Piper voice file (public-domain default, #157)
    "length_scale": 1.0,
    "noise_scale": 0.667,
    "noise_w": 0.8,
    "show_overlay": True,
    "show_text_in_overlay": True,
    "auto_hide_ms": 1500,
    "overlay_y_offset": 100,
    "karaoke_offset_ms": 120,

    # UI language (BCP-47 tag, e.g. "de"). Empty string = "Auto":
    # follow the system language when it is supported, else English.
    # Resolved to a concrete tag by pippal.i18n (see i18n_fallback until
    # the T-101/T-102 engine lands) and surfaced to the web UI through
    # `get_config`. The Settings language picker writes this key via the
    # existing save_config seam — zero new config machinery (0.3.1 i18n).
    "language": "",

    # Built-in hotkeys — Windows+Shift+letter scheme. Chrome / Edge /
    # Firefox / Office never see Win-key combinations, so we don't
    # trample browser actions like Ctrl+Shift+T (reopen tab) or
    # Ctrl+Shift+Q (quit Chrome). Layout-independent: no AltGr
    # collision with Hungarian / Polish keyboards. Win+Shift combos
    # taken by Windows itself (S=screenshot, M=restore,
    # arrows=move-window) avoided; letters picked for mnemonic value
    # where possible. Extension packages register their own combos via
    # `plugins.register_hotkey_action`.
    "hotkey_speak":     "windows+shift+r",   # Read
    "hotkey_stop":      "windows+shift+b",   # Break (S is screenshot)
    "hotkey_pause":     "windows+shift+p",
    "hotkey_queue":     "windows+shift+q",
}


def _layered_defaults() -> dict[str, Any]:
    """Effective defaults = `DEFAULT_CONFIG` (the core package's
    canonical list) overlaid with whatever any plugin (including
    core `_register.py` and optional extension packages) registered.

    DEFAULT_CONFIG is kept as the in-source canonical core reference
    so existing tests, scripts, and reviewers can read one literal to
    see what the core package ships. The plugin registry adds extension
    defaults when those packages are installed."""
    from . import plugins
    merged = dict(DEFAULT_CONFIG)
    merged.update(plugins.defaults())
    return merged


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load the effective config = layered defaults + user overrides.

    User overrides are whatever the file actually contains. Unknown
    keys (e.g. an extension setting saved while its package was installed,
    then removed) are PRESERVED rather than dropped — codex'
    'Unavailable action' principle: don't destroy user state when a
    plugin disappears, the next reinstall picks up where they left
    off."""
    defaults = _layered_defaults()
    if not path.exists():
        return dict(defaults)
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception as e:
        # Don't silently throw away the user's config on a parse error —
        # rename it so they can recover, and tell them in stderr.
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(backup)
        except Exception:
            pass
        print(f"[config] {path} unreadable ({e}); moved to {backup}",
              file=sys.stderr)
        return dict(defaults)
    if not isinstance(data, dict):
        return dict(defaults)
    effective = dict(defaults)
    effective.update(data)
    return effective


def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    """Atomic write of user OVERRIDES only. Values that match the
    current layered default are dropped, so config.json stays small
    and uninstalling a plugin doesn't leave stale defaults stranded
    on disk. Unknown keys (no registered default) are preserved
    verbatim — they may belong to a plugin that's currently absent."""
    defaults = _layered_defaults()
    overrides: dict[str, Any] = {}
    for key, value in cfg.items():
        if key not in defaults or value != defaults[key]:
            overrides[key] = value
    tmp = path.with_suffix(path.suffix + ".part")
    payload = json.dumps(overrides, indent=2, ensure_ascii=False)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(str(tmp), str(path))
