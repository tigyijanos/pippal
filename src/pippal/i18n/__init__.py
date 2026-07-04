"""Core i18n runtime for PipPal (Python side).

This is the Python twin of the JS ``webui/js/i18n.js`` helper (T-101). Both
runtimes read the **same** JSON catalogs under ``webui/i18n/<lang>.json`` —
there is a single source of truth per language and no build step (see
``docs/I18N_DESIGN_0_3_1.md`` §5, Alt A).

Public surface
--------------
``SUPPORTED_LANGS``
    List of language tags derived by scanning ``webui/i18n/*.json`` at import
    time — never a hardcoded list. Dropping a new ``xx.json`` file into the
    catalog directory makes ``xx`` supported with zero code changes.
``load_catalog(lang)``
    Load (and cache) one language catalog as a ``dict``.
``cldr_plural(lang, n)``
    Return the CLDR plural category (``one``/``few``/``many``/``other``) for a
    count, using a tiny stdlib resolver that mirrors ``Intl.PluralRules`` for
    our six languages — no Babel/gettext dependency.
``t(key, params)``
    Look a key up with the fallback chain ``active-lang -> en -> ⟦key⟧`` and
    substitute ``{name}`` placeholders (plural keys resolve their category
    first). Same contract as the JS ``t()``.
``detect_system_language(supported)``
    Windows system language via ``GetUserDefaultLocaleName`` mapped onto the
    supported set (bare ``pt`` -> ``pt-BR``, ``zh`` -> ``zh-CN``; unsupported
    -> ``en``).
``resolve_language(cfg_value, supported)``
    The precedence resolver the ``language`` config key (T-103) plugs into:
    explicit config value -> system language -> ``en``.

The active language is a module-level global so on-demand Python surfaces
(toasts, window titles, Ollama status) pick up a language change immediately
after ``save_config`` (design §5.5); the tray menu remains restart-required.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_LANG",
    "MARKER_CLOSE",
    "MARKER_OPEN",
    "SUPPORTED_LANGS",
    "catalog_dir",
    "cldr_plural",
    "clear_catalog_cache",
    "detect_system_language",
    "discover_langs",
    "get_language",
    "load_catalog",
    "refresh_supported_langs",
    "resolve_language",
    "set_language",
    "t",
]

DEFAULT_LANG = "en"

# Greppable fallback marker wrapping the raw key when a string is missing from
# BOTH the active catalog and English. The completeness linter (T-303) and the
# per-language smoke (T-304) assert it never appears in shipped surfaces.
MARKER_OPEN = "⟦"  # ⟦
MARKER_CLOSE = "⟧"  # ⟧


# --------------------------------------------------------------------------
# Catalog directory resolution (mirrors web_ui/server.py::_resolve_webui_dir)
# --------------------------------------------------------------------------
def catalog_dir() -> Path:
    """Locate the shared ``webui/i18n`` catalog directory.

    Source/editable checkout: ``<repo>/webui/i18n`` (this file lives at
    ``src/pippal/i18n/__init__.py`` -> ``parents[3]`` is the repo root).
    Frozen PyInstaller onedir bundle: ``<sys._MEIPASS>/webui/i18n`` (shipped
    via ``packaging/pippal.spec`` datas), matching the JS server's lookup so
    both runtimes read byte-identical files.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "webui" / "i18n"
        if frozen.is_dir():
            return frozen
    return Path(__file__).resolve().parents[3] / "webui" / "i18n"


def _resolve_dir(catalog_directory: Path | str | None) -> Path:
    return Path(catalog_directory) if catalog_directory is not None else catalog_dir()


