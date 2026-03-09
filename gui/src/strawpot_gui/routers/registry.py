"""Resource registry endpoints — list, detail, install, uninstall."""

import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from strawpot.agents.registry import parse_agent_md
from strawpot.config import get_strawpot_home
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
