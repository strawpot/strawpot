"""Resource registry endpoints — list, detail, install, uninstall."""

import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from strawpot.agents.registry import parse_agent_md
from strawpot.config import _read_toml, get_strawpot_home, save_resource_config
from strawpot.context import parse_frontmatter
from strawpot.memory.registry import parse_memory_md

router = APIRouter(prefix="/api/registry", tags=["registry"])

# Maps URL resource_type to (directory_name, manifest_filename)
RESOURCE_TYPES: dict[str, tuple[str, str]] = {
    "roles": ("roles", "ROLE.md"),
    "skills": ("skills", "SKILL.md"),
    "agents": ("agents", "AGENT.md"),
    "memories": ("memories", "MEMORY.md"),
}


def _validate_type(resource_type: str) -> tuple[str, str]:
    """Return (dir_name, manifest) or raise 400."""
    entry = RESOURCE_TYPES.get(resource_type)
    if entry is None:
        raise HTTPException(
            400,
            f"Unknown resource type: {resource_type}. "
            f"Valid types: {', '.join(RESOURCE_TYPES)}",
        )
    return entry


def _parse_manifest(manifest_path: Path, resource_type: str) -> tuple[dict, str]:
    """Parse a manifest file and return (frontmatter, body)."""
    if resource_type == "agents":
        return parse_agent_md(manifest_path)
    if resource_type == "memories":
        return parse_memory_md(manifest_path)
    # roles and skills use generic frontmatter parsing
    text = manifest_path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("frontmatter", {}), parsed.get("body", "")


def _read_version(resource_dir: Path, fm: dict) -> str | None:
    """Read version from .version file, falling back to frontmatter metadata."""
    version_file = resource_dir / ".version"
    if version_file.is_file():
        try:
            return version_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    metadata = fm.get("metadata", {})
    return metadata.get("version", fm.get("version")) or None


