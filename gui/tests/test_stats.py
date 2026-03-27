"""Tests for project activity stats endpoint."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from strawpot_gui.db import get_db, sync_sessions

from test_sessions_sync import _register_project, _write_session, _write_trace


def _setup_project_with_sessions(client, tmp_path, sessions_data):
    """Register a project and create sessions, then sync.

    sessions_data: list of dicts with keys:
        run_id, status (completed|failed|stopped), duration_ms, started_at
    """
    pid = _register_project(client, tmp_path)

    for s in sessions_data:
        run_id = s["run_id"]
        status = s.get("status", "completed")
        is_archived = status in ("completed", "failed", "stopped")
        session_dir = _write_session(
            tmp_path,
            run_id,
            archived=is_archived,
            started_at=s.get("started_at", "2026-01-15T12:00:00+00:00"),
        )
        # Build trace events matching _parse_trace expectations
        events = []
        if status in ("completed", "failed", "stopped"):
            end_data = {}
            if s.get("duration_ms") is not None:
                end_data["duration_ms"] = s["duration_ms"]
            exit_code = 0 if status == "completed" else 1
            end_data["exit_code"] = exit_code
            events.append({
                "event": "session_end",
                "ts": s.get("started_at", "2026-01-15T12:00:00+00:00"),
                "data": end_data,
            })
        _write_trace(session_dir, events)

    sync_sessions(client.app.state.db_path)
    return pid


class TestStatsEndpoint:
    def test_project_not_found(self, client):
        resp = client.get("/api/projects/999/stats")
        assert resp.status_code == 404

    def test_invalid_period(self, client, tmp_path):
        pid = _register_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "5d"})
        assert resp.status_code == 422

    def test_empty_project(self, client, tmp_path):
        pid = _register_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "30d"
        assert data["total_runs"] == 0
        assert data["completed"] == 0
        assert data["failed"] == 0
        assert data["stopped"] == 0
        assert data["success_rate"] == 0.0
        assert data["avg_duration_ms"] is None
        # Daily array should be gap-filled
        assert len(data["daily"]) == 31  # 30 days + today

    def test_default_period_is_30d(self, client, tmp_path):
        pid = _register_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/stats")
        assert resp.json()["period"] == "30d"

    def test_period_7d(self, client, tmp_path):
        pid = _register_project(client, tmp_path)
        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()
        assert data["period"] == "7d"
        assert len(data["daily"]) == 8  # 7 days + today

    def test_aggregation(self, client, tmp_path):
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        today = now.replace(hour=10, minute=0, second=0, microsecond=0)

        sessions = [
            {"run_id": "run_s1", "status": "completed", "duration_ms": 100000, "started_at": yesterday.isoformat()},
            {"run_id": "run_s2", "status": "completed", "duration_ms": 200000, "started_at": yesterday.isoformat()},
            {"run_id": "run_s3", "status": "failed", "duration_ms": 50000, "started_at": today.isoformat()},
        ]
        pid = _setup_project_with_sessions(client, tmp_path, sessions)

        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()

        assert data["total_runs"] == 3
        assert data["completed"] == 2
        assert data["failed"] == 1
        assert data["success_rate"] == 66.7
        assert data["avg_duration_ms"] is not None

    def test_gap_filling(self, client, tmp_path):
        now = datetime.now(timezone.utc)
        three_days_ago = (now - timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)

        sessions = [
            {"run_id": "run_s1", "status": "completed", "duration_ms": 60000, "started_at": three_days_ago.isoformat()},
        ]
        pid = _setup_project_with_sessions(client, tmp_path, sessions)

        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()

        dates = [d["date"] for d in data["daily"]]
        three_days_ago_date = three_days_ago.date().isoformat()
        assert three_days_ago_date in dates

        # Days without sessions should have zeroes
        for d in data["daily"]:
            if d["date"] != three_days_ago_date:
                assert d["total"] == 0
                assert d["completed"] == 0
                assert d["failed"] == 0
                assert d["avg_duration_ms"] is None

    def test_excludes_running_sessions(self, client, tmp_path):
        now = datetime.now(timezone.utc)
        today = now.replace(hour=10, minute=0, second=0, microsecond=0)

        # Create a completed session
        pid = _register_project(client, tmp_path)
        session_dir = _write_session(
            tmp_path, "run_s1", archived=True,
            started_at=today.isoformat(),
        )
        _write_trace(session_dir, [
            {"event": "session_end", "ts": today.isoformat(), "data": {"duration_ms": 60000, "exit_code": 0}},
        ])

        # Create a running session (not archived, no trace)
        _write_session(
            tmp_path, "run_s2", archived=False,
            started_at=today.isoformat(),
        )

        sync_sessions(client.app.state.db_path)

        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()

        assert data["total_runs"] == 1
        assert data["completed"] == 1

    def test_null_duration_excluded_from_avg(self, client, tmp_path):
        now = datetime.now(timezone.utc)
        today = now.replace(hour=10, minute=0, second=0, microsecond=0)

        sessions = [
            {"run_id": "run_s1", "status": "completed", "duration_ms": 120000, "started_at": today.isoformat()},
            {"run_id": "run_s2", "status": "completed", "duration_ms": None, "started_at": today.isoformat()},
        ]
        pid = _setup_project_with_sessions(client, tmp_path, sessions)

        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()

        assert data["avg_duration_ms"] == 120000

    def test_stopped_sessions_in_aggregation(self, client, tmp_path, app):
        """Stopped sessions count toward total_runs and the stopped field,
        but do not affect success_rate (which only considers completed vs failed).

        Uses direct DB insertion because sync_sessions infers status from
        exit_code (non-zero → failed), which would lose the 'stopped' state.
        """
        now = datetime.now(timezone.utc)
        today = now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()

        pid = _register_project(client, tmp_path)

        with get_db(app.state.db_path) as conn:
            for status, duration_ms in [("completed", 100000), ("failed", 50000), ("stopped", 30000)]:
                run_id = f"run_{uuid.uuid4().hex[:8]}"
                exit_code = 0 if status == "completed" else 1
                conn.execute(
                    "INSERT INTO sessions "
                    "(run_id, project_id, role, runtime, status, task, "
                    "exit_code, started_at, duration_ms, session_dir) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, pid, "default", "claude-code", status,
                     "test task", exit_code, today, duration_ms, str(tmp_path)),
                )

        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()

        assert data["total_runs"] == 3
        assert data["completed"] == 1
        assert data["failed"] == 1
        assert data["stopped"] == 1
        # success_rate = completed / (completed + failed) = 1/2 = 50%
        # stopped sessions are excluded from rate calculation
        assert data["success_rate"] == 50.0

        # Daily breakdown also includes stopped count
        today_entry = next(d for d in data["daily"] if d["total"] > 0)
        assert today_entry["stopped"] == 1

    def test_period_filters_old_sessions(self, client, tmp_path):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
        old = (now - timedelta(days=20)).replace(hour=10, minute=0, second=0, microsecond=0)

        sessions = [
            {"run_id": "run_recent", "status": "completed", "duration_ms": 60000, "started_at": recent.isoformat()},
            {"run_id": "run_old", "status": "completed", "duration_ms": 60000, "started_at": old.isoformat()},
        ]
        pid = _setup_project_with_sessions(client, tmp_path, sessions)

        resp = client.get(f"/api/projects/{pid}/stats", params={"period": "7d"})
        data = resp.json()

        assert data["total_runs"] == 1
