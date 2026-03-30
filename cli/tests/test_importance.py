"""Tests for memory importance tracking."""

import json
import time
from unittest.mock import patch

import pytest

from strawpot.memory.importance import (
    EntryStats,
    _stats_path,
    importance_score,
    load_stats,
    record_recall,
    save_stats,
)


class TestStatsPath:
    def test_project_dir(self, tmp_path):
        path = _stats_path(str(tmp_path))
        assert path == tmp_path / ".strawpot" / "memory_stats.json"

    def test_global_fallback(self):
        from pathlib import Path

        with patch("strawpot.memory.importance.get_strawpot_home") as mock_home:
            mock_home.return_value = Path("/home/user/.strawpot")
            path = _stats_path(None)
            assert path == Path("/home/user/.strawpot/memory_stats.json")


class TestLoadStats:
    def test_empty_when_no_file(self, tmp_path):
        stats = load_stats(str(tmp_path))
        assert stats == {}

    def test_loads_valid_json(self, tmp_path):
        stats_dir = tmp_path / ".strawpot"
        stats_dir.mkdir()
        stats_file = stats_dir / "memory_stats.json"
        stats_file.write_text(json.dumps({
            "entry_1": {
                "recall_count": 5,
                "last_recalled": 1000.0,
                "created": 500.0,
            }
        }))

        stats = load_stats(str(tmp_path))
        assert "entry_1" in stats
        assert stats["entry_1"].recall_count == 5
        assert stats["entry_1"].last_recalled == 1000.0
        assert stats["entry_1"].created == 500.0

    def test_empty_on_corrupt_json(self, tmp_path):
        stats_dir = tmp_path / ".strawpot"
        stats_dir.mkdir()
        (stats_dir / "memory_stats.json").write_text("not json{{{")

        stats = load_stats(str(tmp_path))
        assert stats == {}


class TestSaveStats:
    def test_creates_directory_and_file(self, tmp_path):
        stats = {"e1": EntryStats(recall_count=3, last_recalled=1.0, created=0.5)}
        save_stats(stats, str(tmp_path))

        path = tmp_path / ".strawpot" / "memory_stats.json"
        assert path.is_file()
        raw = json.loads(path.read_text())
        assert raw["e1"]["recall_count"] == 3

    def test_roundtrip(self, tmp_path):
        original = {
            "a": EntryStats(recall_count=10, last_recalled=2000.0, created=1000.0),
            "b": EntryStats(recall_count=1, last_recalled=500.0, created=400.0),
        }
        save_stats(original, str(tmp_path))
        loaded = load_stats(str(tmp_path))

        assert loaded["a"].recall_count == 10
        assert loaded["b"].last_recalled == 500.0


class TestRecordRecall:
    def test_new_entries(self, tmp_path):
        record_recall(["e1", "e2"], str(tmp_path))

        stats = load_stats(str(tmp_path))
        assert stats["e1"].recall_count == 1
        assert stats["e2"].recall_count == 1
        assert stats["e1"].last_recalled > 0

    def test_increments_existing(self, tmp_path):
        save_stats(
            {"e1": EntryStats(recall_count=5, last_recalled=100.0, created=50.0)},
            str(tmp_path),
        )

        record_recall(["e1"], str(tmp_path))

        stats = load_stats(str(tmp_path))
        assert stats["e1"].recall_count == 6
        assert stats["e1"].last_recalled > 100.0
        # created should be preserved
        assert stats["e1"].created == 50.0

    def test_empty_list_is_noop(self, tmp_path):
        record_recall([], str(tmp_path))
        stats = load_stats(str(tmp_path))
        assert stats == {}


class TestImportanceScore:
    def test_zero_for_no_recalls(self):
        entry = EntryStats(recall_count=0, last_recalled=0.0, created=100.0)
        assert importance_score(entry) == 0.0

    def test_recent_high_recall(self):
        now = time.time()
        entry = EntryStats(recall_count=10, last_recalled=now, created=now - 100)
        score = importance_score(entry, now)
        # Just recalled, so recency_weight ≈ 1.0, score ≈ 10.0
        assert 9.5 < score <= 10.0

    def test_old_recall_decays(self):
        now = time.time()
        thirty_days_ago = now - 30 * 86400
        entry = EntryStats(
            recall_count=10,
            last_recalled=thirty_days_ago,
            created=thirty_days_ago - 100,
        )
        score = importance_score(entry, now)
        # recency_weight = 1/(1+1) = 0.5, score = 10 * 0.5 = 5.0
        assert 4.9 < score < 5.1

    def test_very_old_recall(self):
        now = time.time()
        ninety_days_ago = now - 90 * 86400
        entry = EntryStats(
            recall_count=1,
            last_recalled=ninety_days_ago,
            created=ninety_days_ago,
        )
        score = importance_score(entry, now)
        # recency_weight = 1/(1+3) = 0.25, score = 1 * 0.25 = 0.25
        assert 0.2 < score < 0.3