# --------------------------------------------------------------------------
# Supported-language discovery (dynamic — no hardcoded registry)
# --------------------------------------------------------------------------
def discover_langs(catalog_directory: Path | str | None = None) -> list[str]:
    """Return the supported language tags by scanning ``*.json`` catalog files.

    The tag is the filename stem. Files whose stem starts with ``_`` (private
    fixtures/meta) are ignored. English is always listed first (it is the
    universal fallback); the rest are sorted for determinism. A missing
    directory yields ``["en"]`` — English is always nominally supported so the
    fallback chain and ``t()`` never blow up on a fresh tree.
    """
    directory = _resolve_dir(catalog_directory)
    langs: set[str] = set()
    if directory.is_dir():
        for path in directory.glob("*.json"):
            stem = path.stem
            if stem and not stem.startswith("_"):
                langs.add(stem)
    langs.add(DEFAULT_LANG)
    return [DEFAULT_LANG, *sorted(langs - {DEFAULT_LANG})]


#: The single supported-language registry — the picker (T-103), JS boot and
#: Python all read this. Computed once at import; call
#: :func:`refresh_supported_langs` after adding a catalog file at runtime
#: (tests, hot add). Adding language #7 = drop ``<lang>.json`` in, nothing else.
SUPPORTED_LANGS: list[str] = discover_langs()


def refresh_supported_langs() -> list[str]:
    """Re-scan the default catalog directory and update ``SUPPORTED_LANGS``."""
    global SUPPORTED_LANGS
    SUPPORTED_LANGS = discover_langs()
    return SUPPORTED_LANGS


# --------------------------------------------------------------------------
# Catalog loading (cached)
# --------------------------------------------------------------------------
_catalog_cache: dict[tuple[str, str], dict[str, Any]] = {}
_cache_lock = threading.Lock()


def load_catalog(lang: str, catalog_directory: Path | str | None = None) -> dict[str, Any]:
    """Load one language catalog as a dict (cached by directory + lang).

    A missing or malformed file yields an empty dict so the caller falls
    through the ``en`` link of the chain instead of raising.
    """
    directory = _resolve_dir(catalog_directory)
    key = (str(directory), lang)
    with _cache_lock:
        cached = _catalog_cache.get(key)
        if cached is not None:
            return cached
    path = directory / f"{lang}.json"
    data: dict[str, Any] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    with _cache_lock:
        _catalog_cache[key] = data
    return data


def clear_catalog_cache() -> None:
    """Drop all cached catalogs (used by tests that mutate catalog files)."""
    with _cache_lock:
        _catalog_cache.clear()


# --------------------------------------------------------------------------
# CLDR plural resolver (stdlib-only; mirrors Intl.PluralRules for our 6 langs)
# --------------------------------------------------------------------------
def _operands(n: float | int) -> tuple[int, int]:
    """Return the CLDR operands ``(i, v)`` we need.

    ``i`` = integer part (absolute); ``v`` = count of visible fraction digits.
    Integral floats are normalised to ``int`` so ``1.0`` behaves like ``1`` —
    matching JS, where ``1`` and ``1.0`` are the same ``Number`` and
    ``Intl.PluralRules`` cannot tell them apart. The remaining operands
    (f/t/w/e) are unused by en/de/hu/uk/pt-BR/zh cardinal rules for integer
    and simple-decimal counts, so we omit them.
    """
    if isinstance(n, bool):  # bool is a subclass of int — treat as its value
        n = int(n)
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if isinstance(n, int):
        return abs(n), 0
    # Genuine fraction: render without scientific notation, strip trailing 0s.
    text = format(abs(float(n)), "f")
    int_str, _, frac_str = text.partition(".")
    frac_str = frac_str.rstrip("0")
    i = int(int_str) if int_str else 0
    v = len(frac_str)
    return i, v


def _plural_one_other(i: int, v: int) -> str:
    """en / de / hu: ``one`` only for the integer 1, everything else ``other``."""
    return "one" if i == 1 and v == 0 else "other"


def _plural_pt_br(i: int, v: int) -> str:
    """pt-BR: ``one`` when the integer part is 0 or 1 (so 0, 1 and 1.5 -> one)."""
    return "one" if i in (0, 1) else "other"


