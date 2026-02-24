"""SkillManager — resolves skill pool directories for an agent session.

The three pools are passed to the agent at session start so it can read them
and generate ``CLAUDE.md``. The agent uses its native ``Glob`` and ``Read``
tools to explore skill content; no parsing happens on the Python side.

Construction
------------
From an already-resolved ``Charter`` (preferred in ``lt prime``)::

    manager = SkillManager.from_charter(charter, workdir)

From a workdir (reads identity from ``.loguetown/runtime/``)::

    manager = SkillManager.from_workdir(workdir)

Usage
-----

    pools = manager.pools()   # list[SkillPool] that exist on disk
"""

from __future__ import annotations

import json
from pathlib import Path

from .types import SkillPool


class SkillManager:
    """Resolves the global, project, and agent skill pool directories."""

    def __init__(
        self,
        workdir: Path,
        agent_name: str | None = None,
        global_root: Path | None = None,
    ) -> None:
        self._workdir = workdir.resolve()
        self._agent_name = agent_name
        self._global_root = (global_root or Path.home() / ".loguetown").resolve()

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_charter(
        cls,
        charter,  # core.agents.types.Charter — avoid circular import
        workdir: Path,
        global_root: Path | None = None,
    ) -> SkillManager:
        """Build from an already-resolved ``Charter``."""
        return cls(workdir=workdir, agent_name=charter.name, global_root=global_root)

    @classmethod
    def from_workdir(
        cls,
        workdir: Path,
        global_root: Path | None = None,
    ) -> SkillManager:
        """Build by reading agent identity from ``.loguetown/runtime/agent.json``."""
        workdir = workdir.resolve()
        agent_name: str | None = None

        agent_json = workdir / ".loguetown" / "runtime" / "agent.json"
        if agent_json.exists():
            try:
                identity = json.loads(agent_json.read_text())
                agent_name = identity.get("name")
            except (json.JSONDecodeError, OSError):
                pass

        return cls(workdir=workdir, agent_name=agent_name, global_root=global_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pools(self) -> list[SkillPool]:
        """Return all skill pools that exist on disk.

        Order: global → project → agent.
        Pools whose directories do not yet exist are omitted.
        """
        candidates = self._all_pools()
        return [p for p in candidates if p.exists]

    def all_pools(self) -> list[SkillPool]:
        """Return all configured pools regardless of whether they exist on disk.

        Useful for setup/display (e.g. ``lt init`` scaffolding).
        """
        return self._all_pools()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _all_pools(self) -> list[SkillPool]:
        result: list[SkillPool] = [
            SkillPool(path=self._global_root / "skills", scope="global"),
            SkillPool(path=self._workdir / ".loguetown" / "skills", scope="project"),
        ]
        if self._agent_name:
            result.append(
                SkillPool(
                    path=self._workdir / ".loguetown" / "skills" / self._agent_name,
                    scope="agent",
                )
            )
        return result
