"""Resource registry endpoints — list, detail, install, uninstall."""

import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from strawpot.agents.registry import (
    AgentSpec,
    _current_os,
    parse_agent_md,
    validate_agent,
)
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


def validate_type(resource_type: str) -> tuple[str, str]:
    """Return (dir_name, manifest) or raise 400."""
    entry = RESOURCE_TYPES.get(resource_type)
    if entry is None:
        raise HTTPException(
            400,
            f"Unknown resource type: {resource_type}. "
            f"Valid types: {', '.join(RESOURCE_TYPES)}",
        )
    return entry


def parse_manifest(manifest_path: Path, resource_type: str) -> tuple[dict, str]:
    """Parse a manifest file and return (frontmatter, body)."""
    if resource_type == "agents":
        return parse_agent_md(manifest_path)
    if resource_type == "memories":
        return parse_memory_md(manifest_path)
    # roles and skills use generic frontmatter parsing
    text = manifest_path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    return parsed.get("frontmatter", {}), parsed.get("body", "")


def read_version(resource_dir: Path, fm: dict) -> str | None:
    """Read version from .version file, falling back to frontmatter metadata."""
    version_file = resource_dir / ".version"
    if version_file.is_file():
        try:
            return version_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    metadata = fm.get("metadata", {})
    return metadata.get("version", fm.get("version")) or None


