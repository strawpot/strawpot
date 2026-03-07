"""SQLite database management — schema initialization and connection helpers."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    working_dir TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    run_id      TEXT PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    runtime     TEXT NOT NULL,
    isolation   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'starting',
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_ms INTEGER,
    exit_code   INTEGER,
    session_dir TEXT NOT NULL,
    task        TEXT,
    summary     TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status  ON sessions(status);

CREATE TABLE IF NOT EXISTS trigger_instances (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    adapter     TEXT NOT NULL,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    config      TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'stopped',
    last_error  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with recommended settings."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    """Create database file and apply schema if needed."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db(db_path: str):
    """Context manager yielding a database connection.

    Commits on clean exit, rolls back on exception.
    """
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db_conn(request: Request):
    """FastAPI dependency that yields a database connection."""
    with get_db(request.app.state.db_path) as conn:
        yield conn
