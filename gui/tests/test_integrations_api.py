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
        assert item["project_id"] == 0

    def test_list_multiple(self, client, home):
        _create_integration(home, "telegram")
        _create_integration(home, "slack")
        resp = client.get("/api/integrations")
        names = [i["name"] for i in resp.json()]
        assert "slack" in names
        assert "telegram" in names

    def test_list_by_project_id(self, client, home):
        """Listing with project_id filters to that project's instances."""
        _create_integration(home, "telegram")
        # Save config for project 1
        client.put(
            "/api/integrations/telegram/config?project_id=1",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "proj1"}},
        )
        # Global should have no config
        resp = client.get("/api/integrations?project_id=0")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["config_values"] == {}
        # Project 1 should have config
        resp = client.get("/api/integrations?project_id=1")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["config_values"]["STRAWPOT_BOT_TOKEN"] == "proj1"
        assert data[0]["project_id"] == 1

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

    def test_config_isolation_between_projects(self, client, home):
        """Config for project_id=0 and project_id=1 are independent."""
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config?project_id=0",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "global_token"}},
        )
        client.put(
            "/api/integrations/telegram/config?project_id=1",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "project_token"}},
        )
        # Each project sees its own config
        resp0 = client.get("/api/integrations/telegram/config?project_id=0")
        assert resp0.json()["config_values"]["STRAWPOT_BOT_TOKEN"] == "global_token"
        resp1 = client.get("/api/integrations/telegram/config?project_id=1")
        assert resp1.json()["config_values"]["STRAWPOT_BOT_TOKEN"] == "project_token"

    def test_delete_config_project_scoped(self, client, home):
        """Deleting config for one project doesn't affect another."""
        _create_integration(home, "telegram")
        client.put(
            "/api/integrations/telegram/config?project_id=0",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "global"}},
        )
        client.put(
            "/api/integrations/telegram/config?project_id=1",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "proj"}},
        )
        client.delete("/api/integrations/telegram/config?project_id=1")
        # Global config untouched
        resp = client.get("/api/integrations/telegram/config?project_id=0")
        assert resp.json()["config_values"]["STRAWPOT_BOT_TOKEN"] == "global"
        # Project 1 config cleared
        resp = client.get("/api/integrations/telegram/config?project_id=1")
        assert resp.json()["config_values"] == {}


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
                "INSERT OR REPLACE INTO integrations (name, project_id, status, pid) "
                "VALUES (?, 0, 'running', ?)",
                ("telegram", 999999),
            )
        resp = client.get("/api/integrations/telegram/status")
        assert resp.json()["status"] == "error"
        assert "exited unexpectedly" in resp.json()["last_error"]

    def test_start_writes_log_file(self, client, home):
        """Adapter stdout/stderr goes to data-dir log file."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text(
            "print('hello from adapter')"
        )
        client.post("/api/integrations/telegram/start")
        time.sleep(0.5)  # let process finish
        log_path = home / "data" / "integrations" / "telegram" / "adapter.log"
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
                "SELECT * FROM integrations WHERE name = ? AND project_id = 0",
                ("telegram",),
            ).fetchone()
            assert row is None
            config = conn.execute(
                "SELECT * FROM integration_config "
                "WHERE integration_name = ? AND project_id = 0",
                ("telegram",),
            ).fetchall()
            assert len(config) == 0

    def test_uninstall_project_scoped_no_strawhub(self, client, home):
        """Uninstalling a project-scoped instance doesn't call strawhub."""
        _create_integration(home, "telegram")
        # Create project instance
        client.put(
            "/api/integrations/telegram/config?project_id=1",
            json={"config_values": {"STRAWPOT_BOT_TOKEN": "proj"}},
        )
        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            resp = client.delete("/api/integrations/telegram?project_id=1")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
            mock.assert_not_called()

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
            mock.assert_called_once_with("update", "-y", "integration", "telegram")

    def test_update_restarts_running_integration(self, client, home):
        """Update stops a running integration and restarts it after success."""
        integration_dir = _create_integration(home, "telegram")
        (integration_dir / "adapter.py").write_text("import time; time.sleep(60)")

        # Start the integration
        client.post("/api/integrations/telegram/start")
        status = client.get("/api/integrations/telegram/status").json()
        assert status["status"] == "running"

        with patch("strawpot_gui.routers.integrations.run_strawhub") as mock:
            mock.return_value = {"exit_code": 0, "stdout": "Updated", "stderr": ""}
            resp = client.post(
                "/api/integrations/update",
                json={"name": "telegram"},
            )
            assert resp.status_code == 200

        # Should be running again after update
        status = client.get("/api/integrations/telegram/status").json()
        assert status["status"] == "running"
        assert status["pid"] is not None

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
                "SELECT * FROM integrations WHERE name = ? AND project_id = 0",
                ("telegram",),
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
                "INSERT OR REPLACE INTO integrations (name, project_id, status, pid) "
                "VALUES (?, 0, 'running', ?)",
                ("telegram", 999999),
            )
        mark_orphaned_integrations_stopped(db_path)
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, pid FROM integrations WHERE name = ? AND project_id = 0",
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
        _create_integration(home, "telegram")
        log_dir = home / "data" / "integrations" / "telegram"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "adapter.log").write_text("line1\nline2\n")
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
        _create_integration(home, "telegram")
        log_dir = home / "data" / "integrations" / "telegram"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "adapter.log").write_text(
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
                "INSERT OR REPLACE INTO integrations (name, project_id, auto_start) "
                "VALUES (?, 0, 1)",
                ("telegram",),
            )
        auto_start_integrations(db_path)

        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, pid FROM integrations WHERE name = ? AND project_id = 0",
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
        # Ensure a DB row exists with auto_start=0
        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO integrations (name, project_id, auto_start) "
                "VALUES (?, 0, 0)",
                ("telegram",),
            )
        auto_start_integrations(db_path)

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, pid FROM integrations WHERE name = ? AND project_id = 0",
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
                "INSERT OR REPLACE INTO integrations (name, project_id, auto_start) "
                "VALUES (?, 0, 1)",
                ("telegram",),
            )

        # First auto-start
        auto_start_integrations(db_path)
        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT pid FROM integrations WHERE name = ? AND project_id = 0",
                ("telegram",),
            ).fetchone()
        first_pid = row["pid"]

        # Second auto-start should not spawn a new process
        auto_start_integrations(db_path)
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT pid FROM integrations WHERE name = ? AND project_id = 0",
                ("telegram",),
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
                "INSERT OR REPLACE INTO integrations (name, project_id, auto_start) "
                "VALUES (?, 0, 1)",
                ("broken",),
            )
        auto_start_integrations(db_path)  # should not raise

        from strawpot_gui.db import get_db
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status, last_error FROM integrations "
                "WHERE name = ? AND project_id = 0",
                ("broken",),
            ).fetchone()
        assert row["status"] == "error"
        assert row["last_error"] is not None