def _plural_uk(i: int, v: int) -> str:
    """Ukrainian: 4 forms — one / few / many / other (Slavic).

    Fractions (``v != 0``) are always ``other``. For integers:
    - one:  i%10 == 1 and i%100 != 11
    - few:  i%10 in 2..4 and i%100 not in 12..14
    - many: everything else (i%10 == 0, i%10 in 5..9, i%100 in 11..14)
    """
    if v != 0:
        return "other"
    mod10 = i % 10
    mod100 = i % 100
    if mod10 == 1 and mod100 != 11:
        return "one"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "few"
    return "many"


def _plural_other(i: int, v: int) -> str:
    """zh-CN: no plural forms — always ``other``."""
    return "other"


# Registry keyed by the canonical supported tag. A language not listed here
# defaults to the common ``one/other`` shape; a new language with different
# rules (e.g. another Slavic tag) must add its resolver alongside its catalog.
_PLURAL_RULES = {
    "en": _plural_one_other,
    "de": _plural_one_other,
    "hu": _plural_one_other,
    "pt-BR": _plural_pt_br,
    "uk": _plural_uk,
    "zh-CN": _plural_other,
}


def cldr_plural(lang: str, n: float | int) -> str:
    """Return the CLDR plural category for ``n`` in ``lang``.

    Mirrors ``new Intl.PluralRules(lang).select(n)`` for en/de/hu/uk/pt-BR/zh-CN
    so the JS and Python UIs never disagree on the same screen (design §10).
    """
    rule = _PLURAL_RULES.get(lang, _plural_one_other)
    i, v = _operands(n)
    return rule(i, v)


# --------------------------------------------------------------------------
# t() — key lookup + fallback chain + interpolation
# --------------------------------------------------------------------------
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _interpolate(template: str, params: dict[str, Any]) -> str:
    """Substitute ``{name}`` placeholders; leave unknown ones literal.

    A missing placeholder is intentionally left as ``{name}`` rather than
    raising — a missing param must never crash a user surface. The catalog
    linter (T-303) forbids stray placeholders in shipped catalogs, and tests
    assert on the safe-literal behaviour.
    """
    return _PLACEHOLDER.sub(
        lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0),
        template,
    )


def _fallback_chain(lang: str, catalog_directory: Path | str | None) -> list[str]:
    """Build the lookup order: ``lang`` -> its declared fallback(s) -> ``en``.

    Each catalog may declare ``_meta.fallback`` (defaults to ``en``); this
    supports future regional variants (e.g. ``pt-BR`` -> ``pt-PT`` -> ``en``)
    without code changes. Cycles are guarded.
    """
    chain: list[str] = []
    current: str | None = lang
    while current and current not in chain:
        chain.append(current)
        meta = load_catalog(current, catalog_directory).get("_meta") or {}
        nxt = meta.get("fallback")
        if not nxt or nxt == current:
            break
        current = nxt
    if DEFAULT_LANG not in chain:
        chain.append(DEFAULT_LANG)
    return chain


def _lookup(key: str, lang: str, catalog_directory: Path | str | None) -> tuple[Any, str | None]:
    for candidate in _fallback_chain(lang, catalog_directory):
        catalog = load_catalog(candidate, catalog_directory)
        if key in catalog:
            return catalog[key], candidate
    return None, None


def t(
    key: str,
    params: dict[str, Any] | None = None,
    *,
    lang: str | None = None,
    catalog_directory: Path | str | None = None,
) -> str:
    """Translate ``key`` for the active language.

    Fallback chain: active-lang -> en -> ``⟦key⟧`` marker. Plural keys are
    objects naming the count placeholder in ``_plural`` plus one entry per CLDR
    category the language uses; the category is resolved against the catalog the
    key was actually found in (so an en fallback uses en's plural rules).
    """
    params = params or {}
    active = lang or _active_lang
    entry, resolved_lang = _lookup(key, active, catalog_directory)
    if entry is None or resolved_lang is None:
        return f"{MARKER_OPEN}{key}{MARKER_CLOSE}"
    if isinstance(entry, dict):
        count_name = entry.get("_plural", "count")
        category = cldr_plural(resolved_lang, params.get(count_name, 0))
        template = entry.get(category)
        if template is None:
            template = entry.get("other")
        if not isinstance(template, str):
            return f"{MARKER_OPEN}{key}{MARKER_CLOSE}"
    elif isinstance(entry, str):
        template = entry
    else:
        return f"{MARKER_OPEN}{key}{MARKER_CLOSE}"
    return _interpolate(template, params)


