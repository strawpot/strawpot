"""Project-scoped resource endpoints — list, detail, install, uninstall."""

from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException

from strawpot.config import _read_toml, get_strawpot_home, save_resource_config

from strawpot_gui.db import get_db_conn
from strawpot_gui.routers.registry import (
    RESOURCE_TYPES,
    coerce_param,
    extract_saved_values,
    parse_manifest,
    read_version,
    run_strawhub,
    scan_dir,
    singular_type,
    validate_type,
)

router = APIRouter(prefix="/api/projects", tags=["project-resources"])


def _get_project_dir(project_id: int, conn) -> str:
    """Look up project working_dir from DB and validate it exists."""
    row = conn.execute(
        "SELECT working_dir FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    working_dir = row["working_dir"]
    if not Path(working_dir).is_dir():
        raise HTTPException(400, f"Project directory does not exist: {working_dir}")
    return working_dir


def _count_config_overrides(toml_data: dict, resource_type: str, name: str) -> int:
    """Count the number of env/param overrides for a resource in TOML data."""
    count = 0
    if resource_type == "roles":
        role_data = toml_data.get("roles", {}).get(name, {})
        count = len(role_data) if isinstance(role_data, dict) else 0
    elif resource_type == "skills":
        skill_data = toml_data.get("skills", {}).get(name, {})
        count = len(skill_data.get("env", {})) if isinstance(skill_data, dict) else 0
    elif resource_type == "agents":
        agent_data = toml_data.get("agents", {}).get(name, {})
        if not isinstance(agent_data, dict):
            agent_data = {}
        count = len(agent_data.get("env", {}))
        # Count non-env params (keys other than "env")
        count += sum(1 for k in agent_data if k != "env")
    elif resource_type == "memories":
        count = len(toml_data.get("memories", {}).get(name, {}).get("env", {}))
        # memory_config is shared across all memory providers, count if any
        count += len(toml_data.get("memory_config", {}))
    return count


@router.get("/{project_id}/resources")
def list_project_resources(project_id: int, conn=Depends(get_db_conn)):
    """List all resources available to a project (project-local + global).

    Project-local resources take precedence over global ones with the same name.
    Each resource includes a config_count of project-level overrides from
    strawpot.toml.
    """
    working_dir = _get_project_dir(project_id, conn)
    project_base = Path(working_dir) / ".strawpot"
    global_base = get_strawpot_home()
    toml_path = Path(working_dir) / "strawpot.toml"
    toml_data = _read_toml(toml_path)
    results = []
    for rtype, (dir_name, manifest) in RESOURCE_TYPES.items():
        # Scan project-local first, track names to avoid duplicates
        seen: set[str] = set()
        for item in scan_dir(project_base, dir_name, manifest, rtype, "project"):
            item["type"] = rtype
            item["config_count"] = _count_config_overrides(toml_data, rtype, item["name"])
            results.append(item)
            seen.add(item["name"])
        # Add global resources not shadowed by project-local ones
        for item in scan_dir(global_base, dir_name, manifest, rtype, "global"):
            if item["name"] not in seen:
                item["type"] = rtype
                item["config_count"] = _count_config_overrides(toml_data, rtype, item["name"])
                results.append(item)
    return results


def _resolve_resource_dir(
    working_dir: str, dir_name: str, manifest: str, name: str
) -> tuple[Path, str]:
    """Find a resource directory, checking project-local first then global.

    Returns (resource_dir, source) where source is "project" or "global".
    Raises HTTPException(404) if not found in either location.
    """
    project_dir = Path(working_dir) / ".strawpot" / dir_name / name
    if (project_dir / manifest).is_file():
        return project_dir, "project"
    global_dir = get_strawpot_home() / dir_name / name
    if (global_dir / manifest).is_file():
        return global_dir, "global"
    raise HTTPException(404, f"Resource not found: {dir_name}/{name}")


@router.get("/{project_id}/resources/{resource_type}/{name}")
def get_project_resource(
    project_id: int, resource_type: str, name: str, conn=Depends(get_db_conn)
):
    """Get detail for a resource available to this project."""
    working_dir = _get_project_dir(project_id, conn)
    dir_name, manifest = validate_type(resource_type)
    resource_dir, source = _resolve_resource_dir(working_dir, dir_name, manifest, name)

    fm, body = parse_manifest(resource_dir / manifest, resource_type)
    return {
        "name": fm.get("name", name),
        "version": read_version(resource_dir, fm),
        "description": fm.get("description", ""),
        "frontmatter": fm,
        "body": body,
        "source": source,
        "path": str(resource_dir),
    }


@router.get("/{project_id}/resources/{resource_type}/{name}/config")
def get_project_resource_config(
    project_id: int, resource_type: str, name: str, conn=Depends(get_db_conn)
):
    """Get env/params schema and saved values from project's strawpot.toml."""
    working_dir = _get_project_dir(project_id, conn)
    dir_name, manifest = validate_type(resource_type)
    resource_dir, _ = _resolve_resource_dir(working_dir, dir_name, manifest, name)

    fm, _ = parse_manifest(resource_dir / manifest, resource_type)
    strawpot_meta = fm.get("metadata", {}).get("strawpot", {})

    env_schema = strawpot_meta.get("env", {})
    params_schema = strawpot_meta.get("params", {})

    if resource_type == "roles":
        manifest_default = strawpot_meta.get("default_agent")
        params_schema = {
            "default_agent": {
                "type": "string",
                "default": manifest_default,
                "description": "Agent to use when running this role",
            },
        }

    toml_path = Path(working_dir) / "strawpot.toml"
    toml_data = _read_toml(toml_path)
    env_values, params_values = extract_saved_values(
        toml_data, resource_type, name, params_schema
    )

    return {
        "env_schema": env_schema,
        "env_values": env_values,
        "params_schema": params_schema,
        "params_values": params_values,
    }


@router.put("/{project_id}/resources/{resource_type}/{name}/config")
def put_project_resource_config(
    project_id: int,
    resource_type: str,
    name: str,
    data: dict = Body(...),
    conn=Depends(get_db_conn),
):
    """Save env and param values for a project-scoped resource."""
    working_dir = _get_project_dir(project_id, conn)
    dir_name, manifest = validate_type(resource_type)
    resource_dir, _ = _resolve_resource_dir(working_dir, dir_name, manifest, name)
    manifest_path = resource_dir / manifest

    env_values = data.get("env_values")
    params_values = data.get("params_values")

    if params_values:
        fm, _ = parse_manifest(manifest_path, resource_type)
        params_schema = fm.get("metadata", {}).get("strawpot", {}).get("params", {})
        coerced = {}
        for k, v in params_values.items():
            schema = params_schema.get(k, {})
            try:
                coerced[k] = coerce_param(v, schema.get("type"))
            except (ValueError, TypeError):
                coerced[k] = v
        params_values = coerced

    save_resource_config(
        Path(working_dir), resource_type, name, env_values, params_values
    )
    return {"ok": True}


@router.post("/{project_id}/resources/install")
def install_project_resource(
    project_id: int, data: dict = Body(...), conn=Depends(get_db_conn)
):
    """Install a resource to a project via strawhub --root."""
    working_dir = _get_project_dir(project_id, conn)
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")
    singular = singular_type(resource_type)
    return run_strawhub("--root", working_dir, "install", singular, "-y", name)


@router.delete("/{project_id}/resources/{resource_type}/{name}")
def uninstall_project_resource(
    project_id: int, resource_type: str, name: str, conn=Depends(get_db_conn)
):
    """Uninstall a resource from a project via strawhub --root."""
    working_dir = _get_project_dir(project_id, conn)
    validate_type(resource_type)
    singular = singular_type(resource_type)
    return run_strawhub("--root", working_dir, "uninstall", singular, name)


@router.post("/{project_id}/resources/update")
def update_project_resource(
    project_id: int, data: dict = Body(...), conn=Depends(get_db_conn)
):
    """Update a project resource to its latest version via strawhub --root."""
    working_dir = _get_project_dir(project_id, conn)
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")
    singular = singular_type(resource_type)
    return run_strawhub("--root", working_dir, "update", singular, "-y", name)


@router.post("/{project_id}/resources/update-all")
def update_all_project_resources(project_id: int, conn=Depends(get_db_conn)):
    """Update all project resources to their latest versions via strawhub --root."""
    working_dir = _get_project_dir(project_id, conn)
    return run_strawhub("--root", working_dir, "update", "--all", "-y", timeout=300)


@router.post("/{project_id}/resources/reinstall")
def reinstall_project_resource(
    project_id: int, data: dict = Body(...), conn=Depends(get_db_conn)
):
    """Reinstall a project resource (re-download current version)."""
    working_dir = _get_project_dir(project_id, conn)
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")

    dir_name, _manifest = validate_type(resource_type)
    version_file = Path(working_dir) / ".strawpot" / dir_name / name / ".version"
    if not version_file.is_file():
        raise HTTPException(
            404, f"Resource not found or has no version: {resource_type}/{name}"
        )
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise HTTPException(404, f"Empty version file for: {resource_type}/{name}")

    singular = singular_type(resource_type)
    return run_strawhub(
        "--root", working_dir, "install", singular, "-y", name,
        "--version", version, "--force",
    )
