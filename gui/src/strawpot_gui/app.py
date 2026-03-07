"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from strawpot.config import get_strawpot_home

from strawpot_gui.db import init_db, sync_sessions
from strawpot_gui.routers import config, health, projects, sessions


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

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(config.router)
    app.include_router(sessions.router)

    return app
