"""Memory importance tracking — recall frequency and decay scoring."""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from strawpot.config import get_strawpot_home

log = logging.getLogger(__name__)

_STATS_FILENAME = "memory_stats.json"


@dataclass
class EntryStats:
    """Tracked statistics for a single memory entry."""

    recall_count: int = 0
    last_recalled: float = 0.0
    created: float = 0.0


def _stats_path(project_dir: str | None = None) -> Path:
    """Return the path to the memory stats file.

    Uses ``<project_dir>/.strawpot/memory_stats.json`` when a project
    directory is provided, otherwise falls back to the global
    ``~/.strawpot/memory_stats.json``.
    """
    if project_dir:
        return Path(project_dir) / ".strawpot" / _STATS_FILENAME
    return get_strawpot_home() / _STATS_FILENAME


def load_stats(project_dir: str | None = None) -> dict[str, EntryStats]:
    """Load importance stats from disk.

    Returns an empty dict if the file doesn't exist or is corrupt.
    """
    path = _stats_path(project_dir)
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Failed to load memory stats from %s", path, exc_info=True)
        return {}

    stats: dict[str, EntryStats] = {}
    for entry_id, data in raw.items():
        stats[entry_id] = EntryStats(
            recall_count=data.get("recall_count", 0),
            last_recalled=data.get("last_recalled", 0.0),
            created=data.get("created", 0.0),
        )
    return stats


def save_stats(
    stats: dict[str, EntryStats],
    project_dir: str | None = None,
) -> None:
    """Persist importance stats to disk."""
    path = _stats_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    raw = {
        entry_id: {
            "recall_count": s.recall_count,
            "last_recalled": s.last_recalled,
            "created": s.created,
        }
        for entry_id, s in stats.items()
    }
    try:
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except OSError:
        log.warning("Failed to save memory stats to %s", path, exc_info=True)


def record_recall(
    entry_ids: list[str],
    project_dir: str | None = None,
) -> None:
    """Increment recall counts for the given entry IDs.

    Loads stats, bumps counts, and writes back. If a given entry ID is
    not yet tracked, it is created with ``recall_count=1``.
    """
    if not entry_ids:
        return

    stats = load_stats(project_dir)
    now = time.time()

    for eid in entry_ids:
        if eid in stats:
            stats[eid].recall_count += 1
            stats[eid].last_recalled = now
        else:
            stats[eid] = EntryStats(
                recall_count=1,
                last_recalled=now,
                created=now,
            )

    save_stats(stats, project_dir)


def importance_score(entry: EntryStats, now: float | None = None) -> float:
    """Calculate importance for an entry using recall frequency and recency.

    Formula: ``recall_count * recency_weight``
    where ``recency_weight = 1.0 / (1 + days_since_last_recall / 30)``

    Returns 0.0 for entries that have never been recalled.
    """
    if entry.recall_count == 0 or entry.last_recalled == 0.0:
        return 0.0

    now = now or time.time()
    days_since = max(0.0, (now - entry.last_recalled) / 86400.0)
    recency_weight = 1.0 / (1.0 + days_since / 30.0)
    return entry.recall_count * recency_weight
