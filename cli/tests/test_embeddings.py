"""Tests for memory embeddings — vector storage and similarity search."""

import json
import math
from unittest.mock import MagicMock, patch

import pytest

from strawpot.memory.embeddings import (
    EmbeddingEntry,
    SimilarityResult,
    _cosine_similarity,
    _embeddings_path,
    find_similar,
    is_available,
    load_embeddings,
    rrf_merge,
    rebuild_all,
    remove_embedding,
    save_embeddings,
    store_embedding,
)


class TestEmbeddingsPath:
    def test_project_scope(self, tmp_path):
        path = _embeddings_path("project", str(tmp_path))
        assert path == tmp_path / ".strawpot" / "embeddings" / "project.json"

    def test_global_scope(self, tmp_path):
        path = _embeddings_path("global", str(tmp_path))
        from strawpot.config import get_strawpot_home

        expected = get_strawpot_home() / "embeddings" / "global.json"
        assert path == expected

    def test_global_without_project(self):
        from pathlib import Path

        with patch("strawpot.memory.embeddings.get_strawpot_home") as mock:
            mock.return_value = Path("/home/user/.strawpot")
            path = _embeddings_path("project", None)
            assert path == Path("/home/user/.strawpot/embeddings/project.json")


class TestLoadSaveEmbeddings:
    def test_empty_when_no_file(self, tmp_path):
        embeddings = load_embeddings("project", str(tmp_path))
        assert embeddings == {}

    def test_roundtrip(self, tmp_path):
        original = {
            "e1": EmbeddingEntry(entry_id="e1", vector=[0.1, 0.2, 0.3]),
            "e2": EmbeddingEntry(entry_id="e2", vector=[0.4, 0.5, 0.6]),
        }
        save_embeddings(original, "project", str(tmp_path))
        loaded = load_embeddings("project", str(tmp_path))

        assert "e1" in loaded
        assert "e2" in loaded
        assert loaded["e1"].vector == [0.1, 0.2, 0.3]
        assert loaded["e2"].vector == [0.4, 0.5, 0.6]

    def test_corrupt_json_returns_empty(self, tmp_path):
        path = tmp_path / ".strawpot" / "embeddings"
        path.mkdir(parents=True)
        (path / "project.json").write_text("not json{{{")

        embeddings = load_embeddings("project", str(tmp_path))
        assert embeddings == {}

    def test_creates_directory(self, tmp_path):
        embeddings = {"e1": EmbeddingEntry(entry_id="e1", vector=[1.0])}
        save_embeddings(embeddings, "project", str(tmp_path))

        path = tmp_path / ".strawpot" / "embeddings" / "project.json"
        assert path.is_file()


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 1e-6

    def test_empty_vectors(self):
        assert _cosine_similarity([], []) == 0.0

    def test_different_lengths(self):
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestRRFMerge:
    def test_basic_merge(self):
        bm25 = ["a", "b", "c"]
        embed = ["b", "d", "a"]
        merged = rrf_merge(bm25, embed)

        # Both a and b appear in both lists, should rank higher
        ids = [eid for eid, _ in merged]
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids
        assert "d" in ids

    def test_shared_entries_rank_higher(self):
        bm25 = ["a", "b", "c"]
        embed = ["a", "d", "e"]
        merged = rrf_merge(bm25, embed)

        # "a" appears first in both lists — should be highest
        assert merged[0][0] == "a"

    def test_empty_lists(self):
        assert rrf_merge([], []) == []

    def test_one_empty(self):
        merged = rrf_merge(["a", "b"], [])
        ids = [eid for eid, _ in merged]
        assert ids == ["a", "b"]

    def test_scores_are_positive(self):
        merged = rrf_merge(["a"], ["b"])
        for _, score in merged:
            assert score > 0


class TestStoreEmbedding:
    @patch("strawpot.memory.embeddings.compute_embedding")
    def test_stores_when_model_available(self, mock_compute, tmp_path):
        mock_compute.return_value = [0.1, 0.2, 0.3]

        result = store_embedding("e1", "test content", "project", str(tmp_path))
        assert result is True

        loaded = load_embeddings("project", str(tmp_path))
        assert "e1" in loaded
        assert loaded["e1"].vector == [0.1, 0.2, 0.3]

    @patch("strawpot.memory.embeddings.compute_embedding")
    def test_returns_false_when_model_unavailable(self, mock_compute, tmp_path):
        mock_compute.return_value = None

        result = store_embedding("e1", "test content", "project", str(tmp_path))
        assert result is False


