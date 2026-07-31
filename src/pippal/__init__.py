"""PipPal — your little offline reading buddy.

Tray-resident Windows app that reads selected text aloud using the
Piper neural TTS engine, with an animated reader panel and right-click
integration. Optional extension packages can self-register additional
engines and selection-driven actions through ``pippal.plugins``.

Public API:
- `main()`     — entry point used by `python -m pippal` and reader_app_web.py
- `TTSEngine`  — orchestration class
"""
# ruff: noqa: E402
# Import order is intentional: registries must be populated by
# _register + extension entry-point loading BEFORE the app/engine modules are
# imported, in case a future change has them read the registry at
# import time. Letting ruff re-sort would re-introduce the bug.

from . import _register  # noqa: F401  (side-effect: built-in registration)
from . import plugins as _plugins

# Discover optional extension plugins. Each entry point self-registers
# through pippal.plugins; failures are logged loudly rather than swallowed.
_plugins.load_extension_plugins()

# Define the package version BEFORE importing the web UI: the web bridge
# does ``from .. import __version__`` at import time, so the name must
# already exist on the partially-initialised package.
__version__ = "0.3.2"

from .engine import TTSEngine
from .web_ui.app_web import main

__all__ = ["TTSEngine", "main"]
