#!/usr/bin/env python3
"""Generate the ``en-XA`` pseudo-locale catalog from ``en.json`` (T-305 / #128).

A *pseudo-locale* is a build/test-only catalog whose every English string is
mechanically transformed so it is instantly recognisable on screen yet still
readable:

* every ASCII letter is replaced by a look-alike accented glyph
  (``Close`` -> ``Çļóšé``) — any un-accented word left on a rendered surface is
  therefore a **hardcoded string that bypassed ``t()``**;
* the string is wrapped in distinctive ``[!! … !!]`` delimiters. These are
  deliberately NOT the ``⟦ … ⟧`` missing-key marker glyphs, so a pseudo string
  can never be mistaken for a missing-translation marker;
* ~40 % padding is appended so the string is worst-case wide — this surfaces
  layout overflow (German-plus widths) before real translations land.

Structure is preserved verbatim: ``{placeholder}`` tokens, ``<html>`` tags and
``&entity;`` references are never accented, and plural objects keep their
``_plural`` count-key and per-category shape.

The output ``webui/i18n/en-XA.json`` is a committed DEV/TEST artifact. It ships
with ``_meta.hidden = true`` so :func:`pippal.i18n.discover_langs` keeps it OUT
of ``SUPPORTED_LANGS`` (and therefore out of the Settings language picker),
while ``load_catalog("en-XA")`` / a served ``?lang``/host-injected boot can
still load it. ``tests/test_pseudo_locale.py`` re-runs this generator and diffs
the result against the committed file, so the artifact can never drift from
``en.json`` silently.

Usage::

    python tools/gen_pseudo_locale.py            # regenerate the catalog
    python tools/gen_pseudo_locale.py --check     # fail if it would change
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = REPO_ROOT / "webui" / "i18n"
SOURCE = CATALOG_DIR / "en.json"
TARGET = CATALOG_DIR / "en-XA.json"

# Pseudo wrap delimiters — intentionally distinct from the ⟦ ⟧ missing-key
# marker (pippal.i18n.MARKER_OPEN / MARKER_CLOSE) so a pseudo string is never
# confused with a missing-translation marker on a rendered surface.
OPEN_DELIM = "[!! "
CLOSE_DELIM = " !!]"

# Fraction of extra width appended as padding (worst-case width stress).
PAD_RATIO = 0.4

# Accented look-alikes for the ASCII alphabet (single codepoints each).
_LOWER_PLAIN = "abcdefghijklmnopqrstuvwxyz"
_LOWER_ACCENT = "áƀçđéƒǧĥíĵķļɱñóƥɋŕšŧúṽŵẋýž"
_UPPER_PLAIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_UPPER_ACCENT = "ÁƁÇĐÉƑǦĤÍĴĶĻṀÑÓƤɊŔŠŦÚṼŴẊÝŽ"

assert len(_LOWER_ACCENT) == 26 and len(_UPPER_ACCENT) == 26, "accent map size"

_ACCENT_MAP = str.maketrans(
    _LOWER_PLAIN + _UPPER_PLAIN,
    _LOWER_ACCENT + _UPPER_ACCENT,
)

# Accented filler used for the padding run (never plain ASCII, so padding can
# never itself look like an untranslated hardcoded string).
_PAD_ALPHABET = "áéíóúàèìòù"

# Segments that must survive VERBATIM: {placeholder}, <html tag>, &entity;.
_PRESERVE = re.compile(r"(\{[^}]*\}|<[^>]*>|&[#0-9A-Za-z]+;)")


def _accent(text: str) -> str:
    """Accent the ASCII letters of ``text`` while leaving placeholders,
    HTML tags and character entities untouched."""
    parts = _PRESERVE.split(text)
    # re.split with one capturing group yields: [plain, token, plain, token, …]
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].translate(_ACCENT_MAP)
    return "".join(parts)


def _padding(width: int) -> str:
    """A run of ``width`` accented filler characters (cycled)."""
    if width <= 0:
        return ""
    return "".join(_PAD_ALPHABET[i % len(_PAD_ALPHABET)] for i in range(width))


def pseudo(text: str) -> str:
    """Transform one English string into its bracketed, accented, padded
    pseudo form. Empty strings are returned unchanged (nothing to translate)."""
    if not text:
        return text
    body = _accent(text)
    pad = _padding(round(len(body) * PAD_RATIO))
    tail = f" {pad}" if pad else ""
    return f"{OPEN_DELIM}{body}{tail}{CLOSE_DELIM}"


def transform_value(value: Any) -> Any:
    """Transform a catalog value: a plain string is pseudo-translated; a
    plural object keeps its ``_plural`` count-key and shape while every
    category template is pseudo-translated."""
    if isinstance(value, str):
        return pseudo(value)
    if isinstance(value, dict):
        return {
            k: (v if k == "_plural" else transform_value(v))
            for k, v in value.items()
        }
    return value


def _pseudo_meta(source_meta: dict[str, Any] | None) -> dict[str, Any]:
    """The ``_meta`` block for the pseudo catalog.

    ``hidden`` keeps the locale out of ``SUPPORTED_LANGS`` / the picker;
    ``fallback: en`` means any (theoretical) missing key falls through to
    English rather than a marker.
    """
    return {
        "lang": "en-XA",
        "name": "Pseudo (en-XA)",
        "fallback": "en",
        "hidden": True,
        "generated_by": "tools/gen_pseudo_locale.py",
    }


def generate_pseudo_catalog(source: dict[str, Any]) -> dict[str, Any]:
    """Return the full pseudo catalog for the ``en`` ``source`` catalog,
    preserving key order. ``_meta`` is replaced with the pseudo meta block;
    every other value is transformed."""
    result: dict[str, Any] = {}
    for key, value in source.items():
        if key == "_meta":
            result[key] = _pseudo_meta(value if isinstance(value, dict) else None)
        else:
            result[key] = transform_value(value)
    return result


def _serialise(catalog: dict[str, Any]) -> str:
    """Deterministic JSON serialisation (UTF-8, 2-space indent, trailing NL)."""
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def render() -> str:
    """Load ``en.json`` and return the serialised pseudo catalog text."""
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    return _serialise(generate_pseudo_catalog(source))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the en-XA pseudo-locale.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if en-XA.json would change (do not write).",
    )
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(
                f"en-XA.json is stale — run: python {Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        print("en-XA.json is up to date.")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(REPO_ROOT)} ({len(rendered)} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
