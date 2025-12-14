"""
Sanhedrin Core Module.

Contains A2A Protocol types, state machine, and error definitions.
"""

from sanhedrin.core.types import (
    # Enums
    TaskState,
    Role,
    # Parts
    Part,
    TextPart,
    FilePart,
    DataPart,
    FileInfo,
    # Messages
    Message,
    # Tasks
    Task,
    TaskStatus,
    Artifact,
    # Agent Card
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    AgentAuthentication,
    AgentProvider,
    # JSON-RPC
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCError,
    # Streaming
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from sanhedrin.core.state_machine import (
    TaskStateMachine,
    StateTransitionRecord,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    ACTIVE_STATES,
)
from sanhedrin.core.errors import (
    SanhedrinError,
    A2AError,
    ErrorCode,
    TaskNotFoundError,
    InvalidStateTransitionError,
    AdapterError,
)

__all__ = [
    # Types
    "TaskState",
    "Role",
    "Part",
    "TextPart",
    "FilePart",
    "DataPart",
    "FileInfo",
    "Message",
    "Task",
    "TaskStatus",
    "Artifact",
    "AgentCard",
    "AgentSkill",
    "AgentCapabilities",
    "AgentAuthentication",
    "AgentProvider",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCError",
    "TaskStatusUpdateEvent",
    "TaskArtifactUpdateEvent",
    # State Machine
    "TaskStateMachine",
    "StateTransitionRecord",
    "VALID_TRANSITIONS",
    "TERMINAL_STATES",
    "ACTIVE_STATES",
    # Errors
    "SanhedrinError",
    "A2AError",
    "ErrorCode",
    "TaskNotFoundError",
    "InvalidStateTransitionError",
    "AdapterError",
]
