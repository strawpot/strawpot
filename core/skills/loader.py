"""SkillsLoader — scans skill pool directories.

Skills are folder-based modules.  Each module is a sub-directory within a
pool.  ``SkillsLoader`` scans a pool directory and returns the module names
and optional descriptions — it does **not** load file content into Python
(the agent does that itself using ``Glob`` and ``Read`` at session start).

Usage::

    pool = SkillPool(path=Path(".loguetown/skills"), scope="project")
    modules = SkillsLoader.list_modules(pool)
    # → [Path(".loguetown/skills/commit-guide"), ...]

    desc = SkillsLoader.module_description(modules[0])
    # → "Commit message style guide"

    files = SkillsLoader.list_files(modules[0])
    # → [SkillFile(name="guide", title="Commit Guide", ...)]
"""

from __future__ import annotations

import re
from pathlib import Path

from .types import SkillFile, SkillPool

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,2}\s+(.+)", re.MULTILINE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_title(content: str, fallback: str) -> str:
    body = _FRONTMATTER_RE.sub("", content, count=1)
    m = _HEADING_RE.search(body)
    return m.group(1).strip() if m else fallback


def _extract_description(content: str) -> str:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return ""
    fm = m.group(1)
    desc_match = re.search(r"description:\s*(.+)", fm)
    if not desc_match:
        return ""
    return desc_match.group(1).strip().strip("\"'")


def _extract_tags(content: str) -> list[str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return []
    fm = m.group(1)
    tag_match = re.search(r"tags:\s*\[([^\]]*)\]", fm)
    if not tag_match:
        return []
    return [t.strip() for t in tag_match.group(1).split(",") if t.strip()]


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# SkillsLoader
# ---------------------------------------------------------------------------


class SkillsLoader:
    """Scans skill pool directories to enumerate skill modules and files."""

    @staticmethod
    def list_modules(pool: SkillPool) -> list[Path]:
        """Return all skill module directories in *pool*, sorted by name.

        Only directories that exist on disk are returned. Hidden directories
        (names starting with ``.``) are excluded.
        """
        if not pool.exists:
            return []
        return sorted(
            [
                d
                for d in pool.path.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ],
            key=lambda d: d.name,
        )

    @staticmethod
    def module_description(module_dir: Path) -> str:
        """Return a one-line description for a skill module.

        Tries, in order:
        1. ``README.md`` frontmatter ``description:`` field
        2. ``README.md`` first heading
        3. First ``.md`` file frontmatter ``description:`` field
        4. First ``.md`` file first heading
        5. Empty string if nothing is found
        """
        for candidate in ("README.md", "readme.md"):
            md = module_dir / candidate
            if md.exists():
                content = _safe_read(md)
                desc = _extract_description(content)
                if desc:
                    return desc
                title = _extract_title(content, "")
                if title:
                    return title

        for md in sorted(module_dir.glob("*.md")):
            content = _safe_read(md)
            desc = _extract_description(content)
            if desc:
                return desc
            title = _extract_title(content, "")
            if title:
                return title

        return ""

    @staticmethod
    def list_files(module_dir: Path) -> list[SkillFile]:
        """Return all ``.md`` files within *module_dir* as :class:`SkillFile` objects.

        Files are discovered recursively (sub-directories are included).
        Results are sorted by path.
        """
        if not module_dir.is_dir():
            return []
        result = []
        for path in sorted(module_dir.rglob("*.md")):
            content = _safe_read(path)
            result.append(
                SkillFile(
                    path=path,
                    title=_extract_title(content, path.stem),
                    content=content,
                    description=_extract_description(content),
                    tags=_extract_tags(content),
                )
            )
        return result
