"""Memory graph — track relationships between memory entries.

Stores an adjacency list of typed edges between memory entries.
Supports traversal for recall expansion and visualization.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from strawpot.config import get_strawpot_home

log = logging.getLogger(__name__)

_GRAPH_FILENAME = "memory_graph.json"

# Valid relation types.
RELATION_TYPES = frozenset({
    "follows_from",
    "caused_by",
    "supersedes",
    "related_to",
})

# Score multiplier for 1-hop neighbors included in recall expansion.
NEIGHBOR_SCORE_FACTOR = 0.5


@dataclass
class Relation:
    """A directed edge between two memory entries."""

    relation_type: str
    target: str
    created_at: float = 0.0


@dataclass
class GraphData:
    """Full adjacency list representation of the memory graph."""

    edges: dict[str, list[Relation]] = field(default_factory=dict)


def _graph_path(project_dir: str | None = None) -> Path:
    """Return the path to the memory graph file.

    Uses ``<project_dir>/.strawpot/memory_graph.json`` when a project
    directory is provided, otherwise falls back to
    ``~/.strawpot/memory_graph.json``.
    """
    if project_dir:
        return Path(project_dir) / ".strawpot" / _GRAPH_FILENAME
    return get_strawpot_home() / _GRAPH_FILENAME


def load_graph(project_dir: str | None = None) -> GraphData:
    """Load the memory graph from disk.

    Returns an empty graph if the file doesn't exist or is corrupt.
    """
    path = _graph_path(project_dir)
    if not path.is_file():
        return GraphData()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Failed to load memory graph from %s", path, exc_info=True)
        return GraphData()

    graph = GraphData()
    for entry_id, relations in raw.items():
        graph.edges[entry_id] = [
            Relation(
                relation_type=r.get("type", "related_to"),
                target=r.get("target", ""),
                created_at=r.get("created_at", 0.0),
            )
            for r in relations
            if r.get("target")
        ]
    return graph


def save_graph(graph: GraphData, project_dir: str | None = None) -> None:
    """Persist the memory graph to disk."""
    path = _graph_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    raw = {
        entry_id: [
            {
                "type": r.relation_type,
                "target": r.target,
                "created_at": r.created_at,
            }
            for r in relations
        ]
        for entry_id, relations in graph.edges.items()
        if relations  # skip empty lists
    }
    try:
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except OSError:
        log.warning("Failed to save memory graph to %s", path, exc_info=True)


def add_relation(
    source: str,
    relation_type: str,
    target: str,
    project_dir: str | None = None,
) -> bool:
    """Add a directed relation between two memory entries.

    Args:
        source: Source entry ID.
        relation_type: One of RELATION_TYPES.
        target: Target entry ID.
        project_dir: Project directory for graph storage.

    Returns:
        True if the relation was added, False if invalid or duplicate.
    """
    if relation_type not in RELATION_TYPES:
        log.warning("Invalid relation type: %s", relation_type)
        return False

    if not source or not target:
        return False

    graph = load_graph(project_dir)
    existing = graph.edges.get(source, [])

    # Check for duplicates
    for rel in existing:
        if rel.relation_type == relation_type and rel.target == target:
            return False

    relation = Relation(
        relation_type=relation_type,
        target=target,
        created_at=time.time(),
    )
    graph.edges.setdefault(source, []).append(relation)
    save_graph(graph, project_dir)
    return True


def remove_entry(entry_id: str, project_dir: str | None = None) -> int:
    """Remove all relations involving an entry (as source or target).

    Returns the number of relations removed.
    """
    graph = load_graph(project_dir)
    removed = 0

    # Remove as source
    if entry_id in graph.edges:
        removed += len(graph.edges[entry_id])
        del graph.edges[entry_id]

    # Remove as target from other entries
    for source_id in list(graph.edges):
        original = graph.edges[source_id]
        filtered = [r for r in original if r.target != entry_id]
        removed += len(original) - len(filtered)
        graph.edges[source_id] = filtered

    if removed:
        save_graph(graph, project_dir)
    return removed


def get_neighbors(
    entry_id: str,
    project_dir: str | None = None,
) -> list[tuple[str, str]]:
    """Get all 1-hop neighbors of an entry.

    Returns a list of (neighbor_id, relation_type) tuples.
    Includes both outgoing and incoming edges.
    """
    graph = load_graph(project_dir)
    neighbors: list[tuple[str, str]] = []

    # Outgoing edges
    for rel in graph.edges.get(entry_id, []):
        neighbors.append((rel.target, rel.relation_type))

    # Incoming edges
    for source_id, relations in graph.edges.items():
        if source_id == entry_id:
            continue
        for rel in relations:
            if rel.target == entry_id:
                neighbors.append((source_id, rel.relation_type))

    return neighbors


def expand_recall(
    entry_ids: list[str],
    project_dir: str | None = None,
) -> list[tuple[str, float]]:
    """Expand recall results by including 1-hop graph neighbors.

    For each entry in the initial results, finds its graph neighbors
    and includes them with a reduced score factor.

    Args:
        entry_ids: Initial recall result entry IDs.
        project_dir: Project directory for graph storage.

    Returns:
        List of (entry_id, score_multiplier) for neighbor entries
        not already in the initial results.
    """
    initial_set = set(entry_ids)
    expansions: dict[str, float] = {}

    graph = load_graph(project_dir)
    if not graph.edges:
        return []

    for eid in entry_ids:
        neighbors = _get_neighbors_from_graph(eid, graph)
        for neighbor_id, _rel_type in neighbors:
            if neighbor_id not in initial_set and neighbor_id not in expansions:
                expansions[neighbor_id] = NEIGHBOR_SCORE_FACTOR

    return list(expansions.items())


def _get_neighbors_from_graph(
    entry_id: str,
    graph: GraphData,
) -> list[tuple[str, str]]:
    """Get neighbors from an already-loaded graph (avoids redundant I/O)."""
    neighbors: list[tuple[str, str]] = []

    for rel in graph.edges.get(entry_id, []):
        neighbors.append((rel.target, rel.relation_type))

    for source_id, relations in graph.edges.items():
        if source_id == entry_id:
            continue
        for rel in relations:
            if rel.target == entry_id:
                neighbors.append((source_id, rel.relation_type))

    return neighbors


def merge_relations(
    old_entry_id: str,
    new_entry_id: str,
    project_dir: str | None = None,
) -> int:
    """Transfer all relations from an old entry to a new entry.

    Used during consolidation when entries are merged. Relations
    pointing to the old entry are redirected to the new one.

    Returns the number of relations transferred.
    """
    graph = load_graph(project_dir)
    transferred = 0

    # Transfer outgoing relations
    old_rels = graph.edges.pop(old_entry_id, [])
    if old_rels:
        existing = graph.edges.setdefault(new_entry_id, [])
        existing_targets = {(r.relation_type, r.target) for r in existing}
        for rel in old_rels:
            if rel.target == new_entry_id:
                continue  # skip self-loops
            if (rel.relation_type, rel.target) not in existing_targets:
                existing.append(rel)
                transferred += 1

    # Redirect incoming relations
    for source_id, relations in graph.edges.items():
        for rel in relations:
            if rel.target == old_entry_id:
                rel.target = new_entry_id
                transferred += 1

    if transferred:
        save_graph(graph, project_dir)
    return transferred


def format_graph(
    entry_id: str | None = None,
    project_dir: str | None = None,
) -> str:
    """Format the graph as human-readable text.

    If entry_id is provided, shows only relations involving that entry.
    Otherwise shows the full graph summary.
    """
    graph = load_graph(project_dir)
    if not graph.edges:
        return "No relations stored."

    lines: list[str] = []

    if entry_id:
        # Show specific entry's relations
        outgoing = graph.edges.get(entry_id, [])
        if outgoing:
            for rel in outgoing:
                lines.append(f"  {entry_id} --{rel.relation_type}--> {rel.target}")

        # Incoming
        for source_id, relations in graph.edges.items():
            if source_id == entry_id:
                continue
            for rel in relations:
                if rel.target == entry_id:
                    lines.append(f"  {source_id} --{rel.relation_type}--> {entry_id}")

        if not lines:
            return f"No relations found for {entry_id}."
    else:
        # Full graph summary
        total_relations = sum(len(rels) for rels in graph.edges.values())
        total_entries = len({
            eid
            for source, rels in graph.edges.items()
            for eid in [source] + [r.target for r in rels]
        })
        lines.append(f"Memory graph: {total_entries} entries, {total_relations} relations")
        lines.append("")
        for source_id, relations in sorted(graph.edges.items()):
            for rel in relations:
                lines.append(f"  {source_id} --{rel.relation_type}--> {rel.target}")

    return "\n".join(lines)