def _scan_dir(
    base_dir: Path, dir_name: str, manifest: str, resource_type: str, source: str
) -> list[dict]:
    """Scan a directory for installed resources."""
    scan_path = base_dir / dir_name
    if not scan_path.is_dir():
        return []
    items = []
    for entry in sorted(scan_path.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        manifest_path = entry / manifest
        if not manifest_path.is_file():
            continue
        try:
            fm, _body = _parse_manifest(manifest_path, resource_type)
        except (ValueError, Exception):
            fm = {}
        items.append(
            {
                "name": fm.get("name", entry.name),
                "version": _read_version(entry, fm),
                "description": fm.get("description", ""),
                "source": source,
                "path": str(entry),
            }
        )
    return items


@router.get("/{resource_type}")
def list_resources(resource_type: str):
    """List all installed resources of a given type."""
    dir_name, manifest = _validate_type(resource_type)
    home = get_strawpot_home()
    return _scan_dir(home, dir_name, manifest, resource_type, "global")


@router.get("/{resource_type}/{name}")
def get_resource(resource_type: str, name: str):
    """Get detail for a single installed resource."""
    dir_name, manifest = _validate_type(resource_type)
    home = get_strawpot_home()

    resource_dir = home / dir_name / name
    manifest_path = resource_dir / manifest
    if not manifest_path.is_file():
        raise HTTPException(404, f"Resource not found: {resource_type}/{name}")

    fm, body = _parse_manifest(manifest_path, resource_type)
    return {
        "name": fm.get("name", name),
        "version": _read_version(resource_dir, fm),
        "description": fm.get("description", ""),
        "frontmatter": fm,
        "body": body,
        "source": "global",
        "path": str(resource_dir),
    }


def _extract_saved_values(
    toml_data: dict, resource_type: str, name: str, params_schema: dict
) -> tuple[dict, dict]:
    """Extract saved env and param values from parsed TOML data."""
    env_values: dict[str, str] = {}
    params_values: dict = {}

    if resource_type == "roles":
        role_data = toml_data.get("roles", {}).get(name, {})
        for key in params_schema:
            if key in role_data:
                params_values[key] = role_data[key]
    elif resource_type == "skills":
        env_values = toml_data.get("skills", {}).get(name, {}).get("env", {})
    elif resource_type == "agents":
        agent_data = toml_data.get("agents", {}).get(name, {})
        env_values = agent_data.get("env", {})
        for key in params_schema:
            if key in agent_data:
                params_values[key] = agent_data[key]
    elif resource_type == "memories":
        env_values = toml_data.get("memories", {}).get(name, {}).get("env", {})
        memory_cfg = toml_data.get("memory_config", {})
        for key in params_schema:
            if key in memory_cfg:
                params_values[key] = memory_cfg[key]

    return env_values, params_values


def _coerce_param(value: object, param_type: str | None) -> object:
    """Coerce a param value to the correct Python type for TOML."""
    if param_type == "int":
        return int(value)  # type: ignore[arg-type]
    if param_type == "float":
        return float(value)  # type: ignore[arg-type]
    if param_type == "boolean":
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    return value


@router.get("/{resource_type}/{name}/config")
def get_resource_config(resource_type: str, name: str):
    """Get env/params schema from manifest and saved values from TOML."""
    dir_name, manifest = _validate_type(resource_type)
    home = get_strawpot_home()

    resource_dir = home / dir_name / name
    manifest_path = resource_dir / manifest
    if not manifest_path.is_file():
        raise HTTPException(404, f"Resource not found: {resource_type}/{name}")

    fm, _ = _parse_manifest(manifest_path, resource_type)
    strawpot_meta = fm.get("metadata", {}).get("strawpot", {})

    env_schema = strawpot_meta.get("env", {})
    params_schema = strawpot_meta.get("params", {})

    # Roles expose default_agent as a configurable parameter
    if resource_type == "roles":
        manifest_default = strawpot_meta.get("default_agent")
        params_schema = {
            "default_agent": {
                "type": "string",
                "default": manifest_default,
                "description": "Agent to use when running this role",
            },
        }

    toml_data = _read_toml(home / "strawpot.toml")
    env_values, params_values = _extract_saved_values(
        toml_data, resource_type, name, params_schema
    )

    return {
        "env_schema": env_schema,
        "env_values": env_values,
        "params_schema": params_schema,
        "params_values": params_values,
    }


@router.put("/{resource_type}/{name}/config")
def put_resource_config(resource_type: str, name: str, data: dict = Body(...)):
    """Save env and param values for a resource."""
    dir_name, manifest = _validate_type(resource_type)
    home = get_strawpot_home()
    manifest_path = home / dir_name / name / manifest
    if not manifest_path.is_file():
        raise HTTPException(404, f"Resource not found: {resource_type}/{name}")

    env_values = data.get("env_values")
    params_values = data.get("params_values")

    # Type-coerce params based on schema
    if params_values:
        fm, _ = _parse_manifest(manifest_path, resource_type)
        params_schema = fm.get("metadata", {}).get("strawpot", {}).get("params", {})
        coerced = {}
        for k, v in params_values.items():
            schema = params_schema.get(k, {})
            try:
                coerced[k] = _coerce_param(v, schema.get("type"))
            except (ValueError, TypeError):
                coerced[k] = v
        params_values = coerced

    save_resource_config(None, resource_type, name, env_values, params_values)
    return {"ok": True}


def _run_strawhub(*args: str) -> dict:
    """Run a strawhub CLI command and return result."""
    cmd = shutil.which("strawhub")
    if cmd is None:
        raise HTTPException(
            503,
            "strawhub CLI not found on PATH. Install it with: pip install strawhub",
        )
    result = subprocess.run(
        [cmd, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@router.post("/install")
def install_resource(data: dict = Body(...)):
    """Install a resource via strawhub."""
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")
    # strawhub uses singular type names for install
    singular = resource_type.rstrip("s") if resource_type != "memories" else "memory"
    return _run_strawhub("install", "-y", singular, name, "--global")


@router.delete("/{resource_type}/{name}")
def uninstall_resource(resource_type: str, name: str):
    """Uninstall a resource via strawhub."""
    _validate_type(resource_type)
    singular = resource_type.rstrip("s") if resource_type != "memories" else "memory"
    return _run_strawhub("uninstall", singular, name, "--global")


def _singular_type(resource_type: str) -> str:
    return resource_type.rstrip("s") if resource_type != "memories" else "memory"


@router.post("/update")
def update_resource(data: dict = Body(...)):
    """Update a resource to its latest version via strawhub."""
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")
    singular = _singular_type(resource_type)
    return _run_strawhub("update", singular, name, "--global")


@router.post("/reinstall")
def reinstall_resource(data: dict = Body(...)):
    """Reinstall a resource (re-download the current version) via strawhub."""
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")

    dir_name, _manifest = _validate_type(resource_type)
    home = get_strawpot_home()
    version_file = home / dir_name / name / ".version"
    if not version_file.is_file():
        raise HTTPException(404, f"Resource not found or has no version: {resource_type}/{name}")
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise HTTPException(404, f"Empty version file for: {resource_type}/{name}")

    singular = _singular_type(resource_type)
    return _run_strawhub("install", "-y", singular, name, "--version", version, "--force", "--global")
