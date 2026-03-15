"""Integration management endpoints — list, detail, config CRUD."""

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException

from strawpot.config import get_strawpot_home
from strawpot.context import parse_frontmatter

from strawpot_gui.db import get_db_conn

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
            "description": fm.get("description", ""),
            "entry_point": strawpot_meta.get("entry_point", ""),
            "auto_start": strawpot_meta.get("auto_start", False),
            "config_schema": strawpot_meta.get("config", {}),
            "health_check": strawpot_meta.get("health_check"),
            "path": str(entry),
        })
    return items


def _get_db_state(conn, name: str) -> dict | None:
    """Read runtime state from the integrations DB table."""
    row = conn.execute(
        "SELECT status, pid, auto_start, last_error, started_at, created_at "
        "FROM integrations WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _get_db_config(conn, name: str) -> dict[str, str]:
    """Read saved config values from integration_config table."""
    rows = conn.execute(
        "SELECT key, value FROM integration_config WHERE integration_name = ?",
        (name,),
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def _ensure_db_row(conn, name: str) -> None:
    """Insert a row into integrations if it doesn't exist yet."""
    conn.execute(
        "INSERT OR IGNORE INTO integrations (name) VALUES (?)",
        (name,),
    )


def _merge_integration(manifest: dict, db_state: dict | None, db_config: dict) -> dict:
    """Merge filesystem manifest with DB runtime state."""
    result = {**manifest}
    if db_state:
        result["status"] = db_state["status"]
        result["pid"] = db_state["pid"]
        result["last_error"] = db_state["last_error"]
        result["started_at"] = db_state["started_at"]
    else:
        result["status"] = "stopped"
        result["pid"] = None
        result["last_error"] = None
        result["started_at"] = None
    result["config_values"] = db_config
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_integrations(conn=Depends(get_db_conn)):
    """List all installed integrations with their runtime state."""
    home = get_strawpot_home()
    manifests = scan_integrations(home)
    results = []
    for manifest in manifests:
        name = manifest["name"]
        db_state = _get_db_state(conn, name)
        db_config = _get_db_config(conn, name)
        results.append(_merge_integration(manifest, db_state, db_config))
    return results


@router.get("/{name}")
def get_integration(name: str, conn=Depends(get_db_conn)):
    """Get detail for a single integration."""
    home = get_strawpot_home()
    integration_dir = home / "integrations" / name
    manifest_path = integration_dir / MANIFEST
    if not manifest_path.is_file():
        raise HTTPException(404, f"Integration not found: {name}")

    fm, body = parse_integration_manifest(manifest_path)
    strawpot_meta = fm.get("metadata", {}).get("strawpot", {})
    manifest = {
        "name": fm.get("name", name),
        "description": fm.get("description", ""),
        "entry_point": strawpot_meta.get("entry_point", ""),
        "auto_start": strawpot_meta.get("auto_start", False),
        "config_schema": strawpot_meta.get("config", {}),
        "health_check": strawpot_meta.get("health_check"),
        "path": str(integration_dir),
        "body": body,
        "frontmatter": fm,
    }

    db_state = _get_db_state(conn, name)
    db_config = _get_db_config(conn, name)
    return _merge_integration(manifest, db_state, db_config)


@router.get("/{name}/config")
def get_integration_config(name: str, conn=Depends(get_db_conn)):
    """Get config schema and saved values for an integration."""
    home = get_strawpot_home()
    manifest_path = home / "integrations" / name / MANIFEST
    if not manifest_path.is_file():
        raise HTTPException(404, f"Integration not found: {name}")

    fm, _ = parse_integration_manifest(manifest_path)
    config_schema = fm.get("metadata", {}).get("strawpot", {}).get("config", {})
    config_values = _get_db_config(conn, name)

    return {
        "config_schema": config_schema,
        "config_values": config_values,
    }


@router.put("/{name}/config")
def put_integration_config(
    name: str, data: dict = Body(...), conn=Depends(get_db_conn)
):
    """Save config values for an integration."""
    home = get_strawpot_home()
    manifest_path = home / "integrations" / name / MANIFEST
    if not manifest_path.is_file():
        raise HTTPException(404, f"Integration not found: {name}")

    config_values = data.get("config_values", {})
    if not isinstance(config_values, dict):
        raise HTTPException(400, "config_values must be a dict")

    _ensure_db_row(conn, name)

    # Delete existing config and re-insert
    conn.execute(
        "DELETE FROM integration_config WHERE integration_name = ?", (name,)
    )
    for key, value in config_values.items():
        conn.execute(
            "INSERT INTO integration_config (integration_name, key, value) "
            "VALUES (?, ?, ?)",
            (name, key, str(value) if value is not None else None),
        )

    return {"ok": True}


@router.delete("/{name}/config")
def delete_integration_config(name: str, conn=Depends(get_db_conn)):
    """Clear all saved config for an integration."""
    conn.execute(
        "DELETE FROM integration_config WHERE integration_name = ?", (name,)
    )
    conn.execute("DELETE FROM integrations WHERE name = ?", (name,))
    return {"ok": True}
