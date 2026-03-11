"""Filesystem browsing endpoints for directory selection."""

import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["fs"])


@router.get("/fs/browse")
def browse(path: str | None = Query(None)):
    """List subdirectories at the given path (defaults to home directory)."""
    target = Path(path).resolve() if path else Path.home()

    if not target.exists() or not target.is_dir():
        raise HTTPException(400, f"Not a valid directory: {target}")

    parent = str(target.parent) if target.parent != target else None

    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: e.name.lower()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            entries.append({"name": entry.name, "path": str(entry)})
    except PermissionError:
        pass

    return {"path": str(target), "parent": parent, "entries": entries}


class MkdirBody(BaseModel):
    path: str
    name: str


@router.post("/fs/mkdir")
def mkdir(body: MkdirBody):
    """Create a new subdirectory inside the given path."""
    parent = Path(body.path).resolve()
    if not parent.is_dir():
        raise HTTPException(400, f"Parent is not a valid directory: {parent}")

    name = body.name.strip()
    if not name or "/" in name or name.startswith("."):
        raise HTTPException(400, "Invalid folder name")

    target = parent / name
    if target.exists():
        raise HTTPException(409, f"Already exists: {target}")

    try:
        target.mkdir()
    except PermissionError:
        raise HTTPException(403, "Permission denied")

    return {"path": str(target)}


@router.get("/fs/git-check")
def git_check(path: str = Query(...)):
    """Check if a directory is inside a git repository."""
    target = Path(path).resolve()
    if not target.is_dir():
        raise HTTPException(400, f"Not a valid directory: {target}")

    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    return {"is_git": result.returncode == 0}


class GitInitBody(BaseModel):
    path: str


@router.post("/fs/git-init")
def git_init(body: GitInitBody):
    """Initialize a git repository in the given directory."""
    target = Path(body.path).resolve()
    if not target.is_dir():
        raise HTTPException(400, f"Not a valid directory: {target}")

    result = subprocess.run(
        ["git", "init"],
        cwd=str(target),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(500, f"git init failed: {result.stderr.strip()}")

    return {"ok": True}
