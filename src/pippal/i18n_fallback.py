"""Standalone language-resolution fallback for the 0.3.1 i18n work.

The real i18n engine (T-101 / T-102, module ``pippal.i18n``) lands in
parallel and supersedes this module: :mod:`pippal.web_ui.bridge` prefers
``pippal.i18n.resolve_language`` / ``SUPPORTED_LANGS`` when importable and
only falls back here, so the language-picker PR (T-103) stands alone and
integrates trivially once the engine merges.

The contract mirrors the 0.3.1 i18n design doc (§5.3 language resolution):
explicit user pick wins, else the system language if supported, else
English. Endonyms (each language shown in its OWN language) drive the
Settings picker labels.
"""

from __future__ import annotations

import sys

# BCP-47 tags the core ships catalogs for, in picker order. Once
# ``pippal.i18n`` lands it derives this list by scanning
# ``webui/i18n/*.json`` (so a 7th language is "add a catalog file, no code
# change"); here it is the design-locked core set.
SUPPORTED_LANGS: list[str] = ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]

# Endonyms — each language rendered in its own language, for the picker.
NATIVE_NAMES: dict[str, str] = {
    "en": "English",
    "zh-CN": "简体中文",
    "de": "Deutsch",
    "hu": "Magyar",
    "uk": "Українська",
    "pt-BR": "Português (Brasil)",
}

# Bare tag -> shipped regional variant (design §1 / §5.3): a system locale
# of bare "pt" / "zh" maps onto the concrete catalog we ship.
_VARIANT_MAP: dict[str, str] = {"pt": "pt-BR", "zh": "zh-CN"}


def native_name(tag: str) -> str:
    """Native (endonym) display name for ``tag``; the tag itself if
    unknown (a not-yet-named 7th language still appears in the picker)."""
    return NATIVE_NAMES.get(tag, tag)


def _system_locale() -> str:
    """Best-effort OS UI language as a BCP-47 tag ('' if unknown).

    Windows uses ``GetUserDefaultLocaleName`` via ctypes (design §5.3);
    other platforms / failures fall back to the stdlib locale. Isolated
    in its own function so tests can monkeypatch it deterministically.
    """
    if sys.platform == "win32":  # pragma: no cover - platform-specific
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            length = ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85)
            if length:
                return buf.value
        except Exception:
            pass
    try:
        import locale

        code = locale.getdefaultlocale()[0]  # e.g. "de_DE"
        if code:
            return code.replace("_", "-")
    except Exception:
        pass
    return ""


def _match_supported(tag: str) -> str:
    """Map an arbitrary BCP-47 ``tag`` onto a supported catalog tag, or
    return '' if none matches. Order: exact, then bare-tag variant, then
    any supported catalog sharing the bare language subtag."""
    if not tag:
        return ""
    if tag in SUPPORTED_LANGS:
        return tag
    bare = tag.split("-")[0].lower()
    variant = _VARIANT_MAP.get(bare)
    if variant and variant in SUPPORTED_LANGS:
        return variant
    for cand in SUPPORTED_LANGS:
        if cand.split("-")[0].lower() == bare:
            return cand
    return ""


def resolve_language(
    config_lang: str | None,
    system_locale: str | None = None,
) -> str:
    """Resolve the active language tag (design §5.3 precedence):

    1. explicit non-empty supported ``config_lang`` (user pick, permanent);
    2. the system language if supported (bare tag mapped to a shipped
       variant); ``system_locale`` defaults to :func:`_system_locale`;
    3. ``"en"``.
    """
    picked = _match_supported((config_lang or "").strip())
    if picked:
        return picked
    if system_locale is None:
        system_locale = _system_locale()
    picked = _match_supported((system_locale or "").strip())
    if picked:
        return picked
    return "en"


def supported_language_options() -> list[dict[str, str]]:
    """``[{"tag", "name"}]`` for the Settings picker, driven by
    :data:`SUPPORTED_LANGS` (the single source of truth for which
    languages the picker offers)."""
    return [{"tag": tag, "name": native_name(tag)} for tag in SUPPORTED_LANGS]
