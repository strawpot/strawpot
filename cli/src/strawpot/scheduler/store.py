"""Schedule storage — JSON-based CRUD for scheduled workflows."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter

log = logging.getLogger(__name__)

_SCHEDULE_FILE = "schedules.json"


@dataclass
class Schedule:
    """A stored scheduled workflow."""

    schedule_id: str = ""
    name: str = ""
    description: str = ""
    cron: str = ""
    task: str = ""
    role: str = ""
    created_at: str = ""
    last_run: str = ""
    last_status: str = ""

    def next_run(self) -> str:
        """Compute the next run time from the cron expression."""
        try:
            base = datetime.now(timezone.utc)
            return croniter(self.cron, base).get_next(datetime).isoformat()
        except (ValueError, KeyError):
            return ""


class ScheduleStore:
    """JSON file-backed schedule storage.

    Stores schedules in ``<project_dir>/.strawpot/schedules.json``.
    """

    def __init__(self, project_dir: str | None = None):
        from strawpot.memory.standalone import detect_project_dir

        proj = project_dir or detect_project_dir()
        self._path = Path(proj) / ".strawpot" / _SCHEDULE_FILE

    def _read(self) -> list[dict]:
        if not self._path.is_file():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, schedules: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(schedules, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def create(
        self,
        *,
        name: str,
        description: str = "",
        cron: str,
        task: str,
        role: str = "",
    ) -> Schedule:
        """Create a new schedule.

        Raises:
            ValueError: If the cron expression is invalid.
        """
        if not croniter.is_valid(cron):
            raise ValueError(f"Invalid cron expression: {cron!r}")

        schedule = Schedule(
            schedule_id=f"sched_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            cron=cron,
            task=task,
            role=role,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        schedules = self._read()
        schedules.append(asdict(schedule))
        self._write(schedules)
        return schedule

    def list_schedules(self) -> list[Schedule]:
        """List all stored schedules."""
        return [Schedule(**s) for s in self._read()]

    def get(self, schedule_id: str) -> Schedule | None:
        """Get a single schedule by ID."""
        for s in self._read():
            if s.get("schedule_id") == schedule_id:
                return Schedule(**s)
        return None

    def delete(self, schedule_id: str) -> bool:
        """Delete a schedule by ID. Returns True if found and deleted."""
        schedules = self._read()
        remaining = [s for s in schedules if s.get("schedule_id") != schedule_id]
        if len(remaining) < len(schedules):
            self._write(remaining)
            return True
        return False

    def update_status(self, schedule_id: str, status: str) -> None:
        """Update the last_run and last_status of a schedule."""
        schedules = self._read()
        for s in schedules:
            if s.get("schedule_id") == schedule_id:
                s["last_run"] = datetime.now(timezone.utc).isoformat()
                s["last_status"] = status
                break
        self._write(schedules)
