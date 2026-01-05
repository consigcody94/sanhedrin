"""
A2A Protocol compatible Pydantic models for Sanhedrin.

Based on A2A Protocol version 0.3.0
Specification: https://a2a-protocol.org/latest/specification/
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def generate_id() -> str:
    """Generate a unique identifier."""
    return str(uuid4())


def utc_now_iso() -> str:
    """Get current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class SanhedrinBaseModel(BaseModel):
    """Base model with consistent configuration for all Sanhedrin models."""

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


# ============================================================================
# Enums
# ============================================================================


class TaskState(str, Enum):
    """
    A2A Task lifecycle states.

    Reference: https://a2a-protocol.org/latest/specification/#task-states
    """

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    AUTH_REQUIRED = "auth-required"
    UNKNOWN = "unknown"


class Role(str, Enum):
    """Message sender role."""

    USER = "user"
    AGENT = "agent"


class PartKind(str, Enum):
    """Types of message parts."""

    TEXT = "text"
    FILE = "file"
    DATA = "data"


# ============================================================================
# Message Parts
# ============================================================================


class TextPart(SanhedrinBaseModel):
    """
    Text content within a message.

    The most common part type for natural language communication.
    """

    kind: Literal["text"] = "text"
    text: str = Field(..., description="The text content")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


class FileWithBytes(SanhedrinBaseModel):
    """File content as base64-encoded bytes."""

    bytes: str = Field(..., description="Base64-encoded file content")
    mime_type: str | None = Field(
        default=None, alias="mimeType", description="MIME type of the file"
    )
    name: str | None = Field(default=None, description="Original filename")


class FileWithUri(SanhedrinBaseModel):
    """File referenced by URI."""

    uri: str = Field(..., description="URI pointing to the file")
    mime_type: str | None = Field(
        default=None, alias="mimeType", description="MIME type of the file"
    )
    name: str | None = Field(default=None, description="Original filename")


class FilePart(SanhedrinBaseModel):
    """
    File content within a message.

    Can contain either inline bytes or a URI reference.
    """

    kind: Literal["file"] = "file"
    file: FileWithBytes | FileWithUri = Field(..., description="File content or URI")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


class DataPart(SanhedrinBaseModel):
    """
    Structured data within a message.

    Useful for passing JSON objects, configuration, or structured output.
    """

    kind: Literal["data"] = "data"
    data: dict[str, Any] = Field(..., description="Structured data payload")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


# Union type for all part kinds
Part = Annotated[Union[TextPart, FilePart, DataPart], Field(discriminator="kind")]


# ============================================================================
# Messages
# ============================================================================


