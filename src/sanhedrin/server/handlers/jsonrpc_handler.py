"""
JSON-RPC 2.0 request handler.

Implements A2A Protocol methods:
- message/send: Send message and receive response
- message/stream: Send message with streaming response
- tasks/get: Retrieve task by ID
- tasks/cancel: Cancel a running task
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, AsyncIterator

from sanhedrin.core.types import (
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCError,
    Message,
    Role,
    TextPart,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from sanhedrin.core.errors import (
    ErrorCode,
    TaskNotFoundError,
    InvalidStateTransitionError,
    A2AError,
)

if TYPE_CHECKING:
    from sanhedrin.server.task_manager import TaskManager


class JSONRPCHandler:
    """
    Handles JSON-RPC 2.0 requests per A2A Protocol.

    Supported methods:
    - message/send: Non-streaming message handling
    - message/stream: SSE streaming response
    - tasks/get: Retrieve task status and history
    - tasks/cancel: Cancel a task

    Example:
        >>> handler = JSONRPCHandler(task_manager)
        >>> response = await handler.handle(request)
    """

    # Supported A2A methods
    METHODS = {
        "message/send",
        "message/stream",
        "tasks/get",
        "tasks/cancel",
        "tasks/pushNotificationConfig/set",
        "tasks/pushNotificationConfig/get",
    }

    def __init__(self, task_manager: TaskManager) -> None:
        """
        Initialize handler.

        Args:
            task_manager: Task manager for execution
        """
        self.task_manager = task_manager

    async def handle(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """
        Handle a JSON-RPC request.

        Args:
            request: The request to handle

        Returns:
            JSON-RPC response
        """
        # Validate method
        if request.method not in self.METHODS:
            return self._error_response(
                request.id,
                ErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {request.method}",
            )

        try:
            # Dispatch to method handler
            if request.method == "message/send":
                result = await self._handle_message_send(request.params)
            elif request.method == "message/stream":
                # Streaming is handled separately
                result = {"error": "Use stream endpoint for message/stream"}
            elif request.method == "tasks/get":
                result = await self._handle_tasks_get(request.params)
            elif request.method == "tasks/cancel":
                result = await self._handle_tasks_cancel(request.params)
            elif request.method == "tasks/pushNotificationConfig/set":
                result = await self._handle_push_config_set(request.params)
            elif request.method == "tasks/pushNotificationConfig/get":
                result = await self._handle_push_config_get(request.params)
            else:
                return self._error_response(
                    request.id,
                    ErrorCode.METHOD_NOT_FOUND,
                    f"Method not implemented: {request.method}",
                )

            return JSONRPCResponse(
                id=request.id,
                result=result,
            )

        except TaskNotFoundError as e:
            return self._error_response(
                request.id,
                ErrorCode.TASK_NOT_FOUND,
                str(e),
            )
        except InvalidStateTransitionError as e:
            return self._error_response(
                request.id,
                ErrorCode.INVALID_STATE_TRANSITION,
                str(e),
            )
        except A2AError as e:
            return self._error_response(
                request.id,
                e.code,
                e.message,
            )
        except Exception as e:
            return self._error_response(
                request.id,
                ErrorCode.INTERNAL_ERROR,
                f"Internal error: {str(e)}",
            )

    async def handle_stream(
        self,
        request: JSONRPCRequest,
    ) -> AsyncIterator[str]:
        """
        Handle a streaming JSON-RPC request.

        Yields SSE-formatted events.

        Args:
            request: The request to handle

        Yields:
            SSE event strings
        """
        if request.method != "message/stream":
            yield self._sse_event(
                "error",
                {"error": "Only message/stream supports streaming"},
            )
            return

        try:
            # Extract message from params
            message = self._extract_message(request.params)

            # Create task
            context_id = request.params.get("contextId") if request.params else None
            task = await self.task_manager.create_task(message, context_id)

            # Execute and stream
            async for event in self.task_manager.execute_task(task.id):
                if isinstance(event, TaskStatusUpdateEvent):
                    yield self._sse_event(
                        "task.status",
                        {
                            "id": request.id,
                            "jsonrpc": "2.0",
                            "result": {
                                "taskId": event.task_id,
                                "contextId": event.context_id,
                                "status": {
                                    "state": event.status.state.value,
                                    "createdAt": event.status.created_at.isoformat() if event.status.created_at else None,
                                    "updatedAt": event.status.updated_at.isoformat() if event.status.updated_at else None,
                                },
                                "final": event.final,
                            },
                        },
                    )
                elif isinstance(event, TaskArtifactUpdateEvent):
                    yield self._sse_event(
                        "task.artifact",
                        {
                            "id": request.id,
                            "jsonrpc": "2.0",
                            "result": {
                                "taskId": event.task_id,
                                "contextId": event.context_id,
                                "artifact": {
                                    "artifactId": event.artifact.artifact_id,
                                    "name": event.artifact.name,
                                    "parts": [
                                        self._serialize_part(p)
                                        for p in event.artifact.parts
                                    ],
                                },
                            },
                        },
                    )

        except Exception as e:
            yield self._sse_event(
                "error",
                {
                    "id": request.id,
                    "jsonrpc": "2.0",
                    "error": {
                        "code": ErrorCode.INTERNAL_ERROR,
                        "message": str(e),
                    },
                },
            )

    async def _handle_message_send(self, params: dict[str, Any] | None) -> dict:
        """Handle message/send method."""
        if not params:
            raise A2AError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing params",
            )

        message = self._extract_message(params)
        context_id = params.get("contextId")

        # Create and execute task
        task = await self.task_manager.create_task(message, context_id)
        task = await self.task_manager.execute_task_sync(task.id)

        return self._serialize_task(task)

    async def _handle_tasks_get(self, params: dict[str, Any] | None) -> dict:
        """Handle tasks/get method."""
        if not params or "taskId" not in params:
            raise A2AError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing taskId parameter",
            )

        task_id = params["taskId"]
        task = self.task_manager.get_task(task_id)

        return self._serialize_task(task)

    async def _handle_tasks_cancel(self, params: dict[str, Any] | None) -> dict:
        """Handle tasks/cancel method."""
        if not params or "taskId" not in params:
            raise A2AError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing taskId parameter",
            )

        task_id = params["taskId"]
        task = await self.task_manager.cancel_task(task_id)

        return self._serialize_task(task)

    async def _handle_push_config_set(self, params: dict[str, Any] | None) -> dict:
        """Handle push notification config set (stub)."""
        # Push notifications not yet implemented
        return {"supported": False}

    async def _handle_push_config_get(self, params: dict[str, Any] | None) -> dict:
        """Handle push notification config get (stub)."""
        return {"supported": False}

    def _extract_message(self, params: dict[str, Any]) -> Message:
        """Extract Message from request params."""
        msg_data = params.get("message", {})

        # Handle parts
        parts = []
        for part_data in msg_data.get("parts", []):
            if "text" in part_data:
                parts.append(TextPart(text=part_data["text"]))
            # Add other part types as needed

        # Default to user role
        role = Role(msg_data.get("role", "user"))

        return Message(
            role=role,
            parts=parts,
            context_id=params.get("contextId"),
        )

    def _serialize_task(self, task: Any) -> dict:
        """Serialize task for response."""
        return {
            "taskId": task.id,
            "contextId": task.context_id,
            "status": {
                "state": task.status.state.value,
                "createdAt": task.status.created_at.isoformat() if task.status.created_at else None,
                "updatedAt": task.status.updated_at.isoformat() if task.status.updated_at else None,
            },
            "history": [
                {
                    "role": msg.role.value,
                    "parts": [self._serialize_part(p) for p in msg.parts],
                }
                for msg in task.history
            ],
            "artifacts": [
                {
                    "artifactId": art.artifact_id,
                    "name": art.name,
                    "parts": [self._serialize_part(p) for p in art.parts],
                }
                for art in task.artifacts
            ],
        }

    def _serialize_part(self, part: Any) -> dict:
        """Serialize a message part."""
        if hasattr(part, "text"):
            return {"type": "text", "text": part.text}
        elif hasattr(part, "file"):
            return {"type": "file", "file": {"uri": part.file.uri}}
        elif hasattr(part, "data"):
            return {"type": "data", "data": part.data}
        return {}

    def _error_response(
        self,
        request_id: str | int | None,
        code: int,
        message: str,
    ) -> JSONRPCResponse:
        """Create error response."""
        return JSONRPCResponse(
            id=request_id,
            error=JSONRPCError(
                code=code,
                message=message,
            ),
        )

    def _sse_event(self, event_type: str, data: dict) -> str:
        """Format SSE event."""
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
