"""
Custom exceptions for Sanhedrin.

Includes A2A Protocol compliant error codes and custom exceptions
for adapter, server, and client operations.

Error codes follow A2A Protocol specification:
- JSON-RPC standard errors: -32700 to -32600
- A2A specific errors: -32001 to -32099
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sanhedrin.core.types import TaskState


# ============================================================================
# JSON-RPC Error Codes (Standard)
# ============================================================================

class ErrorCode:
    """JSON-RPC 2.0 and A2A error codes."""

    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # A2A specific errors
    TASK_NOT_FOUND = -32001
    TASK_NOT_CANCELABLE = -32002
    PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
    UNSUPPORTED_OPERATION = -32004
    CONTENT_TYPE_NOT_SUPPORTED = -32005
    INVALID_AGENT_CARD = -32006
    AUTHENTICATION_REQUIRED = -32007
    AUTHORIZATION_FAILED = -32008
    VERSION_NOT_SUPPORTED = -32009


# ============================================================================
# Base Exceptions
# ============================================================================


class SanhedrinError(Exception):
    """Base exception for all Sanhedrin errors."""

    def __init__(
        self,
        message: str,
        code: int = ErrorCode.INTERNAL_ERROR,
        data: Any | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.data = data
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-RPC error format."""
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result


class A2AError(SanhedrinError):
    """Base exception for A2A protocol errors."""

    pass


# ============================================================================
# JSON-RPC Errors
# ============================================================================


class ParseError(SanhedrinError):
    """Invalid JSON was received."""

    def __init__(self, message: str = "Parse error", data: Any | None = None) -> None:
        super().__init__(message, ErrorCode.PARSE_ERROR, data)


class InvalidRequestError(SanhedrinError):
    """The JSON sent is not a valid Request object."""

    def __init__(
        self, message: str = "Invalid request", data: Any | None = None
    ) -> None:
        super().__init__(message, ErrorCode.INVALID_REQUEST, data)


class MethodNotFoundError(SanhedrinError):
    """The method does not exist or is not available."""

    def __init__(self, method: str, data: Any | None = None) -> None:
        super().__init__(
            f"Method not found: {method}",
            ErrorCode.METHOD_NOT_FOUND,
            data,
        )
        self.method = method


class InvalidParamsError(SanhedrinError):
    """Invalid method parameters."""

    def __init__(
        self, message: str = "Invalid params", data: Any | None = None
    ) -> None:
        super().__init__(message, ErrorCode.INVALID_PARAMS, data)


class InternalError(SanhedrinError):
    """Internal JSON-RPC error."""

    def __init__(
        self, message: str = "Internal error", data: Any | None = None
    ) -> None:
        super().__init__(message, ErrorCode.INTERNAL_ERROR, data)


# ============================================================================
# A2A Protocol Errors
# ============================================================================


class TaskNotFoundError(A2AError):
    """The specified task was not found."""

    def __init__(self, task_id: str, data: Any | None = None) -> None:
        super().__init__(
            f"Task not found: {task_id}",
            ErrorCode.TASK_NOT_FOUND,
            data,
        )
        self.task_id = task_id


class TaskNotCancelableError(A2AError):
    """The task cannot be canceled in its current state."""

    def __init__(
        self,
        task_id: str,
        current_state: str,
        data: Any | None = None,
    ) -> None:
        super().__init__(
            f"Task {task_id} cannot be canceled (state: {current_state})",
            ErrorCode.TASK_NOT_CANCELABLE,
            data,
        )
        self.task_id = task_id
        self.current_state = current_state


class PushNotificationNotSupportedError(A2AError):
    """Push notifications are not supported by this agent."""

    def __init__(self, data: Any | None = None) -> None:
        super().__init__(
            "Push notifications not supported",
            ErrorCode.PUSH_NOTIFICATION_NOT_SUPPORTED,
            data,
        )


class UnsupportedOperationError(A2AError):
    """The requested operation is not supported."""

    def __init__(self, operation: str, data: Any | None = None) -> None:
        super().__init__(
            f"Unsupported operation: {operation}",
            ErrorCode.UNSUPPORTED_OPERATION,
            data,
        )
        self.operation = operation


class ContentTypeNotSupportedError(A2AError):
    """The content type is not supported."""

    def __init__(
        self,
        content_type: str,
        supported: list[str] | None = None,
        data: Any | None = None,
    ) -> None:
        msg = f"Content type not supported: {content_type}"
        if supported:
            msg += f" (supported: {', '.join(supported)})"
        super().__init__(msg, ErrorCode.CONTENT_TYPE_NOT_SUPPORTED, data)
        self.content_type = content_type
        self.supported = supported


class InvalidAgentCardError(A2AError):
    """The agent card is invalid or malformed."""

    def __init__(self, message: str, data: Any | None = None) -> None:
        super().__init__(message, ErrorCode.INVALID_AGENT_CARD, data)


class AuthenticationRequiredError(A2AError):
    """Authentication is required for this operation."""

    def __init__(
        self, message: str = "Authentication required", data: Any | None = None
    ) -> None:
        super().__init__(message, ErrorCode.AUTHENTICATION_REQUIRED, data)


