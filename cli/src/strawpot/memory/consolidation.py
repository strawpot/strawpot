"""Memory consolidation — merge duplicates, archive stale entries."""

import datetime
import logging
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from strawpot.memory.importance import (
    EntryStats,
    importance_score,
    load_stats,
    save_stats,
)
from strawpot_memory.memory_protocol import ListEntry, MemoryProvider

log = logging.getLogger(__name__)

# Entries sharing this many keywords are grouped together.
_MIN_KEYWORD_OVERLAP = 2

# Content similarity threshold for near-duplicate detection.
_DUPLICATE_THRESHOLD = 0.80

# Groups need at least this many entries to trigger consolidation.
_MIN_GROUP_SIZE = 3

# Entries below this importance with age > _ARCHIVE_AGE_DAYS are archived.
_ARCHIVE_IMPORTANCE_THRESHOLD = 0.1
_ARCHIVE_AGE_DAYS = 30


@dataclass
class ConsolidationAction:
    """A single consolidation action for auditability."""

    action: str  # "delete_duplicate" | "archive_stale"
    entry_id: str
    reason: str
    succeeded: bool = True


@dataclass
class ConsolidationReport:
    """Summary of a consolidation run."""

    actions: list[ConsolidationAction] = field(default_factory=list)
    groups_found: int = 0
    total_entries_scanned: int = 0

    @property
    def duplicates_removed(self) -> int:
        return sum(
            1 for a in self.actions
            if a.action == "delete_duplicate" and a.succeeded
        )

    @property
    def entries_archived(self) -> int:
        return sum(
            1 for a in self.actions
            if a.action == "archive_stale" and a.succeeded
        )


def _content_similarity(a: str, b: str) -> float:
    """Return a similarity ratio between two strings (0.0–1.0)."""
    return SequenceMatcher(None, a, b).ratio()


def _keyword_overlap(a: list[str], b: list[str]) -> int:
    """Return the number of shared keywords between two entries."""
    return len(set(a) & set(b))


