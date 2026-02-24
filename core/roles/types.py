"""Role YAML types.

A Role is a named, reusable configuration template for agents.  Agent Charters
reference a role name; the role supplies default tools and model config that
the Charter may override.

File location: ``.strawpot/roles/<name>.yaml``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Role:
    """A named role definition loaded from YAML.

    Example YAML::

        name: implementer
        description: "Writes code to implement features and fix bugs"

        default_tools:
          allowed: [Bash, Read, Write, Edit, Glob, Grep]

        default_model:
          provider: claude_session
          id: claude-opus-4-6
    """

    name: str
    description: str = ""
    default_tools: dict = field(default_factory=dict)
    default_model: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # YAML serialisation
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: Path) -> Role:
        """Load a role from a YAML file."""
        import yaml

        data = yaml.safe_load(path.read_text())
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            default_tools=data.get("default_tools", {}),
            default_model=data.get("default_model", {}),
        )

    def to_yaml(self, path: Path | None = None) -> str:
        """Serialise to YAML string, optionally writing to *path*."""
        import yaml

        data: dict = {"name": self.name}
        if self.description:
            data["description"] = self.description
        if self.default_tools:
            data["default_tools"] = self.default_tools
        if self.default_model:
            data["default_model"] = self.default_model

        text = yaml.dump(data, default_flow_style=False, sort_keys=False)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return text

    def __repr__(self) -> str:
        return f"Role(name={self.name!r}, description={self.description!r})"
