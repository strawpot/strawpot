"""Tests for integration management API endpoints."""

import time
from unittest.mock import patch

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Patch get_strawpot_home to use a temp directory."""
    monkeypatch.setattr(
        "strawpot_gui.routers.integrations.get_strawpot_home", lambda: tmp_path
    )
    return tmp_path


def _create_integration(home, name, extra_meta=""):
    """Create a minimal INTEGRATION.md manifest."""
    integration_dir = home / "integrations" / name
    integration_dir.mkdir(parents=True)
    content = (
        f"---\nname: {name}\ndescription: A test {name} adapter\n"
        f"metadata:\n  strawpot:\n    entry_point: python adapter.py\n"
        f"    auto_start: false\n"
        f"    env:\n"
        f"      STRAWPOT_BOT_TOKEN:\n"
        f"        required: true\n"
        f"        description: Bot API token\n"
        f"{extra_meta}"
        f"---\n# {name.title()} Adapter\n\nBody text."
    )
    (integration_dir / "INTEGRATION.md").write_text(content)
    return integration_dir


class TestListIntegrations:
    def test_list_empty(self, client, home):
        resp = client.get("/api/integrations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_one(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["name"] == "telegram"
        assert item["description"] == "A test telegram adapter"
        assert item["entry_point"] == "python adapter.py"
        assert item["status"] == "stopped"
        assert item["pid"] is None

    def test_list_multiple(self, client, home):
        _create_integration(home, "telegram")
        _create_integration(home, "slack")
        resp = client.get("/api/integrations")
        names = [i["name"] for i in resp.json()]
        assert "slack" in names
        assert "telegram" in names

    def test_excludes_hidden_dirs(self, client, home):
        _create_integration(home, "telegram")
        hidden = home / "integrations" / ".hidden"
        hidden.mkdir(parents=True)
        (hidden / "INTEGRATION.md").write_text("---\nname: hidden\n---\n")
        resp = client.get("/api/integrations")
        names = [i["name"] for i in resp.json()]
        assert "telegram" in names
        assert "hidden" not in names


class TestGetIntegration:
    def test_get_detail(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations/telegram")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "telegram"
        assert data["body"].strip().startswith("# Telegram Adapter")
        assert "frontmatter" in data
        assert data["status"] == "stopped"

    def test_get_not_found(self, client, home):
        resp = client.get("/api/integrations/nonexistent")
        assert resp.status_code == 404


class TestIntegrationConfig:
    def test_get_config_schema(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations/telegram/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "STRAWPOT_BOT_TOKEN" in data["env_schema"]
        assert data["env_schema"]["STRAWPOT_BOT_TOKEN"]["required"] is True
        assert data["config_values"] == {}

    def test_put_config(self, client, home):
        _create_integration(home, "telegram")
        resp = client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "123:ABC"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify saved
        resp = client.get("/api/integrations/telegram/config")
        assert resp.json()["config_values"]["STRAWPOT_BOT_TOKEN"] == "123:ABC"

    def test_put_config_updates_existing(self, client, home):
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "old"}},
        )
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "new"}},
        )
        resp = client.get("/api/integrations/telegram/config")
        assert resp.json()["config_values"]["STRAWPOT_BOT_TOKEN"] == "new"

    def test_put_config_not_found(self, client, home):
        resp = client.put(
            "/api/integrations/nonexistent/config",
            json={"config_values": {"key": "val"}},
        )
        assert resp.status_code == 404

    def test_delete_config(self, client, home):
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "123:ABC"}},
        )
        resp = client.delete("/api/integrations/telegram/config")
        assert resp.status_code == 200

        # Config should be cleared
        resp = client.get("/api/integrations/telegram/config")
        assert resp.json()["config_values"] == {}

    def test_config_visible_in_list(self, client, home):
        """Saved config values appear when listing integrations."""
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "123:ABC"}},
        )
        resp = client.get("/api/integrations")
        item = resp.json()[0]
        assert item["config_values"]["STRAWPOT_BOT_TOKEN"] == "123:ABC"


class TestIntegrationLifecycle:
    def test_start_integration(self, client, home):
        """Start spawns a subprocess and updates DB state."""
        integration_dir = _create_integration(home, "telegram")
        # Create a dummy adapter script that sleeps
        (integration_dir / "adapter.py").write_text(
            "import time; time.sleep(60)"
        )
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "123:ABC"}},
        )
        resp = client.post("/api/integrations/telegram/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["pid"] is not None

        # Clean up: stop the process
        client.post("/api/integrations/telegram/stop")

    def test_start_not_found(self, client, home):
        resp = client.post("/api/integrations/nonexistent/start")
        assert resp.status_code == 404

    def test_start_no_entry_point(self, client, home):
        """Integration with no entry_point returns 422."""
        integration_dir = home / "integrations" / "broken"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text(
            "---\nname: broken\ndescription: No entry point\n"
            "metadata:\n  strawpot: {}\n---\nBody."
        )
        resp = client.post("/api/integrations/broken/start")
        assert resp.status_code == 422

    def test_start_already_running(self, client, home):
        """Starting an already-running integration returns 409."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text(
            "import time; time.sleep(60)"
        )
        client.post("/api/integrations/telegram/start")
        resp = client.post("/api/integrations/telegram/start")
        assert resp.status_code == 409

        client.post("/api/integrations/telegram/stop")

    def test_stop_integration(self, client, home):
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text(
            "import time; time.sleep(60)"
        )
        client.post("/api/integrations/telegram/start")
        resp = client.post("/api/integrations/telegram/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_stop_not_running(self, client, home):
        _create_integration(home, "telegram")
        resp = client.post("/api/integrations/telegram/stop")
        assert resp.status_code == 409

    def test_status_stopped(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations/telegram/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_status_running(self, client, home):
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text(
            "import time; time.sleep(60)"
        )
        client.post("/api/integrations/telegram/start")
        resp = client.get("/api/integrations/telegram/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert resp.json()["pid"] is not None

        client.post("/api/integrations/telegram/stop")

    def test_status_detects_dead_process(self, client, home):
        """Status endpoint detects dead process and marks as error."""
        _create_integration(home, "telegram")
        # Manually insert a DB row with a fake PID
        from strawpot_gui.db import get_db
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO integrations (name, status, pid) "
                "VALUES (?, 'running', ?)",
                ("telegram", 999999),
            )
        resp = client.get("/api/integrations/telegram/status")
        assert resp.json()["status"] == "error"
        assert "exited unexpectedly" in resp.json()["last_error"]

    def test_start_writes_log_file(self, client, home):
        """Adapter stdout/stderr goes to .log file."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text(
            "print('hello from adapter')"
        )
        client.post("/api/integrations/telegram/start")
        time.sleep(0.5)  # let process finish
        log_path = integration_dir / ".log"
        assert log_path.exists()
        assert "hello from adapter" in log_path.read_text()


class TestInstallUninstall:
    def test_install_calls_strawhub(self, client, home):
        """Install endpoint calls strawhub with correct args."""
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "Installed telegram", "stderr": ""}
            resp = client.post(
                "/api/integrations/install",
                json={"name": "telegram"},
            )
            assert resp.status_code == 200
            assert resp.json()["exit_code"] == 0
            mock.assert_called_once_with("install", "integration", "-y", "telegram")

    def test_install_missing_name(self, client, home):
        resp = client.post("/api/integrations/install", json={"name": ""})
        assert resp.status_code == 400

    def test_install_strips_whitespace(self, client, home):
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
            client.post("/api/integrations/install", json={"name": "  telegram  "})
            mock.assert_called_once_with("install", "integration", "-y", "telegram")

    def test_uninstall_calls_strawhub(self, client, home):
        """Uninstall endpoint calls strawhub with correct args."""
        _create_integration(home, "telegram")
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "Removed telegram", "stderr": ""}
            resp = client.delete("/api/integrations/telegram")
            assert resp.status_code == 200
            assert resp.json()["exit_code"] == 0
            mock.assert_called_once_with("uninstall", "integration", "telegram")

    def test_uninstall_cleans_db_state(self, client, home):
        """Uninstall removes DB rows for config and status."""
        _create_integration(home, "telegram")
        # Save config and ensure DB row exists
        client.put(
            "/api/integrations/telegram/config",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "abc"}},
        )
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
            client.delete("/api/integrations/telegram")

        # DB state should be gone
        from strawpot_gui.db import get_db
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM integrations WHERE name = ?", ("telegram",)
            ).fetchone()
            assert row is None
            config = conn.execute(
                "SELECT * FROM integration_config WHERE integration_name = ?", ("telegram",)
            ).fetchall()
            assert len(config) == 0

    def test_update_calls_strawhub(self, client, home):
        """Update endpoint calls strawhub with correct args."""
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "Updated telegram", "stderr": ""}
            resp = client.post(
                "/api/integrations/update",
                json={"name": "telegram"},
            )
            assert resp.status_code == 200
            assert resp.json()["exit_code"] == 0
            mock.assert_called_once_with("update", "integration", "telegram")

    def test_update_missing_name(self, client, home):
        resp = client.post("/api/integrations/update", json={"name": ""})
        assert resp.status_code == 400

    def test_reinstall_calls_strawhub(self, client, home):
        """Reinstall reads .version and calls strawhub install --version --force."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / ".version").write_text("1.2.0")
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "Reinstalled telegram", "stderr": ""}
            resp = client.post(
                "/api/integrations/reinstall",
                json={"name": "telegram"},
            )
            assert resp.status_code == 200
            mock.assert_called_once_with(
                "install", "integration", "-y", "telegram", "--version", "1.2.0", "--force",
            )

    def test_reinstall_missing_version_file(self, client, home):
        """Reinstall returns 404 when no .version file exists."""
        _create_integration(home, "telegram")
        resp = client.post(
            "/api/integrations/reinstall",
            json={"name": "telegram"},
        )
        assert resp.status_code == 404

    def test_uninstall_stops_running_process(self, client, home):
        """Uninstall stops a running adapter before removing."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text("import time; time.sleep(60)")
        client.post("/api/integrations/telegram/start")

        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
            resp = client.delete("/api/integrations/telegram")
            assert resp.status_code == 200

        # DB should show no running state
        from strawpot_gui.db import get_db
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM integrations WHERE name = ?", ("telegram",)
            ).fetchone()
            assert row is None


class TestOrphanedIntegrations:
    def test_mark_orphaned_stopped(self, client, home):
        """Orphaned integrations (dead PID) are marked stopped at startup."""
        from strawpot_gui.db import get_db
        from strawpot_gui.routers.integrations import mark_orphaned_integrations_stopped

        _create_integration(home, "telegram")
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO integrations (name, status, pid) VALUES (?, 'running', ?)",
                ("telegram", 999999),
            )
        mark_orphaned_integrations_stopped(db_path)
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, pid FROM integrations WHERE name = ?",
                ("telegram",),
            ).fetchone()
        assert row["status"] == "stopped"
        assert row["pid"] is None


class TestIntegrationLogs:
    def test_logs_ws_not_found(self, client, home):
        """WebSocket for nonexistent integration returns error and closes."""
        with client.websocket_connect("/api/integrations/nonexistent/logs/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["message"]

    def test_logs_ws_stopped_sends_done(self, client, home):
        """Stopped integration sends snapshot then done."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / ".log").write_text("line1\nline2\n")
        with client.websocket_connect("/api/integrations/telegram/logs/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "log_snapshot"
            assert "line1" in msg["lines"]
            assert "line2" in msg["lines"]
            msg = ws.receive_json()
            assert msg["type"] == "log_done"

    def test_logs_ws_empty_log(self, client, home):
        """No log file yet — snapshot has empty lines, then done."""
        _create_integration(home, "telegram")
        with client.websocket_connect("/api/integrations/telegram/logs/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "log_snapshot"
            assert msg["lines"] == []
            msg = ws.receive_json()
            assert msg["type"] == "log_done"

    def test_logs_ws_snapshot_includes_existing_content(self, client, home):
        """Snapshot includes existing log content."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / ".log").write_text(
            "line1\nline2\nline3\nline4\nline5\n"
        )
        with client.websocket_connect("/api/integrations/telegram/logs/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "log_snapshot"
            assert len(msg["lines"]) == 5
            assert msg["lines"][0] == "line1"
            assert msg["lines"][4] == "line5"
            assert msg["offset"] > 0


class TestAutoStart:
    def test_auto_start_launches_flagged_integration(self, client, home):
        """auto_start_integrations() starts integrations with auto_start enabled in DB."""
        from strawpot_gui.routers.integrations import auto_start_integrations

        integration_dir = home / "integrations" / "telegram"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text(
            "---\nname: telegram\ndescription: Test\n"
            "metadata:\n  strawpot:\n    entry_point: python adapter.py\n"
            "---\nBody."
        )
        (integration_dir / "adapter.py").write_text("import time; time.sleep(60)")

        db_path = client.app.state.db_path
        # Enable auto_start in DB
        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO integrations (name, auto_start) VALUES (?, 1)",
                ("telegram",),
            )
        auto_start_integrations(db_path)

        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, pid FROM integrations WHERE name = ?",
                ("telegram",),
            ).fetchone()
        assert row["status"] == "running"
        assert row["pid"] is not None

        # Clean up
        import os
        import signal
        try:
            os.kill(row["pid"], signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def test_auto_start_skips_non_flagged(self, client, home):
        """auto_start_integrations() skips integrations with auto_start disabled in DB."""
        from strawpot_gui.routers.integrations import auto_start_integrations

        _create_integration(home, "telegram")  # auto_start: 0 by default in DB

        db_path = client.app.state.db_path
        auto_start_integrations(db_path)

        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, pid FROM integrations WHERE name = ?",
                ("telegram",),
            ).fetchone()
        assert row["status"] == "stopped"
        assert row["pid"] is None

    def test_auto_start_skips_already_running(self, client, home):
        """auto_start_integrations() skips if already running with live PID."""
        from strawpot_gui.routers.integrations import auto_start_integrations

        integration_dir = home / "integrations" / "telegram"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text(
            "---\nname: telegram\ndescription: Test\n"
            "metadata:\n  strawpot:\n    entry_point: python adapter.py\n"
            "---\nBody."
        )
        (integration_dir / "adapter.py").write_text("import time; time.sleep(60)")

        db_path = client.app.state.db_path
        # Enable auto_start in DB
        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO integrations (name, auto_start) VALUES (?, 1)",
                ("telegram",),
            )

        # First auto-start
        auto_start_integrations(db_path)
        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT pid FROM integrations WHERE name = ?", ("telegram",)
            ).fetchone()
        first_pid = row["pid"]

        # Second auto-start should not spawn a new process
        auto_start_integrations(db_path)
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT pid FROM integrations WHERE name = ?", ("telegram",)
            ).fetchone()
        assert row["pid"] == first_pid

        # Clean up
        import os
        import signal
        try:
            os.kill(first_pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def test_auto_start_handles_bad_entry_point(self, client, home):
        """auto_start_integrations() logs error for invalid entry_point."""
        from strawpot_gui.routers.integrations import auto_start_integrations

        integration_dir = home / "integrations" / "broken"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text(
            "---\nname: broken\ndescription: Test\n"
            "metadata:\n  strawpot:\n    entry_point: /nonexistent/binary\n"
            "---\nBody."
        )

        db_path = client.app.state.db_path
        # Enable auto_start in DB
        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO integrations (name, auto_start) VALUES (?, 1)",
                ("broken",),
            )
        auto_start_integrations(db_path)  # should not raise

        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, last_error FROM integrations WHERE name = ?",
                ("broken",),
            ).fetchone()
        assert row["status"] == "error"
        assert row["last_error"] is not None


class TestManifestParsing:
    def test_scan_skips_dir_without_manifest(self, client, home):
        """Directories without INTEGRATION.md are silently skipped."""
        (home / "integrations" / "empty").mkdir(parents=True)
        resp = client.get("/api/integrations")
        assert resp.json() == []

    def test_scan_handles_malformed_frontmatter(self, client, home):
        """Malformed YAML in manifest is handled gracefully."""
        integration_dir = home / "integrations" / "bad"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text(
            "---\n  invalid:\nyaml: [unterminated\n---\nBody."
        )
        resp = client.get("/api/integrations")
        data = resp.json()
        # Should still appear with defaults rather than crashing
        assert len(data) == 1
        assert data[0]["name"] == "bad"
        assert data[0]["entry_point"] == ""

    def test_scan_handles_empty_manifest(self, client, home):
        """Empty INTEGRATION.md is handled gracefully."""
        integration_dir = home / "integrations" / "empty"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text("")
        resp = client.get("/api/integrations")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "empty"
        assert data[0]["description"] == ""

    def test_scan_handles_no_strawpot_metadata(self, client, home):
        """Manifest with frontmatter but no metadata.strawpot section."""
        integration_dir = home / "integrations" / "minimal"
        integration_dir.mkdir(parents=True)
        (integration_dir / "INTEGRATION.md").write_text(
            "---\nname: minimal\ndescription: Just a name\n---\nBody."
        )
        resp = client.get("/api/integrations")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "minimal"
        assert data[0]["entry_point"] == ""
        assert data[0]["auto_start"] is False
        assert data[0]["env_schema"] == {}