def scan_dir(
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
            fm, _body = parse_manifest(manifest_path, resource_type)
        except (ValueError, Exception):
            fm = {}
        items.append(
            {
                "name": fm.get("name", entry.name),
                "version": read_version(entry, fm),
                "description": fm.get("description", ""),
                "source": source,
                "path": str(entry),
            }
        )
    return items


@router.post("/update-all")
def update_all_resources():
    """Update all global resources to their latest versions via strawhub."""
    return run_strawhub("update", "--all", "--global", "-y")


@router.get("/{resource_type}")
def list_resources(resource_type: str):
    """List all installed resources of a given type."""
    dir_name, manifest = validate_type(resource_type)
    home = get_strawpot_home()
    return scan_dir(home, dir_name, manifest, resource_type, "global")


@router.get("/{resource_type}/{name}")
def get_resource(resource_type: str, name: str):
    """Get detail for a single installed resource."""
    dir_name, manifest = validate_type(resource_type)
    home = get_strawpot_home()

    resource_dir = home / dir_name / name
    manifest_path = resource_dir / manifest
    if not manifest_path.is_file():
        raise HTTPException(404, f"Resource not found: {resource_type}/{name}")

    fm, body = parse_manifest(manifest_path, resource_type)
    return {
        "name": fm.get("name", name),
        "version": read_version(resource_dir, fm),
        "description": fm.get("description", ""),
        "frontmatter": fm,
        "body": body,
        "source": "global",
        "path": str(resource_dir),
    }


def extract_saved_values(
    toml_data: dict, resource_type: str, name: str, params_schema: dict
) -> tuple[dict, dict]:
    """Extract saved env and param values from parsed TOML data."""
    env_values: dict[str, str] = {}
    params_values: dict = {}

    if resource_type == "roles":
        role_data = toml_data.get("roles", {}).get(name, {})
        if isinstance(role_data, dict):
            for key in params_schema:
                if key in role_data:
                    params_values[key] = role_data[key]
    elif resource_type == "skills":
        skill_data = toml_data.get("skills", {}).get(name, {})
        if isinstance(skill_data, dict):
            env_values = skill_data.get("env", {})
    elif resource_type == "agents":
        agent_data = toml_data.get("agents", {}).get(name, {})
        if isinstance(agent_data, dict):
            env_values = agent_data.get("env", {})
            for key in params_schema:
                if key in agent_data:
                    params_values[key] = agent_data[key]
    elif resource_type == "memories":
        mem_data = toml_data.get("memories", {}).get(name, {})
        if isinstance(mem_data, dict):
            env_values = mem_data.get("env", {})
        memory_cfg = toml_data.get("memory_config", {})
        for key in params_schema:
            if key in memory_cfg:
                params_values[key] = memory_cfg[key]

    return env_values, params_values


def coerce_param(value: object, param_type: str | None) -> object:
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
    dir_name, manifest = validate_type(resource_type)
    home = get_strawpot_home()

    resource_dir = home / dir_name / name
    manifest_path = resource_dir / manifest
    if not manifest_path.is_file():
        raise HTTPException(404, f"Resource not found: {resource_type}/{name}")

    fm, _ = parse_manifest(manifest_path, resource_type)
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
    env_values, params_values = extract_saved_values(
        toml_data, resource_type, name, params_schema
    )

    return {
        "env_schema": env_schema,
        "env_values": env_values,
        "params_schema": params_schema,
        "params_values": params_values,
    }


@router.get("/agents/{name}/validate")
def validate_agent_status(name: str):
    """Check if an agent's prerequisites are satisfied."""
    home = get_strawpot_home()
    agent_dir = home / "agents" / name
    manifest_path = agent_dir / "AGENT.md"
    if not manifest_path.is_file():
        raise HTTPException(404, f"Agent not found: {name}")

    fm, _ = parse_agent_md(manifest_path)
    strawpot_meta = fm.get("metadata", {}).get("strawpot", {})

    spec = AgentSpec(
        name=fm.get("name", name),
        version="0",
        wrapper_cmd=[],
        tools=strawpot_meta.get("tools", {}),
        env_schema=strawpot_meta.get("env", {}),
    )
    result = validate_agent(spec)

    bin_map = strawpot_meta.get("bin", {})
    os_key = _current_os()
    bin_name = bin_map.get(os_key)
    setup_command = f"{bin_name} setup" if bin_name else None
    setup_description = strawpot_meta.get("setup", {}).get("description")

    return {
        "tools_ok": len(result.missing_tools) == 0,
        "missing_tools": [
            {"name": t[0], "install_hint": t[1]} for t in result.missing_tools
        ],
        "env_ok": len(result.missing_env) == 0,
        "missing_env": result.missing_env,
        "setup_command": setup_command,
        "setup_description": setup_description,
    }


@router.put("/{resource_type}/{name}/config")
def put_resource_config(resource_type: str, name: str, data: dict = Body(...)):
    """Save env and param values for a resource."""
    dir_name, manifest = validate_type(resource_type)
    home = get_strawpot_home()
    manifest_path = home / dir_name / name / manifest
    if not manifest_path.is_file():
        raise HTTPException(404, f"Resource not found: {resource_type}/{name}")

    env_values = data.get("env_values")
    params_values = data.get("params_values")

    # Type-coerce params based on schema
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

    save_resource_config(None, resource_type, name, env_values, params_values)
    return {"ok": True}


def _strawhub_cmd() -> list[str] | None:
    """Locate the strawhub CLI, falling back to python -m for pipx installs."""
    path = shutil.which("strawhub")
    if path:
        return [path]
    try:
        subprocess.run(
            [sys.executable, "-m", "strawhub", "--version"],
            capture_output=True,
            check=True,
        )
        return [sys.executable, "-m", "strawhub"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run_strawhub(*args: str) -> dict:
    """Run a strawhub CLI command and return result."""
    cmd = _strawhub_cmd()
    if cmd is None:
        raise HTTPException(
            503,
            "strawhub CLI not found. Install it with: pip install strawhub",
        )
    result = subprocess.run(
        [*cmd, *args],
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
    return run_strawhub("install", singular, "-y", name, "--global")


# Built-in resources that cannot be uninstalled.
# IMPORTANT: Keep in sync with PROTECTED in frontend/src/pages/ResourceBrowser.tsx
# and frontend/src/components/ResourceDetailSheet.tsx — both must be updated together.
_PROTECTED_ROLES = {"imu", "ai-ceo", "ai-employee"}
_PROTECTED_SKILLS = {"denden", "strawpot-session-recap"}
_PROTECTED_AGENTS = {"strawpot-claude-code"}
_PROTECTED_MEMORIES = {"dial"}


@router.delete("/{resource_type}/{name}")
def uninstall_resource(resource_type: str, name: str):
    """Uninstall a resource via strawhub."""
    validate_type(resource_type)
    if resource_type == "roles" and name in _PROTECTED_ROLES:
        raise HTTPException(403, f"'{name}' is a built-in role and cannot be uninstalled.")
    if resource_type == "skills" and name in _PROTECTED_SKILLS:
        raise HTTPException(403, f"'{name}' is a built-in skill and cannot be uninstalled.")
    if resource_type == "agents" and name in _PROTECTED_AGENTS:
        raise HTTPException(403, f"'{name}' is a built-in agent and cannot be uninstalled.")
    if resource_type == "memories" and name in _PROTECTED_MEMORIES:
        raise HTTPException(403, f"'{name}' is a built-in memory provider and cannot be uninstalled.")
    singular = resource_type.rstrip("s") if resource_type != "memories" else "memory"
    return run_strawhub("uninstall", singular, name, "--global")


def singular_type(resource_type: str) -> str:
    return resource_type.rstrip("s") if resource_type != "memories" else "memory"


@router.post("/update")
def update_resource(data: dict = Body(...)):
    """Update a resource to its latest version via strawhub."""
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")
    singular = singular_type(resource_type)
    return run_strawhub("update", "-y", singular, name, "--global")


@router.post("/reinstall")
def reinstall_resource(data: dict = Body(...)):
    """Reinstall a resource (re-download the current version) via strawhub."""
    resource_type = data.get("type", "")
    name = data.get("name", "")
    if not resource_type or not name:
        raise HTTPException(400, "Both 'type' and 'name' are required")

    dir_name, _manifest = validate_type(resource_type)
    home = get_strawpot_home()
    version_file = home / dir_name / name / ".version"
    if not version_file.is_file():
        raise HTTPException(404, f"Resource not found or has no version: {resource_type}/{name}")
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise HTTPException(404, f"Empty version file for: {resource_type}/{name}")

    singular = singular_type(resource_type)
    return run_strawhub("install", singular, "-y", name, "--version", version, "--force", "--global")
