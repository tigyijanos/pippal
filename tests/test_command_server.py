"""End-to-end-ish tests for the local command server.

Spins a real server on a free port, posts JSON, verifies the engine
seam was called with the right payload."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from pippal.command_server import (
    ALLOWED_EXTENSIONS,
    MAX_READ_FILE_BYTES,
    probe_running_instance,
    read_cmd_port_file,
    resolve_candidate_port,
    start_command_server,
    write_cmd_port_file,
)


class _FakeEngine:
    """Captures calls so tests can assert against them."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.replay_calls: list[str] = []

    def read_text_async(self, text: str) -> None:
        self.calls.append(text)

    def replay_text(self, text: str) -> None:
        self.replay_calls.append(text)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(port: int, path: str, body: dict[str, Any]) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _post_empty(port: int, path: str) -> tuple[int, str]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=b"",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _get(port: int, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                     timeout=2) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture()
def server() -> tuple[_FakeEngine, int]:
    engine = _FakeEngine()
    port = _free_port()
    srv = start_command_server(engine, port=port)
    assert srv is not None
    # Tiny wait so the listener thread is actually accepting.
    time.sleep(0.05)
    yield engine, port
    srv.shutdown()
    srv.server_close()


class TestReadEndpoint:
    def test_read_text_routes_to_engine(self, server):
        engine, port = server
        code, _ = _post(port, "/read", {"text": "hello"})
        assert code == 200
        assert engine.calls == ["hello"]
        assert engine.replay_calls == []

    def test_read_strips_whitespace_and_rejects_empty(self, server):
        engine, port = server
        code, _ = _post(port, "/read", {"text": "   "})
        assert code == 400
        assert engine.calls == []

    def test_read_oversize_text_rejected(self, server):
        engine, port = server
        big = "x" * (200 * 1024 + 10)
        code, _ = _post(port, "/read", {"text": big})
        assert code == 413
        assert engine.calls == []


class TestReadFileEndpoint:
    def test_known_extension_succeeds(self, tmp_path: Path, server):
        engine, port = server
        f = tmp_path / "note.txt"
        f.write_text("hello from a file", encoding="utf-8")
        code, _ = _post(port, "/read-file", {"path": str(f)})
        assert code == 200
        assert engine.calls == ["hello from a file"]
        assert engine.replay_calls == []

    def test_unknown_extension_rejected(self, tmp_path: Path, server):
        engine, port = server
        f = tmp_path / "thing.exe"
        f.write_bytes(b"not text")
        code, _ = _post(port, "/read-file", {"path": str(f)})
        assert code == 415
        assert engine.calls == []

    def test_oversize_file_rejected(self, tmp_path: Path, server):
        engine, port = server
        f = tmp_path / "big.txt"
        f.write_bytes(b"a" * (MAX_READ_FILE_BYTES + 1))
        code, _ = _post(port, "/read-file", {"path": str(f)})
        assert code == 413
        assert engine.calls == []

    def test_binary_content_rejected(self, tmp_path: Path, server):
        engine, port = server
        f = tmp_path / "ish.txt"
        # Allowed extension, but the bytes look binary (NUL inside the
        # first 1 KB heuristic).
        f.write_bytes(b"hello\x00world")
        code, _ = _post(port, "/read-file", {"path": str(f)})
        assert code == 415
        assert engine.calls == []

    def test_missing_file_404(self, tmp_path: Path, server):
        _, port = server
        code, _ = _post(port, "/read-file", {"path": str(tmp_path / "nope.txt")})
        assert code == 404


