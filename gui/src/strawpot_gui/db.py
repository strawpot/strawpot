"""SQLite database management — schema initialization and connection helpers."""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    working_dir TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, created_at DESC);

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
    user_task   TEXT,
    summary     TEXT,
    files_changed TEXT,
    schedule_id INTEGER REFERENCES scheduled_tasks(id) ON DELETE SET NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status  ON sessions(status);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role          TEXT,
    task          TEXT NOT NULL,
    cron_expr     TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    system_prompt   TEXT,
    skip_if_running INTEGER NOT NULL DEFAULT 1,
    last_run_at     TEXT,
    next_run_at     TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with recommended settings."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
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
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def mark_orphaned_sessions_stopped(db_path: str) -> int:
    """Mark sessions stuck in 'running' or 'starting' as 'stopped' on server startup.

    Sessions in these states when the server starts are orphaned — their agent
    processes died with the previous server process.  Leaving them as 'running'
    causes WS file-watchers to hang indefinitely for every open browser tab.

    Returns the number of rows updated.
    """
    with get_db(db_path) as conn:
        cur = conn.execute(
            "UPDATE sessions SET status = 'stopped'"
            " WHERE status IN ('running', 'starting')"
        )
        return cur.rowcount


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply incremental schema migrations for existing databases."""
    # Add schedule_id column to sessions (added 2026-03-09)
    try:
        conn.execute(
            "ALTER TABLE sessions "
            "ADD COLUMN schedule_id INTEGER REFERENCES scheduled_tasks(id) ON DELETE SET NULL"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add skip_if_running column to scheduled_tasks (added 2026-03-09)
    try:
        conn.execute(
            "ALTER TABLE scheduled_tasks "
            "ADD COLUMN skip_if_running INTEGER NOT NULL DEFAULT 1"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add interactive column to sessions (added 2026-03-09)
    try:
        conn.execute(
            "ALTER TABLE sessions "
            "ADD COLUMN interactive INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add summary column to sessions (added 2026-03-11)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add conversation_id column to sessions (added 2026-03-11)
    try:
        conn.execute(
            "ALTER TABLE sessions "
            "ADD COLUMN conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add user_task column to sessions (added 2026-03-11)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_task TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add pending_task column to conversations (added 2026-03-12)
    try:
        conn.execute("ALTER TABLE conversations ADD COLUMN pending_task TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add files_changed column to sessions (added 2026-03-12)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN files_changed TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add duration_ms column to sessions (added 2026-03-12)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN duration_ms INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Index on conversation sessions (added 2026-03-11, after column migration)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_conversation "
        "ON sessions(conversation_id, started_at)"
    )

    # Migrate conversations table to AUTOINCREMENT to prevent rowid reuse
    # after deletion (added 2026-03-13).
    # IMPORTANT: foreign_keys must be OFF during the table swap, otherwise
    # DROP TABLE triggers ON DELETE SET NULL and wipes sessions.conversation_id.
    has_autoincrement = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone() and conn.execute(
        "SELECT 1 FROM sqlite_sequence WHERE name='conversations'"
    ).fetchone()
    if not has_autoincrement:
        conn.executescript("""
            PRAGMA foreign_keys=OFF;
            CREATE TABLE conversations_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title       TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT,
                pending_task TEXT
            );
            INSERT INTO conversations_new SELECT id, project_id, title, created_at, updated_at, pending_task FROM conversations;
            DROP TABLE conversations;
            ALTER TABLE conversations_new RENAME TO conversations;
            CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, created_at DESC);
            PRAGMA foreign_keys=ON;
        """)


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


# ---------------------------------------------------------------------------
# Session index sync
# ---------------------------------------------------------------------------


def _extract_recap(content: str) -> str:
    """Extract a '## Session Recap' block from agent output.

    If present, returns the recap section (without the heading).
    Otherwise returns the full content unchanged.
    """
    marker = "## Session Recap"
    idx = content.rfind(marker)
    if idx == -1:
        return content
    recap = content[idx + len(marker) :].strip()
    return recap if recap else content


def _strip_recap(content: str) -> str:
    """Return agent output with the '## Session Recap' block removed.

    If no recap is found, returns the full content unchanged.
    """
    marker = "## Session Recap"
    idx = content.rfind(marker)
    if idx == -1:
        return content
    before = content[:idx].rstrip()
    return before if before else content


def _parse_trace(trace_path: str, session_dir: str | None = None) -> dict:
    """Extract completion fields from a trace.jsonl file.

    Returns dict with keys: ended_at, duration_ms, exit_code, summary.
    Missing fields are omitted.
    """
    result: dict = {}
    try:
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("event")
                data = event.get("data", {})
                if etype == "session_end":
                    result["ended_at"] = event.get("ts")
                    if "duration_ms" in data:
                        result["duration_ms"] = data["duration_ms"]
                    result["exit_code"] = data.get("exit_code", 0)
                    # session_end carries the final output ref
                    output_ref = data.get("output_ref")
                    if output_ref and session_dir and "summary" not in result:
                        artifact_path = os.path.join(session_dir, "artifacts", output_ref)
                        try:
                            with open(artifact_path, encoding="utf-8") as af:
                                content = af.read().strip()
                            if content:
                                result["summary"] = content
                        except OSError:
                            pass
                    files_changed = data.get("files_changed")
                    if files_changed:
                        result["files_changed"] = json.dumps(files_changed)
                elif etype == "delegate_end" and not event.get("parent_span"):
                    # Fallback: root delegation also carries an output ref
                    output_ref = data.get("output_ref")
                    if output_ref and session_dir and "summary" not in result:
                        artifact_path = os.path.join(session_dir, "artifacts", output_ref)
                        try:
                            with open(artifact_path, encoding="utf-8") as af:
                                content = af.read().strip()
                            if content:
                                result["summary"] = content
                        except OSError:
                            pass
    except OSError:
        pass
    return result


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is alive (thin wrapper, no strawpot dependency)."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def ensure_imu_project(db_path: str) -> None:
    """Insert the virtual Bot Imu project (id=0) if not present.

    Uses the parent of STRAWPOT_HOME as working_dir so that session scanning
    resolves to ``{working_dir}/.strawpot/sessions/``.  When STRAWPOT_HOME is
    the default ``~/.strawpot``, this is equivalent to ``~``.
    """
    from strawpot.config import get_strawpot_home

    imu_working_dir = str(get_strawpot_home().parent)
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO projects (id, display_name, working_dir, created_at)
               VALUES (0, 'Bot Imu', ?, datetime('now'))""",
            (imu_working_dir,),
        )


