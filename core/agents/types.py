from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass
class AgentResponse:
    content: str
    model: str | None = None
    stop_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass
class ModelConfig:
    provider: str = "claude_session"
    id: str | None = None


_DEFAULT_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]


@dataclass
class Charter:
    """Single source of truth for an agent's identity and configuration.

    Can be loaded from / saved to a YAML file::

        charter = Charter.from_yaml(Path(".loguetown/agents/charlie.yaml"))
        charter.instructions = "Updated instructions"
        charter.to_yaml(Path(".loguetown/agents/charlie.yaml"))
    """

    name: str
    role: str  # planner | implementer | reviewer | fixer | custom
    instructions: str = ""
    model: ModelConfig = field(default_factory=ModelConfig)
    max_tokens: int = 8096
    allowed_tools: list[str] = field(default_factory=lambda: list(_DEFAULT_TOOLS))
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return self.model.provider

    @property
    def model_id(self) -> str | None:
        return self.model.id

    # ------------------------------------------------------------------
    # YAML serialisation
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: Path) -> Charter:
        """Load a charter from a YAML file."""
        import yaml  # lazy import — only needed when loading from disk

        data = yaml.safe_load(path.read_text())
        model_data = data.get("model", {})
        return cls(
            name=data["name"],
            role=data["role"],
            instructions=data.get("instructions", ""),
            model=ModelConfig(
                provider=model_data.get("provider", "claude_session"),
                id=model_data.get("id"),
            ),
            max_tokens=data.get("max_tokens", 8096),
            allowed_tools=data.get("tools", {}).get("allowed", list(_DEFAULT_TOOLS)),
            metadata=data.get("metadata", {}),
        )

    def to_yaml(self, path: Path | None = None) -> str:
        """Serialise to YAML string, optionally writing to *path*."""
        import yaml

        data: dict = {
            "name": self.name,
            "role": self.role,
            "instructions": self.instructions,
            "model": {
                "provider": self.model.provider,
                **({"id": self.model.id} if self.model.id else {}),
            },
            "max_tokens": self.max_tokens,
            "tools": {"allowed": self.allowed_tools},
        }
        if self.metadata:
            data["metadata"] = self.metadata

        text = yaml.dump(data, default_flow_style=False, sort_keys=False)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return text
