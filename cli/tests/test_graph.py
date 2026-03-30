"""Tests for memory graph — relationship tracking between entries."""

import json
import time
from unittest.mock import patch

import pytest

from strawpot.memory.graph import (
    NEIGHBOR_SCORE_FACTOR,
    RELATION_TYPES,
    GraphData,
    Relation,
    _graph_path,
    _get_neighbors_from_graph,
    add_relation,
    expand_recall,
    format_graph,
    get_neighbors,
    load_graph,
    merge_relations,
    remove_entry,
    save_graph,
)


class TestGraphPath:
    def test_project_dir(self, tmp_path):
        path = _graph_path(str(tmp_path))
        assert path == tmp_path / ".strawpot" / "memory_graph.json"

    def test_global_fallback(self):
        from pathlib import Path

        with patch("strawpot.memory.graph.get_strawpot_home") as mock:
            mock.return_value = Path("/home/user/.strawpot")
            path = _graph_path(None)
            assert path == Path("/home/user/.strawpot/memory_graph.json")


class TestLoadSaveGraph:
    def test_empty_when_no_file(self, tmp_path):
        graph = load_graph(str(tmp_path))
        assert graph.edges == {}

    def test_roundtrip(self, tmp_path):
        graph = GraphData(edges={
            "e1": [
                Relation(relation_type="follows_from", target="e0", created_at=1000.0),
                Relation(relation_type="related_to", target="e2", created_at=1001.0),
            ],
        })
        save_graph(graph, str(tmp_path))
        loaded = load_graph(str(tmp_path))

        assert "e1" in loaded.edges
        assert len(loaded.edges["e1"]) == 2
        assert loaded.edges["e1"][0].relation_type == "follows_from"
        assert loaded.edges["e1"][0].target == "e0"
        assert loaded.edges["e1"][1].relation_type == "related_to"

    def test_corrupt_json_returns_empty(self, tmp_path):
        path = tmp_path / ".strawpot"
        path.mkdir()
        (path / "memory_graph.json").write_text("not json{{{")
        graph = load_graph(str(tmp_path))
        assert graph.edges == {}

    def test_skips_empty_targets(self, tmp_path):
        path = tmp_path / ".strawpot"
        path.mkdir()
        (path / "memory_graph.json").write_text(json.dumps({
            "e1": [
                {"type": "related_to", "target": "", "created_at": 0},
                {"type": "related_to", "target": "e2", "created_at": 0},
            ]
        }))
        graph = load_graph(str(tmp_path))
        assert len(graph.edges["e1"]) == 1
        assert graph.edges["e1"][0].target == "e2"

    def test_empty_lists_not_saved(self, tmp_path):
        graph = GraphData(edges={"e1": [], "e2": [
            Relation(relation_type="related_to", target="e3", created_at=0),
        ]})
        save_graph(graph, str(tmp_path))
        raw = json.loads(
            (tmp_path / ".strawpot" / "memory_graph.json").read_text()
        )
        assert "e1" not in raw
        assert "e2" in raw


