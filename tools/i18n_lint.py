#!/usr/bin/env python3
"""i18n_lint.py — CI linters for the PipPal i18n system (#337 T-302 + #338 T-303).

Two independent gate modes over one shared tool (the Pro repo ships a
repo-appropriate twin of this file + ``i18n_lint_lib.py``):

``--scan-literals``  (T-302, the *no-hardcoded-string* gate)
    Flags user-facing bare string literals in the extracted render surfaces
    (``webui/js`` render paths and the Python UI modules) that live *outside*
    the catalogs. Post-extraction every user-facing string routes through
    ``t()``; anything left is either a documented, sanctioned exclusion
    (``tools/i18n_lint_exclusions.txt``) or a NEW regression that fails the
    build with a ``file:line`` pointer. Zero findings after exclusions => 0.

``--check-catalogs``  (T-303, the *completeness + core-purity* gate)
    Key-set parity vs the reference catalog, ``{placeholder}`` parity per key,
    CLDR plural-category correctness (reusing ``pippal.i18n.cldr_plural``), no
    empty / ``⟦⟧``-marker values, width budgets on width-constrained keys, and
    identical-to-en values only where an allowlist justifies it. On the **core**
    side it additionally FAILS on a Pro-term leaking into a core catalog; on the
    **pro** side it lints the overlay alone AND the merged ``{**core, **pro}``
    view and WARNs on an unmarked core-key override.

Both modes are stdlib + the in-repo ``pippal.i18n`` engine and run in well under
10 s. ``--repo`` is auto-detected from the tree; ``--root`` / ``--exclusions``
let the linter's own unit tests point it at a seeded fixture tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import i18n_lint_lib as lib  # sibling import after the sys.path setup above

TOOL_ROOT = Path(__file__).resolve().parents[1]


def repo_config(repo: str, root: Path) -> dict:
    """Per-repo file sets, catalog dir, width budgets and identical-to-en
    allowlists. The allowlists mirror the existing catalog-oracle tests
    (``tests/test_i18n_catalogs.py`` core / ``tests/test_i18n_pro_catalogs.py``
    pro) — the single sanctioned set of values allowed to equal English."""
    if repo == "core":
        return {
            "js_globs": ["webui/js/*.js"],
            "py_globs": ["src/pippal/**/*.py"],
            # webui/js/app.js is a conftest-only bundle regenerated at test time
            # (gitignored, NOT shipped — see docs/strings-inventory); never scan
            # the generated aggregate, only the real ES-module render surfaces.
            "skip_files": ["webui/js/app.js"],
            "catalog_dir": root / "webui" / "i18n",
            "reference_lang": "en",
            "check_core_purity": True,
            "check_merged": False,
            "width_constrained": {"overlay.loading.": 1.2},
            "global_equals_en": {
                "about.link.github",
                "window.settings.title",
                "window.onboarding.title",
                "window.overlay.title",
                "settings.panel.auto_hide_unit",
                "settings.panel.distance_unit",
                "voices.row.meta",
            },
            "per_lang_equals_en": {
                ("de", "settings.voice.engine_label"),
                ("de", "voices.filter.status_label"),
                ("de", "about.link.reddit"),
                ("pt-BR", "voices.filter.status_label"),
            },
        }
    if repo == "pro":
        return {
            "js_globs": ["webui/js/*.js"],
            "py_globs": ["src/pippal_pro/**/*.py"],
            # webui/js/app.js is a conftest-only bundle regenerated at test time
            # (gitignored, NOT shipped — see docs/strings-inventory-pro); scan
            # only the real ES-module render surfaces, never the aggregate.
            "skip_files": ["webui/js/app.js"],
            "catalog_dir": root / "webui" / "i18n" / "pro",
            "reference_lang": "en",
            "check_core_purity": False,
            "check_merged": True,
            "width_constrained": {
                "pro.import.ok": 2.0,
                "pro.settings.ai.endpoint_label": 2.0,
                "pro.tray.": 2.6,
            },
            "global_equals_en": {
                "pro.window.brand",
                "pro.import.audit_rule",
                "pro.tray.mood_menu_unavailable",
                "pro.settings.kokoro.voice_option",
                "pro.settings.pron.rules_fired_item",
            },
            "per_lang_equals_en": {
                ("de", "pro.import.ok"),
                ("hu", "pro.import.ok"),
                ("uk", "pro.import.ok"),
                ("pt-BR", "pro.import.ok"),
                ("pt-BR", "pro.settings.ai.endpoint_label"),
            },
        }
    raise SystemExit(f"unknown repo {repo!r} (expected core|pro)")


def detect_repo(root: Path) -> str:
    if (root / "src" / "pippal_pro").is_dir():
        return "pro"
    if (root / "src" / "pippal").is_dir():
        return "core"
    raise SystemExit(f"cannot detect repo (no src/pippal or src/pippal_pro under {root})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PipPal i18n CI linter (T-302 + T-303).")
    ap.add_argument("--scan-literals", action="store_true", help="no-hardcoded-string gate (T-302)")
    ap.add_argument("--check-catalogs", action="store_true", help="completeness + purity gate (T-303)")
    ap.add_argument("--repo", choices=["core", "pro"], help="repo flavour (auto-detected if omitted)")
    ap.add_argument("--root", type=Path, default=TOOL_ROOT, help="repo root (default: tool's parent)")
    ap.add_argument("--exclusions", type=Path, help="path to exclusions file")
    args = ap.parse_args(argv)

    if not (args.scan_literals or args.check_catalogs):
        ap.error("choose at least one of --scan-literals / --check-catalogs")

    root = args.root.resolve()
    repo = args.repo or detect_repo(root)
    cfg = repo_config(repo, root)
    exc_path = args.exclusions or (root / "tools" / "i18n_lint_exclusions.txt")
    exc = lib.Exclusions.load(exc_path)

    rc = 0
    if args.scan_literals:
        rc |= lib.run_scan_literals(root, cfg, exc)
    if args.check_catalogs:
        rc |= lib.run_check_catalogs(root, repo, cfg)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