# --------------------------------------------------------------------------
# Language resolution (system detection + config plug for T-103)
# --------------------------------------------------------------------------
# Languages whose supported catalog tag differs from the bare primary subtag.
# Bare-tag languages (en/de/hu/uk) need no entry — see detect_system_language
# step 2. Adding a bare-tag language #7 needs zero entries here; only a new
# region-variant language would add one line.
_VARIANT_MAP = {
    "pt": "pt-BR",
    "zh": "zh-CN",
}


def _read_system_locale() -> str:
    """Return the raw Windows user locale (e.g. ``"pt-BR"``) or ``""``.

    Wraps ``kernel32.GetUserDefaultLocaleName``. This is the single ctypes
    boundary; tests monkeypatch *this* function so they never depend on the CI
    machine's locale, and it degrades to ``""`` on non-Windows platforms.
    """
    try:
        import ctypes

        buffer_len = 85  # LOCALE_NAME_MAX_LENGTH
        buffer = ctypes.create_unicode_buffer(buffer_len)
        written = ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, buffer_len)
        return buffer.value if written else ""
    except (AttributeError, OSError):
        return ""


def detect_system_language(supported: list[str] | None = None) -> str:
    """Map the OS locale onto the supported set, defaulting to ``en``.

    Precedence:
    1. Exact match of the raw locale (``pt-BR`` -> ``pt-BR``).
    2. Primary subtag directly supported (``en-US`` -> ``en``, ``de-DE`` ->
       ``de``, and any future bare-tag language).
    3. Region-variant mapping (``pt`` / ``pt-PT`` -> ``pt-BR``; ``zh-Hans`` /
       ``zh`` -> ``zh-CN``).
    4. Otherwise ``en``.
    """
    langs = supported if supported is not None else SUPPORTED_LANGS
    raw = (_read_system_locale() or "").strip()
    if not raw:
        return DEFAULT_LANG
    if raw in langs:
        return raw
    primary = raw.split("-", 1)[0].lower()
    if primary in langs:
        return primary
    variant = _VARIANT_MAP.get(primary)
    if variant and variant in langs:
        return variant
    return DEFAULT_LANG


def resolve_language(cfg_value: str | None, supported: list[str] | None = None) -> str:
    """Resolve the effective language — the seam the ``language`` key (T-103) plugs into.

    ``cfg_value`` is the persisted ``config["language"]`` (``""`` = Auto/system).
    Precedence: explicit supported config value -> system language -> ``en``.
    """
    langs = supported if supported is not None else SUPPORTED_LANGS
    value = (cfg_value or "").strip()
    if value and value in langs:
        return value
    return detect_system_language(langs)


# --------------------------------------------------------------------------
# Active-language module global (live updates for on-demand strings)
# --------------------------------------------------------------------------
_active_lang: str = DEFAULT_LANG


def get_language() -> str:
    """Return the currently active language tag."""
    return _active_lang


def set_language(lang: str | None, supported: list[str] | None = None) -> str:
    """Set the active language (call this from ``save_config``).

    An empty/unsupported value resolves via :func:`resolve_language` (Auto).
    On-demand Python surfaces (toasts, titles, status) then render in the new
    language immediately; the tray menu is restart-required (design §5.5).
    """
    global _active_lang
    _active_lang = resolve_language(lang, supported)
    return _active_lang
