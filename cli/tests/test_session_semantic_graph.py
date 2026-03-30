"""Tests for semantic search and graph expansion in session recall."""

from unittest.mock import MagicMock, patch

import pytest

from strawpot.session import (
    _expand_with_graph,
    _link_session_recap,
    _semantic_recall,
    _store_embedding,
)
from strawpot_memory.memory_protocol import RecallEntry, RecallResult


class TestStoreEmbedding:
    @patch("strawpot.session.logger")
    def test_logs_failure_at_debug(self, mock_logger, tmp_path):
        with patch(
            "strawpot.memory.embeddings.store_embedding",
            side_effect=RuntimeError("fail"),
        ):
            _store_embedding("e1", "content", "project", str(tmp_path))
        mock_logger.debug.assert_called()

    @patch("strawpot.memory.embeddings.store_embedding", return_value=True)
    def test_calls_store_embedding(self, mock_store, tmp_path):
        _store_embedding("e1", "content", "project", str(tmp_path))
        mock_store.assert_called_once_with("e1", "content", "project", str(tmp_path))


class TestSemanticRecall:
    def _make_entries(self, ids):
        return [
            RecallEntry(entry_id=eid, content=f"content {eid}", score=10.0 - i)
            for i, eid in enumerate(ids)
        ]

    @patch("strawpot.memory.embeddings.find_similar", return_value=[])
    def test_returns_bm25_when_no_similar(self, _mock, tmp_path):
        entries = self._make_entries(["a", "b"])
        result = _semantic_recall("query", "project", str(tmp_path), entries, 10)
        assert [e.entry_id for e in result] == ["a", "b"]

    @patch("strawpot.memory.embeddings.rrf_merge")
    @patch("strawpot.memory.embeddings.find_similar")
    def test_reranks_with_rrf(self, mock_similar, mock_rrf, tmp_path):
        from strawpot.memory.embeddings import SimilarityResult

        entries = self._make_entries(["a", "b", "c"])
        mock_similar.return_value = [
            SimilarityResult(entry_id="c", score=0.9),
            SimilarityResult(entry_id="a", score=0.5),
        ]
        # RRF puts c first
        mock_rrf.return_value = [("c", 0.03), ("a", 0.02), ("b", 0.01)]

        result = _semantic_recall("query", "project", str(tmp_path), entries, 10)
        assert result[0].entry_id == "c"

    @patch(
        "strawpot.memory.embeddings.find_similar",
        side_effect=RuntimeError("fail"),
    )
    def test_falls_back_on_error(self, _mock, tmp_path):
        entries = self._make_entries(["a", "b"])
        result = _semantic_recall("query", "project", str(tmp_path), entries, 10)
        assert [e.entry_id for e in result] == ["a", "b"]

    @patch("strawpot.memory.embeddings.rrf_merge")
    @patch("strawpot.memory.embeddings.find_similar")
    def test_respects_max_results(self, mock_similar, mock_rrf, tmp_path):
        from strawpot.memory.embeddings import SimilarityResult

        entries = self._make_entries(["a", "b", "c"])
        mock_similar.return_value = [SimilarityResult(entry_id="a", score=0.9)]
        mock_rrf.return_value = [("a", 0.03), ("b", 0.02), ("c", 0.01)]

        result = _semantic_recall("query", "project", str(tmp_path), entries, 2)
        assert len(result) == 2


class TestExpandWithGraph:
    def _make_result(self, ids):
        entries = [
            RecallEntry(entry_id=eid, content=f"content {eid}", score=10.0 - i)
            for i, eid in enumerate(ids)
        ]
        return RecallResult(entries=entries)

    @patch("strawpot.memory.graph.expand_recall", return_value=[])
    def test_no_expansion(self, _mock):
        result = self._make_result(["a", "b"])
        provider = MagicMock()
        _expand_with_graph(result, "/tmp/test", provider, 10)
        assert len(result.entries) == 2

    @patch("strawpot.memory.graph.expand_recall")
    def test_adds_neighbors(self, mock_expand):
        mock_expand.return_value = [("c", 0.5)]
        result = self._make_result(["a", "b"])

        provider = MagicMock()
        neighbor_entry = RecallEntry(
            entry_id="c", content="neighbor", score=5.0
        )
        provider.recall.return_value = RecallResult(entries=[neighbor_entry])

        _expand_with_graph(result, "/tmp/test", provider, 10)
        assert len(result.entries) == 3
        assert result.entries[-1].entry_id == "c"
        # Score should be min_score * factor
        assert result.entries[-1].score == 9.0 * 0.5

    @patch("strawpot.memory.graph.expand_recall")
    def test_respects_max_results(self, mock_expand):
        mock_expand.return_value = [("c", 0.5), ("d", 0.5)]
        result = self._make_result(["a", "b"])

        provider = MagicMock()

        def fake_recall(**kwargs):
            eid = kwargs["query"]
            return RecallResult(
                entries=[RecallEntry(entry_id=eid, content="n", score=1.0)]
            )

        provider.recall.side_effect = fake_recall

        _expand_with_graph(result, "/tmp/test", provider, 3)
        assert len(result.entries) == 3  # max_results=3, started with 2

    @patch(
        "strawpot.memory.graph.expand_recall",
        side_effect=RuntimeError("fail"),
    )
    def test_handles_error_gracefully(self, _mock):
        result = self._make_result(["a"])
        provider = MagicMock()
        _expand_with_graph(result, "/tmp/test", provider, 10)
        assert len(result.entries) == 1


class TestLinkSessionRecap:
    @patch("strawpot.memory.graph.add_relation")
    def test_links_to_previous_recap(self, mock_add):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[
            RecallEntry(entry_id="prev_recap", content="old recap"),
        ])

        _link_session_recap("new_recap", provider, "run_1", "/tmp")
        mock_add.assert_called_once_with(
            "new_recap", "follows_from", "prev_recap", "/tmp"
        )

    @patch("strawpot.memory.graph.add_relation")
    def test_skips_self_link(self, mock_add):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[
            RecallEntry(entry_id="new_recap", content="same entry"),
            RecallEntry(entry_id="prev_recap", content="old entry"),
        ])

        _link_session_recap("new_recap", provider, "run_1", "/tmp")
        mock_add.assert_called_once_with(
            "new_recap", "follows_from", "prev_recap", "/tmp"
        )

    @patch("strawpot.memory.graph.add_relation")
    def test_noop_when_no_previous(self, mock_add):
        provider = MagicMock()
        provider.recall.return_value = RecallResult(entries=[
            RecallEntry(entry_id="new_recap", content="only this one"),
        ])

        _link_session_recap("new_recap", provider, "run_1", "/tmp")
        mock_add.assert_not_called()

    def test_handles_recall_error(self):
        provider = MagicMock()
        provider.recall.side_effect = RuntimeError("fail")
        # Should not raise
        _link_session_recap("new_recap", provider, "run_1", "/tmp")
