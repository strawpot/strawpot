"""Shared fixtures for GUI tests."""

import os
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from strawpot_gui.app import create_app
from strawpot_gui.db import get_db
from strawpot_gui.routers.conversations import _recent_submissions, _submissions_lock

# Tables deleted in an order that avoids FK constraint violations.
_TABLES = [
    "conversation_task_queue",
    "integration_notifications",
    "integration_config",
    "sessions",
    "scheduled_tasks",
    "integrations",
    "conversations",
    "projects",
]


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """Create a test app with a temp database (one per test module)."""
    db_path = str(tmp_path_factory.mktemp("gui") / "test_gui.db")
    return create_app(db_path=db_path)


@pytest.fixture(scope="module")
def client(app):
    """Module-scoped TestClient — enters ASGI lifespan once per test file."""
    with patch("strawpot_gui.app._ensure_imu_role"), TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_db(request):
    """Reset all database tables between tests for isolation.

    Only runs when the test's module has an initialised app with a real
    database (i.e. the ``client`` fixture was used).  Re-inserts a stub
    IMU project (id=0) after cleanup so subsequent tests can reference it.
    """
    # Clear the in-memory duplicate-submission cache so stale entries from
    # a previous test (which may have used the same auto-incremented
    # conversation_id + task text) don't cause false 409 rejections.
    with _submissions_lock:
        _recent_submissions.clear()
    yield
    with _submissions_lock:
        _recent_submissions.clear()
    # Resolve the db_path from the module's app fixture, if present.
    try:
        app_instance = request.getfixturevalue("app")
    except pytest.FixtureLookupError:
        return
    db_path = app_instance.state.db_path
    if not os.path.exists(db_path):
        return
    with get_db(db_path) as conn:
        for table in _TABLES:
            try:
                conn.execute(f"DELETE FROM {table}")  # noqa: S608
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
        conn.execute(
            "DELETE FROM sqlite_sequence"
            " WHERE name IN ('conversations', 'conversation_task_queue')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO projects (id, display_name, working_dir)"
            " VALUES (0, 'Bot Imu', '/tmp/imu')"
        )
