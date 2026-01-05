"""
Tests for core types.
"""

import pytest

from sanhedrin.core.types import (
    TaskState,
    TaskStatus,
    Message,
    Role,
    TextPart,
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
    Artifact,
    Task,
    AgentSkill,
    AgentCapabilities,
    AgentCard,
    JSONRPCRequest,
    JSONRPCSuccessResponse,
    JSONRPCErrorResponse,
    JSONRPCError,
)


class TestTaskState:
    """Tests for TaskState enum."""

    def test_all_states_exist(self) -> None:
        """All expected states exist."""
        assert TaskState.SUBMITTED
        assert TaskState.WORKING
        assert TaskState.COMPLETED
        assert TaskState.FAILED
        assert TaskState.CANCELED
        assert TaskState.INPUT_REQUIRED
        assert TaskState.AUTH_REQUIRED
        assert TaskState.REJECTED
        assert TaskState.UNKNOWN

    def test_state_values(self) -> None:
        """States have correct string values."""
        assert TaskState.SUBMITTED.value == "submitted"
        assert TaskState.COMPLETED.value == "completed"


class TestTaskStatus:
    """Tests for TaskStatus model."""

    def test_minimal_status(self) -> None:
        """Create status with minimal fields."""
        status = TaskStatus(state=TaskState.SUBMITTED)

        assert status.state == TaskState.SUBMITTED

    def test_status_with_message(self) -> None:
        """Create status with message."""
        msg = Message(role=Role.AGENT, parts=[TextPart(text="Working...")])
        status = TaskStatus(state=TaskState.WORKING, message=msg)

        assert status.message is not None
        assert status.timestamp is not None


class TestMessage:
    """Tests for Message model."""

    def test_user_message(self) -> None:
        """Create user message."""
        msg = Message(
            role=Role.USER,
            parts=[TextPart(text="Hello")],
        )

        assert msg.role == Role.USER
        assert len(msg.parts) == 1

    def test_agent_message(self) -> None:
        """Create agent message."""
        msg = Message(
            role=Role.AGENT,
            parts=[TextPart(text="Response")],
        )

        assert msg.role == Role.AGENT

    def test_message_with_context(self) -> None:
        """Create message with context and task IDs."""
        msg = Message(
            role=Role.USER,
            parts=[TextPart(text="Hello")],
            contextId="ctx-123",
            taskId="task-456",
        )

        assert msg.context_id == "ctx-123"
        assert msg.task_id == "task-456"


class TestParts:
    """Tests for message part types."""

    def test_text_part(self) -> None:
        """Create text part."""
        part = TextPart(text="Hello, world!")

        assert part.kind == "text"
        assert part.text == "Hello, world!"

    def test_data_part(self) -> None:
        """Create data part."""
        part = DataPart(
            data={"key": "value"},
        )

        assert part.kind == "data"
        assert part.data["key"] == "value"

    def test_file_part_with_bytes(self) -> None:
        """Create file part with bytes."""
        file_content = FileWithBytes(
            bytes="SGVsbG8gV29ybGQ=",  # base64 "Hello World"
            mimeType="text/plain",
            name="test.txt",
        )
        part = FilePart(file=file_content)

        assert part.kind == "file"
        assert part.file.name == "test.txt"

    def test_file_part_with_uri(self) -> None:
        """Create file part with URI."""
        file_ref = FileWithUri(
            uri="https://example.com/file.py",
            mimeType="text/x-python",
            name="example.py",
        )
        part = FilePart(file=file_ref)

        assert part.kind == "file"
        # The file is typed as union, access via the actual type
        assert isinstance(part.file, FileWithUri)
        assert part.file.uri == "https://example.com/file.py"


class TestArtifact:
    """Tests for Artifact model."""

    def test_create_artifact(self) -> None:
        """Create artifact with parts."""
        artifact = Artifact(
            name="response",
            parts=[TextPart(text="Content")],
        )

        assert artifact.artifact_id is not None
        assert artifact.name == "response"
        assert len(artifact.parts) == 1

    def test_artifact_with_metadata(self) -> None:
        """Create artifact with metadata."""
        artifact = Artifact(
            name="code",
            parts=[TextPart(text="print('hello')")],
            metadata={"language": "python"},
        )

        assert artifact.metadata is not None
        assert artifact.metadata["language"] == "python"


class TestTask:
    """Tests for Task model."""

    def test_create_task(self) -> None:
        """Create complete task."""
        status = TaskStatus(state=TaskState.SUBMITTED)
        message = Message(
            role=Role.USER,
            parts=[TextPart(text="Hello")],
        )

        task = Task(
            id="task-123",
            contextId="ctx-456",
            status=status,
            history=[message],
        )

        assert task.id == "task-123"
        assert task.status.state == TaskState.SUBMITTED
        assert task.history is not None
        assert len(task.history) == 1


class TestAgentSkill:
    """Tests for AgentSkill model."""

    def test_create_skill(self) -> None:
        """Create skill with all fields."""
        skill = AgentSkill(
            id="code-gen",
            name="Code Generation",
            description="Generate code in various languages",
            tags=["coding", "programming"],
            examples=["Write a Python function"],
        )

        assert skill.id == "code-gen"
        assert "coding" in skill.tags


class TestAgentCapabilities:
    """Tests for AgentCapabilities model."""

    def test_default_capabilities(self) -> None:
        """Default capabilities."""
        caps = AgentCapabilities()

        # Defaults are None, not False
        assert caps.streaming is None
        assert caps.push_notifications is None

    def test_custom_capabilities(self) -> None:
        """Custom capabilities."""
        caps = AgentCapabilities(
            streaming=True,
            pushNotifications=True,
            stateTransitionHistory=True,
        )

        assert caps.streaming is True
        assert caps.push_notifications is True


class TestJSONRPCRequest:
    """Tests for JSON-RPC request model."""

    def test_minimal_request(self) -> None:
        """Create minimal request."""
        request = JSONRPCRequest(
            id="req-123",
            method="test/method",
        )

        assert request.jsonrpc == "2.0"
        assert request.method == "test/method"

    def test_request_with_params(self) -> None:
        """Create request with parameters."""
        request = JSONRPCRequest(
            id=1,
            method="message/send",
            params={"message": {"role": "user"}},
        )

        assert request.params is not None
        assert request.params["message"]["role"] == "user"


class TestJSONRPCResponse:
    """Tests for JSON-RPC response model."""

    def test_success_response(self) -> None:
        """Create success response."""
        response = JSONRPCSuccessResponse(
            id="req-123",
            result={"status": "ok"},
        )

        assert response.id == "req-123"
        assert response.result["status"] == "ok"

    def test_error_response(self) -> None:
        """Create error response."""
        error = JSONRPCError(
            code=-32600,
            message="Invalid request",
        )
        response = JSONRPCErrorResponse(
            id="req-123",
            error=error,
        )

        assert response.error.code == -32600
        assert response.error.message == "Invalid request"