def _group_by_keywords(
    entries: list[ListEntry],
) -> list[list[ListEntry]]:
    """Group entries by keyword overlap (≥ _MIN_KEYWORD_OVERLAP shared).

    Uses a simple union-find approach: for each pair of entries that
    share enough keywords, merge them into the same group.
    """
    n = len(entries)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(n):
        for j in range(i + 1, n):
            if _keyword_overlap(entries[i].keywords, entries[j].keywords) >= _MIN_KEYWORD_OVERLAP:
                union(i, j)

    groups: dict[int, list[ListEntry]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(entries[i])

    return list(groups.values())


def _find_duplicates(
    group: list[ListEntry],
) -> list[tuple[ListEntry, ListEntry]]:
    """Find near-duplicate pairs within a group.

    Returns pairs ``(to_delete, to_keep)`` where ``to_keep`` is the
    entry with the later timestamp.
    """
    duplicates: list[tuple[ListEntry, ListEntry]] = []
    seen_deleted: set[str] = set()

    # Sort by timestamp descending so the newest entry is checked first.
    sorted_group = sorted(group, key=lambda e: e.ts or "", reverse=True)

    for i, a in enumerate(sorted_group):
        if a.entry_id in seen_deleted:
            continue
        for b in sorted_group[i + 1 :]:
            if b.entry_id in seen_deleted:
                continue
            if _content_similarity(a.content, b.content) >= _DUPLICATE_THRESHOLD:
                # a is newer (sorted desc), keep a, delete b
                duplicates.append((b, a))
                seen_deleted.add(b.entry_id)

    return duplicates


def consolidate(
    provider: MemoryProvider,
    *,
    scope: str = "",
    project_dir: str | None = None,
    dry_run: bool = False,
) -> ConsolidationReport:
    """Run memory consolidation: deduplicate and archive stale entries.

    Args:
        provider: Memory provider to consolidate.
        scope: Limit to ``"project"`` or ``"global"``. Empty for all.
        project_dir: Project directory for importance stats path.
        dry_run: If True, report what would happen without modifying data.

    Returns:
        A ConsolidationReport detailing all actions taken (or planned).
    """
    report = ConsolidationReport()

    # 1. List all entries for the given scope
    result = provider.list_entries(scope=scope, limit=10000)
    entries = result.entries
    report.total_entries_scanned = len(entries)

    if not entries:
        return report

    # 2. Group by keyword overlap
    groups = _group_by_keywords(entries)
    qualifying_groups = [g for g in groups if len(g) >= _MIN_GROUP_SIZE]
    report.groups_found = len(qualifying_groups)

    # 3. Deduplicate within qualifying groups
    deleted_ids: set[str] = set()
    for group in qualifying_groups:
        for to_delete, to_keep in _find_duplicates(group):
            action = ConsolidationAction(
                action="delete_duplicate",
                entry_id=to_delete.entry_id,
                reason=(
                    f"Near-duplicate of {to_keep.entry_id} "
                    f"(similarity >= {_DUPLICATE_THRESHOLD})"
                ),
            )

            if not dry_run:
                try:
                    provider.forget(entry_id=to_delete.entry_id)
                    deleted_ids.add(to_delete.entry_id)
                    # Transfer graph relations from deleted entry to kept entry
                    _merge_graph_relations(
                        to_delete.entry_id, to_keep.entry_id, project_dir
                    )
                except Exception:
                    action.succeeded = False
                    log.warning(
                        "Failed to delete duplicate %s",
                        to_delete.entry_id,
                        exc_info=True,
                    )

            report.actions.append(action)

    # 4. Archive stale entries based on importance decay
    stats = load_stats(project_dir)
    now = time.time()
    stats_modified = False

    for entry in entries:
        # Skip entries already deleted in step 3
        if entry.entry_id in deleted_ids:
            continue

        entry_stats = stats.get(entry.entry_id)
        if entry_stats is None:
            # No stats = never recalled; use entry timestamp as creation time.
            created_ts = _parse_ts(entry.ts) if entry.ts else 0.0
            if created_ts == 0.0:
                continue
            age_days = (now - created_ts) / 86400.0
            if age_days < _ARCHIVE_AGE_DAYS:
                continue
            # Never recalled + old enough → archive candidate
            score = 0.0
        else:
            score = importance_score(entry_stats, now)
            created_ts = entry_stats.created or (_parse_ts(entry.ts) if entry.ts else 0.0)
            if created_ts == 0.0:
                continue
            age_days = (now - created_ts) / 86400.0

        if score < _ARCHIVE_IMPORTANCE_THRESHOLD and age_days >= _ARCHIVE_AGE_DAYS:
            action = ConsolidationAction(
                action="archive_stale",
                entry_id=entry.entry_id,
                reason=(
                    f"Importance {score:.3f} < {_ARCHIVE_IMPORTANCE_THRESHOLD}, "
                    f"age {age_days:.0f} days"
                ),
            )

            if not dry_run:
                ok = _archive_entry(provider, entry)
                if ok:
                    stats.pop(entry.entry_id, None)
                    stats_modified = True
                    _remove_graph_entry(entry.entry_id, project_dir)
                else:
                    action.succeeded = False

            report.actions.append(action)

    # Save stats once after all archival operations
    if stats_modified:
        save_stats(stats, project_dir)

    return report


def _parse_ts(ts_str: str) -> float:
    """Parse an ISO-ish timestamp string to epoch seconds.

    Returns 0.0 on failure.
    """
    try:
        dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _merge_graph_relations(
    old_entry_id: str, new_entry_id: str, project_dir: str | None
) -> None:
    """Transfer graph relations from a deleted entry to its replacement.

    Best-effort — failures are logged but don't block consolidation.
    """
    try:
        from strawpot.memory.graph import merge_relations

        merge_relations(old_entry_id, new_entry_id, project_dir)
    except Exception:
        log.debug(
            "Failed to merge graph relations %s -> %s",
            old_entry_id, new_entry_id,
            exc_info=True,
        )


def _remove_graph_entry(entry_id: str, project_dir: str | None) -> None:
    """Remove all graph relations for an archived entry.

    Best-effort — failures are logged but don't block consolidation.
    """
    try:
        from strawpot.memory.graph import remove_entry

        remove_entry(entry_id, project_dir)
    except Exception:
        log.debug(
            "Failed to remove graph relations for %s",
            entry_id, exc_info=True,
        )


def _archive_entry(
    provider: MemoryProvider,
    entry: ListEntry,
) -> bool:
    """Archive a stale entry: store in archive, then forget original.

    Archived entries are remembered with an ``archived`` keyword so they
    can still be found if needed, then the original is deleted.

    Returns True if both operations succeeded, False otherwise.
    """
    try:
        provider.remember(
            session_id="consolidation",
            agent_id="consolidation-job",
            role="system",
            content=f"[ARCHIVED] {entry.content}",
            keywords=[*(entry.keywords or []), "archived"],
            scope=entry.scope or "project",
        )
    except Exception:
        log.warning(
            "Failed to create archive copy of %s", entry.entry_id,
            exc_info=True,
        )
        return False

    try:
        provider.forget(entry_id=entry.entry_id)
    except Exception:
        log.warning(
            "Archived copy created but failed to delete original %s — "
            "manual cleanup may be needed",
            entry.entry_id,
            exc_info=True,
        )
        return False

    return True