class AuthorizationFailedError(A2AError):
    """Authorization failed for this operation."""

    def __init__(
        self, message: str = "Authorization failed", data: Any | None = None
    ) -> None:
        super().__init__(message, ErrorCode.AUTHORIZATION_FAILED, data)


class VersionNotSupportedError(A2AError):
    """The requested protocol version is not supported."""

    def __init__(
        self,
        requested_version: str,
        supported_versions: list[str] | None = None,
        data: Any | None = None,
    ) -> None:
        msg = f"Protocol version not supported: {requested_version}"
        if supported_versions:
            msg += f" (supported: {', '.join(supported_versions)})"
        super().__init__(msg, ErrorCode.VERSION_NOT_SUPPORTED, data)
        self.requested_version = requested_version
        self.supported_versions = supported_versions


# ============================================================================
# State Machine Errors
# ============================================================================


class InvalidStateTransitionError(SanhedrinError):
    """Invalid task state transition attempted."""

    def __init__(
        self,
        from_state: "TaskState",
        to_state: "TaskState",
        valid_transitions: set["TaskState"] | None = None,
    ) -> None:
        msg = f"Invalid state transition: {from_state.value} -> {to_state.value}"
        if valid_transitions:
            valid_str = ", ".join(s.value for s in valid_transitions)
            msg += f" (valid: {valid_str})"

        super().__init__(msg, ErrorCode.INVALID_REQUEST)
        self.from_state = from_state
        self.to_state = to_state
        self.valid_transitions = valid_transitions


# ============================================================================
# Adapter Errors
# ============================================================================


class AdapterError(SanhedrinError):
    """Base exception for adapter errors."""

    def __init__(
        self,
        adapter: str,
        message: str,
        code: int = ErrorCode.INTERNAL_ERROR,
        data: Any | None = None,
    ) -> None:
        super().__init__(f"[{adapter}] {message}", code, data)
        self.adapter = adapter


class AdapterInitializationError(AdapterError):
    """Adapter failed to initialize."""

    def __init__(self, adapter: str, message: str, data: Any | None = None) -> None:
        super().__init__(adapter, f"Initialization failed: {message}", data=data)


class AdapterExecutionError(AdapterError):
    """Adapter execution failed."""

    def __init__(
        self,
        adapter: str,
        message: str,
        exit_code: int | None = None,
        data: Any | None = None,
    ) -> None:
        super().__init__(adapter, f"Execution failed: {message}", data=data)
        self.exit_code = exit_code


class AdapterNotFoundError(SanhedrinError):
    """Requested adapter not found in registry."""

    def __init__(
        self, name: str, available: list[str] | None = None
    ) -> None:
        msg = f"Adapter not found: {name}"
        if available:
            msg += f" (available: {', '.join(available)})"
        super().__init__(msg, ErrorCode.UNSUPPORTED_OPERATION)
        self.name = name
        self.available = available


class AdapterTimeoutError(AdapterError):
    """Adapter execution timed out."""

    def __init__(
        self,
        adapter: str,
        timeout: float,
        data: Any | None = None,
    ) -> None:
        super().__init__(
            adapter,
            f"Execution timed out after {timeout}s",
            data=data,
        )
        self.timeout = timeout


class CLINotFoundError(AdapterError):
    """CLI tool not found on the system."""

    def __init__(
        self,
        adapter: str,
        cli_command: str,
        install_hint: str | None = None,
    ) -> None:
        msg = f"CLI not found: {cli_command}"
        if install_hint:
            msg += f" - {install_hint}"
        super().__init__(adapter, msg)
        self.cli_command = cli_command
        self.install_hint = install_hint


# ============================================================================
# Client Errors
# ============================================================================


class ClientError(SanhedrinError):
    """Base exception for client errors."""

    pass


class AgentNotFoundError(ClientError):
    """Agent not found at the specified URL."""

    def __init__(self, url: str, data: Any | None = None) -> None:
        super().__init__(f"Agent not found at: {url}", ErrorCode.TASK_NOT_FOUND, data)
        self.url = url


class AgentConnectionError(ClientError):
    """Failed to connect to agent."""

    def __init__(self, url: str, reason: str | None = None) -> None:
        msg = f"Failed to connect to agent at: {url}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg, ErrorCode.INTERNAL_ERROR)
        self.url = url
        self.reason = reason


class TaskExecutionError(ClientError):
    """Task execution failed."""

    def __init__(
        self,
        task_id: str | None = None,
        message: str = "Task execution failed",
        code: int = ErrorCode.INTERNAL_ERROR,
    ) -> None:
        super().__init__(message, code)
        self.task_id = task_id


# ============================================================================
# Storage Errors
# ============================================================================


class StorageError(SanhedrinError):
    """Base exception for storage errors."""

    pass


class TaskStorageError(StorageError):
    """Error storing or retrieving task."""

    def __init__(self, task_id: str, operation: str, reason: str) -> None:
        super().__init__(f"Task {operation} failed for {task_id}: {reason}")
        self.task_id = task_id
        self.operation = operation
        self.reason = reason


# ============================================================================
# Configuration Errors
# ============================================================================


class ConfigurationError(SanhedrinError):
    """Configuration error."""

    def __init__(self, message: str, data: Any | None = None) -> None:
        super().__init__(message, ErrorCode.INVALID_REQUEST, data)
