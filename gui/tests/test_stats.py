"""Tests for project activity stats endpoint."""

import json
import os
from datetime import datetime, timedelta, timezone

from strawpot_gui.db import sync_sessions

from test_sessions_sync import _register_project, _write_session, _write_trace


def _setup_project_with_sessions(client, tmp_path, sessions_data):
    """Register a project and create sessions, then sync.

    sessions_data: list of dicts with keys:
        run_id, status (completed|failed), duration_ms, started_at
    """
    pid = _register_project(client, tmp_path)

    for s in sessions_data:
        run_id = s["run_id"]
        status = s.get("status", "completed")
        is_archived = status in ("completed", "failed")
        session_dir = _write_session(
            tmp_path,
            run_id,
            archived=is_archived,
            started_at=s.get("started_at", "2026-01-15T12:00:00+00:00"),
        )
        # Build trace events matching _parse_trace expectations
        events = []
        if status in ("completed", "failed"):
            end_data = {}
            if s.get("duration_ms") is not None:
                end_data["duration_ms"] = s["duration_ms"]
            events.append({
                "event": "session_end",
                "ts": s.get("started_at", "2026-01-15T12:00:00+00:00"),
                "data": end_data,
            })
            # delegate_end with exit_code determines completed vs failed
            exit_code = 0 if status == "completed" else 1
            events.append({
                "event": "delegate_end",
                "ts": s.get("started_at", "2026-01-15T12:00:00+00:00"),
                "data": {"exit_code": exit_code},
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
            {"event": "session_end", "ts": today.isoformat(), "data": {"duration_ms": 60000}},
            {"event": "delegate_end", "ts": today.isoformat(), "data": {"exit_code": 0}},
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
