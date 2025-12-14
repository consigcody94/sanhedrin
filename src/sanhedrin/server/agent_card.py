"""
Agent Card builder.

Generates A2A-compliant Agent Cards from adapter metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sanhedrin.core.types import (
    AgentCard,
    AgentCapabilities,
    AgentAuthentication,
    AgentProvider,
)

if TYPE_CHECKING:
    from sanhedrin.adapters.base import BaseAdapter


class AgentCardBuilder:
    """
    Builds Agent Cards from adapter information.

    The Agent Card is served at /.well-known/agent.json and
    describes the agent's capabilities for discovery.

    Example:
        >>> builder = AgentCardBuilder(adapter, "http://localhost:8000")
        >>> card = builder.build()
        >>> print(card.model_dump_json(by_alias=True))
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        base_url: str,
        *,
        provider_name: str = "Sanhedrin",
        provider_url: str = "https://github.com/sanhedrin",
        version: str = "0.1.0",
        auth_schemes: list[str] | None = None,
    ) -> None:
        """
        Initialize Agent Card builder.

        Args:
            adapter: The adapter to build card for
            base_url: Base URL where agent is hosted
            provider_name: Provider organization name
            provider_url: Provider website URL
            version: Agent version string
            auth_schemes: Supported authentication schemes
        """
        self.adapter = adapter
        self.base_url = base_url.rstrip("/")
        self.provider_name = provider_name
        self.provider_url = provider_url
        self.version = version
        self.auth_schemes = auth_schemes or []

    def build(self) -> AgentCard:
        """
        Build the Agent Card.

        Returns:
            Complete Agent Card ready for serialization
        """
        return AgentCard(
            name=self.adapter.display_name,
            description=self.adapter.description,
            url=f"{self.base_url}/a2a",
            version=self.version,
            capabilities=self._build_capabilities(),
            skills=self.adapter.skills,
            provider=self._build_provider(),
            documentation_url=f"{self.base_url}/docs",
            authentication=self._build_authentication(),
        )

    def _build_capabilities(self) -> AgentCapabilities:
        """Build capabilities from adapter features."""
        return AgentCapabilities(
            streaming=self.adapter.supports_streaming,
            push_notifications=False,  # Not implemented yet
            state_transition_history=True,
        )

    def _build_provider(self) -> AgentProvider:
        """Build provider information."""
        return AgentProvider(
            organization=self.provider_name,
            url=self.provider_url,
        )

    def _build_authentication(self) -> AgentAuthentication | None:
        """Build authentication configuration."""
        if not self.auth_schemes:
            return None

        return AgentAuthentication(
            schemes=self.auth_schemes,
        )

    def to_dict(self) -> dict:
        """
        Build and serialize to dictionary.

        Returns:
            Agent Card as dictionary with camelCase keys
        """
        return self.build().model_dump(by_alias=True, exclude_none=True)


def build_agent_card(
    adapter: BaseAdapter,
    base_url: str,
    **kwargs,
) -> AgentCard:
    """
    Convenience function to build an Agent Card.

    Args:
        adapter: The adapter to build card for
        base_url: Base URL where agent is hosted
        **kwargs: Additional builder arguments

    Returns:
        Agent Card
    """
    builder = AgentCardBuilder(adapter, base_url, **kwargs)
    return builder.build()
