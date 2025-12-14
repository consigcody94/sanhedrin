"""
Agent Router for intelligent task routing.

Routes tasks to appropriate agents based on various strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any

from sanhedrin.orchestration.catalog import AgentEntry

if TYPE_CHECKING:
    from sanhedrin.orchestration.catalog import AgentCatalog


class RoutingStrategy(str, Enum):
    """Available routing strategies."""

    ROUND_ROBIN = "round_robin"
    SKILL_MATCH = "skill_match"
    FIRST_AVAILABLE = "first_available"
    WEIGHTED = "weighted"
    RANDOM = "random"


class BaseRouter(ABC):
    """
    Abstract base for routing strategies.

    Routers select which agent should handle a given task.
    """

    @abstractmethod
    def select(
        self,
        agents: list[AgentEntry],
        context: dict[str, Any] | None = None,
    ) -> AgentEntry | None:
        """
        Select an agent from the list.

        Args:
            agents: Available agents
            context: Optional routing context

        Returns:
            Selected agent or None
        """
        ...


class RoundRobinRouter(BaseRouter):
    """
    Round-robin routing.

    Distributes tasks evenly across agents.
    """

    def __init__(self) -> None:
        self._index = 0

    def select(
        self,
        agents: list[AgentEntry],
        context: dict[str, Any] | None = None,
    ) -> AgentEntry | None:
        if not agents:
            return None

        agent = agents[self._index % len(agents)]
        self._index += 1
        return agent


class FirstAvailableRouter(BaseRouter):
    """
    First available routing.

    Selects the first healthy agent.
    """

    def select(
        self,
        agents: list[AgentEntry],
        context: dict[str, Any] | None = None,
    ) -> AgentEntry | None:
        for agent in agents:
            if agent.healthy:
                return agent
        return agents[0] if agents else None


class SkillMatchRouter(BaseRouter):
    """
    Skill-based routing.

    Selects agents based on required skills from context.
    """

    def select(
        self,
        agents: list[AgentEntry],
        context: dict[str, Any] | None = None,
    ) -> AgentEntry | None:
        if not agents:
            return None

        if not context:
            return agents[0]

        required_skills = context.get("skills", [])
        required_tags = context.get("tags", [])

        if not required_skills and not required_tags:
            return agents[0]

        # Score agents by skill/tag match
        scored: list[tuple[int, AgentEntry]] = []

        for agent in agents:
            score = 0

            # Check skills
            agent_skill_ids = {s.id for s in agent.skills}
            for skill in required_skills:
                if skill in agent_skill_ids:
                    score += 10  # High weight for exact skill match

            # Check tags
            agent_tags = agent.skill_tags
            for tag in required_tags:
                if tag in agent_tags:
                    score += 1  # Lower weight for tag match

            if score > 0:
                scored.append((score, agent))

        if scored:
            # Return highest scored
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]

        # No matches, return first
        return agents[0]


class WeightedRouter(BaseRouter):
    """
    Weighted routing.

    Routes based on agent weights (e.g., for load balancing).
    """

    def __init__(self, weights: dict[str, int] | None = None) -> None:
        """
        Initialize with optional weights.

        Args:
            weights: Map of agent name to weight (default 1)
        """
        self._weights = weights or {}
        self._counters: dict[str, int] = {}

    def set_weight(self, name: str, weight: int) -> None:
        """Set weight for an agent."""
        self._weights[name] = weight

    def select(
        self,
        agents: list[AgentEntry],
        context: dict[str, Any] | None = None,
    ) -> AgentEntry | None:
        if not agents:
            return None

        # Simple weighted selection using counters
        best_agent: AgentEntry | None = None
        best_ratio = float("inf")

        for agent in agents:
            if not agent.healthy:
                continue

            weight = self._weights.get(agent.name, 1)
            count = self._counters.get(agent.name, 0)

            # Ratio of calls to weight
            ratio = count / weight if weight > 0 else float("inf")

            if ratio < best_ratio:
                best_ratio = ratio
                best_agent = agent

        if best_agent:
            self._counters[best_agent.name] = (
                self._counters.get(best_agent.name, 0) + 1
            )

        return best_agent or (agents[0] if agents else None)


class RandomRouter(BaseRouter):
    """
    Random routing.

    Randomly selects from available agents.
    """

    def select(
        self,
        agents: list[AgentEntry],
        context: dict[str, Any] | None = None,
    ) -> AgentEntry | None:
        import random

        if not agents:
            return None

        healthy = [a for a in agents if a.healthy]
        pool = healthy if healthy else agents

        return random.choice(pool)


class AgentRouter:
    """
    Main router coordinating agent selection.

    Combines catalog with routing strategy.

    Example:
        >>> router = AgentRouter(catalog)
        >>> router.set_strategy(RoutingStrategy.SKILL_MATCH)
        >>> agent = router.route({"tags": ["coding"]})
    """

    STRATEGIES: dict[RoutingStrategy, type[BaseRouter]] = {
        RoutingStrategy.ROUND_ROBIN: RoundRobinRouter,
        RoutingStrategy.SKILL_MATCH: SkillMatchRouter,
        RoutingStrategy.FIRST_AVAILABLE: FirstAvailableRouter,
        RoutingStrategy.WEIGHTED: WeightedRouter,
        RoutingStrategy.RANDOM: RandomRouter,
    }

    def __init__(
        self,
        catalog: AgentCatalog,
        strategy: RoutingStrategy = RoutingStrategy.SKILL_MATCH,
    ) -> None:
        """
        Initialize router.

        Args:
            catalog: Agent catalog
            strategy: Default routing strategy
        """
        self.catalog = catalog
        self._strategy = strategy
        self._routers: dict[RoutingStrategy, BaseRouter] = {}

    def set_strategy(self, strategy: RoutingStrategy) -> None:
        """Set the default routing strategy."""
        self._strategy = strategy

    def get_router(self, strategy: RoutingStrategy) -> BaseRouter:
        """Get or create router for strategy."""
        if strategy not in self._routers:
            router_class = self.STRATEGIES.get(strategy)
            if router_class is None:
                raise ValueError(f"Unknown strategy: {strategy}")
            self._routers[strategy] = router_class()
        return self._routers[strategy]

    def route(
        self,
        context: dict[str, Any] | None = None,
        *,
        strategy: RoutingStrategy | None = None,
        healthy_only: bool = True,
    ) -> AgentEntry | None:
        """
        Route to an agent.

        Args:
            context: Routing context with skills/tags
            strategy: Override default strategy
            healthy_only: Only consider healthy agents

        Returns:
            Selected agent or None
        """
        # Get agents
        agents = self.catalog.list_agents(healthy_only=healthy_only)

        if not agents:
            return None

        # Pre-filter by tags if specified
        if context:
            tags = context.get("tags", [])
            skills = context.get("skills", [])

            if tags or skills:
                # Filter to agents with any matching capability
                filtered = []
                for agent in agents:
                    agent_skills = {s.id for s in agent.skills}
                    agent_tags = agent.skill_tags

                    if any(s in agent_skills for s in skills):
                        filtered.append(agent)
                    elif any(t in agent_tags for t in tags):
                        filtered.append(agent)

                if filtered:
                    agents = filtered

        # Route
        active_strategy = strategy or self._strategy
        router = self.get_router(active_strategy)

        return router.select(agents, context)

    def route_by_skill(self, skill_id: str) -> AgentEntry | None:
        """
        Route to agent with specific skill.

        Args:
            skill_id: Required skill

        Returns:
            Agent with the skill or None
        """
        agents = self.catalog.find_by_skill(skill_id)
        if not agents:
            return None

        # Filter healthy
        healthy = [a for a in agents if a.healthy]
        pool = healthy if healthy else agents

        router = self.get_router(self._strategy)
        return router.select(pool, {"skills": [skill_id]})

    def route_by_tags(
        self,
        tags: list[str],
        *,
        match_all: bool = False,
    ) -> AgentEntry | None:
        """
        Route to agent matching tags.

        Args:
            tags: Required tags
            match_all: Require all tags

        Returns:
            Matching agent or None
        """
        agents = self.catalog.find_by_tags(tags, match_all=match_all)
        if not agents:
            return None

        # Filter healthy
        healthy = [a for a in agents if a.healthy]
        pool = healthy if healthy else agents

        router = self.get_router(self._strategy)
        return router.select(pool, {"tags": tags})
