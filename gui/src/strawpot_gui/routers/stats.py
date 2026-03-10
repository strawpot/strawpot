"""Project activity stats endpoint."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from strawpot_gui.db import get_db_conn

router = APIRouter(prefix="/api", tags=["stats"])

_VALID_PERIODS = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/projects/{project_id}/stats")
def get_project_stats(
    project_id: int,
    period: str = Query("30d"),
    conn=Depends(get_db_conn),
):
    if period not in _VALID_PERIODS:
        raise HTTPException(422, f"Invalid period: {period}. Must be one of {', '.join(_VALID_PERIODS)}")

    # Verify project exists
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")

    days = _VALID_PERIODS[period]
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    until = now.replace(hour=23, minute=59, second=59, microsecond=0)

    since_iso = since.isoformat()

    # Summary
    summary = conn.execute(
        """
        SELECT COUNT(*) AS total_runs,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
               CAST(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) AS INTEGER) AS avg_duration_ms
        FROM sessions
        WHERE project_id = ? AND started_at >= ? AND status IN ('completed','failed')
        """,
        (project_id, since_iso),
    ).fetchone()

    total_runs = summary["total_runs"] or 0
    completed = summary["completed"] or 0
    failed = summary["failed"] or 0
    avg_duration_ms = summary["avg_duration_ms"]
    success_rate = round(completed / total_runs * 100, 1) if total_runs > 0 else 0.0

    # Daily breakdown
    daily_rows = conn.execute(
        """
        SELECT DATE(started_at) AS date, COUNT(*) AS total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
               CAST(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) AS INTEGER) AS avg_duration_ms
        FROM sessions
        WHERE project_id = ? AND started_at >= ? AND status IN ('completed','failed')
        GROUP BY DATE(started_at) ORDER BY date ASC
        """,
        (project_id, since_iso),
    ).fetchall()

    daily_map = {
        row["date"]: {
            "date": row["date"],
            "total": row["total"],
            "completed": row["completed"],
            "failed": row["failed"],
            "avg_duration_ms": row["avg_duration_ms"],
        }
        for row in daily_rows
    }

    # Gap-fill
    daily = []
    current = since.date()
    today = now.date()
    while current <= today:
        date_str = current.isoformat()
        daily.append(
            daily_map.get(date_str, {
                "date": date_str,
                "total": 0,
                "completed": 0,
                "failed": 0,
                "avg_duration_ms": None,
            })
        )
        current += timedelta(days=1)

    return {
        "period": period,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "total_runs": total_runs,
        "completed": completed,
        "failed": failed,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration_ms,
        "daily": daily,
    }
