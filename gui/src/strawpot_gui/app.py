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

from strawpot.config import ensure_global_config, get_strawpot_home

from strawpot_gui.db import ensure_imu_project, init_db, sync_sessions
from strawpot_gui.event_bus import event_bus
from strawpot_gui.scheduler import Scheduler

logger = logging.getLogger(__name__)
from strawpot_gui.routers import config, conversations, files, fs, health, imu, logs, project_resources, projects, registry, schedules, sessions, sse, stats, ws


def _ensure_imu_role() -> None:
    """Install the imu role globally at startup if not already present."""
    imu_role_path = get_strawpot_home() / "roles" / "imu" / "ROLE.md"
    if not imu_role_path.exists():
        logger.info("imu role not found, installing...")
        result = subprocess.run(
            ["strawhub", "install", "role", "imu", "--global", "-y"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("imu role installed successfully")
        else:
            logger.warning("Failed to install imu role: %s", result.stderr[:200])


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
        ensure_global_config()
        init_db(db_path)
        ensure_imu_project(db_path)
        _ensure_imu_role()
        from strawpot_gui.db import mark_orphaned_sessions_stopped
        mark_orphaned_sessions_stopped(db_path)
        sync_sessions(db_path)
        from strawpot_gui.routers.sessions import launch_session_subprocess
        scheduler = Scheduler(db_path, launch_fn=launch_session_subprocess)
        app.state.scheduler = scheduler
        await scheduler.start()
        yield
        await scheduler.stop()

    app = FastAPI(title="StrawPot GUI", version="0.1.0", lifespan=lifespan)
    app.state.db_path = db_path
    app.state.event_bus = event_bus

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
    app.include_router(imu.router)
    app.include_router(projects.router)
    app.include_router(conversations.router)
    app.include_router(config.router)
    app.include_router(files.router)
    app.include_router(sessions.router)
    app.include_router(sse.router)
    app.include_router(ws.router)
    app.include_router(logs.router)
    app.include_router(fs.router)
    app.include_router(registry.router)
    app.include_router(project_resources.router)
    app.include_router(schedules.router)
    app.include_router(stats.router)

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
