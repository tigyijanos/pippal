"""Unit oracle for T-107 — the Python seams that make every web window boot
in the persisted/resolved language instead of ``navigator.language``.

Three seams, asserted against an INDEPENDENT oracle (the design precedence
rules + the URL/config contract), never a mirror of the implementation:

  * ``app_web._apply_boot_language`` resolves + activates the UI language once
    at startup (``config.language -> system -> en``).
  * ``window_lifecycle._surface_url`` / ``make_window`` carry the resolved
    language as ``?lang=<tag>`` on EVERY surface's load URL.
  * ``bridge.save_config`` re-activates the language on a Settings change and
    echoes back ``language_resolved`` so a reload boots in the new language.

Cross-runtime agreement is asserted structurally here (the tag Python resolves
== the tag embedded in the URL the JS reads); the served Playwright suite
(``e2e/web/test_i18n_boot_language.py``) asserts the DOM side.
"""

from __future__ import annotations

import sys
import types
import unittest.mock as mock

import pytest

from pippal import i18n
from pippal.web_ui import app_web

SIX = ["en", "zh-CN", "de", "hu", "uk", "pt-BR"]


@pytest.fixture(autouse=True)
def _restore_active_language():
    """Save/restore the module-global active language around each test so a
    boot-language mutation never bleeds into another test."""
    original = i18n.get_language()
    try:
        yield
    finally:
        i18n._active_lang = original


# ---------------------------------------------------------------------------
# _apply_boot_language — resolve + activate once at startup
# ---------------------------------------------------------------------------


class TestApplyBootLanguage:
    def test_explicit_pick_activates_that_language(self, monkeypatch):
        # An en OS locale must NOT override an explicit German pick (the core
        # bug: web chrome kept rendering in the OS language on next boot).
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "en-US")
        resolved = app_web._apply_boot_language({"language": "de"})
        assert resolved == "de"
        assert i18n.get_language() == "de"

    def test_auto_follows_supported_system_locale(self, monkeypatch):
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "hu-HU")
        assert app_web._apply_boot_language({"language": ""}) == "hu"
        assert i18n.get_language() == "hu"

    def test_auto_unsupported_system_falls_back_to_en(self, monkeypatch):
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "fr-FR")
        assert app_web._apply_boot_language({"language": ""}) == "en"

    def test_missing_language_key_is_treated_as_auto(self, monkeypatch):
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "de-DE")
        # No "language" key at all — must not raise, resolves via system.
        assert app_web._apply_boot_language({}) == "de"


# ---------------------------------------------------------------------------
# window_lifecycle URL — every surface carries ?lang=<resolved>
# ---------------------------------------------------------------------------


def _fresh_lifecycle(monkeypatch):
    """Import window_lifecycle with a stubbed ``webview`` so ``make_window``
    runs head-less (no real WebView2 / Win32)."""
    fake = types.ModuleType("webview")
    fake.screens = []

    def _create_window(**kwargs):
        w = mock.MagicMock()
        w.on_top = kwargs.get("on_top", False)
        w.events = mock.MagicMock()
        return w

    fake.create_window = _create_window
    monkeypatch.setitem(sys.modules, "webview", fake)
    for key in list(sys.modules):
        if "pippal.web_ui.window" in key:
            del sys.modules[key]
    from pippal.web_ui.windows import WebWindowManager

    return WebWindowManager, fake


class TestSurfaceUrl:
    def test_url_carries_the_active_language(self, monkeypatch):
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "en-US")
        i18n.set_language("de", SIX)
        from pippal.web_ui import window_lifecycle

        url = window_lifecycle._surface_url("http://127.0.0.1:9999", "settings")
        assert url == "http://127.0.0.1:9999/index.html?view=settings&lang=de"

    def test_lang_param_follows_the_view_param(self, monkeypatch):
        # The ?lang= seam must NOT clobber ?view= — it is appended as a second
        # query parameter (JS reads both independently).
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "en-US")
        i18n.set_language("hu", SIX)
        from pippal.web_ui import window_lifecycle

        url = window_lifecycle._surface_url("http://h", "overlay")
        assert "view=overlay" in url
        assert url.endswith("&lang=hu")

    def test_url_omits_lang_when_i18n_reports_empty(self, monkeypatch):
        from pippal.web_ui import window_lifecycle

        monkeypatch.setattr(window_lifecycle, "_resolved_lang", lambda: "")
        url = window_lifecycle._surface_url("http://h", "voices")
        assert url == "http://h/index.html?view=voices"


class TestMakeWindowCarriesLanguage:
    @pytest.mark.parametrize(
        "surface", ["settings", "voices", "overlay", "notices", "onboarding"]
    )
    def test_every_surface_boots_with_resolved_lang(self, monkeypatch, surface):
        """Integration: the REAL make_window path passes ?lang=<resolved> to
        create_window for EVERY web surface (settings/voices/overlay/notices/
        onboarding) — the T-107 AC 'every web surface boots in the language'."""
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "en-US")
        i18n.set_language("de", SIX)
        WebWindowManager, fake = _fresh_lifecycle(monkeypatch)
        created: dict[str, str] = {}

        def _capture(**kwargs):
            created["url"] = kwargs.get("url", "")
            w = mock.MagicMock()
            w.on_top = kwargs.get("on_top", False)
            w.events = mock.MagicMock()
            return w

        fake.create_window = _capture

        mgr = WebWindowManager()
        mgr._base_url = "http://127.0.0.1:9999"
        mgr._bridge = mock.MagicMock()
        mgr._started = True
        mgr._make_window(surface)

        assert f"view={surface}" in created["url"]
        assert "lang=de" in created["url"], created["url"]


# ---------------------------------------------------------------------------
# save_config — Settings change re-activates the language + echoes it back
# ---------------------------------------------------------------------------


class TestSaveConfigReactivatesLanguage:
    def _bridge(self, monkeypatch):
        monkeypatch.setattr(i18n, "_read_system_locale", lambda: "en-US")
        from pippal import config as config_mod
        from pippal.web_ui import bridge as bridge_mod
        from pippal.web_ui.bridge import PipPalBridge

        # Neutralise disk persistence: patch the ``save_config`` symbol the
        # bridge actually calls so the test never touches the real profile
        # (its ``path`` is a bound default arg, so patching the constant would
        # not redirect it).
        monkeypatch.setattr(bridge_mod, "save_config", lambda *a, **k: None)

        engine = mock.MagicMock()
        overlay = mock.MagicMock()
        cfg = dict(config_mod.DEFAULT_CONFIG)
        bridge = PipPalBridge(engine, cfg, overlay)
        return bridge

    def test_change_activates_and_returns_resolved(self, monkeypatch):
        bridge = self._bridge(monkeypatch)
        assert i18n.get_language() != "de" or True  # baseline irrelevant
        result = bridge.save_config({"language": "de"})
        assert result["ok"] is True
        assert result["language_resolved"] == "de"
        # Python runtime now agrees so tray/toasts/titles render in German.
        assert i18n.get_language() == "de"

    def test_auto_clear_resolves_via_system(self, monkeypatch):
        bridge = self._bridge(monkeypatch)
        bridge.save_config({"language": "de"})
        assert i18n.get_language() == "de"
        # Switching back to Auto ("") re-resolves via the (mocked) en system.
        result = bridge.save_config({"language": ""})
        assert result["language_resolved"] == "en"
        assert i18n.get_language() == "en"
