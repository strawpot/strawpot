"""Tests for POST /api/sessions (session launch) endpoint."""

from unittest.mock import patch

from test_sessions_sync import _register_project

from strawpot_gui.db import get_db


class TestLaunchSession:
    def _launch(self, client, pid, **json_overrides):
        """POST /api/sessions with mocked subprocess and shutil.which."""
        body = {"project_id": pid, "task": "Fix the tests"}
        body.update(json_overrides)
        with patch("strawpot_gui.routers.sessions.shutil.which", return_value="/usr/bin/strawpot"), \
             patch("strawpot_gui.routers.sessions.subprocess.Popen") as mock_popen, \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()
            resp = client.post("/api/sessions", json=body)
        return resp, mock_popen

    def test_launch_returns_201(self, client, tmp_path):
        """Successful launch returns 201 with run_id and status."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp, mock_popen = self._launch(client, pid)

        assert resp.status_code == 201
        data = resp.json()
        assert data["run_id"].startswith("run_")
        assert data["status"] == "starting"
        mock_popen.assert_called_once()

    def test_launch_passes_run_id_to_cli(self, client, tmp_path):
        """The subprocess command includes --run-id with the pre-generated ID."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp, mock_popen = self._launch(client, pid)

        run_id = resp.json()["run_id"]
        cmd = mock_popen.call_args[0][0]
        assert "--run-id" in cmd
        assert run_id in cmd
        assert "--headless" in cmd
        assert "--task" in cmd

    def test_launch_with_overrides(self, client, tmp_path):
        """Overrides are passed as CLI flags."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp, mock_popen = self._launch(
            client, pid,
            role="deployer",
            overrides={"runtime": "gemini"},
        )

        assert resp.status_code == 201
        cmd = mock_popen.call_args[0][0]
        assert "--role" in cmd
        assert "deployer" in cmd
        assert "--runtime" in cmd
        assert "gemini" in cmd

    def test_launch_inserts_db_row(self, client, tmp_path):
        """A DB row with status 'starting' is inserted."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp, _ = self._launch(client, pid, task="Build feature")

        run_id = resp.json()["run_id"]
        with get_db(client.app.state.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row is not None
        assert row["status"] == "starting"
        assert row["task"] == "Build feature"
        assert row["project_id"] == pid

    def test_launch_nonexistent_project_returns_404(self, client):
        """Unknown project_id returns 404."""
        resp = client.post("/api/sessions", json={
            "project_id": 9999,
            "task": "anything",
        })
        assert resp.status_code == 404

    def test_launch_missing_dir_returns_422(self, client, tmp_path):
        """Project whose working_dir no longer exists returns 422."""
        resp = client.post("/api/projects", json={
            "display_name": "Ghost",
            "working_dir": str(tmp_path / "vanished"),
        })
        pid = resp.json()["id"]

        with patch("strawpot_gui.routers.sessions.load_config"):
            resp = client.post("/api/sessions", json={
                "project_id": pid,
                "task": "doomed",
            })
        assert resp.status_code == 422

    def test_launch_empty_task_returns_422(self, client, tmp_path):
        """Empty or whitespace-only task is rejected."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp = client.post("/api/sessions", json={
            "project_id": pid,
            "task": "   ",
        })
        assert resp.status_code == 422

    def test_launch_strawpot_not_on_path_returns_500(self, client, tmp_path):
        """If strawpot binary is not on PATH, returns 500."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        with patch("strawpot_gui.routers.sessions.shutil.which", return_value=None), \
             patch("strawpot_gui.routers.sessions.load_config") as mock_config:
            from strawpot.config import StrawPotConfig
            mock_config.return_value = StrawPotConfig()

            resp = client.post("/api/sessions", json={
                "project_id": pid,
                "task": "anything",
            })
        assert resp.status_code == 500
