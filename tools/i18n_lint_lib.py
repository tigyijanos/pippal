#!/usr/bin/env python3
"""Implementation half of the PipPal i18n CI linter (see ``i18n_lint.py``).

Split out purely to keep each file focused (and under the repo line-count
guard): string-literal extraction, the user-facing/technical heuristics, the
sink scanners, the exclusions file, and the catalog-structure checks all live
here; ``i18n_lint.py`` owns per-repo config and the CLI.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# pippal.i18n engine access (shared CLDR plural oracle)
# --------------------------------------------------------------------------
# The linter reuses the SHIPPED engine (cldr_plural, load_catalog, ...) rather
# than reimplementing plural rules. It loads ``pippal/i18n/__init__.py`` DIRECTLY
# via importlib instead of ``import pippal`` — the parent package __init__ pulls
# in engine/web_ui (pywebview & friends), which the lightweight CI lint job does
# not install, whereas i18n/__init__.py is pure stdlib. This keeps the gate
# dependency-free (only the i18n source file needs to be on disk).
_I18N_CACHE: dict[str, object] = {}


def _i18n_source(root: Path) -> Path | None:
    """Locate ``pippal/i18n/__init__.py``.

    Order: the core checkout (``<root>/src``); the Pro checkout's sibling core
    (``../pippal-public/src``, mirroring Pro CI's dual checkout); then any entry
    on ``sys.path`` (covers a pip-installed core and a local ``PYTHONPATH``)."""
    candidates = [root / "src", root.parent / "pippal-public" / "src"]
    candidates += [Path(p) for p in sys.path if p]
    for cand in candidates:
        f = cand / "pippal" / "i18n" / "__init__.py"
        if f.exists():
            return f
    return None


def load_i18n_module(root: Path):
    src = _i18n_source(root)
    if src is None:
        raise SystemExit(
            f"i18n_lint: cannot locate pippal/i18n/__init__.py under {root}/src "
            f"or {root.parent}/pippal-public/src"
        )
    key = str(src)
    if key in _I18N_CACHE:
        return _I18N_CACHE[key]
    spec = importlib.util.spec_from_file_location("pippal_i18n_lint", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _I18N_CACHE[key] = mod
    return mod


def load_cldr_plural(root: Path):
    return load_i18n_module(root).cldr_plural


# Pro FEATURE names that must never appear in a CORE catalog value (feature
# leakage). Deliberately NOT the product name "PipPal Pro" / "Pro": core is
# allowed to advertise the paid tier by name (the `promo.*` upsell keys say
# "Unlock PipPal Pro"). The denylist targets Pro-exclusive *feature* vocabulary.
PRO_DENYLIST = [
    "Listen Later",
    "AI mood",
    "AI Mood",
    "Ollama",
]

# The CORE identical-to-en allowlist (mirrors tests/test_i18n_catalogs.py in
# pippal-public). Needed on the Pro side when validating the MERGED
# ``{**core, **pro}`` view: those core keys legitimately equal en and are
# core's own sanctioned set, so the merged check unions this in.
CORE_GLOBAL_EQUALS_EN = {
    "about.link.github",
    "window.settings.title",
    "window.onboarding.title",
    "window.overlay.title",
    "settings.panel.auto_hide_unit",
    "settings.panel.distance_unit",
    "voices.row.meta",
}
CORE_PER_LANG_EQUALS_EN = {
    ("de", "settings.voice.engine_label"),
    ("de", "voices.filter.status_label"),
    ("de", "about.link.reddit"),
    ("pt-BR", "voices.filter.status_label"),
}


# --------------------------------------------------------------------------
# Exclusions file
# --------------------------------------------------------------------------
class Exclusions:
    """Documented, sanctioned literal exclusions.

    File format (``#`` comments + blank lines ignored):
      * ``literal:<exact text>``   — exclude this exact literal anywhere.
      * ``file:<relpath>::<text>`` — exclude this literal only in that file.
      * ``<exact text>``           — shorthand for ``literal:``.
    """

    def __init__(self) -> None:
        self.global_literals: set[str] = set()
        self.file_literals: set[tuple[str, str]] = set()

    @classmethod
    def load(cls, path: Path) -> Exclusions:
        exc = cls()
        if not path.exists():
            return exc
        for raw in path.read_text("utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("literal:"):
                exc.global_literals.add(stripped[len("literal:") :])
            elif stripped.startswith("file:"):
                relpath, sep, text = stripped[len("file:") :].partition("::")
                if sep:
                    exc.file_literals.add((relpath.strip().replace("\\", "/"), text))
            else:
                exc.global_literals.add(stripped)
        return exc

    def excludes(self, relpath: str, value: str) -> bool:
        if value in self.global_literals:
            return True
        return (relpath.replace("\\", "/"), value) in self.file_literals


# --------------------------------------------------------------------------
# String-literal extraction (comment/docstring aware)
# --------------------------------------------------------------------------
def extract_js_strings(text: str):
    """Yield ``(lineno, value, col, line_text)`` for JS string literals.

    Line-oriented on purpose: a whole-file char scan trips over JS *regex
    literals* (``/`([^`]+)`/`` in the markdown renderer contains quotes and
    backticks) and swallows dozens of lines into one bogus 'string'. Scanning
    per line — with a persistent ``/* */`` block-comment flag — confines any
    regex-literal confusion to a single line, where the technical/prose filters
    reject it. ``//`` comments and ``${...}`` template literals are skipped."""
    in_block = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        i, n = 0, len(line)
        while i < n:
            if in_block:
                end = line.find("*/", i)
                if end == -1:
                    break
                i, in_block = end + 2, False
                continue
            c = line[i]
            if c == "/" and i + 1 < n and line[i + 1] == "/":
                break
            if c == "/" and i + 1 < n and line[i + 1] == "*":
                in_block, i = True, i + 2
                continue
            if c in "\"'`":
                quote, col = c, i
                i += 1
                buf, dynamic = [], False
                closed = False
                while i < n:
                    ch = line[i]
                    if ch == "\\" and i + 1 < n:
                        buf.append(line[i + 1])
                        i += 2
                        continue
                    if quote == "`" and ch == "$" and i + 1 < n and line[i + 1] == "{":
                        dynamic = True
                    if ch == quote:
                        i += 1
                        closed = True
                        break
                    buf.append(ch)
                    i += 1
                if closed and not dynamic:
                    yield lineno, "".join(buf), col, i, line
                continue
            i += 1


def extract_py_strings(text: str):
    """Yield ``(lineno, value, col, line_text)`` for Python string literals.

    Skips ``#`` comments and triple-quoted strings (docstrings / multi-line
    blobs). Implicit ``"a" "b"`` concatenation surfaces as separate literals."""
    lines = text.splitlines()
    i, n, line, line_start = 0, len(text), 1, 0
    while i < n:
        c = text[i]
        if c == "\n":
            line, line_start, i = line + 1, i + 1, i + 1
            continue
        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in "\"'":
            quote = c
            triple = text[i : i + 3] in ('"""', "'''")
            col, start_line = i - line_start, line
            if triple:
                q3 = text[i : i + 3]
                i += 3
                while i < n and text[i : i + 3] != q3:
                    if text[i] == "\n":
                        line, line_start = line + 1, i + 1
                    i += 1
                i += 3
                continue
            i += 1
            buf = []
            while i < n:
                ch = text[i]
                if ch == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    i += 1
                    break
                if ch == "\n":
                    break
                buf.append(ch)
                i += 1
            line_text = lines[start_line - 1] if start_line - 1 < len(lines) else ""
            endcol = i - line_start
            yield start_line, "".join(buf), col, endcol, line_text
            continue
        i += 1


# --------------------------------------------------------------------------
# User-facing / technical heuristics
# --------------------------------------------------------------------------
_LETTER_RUN = re.compile(r"[A-Za-z]{3,}")
_URLISH = re.compile(r"https?://|://|^[.#/]|\.(?:js|py|json|css|html)$")
_KEBAB_OR_LOWER = re.compile(r"[a-z0-9][a-z0-9_-]*")  # css class / id token
_STYLE = re.compile(r"\d\s*px|\d\s*%|flex\s*:|width\s*:|height\s*:|:\s*\d")


def has_words(value: str) -> bool:
    return bool(_LETTER_RUN.search(value))


def is_phrase(value: str) -> bool:
    """A standalone (non-sink) string that reads like user copy: a real word
    AND (whitespace OR a trailing sentence punctuation)."""
    v = value.strip()
    if not has_words(v):
        return False
    if " " in v:
        return True
    return v[-1:] in "…!?." and len(v) > 3


def is_technical(value: str) -> bool:
    """True for strings that are code/markup/styling, not user-facing copy:
    URLs/paths, HTML fragments, inline CSS, and all-lowercase token lists
    (CSS class lists, ``"use strict"`` directives, kebab ids)."""
    v = value.strip()
    if not v or not has_words(v):
        return True
    if _URLISH.search(v):
        return True
    if "<" in v or ">" in v or ";" in v or _STYLE.search(v):
        return True
    stripped = re.sub(r"\{[^}]*\}", "", v)
    if not _LETTER_RUN.search(stripped):
        return True
    # All whitespace-separated tokens are lowercase/kebab identifiers -> a class
    # list or directive, never Title/Sentence-case user copy.
    tokens = v.split()
    if tokens and all(_KEBAB_OR_LOWER.fullmatch(tok) for tok in tokens):
        return True
    return False


# --------------------------------------------------------------------------
# Sink / context detection
# --------------------------------------------------------------------------
_JS_SINK = re.compile(
    r"(?:\.(?:textContent|innerHTML|innerText|title|placeholder|ariaLabel|alt)\s*=\s*$)"
    r"|(?:\b(?:html|title|label|text|message|tooltip|placeholder)\s*:\s*$)"
    r"|(?:\b(?:notify|toast|alert|setStatus|showError|showToast)\s*\(\s*$)"
)
_PY_SINK = re.compile(
    r"\b(?:MenuItem|set_tooltip|set_title|set_label|notify|toast|showinfo|"
    r"showerror|showwarning|set_status)\s*\(\s*$"
)
_T_ARG = re.compile(r"(?:^|[^A-Za-z0-9_$])t\s*\(\s*$")
_SKIP_LINE_CTX = re.compile(
    r"\b(?:import|from|require|console|logger|logging|getLogger|querySelector|"
    r"getElementById|getAttribute|setAttribute|dataset|classList|addEventListener|"
    r"createElement|matchMedia|print)\b"
)
_PY_MODULE_CONST = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*(?::[^=]+)?=\s*\(?")
# A standalone string that is an ARRAY element or OBJECT/dict VALUE (prefix ends
# with `[`, `,`, `:`, or `= ` / `(` opening a collection, or is blank). This is
# how the whimsical loader constants (arrays/objects) get caught while ordinary
# function-call arguments (e.g. `btn("Open Settings", ...)`) do NOT — those are
# a separate render-helper concern, not a bare user-string-in-a-constant.
_COLLECTION_PREFIX = re.compile(r"(?:^\s*$|[\[,:]\s*$)")


def _is_key(value_end_suffix: str) -> bool:
    """The string is an object KEY (``"Not installed": t(...)``) — its display
    goes through the mapped ``t()`` value, so the key literal is not copy."""
    return value_end_suffix.lstrip().startswith(":")


def scan_js_file(text: str, relpath: str, exc: Exclusions) -> list[tuple[int, str]]:
    findings = []
    for lineno, value, col, endcol, line in extract_js_strings(text):
        prefix = line[:col]
        suffix = line[endcol:]
        if _T_ARG.search(prefix) or _SKIP_LINE_CTX.search(line) or exc.excludes(relpath, value):
            continue
        if _JS_SINK.search(prefix):
            if has_words(value) and not is_technical(value):
                findings.append((lineno, value))
        elif (
            _COLLECTION_PREFIX.search(prefix)
            and not _is_key(suffix)
            and is_phrase(value)
            and not is_technical(value)
        ):
            findings.append((lineno, value))
    return findings


def scan_py_file(text: str, relpath: str, exc: Exclusions) -> list[tuple[int, str]]:
    findings = []
    for lineno, value, col, _endcol, line in extract_py_strings(text):
        prefix = line[:col]
        if _T_ARG.search(prefix) or _SKIP_LINE_CTX.search(line) or exc.excludes(relpath, value):
            continue
        is_module_const = bool(line) and line[0] not in " \t" and bool(_PY_MODULE_CONST.match(line))
        if _PY_SINK.search(prefix):
            if has_words(value) and not is_technical(value):
                findings.append((lineno, value))
        elif is_module_const and is_phrase(value) and not is_technical(value):
            findings.append((lineno, value))
    return findings


def run_scan_literals(root: Path, cfg: dict, exc: Exclusions) -> int:
    findings: list[str] = []
    skip = {s.replace("\\", "/") for s in cfg.get("skip_files", [])}
    for glob, scanner in ((cfg["js_globs"], scan_js_file), (cfg["py_globs"], scan_py_file)):
        for pattern in glob:
            for path in sorted(root.glob(pattern)):
                rel = path.relative_to(root).as_posix()
                if rel in skip:
                    continue
                for lineno, value in scanner(path.read_text("utf-8"), rel, exc):
                    findings.append(f"{rel}:{lineno}: user-facing literal {value!r}")
    if findings:
        print("scan-literals: FAIL — user-facing hardcoded string(s) outside catalogs:")
        for f in findings:
            print(f"  {f}")
        print(
            "\nExtract the string into the catalog + render via t(), or (if genuinely "
            "sanctioned) add a documented entry to tools/i18n_lint_exclusions.txt."
        )
        return 1
    print("scan-literals: OK — no user-facing hardcoded strings outside catalogs.")
    return 0


# --------------------------------------------------------------------------
# Catalog checks
# --------------------------------------------------------------------------
PLACEHOLDER = re.compile(r"\{(\w+)\}")
MARKER_OPEN = "⟦"
MARKER_CLOSE = "⟧"


def _leaves(value):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k != "_plural"}
    return {None: value}


def _placeholders(value) -> set[str]:
    out: set[str] = set()
    for text in _leaves(value).values():
        if isinstance(text, str):
            out |= set(PLACEHOLDER.findall(text))
    return out


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _catalog_langs(catalog_dir: Path) -> list[str]:
    """Real, shippable language tags in a catalog directory.

    Skips ``_``-prefixed private files and ``_meta.hidden`` build-only catalogs
    (the ``en-XA`` pseudo-locale, T-305) — mirroring the engine's
    ``discover_langs``/``SUPPORTED_LANGS``, which also exclude hidden locales, so
    the linter validates exactly the set the app actually ships."""
    langs = []
    for p in sorted(catalog_dir.glob("*.json")):
        if p.stem.startswith("_"):
            continue
        try:
            meta = _load_json(p).get("_meta") or {}
        except (OSError, ValueError):
            meta = {}
        if isinstance(meta, dict) and meta.get("hidden"):
            continue
        langs.append(p.stem)
    return langs


def _check_plural(label, lang, key, obj, expected, errors):
    if "_plural" not in obj:
        errors.append(f"[{label}] {lang}: {key}: plural object missing _plural marker")
        return
    got = {k for k in obj if k != "_plural"}
    if got != expected:
        errors.append(
            f"[{label}] {lang}: {key}: plural categories {sorted(got)} != CLDR {sorted(expected)}"
        )
    count_name = obj.get("_plural")
    for c in got:
        if isinstance(obj.get(c), str) and "{" + str(count_name) + "}" not in obj[c]:
            errors.append(f"[{label}] {lang}: {key}[{c}]: missing count placeholder {{{count_name}}}")


def _check_width(label, lang, key, cat_val, ref_val, cfg, errors):
    for prefix, mult in cfg["width_constrained"].items():
        if not key.startswith(prefix):
            continue
        ref_leaves = _leaves(ref_val)
        for cat_name, text in _leaves(cat_val).items():
            if not isinstance(text, str):
                continue
            ref_text = ref_leaves.get(cat_name, ref_leaves.get("other"))
            if not isinstance(ref_text, str):
                continue
            budget = max(len(ref_text) * mult, len(ref_text) + 4)
            if len(text) > budget:
                errors.append(
                    f"[{label}] {lang}: {key}"
                    + ("" if cat_name is None else f"[{cat_name}]")
                    + f": width-constrained value len {len(text)} exceeds budget "
                    + f"{budget:.0f} (en len {len(ref_text)})"
                )


def check_one_catalog_set(catalog_dir, reference_lang, cfg, cldr_plural, *, label, core_catalogs=None):
    """Validate a directory of ``<lang>.json`` catalogs against its reference.

    ``core_catalogs`` (Pro merged view) — when given, each language is validated
    as ``{**core[lang], **pro[lang]}`` and Pro keys shadowing a core key without
    ``_override: true`` are WARNED (not failed)."""
    errors: list[str] = []
    ref_path = catalog_dir / f"{reference_lang}.json"
    if not ref_path.exists():
        return [f"[{label}] reference catalog missing: {ref_path}"]
    langs = _catalog_langs(catalog_dir)
    raw = {lang: _load_json(catalog_dir / f"{lang}.json") for lang in langs}

    if core_catalogs is not None:
        cats = {lang: {**core_catalogs.get(lang, {}), **raw.get(lang, {})} for lang in langs}
        core_ref_keys = set(core_catalogs.get(reference_lang, {}))
        for key, val in raw[reference_lang].items():
            if key != "_meta" and key in core_ref_keys and not (
                isinstance(val, dict) and val.get("_override") is True
            ):
                print(f'  WARN [{label}] Pro key {key!r} shadows a core key without "_override": true')
    else:
        cats = raw

    ref = cats[reference_lang]
    ref_keys = {k for k in ref if k != "_meta"}
    global_eq, per_lang_eq = cfg["global_equals_en"], cfg["per_lang_equals_en"]
    if core_catalogs is not None:  # merged view also carries core keys
        global_eq = global_eq | CORE_GLOBAL_EQUALS_EN
        per_lang_eq = per_lang_eq | CORE_PER_LANG_EQUALS_EN

    for lang in (x for x in langs if x != reference_lang):
        cat = cats[lang]
        keys = {k for k in cat if k != "_meta"}
        if ref_keys - keys:
            errors.append(f"[{label}] {lang}: missing keys vs {reference_lang}: {sorted(ref_keys - keys)}")
        if keys - ref_keys:
            errors.append(f"[{label}] {lang}: keys absent from {reference_lang}: {sorted(keys - ref_keys)}")
        expected_cats = {cldr_plural(lang, x) for x in [*range(0, 201), 0.5, 1.5, 2.5]}

        for key in ref_keys & keys:
            if _placeholders(ref[key]) != _placeholders(cat[key]):
                errors.append(
                    f"[{label}] {lang}: {key}: placeholder mismatch "
                    f"{sorted(_placeholders(ref[key]))} != {sorted(_placeholders(cat[key]))}"
                )
            ref_plural, cat_plural = isinstance(ref[key], dict), isinstance(cat[key], dict)
            if ref_plural != cat_plural:
                errors.append(f"[{label}] {lang}: {key}: plural/scalar shape differs from {reference_lang}")
            elif cat_plural:
                _check_plural(label, lang, key, cat[key], expected_cats, errors)
            for cat_name, text in _leaves(cat[key]).items():
                where = key if cat_name is None else f"{key}[{cat_name}]"
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"[{label}] {lang}: {where}: empty/whitespace value")
                elif MARKER_OPEN in text or MARKER_CLOSE in text:
                    errors.append(f"[{label}] {lang}: {where}: contains ⟦⟧ fallback marker")
            if key not in global_eq and (lang, key) not in per_lang_eq:
                ref_leaves = _leaves(ref[key])
                for cat_name, text in _leaves(cat[key]).items():
                    ref_text = ref_leaves.get(cat_name, ref_leaves.get("other"))
                    if isinstance(text, str) and text == ref_text:
                        errors.append(
                            f"[{label}] {lang}: {key}"
                            + ("" if cat_name is None else f"[{cat_name}]")
                            + f": equals {reference_lang} without an allowlist entry"
                        )
            _check_width(label, lang, key, cat[key], ref[key], cfg, errors)

    if cfg["check_core_purity"]:
        for lang in langs:
            for key, val in cats[lang].items():
                if key == "_meta":
                    continue
                for cat_name, text in _leaves(val).items():
                    if not isinstance(text, str):
                        continue
                    for term in PRO_DENYLIST:
                        if term in text:
                            errors.append(
                                f"[{label}] CORE-PURITY: {lang}: {key}"
                                + ("" if cat_name is None else f"[{cat_name}]")
                                + f": contains Pro-term {term!r} in a core catalog"
                            )
    return errors


def run_check_catalogs(root: Path, repo: str, cfg: dict) -> int:
    cldr_plural = load_cldr_plural(root)
    errors = check_one_catalog_set(
        cfg["catalog_dir"], cfg["reference_lang"], cfg, cldr_plural,
        label="overlay" if repo == "pro" else "core",
    )
    if cfg["check_merged"]:
        core = load_i18n_module(root)
        core.clear_catalog_cache()
        core_catalogs = {lang: core.load_catalog(lang) for lang in core.SUPPORTED_LANGS}
        errors += check_one_catalog_set(
            cfg["catalog_dir"], cfg["reference_lang"], cfg, cldr_plural,
            label="merged", core_catalogs=core_catalogs,
        )
    if errors:
        print("check-catalogs: FAIL")
        for e in errors:
            print(f"  {e}")
        return 1
    print("check-catalogs: OK — catalogs complete, plural-correct and core-pure.")
    return 0
