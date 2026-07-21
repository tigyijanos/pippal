"""core distribution self-registration.

Imported once at package import time (`pippal/__init__.py`) so that the
plugin registries (`pippal.plugins`) come up populated with everything
the core build provides:

- the Piper engine
- the built-in voice catalogue
- four selection-driven hotkey actions (read / queue / pause / stop)
- the core config defaults

If you're a third-party plugin author, this file is a good worked
example of how to fill the registries from your own package's
`__init__.py`.
"""

from __future__ import annotations

from typing import Any

from . import plugins
from .config import DEFAULT_CONFIG
from .engines.piper import PiperBackend


def _register() -> None:
    # ----- Engine -----
    plugins.register_engine("piper", PiperBackend)

    # ----- Voice catalogue -----
    # Built-in subset of the rhasspy/piper-voices catalogue.
    # Extension packages can extend this via plugins.register_voices().
    from .voices import KNOWN_VOICES
    plugins.register_voices(KNOWN_VOICES)

    # ----- Hotkey actions (selection-driven) -----
    # Labels are i18n catalog KEYS; the web Settings UI resolves them
    # through t() (settings.js) and falls back to the raw string for
    # third-party plugins that register a plain-English label. The EN
    # catalog carries the original English values verbatim.
    plugins.register_hotkey_action(
        "speak", "hotkey_speak", "settings.hotkeys.action.speak",
        "windows+shift+r",
    )
    plugins.register_hotkey_action(
        "queue", "hotkey_queue", "settings.hotkeys.action.queue",
        "windows+shift+q",
    )
    plugins.register_hotkey_action(
        "pause", "hotkey_pause", "settings.hotkeys.action.pause",
        "windows+shift+p",
    )
    plugins.register_hotkey_action(
        "stop", "hotkey_stop", "settings.hotkeys.action.stop",
        "windows+shift+b",
    )

    # ----- core config defaults -----
    free_defaults: dict[str, Any] = {
        k: v for k, v in DEFAULT_CONFIG.items()
        if not k.startswith("hotkey_")
    }
    plugins.register_defaults(free_defaults)


_register()