class TestAddRelation:
    def test_adds_new_relation(self, tmp_path):
        result = add_relation("e1", "follows_from", "e0", str(tmp_path))
        assert result is True

        graph = load_graph(str(tmp_path))
        assert len(graph.edges["e1"]) == 1
        assert graph.edges["e1"][0].target == "e0"
        assert graph.edges["e1"][0].relation_type == "follows_from"

    def test_rejects_invalid_type(self, tmp_path):
        result = add_relation("e1", "invalid_type", "e0", str(tmp_path))
        assert result is False

    def test_rejects_empty_source(self, tmp_path):
        result = add_relation("", "follows_from", "e0", str(tmp_path))
        assert result is False

    def test_rejects_empty_target(self, tmp_path):
        result = add_relation("e1", "follows_from", "", str(tmp_path))
        assert result is False

    def test_prevents_duplicates(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        result = add_relation("e1", "follows_from", "e0", str(tmp_path))
        assert result is False

        graph = load_graph(str(tmp_path))
        assert len(graph.edges["e1"]) == 1

    def test_allows_different_types_same_pair(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        result = add_relation("e1", "related_to", "e0", str(tmp_path))
        assert result is True

        graph = load_graph(str(tmp_path))
        assert len(graph.edges["e1"]) == 2

    def test_all_valid_types(self, tmp_path):
        for i, rtype in enumerate(sorted(RELATION_TYPES)):
            result = add_relation(f"s{i}", rtype, f"t{i}", str(tmp_path))
            assert result is True


class TestRemoveEntry:
    def test_removes_as_source(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        add_relation("e1", "related_to", "e2", str(tmp_path))

        removed = remove_entry("e1", str(tmp_path))
        assert removed == 2

        graph = load_graph(str(tmp_path))
        assert "e1" not in graph.edges

    def test_removes_as_target(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        add_relation("e2", "related_to", "e0", str(tmp_path))

        removed = remove_entry("e0", str(tmp_path))
        assert removed == 2

    def test_noop_for_missing(self, tmp_path):
        removed = remove_entry("nonexistent", str(tmp_path))
        assert removed == 0


class TestGetNeighbors:
    def test_outgoing_and_incoming(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        add_relation("e2", "related_to", "e1", str(tmp_path))

        neighbors = get_neighbors("e1", str(tmp_path))
        neighbor_ids = {nid for nid, _ in neighbors}
        assert "e0" in neighbor_ids  # outgoing
        assert "e2" in neighbor_ids  # incoming

    def test_empty_for_isolated(self, tmp_path):
        neighbors = get_neighbors("nonexistent", str(tmp_path))
        assert neighbors == []


class TestExpandRecall:
    def test_expands_with_neighbors(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        add_relation("e1", "related_to", "e3", str(tmp_path))

        expansions = expand_recall(["e1"], str(tmp_path))
        expansion_ids = {eid for eid, _ in expansions}
        assert "e0" in expansion_ids
        assert "e3" in expansion_ids

    def test_excludes_initial_entries(self, tmp_path):
        add_relation("e1", "follows_from", "e2", str(tmp_path))

        # e2 is already in initial results — should not be expanded
        expansions = expand_recall(["e1", "e2"], str(tmp_path))
        expansion_ids = {eid for eid, _ in expansions}
        assert "e2" not in expansion_ids

    def test_score_factor(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))

        expansions = expand_recall(["e1"], str(tmp_path))
        for _, factor in expansions:
            assert factor == NEIGHBOR_SCORE_FACTOR

    def test_empty_graph(self, tmp_path):
        expansions = expand_recall(["e1"], str(tmp_path))
        assert expansions == []


class TestMergeRelations:
    def test_transfers_outgoing(self, tmp_path):
        add_relation("old", "follows_from", "e0", str(tmp_path))
        add_relation("old", "related_to", "e2", str(tmp_path))

        transferred = merge_relations("old", "new", str(tmp_path))
        assert transferred == 2

        graph = load_graph(str(tmp_path))
        assert "old" not in graph.edges
        new_targets = {r.target for r in graph.edges.get("new", [])}
        assert "e0" in new_targets
        assert "e2" in new_targets

    def test_redirects_incoming(self, tmp_path):
        add_relation("e1", "follows_from", "old", str(tmp_path))

        transferred = merge_relations("old", "new", str(tmp_path))
        assert transferred >= 1

        graph = load_graph(str(tmp_path))
        targets = {r.target for r in graph.edges.get("e1", [])}
        assert "new" in targets
        assert "old" not in targets

    def test_skips_self_loops(self, tmp_path):
        add_relation("old", "follows_from", "new", str(tmp_path))

        transferred = merge_relations("old", "new", str(tmp_path))
        # The old->new relation becomes new->new (self-loop), should be skipped
        graph = load_graph(str(tmp_path))
        for rel in graph.edges.get("new", []):
            assert rel.target != "new"

    def test_skips_duplicate_transfers(self, tmp_path):
        add_relation("old", "follows_from", "e0", str(tmp_path))
        add_relation("new", "follows_from", "e0", str(tmp_path))

        merge_relations("old", "new", str(tmp_path))
        graph = load_graph(str(tmp_path))
        # Should not have duplicate follows_from -> e0
        count = sum(
            1 for r in graph.edges.get("new", [])
            if r.relation_type == "follows_from" and r.target == "e0"
        )
        assert count == 1

    def test_dedup_incoming_redirects(self, tmp_path):
        """When redirecting incoming edges, don't create duplicates."""
        # e1 -> old AND e1 -> new already exist
        add_relation("e1", "related_to", "old", str(tmp_path))
        add_relation("e1", "related_to", "new", str(tmp_path))

        merge_relations("old", "new", str(tmp_path))
        graph = load_graph(str(tmp_path))
        # e1 should have exactly one related_to -> new, not two
        count = sum(
            1 for r in graph.edges.get("e1", [])
            if r.relation_type == "related_to" and r.target == "new"
        )
        assert count == 1


class TestFormatGraph:
    def test_empty_graph(self, tmp_path):
        output = format_graph(project_dir=str(tmp_path))
        assert "No relations" in output

    def test_full_graph(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        add_relation("e2", "related_to", "e1", str(tmp_path))

        output = format_graph(project_dir=str(tmp_path))
        assert "e1" in output
        assert "follows_from" in output
        assert "related_to" in output

    def test_specific_entry(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))
        add_relation("e2", "related_to", "e3", str(tmp_path))

        output = format_graph("e1", str(tmp_path))
        assert "e1" in output
        assert "e0" in output
        # e2->e3 should not be shown
        assert "e3" not in output

    def test_no_relations_for_entry(self, tmp_path):
        add_relation("e1", "follows_from", "e0", str(tmp_path))

        output = format_graph("e99", str(tmp_path))
        assert "No relations found" in output


class TestGetNeighborsFromGraph:
    def test_from_loaded_graph(self):
        graph = GraphData(edges={
            "e1": [Relation(relation_type="follows_from", target="e0")],
            "e2": [Relation(relation_type="related_to", target="e1")],
        })
        neighbors = _get_neighbors_from_graph("e1", graph)
        ids = {nid for nid, _ in neighbors}
        assert "e0" in ids  # outgoing
        assert "e2" in ids  # incoming
