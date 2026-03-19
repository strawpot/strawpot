"""Integration management endpoints — list, detail, config CRUD, lifecycle, logs."""

import asyncio
import logging
import os
import shlex
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from starlette.websockets import WebSocket, WebSocketDisconnect

from strawpot.config import get_strawpot_home
from strawpot.context import parse_frontmatter

from strawpot_gui.db import get_db_conn
from strawpot_gui.routers.logs import read_log_delta, read_log_tail
from strawpot_gui.routers.registry import run_strawhub
from strawpot_gui.sse import watch_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

MANIFEST = "INTEGRATION.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_integration_manifest(manifest_path: Path) -> tuple[dict, str]:
    """Parse an INTEGRATION.md file and return (frontmatter, body)."""
    text = manifest_path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("frontmatter", {}), parsed.get("body", "")


def _read_version(resource_dir: Path) -> str | None:
    """Read version from .version file."""
    version_file = resource_dir / ".version"
    if version_file.is_file():
        try:
            return version_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    return None


def scan_integrations(base_dir: Path) -> list[dict]:
    """Scan ``base_dir/integrations/*/INTEGRATION.md`` for installed integrations."""
    scan_path = base_dir / "integrations"
    if not scan_path.is_dir():
        return []
    items: list[dict] = []
    for entry in sorted(scan_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        manifest_path = entry / MANIFEST
        if not manifest_path.is_file():
            continue
        try:
            fm, _body = parse_integration_manifest(manifest_path)
        except Exception:
            fm = {}
        strawpot_meta = fm.get("metadata", {}).get("strawpot", {})
        items.append({
            "name": fm.get("name", entry.name),
            "version": _read_version(entry),
            "description": fm.get("description", ""),
            "entry_point": strawpot_meta.get("entry_point", ""),
            "env_schema": strawpot_meta.get("env", {}),
            "health_check": strawpot_meta.get("health_check"),
            "path": str(entry),
        })
    return items


def _get_db_state(conn, name: str, project_id: int = 0) -> dict | None:
    """Read runtime state from the integrations DB table."""
    row = conn.execute(
        "SELECT status, pid, auto_start, last_error, started_at, created_at "
        "FROM integrations WHERE name = ? AND project_id = ?",
        (name, project_id),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _get_db_config(conn, name: str, project_id: int = 0) -> dict[str, str]:
    """Read saved config values from integration_config table."""
    rows = conn.execute(
        "SELECT key, value FROM integration_config "
        "WHERE integration_name = ? AND project_id = ?",
        (name, project_id),
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def _ensure_db_row(conn, name: str, project_id: int = 0) -> None:
    """Insert a row into integrations if it doesn't exist yet."""
    conn.execute(
        "INSERT OR IGNORE INTO integrations (name, project_id) VALUES (?, ?)",
        (name, project_id),
    )


def _merge_integration(manifest: dict, db_state: dict | None, db_config: dict) -> dict:
    """Merge filesystem manifest with DB runtime state."""
    result = {**manifest}
    if db_state:
        result["status"] = db_state["status"]
        result["pid"] = db_state["pid"]
        result["auto_start"] = bool(db_state["auto_start"])
        result["last_error"] = db_state["last_error"]
        result["started_at"] = db_state["started_at"]
    else:
        result["status"] = "stopped"
        result["pid"] = None
        result["auto_start"] = False
        result["last_error"] = None
        result["started_at"] = None
    result["config_values"] = db_config
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_integrations(project_id: int | None = None, conn=Depends(get_db_conn)):
    """List all installed integrations with their runtime state.

    When ``project_id`` is given, return instances for that project only.
    Project-local integrations take precedence over global ones with the
    same name.  When omitted, return global (project_id=0) instances
    (backward compat).
    """
    pid = project_id if project_id is not None else 0
    home = get_strawpot_home()

    results = []
    seen: set[str] = set()

    # For project-scoped requests, scan project-local integrations first
    if pid > 0:
        working_dir = _get_project_working_dir(conn, pid)
        if working_dir:
            project_base = Path(working_dir) / ".strawpot"
            for manifest in scan_integrations(project_base):
                name = manifest["name"]
                manifest["source"] = "project"
                db_state = _get_db_state(conn, name, pid)
                db_config = _get_db_config(conn, name, pid)
                merged = _merge_integration(manifest, db_state, db_config)
                merged["project_id"] = pid
                results.append(merged)
                seen.add(name)

    # Add global integrations (skip any shadowed by project-local)
    for manifest in scan_integrations(home):
        name = manifest["name"]
        if name in seen:
            continue
        manifest["source"] = "global"
        db_state = _get_db_state(conn, name, pid)
        db_config = _get_db_config(conn, name, pid)
        merged = _merge_integration(manifest, db_state, db_config)
        merged["project_id"] = pid
        results.append(merged)
    return results


@router.get("/{name}")
def get_integration(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Get detail for a single integration."""
    integration_dir, source = _resolve_integration_dir(name, conn, project_id)
    fm, body = parse_integration_manifest(integration_dir / MANIFEST)
    strawpot_meta = fm.get("metadata", {}).get("strawpot", {})
    manifest = {
        "name": fm.get("name", name),
        "description": fm.get("description", ""),
        "entry_point": strawpot_meta.get("entry_point", ""),
        "env_schema": strawpot_meta.get("env", {}),
        "health_check": strawpot_meta.get("health_check"),
        "path": str(integration_dir),
        "source": source,
        "body": body,
        "frontmatter": fm,
    }

    db_state = _get_db_state(conn, name, project_id)
    db_config = _get_db_config(conn, name, project_id)
    merged = _merge_integration(manifest, db_state, db_config)
    merged["project_id"] = project_id
    return merged


@router.get("/{name}/config")
def get_integration_config(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Get config schema and saved values for an integration."""
    integration_dir, _source = _resolve_integration_dir(name, conn, project_id)
    fm, _ = parse_integration_manifest(integration_dir / MANIFEST)
    env_schema = fm.get("metadata", {}).get("strawpot", {}).get("env", {})
    config_values = _get_db_config(conn, name, project_id)

    return {
        "env_schema": env_schema,
        "config_values": config_values,
    }


@router.put("/{name}/config")
def put_integration_config(
    name: str, data: dict = Body(...), project_id: int = 0, conn=Depends(get_db_conn)
):
    """Save config values for an integration."""
    _resolve_integration_dir(name, conn, project_id)  # validates existence

    config_values = data.get("config_values", {})
    if not isinstance(config_values, dict):
        raise HTTPException(400, "config_values must be a dict")

    _ensure_db_row(conn, name, project_id)

    # Delete existing config and re-insert
    conn.execute(
        "DELETE FROM integration_config "
        "WHERE integration_name = ? AND project_id = ?",
        (name, project_id),
    )
    for key, value in config_values.items():
        conn.execute(
            "INSERT INTO integration_config (integration_name, project_id, key, value) "
            "VALUES (?, ?, ?, ?)",
            (name, project_id, key, str(value) if value is not None else None),
        )

    return {"ok": True}


@router.put("/{name}/auto-start")
def put_auto_start(
    name: str, data: dict = Body(...), project_id: int = 0, conn=Depends(get_db_conn)
):
    """Toggle auto-start for an integration."""
    _resolve_integration_dir(name, conn, project_id)  # validates existence

    enabled = bool(data.get("enabled", False))
    _ensure_db_row(conn, name, project_id)
    conn.execute(
        "UPDATE integrations SET auto_start = ? "
        "WHERE name = ? AND project_id = ?",
        (1 if enabled else 0, name, project_id),
    )
    return {"ok": True, "auto_start": enabled}


@router.delete("/{name}/config")
def delete_integration_config(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Clear all saved config for an integration."""
    conn.execute(
        "DELETE FROM integration_config "
        "WHERE integration_name = ? AND project_id = ?",
        (name, project_id),
    )
    conn.execute(
        "DELETE FROM integrations WHERE name = ? AND project_id = ?",
        (name, project_id),
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.post("/{name}/notify")
def notify_integration(
    name: str, data: dict = Body(...), project_id: int = 0, conn=Depends(get_db_conn)
):
    """Push a notification to an integration for delivery to the chat platform.

    Body: {"message": "...", "chat_id": "optional-target"}
    """
    message = data.get("message", "").strip()
    if not message:
        raise HTTPException(400, "'message' is required")

    _resolve_integration_dir(name, conn, project_id)  # validates existence
    _ensure_db_row(conn, name, project_id)

    chat_id = data.get("chat_id")
    conn.execute(
        "INSERT INTO integration_notifications "
        "(integration_name, project_id, chat_id, message) "
        "VALUES (?, ?, ?, ?)",
        (name, project_id, chat_id, message),
    )
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    notification_id = row[0]

    return {"id": notification_id, "integration_name": name, "status": "pending"}


@router.get("/{name}/notifications")
def list_notifications(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Return pending (undelivered) notifications for an integration.

    Adapters poll this endpoint to discover messages they need to deliver.
    """
    _resolve_integration_dir(name, conn, project_id)  # validates existence

    rows = conn.execute(
        "SELECT id, chat_id, message, created_at "
        "FROM integration_notifications "
        "WHERE integration_name = ? AND project_id = ? AND delivered_at IS NULL "
        "ORDER BY id",
        (name, project_id),
    ).fetchall()

    return [dict(r) for r in rows]


@router.post("/{name}/notifications/{notification_id}/ack")
def ack_notification(
    name: str, notification_id: int, project_id: int = 0, conn=Depends(get_db_conn)
):
    """Mark a notification as delivered.

    Adapters call this after successfully sending the message to the platform.
    """
    row = conn.execute(
        "SELECT id FROM integration_notifications "
        "WHERE id = ? AND integration_name = ? AND project_id = ?",
        (notification_id, name, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Notification not found")

    conn.execute(
        "UPDATE integration_notifications SET delivered_at = datetime('now') "
        "WHERE id = ?",
        (notification_id,),
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Install / Uninstall via Strawhub
# ---------------------------------------------------------------------------


@router.post("/install")
def install_integration(data: dict = Body(...)):
    """Install an integration from Strawhub by name."""
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    return run_strawhub("install", "integration", "-y", name)


def _stop_if_running(conn, name: str, project_id: int = 0) -> bool:
    """Stop an integration if it is running. Returns True if it was running."""
    db_state = _get_db_state(conn, name, project_id)
    if not db_state or db_state["status"] != "running" or not db_state["pid"]:
        return False
    pid = db_state["pid"]
    if _is_process_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        # Wait for the process to actually exit before proceeding
        for _ in range(50):  # up to 5 seconds
            if not _is_process_alive(pid):
                break
            time.sleep(0.1)
        else:
            logger.warning(
                "Integration '%s' (pid %s) did not exit after SIGTERM, sending SIGKILL",
                name, pid,
            )
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
    conn.execute(
        "UPDATE integrations SET status = 'stopped', pid = NULL "
        "WHERE name = ? AND project_id = ?",
        (name, project_id),
    )
    logger.info("Stopped integration '%s' (pid %s) before mutation", name, pid)
    return True


@router.post("/update")
def update_integration(
    data: dict = Body(...),
    request: Request = None,
    conn=Depends(get_db_conn),
):
    """Update an integration to its latest version via strawhub."""
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    project_id = int(data.get("project_id", 0))
    was_running = _stop_if_running(conn, name, project_id)
    result = run_strawhub("update", "-y", "integration", name)
    if was_running and result.get("exit_code") == 0:
        try:
            start_integration(name, request, conn, project_id=project_id)
        except Exception as exc:
            logger.warning("Failed to restart '%s' after update: %s", name, exc)
    return result


@router.post("/reinstall")
def reinstall_integration(
    data: dict = Body(...),
    request: Request = None,
    conn=Depends(get_db_conn),
):
    """Reinstall an integration (re-download current version) via strawhub."""
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")
    project_id = int(data.get("project_id", 0))
    integration_dir, _source = _resolve_integration_dir(name, conn, project_id)
    version_file = integration_dir / ".version"
    if not version_file.is_file():
        raise HTTPException(404, f"Integration has no version: {name}")
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise HTTPException(404, f"Empty version file for integration: {name}")
    was_running = _stop_if_running(conn, name, project_id)
    result = run_strawhub("install", "integration", "-y", name, "--version", version, "--force")
    if was_running and result.get("exit_code") == 0:
        try:
            start_integration(name, request, conn, project_id=project_id)
        except Exception as exc:
            logger.warning("Failed to restart '%s' after reinstall: %s", name, exc)
    return result


@router.delete("/{name}")
def uninstall_integration(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Stop (if running) and uninstall an integration."""
    _stop_if_running(conn, name, project_id)

    # Remove DB state for this instance
    conn.execute(
        "DELETE FROM integration_config "
        "WHERE integration_name = ? AND project_id = ?",
        (name, project_id),
    )
    conn.execute(
        "DELETE FROM integrations WHERE name = ? AND project_id = ?",
        (name, project_id),
    )

    # Uninstall the binary — global or project-scoped
    if project_id > 0:
        working_dir = _get_project_working_dir(conn, project_id)
        if working_dir:
            return run_strawhub("uninstall", "integration", name, "--root", working_dir)
        return {"ok": True}
    return run_strawhub("uninstall", "integration", name)



# ---------------------------------------------------------------------------
# Lifecycle endpoints
# ---------------------------------------------------------------------------


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _get_project_working_dir(conn, project_id: int) -> str | None:
    """Look up a project's working_dir from the projects table."""
    row = conn.execute(
        "SELECT working_dir FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return row["working_dir"] if row else None


def _resolve_integration_dir(
    name: str, conn, project_id: int = 0
) -> tuple[Path, str]:
    """Find an integration directory, checking project-local first then global.

    Returns (integration_dir, source) where source is "project" or "global".
    Raises HTTPException(404) if not found in either location.
    """
    if project_id > 0:
        working_dir = _get_project_working_dir(conn, project_id)
        if working_dir:
            project_dir = Path(working_dir) / ".strawpot" / "integrations" / name
            if (project_dir / MANIFEST).is_file():
                return project_dir, "project"
    global_dir = get_strawpot_home() / "integrations" / name
    if (global_dir / MANIFEST).is_file():
        return global_dir, "global"
    raise HTTPException(404, f"Integration not found: {name}")


def _build_env(
    name: str, config_values: dict, request: Request, conn, *, project_id: int = 0
) -> dict:
    """Build environment variables for the adapter subprocess."""
    env = os.environ.copy()

    # Add common PATH entries
    home = Path.home()
    extra_paths = [
        str(home / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]
    existing = env.get("PATH", "")
    env["PATH"] = ":".join(extra_paths) + ":" + existing

    # Derive API URL from the running server's actual request URL.
    # Include /via prefix so the middleware auto-tags conversations.
    base = str(request.base_url).rstrip("/")
    if project_id > 0:
        env["STRAWPOT_API_URL"] = f"{base}/via/p/{project_id}/{name}"
        env["STRAWPOT_PROJECT_ID"] = str(project_id)
    else:
        env["STRAWPOT_API_URL"] = f"{base}/via/{name}"
    env["STRAWPOT_INTEGRATION_NAME"] = name

    # Persistent data directory for adapter state (survives reinstalls).
    # Project-scoped instances store data under the project's working dir;
    # global instances use the strawpot home directory.
    if project_id > 0:
        working_dir = _get_project_working_dir(conn, project_id)
        if working_dir:
            data_dir = Path(working_dir) / ".strawpot" / "data" / "integrations" / name
            env["STRAWPOT_PROJECT_DIR"] = working_dir
        else:
            data_dir = get_strawpot_home() / "data" / "integrations" / name
    else:
        data_dir = get_strawpot_home() / "data" / "integrations" / name
    data_dir.mkdir(parents=True, exist_ok=True)
    env["STRAWPOT_DATA_DIR"] = str(data_dir)

    # Pass saved env values directly (keys are already env var names).
    # Skip empty strings so they don't overwrite auto-derived values
    # like STRAWPOT_API_URL.
    for key, value in config_values.items():
        if value is not None and value != "":
            env[key] = str(value)

    return env


@router.post("/{name}/start")
def start_integration(
    name: str, request: Request, conn=Depends(get_db_conn), project_id: int = 0
):
    """Start an integration adapter subprocess."""
    integration_dir, _source = _resolve_integration_dir(name, conn, project_id)
    fm, _ = parse_integration_manifest(integration_dir / MANIFEST)
    strawpot_meta = fm.get("metadata", {}).get("strawpot", {})
    entry_point = strawpot_meta.get("entry_point", "")
    if not entry_point:
        raise HTTPException(422, f"Integration '{name}' has no entry_point")

    _ensure_db_row(conn, name, project_id)

    # Check if already running
    db_state = _get_db_state(conn, name, project_id)
    if db_state and db_state["status"] == "running" and db_state["pid"]:
        if _is_process_alive(db_state["pid"]):
            raise HTTPException(409, f"Integration '{name}' is already running (pid {db_state['pid']})")
        # PID stale — clean up below

    config_values = _get_db_config(conn, name, project_id)
    env = _build_env(name, config_values, request, conn, project_id=project_id)

    # Log file for adapter output
    log_path = integration_dir / ".log"

    try:
        log_file = open(log_path, "a", encoding="utf-8")
        cmd = shlex.split(entry_point)
        proc = subprocess.Popen(
            cmd,
            cwd=str(integration_dir),
            start_new_session=True,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except OSError as exc:
        conn.execute(
            "UPDATE integrations SET status = 'error', last_error = ?, pid = NULL "
            "WHERE name = ? AND project_id = ?",
            (str(exc), name, project_id),
        )
        raise HTTPException(500, f"Failed to start integration: {exc}")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE integrations SET status = 'running', pid = ?, last_error = NULL, "
        "started_at = ? WHERE name = ? AND project_id = ?",
        (proc.pid, now, name, project_id),
    )
    logger.info("Started integration '%s' (project_id=%d, pid %d)", name, project_id, proc.pid)
    return {"name": name, "project_id": project_id, "status": "running", "pid": proc.pid}


@router.post("/{name}/stop")
def stop_integration(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Stop a running integration adapter by sending SIGTERM."""
    _resolve_integration_dir(name, conn, project_id)  # verify exists
    _ensure_db_row(conn, name, project_id)

    db_state = _get_db_state(conn, name, project_id)
    if not db_state or db_state["status"] != "running" or not db_state["pid"]:
        raise HTTPException(409, f"Integration '{name}' is not running")

    pid = db_state["pid"]

    if not _is_process_alive(pid):
        conn.execute(
            "UPDATE integrations SET status = 'stopped', pid = NULL "
            "WHERE name = ? AND project_id = ?",
            (name, project_id),
        )
        return {"name": name, "status": "stopped"}

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass  # race: died between check and kill

    conn.execute(
        "UPDATE integrations SET status = 'stopped', pid = NULL "
        "WHERE name = ? AND project_id = ?",
        (name, project_id),
    )
    logger.info("Stopped integration '%s' (pid %d)", name, pid)
    return {"name": name, "status": "stopped"}


@router.get("/{name}/status")
def get_integration_status(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Check live status of an integration (process alive + optional health check)."""
    _resolve_integration_dir(name, conn, project_id)
    db_state = _get_db_state(conn, name, project_id)
    if not db_state:
        return {"name": name, "status": "stopped", "pid": None}

    pid = db_state["pid"]
    if pid and not _is_process_alive(pid):
        # Process died — update DB
        conn.execute(
            "UPDATE integrations SET status = 'error', "
            "last_error = 'Process exited unexpectedly' "
            "WHERE name = ? AND project_id = ?",
            (name, project_id),
        )
        return {
            "name": name,
            "status": "error",
            "pid": pid,
            "last_error": "Process exited unexpectedly",
        }

    return {
        "name": name,
        "status": db_state["status"],
        "pid": pid,
        "last_error": db_state["last_error"],
        "started_at": db_state["started_at"],
    }


# ---------------------------------------------------------------------------
# Auto-start support
# ---------------------------------------------------------------------------


def mark_orphaned_integrations_stopped(db_path: str) -> None:
    """Stop all integrations marked as running. Called at startup.

    On a clean restart the adapters were already SIGTERM'd during shutdown.
    On a crash they may still be alive but pointing at the old server URL,
    so we kill them and let auto_start_integrations re-launch with the
    correct API URL.
    """
    from strawpot_gui.db import get_db

    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT name, project_id, pid FROM integrations "
            "WHERE status = 'running' AND pid IS NOT NULL"
        ).fetchall()
        for row in rows:
            pid = row["pid"]
            if _is_process_alive(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info(
                        "Stopped stale integration '%s' (project_id=%d, pid %d) from previous run",
                        row["name"], row["project_id"], pid,
                    )
                except (ProcessLookupError, OSError):
                    pass
                # Wait for the process to exit before proceeding — without
                # this, auto_start_integrations can spawn a replacement while
                # the old process is still alive, leaking zombie adapters.
                for _ in range(50):  # up to 5 seconds
                    if not _is_process_alive(pid):
                        break
                    time.sleep(0.1)
                else:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass
            conn.execute(
                "UPDATE integrations SET status = 'stopped', pid = NULL "
                "WHERE name = ? AND project_id = ?",
                (row["name"], row["project_id"]),
            )


def auto_start_integrations(db_path: str, *, host: str = "127.0.0.1", port: int = 8741) -> None:
    """Start all integrations with auto_start enabled. Called during app lifespan."""
    from strawpot_gui.db import get_db

    home = get_strawpot_home()

    # Query all rows with auto_start across all projects
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT name, project_id, status, pid, auto_start "
            "FROM integrations WHERE auto_start = 1"
        ).fetchall()

    for row in rows:
        name = row["name"]
        project_id = row["project_id"]

        # Resolve integration dir: project-local first, global fallback
        try:
            with get_db(db_path) as conn:
                integration_dir, _source = _resolve_integration_dir(name, conn, project_id)
        except HTTPException:
            continue  # not installed

        fm, _ = parse_integration_manifest(integration_dir / MANIFEST)
        entry_point = fm.get("metadata", {}).get("strawpot", {}).get("entry_point", "")
        if not entry_point:
            continue

        if row["status"] == "running" and row["pid"]:
            if _is_process_alive(row["pid"]):
                continue  # already running

        with get_db(db_path) as conn:
            config_values = _get_db_config(conn, name, project_id)

        # Build env without request context
        env = os.environ.copy()
        home_dir = Path.home()
        extra_paths = [
            str(home_dir / ".local" / "bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]
        env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")
        if project_id > 0:
            env["STRAWPOT_API_URL"] = f"http://{host}:{port}/via/p/{project_id}/{name}"
            env["STRAWPOT_PROJECT_ID"] = str(project_id)
        else:
            env["STRAWPOT_API_URL"] = f"http://{host}:{port}/via/{name}"
        env["STRAWPOT_INTEGRATION_NAME"] = name

        # Project-scoped data dir mirrors _build_env logic
        if project_id > 0:
            with get_db(db_path) as conn2:
                working_dir = _get_project_working_dir(conn2, project_id)
            if working_dir:
                data_dir = Path(working_dir) / ".strawpot" / "data" / "integrations" / name
                env["STRAWPOT_PROJECT_DIR"] = working_dir
            else:
                data_dir = home / "data" / "integrations" / name
        else:
            data_dir = home / "data" / "integrations" / name
        data_dir.mkdir(parents=True, exist_ok=True)
        env["STRAWPOT_DATA_DIR"] = str(data_dir)
        for key, value in config_values.items():
            if value is not None and value != "":
                env[key] = str(value)

        log_path = integration_dir / ".log"
        try:
            log_file = open(log_path, "a", encoding="utf-8")
            cmd = shlex.split(entry_point)
            proc = subprocess.Popen(
                cmd,
                cwd=str(integration_dir),
                start_new_session=True,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except OSError as exc:
            logger.warning("Failed to auto-start integration '%s' (project_id=%d): %s", name, project_id, exc)
            with get_db(db_path) as conn:
                conn.execute(
                    "UPDATE integrations SET status = 'error', last_error = ? "
                    "WHERE name = ? AND project_id = ?",
                    (str(exc), name, project_id),
                )
            continue

        now = datetime.now(timezone.utc).isoformat()
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE integrations SET status = 'running', pid = ?, "
                "last_error = NULL, started_at = ? WHERE name = ? AND project_id = ?",
                (proc.pid, now, name, project_id),
            )
        logger.info("Auto-started integration '%s' (project_id=%d, pid %d)", name, project_id, proc.pid)


def stop_all_integrations(db_path: str) -> None:
    """Send SIGTERM to all running integrations. Called during app shutdown."""
    from strawpot_gui.db import get_db

    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT name, project_id, pid FROM integrations "
            "WHERE status = 'running' AND pid IS NOT NULL"
        ).fetchall()
        for row in rows:
            pid = row["pid"]
            if _is_process_alive(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info("Sent SIGTERM to integration '%s' (project_id=%d, pid %d)", row["name"], row["project_id"], pid)
                except (ProcessLookupError, OSError):
                    pass
            conn.execute(
                "UPDATE integrations SET status = 'stopped', pid = NULL "
                "WHERE name = ? AND project_id = ?",
                (row["name"], row["project_id"]),
            )


# ---------------------------------------------------------------------------
# Log management
# ---------------------------------------------------------------------------


@router.delete("/{name}/logs")
def clear_integration_logs(name: str, project_id: int = 0, conn=Depends(get_db_conn)):
    """Truncate the integration adapter log file."""
    integration_dir, _source = _resolve_integration_dir(name, conn, project_id)
    log_path = integration_dir / ".log"
    if log_path.is_file():
        log_path.write_text("")
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSocket: integration log streaming
# ---------------------------------------------------------------------------


@router.websocket("/{name}/logs/ws")
async def integration_logs_ws(websocket: WebSocket, name: str, project_id: int = 0) -> None:
    """Stream integration adapter logs over WebSocket.

    Protocol (server → client):
      {"type": "log_snapshot", "lines": [...], "offset": N}
      {"type": "log_delta",    "lines": [...], "offset": N}
      {"type": "log_done"}  — integration stopped, stream ends
      {"type": "error", "message": "..."}
    """
    # Resolve integration dir — need DB connection for project-local lookup
    db_path: str = websocket.app.state.db_path
    from strawpot_gui.db import get_db
    try:
        with get_db(db_path) as conn:
            integration_dir, _source = _resolve_integration_dir(name, conn, project_id)
    except HTTPException:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": f"Integration not found: {name}"})
        await websocket.close(code=4004)
        return

    log_path = str(integration_dir / ".log")

    await websocket.accept()

    # Send initial snapshot
    lines, offset = read_log_tail(log_path)
    await websocket.send_json({
        "type": "log_snapshot",
        "lines": lines,
        "offset": offset,
    })

    # Check if integration is currently running
    with get_db(db_path) as conn:
        db_state = _get_db_state(conn, name, project_id)

    is_running = (
        db_state is not None
        and db_state["status"] == "running"
        and db_state["pid"]
        and _is_process_alive(db_state["pid"])
    )

    if not is_running:
        await websocket.send_json({"type": "log_done"})
        await websocket.close()
        return

    # Watch for log changes
    stop = asyncio.Event()

    async def log_watcher() -> None:
        nonlocal offset
        try:
            async for changed_files in watch_dir(str(integration_dir), stop):
                if not changed_files:
                    # Timeout — check if still running
                    with get_db(db_path) as conn:
                        state = _get_db_state(conn, name, project_id)
                    alive = (
                        state is not None
                        and state["status"] == "running"
                        and state["pid"]
                        and _is_process_alive(state["pid"])
                    )
                    if not alive:
                        # Final read
                        new_lines, offset = read_log_delta(log_path, offset)
                        if new_lines:
                            await websocket.send_json({
                                "type": "log_delta",
                                "lines": new_lines,
                                "offset": offset,
                            })
                        await websocket.send_json({"type": "log_done"})
                        return
                    continue

                if any(f.endswith(".log") for f in changed_files):
                    new_lines, offset = read_log_delta(log_path, offset)
                    if new_lines:
                        await websocket.send_json({
                            "type": "log_delta",
                            "lines": new_lines,
                            "offset": offset,
                        })
        except asyncio.CancelledError:
            pass

    async def receiver() -> None:
        """Drain client messages (keep connection alive)."""
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            stop.set()

    watcher_task = asyncio.create_task(log_watcher())
    receiver_task = asyncio.create_task(receiver())

    try:
        await asyncio.wait(
            {watcher_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        stop.set()
        for task in [watcher_task, receiver_task]:
            task.cancel()
        await asyncio.gather(watcher_task, receiver_task, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
