"""Language view helper for the web-UI bridge (0.3.1 i18n).

Kept out of :mod:`pippal.web_ui.bridge` so that module stays small and the
resolver source is chosen in exactly one place: the real ``pippal.i18n``
engine (T-101 / T-102) when it is importable, else the standalone
:mod:`pippal.i18n_fallback` so the Settings language picker works on its own
until that engine merges. Same contract either way (design §5.3).
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised via whichever module is installed
    from ..i18n import SUPPORTED_LANGS, resolve_language
except Exception:  # pragma: no cover - fallback until pippal.i18n lands
    from ..i18n_fallback import SUPPORTED_LANGS, resolve_language
from ..i18n_fallback import native_name


def language_config_view(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``config`` augmented with the resolved UI language
    and the picker's option set (design §5.3).

    ``language`` stays the raw stored value ("" = Auto); ``language_resolved``
    is the concrete BCP-47 tag the JS renders in; ``supported_languages``
    drives the picker list from :data:`SUPPORTED_LANGS` (adding a catalog
    file adds a picker option with no UI code change). These are computed,
    read-only view keys — the Settings form never writes them back.
    """
    view = dict(config)
    raw_lang = str(view.get("language", "") or "")
    view["language_resolved"] = resolve_language(raw_lang)
    view["supported_languages"] = [
        {"tag": tag, "name": native_name(tag)} for tag in SUPPORTED_LANGS
    ]
    return view
