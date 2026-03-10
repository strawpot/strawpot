"""Cron-based scheduled task runner.

Runs as an asyncio background task inside the FastAPI event loop.
Checks for due schedules every 30 seconds and fires sessions via
the shared launch_session_subprocess() function.
"""

import asyncio
import logging
from datetime import datetime, timezone

from croniter import croniter

from strawpot_gui.db import get_db

logger = logging.getLogger(__name__)


class Scheduler:
    """Manages scheduled task execution."""

    def __init__(self, db_path: str, launch_fn) -> None:
        self._db_path = db_path
        self._launch_fn = launch_fn
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the scheduler background loop."""
        self._init_next_run_times()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler background loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Scheduler stopped")

    def _init_next_run_times(self) -> None:
        """Compute next_run_at for enabled schedules that don't have one."""
        now = datetime.now(timezone.utc)
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, cron_expr FROM scheduled_tasks "
                "WHERE enabled = 1 AND next_run_at IS NULL"
            ).fetchall()
            for row in rows:
                next_run = _next_run(row["cron_expr"], now)
                if next_run:
                    conn.execute(
                        "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
                        (next_run, row["id"]),
                    )

    async def _run_loop(self) -> None:
        """Main loop: check for due schedules every 30 seconds."""
        while True:
            try:
                self._check_and_fire()
            except Exception:
                logger.exception("Scheduler tick error")
            await asyncio.sleep(30)

    def _check_and_fire(self) -> None:
        """Check all enabled schedules and fire any that are due."""
        now = datetime.now(timezone.utc)
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks "
                "WHERE enabled = 1 AND next_run_at IS NOT NULL"
            ).fetchall()
            for row in rows:
                next_run_str = row["next_run_at"]
                try:
                    next_run = datetime.fromisoformat(next_run_str)
                except (ValueError, TypeError):
                    continue
                if next_run <= now:
                    self._fire(conn, dict(row), now)

    def _fire(self, conn, schedule: dict, now: datetime) -> None:
        """Fire a single scheduled task."""
        schedule_id = schedule["id"]
        name = schedule["name"]
        try:
            run_id = self._launch_fn(
                conn,
                schedule["project_id"],
                schedule["task"],
                role=schedule["role"],
                system_prompt=schedule["system_prompt"],
                schedule_id=schedule_id,
            )
            next_run = _next_run(schedule["cron_expr"], now)
            conn.execute(
                "UPDATE scheduled_tasks "
                "SET last_run_at = ?, next_run_at = ?, last_error = NULL "
                "WHERE id = ?",
                (now.isoformat(), next_run, schedule_id),
            )
            logger.info(
                "Schedule '%s' fired session %s, next run: %s",
                name, run_id, next_run,
            )
        except Exception as exc:
            conn.execute(
                "UPDATE scheduled_tasks SET last_error = ? WHERE id = ?",
                (str(exc), schedule_id),
            )
            logger.warning("Schedule '%s' failed: %s", name, exc)


def _next_run(cron_expr: str, after: datetime) -> str | None:
    """Compute the next run time for a cron expression."""
    try:
        return croniter(cron_expr, after).get_next(datetime).isoformat()
    except (ValueError, KeyError):
        return None
