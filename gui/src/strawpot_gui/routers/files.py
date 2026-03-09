"""Project file upload, listing, and deletion endpoints."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api", tags=["files"])


def _get_working_dir(project_id: int, conn) -> str:
    """Look up project working_dir or raise 404."""
    row = conn.execute(
        "SELECT working_dir FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return row["working_dir"]


def _files_dir(working_dir: str) -> Path:
    return Path(working_dir) / ".strawpot" / "files"


def _file_entry(files_dir: Path, file_path: Path) -> dict:
    stat = file_path.stat()
    rel = file_path.relative_to(files_dir)
    return {
        "name": file_path.name,
        "path": str(rel),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    }


@router.get("/projects/{project_id}/files")
def list_files(project_id: int, conn=Depends(get_db_conn)):
    """List all files under <project>/.strawpot/files/."""
    working_dir = _get_working_dir(project_id, conn)
    fdir = _files_dir(working_dir)
    if not fdir.is_dir():
        return []
    entries = []
    for file_path in sorted(fdir.rglob("*")):
        if file_path.is_file():
            entries.append(_file_entry(fdir, file_path))
    return entries


@router.post("/projects/{project_id}/files")
async def upload_files(
    project_id: int,
    files: list[UploadFile],
    conn=Depends(get_db_conn),
):
    """Upload one or more files to <project>/.strawpot/files/."""
    working_dir = _get_working_dir(project_id, conn)
    fdir = _files_dir(working_dir).resolve()
    fdir.mkdir(parents=True, exist_ok=True)

    created = []
    for upload in files:
        if not upload.filename:
            continue
        # Sanitize: reject path traversal and absolute paths
        name = upload.filename.replace("\\", "/")
        if ".." in name.split("/") or name.startswith("/"):
            raise HTTPException(400, f"Invalid filename: {upload.filename}")

        target = (fdir / name).resolve()
        if not target.is_relative_to(fdir):
            raise HTTPException(400, f"Path escapes files directory: {upload.filename}")

        target.parent.mkdir(parents=True, exist_ok=True)
        content = await upload.read()
        target.write_bytes(content)
        created.append(_file_entry(fdir, target))

    return JSONResponse(content=created, status_code=201)


@router.delete("/projects/{project_id}/files/{file_path:path}")
def delete_file(project_id: int, file_path: str, conn=Depends(get_db_conn)):
    """Delete a file from <project>/.strawpot/files/."""
    working_dir = _get_working_dir(project_id, conn)
    fdir = _files_dir(working_dir).resolve()

    target = (fdir / file_path).resolve()
    if not target.is_relative_to(fdir):
        raise HTTPException(400, "Path escapes files directory")
    if not target.is_file():
        raise HTTPException(404, "File not found")

    target.unlink()

    # Clean up empty parent directories up to files_dir
    parent = target.parent
    while parent != fdir:
        try:
            if not any(parent.iterdir()):
                parent.rmdir()
            else:
                break
        except OSError:
            break
        parent = parent.parent

    return {"ok": True}
