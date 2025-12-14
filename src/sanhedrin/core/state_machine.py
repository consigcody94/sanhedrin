"""
A2A Task State Machine implementation.

Enforces valid state transitions per A2A Protocol specification.
Reference: https://a2a-protocol.org/latest/specification/#task-states
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sanhedrin.core.types import TaskState, TaskStatus, Message

if TYPE_CHECKING:
    from typing import Callable


# Valid A2A state transitions
VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {
        TaskState.WORKING,
        TaskState.COMPLETED,  # Fast completion
        TaskState.FAILED,
        TaskState.REJECTED,
        TaskState.CANCELED,
    },
    TaskState.WORKING: {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.INPUT_REQUIRED,
        TaskState.AUTH_REQUIRED,
    },
    TaskState.INPUT_REQUIRED: {
        TaskState.WORKING,  # Resume after input
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
    },
    TaskState.AUTH_REQUIRED: {
        TaskState.WORKING,  # Resume after auth
        TaskState.FAILED,
        TaskState.CANCELED,
    },
    # Terminal states - no further transitions allowed
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELED: set(),
    TaskState.REJECTED: set(),
    TaskState.UNKNOWN: set(),
}

# Terminal states that cannot be transitioned from
TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.REJECTED,
    }
)

# States where the agent is actively working
ACTIVE_STATES: frozenset[TaskState] = frozenset(
    {
        TaskState.SUBMITTED,
        TaskState.WORKING,
    }
)

# States waiting for external input
WAITING_STATES: frozenset[TaskState] = frozenset(
    {
        TaskState.INPUT_REQUIRED,
        TaskState.AUTH_REQUIRED,
    }
)


@dataclass
class StateTransitionRecord:
    """Record of a state transition."""

    from_state: TaskState
    to_state: TaskState
    timestamp: datetime
    reason: str | None = None


@dataclass
class TaskStateMachine:
    """
    Manages task state transitions with validation.

    Enforces A2A Protocol state transition rules and maintains
    transition history for debugging and audit purposes.

    Example:
        >>> sm = TaskStateMachine()
        >>> sm.current_state
        <TaskState.SUBMITTED: 'submitted'>
        >>> sm.transition_to(TaskState.WORKING)
        >>> sm.current_state
        <TaskState.WORKING: 'working'>
        >>> sm.transition_to(TaskState.COMPLETED)
        >>> sm.is_terminal
        True
    """

    current_state: TaskState = TaskState.SUBMITTED
    history: list[StateTransitionRecord] = field(default_factory=list)
    _created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Record initial state in history."""
        self._record_transition(
            from_state=TaskState.UNKNOWN,
            to_state=self.current_state,
            reason="Initial state",
        )

    def _record_transition(
        self,
        from_state: TaskState,
        to_state: TaskState,
        reason: str | None = None,
    ) -> None:
        """Record a state transition in history."""
        record = StateTransitionRecord(
            from_state=from_state,
            to_state=to_state,
            timestamp=datetime.now(timezone.utc),
            reason=reason,
        )
        self.history.append(record)

    def can_transition_to(self, target_state: TaskState) -> bool:
        """
        Check if transition to target state is valid.

        Args:
            target_state: The state to check

        Returns:
            True if the transition is allowed
        """
        return target_state in VALID_TRANSITIONS.get(self.current_state, set())

    def get_valid_transitions(self) -> set[TaskState]:
        """Get all valid states that can be transitioned to from current state."""
        return VALID_TRANSITIONS.get(self.current_state, set()).copy()

    def transition_to(
        self,
        target_state: TaskState,
        reason: str | None = None,
    ) -> TaskStatus:
        """
        Transition to a new state.

        Args:
            target_state: The state to transition to
            reason: Optional reason for the transition

        Returns:
            New TaskStatus with updated state

        Raises:
            InvalidStateTransitionError: If transition is not valid
        """
        from sanhedrin.core.errors import InvalidStateTransitionError

        if not self.can_transition_to(target_state):
            valid = self.get_valid_transitions()
            raise InvalidStateTransitionError(
                from_state=self.current_state,
                to_state=target_state,
                valid_transitions=valid,
            )

        from_state = self.current_state
        self.current_state = target_state
        self._record_transition(from_state, target_state, reason)

        return TaskStatus(
            state=target_state,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def force_transition(
        self,
        target_state: TaskState,
        reason: str | None = None,
    ) -> TaskStatus:
        """
        Force a state transition without validation.

        WARNING: This bypasses A2A protocol rules. Use only for
        error recovery or administrative operations.

        Args:
            target_state: The state to transition to
            reason: Reason for the forced transition

        Returns:
            New TaskStatus with updated state
        """
        from_state = self.current_state
        self.current_state = target_state
        self._record_transition(from_state, target_state, f"[FORCED] {reason or ''}")

        return TaskStatus(
            state=target_state,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @property
    def is_terminal(self) -> bool:
        """Check if current state is terminal (no further transitions)."""
        return self.current_state in TERMINAL_STATES

    @property
    def is_active(self) -> bool:
        """Check if task is actively being processed."""
        return self.current_state in ACTIVE_STATES

    @property
    def is_waiting(self) -> bool:
        """Check if task is waiting for external input."""
        return self.current_state in WAITING_STATES

    @property
    def is_working(self) -> bool:
        """Check if task is in the working state."""
        return self.current_state == TaskState.WORKING

    @property
    def requires_input(self) -> bool:
        """Check if task is waiting for user input."""
        return self.current_state == TaskState.INPUT_REQUIRED

    @property
    def requires_auth(self) -> bool:
        """Check if task is waiting for authentication."""
        return self.current_state == TaskState.AUTH_REQUIRED

    @property
    def is_successful(self) -> bool:
        """Check if task completed successfully."""
        return self.current_state == TaskState.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Check if task failed."""
        return self.current_state == TaskState.FAILED

    @property
    def duration(self) -> float:
        """Get duration since task creation in seconds."""
        return (datetime.now(timezone.utc) - self._created_at).total_seconds()

    def get_status(self, message: Message | None = None) -> TaskStatus:
        """
        Get current status with optional message.

        Args:
            message: Optional message to include in status

        Returns:
            Current TaskStatus
        """
        return TaskStatus(
            state=self.current_state,
            message=message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def get_history_summary(self) -> list[dict[str, str]]:
        """Get a summary of state transition history."""
        return [
            {
                "from": record.from_state.value,
                "to": record.to_state.value,
                "timestamp": record.timestamp.isoformat(),
                "reason": record.reason or "",
            }
            for record in self.history
        ]


def create_state_machine(initial_state: TaskState = TaskState.SUBMITTED) -> TaskStateMachine:
    """
    Create a new state machine with the specified initial state.

    Args:
        initial_state: Starting state (default: SUBMITTED)

    Returns:
        New TaskStateMachine instance
    """
    return TaskStateMachine(current_state=initial_state)
