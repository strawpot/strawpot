"""Tests for memory consolidation."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from strawpot.memory.consolidation import (
    ConsolidationAction,
    _content_similarity,
    _find_duplicates,
    _group_by_keywords,
    _parse_ts,
    consolidate,
)
from strawpot.memory.importance import EntryStats, save_stats
from strawpot_memory.memory_protocol import (
    ForgetResult,
    ListEntry,
    ListResult,
    RememberResult,
)


class TestContentSimilarity:
    def test_identical_strings(self):
        assert _content_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _content_similarity("abc", "xyz") < 0.5

    def test_partial_overlap(self):
        sim = _content_similarity(
            "The quick brown fox", "The quick brown dog"
        )
        assert 0.7 < sim < 1.0


class TestGroupByKeywords:
    def _entry(self, eid, keywords):
        return ListEntry(
            entry_id=eid,
            content=f"content {eid}",
            keywords=keywords,
            scope="project",
            ts="2026-01-01T00:00:00Z",
        )

    def test_groups_by_overlap(self):
        entries = [
            self._entry("a", ["kw1", "kw2", "kw3"]),
            self._entry("b", ["kw1", "kw2", "kw4"]),
            self._entry("c", ["kw5", "kw6"]),
        ]
        groups = _group_by_keywords(entries)
        # a and b share kw1+kw2, c is separate
        assert len(groups) == 2
        group_ids = [sorted(e.entry_id for e in g) for g in groups]
        assert ["a", "b"] in group_ids
        assert ["c"] in group_ids

    def test_no_overlap(self):
        entries = [
            self._entry("a", ["kw1"]),
            self._entry("b", ["kw2"]),
        ]
        groups = _group_by_keywords(entries)
        assert len(groups) == 2

    def test_empty_keywords(self):
        """Entries with empty keyword lists remain ungrouped."""
        entries = [
            self._entry("a", []),
            self._entry("b", []),
            self._entry("c", ["kw1"]),
        ]
        groups = _group_by_keywords(entries)
        # No pair can share >= 2 keywords, so each is its own group
        assert len(groups) == 3

    def test_empty_input(self):
        """Empty entry list returns empty groups."""
        assert _group_by_keywords([]) == []

    def test_transitive_grouping(self):
        entries = [
            self._entry("a", ["kw1", "kw2", "kw3"]),
            self._entry("b", ["kw2", "kw3", "kw4"]),
            self._entry("c", ["kw3", "kw4", "kw5"]),
        ]
        groups = _group_by_keywords(entries)
        # a-b share kw2+kw3, b-c share kw3+kw4 → all in one group
        assert len(groups) == 1
        assert len(groups[0]) == 3


class TestFindDuplicates:
    def _entry(self, eid, content, ts="2026-01-01T00:00:00Z"):
        return ListEntry(
            entry_id=eid,
            content=content,
            keywords=["kw1", "kw2"],
            scope="project",
            ts=ts,
        )

    def test_finds_near_duplicates(self):
        group = [
            self._entry("old", "The quick brown fox jumps over the lazy dog",
                         ts="2026-01-01T00:00:00Z"),
            self._entry("new", "The quick brown fox jumps over the lazy cat",
                         ts="2026-01-02T00:00:00Z"),
        ]
        dupes = _find_duplicates(group)
        assert len(dupes) == 1
        to_delete, to_keep = dupes[0]
        assert to_delete.entry_id == "old"
        assert to_keep.entry_id == "new"

    def test_no_duplicates(self):
        group = [
            self._entry("a", "completely different content"),
            self._entry("b", "nothing at all like the other"),
        ]
        dupes = _find_duplicates(group)
        assert len(dupes) == 0

    def test_exact_duplicates(self):
        group = [
            self._entry("a", "same exact text", ts="2026-01-01T00:00:00Z"),
            self._entry("b", "same exact text", ts="2026-01-02T00:00:00Z"),
        ]
        dupes = _find_duplicates(group)
        assert len(dupes) == 1
        assert dupes[0][0].entry_id == "a"  # older one deleted


class TestParseTs:
    def test_iso_format(self):
        ts = _parse_ts("2026-01-01T00:00:00Z")
        assert ts > 0

    def test_iso_with_offset(self):
        ts = _parse_ts("2026-01-01T00:00:00+00:00")
        assert ts > 0

    def test_invalid_returns_zero(self):
        assert _parse_ts("not a date") == 0.0

    def test_empty_returns_zero(self):
        assert _parse_ts("") == 0.0


class TestConsolidate:
    def _make_provider(self, entries):
        provider = MagicMock()
        provider.list_entries.return_value = ListResult(
            entries=entries, total_count=len(entries)
        )
        provider.forget.return_value = ForgetResult(status="deleted")
        provider.remember.return_value = RememberResult(status="accepted", entry_id="archived_1")
        return provider

    def _entry(self, eid, content, keywords, ts="2026-01-01T00:00:00Z"):
        return ListEntry(
            entry_id=eid,
            content=content,
            keywords=keywords,
            scope="project",
            ts=ts,
        )

    def test_no_entries(self):
        provider = self._make_provider([])
        report = consolidate(provider)
        assert report.total_entries_scanned == 0
        assert len(report.actions) == 0

    def test_dry_run_does_not_modify(self):
        entries = [
            self._entry("a", "same content here", ["kw1", "kw2"]),
            self._entry("b", "same content here", ["kw1", "kw2"]),
            self._entry("c", "same content here", ["kw1", "kw2"],
                         ts="2026-01-02T00:00:00Z"),
        ]
        provider = self._make_provider(entries)
        report = consolidate(provider, dry_run=True)

        assert report.duplicates_removed > 0
        provider.forget.assert_not_called()

    def test_deduplicates_in_qualifying_group(self):
        from datetime import datetime, timezone, timedelta

        # Use recent dates to avoid archival trigger
        now = datetime.now(timezone.utc)
        entries = [
            self._entry("a", "the quick brown fox", ["kw1", "kw2"],
                         ts=(now - timedelta(days=2)).isoformat()),
            self._entry("b", "the quick brown fox", ["kw1", "kw2"],
                         ts=(now - timedelta(days=1)).isoformat()),
            self._entry("c", "completely different", ["kw1", "kw2"],
                         ts=now.isoformat()),
        ]
        provider = self._make_provider(entries)
        report = consolidate(provider)

        assert report.groups_found == 1
        assert report.duplicates_removed == 1
        # Should have called forget to delete the older duplicate
        provider.forget.assert_called_once_with(entry_id="a")

    def test_archives_stale_entries(self, tmp_path):
        now = time.time()
        sixty_days_ago = now - 60 * 86400

        entries = [
            self._entry("stale", "old forgotten fact", ["kw1"],
                         ts="2025-01-01T00:00:00Z"),
        ]
        provider = self._make_provider(entries)

        # No stats = never recalled, and entry is old
        report = consolidate(
            provider, project_dir=str(tmp_path)
        )

        assert report.entries_archived == 1
        archive_action = [a for a in report.actions if a.action == "archive_stale"]
        assert len(archive_action) == 1

    def test_does_not_archive_recent_entries(self, tmp_path):
        # Entry created today
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        entries = [
            self._entry("recent", "brand new fact", ["kw1"], ts=now_iso),
        ]
        provider = self._make_provider(entries)

        report = consolidate(provider, project_dir=str(tmp_path))
        assert report.entries_archived == 0

    def test_does_not_archive_important_entries(self, tmp_path):
        # Entry is old but has high recall count
        now = time.time()
        save_stats(
            {"important": EntryStats(
                recall_count=100,
                last_recalled=now,
                created=now - 90 * 86400,
            )},
            str(tmp_path),
        )

        entries = [
            self._entry("important", "frequently recalled", ["kw1"],
                         ts="2025-01-01T00:00:00Z"),
        ]
        provider = self._make_provider(entries)

        report = consolidate(provider, project_dir=str(tmp_path))
        assert report.entries_archived == 0

    def test_small_groups_not_deduplicated(self):
        """Groups with < 3 entries are not checked for duplicates."""
        entries = [
            self._entry("a", "same content", ["kw1", "kw2"]),
            self._entry("b", "same content", ["kw1", "kw2"]),
        ]
        provider = self._make_provider(entries)
        report = consolidate(provider)

        # Group of 2 doesn't qualify for deduplication
        assert report.groups_found == 0
        assert report.duplicates_removed == 0

    def test_deleted_duplicates_not_reprocessed_in_archive(self, tmp_path):
        """Entries deleted during dedup are skipped in the archive step (AC #5)."""
        entries = [
            self._entry("a", "old repeated fact", ["kw1", "kw2"],
                         ts="2025-01-01T00:00:00Z"),
            self._entry("b", "old repeated fact", ["kw1", "kw2"],
                         ts="2025-01-02T00:00:00Z"),
            self._entry("c", "old repeated fact slightly different", ["kw1", "kw2"],
                         ts="2025-01-03T00:00:00Z"),
        ]
        provider = self._make_provider(entries)

        report = consolidate(provider, project_dir=str(tmp_path))

        # "a" should be deleted as duplicate (oldest, near-identical to "b")
        deleted_ids = {
            a.entry_id for a in report.actions if a.action == "delete_duplicate"
        }
        archived_ids = {
            a.entry_id for a in report.actions if a.action == "archive_stale"
        }
        # Confirm "a" was actually deleted in dedup step
        assert "a" in deleted_ids
        # Deleted entries must not appear in archive actions
        assert deleted_ids & archived_ids == set()

    def test_partial_archive_failure_reported(self, tmp_path):
        """When _archive_entry fails, the action is marked succeeded=False (AC #6)."""
        entries = [
            self._entry("stale1", "old fact one", ["kw1"],
                         ts="2025-01-01T00:00:00Z"),
            self._entry("stale2", "old fact two", ["kw2"],
                         ts="2025-01-01T00:00:00Z"),
        ]
        provider = self._make_provider(entries)
        # First remember call succeeds (archive copy), but forget fails
        provider.remember.return_value = RememberResult(
            status="accepted", entry_id="arc_1"
        )
        provider.forget.side_effect = Exception("storage error")

        report = consolidate(provider, project_dir=str(tmp_path))

        archive_actions = [
            a for a in report.actions if a.action == "archive_stale"
        ]
        assert len(archive_actions) == 2
        assert all(not a.succeeded for a in archive_actions)

    def test_archive_remember_failure_reported(self, tmp_path):
        """When the archive copy (remember) itself fails, action is failed."""
        entries = [
            self._entry("stale", "old fact", ["kw1"],
                         ts="2025-01-01T00:00:00Z"),
        ]
        provider = self._make_provider(entries)
        provider.remember.side_effect = Exception("cannot write")

        report = consolidate(provider, project_dir=str(tmp_path))

        archive_actions = [
            a for a in report.actions if a.action == "archive_stale"
        ]
        assert len(archive_actions) == 1
        assert not archive_actions[0].succeeded

    def test_dedup_failure_does_not_block_archive(self, tmp_path):
        """A forget failure during dedup still allows the archive step to run."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        entries = [
            # 3 entries sharing keywords for dedup qualification
            self._entry("dup1", "repeated fact", ["kw1", "kw2"],
                         ts=(now - timedelta(days=2)).isoformat()),
            self._entry("dup2", "repeated fact", ["kw1", "kw2"],
                         ts=(now - timedelta(days=1)).isoformat()),
            self._entry("diff", "different content entirely", ["kw1", "kw2"],
                         ts=now.isoformat()),
            # Separate stale entry that should still get archived
            self._entry("stale", "old separate fact", ["kw3"],
                         ts="2025-01-01T00:00:00Z"),
        ]
        provider = self._make_provider(entries)
        # forget fails for dedup but succeeds for archive

        def forget_side_effect(*, entry_id):
            if entry_id == "dup1":
                raise Exception("dedup storage error")
            return ForgetResult(status="deleted")

        provider.forget.side_effect = forget_side_effect

        report = consolidate(provider, project_dir=str(tmp_path))

        # Dedup action should have failed
        dedup_actions = [a for a in report.actions if a.action == "delete_duplicate"]
        assert any(not a.succeeded for a in dedup_actions)

        # Archive step should still have run for the stale entry
        archive_actions = [a for a in report.actions if a.action == "archive_stale"]
        assert len(archive_actions) >= 1