def sync_sessions(db_path: str) -> None:
    """Scan all registered projects and upsert session rows into gui.db."""
    with get_db(db_path) as conn:
        projects = conn.execute(
            "SELECT id, working_dir FROM projects"
        ).fetchall()

        for project in projects:
            project_id = project["id"]
            working_dir = project["working_dir"]
            sync_project_sessions(conn, project_id, working_dir)


def sync_project_sessions(
    conn: sqlite3.Connection, project_id: int, working_dir: str
) -> None:
    """Scan a single project's session directories and upsert rows."""
    strawpot_dir = os.path.join(working_dir, ".strawpot")
    sessions_base = os.path.join(strawpot_dir, "sessions")
    if not os.path.isdir(sessions_base):
        return

    # Scan running sessions (symlinks in .strawpot/running/)
    running_dir = os.path.join(strawpot_dir, "running")
    if os.path.isdir(running_dir):
        for entry in os.listdir(running_dir):
            if not entry.startswith("run_"):
                continue
            session_dir = os.path.join(sessions_base, entry)
            if os.path.isdir(session_dir):
                _upsert_session(conn, project_id, session_dir, is_archived=False)

    # Scan archived sessions (symlinks in .strawpot/archive/)
    archive_dir = os.path.join(strawpot_dir, "archive")
    if os.path.isdir(archive_dir):
        for entry in os.listdir(archive_dir):
            if not entry.startswith("run_"):
                continue
            session_dir = os.path.join(sessions_base, entry)
            if os.path.isdir(session_dir):
                _upsert_session(conn, project_id, session_dir, is_archived=True)


def _upsert_session(
    conn: sqlite3.Connection,
    project_id: int,
    session_dir: str,
    *,
    is_archived: bool,
) -> None:
    """Read session.json + trace.jsonl and upsert a session row."""
    session_file = os.path.join(session_dir, "session.json")
    if not os.path.isfile(session_file):
        return

    try:
        with open(session_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.debug("Skipping unreadable session file: %s", session_file)
        return

    run_id = data.get("run_id")
    if not run_id:
        return

    # Extract role from first agent
    agents = data.get("agents", {})
    role = "unknown"
    if agents:
        first_agent = next(iter(agents.values()))
        role = first_agent.get("role", "unknown")

    runtime = data.get("runtime", "unknown")
    isolation = data.get("isolation", "none")
    started_at = data.get("started_at", "")

    # Determine status and parse trace
    trace_path = os.path.join(session_dir, "trace.jsonl")
    trace_info = _parse_trace(trace_path, session_dir)

    if is_archived:
        exit_code = trace_info.get("exit_code")
        if exit_code is not None and exit_code == 0:
            status = "completed"
        elif exit_code is not None:
            status = "failed"
        elif "ended_at" in trace_info:
            status = "completed"
        else:
            status = "failed"
    else:
        pid = data.get("pid")
        if pid is not None and _is_pid_alive(pid):
            status = "running"
        else:
            status = "stale"

    # Detect interactive sessions by presence of chat_messages.jsonl
    interactive = os.path.isfile(os.path.join(session_dir, "chat_messages.jsonl"))

    conn.execute(
        """INSERT INTO sessions
           (run_id, project_id, role, runtime, isolation, status,
            started_at, ended_at, duration_ms, exit_code, session_dir,
            task, summary, files_changed, interactive)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(run_id) DO UPDATE SET
             project_id  = excluded.project_id,
             role        = excluded.role,
             runtime     = excluded.runtime,
             isolation   = excluded.isolation,
             status      = CASE WHEN sessions.status IN ('stopped', 'completed', 'failed') THEN sessions.status ELSE excluded.status END,
             started_at  = excluded.started_at,
             ended_at    = excluded.ended_at,
             duration_ms = excluded.duration_ms,
             exit_code   = excluded.exit_code,
             session_dir = excluded.session_dir,
             task        = excluded.task,
             summary     = COALESCE(excluded.summary, sessions.summary),
             files_changed = COALESCE(excluded.files_changed, sessions.files_changed),
             interactive = MAX(sessions.interactive, excluded.interactive)
             -- conversation_id intentionally omitted: preserve existing FK""",
        (
            run_id,
            project_id,
            role,
            runtime,
            isolation,
            status,
            started_at,
            trace_info.get("ended_at"),
            trace_info.get("duration_ms"),
            trace_info.get("exit_code"),
            session_dir,
            data.get("task"),
            trace_info.get("summary"),
            trace_info.get("files_changed"),
            1 if interactive else 0,
        ),
    )