class TestNotify:
    def test_notify_creates_notification(self, client, home):
        _create_integration(home, "telegram")
        resp = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "Hello from agent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] is not None
        assert data["integration_name"] == "telegram"
        assert data["status"] == "pending"

    def test_notify_with_chat_id(self, client, home):
        _create_integration(home, "telegram")
        resp = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "Targeted msg", "chat_id": "12345"},
        )
        assert resp.status_code == 200
        # Verify DB row has the chat_id
        from strawpot_gui.db import get_db
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT chat_id, message, delivered_at FROM integration_notifications "
                "WHERE id = ?",
                (resp.json()["id"],),
            ).fetchone()
        assert row["chat_id"] == "12345"
        assert row["message"] == "Targeted msg"
        assert row["delivered_at"] is None

    def test_notify_empty_message(self, client, home):
        _create_integration(home, "telegram")
        resp = client.post(
            "/api/integrations/telegram/notify",
            json={"message": ""},
        )
        assert resp.status_code == 400

    def test_notify_whitespace_only_message(self, client, home):
        _create_integration(home, "telegram")
        resp = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "   "},
        )
        assert resp.status_code == 400

    def test_notify_not_found(self, client, home):
        resp = client.post(
            "/api/integrations/nonexistent/notify",
            json={"message": "Hello"},
        )
        assert resp.status_code == 404

    def test_notify_multiple_creates_separate_rows(self, client, home):
        _create_integration(home, "telegram")
        r1 = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "First"},
        )
        r2 = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "Second"},
        )
        assert r1.json()["id"] != r2.json()["id"]


