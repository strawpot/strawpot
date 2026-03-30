"""Semantic memory — vector embeddings for similarity search.

Provides optional embedding-based recall alongside BM25 keyword search.
Falls back gracefully when no embedding model is available.
"""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from strawpot.config import get_strawpot_home

log = logging.getLogger(__name__)

_EMBEDDINGS_DIR = "embeddings"


@dataclass
class EmbeddingEntry:
    """A stored embedding for a single memory entry."""

    entry_id: str
    vector: list[float]


def _embeddings_path(scope: str, project_dir: str | None = None) -> Path:
    """Return the path to the embeddings file for a given scope.

    Project-scoped embeddings live in ``<project>/.strawpot/embeddings/``,
    global embeddings in ``~/.strawpot/embeddings/``.
    """
    if project_dir and scope != "global":
        return Path(project_dir) / ".strawpot" / _EMBEDDINGS_DIR / f"{scope}.json"
    return get_strawpot_home() / _EMBEDDINGS_DIR / f"{scope}.json"


def _load_model():
    """Attempt to load the sentence-transformers embedding model.

    Returns the model instance, or None if the package is unavailable.
    """
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        log.debug("sentence-transformers not installed; semantic search disabled")
        return None
    except Exception:
        log.warning("Failed to load embedding model", exc_info=True)
        return None


# Module-level cache to avoid reloading the model on every call.
_cached_model = None
_model_loaded = False


def _get_model():
    """Return the cached embedding model, loading it on first call."""
    global _cached_model, _model_loaded
    if not _model_loaded:
        _cached_model = _load_model()
        _model_loaded = True
    return _cached_model


def is_available() -> bool:
    """Return True if an embedding model is loaded and ready."""
    return _get_model() is not None


def compute_embedding(text: str) -> list[float] | None:
    """Compute an embedding vector for the given text.

    Returns None if no embedding model is available.
    """
    model = _get_model()
    if model is None:
        return None

    try:
        vector = model.encode(text, show_progress_bar=False)
        return vector.tolist()
    except Exception:
        log.warning("Failed to compute embedding", exc_info=True)
        return None


def load_embeddings(
    scope: str, project_dir: str | None = None
) -> dict[str, EmbeddingEntry]:
    """Load stored embeddings from disk.

    Returns an empty dict if the file doesn't exist or is corrupt.
    """
    path = _embeddings_path(scope, project_dir)
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Failed to load embeddings from %s", path, exc_info=True)
        return {}

    entries: dict[str, EmbeddingEntry] = {}
    for entry_id, data in raw.items():
        entries[entry_id] = EmbeddingEntry(
            entry_id=entry_id,
            vector=data.get("vector", []),
        )
    return entries


def save_embeddings(
    embeddings: dict[str, EmbeddingEntry],
    scope: str,
    project_dir: str | None = None,
) -> None:
    """Persist embeddings to disk."""
    path = _embeddings_path(scope, project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    raw = {
        eid: {"vector": e.vector}
        for eid, e in embeddings.items()
    }
    try:
        path.write_text(json.dumps(raw), encoding="utf-8")
    except OSError:
        log.warning("Failed to save embeddings to %s", path, exc_info=True)


def store_embedding(
    entry_id: str,
    content: str,
    scope: str,
    project_dir: str | None = None,
) -> bool:
    """Compute and store an embedding for a memory entry.

    Returns True if the embedding was stored, False if skipped
    (model unavailable or computation failed).
    """
    vector = compute_embedding(content)
    if vector is None:
        return False

    embeddings = load_embeddings(scope, project_dir)
    embeddings[entry_id] = EmbeddingEntry(entry_id=entry_id, vector=vector)
    save_embeddings(embeddings, scope, project_dir)
    return True


def remove_embedding(
    entry_id: str,
    scope: str,
    project_dir: str | None = None,
) -> None:
    """Remove a stored embedding for a memory entry."""
    embeddings = load_embeddings(scope, project_dir)
    if entry_id in embeddings:
        del embeddings[entry_id]
        save_embeddings(embeddings, scope, project_dir)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 if either vector is zero-length or dimensions differ.
    """
    if len(a) != len(b) or not a:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


@dataclass
class SimilarityResult:
    """A single semantic similarity match."""

    entry_id: str
    score: float


def find_similar(
    query: str,
    scope: str,
    project_dir: str | None = None,
    top_k: int = 10,
) -> list[SimilarityResult]:
    """Find the top-K most similar entries to a query by embedding similarity.

    Returns an empty list if the embedding model is unavailable or no
    embeddings are stored.
    """
    query_vector = compute_embedding(query)
    if query_vector is None:
        return []

    embeddings = load_embeddings(scope, project_dir)
    if not embeddings:
        return []

    similarities: list[SimilarityResult] = []
    for entry_id, entry in embeddings.items():
        score = _cosine_similarity(query_vector, entry.vector)
        similarities.append(SimilarityResult(entry_id=entry_id, score=score))

    similarities.sort(key=lambda s: s.score, reverse=True)
    return similarities[:top_k]


def rrf_merge(
    bm25_ids: list[str],
    embedding_ids: list[str],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge BM25 and embedding results using Reciprocal Rank Fusion.

    Args:
        bm25_ids: Entry IDs ordered by BM25 score (best first).
        embedding_ids: Entry IDs ordered by embedding similarity (best first).
        k: RRF constant (default 60, standard value).

    Returns:
        List of (entry_id, rrf_score) sorted by RRF score descending.
    """
    scores: dict[str, float] = {}

    for rank, eid in enumerate(bm25_ids, start=1):
        scores[eid] = scores.get(eid, 0.0) + 1.0 / (k + rank)

    for rank, eid in enumerate(embedding_ids, start=1):
        scores[eid] = scores.get(eid, 0.0) + 1.0 / (k + rank)

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return merged


def rebuild_all(
    provider,
    *,
    scope: str = "",
    project_dir: str | None = None,
) -> int:
    """Recompute embeddings for all existing memories.

    Args:
        provider: Memory provider to read entries from.
        scope: Limit to a specific scope. Empty for all scopes.
        project_dir: Project directory for storage paths.

    Returns:
        Number of entries processed.
    """
    if not is_available():
        log.warning("No embedding model available; cannot rebuild embeddings")
        return 0

    result = provider.list_entries(scope=scope, limit=10000)
    count = 0

    for entry in result.entries:
        entry_scope = entry.scope or "project"
        stored = store_embedding(
            entry_id=entry.entry_id,
            content=entry.content,
            scope=entry_scope,
            project_dir=project_dir,
        )
        if stored:
            count += 1

    return count
