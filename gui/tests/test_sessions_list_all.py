"""Tests for GET /api/sessions (global session list with pagination/filters)."""

import os

from strawpot_gui.db import sync_sessions

from test_sessions_sync import _register_project, _write_session, _write_trace


def _setup_sessions(client, tmp_path):
    """Create two projects with sessions and return their IDs."""
    p1 = tmp_path / "proj1"
    p1.mkdir()
    p2 = tmp_path / "proj2"
    p2.mkdir()
    pid1 = _register_project(client, p1)
    pid2 = _register_project(client, p2)

    # Project 1: two archived sessions
    sd1 = _write_session(
        p1, "run_a", archived=True,
        started_at="2026-01-01T10:00:00+00:00",
    )
    _write_trace(sd1, [
        {
            "ts": "2026-01-01T10:05:01+00:00",
            "event": "session_end",
            "trace_id": "run_a", "span_id": "s0",
            "data": {"duration_ms": 300100, "exit_code": 0, "summary": "Done A"},
        },
    ])

    sd2 = _write_session(
        p1, "run_b", archived=True,
        started_at="2026-01-02T10:00:00+00:00",
    )
    _write_trace(sd2, [
        {
            "ts": "2026-01-02T10:01:00+00:00",
            "event": "session_end",
            "trace_id": "run_b", "span_id": "s0",
            "data": {"duration_ms": 60000, "exit_code": 1, "summary": "Failed B"},
        },
    ])

    # Project 2: one archived session
    _write_session(
        p2, "run_c", archived=True,
        started_at="2026-01-03T10:00:00+00:00",
    )

    sync_sessions(client.app.state.db_path)
    return pid1, pid2


class TestListAllSessions:
    def test_returns_all_sessions(self, client, tmp_path):
        """Without filters, returns all sessions."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        assert data["page"] == 1
        assert data["per_page"] == 20

    def test_ordered_by_most_recent(self, client, tmp_path):
        """Sessions are ordered by started_at descending."""
        _setup_sessions(client, tmp_path)

        items = client.get("/api/sessions").json()["items"]
        assert items[0]["run_id"] == "run_c"
        assert items[1]["run_id"] == "run_b"
        assert items[2]["run_id"] == "run_a"

    def test_filter_by_project_id(self, client, tmp_path):
        """Filter sessions by project_id."""
        pid1, pid2 = _setup_sessions(client, tmp_path)

        resp = client.get(f"/api/sessions?project_id={pid1}")
        data = resp.json()
        assert data["total"] == 2
        assert all(s["project_id"] == pid1 for s in data["items"])

        resp = client.get(f"/api/sessions?project_id={pid2}")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["run_id"] == "run_c"

    def test_filter_by_status(self, client, tmp_path):
        """Filter sessions by status."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions?status=completed")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["run_id"] == "run_a"

        resp = client.get("/api/sessions?status=failed")
        data = resp.json()
        assert data["total"] == 2  # run_b (exit_code 1) + run_c (no trace)

    def test_filter_by_since(self, client, tmp_path):
        """Filter sessions started on or after a date."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions?since=2026-01-02T00:00:00+00:00")
        data = resp.json()
        assert data["total"] == 2
        run_ids = {s["run_id"] for s in data["items"]}
        assert run_ids == {"run_b", "run_c"}

    def test_filter_by_until(self, client, tmp_path):
        """Filter sessions started on or before a date."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions?until=2026-01-01T23:59:59+00:00")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["run_id"] == "run_a"

    def test_filter_combined(self, client, tmp_path):
        """Multiple filters are ANDed together."""
        pid1, _ = _setup_sessions(client, tmp_path)

        resp = client.get(
            f"/api/sessions?project_id={pid1}&status=completed"
        )
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["run_id"] == "run_a"

    def test_pagination_page_size(self, client, tmp_path):
        """per_page limits results per page."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions?per_page=2")
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["page"] == 1

    def test_pagination_page_2(self, client, tmp_path):
        """Second page returns remaining items."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions?per_page=2&page=2")
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 1
        assert data["page"] == 2

    def test_pagination_beyond_last_page(self, client, tmp_path):
        """Page beyond total returns empty items."""
        _setup_sessions(client, tmp_path)

        resp = client.get("/api/sessions?page=99")
        data = resp.json()
        assert data["total"] == 3
        assert data["items"] == []
        assert data["page"] == 99

    def test_no_sessions(self, client):
        """Empty database returns zero total."""
        resp = client.get("/api/sessions")
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_session_dir_not_exposed(self, client, tmp_path):
        """session_dir field is not included in response items."""
        _setup_sessions(client, tmp_path)

        items = client.get("/api/sessions").json()["items"]
        for item in items:
            assert "session_dir" not in item
