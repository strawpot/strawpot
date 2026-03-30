"""Tests for CLI memory commands: rebuild-embeddings, graph, add-relation."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from strawpot.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestRebuildEmbeddings:
    @patch("strawpot.memory.embeddings.rebuild_all", return_value=5)
    @patch("strawpot.memory.embeddings.is_available", return_value=True)
    @patch("strawpot.memory.standalone.get_standalone_provider")
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_success(self, _proj, _provider, _available, _rebuild, runner):
        result = runner.invoke(cli, ["memory", "rebuild-embeddings"])
        assert result.exit_code == 0
        assert "Rebuilt embeddings for 5" in result.output

    @patch("strawpot.memory.embeddings.is_available", return_value=False)
    def test_no_model(self, _available, runner):
        result = runner.invoke(cli, ["memory", "rebuild-embeddings"])
        assert result.exit_code != 0
        assert "No embedding model" in result.output

    @patch("strawpot.memory.embeddings.rebuild_all", return_value=3)
    @patch("strawpot.memory.embeddings.is_available", return_value=True)
    @patch("strawpot.memory.standalone.get_standalone_provider")
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_with_scope(self, _proj, mock_provider, _available, mock_rebuild, runner):
        result = runner.invoke(cli, ["memory", "rebuild-embeddings", "--scope", "global"])
        assert result.exit_code == 0
        mock_rebuild.assert_called_once()
        call_kwargs = mock_rebuild.call_args
        assert call_kwargs.kwargs["scope"] == "global"


class TestMemoryGraph:
    @patch("strawpot.memory.graph.format_graph", return_value="e1 --follows_from--> e0")
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_full_graph(self, _proj, _format, runner):
        result = runner.invoke(cli, ["memory", "graph"])
        assert result.exit_code == 0
        assert "follows_from" in result.output

    @patch("strawpot.memory.graph.format_graph", return_value="e1 --follows_from--> e0")
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_specific_entry(self, _proj, mock_format, runner):
        result = runner.invoke(cli, ["memory", "graph", "e1"])
        assert result.exit_code == 0
        mock_format.assert_called_once_with("e1", "/tmp/proj")

    @patch("strawpot.memory.graph.load_graph")
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_json_output(self, _proj, mock_load, runner):
        from strawpot.memory.graph import GraphData, Relation

        mock_load.return_value = GraphData(edges={
            "e1": [Relation(relation_type="follows_from", target="e0", created_at=1000.0)],
        })
        result = runner.invoke(cli, ["memory", "graph", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "e1" in data

    @patch("strawpot.memory.graph.load_graph")
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_json_filtered_by_entry(self, _proj, mock_load, runner):
        from strawpot.memory.graph import GraphData, Relation

        mock_load.return_value = GraphData(edges={
            "e1": [Relation(relation_type="follows_from", target="e0", created_at=1000.0)],
            "e2": [Relation(relation_type="related_to", target="e3", created_at=1000.0)],
        })
        result = runner.invoke(cli, ["memory", "graph", "e1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "e1" in data
        assert "e2" not in data


class TestAddRelation:
    @patch("strawpot.memory.graph.add_relation", return_value=True)
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_success(self, _proj, _add, runner):
        result = runner.invoke(
            cli, ["memory", "add-relation", "e1", "follows_from", "e0"]
        )
        assert result.exit_code == 0
        assert "follows_from" in result.output

    @patch("strawpot.memory.graph.add_relation", return_value=False)
    @patch("strawpot.memory.standalone.detect_project_dir", return_value="/tmp/proj")
    def test_duplicate(self, _proj, _add, runner):
        result = runner.invoke(
            cli, ["memory", "add-relation", "e1", "follows_from", "e0"]
        )
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_invalid_type(self, runner):
        result = runner.invoke(
            cli, ["memory", "add-relation", "e1", "invalid_type", "e0"]
        )
        assert result.exit_code != 0
        assert "Invalid relation type" in result.output
