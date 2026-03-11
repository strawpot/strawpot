"""Tests for the cron scheduler engine."""

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from croniter import croniter

from strawpot_gui.db import get_db, init_db
from strawpot_gui.scheduler import Scheduler, _next_run


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database and return its path."""
    path = str(tmp_path / "scheduler_test.db")
    init_db(path)
    return path


@pytest.fixture
def project_id(db_path):
    """Insert a test project and return its id."""
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (display_name, working_dir) VALUES (?, ?)",
            ("test-proj", "/tmp/test"),
        )
        return cursor.lastrowid


def _insert_schedule(db_path, project_id, **kwargs):
    """Insert a scheduled task and return its id."""
    defaults = {
        "name": "test-schedule",
        "project_id": project_id,
        "task": "run tests",
        "cron_expr": "0 0 * * *",
        "enabled": 1,
        "skip_if_running": 1,
        "next_run_at": None,
    }
    defaults.update(kwargs)
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO scheduled_tasks
               (name, project_id, task, cron_expr, enabled,
                skip_if_running, next_run_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                defaults["name"],
                defaults["project_id"],
                defaults["task"],
                defaults["cron_expr"],
                defaults["enabled"],
                defaults["skip_if_running"],
                defaults["next_run_at"],
            ),
        )
        return cursor.lastrowid


class TestNextRun:
    def test_valid_cron(self):
        now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        result = _next_run("0 0 * * *", now)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        assert parsed > now

    def test_invalid_cron_returns_none(self):
        now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert _next_run("bad-cron", now) is None


class TestInitNextRunTimes:
    def test_computes_missing_next_run(self, db_path, project_id):
        sid = _insert_schedule(db_path, project_id, enabled=1, next_run_at=None)
        scheduler = Scheduler(db_path, MagicMock())
        scheduler._init_next_run_times()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT next_run_at FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone()
        assert row["next_run_at"] is not None

    def test_skips_disabled(self, db_path, project_id):
        sid = _insert_schedule(db_path, project_id, enabled=0, next_run_at=None)
        scheduler = Scheduler(db_path, MagicMock())
        scheduler._init_next_run_times()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT next_run_at FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone()
        assert row["next_run_at"] is None

    def test_skips_already_set(self, db_path, project_id):
        original = "2099-01-01T00:00:00+00:00"
        sid = _insert_schedule(
            db_path, project_id, enabled=1, next_run_at=original
        )
        scheduler = Scheduler(db_path, MagicMock())
        scheduler._init_next_run_times()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT next_run_at FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone()
        assert row["next_run_at"] == original


class TestCheckAndFire:
    def test_fires_due_schedule(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        _insert_schedule(db_path, project_id, next_run_at=past)

        launch_fn = MagicMock(return_value="run-123")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        call_kwargs = launch_fn.call_args
        assert call_kwargs[1]["role"] is None
        assert call_kwargs[0][2] == "run tests"  # task positional arg

    def test_skips_future_schedule(self, db_path, project_id):
        future = "2099-01-01T00:00:00+00:00"
        _insert_schedule(db_path, project_id, next_run_at=future)

        launch_fn = MagicMock()
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert not launch_fn.called

    def test_skips_disabled_schedule(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        _insert_schedule(db_path, project_id, enabled=0, next_run_at=past)

        launch_fn = MagicMock()
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert not launch_fn.called

    def test_skips_if_running_session(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        sid = _insert_schedule(
            db_path, project_id, next_run_at=past, skip_if_running=1
        )

        # Insert a running session for this schedule
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, schedule_id, status, role, runtime, "
                " isolation, started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-active", project_id, sid, "running",
                 "test", "test", "none", "2025-01-01T00:00:00", "/tmp"),
            )

        launch_fn = MagicMock()
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert not launch_fn.called

    def test_fires_when_skip_if_running_disabled(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        sid = _insert_schedule(
            db_path, project_id, next_run_at=past, skip_if_running=0
        )

        # Insert a running session — should still fire
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, schedule_id, status, role, runtime, "
                " isolation, started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-active", project_id, sid, "running",
                 "test", "test", "none", "2025-01-01T00:00:00", "/tmp"),
            )

        launch_fn = MagicMock(return_value="run-new")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called

    def test_updates_next_run_after_fire(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        sid = _insert_schedule(db_path, project_id, next_run_at=past)

        launch_fn = MagicMock(return_value="run-123")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT next_run_at, last_run_at FROM scheduled_tasks WHERE id = ?",
                (sid,),
            ).fetchone()
        assert row["next_run_at"] is not None
        assert row["last_run_at"] is not None
        # next_run should be in the future
        next_dt = datetime.fromisoformat(row["next_run_at"])
        assert next_dt > datetime.now(timezone.utc)

    def test_records_error_on_launch_failure(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        sid = _insert_schedule(db_path, project_id, next_run_at=past)

        launch_fn = MagicMock(side_effect=RuntimeError("launch failed"))
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT last_error FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone()
        assert "launch failed" in row["last_error"]