class TestListNotifications:
    def test_list_pending(self, client, home):
        _create_integration(home, "telegram")
        client.post(
            "/api/integrations/telegram/notify",
            json={"message": "Hello"},
        )
        client.post(
            "/api/integrations/telegram/notify",
            json={"message": "World", "chat_id": "99"},
        )
        resp = client.get("/api/integrations/telegram/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["message"] == "Hello"
        assert data[0]["chat_id"] is None
        assert data[1]["message"] == "World"
        assert data[1]["chat_id"] == "99"

    def test_list_empty(self, client, home):
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations/telegram/notifications")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_excludes_delivered(self, client, home):
        """Notifications marked as delivered are not returned."""
        _create_integration(home, "telegram")
        r = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "Delivered one"},
        )
        nid = r.json()["id"]
        # Manually mark as delivered
        from strawpot_gui.db import get_db
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE integration_notifications SET delivered_at = datetime('now') "
                "WHERE id = ?",
                (nid,),
            )
        resp = client.get("/api/integrations/telegram/notifications")
        assert resp.json() == []

    def test_list_not_found(self, client, home):
        resp = client.get("/api/integrations/nonexistent/notifications")
        assert resp.status_code == 404

    def test_list_ordered_by_id(self, client, home):
        _create_integration(home, "telegram")
        client.post("/api/integrations/telegram/notify", json={"message": "A"})
        client.post("/api/integrations/telegram/notify", json={"message": "B"})
        client.post("/api/integrations/telegram/notify", json={"message": "C"})
        data = client.get("/api/integrations/telegram/notifications").json()
        assert [n["message"] for n in data] == ["A", "B", "C"]
        assert data[0]["id"] < data[1]["id"] < data[2]["id"]


class TestAckNotification:
    def test_ack_marks_delivered(self, client, home):
        _create_integration(home, "telegram")
        r = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "To deliver"},
        )
        nid = r.json()["id"]
        resp = client.post(f"/api/integrations/telegram/notifications/{nid}/ack")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # Should no longer appear in pending list
        pending = client.get("/api/integrations/telegram/notifications").json()
        assert len(pending) == 0

    def test_ack_not_found(self, client, home):
        _create_integration(home, "telegram")
        resp = client.post("/api/integrations/telegram/notifications/999/ack")
        assert resp.status_code == 404

    def test_ack_wrong_integration(self, client, home):
        """ACK with mismatched integration name returns 404."""
        _create_integration(home, "telegram")
        _create_integration(home, "slack")
        r = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "For telegram"},
        )
        nid = r.json()["id"]
        resp = client.post(f"/api/integrations/slack/notifications/{nid}/ack")
        assert resp.status_code == 404

    def test_ack_idempotent(self, client, home):
        """ACKing an already-delivered notification succeeds."""
        _create_integration(home, "telegram")
        r = client.post(
            "/api/integrations/telegram/notify",
            json={"message": "Double ack"},
        )
        nid = r.json()["id"]
        client.post(f"/api/integrations/telegram/notifications/{nid}/ack")
        resp = client.post(f"/api/integrations/telegram/notifications/{nid}/ack")
        assert resp.status_code == 200


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


class TestBuildEnv:
    """Tests for _build_env environment variable construction."""

    def test_global_data_dir(self, client, home):
        """Global instance uses strawpot home for data dir."""
        from starlette.testclient import TestClient as _TC
        from strawpot_gui.routers.integrations import _build_env
        from strawpot_gui.db import get_db

        _create_integration(home, "telegram")
        db_path = client.app.state.db_path

        # Use a real request object via the test client
        with _TC(client.app) as tc:
            # Build a mock-ish request from the app
            from starlette.requests import Request
            from starlette.datastructures import URL

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [],
                "query_string": b"",
                "root_path": "",
                "server": ("testserver", 80),
            }
            request = Request(scope)

            with get_db(db_path) as conn:
                env = _build_env("telegram", {}, request, conn, project_id=0)

        assert env["STRAWPOT_INTEGRATION_NAME"] == "telegram"
        assert env["STRAWPOT_API_URL"].endswith("/via/telegram")
        assert env["STRAWPOT_DATA_DIR"] == str(home / "data" / "integrations" / "telegram")
        assert "STRAWPOT_PROJECT_ID" not in env
        assert "STRAWPOT_PROJECT_DIR" not in env

    def test_project_scoped_data_dir(self, client, home, tmp_path):
        """Project-scoped instance uses project working dir for data dir."""
        from strawpot_gui.routers.integrations import _build_env
        from strawpot_gui.db import get_db
        from starlette.requests import Request

        _create_integration(home, "discord")
        db_path = client.app.state.db_path
        project_dir = str(tmp_path / "my_project")

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
        }
        request = Request(scope)

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, display_name, working_dir) VALUES (?, ?, ?)",
                (5, "My Project", project_dir),
            )
            env = _build_env("discord", {}, request, conn, project_id=5)

        expected_data = str(tmp_path / "my_project" / ".strawpot" / "data" / "integrations" / "discord")
        assert env["STRAWPOT_DATA_DIR"] == expected_data
        assert env["STRAWPOT_PROJECT_DIR"] == project_dir
        assert env["STRAWPOT_PROJECT_ID"] == "5"
        assert env["STRAWPOT_API_URL"].endswith("/via/p/5/discord")

    def test_project_scoped_fallback_when_project_missing(self, client, home):
        """Project-scoped instance falls back to global data dir if project not found."""
        from strawpot_gui.routers.integrations import _build_env
        from strawpot_gui.db import get_db
        from starlette.requests import Request

        _create_integration(home, "slack")
        db_path = client.app.state.db_path

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
        }
        request = Request(scope)

        with get_db(db_path) as conn:
            # No project with id=99 exists
            env = _build_env("slack", {}, request, conn, project_id=99)

        assert env["STRAWPOT_DATA_DIR"] == str(home / "data" / "integrations" / "slack")
        assert "STRAWPOT_PROJECT_DIR" not in env

    def test_config_values_passed_through(self, client, home):
        """Config values are set as env vars."""
        from strawpot_gui.routers.integrations import _build_env
        from strawpot_gui.db import get_db
        from starlette.requests import Request

        _create_integration(home, "telegram")
        db_path = client.app.state.db_path

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
        }
        request = Request(scope)

        config = {"STRAWPOT_BOT_TOKEN": "123:ABC", "EMPTY_VAL": ""}
        with get_db(db_path) as conn:
            env = _build_env("telegram", config, request, conn)

        assert env["STRAWPOT_BOT_TOKEN"] == "123:ABC"
        # Empty values should not be set
        assert "EMPTY_VAL" not in env


