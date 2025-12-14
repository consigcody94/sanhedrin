"""
Sanhedrin CLI Adapters.

Provides unified interfaces for AI CLI tools:
- Claude Code CLI
- Gemini CLI
- Codex CLI
- Ollama (Python SDK)
"""

from sanhedrin.adapters.base import (
    BaseAdapter,
    AdapterConfig,
    ExecutionResult,
    StreamChunk,
)
from sanhedrin.adapters.registry import (
    AdapterRegistry,
    get_registry,
    register_default_adapters,
)

__all__ = [
    # Base
    "BaseAdapter",
    "AdapterConfig",
    "ExecutionResult",
    "StreamChunk",
    # Registry
    "AdapterRegistry",
    "get_registry",
    "register_default_adapters",
]


def get_adapter(name: str, **kwargs) -> BaseAdapter:
    """
    Convenience function to get an adapter by name.

    Args:
        name: Adapter identifier (e.g., "claude-code", "gemini-cli")
        **kwargs: Arguments passed to adapter constructor

    Returns:
        Adapter instance (not initialized)
    """
    register_default_adapters()
    return get_registry().create(name, **kwargs)
