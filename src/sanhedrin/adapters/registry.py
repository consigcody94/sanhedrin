"""
Adapter registry for dynamic adapter management.

Provides centralized registration, discovery, and factory methods
for CLI tool adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sanhedrin.core.errors import (
    AdapterNotFoundError,
    AdapterInitializationError,
)

if TYPE_CHECKING:
    from sanhedrin.adapters.base import BaseAdapter, AdapterConfig


class AdapterRegistry:
    """
    Registry for managing adapter types and instances.

    Supports:
    - Registration of adapter classes by name
    - Factory method for creating adapter instances
    - Discovery of available adapters
    - Singleton instance management

    Example:
        >>> registry = AdapterRegistry()
        >>> registry.register("claude-code", ClaudeCodeAdapter)
        >>> adapter = registry.create("claude-code")
        >>> await adapter.initialize()
    """

    _instance: AdapterRegistry | None = None
    _adapters: dict[str, type[BaseAdapter]]

    def __new__(cls) -> AdapterRegistry:
        """Singleton pattern for global registry."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._adapters = {}
        return cls._instance

    def register(
        self,
        name: str,
        adapter_class: type[BaseAdapter],
        *,
        override: bool = False,
    ) -> None:
        """
        Register an adapter class.

        Args:
            name: Unique identifier for the adapter
            adapter_class: The adapter class to register
            override: If True, allow overriding existing registrations

        Raises:
            ValueError: If name already registered and override is False
        """
        if name in self._adapters and not override:
            raise ValueError(
                f"Adapter '{name}' already registered. "
                f"Use override=True to replace."
            )
        self._adapters[name] = adapter_class

    def unregister(self, name: str) -> bool:
        """
        Remove an adapter registration.

        Args:
            name: Adapter identifier to remove

        Returns:
            True if adapter was removed, False if not found
        """
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False

    def get(self, name: str) -> type[BaseAdapter]:
        """
        Get an adapter class by name.

        Args:
            name: Adapter identifier

        Returns:
            The adapter class

        Raises:
            AdapterNotFoundError: If adapter not registered
        """
        if name not in self._adapters:
            available = ", ".join(self._adapters.keys()) or "none"
            raise AdapterNotFoundError(
                adapter=name,
                message=f"Available adapters: {available}",
            )
        return self._adapters[name]

    def create(
        self,
        name: str,
        config: AdapterConfig | None = None,
        **kwargs: Any,
    ) -> BaseAdapter:
        """
        Create an adapter instance.

        Args:
            name: Adapter identifier
            config: Optional adapter configuration
            **kwargs: Additional arguments passed to adapter constructor

        Returns:
            New adapter instance (not initialized)

        Raises:
            AdapterNotFoundError: If adapter not registered
            AdapterInitializationError: If instantiation fails
        """
        adapter_class = self.get(name)

        try:
            return adapter_class(config=config, **kwargs)
        except Exception as e:
            raise AdapterInitializationError(
                adapter=name,
                message=f"Failed to instantiate adapter: {e}",
            ) from e

    async def create_and_initialize(
        self,
        name: str,
        config: AdapterConfig | None = None,
        **kwargs: Any,
    ) -> BaseAdapter:
        """
        Create and initialize an adapter instance.

        Args:
            name: Adapter identifier
            config: Optional adapter configuration
            **kwargs: Additional arguments passed to adapter constructor

        Returns:
            Initialized adapter instance

        Raises:
            AdapterNotFoundError: If adapter not registered
            AdapterInitializationError: If initialization fails
        """
        adapter = self.create(name, config, **kwargs)
        await adapter.initialize()
        return adapter

    def list_adapters(self) -> list[str]:
        """
        List all registered adapter names.

        Returns:
            List of registered adapter identifiers
        """
        return list(self._adapters.keys())

    def is_registered(self, name: str) -> bool:
        """
        Check if an adapter is registered.

        Args:
            name: Adapter identifier

        Returns:
            True if registered
        """
        return name in self._adapters

    def clear(self) -> None:
        """Remove all registrations."""
        self._adapters.clear()

    def __contains__(self, name: str) -> bool:
        return self.is_registered(name)

    def __len__(self) -> int:
        return len(self._adapters)

    def __repr__(self) -> str:
        adapters = ", ".join(self._adapters.keys())
        return f"<AdapterRegistry(adapters=[{adapters}])>"


# Global registry instance
_registry: AdapterRegistry | None = None


def get_registry() -> AdapterRegistry:
    """Get the global adapter registry."""
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


def register_default_adapters() -> None:
    """
    Register all built-in adapters.

    Call this to populate the registry with standard adapters.
    """
    registry = get_registry()

    # Import adapters lazily to avoid circular imports
    from sanhedrin.adapters.claude_adapter import ClaudeCodeAdapter
    from sanhedrin.adapters.gemini_adapter import GeminiCLIAdapter
    from sanhedrin.adapters.codex_adapter import CodexCLIAdapter
    from sanhedrin.adapters.ollama_adapter import OllamaAdapter

    # Register with override to allow re-registration
    registry.register("claude-code", ClaudeCodeAdapter, override=True)
    registry.register("gemini-cli", GeminiCLIAdapter, override=True)
    registry.register("codex-cli", CodexCLIAdapter, override=True)
    registry.register("ollama", OllamaAdapter, override=True)

    # Also register short aliases
    registry.register("claude", ClaudeCodeAdapter, override=True)
    registry.register("gemini", GeminiCLIAdapter, override=True)
    registry.register("codex", CodexCLIAdapter, override=True)
