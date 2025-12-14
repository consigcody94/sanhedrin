"""
Agent Catalog for multi-agent management.

Tracks registered agents, their capabilities, and health status.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sanhedrin.core.types import AgentCard, AgentSkill

if TYPE_CHECKING:
    from sanhedrin.adapters.base import BaseAdapter


def utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


@dataclass
class AgentEntry:
    """Entry for a registered agent."""

    name: str
    adapter: BaseAdapter
    card: AgentCard | None = None
    healthy: bool = True
    last_health_check: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def skills(self) -> list[AgentSkill]:
        """Get agent skills."""
        return self.adapter.skills

    @property
    def skill_tags(self) -> set[str]:
        """Get all skill tags."""
        tags: set[str] = set()
        for skill in self.skills:
            tags.update(skill.tags)
        return tags


class AgentCatalog:
    """
    Catalog of registered agents.

    Provides:
    - Agent registration and discovery
    - Skill-based lookup
    - Health monitoring
    - Capability indexing

    Example:
        >>> catalog = AgentCatalog()
        >>> await catalog.register("claude", claude_adapter)
        >>> agents = catalog.find_by_skill("code-generation")
    """

    def __init__(self) -> None:
        """Initialize empty catalog."""
        self._agents: dict[str, AgentEntry] = {}
        self._skill_index: dict[str, set[str]] = {}  # skill_id -> agent_names
        self._tag_index: dict[str, set[str]] = {}  # tag -> agent_names

    async def register(
        self,
        name: str,
        adapter: BaseAdapter,
        *,
        initialize: bool = True,
        card: AgentCard | None = None,
    ) -> AgentEntry:
        """
        Register an agent.

        Args:
            name: Unique name for the agent
            adapter: The adapter instance
            initialize: Whether to initialize the adapter
            card: Optional pre-built agent card

        Returns:
            The agent entry

        Raises:
            ValueError: If name already registered
        """
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already registered")

        # Initialize if requested
        if initialize and not adapter.is_initialized:
            await adapter.initialize()

        # Create entry
        entry = AgentEntry(
            name=name,
            adapter=adapter,
            card=card,
            healthy=adapter.is_initialized,
            last_health_check=utc_now(),
        )

        # Store
        self._agents[name] = entry

        # Index skills
        for skill in adapter.skills:
            if skill.id not in self._skill_index:
                self._skill_index[skill.id] = set()
            self._skill_index[skill.id].add(name)

            # Index tags
            for tag in skill.tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = set()
                self._tag_index[tag].add(name)

        return entry

    def unregister(self, name: str) -> bool:
        """
        Remove an agent from the catalog.

        Args:
            name: Agent name

        Returns:
            True if removed, False if not found
        """
        if name not in self._agents:
            return False

        entry = self._agents[name]

        # Remove from indexes
        for skill in entry.adapter.skills:
            if skill.id in self._skill_index:
                self._skill_index[skill.id].discard(name)
            for tag in skill.tags:
                if tag in self._tag_index:
                    self._tag_index[tag].discard(name)

        del self._agents[name]
        return True

    def get(self, name: str) -> AgentEntry | None:
        """Get agent by name."""
        return self._agents.get(name)

    def get_adapter(self, name: str) -> BaseAdapter | None:
        """Get adapter by agent name."""
        entry = self._agents.get(name)
        return entry.adapter if entry else None

    def list_agents(self, *, healthy_only: bool = False) -> list[AgentEntry]:
        """
        List all registered agents.

        Args:
            healthy_only: Only return healthy agents

        Returns:
            List of agent entries
        """
        agents = list(self._agents.values())
        if healthy_only:
            agents = [a for a in agents if a.healthy]
        return agents

    def find_by_skill(self, skill_id: str) -> list[AgentEntry]:
        """
        Find agents with a specific skill.

        Args:
            skill_id: Skill identifier

        Returns:
            List of agents with the skill
        """
        names = self._skill_index.get(skill_id, set())
        return [self._agents[n] for n in names if n in self._agents]

    def find_by_tag(self, tag: str) -> list[AgentEntry]:
        """
        Find agents with a specific tag.

        Args:
            tag: Tag to search for

        Returns:
            List of agents with the tag
        """
        names = self._tag_index.get(tag, set())
        return [self._agents[n] for n in names if n in self._agents]

    def find_by_tags(
        self,
        tags: list[str],
        *,
        match_all: bool = False,
    ) -> list[AgentEntry]:
        """
        Find agents matching tags.

        Args:
            tags: Tags to search for
            match_all: If True, agent must have all tags

        Returns:
            List of matching agents
        """
        if not tags:
            return self.list_agents()

        if match_all:
            # Agent must have all tags
            result_names: set[str] | None = None
            for tag in tags:
                tag_names = self._tag_index.get(tag, set())
                if result_names is None:
                    result_names = tag_names.copy()
                else:
                    result_names &= tag_names

            names = result_names or set()
        else:
            # Agent must have any tag
            names: set[str] = set()
            for tag in tags:
                names.update(self._tag_index.get(tag, set()))

        return [self._agents[n] for n in names if n in self._agents]

    async def health_check_all(self) -> dict[str, bool]:
        """
        Run health checks on all agents.

        Returns:
            Dict mapping agent name to health status
        """
        results: dict[str, bool] = {}

        async def check_one(name: str, entry: AgentEntry) -> tuple[str, bool]:
            try:
                healthy = await entry.adapter.health_check()
                entry.healthy = healthy
                entry.last_health_check = utc_now()
                return name, healthy
            except Exception:
                entry.healthy = False
                entry.last_health_check = utc_now()
                return name, False

        tasks = [
            check_one(name, entry)
            for name, entry in self._agents.items()
        ]

        for coro in asyncio.as_completed(tasks):
            name, healthy = await coro
            results[name] = healthy

        return results

    async def health_check(self, name: str) -> bool:
        """
        Run health check on specific agent.

        Args:
            name: Agent name

        Returns:
            Health status
        """
        entry = self._agents.get(name)
        if entry is None:
            return False

        try:
            healthy = await entry.adapter.health_check()
            entry.healthy = healthy
            entry.last_health_check = utc_now()
            return healthy
        except Exception:
            entry.healthy = False
            entry.last_health_check = utc_now()
            return False

    def get_healthy_agents(self) -> list[AgentEntry]:
        """Get all healthy agents."""
        return [a for a in self._agents.values() if a.healthy]

    @property
    def all_skills(self) -> list[str]:
        """Get all available skill IDs."""
        return list(self._skill_index.keys())

    @property
    def all_tags(self) -> list[str]:
        """Get all available tags."""
        return list(self._tag_index.keys())

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def __repr__(self) -> str:
        names = ", ".join(self._agents.keys())
        return f"<AgentCatalog(agents=[{names}])>"
