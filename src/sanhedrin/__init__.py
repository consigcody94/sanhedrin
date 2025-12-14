"""
Sanhedrin - A2A Protocol Multi-Agent Coordination.

The Council of AI Agents: Unifying Claude Code, Gemini CLI,
Codex CLI, and Ollama under the A2A Protocol.
"""

__version__ = "0.1.0"
__author__ = "Sanhedrin Contributors"

from sanhedrin.core.types import (
    TaskState,
    Role,
    Message,
    Task,
    TaskStatus,
    AgentCard,
    AgentSkill,
)
from sanhedrin.adapters import (
    BaseAdapter,
    AdapterConfig,
    ExecutionResult,
    get_adapter,
)

__all__ = [
    "__version__",
    # Core Types
    "TaskState",
    "Role",
    "Message",
    "Task",
    "TaskStatus",
    "AgentCard",
    "AgentSkill",
    # Adapters
    "BaseAdapter",
    "AdapterConfig",
    "ExecutionResult",
    "get_adapter",
]
