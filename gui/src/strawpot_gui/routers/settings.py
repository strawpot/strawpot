"""Key-value settings endpoints backed by the SQLite settings table."""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def list_settings(conn=Depends(get_db_conn)):
    """Return all settings as a {key: value} mapping."""
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


@router.get("/{key}")
def get_setting(key: str, conn=Depends(get_db_conn)):
    """Return a single setting by key, or 404."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Setting '{key}' not found")
    return {"key": key, "value": row["value"]}


@router.put("/{key}")
def put_setting(key: str, body: dict = Body(...), conn=Depends(get_db_conn)):
    """Create or update a setting. Body: {"value": "..."}."""
    value = body.get("value")
    if value is None:
        raise HTTPException(422, "Missing 'value' in request body")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, str(value), now),
    )
    conn.connection.commit()
    return {"key": key, "value": str(value)}


@router.delete("/{key}")
def delete_setting(key: str, conn=Depends(get_db_conn)):
    """Delete a setting by key."""
    cur = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.connection.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, f"Setting '{key}' not found")
    return {"deleted": key}