class TestServerWiring:
    def test_ping(self, server):
        _, port = server
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping",
                                     timeout=2) as r:
            assert r.status == 200

    def test_unknown_path_is_404(self, server):
        _, port = server
        code, _ = _post(port, "/nope", {})
        assert code == 404

    def test_control_routes_are_404_by_default_even_with_callbacks(self):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[str] = []
        srv = start_command_server(
            engine,
            port=port,
            commands={
                "settings": lambda: calls.append("settings"),
                "stop": lambda: calls.append("stop"),
            },
            json_commands={
                "settings.apply": lambda _data: calls.append("settings.apply"),
                "ui.click": lambda _data: calls.append("ui.click"),
                "ui.window_move": lambda _data: calls.append("ui.window_move"),
            },
            queries={"state": lambda: calls.append("state") or {"ok": True}},
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            assert _get(port, "/state")[0] == 404
            assert _post_empty(port, "/settings")[0] == 404
            assert _post_empty(port, "/stop")[0] == 404
            assert _post(port, "/settings/apply", {"values": {}})[0] == 404
            assert _post(port, "/ui/click", {"target": "x"})[0] == 404
            assert _post(port, "/ui/window-move", {"target": "x"})[0] == 404
            assert calls == []
        finally:
            srv.shutdown()
            srv.server_close()

    def test_settings_command_routes_to_callback(self):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[str] = []
        srv = start_command_server(
            engine,
            port=port,
            commands={"settings": lambda: calls.append("settings")},
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post_empty(port, "/settings")
            assert code == 200
            assert calls == ["settings"]
        finally:
            srv.shutdown()
            srv.server_close()

    def test_voice_manager_command_routes_to_callback(self):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[str] = []
        srv = start_command_server(
            engine,
            port=port,
            commands={"voice-manager": lambda: calls.append("voice-manager")},
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post_empty(port, "/voice-manager")
            assert code == 200
            assert calls == ["voice-manager"]
        finally:
            srv.shutdown()
            srv.server_close()

    def test_first_run_check_command_routes_to_callback(self):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[str] = []
        srv = start_command_server(
            engine,
            port=port,
            commands={"first-run-check": lambda: calls.append("first-run-check")},
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post_empty(port, "/first-run-check")
            assert code == 200
            assert calls == ["first-run-check"]
        finally:
            srv.shutdown()
            srv.server_close()

    @pytest.mark.parametrize("path", ["/stop", "/pause", "/prev", "/replay", "/next"])
    def test_player_commands_route_to_callbacks(self, path: str):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[str] = []
        name = path.removeprefix("/")
        srv = start_command_server(
            engine,
            port=port,
            commands={name: lambda n=name: calls.append(n)},
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post_empty(port, path)
            assert code == 200
            assert calls == [name]
        finally:
            srv.shutdown()
            srv.server_close()

    def test_settings_command_is_404_without_callback(self):
        engine = _FakeEngine()
        port = _free_port()
        srv = start_command_server(
            engine,
            port=port,
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post_empty(port, "/settings")
            assert code == 404
        finally:
            srv.shutdown()
            srv.server_close()

    def test_json_settings_apply_command_routes_payload(self):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[dict[str, Any]] = []
        srv = start_command_server(
            engine,
            port=port,
            json_commands={
                "settings.apply": lambda data: calls.append(data) or {"ok": True}
            },
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, body = _post(port, "/settings/apply", {"values": {"speed": 1.2}})
            assert code == 200
            assert calls == [{"values": {"speed": 1.2}}]
            assert json.loads(body) == {"ok": True}
        finally:
            srv.shutdown()
            srv.server_close()

    def test_json_settings_apply_is_404_without_callback(self):
        engine = _FakeEngine()
        port = _free_port()
        srv = start_command_server(
            engine,
            port=port,
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post(port, "/settings/apply", {"values": {}})
            assert code == 404
        finally:
            srv.shutdown()
            srv.server_close()

    @pytest.mark.parametrize(
        ("path", "name"),
        [
            ("/ui/click", "ui.click"),
            ("/ui/type", "ui.type"),
            ("/ui/set", "ui.set"),
            ("/ui/select", "ui.select"),
            ("/ui/window-move", "ui.window_move"),
            ("/ui/overlay-click", "ui.overlay_click"),
        ],
    )
    def test_ui_json_commands_route_payload(self, path: str, name: str):
        engine = _FakeEngine()
        port = _free_port()
        calls: list[tuple[str, dict[str, Any]]] = []
        srv = start_command_server(
            engine,
            port=port,
            json_commands={
                name: lambda data, n=name: calls.append((n, data)) or {"ok": True}
            },
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, body = _post(path=path, port=port, body={"target": "x"})
            assert code == 200
            assert calls == [(name, {"target": "x"})]
            assert json.loads(body) == {"ok": True}
        finally:
            srv.shutdown()
            srv.server_close()

    @pytest.mark.parametrize(
        "path",
        [
            "/ui/click",
            "/ui/type",
            "/ui/set",
            "/ui/select",
            "/ui/window-move",
            "/ui/overlay-click",
        ],
    )
    def test_ui_json_commands_are_404_without_callback(self, path: str):
        engine = _FakeEngine()
        port = _free_port()
        srv = start_command_server(
            engine,
            port=port,
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _post(port, path, {"target": "x"})
            assert code == 404
        finally:
            srv.shutdown()
            srv.server_close()

    def test_state_query_returns_json_payload(self):
        engine = _FakeEngine()
        port = _free_port()
        srv = start_command_server(
            engine,
            port=port,
            queries={"state": lambda: {"settings_open": True}},
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, body = _get(port, "/state")
            assert code == 200
            assert json.loads(body) == {"settings_open": True}
        finally:
            srv.shutdown()
            srv.server_close()

    def test_state_query_is_404_without_callback(self):
        engine = _FakeEngine()
        port = _free_port()
        srv = start_command_server(
            engine,
            port=port,
            control_routes_enabled=True,
        )
        assert srv is not None
        time.sleep(0.05)
        try:
            code, _ = _get(port, "/state")
            assert code == 404
        finally:
            srv.shutdown()
            srv.server_close()

    def test_allowed_extensions_constant(self):
        # Sanity check the constant is in sync with the docstring.
        for ext in ALLOWED_EXTENSIONS:
            assert ext.startswith(".") and ext == ext.lower()

    def test_start_returns_none_when_port_is_already_bound(self):
        engine = _FakeEngine()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            port = s.getsockname()[1]

            assert start_command_server(engine, port=port) is None


class TestE2EHermeticityHook:
    """The opt-in ephemeral-port + per-test-token hook used by the web
    E2E harness. Must be strictly behaviour-preserving for production
    (env unset => byte-identical to before)."""

    def test_production_default_is_unchanged_when_env_unset(
        self, monkeypatch
    ):
        # No env vars => the fixed well-known port, no token gate.
        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        monkeypatch.delenv("PIPPAL_CMD_SERVER_TOKEN", raising=False)
        from pippal.paths import CMD_SERVER_PORT

        engine = _FakeEngine()
        # Bind the real fixed port only if it's free here; the contract
        # we assert is "no env => default port arg used, no token".
        srv = start_command_server(engine, port=_free_port())
        assert srv is not None
        try:
            port = srv.server_address[1]
            time.sleep(0.05)
            # No token required: a plain request is accepted.
            status, _ = _post(port, "/read", {"text": "hello"})
            assert status == 200
            assert engine.calls == ["hello"]
            # Env was not written (production never touches it).
            assert "PIPPAL_CMD_SERVER_PORT" not in os.environ
            assert CMD_SERVER_PORT == 51677
        finally:
            srv.shutdown()
            srv.server_close()

    def test_env_port_zero_binds_ephemeral_and_publishes_it(
        self, monkeypatch
    ):
        monkeypatch.setenv("PIPPAL_CMD_SERVER_PORT", "0")
        monkeypatch.delenv("PIPPAL_CMD_SERVER_TOKEN", raising=False)
        engine = _FakeEngine()
        # Default port arg -> env override kicks in -> OS picks a port.
        srv = start_command_server(engine)
        assert srv is not None
        try:
            bound = srv.server_address[1]
            assert bound != 51677
            # The actually-bound port was published back to the env.
            assert os.environ["PIPPAL_CMD_SERVER_PORT"] == str(bound)
            time.sleep(0.05)
            status, _ = _post(bound, "/read", {"text": "ephem"})
            assert status == 200 and engine.calls == ["ephem"]
        finally:
            srv.shutdown()
            srv.server_close()

    def test_token_is_required_and_enforced_when_set(self, monkeypatch):
        monkeypatch.setenv("PIPPAL_CMD_SERVER_PORT", "0")
        monkeypatch.setenv("PIPPAL_CMD_SERVER_TOKEN", "secret-token-123")
        engine = _FakeEngine()
        srv = start_command_server(engine)
        assert srv is not None
        try:
            port = srv.server_address[1]
            time.sleep(0.05)

            # No token -> rejected (404), engine NOT driven.
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/read",
                data=json.dumps({"text": "no-token"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            code = None
            try:
                urllib.request.urlopen(req, timeout=2)
            except urllib.error.HTTPError as e:
                code = e.code
            assert code == 404
            assert engine.calls == []

            # Wrong token -> rejected.
            req2 = urllib.request.Request(
                f"http://127.0.0.1:{port}/read",
                data=json.dumps({"text": "bad"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-PipPal-Token": "wrong",
                },
            )
            code2 = None
            try:
                urllib.request.urlopen(req2, timeout=2)
            except urllib.error.HTTPError as e:
                code2 = e.code
            assert code2 == 404
            assert engine.calls == []

            # Correct token -> accepted, engine driven.
            req3 = urllib.request.Request(
                f"http://127.0.0.1:{port}/read",
                data=json.dumps({"text": "ok"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-PipPal-Token": "secret-token-123",
                },
            )
            with urllib.request.urlopen(req3, timeout=2) as r:
                assert r.status == 200
            assert engine.calls == ["ok"]
        finally:
            srv.shutdown()
            srv.server_close()

    def test_open_file_helper_targets_env_instance_with_token(
        self, monkeypatch, tmp_path
    ):
        """`python -m pippal.open_file` (the registry command) must hit
        the env-published port WITH the token when the hooks are set —
        the exact path the hermetic E2E test relies on."""
        monkeypatch.setenv("PIPPAL_CMD_SERVER_PORT", "0")
        monkeypatch.setenv("PIPPAL_CMD_SERVER_TOKEN", "tok-xyz")
        engine = _FakeEngine()
        srv = start_command_server(engine)
        assert srv is not None
        try:
            time.sleep(0.05)
            target = tmp_path / "doc.txt"
            target.write_text("hermetic open-file marker", "utf-8")
            import sys

            from pippal.open_file import main as _open_main

            monkeypatch.setattr(sys, "argv", ["open_file", str(target)])
            assert _open_main() == 0
            # The engine really read the opened file's contents via the
            # env-targeted, token-gated instance.
            deadline = time.time() + 3.0
            while time.time() < deadline and not engine.calls:
                time.sleep(0.02)
            assert engine.calls == ["hermetic open-file marker"]
        finally:
            srv.shutdown()
            srv.server_close()


class TestExcludedPortFallback:
    """The bind-with-fallback + connect-first fix for excluded/in-use default
    ports (WinError 10013 WSAEACCES from Hyper-V/WSL2/Docker reserved ranges).

    These tests verify:
    1. When the default port cannot be bound, the server falls back to a
       free OS-assigned port and starts listening (NOT treated as "already
       running").
    2. When a live instance IS listening on the recorded port, a second
       startup's connect-first probe detects it (foreground+exit path).
    3. Port persistence: the bound port is written to CMD_PORT_FILE.
    4. resolve_candidate_port reads the persisted file when no env is set.
    """

    def test_fallback_to_free_port_when_default_excluded(
        self, monkeypatch, tmp_path
    ):
        """Simulate an excluded/in-use default port via monkeypatch.

        We intercept the _SingleInstanceHTTPServer constructor to raise
        WSAEACCES (WinError 10013) for the default port 51677 and verify
        that start_command_server falls back to a free port (port 0) rather
        than returning None.
        """
        import errno

        import pippal.command_server as cs
        from pippal.paths import CMD_SERVER_PORT

        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        monkeypatch.delenv("PIPPAL_CMD_SERVER_TOKEN", raising=False)
        # Redirect CMD_PORT_FILE writes to tmp_path.
        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")

        # Patch _SingleInstanceHTTPServer to raise for the default port.
        _real_server = cs._SingleInstanceHTTPServer

        def _patched_server(addr, handler):
            if addr[1] == CMD_SERVER_PORT:
                # Simulate WinError 10013 WSAEACCES (excluded port).
                err = OSError(
                    "[WinError 10013] An attempt was made to access a "
                    "socket in a way forbidden by its access permissions"
                )
                err.errno = errno.EACCES
                raise err
            return _real_server(addr, handler)

        monkeypatch.setattr(cs, "_SingleInstanceHTTPServer", _patched_server)

        engine = _FakeEngine()
        # Must NOT return None — must fall back to a free port.
        srv = start_command_server(engine)
        assert srv is not None, (
            "start_command_server must NOT return None on excluded-port "
            "bind failure; it should fall back to a free OS-assigned port"
        )
        try:
            bound_port = srv.server_address[1]
            assert bound_port != CMD_SERVER_PORT, (
                "Expected a fallback (non-default) port, got the default"
            )
            assert bound_port > 0

            # Server is actually serving.
            time.sleep(0.05)
            status, _ = _post(bound_port, "/read", {"text": "fallback-ok"})
            assert status == 200
            assert engine.calls == ["fallback-ok"]

            # Port was persisted to CMD_PORT_FILE.
            assert (tmp_path / ".cmd_port").exists()
            assert int((tmp_path / ".cmd_port").read_text().strip()) == bound_port
        finally:
            srv.shutdown()
            srv.server_close()

    def test_connect_first_detects_live_instance(self, monkeypatch, tmp_path):
        """When a live instance is listening on the recorded port, the
        connect-first probe returns True so a second startup can foreground
        it instead of trying to bind a new port."""
        import pippal.command_server as cs

        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")

        engine = _FakeEngine()
        # Start a real server (simulates the first running instance).
        srv = start_command_server(engine)
        assert srv is not None
        try:
            bound_port = srv.server_address[1]
            time.sleep(0.05)

            # probe_running_instance should return True for the live server.
            assert probe_running_instance(bound_port), (
                "probe_running_instance must return True when the instance "
                "is listening"
            )

            # resolve_candidate_port reads the persisted file.
            candidate = resolve_candidate_port()
            assert candidate == bound_port
            assert probe_running_instance(candidate)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_probe_returns_false_when_nothing_listening(self):
        """probe_running_instance returns False quickly when no server is up."""
        # Use a free port and immediately release it — nothing will listen.
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead_port = s.getsockname()[1]
        # Socket released; port is free but nothing is listening.
        assert not probe_running_instance(dead_port, timeout=0.3)

    def test_write_and_read_cmd_port_file(self, monkeypatch, tmp_path):
        """write_cmd_port_file + read_cmd_port_file round-trip."""
        import pippal.command_server as cs

        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")
        write_cmd_port_file(54321)
        assert read_cmd_port_file() == 54321

    def test_resolve_candidate_port_priority(self, monkeypatch, tmp_path):
        """resolve_candidate_port: env > .cmd_port file > default."""
        import pippal.command_server as cs
        from pippal.paths import CMD_SERVER_PORT

        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")

        # No env, no file -> default.
        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        assert resolve_candidate_port() == CMD_SERVER_PORT

        # File set -> file wins over default.
        write_cmd_port_file(54000)
        assert resolve_candidate_port() == 54000

        # Env set -> env wins over file.
        monkeypatch.setenv("PIPPAL_CMD_SERVER_PORT", "55000")
        assert resolve_candidate_port() == 55000

    def test_fallback_port_persisted_and_probed_across_restart(
        self, monkeypatch, tmp_path
    ):
        """Full lifecycle: first startup falls back to free port, writes
        .cmd_port; second startup reads .cmd_port, probes successfully,
        and would foreground+exit rather than trying to bind."""
        import errno

        import pippal.command_server as cs
        from pippal.paths import CMD_SERVER_PORT

        monkeypatch.delenv("PIPPAL_CMD_SERVER_PORT", raising=False)
        monkeypatch.delenv("PIPPAL_CMD_SERVER_TOKEN", raising=False)
        monkeypatch.setattr(cs, "CMD_PORT_FILE", tmp_path / ".cmd_port")

        _real_server = cs._SingleInstanceHTTPServer

        def _patched_server(addr, handler):
            if addr[1] == CMD_SERVER_PORT:
                err = OSError("excluded")
                err.errno = errno.EACCES
                raise err
            return _real_server(addr, handler)

        monkeypatch.setattr(cs, "_SingleInstanceHTTPServer", _patched_server)

        engine = _FakeEngine()
        # First "startup" — falls back to free port.
        srv = start_command_server(engine)
        assert srv is not None
        try:
            bound_port = srv.server_address[1]
            assert bound_port != CMD_SERVER_PORT
            time.sleep(0.05)

            # Second "startup" simulation: read candidate from file, probe.
            candidate = resolve_candidate_port()
            assert candidate == bound_port
            # Connect-first: should detect the live instance.
            assert probe_running_instance(candidate), (
                "Second startup must detect the running instance via "
                "connect-first probe on the persisted fallback port"
            )
        finally:
            srv.shutdown()
            srv.server_close()
