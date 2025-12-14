"""
Abstract base class for CLI tool adapters.

Provides a unified interface for different AI CLI tools (Claude, Gemini,
Codex, Ollama). Each adapter wraps a specific CLI and converts responses
to A2A-compatible formats.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from sanhedrin.core.types import (
    Message,
    Part,
    TextPart,
    AgentSkill,
)

if TYPE_CHECKING:
    pass


@dataclass
class AdapterConfig:
    """Configuration for CLI adapters."""

    timeout: float = 120.0  # Execution timeout in seconds
    max_retries: int = 3  # Maximum retry attempts
    retry_delay: float = 1.0  # Delay between retries in seconds
    streaming: bool = True  # Enable streaming by default
    extra: dict[str, Any] = field(default_factory=dict)  # Adapter-specific config


@dataclass
class ExecutionResult:
    """Result from CLI execution."""

    success: bool
    content: str
    raw_output: dict[str, Any] | None = None
    error: str | None = None
    exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        """Check if result represents an error."""
        return not self.success or self.exit_code != 0


@dataclass
class StreamChunk:
    """Streaming chunk from CLI execution."""

    content: str
    is_final: bool = False
    chunk_type: str = "text"  # text, error, metadata
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAdapter(ABC):
    """
    Abstract base class for AI CLI tool adapters.

    Each adapter wraps a specific CLI tool (Claude, Gemini, etc.)
    and converts its responses to A2A-compatible formats.

    The key design principle is CLI-first: adapters invoke locally
    installed CLI tools via subprocess, using the user's existing
    subscriptions and authentication rather than direct API calls.

    Example:
        >>> adapter = ClaudeCodeAdapter()
        >>> await adapter.initialize()
        >>> result = await adapter.execute("Write hello world in Python")
        >>> print(result.content)
        print("Hello, World!")
    """

    def __init__(
        self,
        config: AdapterConfig | None = None,
    ) -> None:
        self.config = config or AdapterConfig()
        self._initialized = False

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this adapter.

        Used for registration and routing.
        Example: "claude-code", "gemini-cli"
        """
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable name for display.

        Example: "Claude Code", "Gemini CLI"
        """
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Description of the adapter's capabilities.

        Should be informative for users discovering the agent.
        """
        ...

    @property
    @abstractmethod
    def skills(self) -> list[AgentSkill]:
        """
        Skills this adapter provides.

        Skills describe what the adapter can do and are used
        for capability-based routing.
        """
        ...

    @property
    def cli_command(self) -> str | None:
        """
        The CLI command this adapter invokes.

        Override in subclasses. Returns None if not CLI-based.
        Example: "claude", "gemini", "codex"
        """
        return None

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the adapter.

        Should verify:
        - CLI tool is installed and accessible
        - Authentication is configured
        - Any required dependencies are available

        Raises:
            AdapterInitializationError: If initialization fails
        """
        ...

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """
        Execute a prompt and return the result.

        This is the main entry point for non-streaming execution.

        Args:
            prompt: The prompt to send to the CLI
            context: Previous messages for conversation context
            **kwargs: Additional adapter-specific arguments

        Returns:
            ExecutionResult with the response

        Raises:
            AdapterExecutionError: If execution fails
        """
        ...

    @abstractmethod
    async def execute_stream(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute a prompt with streaming response.

        Yields chunks as they become available from the CLI.

        Args:
            prompt: The prompt to send to the CLI
            context: Previous messages for conversation context
            **kwargs: Additional adapter-specific arguments

        Yields:
            StreamChunk objects as they arrive

        Raises:
            AdapterExecutionError: If execution fails
        """
        ...
        # Make this a generator
        if False:
            yield StreamChunk(content="")

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the CLI tool is available and working.

        Returns:
            True if the adapter is healthy and ready
        """
        ...

    def message_to_prompt(self, message: Message) -> str:
        """
        Convert an A2A Message to a prompt string.

        Extracts text content from message parts.

        Args:
            message: The message to convert

        Returns:
            Prompt string suitable for CLI input
        """
        parts = []
        for part in message.parts:
            if isinstance(part, TextPart):
                parts.append(part.text)
            elif hasattr(part, "data"):
                # DataPart - convert to string representation
                parts.append(str(part.data))
            elif hasattr(part, "file"):
                # FilePart - indicate file reference
                file_info = part.file
                if hasattr(file_info, "name") and file_info.name:
                    parts.append(f"[File: {file_info.name}]")
                elif hasattr(file_info, "uri"):
                    parts.append(f"[File: {file_info.uri}]")
        return "\n".join(parts)

    def result_to_parts(self, result: ExecutionResult) -> list[Part]:
        """
        Convert ExecutionResult to A2A message parts.

        Args:
            result: The execution result to convert

        Returns:
            List of message parts
        """
        return [TextPart(text=result.content)]

    def build_context_prompt(self, context: list[Message]) -> str:
        """
        Build a context string from message history.

        Args:
            context: List of previous messages

        Returns:
            Formatted context string
        """
        if not context:
            return ""

        context_parts = []
        for msg in context:
            role = "User" if msg.role.value == "user" else "Assistant"
            content = self.message_to_prompt(msg)
            context_parts.append(f"{role}: {content}")

        return "\n".join(context_parts)

    @property
    def is_initialized(self) -> bool:
        """Check if adapter has been initialized."""
        return self._initialized

    @property
    def supports_streaming(self) -> bool:
        """Check if adapter supports streaming responses."""
        return self.config.streaming

    async def __aenter__(self) -> "BaseAdapter":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        # Cleanup if needed - override in subclasses
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name!r}, initialized={self._initialized})>"
