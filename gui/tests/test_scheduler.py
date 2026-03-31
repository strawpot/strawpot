"""Tests for the cron scheduler engine."""

import os
import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from croniter import croniter

from strawpot_gui.db import get_db, init_db
from strawpot_gui.scheduler import Scheduler, fire_schedule, _next_run


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
        "schedule_type": "recurring",
        "run_at": None,
        "enabled": 1,
        "skip_if_running": 1,
        "next_run_at": None,
        "conversation_id": None,
    }
    defaults.update(kwargs)
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO scheduled_tasks
               (name, project_id, task, cron_expr, schedule_type, run_at,
                enabled, skip_if_running, next_run_at, conversation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                defaults["name"],
                defaults["project_id"],
                defaults["task"],
                defaults["cron_expr"],
                defaults["schedule_type"],
                defaults["run_at"],
                defaults["enabled"],
                defaults["skip_if_running"],
                defaults["next_run_at"],
                defaults["conversation_id"],
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
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-active", project_id, sid, "running",
                 "test", "test", "2025-01-01T00:00:00", "/tmp"),
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
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-active", project_id, sid, "running",
                 "test", "test", "2025-01-01T00:00:00", "/tmp"),
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


# ---------------------------------------------------------------------------
# One-time schedule scheduler tests
# ---------------------------------------------------------------------------


class TestOneTimeScheduleFire:
    def test_auto_disables_after_fire(self, db_path, project_id):
        past = "2000-01-01T00:00:00+00:00"
        sid = _insert_schedule(
            db_path, project_id,
            name="one-time-task",
            cron_expr=None,
            schedule_type="one_time",
            run_at=past,
            next_run_at=past,
        )

        launch_fn = MagicMock(return_value="run-ot-1")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT enabled, next_run_at, last_run_at "
                "FROM scheduled_tasks WHERE id = ?",
                (sid,),
            ).fetchone()
        assert row["enabled"] == 0
        assert row["next_run_at"] is None
        assert row["last_run_at"] is not None

    def test_init_skips_one_time(self, db_path, project_id):
        """_init_next_run_times should not touch one-time schedules."""
        sid = _insert_schedule(
            db_path, project_id,
            name="one-time-init",
            cron_expr=None,
            schedule_type="one_time",
            run_at="2099-01-01T00:00:00+00:00",
            next_run_at=None,
            enabled=1,
        )
        scheduler = Scheduler(db_path, MagicMock())
        scheduler._init_next_run_times()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT next_run_at FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone()
        # Should remain None — _init_next_run_times only handles recurring
        assert row["next_run_at"] is None

    def test_skip_if_running_retains_next_run(self, db_path, project_id):
        """When a one-time schedule is skipped due to running session,
        next_run_at should NOT be advanced (stays unchanged for retry)."""
        past = "2000-01-01T00:00:00+00:00"
        sid = _insert_schedule(
            db_path, project_id,
            name="ot-skip",
            cron_expr=None,
            schedule_type="one_time",
            run_at=past,
            next_run_at=past,
            skip_if_running=1,
        )

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, schedule_id, status, role, runtime, "
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-block", project_id, sid, "running",
                 "test", "test", "2025-01-01T00:00:00", "/tmp"),
            )

        launch_fn = MagicMock()
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert not launch_fn.called

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT next_run_at FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone()
        # next_run_at should be unchanged (not cleared or advanced)
        assert row["next_run_at"] == past


# ---------------------------------------------------------------------------
# #20 — imu role enforcement for project_id == 0
# ---------------------------------------------------------------------------


