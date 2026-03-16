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
        """Compute next_run_at for enabled recurring schedules that don't have one.

        One-time schedules already have next_run_at set from run_at at creation,
        so they are excluded here.
        """
        now = datetime.now(timezone.utc)
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, cron_expr FROM scheduled_tasks "
                "WHERE enabled = 1 AND next_run_at IS NULL "
                "AND schedule_type = 'recurring'"
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
                    next_dt = datetime.fromisoformat(next_run_str)
                except (ValueError, TypeError):
                    continue
                if next_dt > now:
                    continue
                if row["skip_if_running"] and self._has_running_session(
                    conn, row["id"]
                ):
                    logger.info(
                        "Schedule '%s' skipped: session already running",
                        row["name"],
                    )
                    # For recurring: advance to next cron tick.
                    # For one-time: leave next_run_at unchanged to retry next tick.
                    if row["schedule_type"] != "one_time":
                        next_run = _next_run(row["cron_expr"], now)
                        conn.execute(
                            "UPDATE scheduled_tasks SET next_run_at = ? "
                            "WHERE id = ?",
                            (next_run, row["id"]),
                        )
                    continue
                self._fire(conn, dict(row), now)

    @staticmethod
    def _has_running_session(conn, schedule_id: int) -> bool:
        """Return True if a session spawned by this schedule is still active."""
        row = conn.execute(
            "SELECT 1 FROM sessions "
            "WHERE schedule_id = ? AND status IN ('starting', 'running') "
            "LIMIT 1",
            (schedule_id,),
        ).fetchone()
        return row is not None

    def _fire(self, conn, schedule: dict, now: datetime) -> None:
        """Fire a single scheduled task."""
        schedule_id = schedule["id"]
        name = schedule["name"]
        project_id = schedule["project_id"]

        # #20 — enforce imu role for project 0 (strawpot-internal)
        role = schedule["role"] or ("imu" if project_id == 0 else None)

        task = schedule["task"]
        conversation_id = schedule.get("conversation_id")

        # #19 — conversation targeting: build context from prior turns
        kwargs: dict = {}
        if conversation_id:
            from strawpot_gui.routers.conversations import (
                _build_conversation_context,
                _write_conversation_history,
            )

            conv = conn.execute(
                "SELECT id, project_id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conv:
                project_row = conn.execute(
                    "SELECT working_dir FROM projects WHERE id = ?",
                    (project_id,),
                ).fetchone()
                hist_path = None
                if project_row and project_row["working_dir"]:
                    hist_path = _write_conversation_history(
                        conn, conversation_id, project_row["working_dir"]
                    )
                context = _build_conversation_context(
                    conn, conversation_id, history_path=hist_path
                )
                if context:
                    kwargs["user_task"] = task
                    task = f"{context}\n\n---\n\n{task}"
                kwargs["conversation_id"] = conversation_id

        try:
            run_id = self._launch_fn(
                conn,
                project_id,
                task,
                role=role,
                system_prompt=schedule["system_prompt"],
                schedule_id=schedule_id,
                **kwargs,
            )
            if schedule.get("schedule_type") == "one_time":
                # One-time: auto-disable after firing
                conn.execute(
                    "UPDATE scheduled_tasks "
                    "SET last_run_at = ?, next_run_at = NULL, "
                    "    enabled = 0, last_error = NULL "
                    "WHERE id = ?",
                    (now.isoformat(), schedule_id),
                )
                next_run = None
            else:
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
