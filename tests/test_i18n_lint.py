"""Unit tests for the i18n CI linter (tools/i18n_lint.py — #337 T-302 + #338 T-303).

The linter is itself a gate, so it needs its own coverage: every seeded
violation class must be detected (exit 1) and a clean fixture tree must pass
(exit 0). Tests build a tiny self-contained catalog/render tree in ``tmp_path``
and drive the tool through its ``main()`` with ``--root`` pointed at it, so they
never depend on the real repo's evolving catalogs. A final smoke test asserts
the real tree passes today (the post-extraction, post-T-105 baseline)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import i18n_lint  # noqa: E402  (imported after tools/ is on sys.path)

NAMES = {
    "en": "English",
    "de": "Deutsch",
    "hu": "Magyar",
    "uk": "Українська",
    "zh-CN": "简体中文",
    "pt-BR": "Português (Brasil)",
}
# Distinct-from-en values so the identical-to-en check never trips by accident.
GREETING = {"en": "Hello", "de": "Hallo", "hu": "Szia", "uk": "Привіт", "zh-CN": "你好", "pt-BR": "Olá"}
LOADING = {"en": "Load", "de": "Laden", "hu": "Tölt", "uk": "Вант", "zh-CN": "载入", "pt-BR": "Carga"}


def _items(lang: str) -> dict:
    """A plural key shaped with EXACTLY the CLDR categories for ``lang``."""
    if lang == "uk":
        cats = {"one": "{count} р", "few": "{count} ре", "many": "{count} рей", "other": "{count} ри"}
    elif lang == "zh-CN":
        cats = {"other": "{count} 项"}
    else:
        cats = {"one": f"{{count}} {lang}-item", "other": f"{{count}} {lang}-items"}
    return {"_plural": "count", **cats}


def _catalog(lang: str) -> dict:
    return {
        "_meta": {"lang": lang, "name": NAMES[lang], "fallback": "en"},
        "greeting": GREETING[lang],
        "overlay.loading.msg": LOADING[lang],
        "items": _items(lang),
    }


def _build_core_tree(root: Path) -> None:
    """A minimal but valid CORE repo layout: 6 catalogs, one JS + one Py file
    that route all user copy through ``t()`` (so a clean tree scans green)."""
    i18n = root / "webui" / "i18n"
    i18n.mkdir(parents=True)
    for lang in NAMES:
        (i18n / f"{lang}.json").write_text(json.dumps(_catalog(lang), ensure_ascii=False), "utf-8")
    js = root / "webui" / "js"
    js.mkdir(parents=True)
    (js / "render.js").write_text(
        '"use strict";\nel.textContent = t("greeting");\nvar x = ["item-one", "item-two"];\n', "utf-8"
    )
    py = root / "src" / "pippal"
    py.mkdir(parents=True)
    (py / "ui.py").write_text('MODE = "piper"\nlabel = t("greeting")\n', "utf-8")


def _run(*args: str) -> int:
    return i18n_lint.main(list(args))


# --------------------------------------------------------------------------
# Clean tree
# --------------------------------------------------------------------------
def test_clean_fixture_scan_passes(tmp_path):
    _build_core_tree(tmp_path)
    assert _run("--scan-literals", "--repo", "core", "--root", str(tmp_path)) == 0


def test_clean_fixture_catalogs_pass(tmp_path):
    _build_core_tree(tmp_path)
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 0


# --------------------------------------------------------------------------
# T-302 — no-hardcoded-string gate
# --------------------------------------------------------------------------
def test_scan_flags_injected_textcontent_literal(tmp_path):
    _build_core_tree(tmp_path)
    js = tmp_path / "webui" / "js" / "render.js"
    js.write_text(js.read_text("utf-8") + '\nel.textContent = "Hardcoded";\n', "utf-8")
    assert _run("--scan-literals", "--repo", "core", "--root", str(tmp_path)) == 1


def test_scan_flags_standalone_prose_array_element(tmp_path):
    _build_core_tree(tmp_path)
    js = tmp_path / "webui" / "js" / "render.js"
    js.write_text(js.read_text("utf-8") + '\nvar M = ["Warming up the engine…"];\n', "utf-8")
    assert _run("--scan-literals", "--repo", "core", "--root", str(tmp_path)) == 1


def test_scan_ignores_technical_and_t_calls(tmp_path):
    _build_core_tree(tmp_path)
    js = tmp_path / "webui" / "js" / "render.js"
    js.write_text(
        js.read_text("utf-8")
        + '\nel.className = "overlay-loading hidden";\n'
        + 'el.textContent = t("greeting");\n'
        + 'el.style = "flex:0 0 80px;width:80px";\n',
        "utf-8",
    )
    assert _run("--scan-literals", "--repo", "core", "--root", str(tmp_path)) == 0


def test_scan_exclusion_file_suppresses_a_literal(tmp_path):
    _build_core_tree(tmp_path)
    js = tmp_path / "webui" / "js" / "render.js"
    js.write_text(js.read_text("utf-8") + '\nel.textContent = "Read with PipPal";\n', "utf-8")
    assert _run("--scan-literals", "--repo", "core", "--root", str(tmp_path)) == 1
    exc = tmp_path / "exc.txt"
    exc.write_text("file:webui/js/render.js::Read with PipPal\n", "utf-8")
    assert _run("--scan-literals", "--repo", "core", "--root", str(tmp_path), "--exclusions", str(exc)) == 0


# --------------------------------------------------------------------------
# T-303 — catalog completeness + core-purity gate
# --------------------------------------------------------------------------
def test_catalog_flags_missing_key(tmp_path):
    _build_core_tree(tmp_path)
    de = tmp_path / "webui" / "i18n" / "de.json"
    data = json.loads(de.read_text("utf-8"))
    del data["greeting"]
    de.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


def test_catalog_flags_wrong_plural_category(tmp_path):
    _build_core_tree(tmp_path)
    uk = tmp_path / "webui" / "i18n" / "uk.json"
    data = json.loads(uk.read_text("utf-8"))
    del data["items"]["few"]  # uk must carry one/few/many/other
    uk.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


def test_catalog_flags_placeholder_mismatch(tmp_path):
    _build_core_tree(tmp_path)
    de = tmp_path / "webui" / "i18n" / "de.json"
    data = json.loads(de.read_text("utf-8"))
    data["items"]["one"] = "{n} de-item"  # wrong placeholder name
    de.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


def test_catalog_flags_marker_and_empty(tmp_path):
    _build_core_tree(tmp_path)
    de = tmp_path / "webui" / "i18n" / "de.json"
    data = json.loads(de.read_text("utf-8"))
    data["greeting"] = "⟦greeting⟧"
    de.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


def test_catalog_flags_core_purity_pro_term(tmp_path):
    _build_core_tree(tmp_path)
    en = tmp_path / "webui" / "i18n" / "en.json"
    data = json.loads(en.read_text("utf-8"))
    data["greeting"] = "Try Listen Later now"
    en.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


def test_catalog_flags_oversized_width_constrained_value(tmp_path):
    _build_core_tree(tmp_path)
    de = tmp_path / "webui" / "i18n" / "de.json"
    data = json.loads(de.read_text("utf-8"))
    data["overlay.loading.msg"] = "Laden " * 20  # far over the en+20% budget
    de.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


def test_catalog_flags_identical_to_en_outside_allowlist(tmp_path):
    _build_core_tree(tmp_path)
    de = tmp_path / "webui" / "i18n" / "de.json"
    data = json.loads(de.read_text("utf-8"))
    data["greeting"] = GREETING["en"]  # de == en, not allowlisted
    de.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert _run("--check-catalogs", "--repo", "core", "--root", str(tmp_path)) == 1


# --------------------------------------------------------------------------
# Real-tree smoke — the shipped release/0.3.1 core tree passes both gates.
# --------------------------------------------------------------------------
def test_real_core_tree_passes_both_gates():
    assert _run("--scan-literals", "--repo", "core") == 0
    assert _run("--check-catalogs", "--repo", "core") == 0