class Message(SanhedrinBaseModel):
    """
    A2A Protocol Message.

    Messages are the primary unit of communication between clients and agents.
    Each message has a role (user or agent) and contains one or more parts.
    """

    message_id: str = Field(
        default_factory=generate_id,
        alias="messageId",
        description="Unique message identifier",
    )
    role: Role = Field(..., description="Role of the message sender")
    parts: list[Part] = Field(..., description="Content parts of the message")
    context_id: str | None = Field(
        default=None,
        alias="contextId",
        description="Conversation context identifier",
    )
    task_id: str | None = Field(
        default=None, alias="taskId", description="Associated task identifier"
    )
    reference_task_ids: list[str] | None = Field(
        default=None,
        alias="referenceTaskIds",
        description="Referenced task identifiers",
    )
    kind: Literal["message"] = "message"
    extensions: list[str] | None = Field(
        default=None, description="Active extension URIs"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


# ============================================================================
# Tasks
# ============================================================================


class TaskStatus(SanhedrinBaseModel):
    """
    Task status with optional status message.

    Represents the current state of a task at a point in time.
    """

    state: TaskState = Field(..., description="Current task state")
    message: Message | None = Field(
        default=None, description="Status message from agent"
    )
    timestamp: str | None = Field(
        default_factory=utc_now_iso, description="ISO 8601 timestamp"
    )


class Artifact(SanhedrinBaseModel):
    """
    Generated artifact from task execution.

    Artifacts are outputs produced by task execution, such as generated
    code, documents, or other content.
    """

    artifact_id: str = Field(
        default_factory=generate_id,
        alias="artifactId",
        description="Unique artifact identifier",
    )
    parts: list[Part] = Field(..., description="Content parts of the artifact")
    name: str | None = Field(default=None, description="Artifact name")
    description: str | None = Field(default=None, description="Artifact description")
    extensions: list[str] | None = Field(
        default=None, description="Active extension URIs"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


class Task(SanhedrinBaseModel):
    """
    A2A Protocol Task - the fundamental unit of work.

    Tasks represent work being performed by an agent. They progress through
    a defined lifecycle (submitted → working → completed/failed) and can
    contain message history and artifacts.
    """

    id: str = Field(default_factory=generate_id, description="Unique task identifier")
    context_id: str = Field(
        default_factory=generate_id,
        alias="contextId",
        description="Conversation context identifier",
    )
    status: TaskStatus = Field(..., description="Current task status")
    history: list[Message] | None = Field(
        default=None, description="Message history for this task"
    )
    artifacts: list[Artifact] | None = Field(
        default=None, description="Generated artifacts"
    )
    kind: Literal["task"] = "task"
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


# ============================================================================
# Agent Card
# ============================================================================


class AgentSkill(SanhedrinBaseModel):
    """
    Capability declaration for an agent.

    Skills describe what an agent can do, helping clients discover
    and select appropriate agents for their needs.
    """

    id: str = Field(..., description="Unique skill identifier")
    name: str = Field(..., description="Human-readable skill name")
    description: str = Field(..., description="Skill description")
    tags: list[str] = Field(default_factory=list, description="Skill tags for search")
    examples: list[str] | None = Field(
        default=None, description="Example prompts for this skill"
    )
    input_modes: list[str] | None = Field(
        default=None, alias="inputModes", description="Accepted input MIME types"
    )
    output_modes: list[str] | None = Field(
        default=None, alias="outputModes", description="Produced output MIME types"
    )


class AgentCapabilities(SanhedrinBaseModel):
    """
    Optional capabilities supported by an agent.

    Declares which A2A features the agent supports.
    """

    streaming: bool | None = Field(
        default=None, description="Supports SSE streaming responses"
    )
    push_notifications: bool | None = Field(
        default=None, alias="pushNotifications", description="Supports webhooks"
    )
    state_transition_history: bool | None = Field(
        default=None,
        alias="stateTransitionHistory",
        description="Tracks full state history",
    )
    extensions: list[dict[str, Any]] | None = Field(
        default=None, description="Supported extensions"
    )


class AgentProvider(SanhedrinBaseModel):
    """Agent provider information."""

    organization: str = Field(..., description="Organization name")
    url: str = Field(..., description="Organization URL")


class AgentInterface(SanhedrinBaseModel):
    """Transport interface declaration."""

    url: str = Field(..., description="Interface endpoint URL")
    protocol_binding: str = Field(
        default="HTTP+JSON",
        alias="protocolBinding",
        description="Transport protocol",
    )
    tenant: str | None = Field(default=None, description="Optional tenant identifier")


class SecurityScheme(SanhedrinBaseModel):
    """Base security scheme."""

    description: str | None = Field(default=None, description="Scheme description")


class APIKeySecurityScheme(SecurityScheme):
    """API Key authentication scheme."""

    location: Literal["header", "query", "cookie"] = Field(
        default="header", description="Where the API key is sent"
    )
    name: str = Field(default="X-API-Key", description="Header/parameter name")


class HTTPAuthSecurityScheme(SecurityScheme):
    """HTTP authentication scheme (Bearer, Basic, etc.)."""

    scheme: str = Field(default="bearer", description="HTTP auth scheme")
    bearer_format: str | None = Field(
        default=None, alias="bearerFormat", description="Format hint (e.g., JWT)"
    )


class AgentAuthentication(SanhedrinBaseModel):
    """Agent authentication configuration."""

    schemes: list[str] = Field(
        default_factory=list, description="Supported authentication schemes"
    )


class AgentCard(SanhedrinBaseModel):
    """
    A2A Agent Card - self-describing agent manifest.

    The Agent Card is the primary discovery mechanism in A2A. It describes
    an agent's identity, capabilities, skills, and how to communicate with it.

    Served at: `/.well-known/agent.json`
    """

    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    url: str = Field(..., description="Agent endpoint URL")
    version: str = Field(default="1.0.0", description="Agent version")
    protocol_version: str = Field(
        default="0.3.0", alias="protocolVersion", description="A2A protocol version"
    )

    capabilities: AgentCapabilities = Field(
        default_factory=AgentCapabilities, description="Supported capabilities"
    )
    skills: list[AgentSkill] = Field(
        default_factory=list, description="Agent skills"
    )

    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"],
        alias="defaultInputModes",
        description="Default accepted input types",
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"],
        alias="defaultOutputModes",
        description="Default output types",
    )

    provider: AgentProvider | None = Field(
        default=None, description="Provider information"
    )
    supported_interfaces: list[AgentInterface] | None = Field(
        default=None, alias="supportedInterfaces", description="Transport interfaces"
    )

    security_schemes: dict[str, Any] | None = Field(
        default=None, alias="securitySchemes", description="Available auth schemes"
    )
    security: list[dict[str, list[str]]] | None = Field(
        default=None, description="Required security"
    )

    documentation_url: str | None = Field(
        default=None, alias="documentationUrl", description="Documentation link"
    )
    icon_url: str | None = Field(
        default=None, alias="iconUrl", description="Agent icon URL"
    )
    authentication: AgentAuthentication | None = Field(
        default=None, description="Authentication configuration"
    )
    supports_authenticated_extended_card: bool = Field(
        default=False,
        alias="supportsAuthenticatedExtendedCard",
        description="Supports extended card endpoint",
    )


# ============================================================================
# JSON-RPC Types
# ============================================================================


class JSONRPCRequest(SanhedrinBaseModel):
    """JSON-RPC 2.0 Request."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int = Field(..., description="Request identifier")
    method: str = Field(..., description="Method name")
    params: dict[str, Any] | None = Field(
        default=None, description="Method parameters"
    )


class JSONRPCError(SanhedrinBaseModel):
    """JSON-RPC 2.0 Error object."""

    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Any | None = Field(default=None, description="Additional error data")


class JSONRPCSuccessResponse(SanhedrinBaseModel):
    """JSON-RPC 2.0 Success Response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = Field(..., description="Request identifier")
    result: Any = Field(..., description="Result value")


class JSONRPCErrorResponse(SanhedrinBaseModel):
    """JSON-RPC 2.0 Error Response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = Field(..., description="Request identifier")
    error: JSONRPCError = Field(..., description="Error details")


JSONRPCResponse = JSONRPCSuccessResponse | JSONRPCErrorResponse


# ============================================================================
# Request/Response Parameter Types
# ============================================================================


class MessageSendConfiguration(SanhedrinBaseModel):
    """Configuration for message/send requests."""

    accepted_output_modes: list[str] | None = Field(
        default=None, alias="acceptedOutputModes", description="Accepted output modes"
    )
    blocking: bool | None = Field(
        default=None, description="Wait for completion before responding"
    )
    history_length: int | None = Field(
        default=None, alias="historyLength", description="Messages to include in history"
    )
    push_notification_config: dict[str, Any] | None = Field(
        default=None, alias="pushNotificationConfig", description="Webhook config"
    )


class MessageSendParams(SanhedrinBaseModel):
    """Parameters for message/send method."""

    message: Message = Field(..., description="Message to send")
    configuration: MessageSendConfiguration | None = Field(
        default=None, description="Send configuration"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


class TaskQueryParams(SanhedrinBaseModel):
    """Parameters for tasks/get method."""

    id: str = Field(..., description="Task ID to retrieve")
    history_length: int | None = Field(
        default=None, alias="historyLength", description="History messages to include"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


class TaskIdParams(SanhedrinBaseModel):
    """Simple task ID parameters."""

    id: str = Field(..., description="Task ID")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


# ============================================================================
# Streaming Event Types
# ============================================================================


class TaskStatusUpdateEvent(SanhedrinBaseModel):
    """SSE event for task status changes."""

    kind: Literal["status-update"] = "status-update"
    task_id: str = Field(..., alias="taskId", description="Task identifier")
    context_id: str = Field(..., alias="contextId", description="Context identifier")
    status: TaskStatus = Field(..., description="Updated status")
    final: bool = Field(..., description="Whether this is the final update")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


class TaskArtifactUpdateEvent(SanhedrinBaseModel):
    """SSE event for artifact updates."""

    kind: Literal["artifact-update"] = "artifact-update"
    task_id: str = Field(..., alias="taskId", description="Task identifier")
    context_id: str = Field(..., alias="contextId", description="Context identifier")
    artifact: Artifact = Field(..., description="Artifact content")
    append: bool | None = Field(
        default=None, description="Append to existing artifact"
    )
    last_chunk: bool | None = Field(
        default=None, alias="lastChunk", description="Final chunk indicator"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata"
    )


# ============================================================================
# Push Notification Types
# ============================================================================


class PushNotificationAuthentication(SanhedrinBaseModel):
    """Authentication for push notification delivery."""

    schemes: list[str] = Field(..., description="Supported auth schemes")
    credentials: str | None = Field(
        default=None, description="Base64-encoded credentials"
    )


class PushNotificationConfig(SanhedrinBaseModel):
    """Push notification configuration."""

    url: str = Field(..., description="Webhook URL")
    token: str | None = Field(default=None, description="Client token for validation")
    authentication: PushNotificationAuthentication | None = Field(
        default=None, description="Auth config for webhook"
    )


class SetPushNotificationConfigParams(SanhedrinBaseModel):
    """Parameters for setting push notification config."""

    id: str = Field(..., description="Task ID")
    push_notification_config: PushNotificationConfig = Field(
        ..., alias="pushNotificationConfig", description="Notification config"
    )


# ============================================================================
# Helper Functions
# ============================================================================


def create_text_message(
    text: str,
    role: Role = Role.USER,
    context_id: str | None = None,
    task_id: str | None = None,
) -> Message:
    """Create a simple text message."""
    return Message(
        role=role,
        parts=[TextPart(text=text)],
        context_id=context_id,
        task_id=task_id,
    )


def create_task(
    state: TaskState = TaskState.SUBMITTED,
    message: Message | None = None,
    context_id: str | None = None,
) -> Task:
    """Create a new task with initial status."""
    return Task(
        context_id=context_id or generate_id(),
        status=TaskStatus(state=state, message=message),
    )
