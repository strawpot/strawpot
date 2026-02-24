from __future__ import annotations

from dataclasses import dataclass, field

from ..skills.types import SkillPool
from .types import Charter


@dataclass
class SessionContext:
    """Everything that gets injected into an agent's session at startup."""

    charter: Charter
    skill_pools: list[SkillPool] = field(default_factory=list)
    work: str | None = None       # current task/work description


class ContextBuilder:
    """Builds the markdown context string injected via the SessionStart hook.

    The output is printed by ``lt prime --hook`` and Claude Code prepends it
    to the agent's context window.

    Skills are organised as sub-folders inside three pool directories (global,
    project, agent). The agent discovers and reads skill content using its
    native ``Glob`` and ``Read`` tools. At the start of each session it should
    synthesise a ``CLAUDE.md`` in the working directory from the relevant skill
    modules so that knowledge is available throughout the session.

    Structure::

        # Identity
        You are <name>, a <role> agent.

        # Role Instructions
        <charter.instructions>

        # Skill Pools
        ...instruction + path table...

        # Current Work
        <work>
    """

    def build(self, ctx: SessionContext) -> str:
        parts: list[str] = []

        # --- Identity -------------------------------------------------------
        parts.append(
            f"# Identity\n\nYou are **{ctx.charter.name}**, "
            f"a {ctx.charter.role} agent."
        )

        # --- Role instructions ----------------------------------------------
        if ctx.charter.instructions.strip():
            parts.append(f"# Role Instructions\n\n{ctx.charter.instructions.strip()}")

        # --- Skill pools ----------------------------------------------------
        if ctx.skill_pools:
            rows = ["| Scope | Path |", "|-------|------|"]
            for pool in ctx.skill_pools:
                rows.append(f"| {pool.scope} | `{pool.path}` |")
            table = "\n".join(rows)

            parts.append(
                "# Skill Pools\n\n"
                "Your skill documentation lives in the directories below. "
                "Each sub-folder is a skill module and may contain any number of files.\n\n"
                "At the start of this session:\n"
                "1. Use `Glob` and `Read` to explore the skill modules relevant to your work.\n"
                "2. Synthesise the applicable guidelines into `CLAUDE.md` in your working directory.\n"
                "3. Claude Code will pick up `CLAUDE.md` automatically in future sessions.\n\n"
                + table
            )

        # --- Current work ---------------------------------------------------
        if ctx.work and ctx.work.strip():
            parts.append(f"# Current Work\n\n{ctx.work.strip()}")

        return "\n\n".join(parts)