class TestLocalFirstResolution:
    """Tests for project-local-first integration resolution."""

    def _create_project(self, client, project_id, working_dir):
        """Insert a project row directly."""
        from strawpot_gui.db import get_db
        db_path = client.app.state.db_path
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, display_name, working_dir) VALUES (?, ?, ?)",
                (project_id, "Test Project", str(working_dir)),
            )

    def _create_project_integration(self, working_dir, name):
        """Create an integration manifest in a project's .strawpot dir."""
        integration_dir = working_dir / ".strawpot" / "integrations" / name
        integration_dir.mkdir(parents=True)
        content = (
            f"---\nname: {name}\ndescription: Project-local {name}\n"
            f"metadata:\n  strawpot:\n    entry_point: python adapter.py\n"
            f"    env:\n"
            f"      STRAWPOT_BOT_TOKEN:\n"
            f"        required: true\n"
            f"        description: Bot token\n"
            f"---\n# {name.title()} Adapter\n"
        )
        (integration_dir / "INTEGRATION.md").write_text(content)
        return integration_dir

    def test_project_local_takes_precedence(self, client, home, tmp_path):
        """Project-local integration shadows global one with same name."""
        _create_integration(home, "telegram")  # global
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        self._create_project(client, 5, project_dir)
        self._create_project_integration(project_dir, "telegram")  # local

        resp = client.get("/api/integrations/telegram?project_id=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "project"
        assert "myproject" in data["path"]

    def test_falls_back_to_global(self, client, home, tmp_path):
        """Falls back to global when not installed locally."""
        _create_integration(home, "telegram")  # global only
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        self._create_project(client, 5, project_dir)

        resp = client.get("/api/integrations/telegram?project_id=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "global"

    def test_list_merges_local_and_global(self, client, home, tmp_path):
        """List shows project-local + unshadowed global integrations."""
        _create_integration(home, "telegram")
        _create_integration(home, "discord")
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        self._create_project(client, 5, project_dir)
        self._create_project_integration(project_dir, "telegram")  # shadows global

        resp = client.get("/api/integrations?project_id=5")
        assert resp.status_code == 200
        items = resp.json()
        names = {i["name"]: i["source"] for i in items}
        assert names["telegram"] == "project"
        assert names["discord"] == "global"

    def test_list_global_only(self, client, home):
        """Without project_id, only global integrations are returned."""
        _create_integration(home, "telegram")
        resp = client.get("/api/integrations")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["source"] == "global"

    def test_config_resolves_project_local(self, client, home, tmp_path):
        """Config endpoint uses project-local manifest for env schema."""
        _create_integration(home, "telegram")
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        self._create_project(client, 5, project_dir)
        self._create_project_integration(project_dir, "telegram")

        resp = client.get("/api/integrations/telegram/config?project_id=5")
        assert resp.status_code == 200
        assert "STRAWPOT_BOT_TOKEN" in resp.json()["env_schema"]
