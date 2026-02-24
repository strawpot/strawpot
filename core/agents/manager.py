from __future__ import annotations

from .agent import Agent
from .provider import AgentProvider
from .types import Charter


class AgentManager:
    """Registry for providers and agents.

    Usage::

        manager = AgentManager()
        manager.register_provider(ClaudeAPIProvider())

        charter = Charter(name="charlie", role="implementer", ...)
        agent = manager.create_agent(charter)

        response = await agent.run("Implement the login endpoint")
    """

    def __init__(self) -> None:
        self._providers: dict[str, AgentProvider] = {}
        self._agents: dict[str, Agent] = {}

    # ------------------------------------------------------------------
    # Provider registry
    # ------------------------------------------------------------------

    def register_provider(self, provider: AgentProvider) -> None:
        """Register a provider under its name. Overwrites any existing registration."""
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> AgentProvider | None:
        return self._providers.get(name)

    @property
    def providers(self) -> dict[str, AgentProvider]:
        return dict(self._providers)

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def create_agent(self, charter: Charter) -> Agent:
        """Instantiate an agent from a charter and register it.

        Raises ValueError if the charter's provider is not registered.
        Raises ValueError if an agent with the same name already exists.
        """
        if charter.provider not in self._providers:
            registered = list(self._providers)
            raise ValueError(
                f"Provider {charter.provider!r} not registered. "
                f"Registered providers: {registered}"
            )
        if charter.name in self._agents:
            raise ValueError(
                f"Agent {charter.name!r} already exists. "
                "Call remove_agent() first or use get_agent()."
            )

        provider = self._providers[charter.provider]
        agent = Agent(charter=charter, provider=provider)
        self._agents[charter.name] = agent
        return agent

    def get_agent(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def remove_agent(self, name: str) -> bool:
        """Remove an agent by name. Returns True if it existed."""
        return self._agents.pop(name, None) is not None

    @property
    def agents(self) -> dict[str, Agent]:
        return dict(self._agents)

    def __repr__(self) -> str:
        return (
            f"AgentManager("
            f"providers={list(self._providers)}, "
            f"agents={list(self._agents)})"
        )
