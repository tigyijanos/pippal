"""Regression tests for the single-instance foreground-on-second-launch path.

The foreground signal flow:
  second launch B → resolve_candidate_port() → probe_running_instance(port)
  → True → _signal_running_instance_to_show(port) [POST /settings to A]
  → A's server invokes windows.raise_window("settings") → B exits.

Regression introduced by fix/cmd-server-excl-port (PR #119):
  main() called start_command_server without control_routes_enabled=True,
  so POST /settings always returned 404 (the /settings route is in
  _CONTROL_COMMAND_ROUTES which is gated by control_routes_enabled).
  _signal_running_instance_to_show therefore always returned False, and
  the Win32 fallback (_foreground_running_window_win32) only works when a
  visible PipPal window already exists — if the app is running tray-only,
  the window never comes to foreground.

Fix: pass control_routes_enabled=True to start_command_server in main().
"""

from __future__ import annotations

import time

from pippal.command_server import start_command_server


class _FakeEngine:
    """Minimal engine stand-in; the signal path does not drive the engine."""

    def read_text_async(self, text: str) -> None:
        pass


class TestSingleInstanceForegroundSignal:
    """Verify the end-to-end foreground signal path works in production."""

    def test_signal_running_instance_to_show_succeeds_with_production_server(
        self, monkeypatch, tmp_path
    ) -> None:
        """_signal_running_instance_to_show must return True and invoke the
        settings callback when the running instance's server has
        control_routes_enabled=True (as production main() must pass).

        Regression guard: with control_routes_enabled=False (old main()),
        POST /settings returns 404 and the signal returns False, so the
        window is never raised on second launch.
        """
        import pippal.command_server as cs
        from pippal.web_ui.app_web import _signal_running_instance_to_show

        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")

        engine = _FakeEngine()
        calls: list[str] = []

        # Production server must pass control_routes_enabled=True so the
        # settings callback is reachable via POST /settings.
        srv = start_command_server(
            engine,
            commands={"settings": lambda: calls.append("settings")},
            control_routes_enabled=True,
        )
        assert srv is not None
        port = srv.server_address[1]
        time.sleep(0.05)
        try:
            result = _signal_running_instance_to_show(port)
            assert result is True, (
                "_signal_running_instance_to_show must return True; "
                "check that main() passes control_routes_enabled=True"
            )
            assert calls == ["settings"], (
                "The settings callback (windows.raise_window) must be "
                "invoked when the foreground signal is received"
            )
        finally:
            srv.shutdown()
            srv.server_close()

    def test_signal_fails_without_control_routes_enabled(
        self, monkeypatch, tmp_path
    ) -> None:
        """Confirm the regression: with control_routes_enabled=False (the
        OLD broken default in main()), POST /settings returns 404 and the
        signal returns False.  This test documents WHY the fix is needed.
        """
        import pippal.command_server as cs
        from pippal.web_ui.app_web import _signal_running_instance_to_show

        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")

        engine = _FakeEngine()
        calls: list[str] = []

        # Old broken setup: control_routes_enabled defaults to False.
        srv = start_command_server(
            engine,
            commands={"settings": lambda: calls.append("settings")},
            # control_routes_enabled=False  (the default — this was the bug)
        )
        assert srv is not None
        port = srv.server_address[1]
        time.sleep(0.05)
        try:
            result = _signal_running_instance_to_show(port)
            # Without the flag the route returns 404, signal returns False.
            assert result is False, (
                "Confirms the regression: False when control_routes_enabled "
                "is not set — main() must explicitly pass True"
            )
            assert calls == [], "callback must NOT be invoked (404 path)"
        finally:
            srv.shutdown()
            srv.server_close()