class TestImuRoleEnforcement:
    """Tests for orchestrator role fallback on project_id == 0.

    All tests mock load_config to isolate from the user's real config file.
    """

    @pytest.fixture(autouse=True)
    def _mock_config(self):
        mock_cfg = MagicMock()
        mock_cfg.orchestrator_role = "imu"
        with patch("strawpot_gui.config_helpers.load_config", return_value=mock_cfg):
            yield mock_cfg

    def test_default_orchestrator_role_for_project_zero(self, db_path):
        """Schedules with project_id=0 and no explicit role get the default orchestrator role."""
        # Insert project 0 (strawpot-internal)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, display_name, working_dir) "
                "VALUES (0, 'strawpot', '/tmp/strawpot')"
            )
        _insert_schedule(db_path, 0, next_run_at="2000-01-01T00:00:00+00:00")

        launch_fn = MagicMock(return_value="run-imu")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        assert launch_fn.call_args[1]["role"] == "imu"

    def test_explicit_role_preserved_for_project_zero(self, db_path):
        """An explicit role on a project-0 schedule is kept (not overridden)."""
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, display_name, working_dir) "
                "VALUES (0, 'strawpot', '/tmp/strawpot')"
            )
        # Manually set role via direct SQL since _insert_schedule doesn't set role
        sid = _insert_schedule(db_path, 0, next_run_at="2000-01-01T00:00:00+00:00")
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET role = 'custom' WHERE id = ?", (sid,)
            )

        launch_fn = MagicMock(return_value="run-custom")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        assert launch_fn.call_args[1]["role"] == "custom"

    def test_no_imu_for_regular_project(self, db_path, project_id):
        """Non-zero project_id without explicit role keeps role=None."""
        past = "2000-01-01T00:00:00+00:00"
        _insert_schedule(db_path, project_id, next_run_at=past)

        launch_fn = MagicMock(return_value="run-123")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        assert launch_fn.call_args[1]["role"] is None


# ---------------------------------------------------------------------------
# #19 — conversation targeting
# ---------------------------------------------------------------------------


class TestConversationTargeting:
    def _setup_conversation(self, db_path, project_id):
        """Create a conversation and return its id."""
        with get_db(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (project_id) VALUES (?)",
                (project_id,),
            )
            return cursor.lastrowid

    def test_passes_conversation_id_to_launch(self, db_path, project_id):
        """When conversation_id is set, it's forwarded to launch_fn."""
        conv_id = self._setup_conversation(db_path, project_id)
        past = "2000-01-01T00:00:00+00:00"
        _insert_schedule(
            db_path, project_id,
            next_run_at=past,
            conversation_id=conv_id,
        )

        launch_fn = MagicMock(return_value="run-conv")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        assert launch_fn.call_args[1]["conversation_id"] == conv_id

    def test_no_conversation_id_by_default(self, db_path, project_id):
        """Without conversation_id, launch_fn is called without it."""
        past = "2000-01-01T00:00:00+00:00"
        _insert_schedule(db_path, project_id, next_run_at=past)

        launch_fn = MagicMock(return_value="run-plain")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        assert "conversation_id" not in launch_fn.call_args[1]

    def test_conversation_context_prepended(self, db_path, project_id):
        """When conversation has prior sessions, context is prepended to task."""
        conv_id = self._setup_conversation(db_path, project_id)
        past = "2000-01-01T00:00:00+00:00"

        # Add a completed session to the conversation
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, conversation_id, status, role, runtime, "
                " started_at, session_dir, task, summary, exit_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-prior", project_id, conv_id, "completed",
                 "test", "test", "2025-01-01T00:00:00", "/tmp",
                 "earlier task", "did stuff", 0),
            )

        _insert_schedule(
            db_path, project_id,
            next_run_at=past,
            conversation_id=conv_id,
        )

        launch_fn = MagicMock(return_value="run-ctx")
        scheduler = Scheduler(db_path, launch_fn)
        scheduler._check_and_fire()

        assert launch_fn.called
        # Task should have context prepended
        task_arg = launch_fn.call_args[0][2]
        assert "Prior Conversation" in task_arg
        assert "run tests" in task_arg
        # user_task should be the original task
        assert launch_fn.call_args[1]["user_task"] == "run tests"


# ---------------------------------------------------------------------------
# fire_schedule() standalone function tests
# ---------------------------------------------------------------------------