class TestRemoveEmbedding:
    def test_removes_existing(self, tmp_path):
        embeddings = {
            "e1": EmbeddingEntry(entry_id="e1", vector=[1.0]),
            "e2": EmbeddingEntry(entry_id="e2", vector=[2.0]),
        }
        save_embeddings(embeddings, "project", str(tmp_path))

        remove_embedding("e1", "project", str(tmp_path))

        loaded = load_embeddings("project", str(tmp_path))
        assert "e1" not in loaded
        assert "e2" in loaded

    def test_noop_for_missing(self, tmp_path):
        # Should not raise
        remove_embedding("nonexistent", "project", str(tmp_path))


class TestFindSimilar:
    @patch("strawpot.memory.embeddings.compute_embedding")
    def test_returns_empty_when_no_model(self, mock_compute, tmp_path):
        mock_compute.return_value = None
        result = find_similar("query", "project", str(tmp_path))
        assert result == []

    @patch("strawpot.memory.embeddings.compute_embedding")
    def test_returns_empty_when_no_embeddings(self, mock_compute, tmp_path):
        mock_compute.return_value = [1.0, 0.0]
        result = find_similar("query", "project", str(tmp_path))
        assert result == []

    @patch("strawpot.memory.embeddings.compute_embedding")
    def test_ranks_by_similarity(self, mock_compute, tmp_path):
        # Store two embeddings: one similar, one different
        embeddings = {
            "close": EmbeddingEntry(entry_id="close", vector=[1.0, 0.0]),
            "far": EmbeddingEntry(entry_id="far", vector=[0.0, 1.0]),
        }
        save_embeddings(embeddings, "project", str(tmp_path))

        # Query vector is [1.0, 0.0] — should rank "close" first
        mock_compute.return_value = [1.0, 0.0]
        results = find_similar("query", "project", str(tmp_path))

        assert len(results) == 2
        assert results[0].entry_id == "close"
        assert results[0].score > results[1].score

    @patch("strawpot.memory.embeddings.compute_embedding")
    def test_top_k_limit(self, mock_compute, tmp_path):
        embeddings = {
            f"e{i}": EmbeddingEntry(entry_id=f"e{i}", vector=[float(i), 0.0])
            for i in range(10)
        }
        save_embeddings(embeddings, "project", str(tmp_path))

        mock_compute.return_value = [5.0, 0.0]
        results = find_similar("query", "project", str(tmp_path), top_k=3)
        assert len(results) == 3


class TestRebuildAll:
    @patch("strawpot.memory.embeddings.is_available", return_value=False)
    def test_returns_zero_when_no_model(self, _mock):
        provider = MagicMock()
        assert rebuild_all(provider) == 0

    @patch("strawpot.memory.embeddings.compute_embedding")
    @patch("strawpot.memory.embeddings.is_available", return_value=True)
    def test_processes_all_entries(self, _available, mock_compute, tmp_path):
        from strawpot_memory.memory_protocol import ListEntry, ListResult

        entries = [
            ListEntry(entry_id="e1", content="hello", scope="project"),
            ListEntry(entry_id="e2", content="world", scope="project"),
        ]
        provider = MagicMock()
        provider.list_entries.return_value = ListResult(entries=entries)

        mock_compute.return_value = [0.1, 0.2, 0.3]
        count = rebuild_all(provider, project_dir=str(tmp_path))
        assert count == 2
        assert mock_compute.call_count == 2
        # Verify embeddings were batched and saved
        loaded = load_embeddings("project", str(tmp_path))
        assert "e1" in loaded
        assert "e2" in loaded


class TestIsAvailable:
    @patch("strawpot.memory.embeddings._get_model", return_value=None)
    def test_false_when_no_model(self, _mock):
        assert is_available() is False

    @patch("strawpot.memory.embeddings._get_model", return_value=MagicMock())
    def test_true_when_model_loaded(self, _mock):
        assert is_available() is True
