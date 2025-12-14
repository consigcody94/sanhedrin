"""
Task lifecycle manager.

Handles task creation, state transitions, execution, and artifact management.
Integrates adapters with the A2A task model.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import uuid4

from sanhedrin.core.types import (
    Task,
    TaskState,
    TaskStatus,
    Message,
    Role,
    TextPart,
    Artifact,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from sanhedrin.core.state_machine import TaskStateMachine
from sanhedrin.core.errors import (
    TaskNotFoundError,
    InvalidStateTransitionError,
    AdapterExecutionError,
)
from sanhedrin.adapters.base import BaseAdapter, StreamChunk


def generate_id() -> str:
    """Generate unique ID."""
    return str(uuid4())


def utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


class TaskManager:
    """
    Manages task lifecycle and execution.

    Responsibilities:
    - Task creation and storage
    - State machine transitions
    - Adapter execution coordination
    - Message and artifact management
    - Streaming response handling

    Example:
        >>> manager = TaskManager(adapter)
        >>> task = await manager.create_task(message)
        >>> async for event in manager.execute_task(task.id):
        ...     print(event)
    """

    def __init__(self, adapter: BaseAdapter) -> None:
        """
        Initialize task manager.

        Args:
            adapter: The adapter to use for execution
        """
        self.adapter = adapter
        self._tasks: dict[str, Task] = {}
        self._state_machines: dict[str, TaskStateMachine] = {}
        self._contexts: dict[str, list[Message]] = {}

    def get_task(self, task_id: str) -> Task:
        """
        Get task by ID.

        Args:
            task_id: Task identifier

        Returns:
            The task

        Raises:
            TaskNotFoundError: If task not found
        """
        if task_id not in self._tasks:
            raise TaskNotFoundError(task_id=task_id)
        return self._tasks[task_id]

    def list_tasks(
        self,
        state: TaskState | None = None,
        limit: int = 100,
    ) -> list[Task]:
        """
        List tasks with optional filtering.

        Args:
            state: Filter by state
            limit: Maximum tasks to return

        Returns:
            List of tasks
        """
        tasks = list(self._tasks.values())

        if state is not None:
            tasks = [t for t in tasks if t.status.state == state]

        # Sort by update time (newest first)
        tasks.sort(
            key=lambda t: t.status.updated_at or t.status.created_at,
            reverse=True,
        )

        return tasks[:limit]

    async def create_task(
        self,
        message: Message,
        context_id: str | None = None,
    ) -> Task:
        """
        Create a new task from a message.

        Args:
            message: Initial message for the task
            context_id: Optional context for conversation continuity

        Returns:
            The created task
        """
        task_id = generate_id()
        now = utc_now()

        # Create task status
        status = TaskStatus(
            state=TaskState.SUBMITTED,
            created_at=now,
            updated_at=now,
        )

        # Create task
        task = Task(
            id=task_id,
            context_id=context_id or generate_id(),
            status=status,
            history=[message],
            artifacts=[],
            metadata={},
        )

        # Initialize state machine
        state_machine = TaskStateMachine(task_id=task_id)

        # Store
        self._tasks[task_id] = task
        self._state_machines[task_id] = state_machine

        # Initialize context if needed
        if context_id and context_id in self._contexts:
            # Inherit context from previous conversation
            pass
        else:
            self._contexts[task.context_id] = []

        return task

    async def transition_state(
        self,
        task_id: str,
        new_state: TaskState,
        message: Message | None = None,
    ) -> Task:
        """
        Transition task to a new state.

        Args:
            task_id: Task identifier
            new_state: Target state
            message: Optional message for the transition

        Returns:
            Updated task

        Raises:
            TaskNotFoundError: If task not found
            InvalidStateTransitionError: If transition is invalid
        """
        task = self.get_task(task_id)
        state_machine = self._state_machines[task_id]

        # Attempt transition
        if not state_machine.can_transition(new_state):
            raise InvalidStateTransitionError(
                task_id=task_id,
                current_state=state_machine.current_state,
                target_state=new_state,
            )

        state_machine.transition(new_state)

        # Update task
        task.status.state = new_state
        task.status.updated_at = utc_now()

        # Add message to history if provided
        if message:
            task.history.append(message)
            self._contexts[task.context_id].append(message)

        return task

    async def execute_task(
        self,
        task_id: str,
    ) -> AsyncIterator[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        """
        Execute a task and stream results.

        Transitions through states and yields events as execution progresses.

        Args:
            task_id: Task identifier

        Yields:
            Status and artifact update events

        Raises:
            TaskNotFoundError: If task not found
        """
        task = self.get_task(task_id)

        # Transition to working
        await self.transition_state(task_id, TaskState.WORKING)
        yield TaskStatusUpdateEvent(
            task_id=task_id,
            context_id=task.context_id,
            status=task.status,
            final=False,
        )

        # Get prompt from last user message
        prompt = self._extract_prompt(task)
        context = self._contexts.get(task.context_id, [])

        try:
            # Execute with streaming
            full_content = ""

            async for chunk in self.adapter.execute_stream(prompt, context):
                if chunk.chunk_type == "error":
                    # Handle error
                    error_msg = chunk.metadata.get("error", "Unknown error")
                    await self._fail_task(task_id, error_msg)
                    yield TaskStatusUpdateEvent(
                        task_id=task_id,
                        context_id=task.context_id,
                        status=task.status,
                        final=True,
                    )
                    return

                if chunk.content:
                    full_content += chunk.content

                if chunk.is_final:
                    break

            # Create response message
            response_message = Message(
                role=Role.AGENT,
                parts=[TextPart(text=full_content)],
                context_id=task.context_id,
                task_id=task_id,
            )

            # Add to history
            task.history.append(response_message)
            self._contexts[task.context_id].append(response_message)

            # Create artifact
            artifact = Artifact(
                artifact_id=generate_id(),
                name="response",
                parts=[TextPart(text=full_content)],
                metadata={
                    "adapter": self.adapter.name,
                    "generated_at": utc_now().isoformat(),
                },
            )
            task.artifacts.append(artifact)

            yield TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=task.context_id,
                artifact=artifact,
            )

            # Transition to completed
            await self.transition_state(task_id, TaskState.COMPLETED)
            yield TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=task.context_id,
                status=task.status,
                final=True,
            )

        except Exception as e:
            await self._fail_task(task_id, str(e))
            yield TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=task.context_id,
                status=task.status,
                final=True,
            )

    async def execute_task_sync(self, task_id: str) -> Task:
        """
        Execute a task synchronously (non-streaming).

        Args:
            task_id: Task identifier

        Returns:
            Completed task
        """
        task = self.get_task(task_id)

        # Transition to working
        await self.transition_state(task_id, TaskState.WORKING)

        prompt = self._extract_prompt(task)
        context = self._contexts.get(task.context_id, [])

        try:
            result = await self.adapter.execute(prompt, context)

            if not result.success:
                await self._fail_task(task_id, result.error or "Execution failed")
                return self.get_task(task_id)

            # Create response message
            response_message = Message(
                role=Role.AGENT,
                parts=[TextPart(text=result.content)],
                context_id=task.context_id,
                task_id=task_id,
            )

            task.history.append(response_message)
            self._contexts[task.context_id].append(response_message)

            # Create artifact
            artifact = Artifact(
                artifact_id=generate_id(),
                name="response",
                parts=[TextPart(text=result.content)],
                metadata={
                    "adapter": self.adapter.name,
                    "generated_at": utc_now().isoformat(),
                    **(result.metadata or {}),
                },
            )
            task.artifacts.append(artifact)

            # Transition to completed
            await self.transition_state(task_id, TaskState.COMPLETED)

        except Exception as e:
            await self._fail_task(task_id, str(e))

        return self.get_task(task_id)

    async def cancel_task(self, task_id: str) -> Task:
        """
        Cancel a task.

        Args:
            task_id: Task identifier

        Returns:
            Updated task
        """
        return await self.transition_state(task_id, TaskState.CANCELED)

    async def _fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed with error message."""
        task = self.get_task(task_id)
        task.status.state = TaskState.FAILED
        task.status.updated_at = utc_now()
        task.status.message = TaskStatus(
            state=TaskState.FAILED,
            message=Message(
                role=Role.AGENT,
                parts=[TextPart(text=f"Error: {error}")],
            ),
        ).message

        state_machine = self._state_machines[task_id]
        if state_machine.can_transition(TaskState.FAILED):
            state_machine.transition(TaskState.FAILED)

    def _extract_prompt(self, task: Task) -> str:
        """Extract prompt text from task's last user message."""
        # Find last user message
        for message in reversed(task.history):
            if message.role == Role.USER:
                return self.adapter.message_to_prompt(message)

        # Fallback: use last message
        if task.history:
            return self.adapter.message_to_prompt(task.history[-1])

        return ""

    def cleanup_completed(self, max_age_seconds: int = 3600) -> int:
        """
        Remove old completed/failed/canceled tasks.

        Args:
            max_age_seconds: Maximum age in seconds

        Returns:
            Number of tasks removed
        """
        now = utc_now()
        to_remove = []

        for task_id, task in self._tasks.items():
            if task.status.state in (
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELED,
            ):
                age = (now - (task.status.updated_at or task.status.created_at)).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]
            del self._state_machines[task_id]

        return len(to_remove)

    def __len__(self) -> int:
        return len(self._tasks)
