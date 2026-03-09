"""FastAPI application factory."""

import logging
import os
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from strawpot.config import get_strawpot_home

from strawpot_gui.db import init_db, sync_sessions

logger = logging.getLogger(__name__)
from strawpot_gui.routers import config, fs, health, projects, sessions, sse


def _auto_rebuild_frontend(dist_dir: Path) -> None:
    """Rebuild the frontend if source files are newer than dist."""
    frontend_dir = dist_dir.parent  # frontend/
    src_dir = frontend_dir / "src"
    if not src_dir.is_dir():
        return

    # Find newest source file mtime
    src_mtime = max(
        (f.stat().st_mtime for f in src_dir.rglob("*") if f.is_file()),
        default=0.0,
    )

    # Find dist mtime (use index.html as marker)
    dist_marker = dist_dir / "index.html"
    dist_mtime = dist_marker.stat().st_mtime if dist_marker.is_file() else 0.0

    if src_mtime <= dist_mtime:
        return

    logger.info("Frontend sources changed, rebuilding...")
    try:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Frontend rebuild complete")
    except FileNotFoundError:
        logger.debug("npm not found, skipping frontend rebuild")
    except subprocess.CalledProcessError as exc:
        logger.warning("Frontend rebuild failed: %s", exc.stderr[:500])


def create_app(db_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Override path to SQLite database.
                 Defaults to ~/.strawpot/gui.db.
    """
    if db_path is None:
        db_path = str(get_strawpot_home() / "gui.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(db_path)
        sync_sessions(db_path)
        yield

    app = FastAPI(title="StrawPot GUI", version="0.1.0", lifespan=lifespan)
    app.state.db_path = db_path

    # CORS — only enabled when developing the frontend with Vite dev server
    if os.environ.get("STRAWPOT_GUI_DEV"):
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(config.router)
    app.include_router(sessions.router)
    app.include_router(sse.router)
    app.include_router(fs.router)

    # Serve built frontend — check installed package path then dev path
    static_dir = Path(__file__).resolve().parent / "static"
    dev_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if not static_dir.is_dir():
        _auto_rebuild_frontend(dev_dir)
    frontend_dir = static_dir if static_dir.is_dir() else dev_dir
    if frontend_dir.is_dir():
        index_html = frontend_dir / "index.html"

        # SPA catch-all: serve index.html for non-API, non-file routes
        @app.get("/{full_path:path}")
        async def spa_fallback(request: Request, full_path: str):
            # Let static files (js, css, assets) be served directly
            file_path = frontend_dir / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(index_html))

    return app