class TestFireSchedule:
    def test_returns_run_id(self, db_path, project_id):
        """fire_schedule returns {"run_id": ...} on success."""
        sid = _insert_schedule(db_path, project_id)
        launch_fn = MagicMock(return_value="run-abc")
        with get_db(db_path) as conn:
            schedule = dict(conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone())
            result = fire_schedule(conn, schedule, launch_fn)
        assert result == {"run_id": "run-abc"}
        assert launch_fn.called

    def test_returns_error_on_failure(self, db_path, project_id):
        """fire_schedule returns {"error": ...} on launch failure."""
        sid = _insert_schedule(db_path, project_id)
        launch_fn = MagicMock(side_effect=RuntimeError("boom"))
        with get_db(db_path) as conn:
            schedule = dict(conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone())
            result = fire_schedule(conn, schedule, launch_fn)
        assert "boom" in result["error"]

    def test_task_override(self, db_path, project_id):
        """fire_schedule uses task_override when provided."""
        sid = _insert_schedule(db_path, project_id, task="original task")
        launch_fn = MagicMock(return_value="run-ovr")
        with get_db(db_path) as conn:
            schedule = dict(conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone())
            fire_schedule(conn, schedule, launch_fn, task_override="override task")
        assert launch_fn.call_args[0][2] == "override task"

    def test_queues_when_conversation_busy(self, db_path, project_id):
        """fire_schedule queues task when conversation has active session."""
        with get_db(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (project_id) VALUES (?)",
                (project_id,),
            )
            conv_id = cursor.lastrowid

        sid = _insert_schedule(
            db_path, project_id, conversation_id=conv_id,
        )

        # Insert active session on the conversation
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, conversation_id, status, role, runtime, "
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("run-busy", project_id, conv_id, "running",
                 "test", "test", "2025-01-01T00:00:00", "/tmp"),
            )

        launch_fn = MagicMock()
        with get_db(db_path) as conn:
            schedule = dict(conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)
            ).fetchone())
            result = fire_schedule(conn, schedule, launch_fn)
        assert result == {"queued": True}
        assert not launch_fn.called


# ---------------------------------------------------------------------------
# _refresh_active_sessions background sweep tests
# ---------------------------------------------------------------------------


class TestRefreshActiveSessions:
    def test_marks_stale_starting_session_failed(self, db_path, project_id, tmp_path):
        """A starting session with no session.json older than 15s gets marked failed."""
        session_dir = str(tmp_path / "sessions" / "run-stale")
        os.makedirs(session_dir)  # dir exists but no session.json

        stale_time = "2000-01-01T00:00:00+00:00"
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, status, role, runtime, "
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("run-stale", project_id, "starting",
                 "test", "test", stale_time, session_dir),
            )

        scheduler = Scheduler(db_path, MagicMock())
        scheduler._refresh_active_sessions()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM sessions WHERE run_id = 'run-stale'"
            ).fetchone()
        assert row["status"] == "failed"

    def test_leaves_recent_starting_session(self, db_path, project_id, tmp_path):
        """A recently started session without session.json stays starting."""
        session_dir = str(tmp_path / "sessions" / "run-recent")
        os.makedirs(session_dir)

        from datetime import datetime as dt, timezone as tz
        recent_time = dt.now(tz.utc).isoformat()
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, status, role, runtime, "
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("run-recent", project_id, "starting",
                 "test", "test", recent_time, session_dir),
            )

        scheduler = Scheduler(db_path, MagicMock())
        scheduler._refresh_active_sessions()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM sessions WHERE run_id = 'run-recent'"
            ).fetchone()
        assert row["status"] == "starting"

    def test_marks_missing_dir_session_failed(self, db_path, project_id):
        """A starting session with no session dir older than 15s gets marked failed."""
        stale_time = "2000-01-01T00:00:00+00:00"
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO sessions "
                "(run_id, project_id, status, role, runtime, "
                " started_at, session_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("run-nodir", project_id, "starting",
                 "test", "test", stale_time, "/nonexistent/path"),
            )

        scheduler = Scheduler(db_path, MagicMock())
        scheduler._refresh_active_sessions()

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM sessions WHERE run_id = 'run-nodir'"
            ).fetchone()
        assert row["status"] == "failed"
