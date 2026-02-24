from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# Pool scope — the three levels presented to agents at session start
PoolScope = Literal["global", "project", "agent"]


@dataclass
class SkillPool:
    """A directory of skill content at a specific scope level.

    Skills are organised as sub-folders inside the pool directory. Each
    sub-folder is a skill module and may contain any number of files.

    Directory layout::

        global  → ~/.strawpot/skills/
                      ├── personal-style/
                      └── security-baseline/

        project → <repo>/.strawpot/skills/
                      ├── architecture/
                      └── commit-guide/

        agent   → <repo>/.strawpot/skills/<agent-name>/
                      ├── typescript-patterns/
                      └── testing-conventions/
    """

    path: Path
    scope: PoolScope

    @property
    def exists(self) -> bool:
        return self.path.is_dir()

    def __repr__(self) -> str:
        return f"SkillPool(scope={self.scope!r}, path={str(self.path)!r})"


@dataclass
class SkillFile:
    """A single markdown file within a skill module.

    Used by CLI commands (``lt skills show``) and future tooling to inspect
    skill module content.

    Frontmatter format (optional)::

        ---
        description: One-line summary shown in the skills index.
        tags: [tag1, tag2]
        ---
    """

    path: Path
    title: str          # first H1/H2 heading or filename stem
    content: str        # full markdown text
    description: str = ""               # from frontmatter description: field
    tags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Stable slug identifier: filename stem with hyphens/spaces → underscores."""
        return self.path.stem.replace("-", "_").replace(" ", "_").lower()

    def __repr__(self) -> str:
        return f"SkillFile(name={self.name!r}, title={self.title!r})"
