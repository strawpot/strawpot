"""Tests for session list and detail endpoints."""

import shutil
from pathlib import Path

from strawpot_gui.db import sync_sessions

from test_sessions_sync import _register_project, _write_session, _write_trace


class TestListSessions:
    def test_empty_list(self, client, tmp_path):
        """Project with no sessions returns empty list."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp = client.get(f"/api/projects/{pid}/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_lists_sessions(self, client, tmp_path):
        """Returns sessions with correct fields."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_abc", archived=True)
        _write_trace(session_dir, [
            {
                "ts": "2026-01-01T12:05:00+00:00",
                "event": "delegate_end",
                "trace_id": "run_abc",
                "span_id": "s1",
                "parent_span": None,
                "data": {"exit_code": 0, "summary": "Done", "duration_ms": 300000},
            },
            {
                "ts": "2026-01-01T12:05:01+00:00",
                "event": "session_end",
                "trace_id": "run_abc",
                "span_id": "s0",
                "data": {"duration_ms": 300100},
            },
        ])
        sync_sessions(client.app.state.db_path)

        resp = client.get(f"/api/projects/{pid}/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        sessions = body["items"]
        assert len(sessions) == 1

        s = sessions[0]
        assert s["run_id"] == "run_abc"
        assert s["project_id"] == pid
        assert s["status"] == "completed"
        assert s["exit_code"] == 0
        assert s["summary"] == "Done"
        assert s["duration_ms"] == 300100
        # session_dir should not be exposed
        assert "session_dir" not in s

    def test_nonexistent_project_returns_404(self, client):
        """Requesting sessions for unknown project returns 404."""
        resp = client.get("/api/projects/9999/sessions")
        assert resp.status_code == 404

    def test_ordered_by_most_recent(self, client, tmp_path):
        """Sessions are ordered by started_at descending."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        _write_session(
            project_dir, "run_old", archived=True,
            started_at="2026-01-01T10:00:00+00:00",
        )
        _write_session(
            project_dir, "run_new", archived=True,
            started_at="2026-01-01T14:00:00+00:00",
        )
        sync_sessions(client.app.state.db_path)

        resp = client.get(f"/api/projects/{pid}/sessions")
        body = resp.json()
        sessions = body["items"]
        assert len(sessions) == 2
        assert sessions[0]["run_id"] == "run_new"
        assert sessions[1]["run_id"] == "run_old"

    def test_scoped_to_project(self, client, tmp_path):
        """Sessions from other projects are not included."""
        p1 = tmp_path / "proj1"
        p1.mkdir()
        p2 = tmp_path / "proj2"
        p2.mkdir()
        pid1 = _register_project(client, p1)
        _register_project(client, p2)

        _write_session(p1, "run_p1", archived=True)
        _write_session(p2, "run_p2", archived=True)
        sync_sessions(client.app.state.db_path)

        resp = client.get(f"/api/projects/{pid1}/sessions")
        body = resp.json()
        sessions = body["items"]
        assert len(sessions) == 1
        assert sessions[0]["run_id"] == "run_p1"


class TestGetSession:
    def _setup_session(self, client, tmp_path):
        """Create a project with one archived session and return (pid, session_dir)."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        session_dir = _write_session(project_dir, "run_detail", archived=True)
        _write_trace(session_dir, [
            {
                "ts": "2026-01-01T12:05:00+00:00",
                "event": "delegate_end",
                "trace_id": "run_detail",
                "span_id": "s1",
                "parent_span": None,
                "data": {"exit_code": 0, "summary": "All done", "duration_ms": 60000},
            },
            {
                "ts": "2026-01-01T12:05:01+00:00",
                "event": "session_end",
                "trace_id": "run_detail",
                "span_id": "s0",
                "data": {"duration_ms": 60100},
            },
        ])
        sync_sessions(client.app.state.db_path)
        return pid, session_dir

    def test_get_session_basic(self, client, tmp_path):
        """Detail endpoint returns metadata without session_dir."""
        pid, _ = self._setup_session(client, tmp_path)

        resp = client.get(f"/api/projects/{pid}/sessions/run_detail")
        assert resp.status_code == 200
        s = resp.json()
        assert s["run_id"] == "run_detail"
        assert s["project_id"] == pid
        assert s["status"] == "completed"
        assert s["exit_code"] == 0
        assert s["summary"] == "All done"
        assert "session_dir" not in s

    def test_get_session_agents(self, client, tmp_path):
        """Detail endpoint returns agents from session.json."""
        pid, _ = self._setup_session(client, tmp_path)

        resp = client.get(f"/api/projects/{pid}/sessions/run_detail")
        agents = resp.json()["agents"]
        assert "agent_abc" in agents
        assert agents["agent_abc"]["role"] == "orchestrator"

    def test_get_session_events(self, client, tmp_path):
        """Detail endpoint returns trace events."""
        pid, _ = self._setup_session(client, tmp_path)

        resp = client.get(f"/api/projects/{pid}/sessions/run_detail")
        events = resp.json()["events"]
        assert len(events) == 2
        assert events[0]["event"] == "delegate_end"
        assert events[1]["event"] == "session_end"

    def test_get_session_not_found(self, client, tmp_path):
        """Nonexistent run_id returns 404."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        pid = _register_project(client, project_dir)

        resp = client.get(f"/api/projects/{pid}/sessions/run_nope")
        assert resp.status_code == 404

    def test_get_session_wrong_project(self, client, tmp_path):
        """Session from another project returns 404."""
        p1 = tmp_path / "proj1"
        p1.mkdir()
        p2 = tmp_path / "proj2"
        p2.mkdir()
        pid1 = _register_project(client, p1)
        pid2 = _register_project(client, p2)

        _write_session(p1, "run_p1", archived=True)
        sync_sessions(client.app.state.db_path)

        resp = client.get(f"/api/projects/{pid2}/sessions/run_p1")
        assert resp.status_code == 404

    def test_get_session_missing_files(self, client, tmp_path):
        """Returns empty agents/events when session dir is deleted."""
        pid, session_dir = self._setup_session(client, tmp_path)

        # Delete the session directory after sync
        shutil.rmtree(session_dir)

        resp = client.get(f"/api/projects/{pid}/sessions/run_detail")
        assert resp.status_code == 200
        s = resp.json()
        assert s["run_id"] == "run_detail"
        assert s["agents"] == {}
        assert s["events"] == []


class TestGetArtifact:
    def _setup(self, client, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _register_project(client, project_dir)
        session_dir = _write_session(project_dir, "run_art", archived=True)
        sync_sessions(client.app.state.db_path)
        return session_dir

    def test_get_artifact(self, client, tmp_path):
        """Artifact endpoint serves stored content."""
        session_dir = Path(self._setup(client, tmp_path))
        artifacts_dir = session_dir / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "abcdef012345").write_text("artifact content")

        resp = client.get("/api/sessions/run_art/artifacts/abcdef012345")
        assert resp.status_code == 200
        assert resp.text == "artifact content"

    def test_artifact_not_found(self, client, tmp_path):
        """Missing artifact returns 404."""
        self._setup(client, tmp_path)
        resp = client.get("/api/sessions/run_art/artifacts/000000000000")
        assert resp.status_code == 404

    def test_artifact_invalid_hash(self, client, tmp_path):
        """Invalid hash format returns 400."""
        self._setup(client, tmp_path)
        resp = client.get("/api/sessions/run_art/artifacts/bad")
        assert resp.status_code == 400

    def test_artifact_session_not_found(self, client, tmp_path):
        """Unknown session returns 404."""
        resp = client.get("/api/sessions/run_nope/artifacts/abcdef012345")
        assert resp.status_code == 404
