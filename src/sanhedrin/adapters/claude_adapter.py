"""
Claude Code CLI adapter.

Wraps the Claude Code CLI for A2A-compatible execution.
Uses subprocess to invoke `claude --print --output-format json` for
cost-effective operation using the user's existing subscription.

Reference: https://docs.anthropic.com/en/docs/claude-code
CLI Reference: https://docs.anthropic.com/en/docs/claude-code/cli-reference
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any, AsyncIterator

from sanhedrin.adapters.base import (
    BaseAdapter,
    AdapterConfig,
    ExecutionResult,
    StreamChunk,
)
from sanhedrin.core.types import AgentSkill, Message
from sanhedrin.core.errors import (
    AdapterInitializationError,
    AdapterExecutionError,
    AdapterTimeoutError,
    CLINotFoundError,
)


class ClaudeCodeAdapter(BaseAdapter):
    """
    Adapter for Claude Code CLI.

    Invokes the locally installed `claude` command via subprocess.
    Uses `--print --output-format json` for programmatic access.

    Cost Model:
        Uses your existing Claude/Anthropic subscription.
        No additional API costs beyond your subscription.

    Authentication:
        - OAuth (default): Uses Claude Code's built-in auth
        - API Key: Set ANTHROPIC_API_KEY environment variable

    Example:
        >>> adapter = ClaudeCodeAdapter()
        >>> await adapter.initialize()
        >>> result = await adapter.execute("Write a Python function to sort a list")
        >>> print(result.content)
    """

    CLI_COMMAND = "claude"
    INSTALL_HINT = "Install from https://claude.ai/code or via npm: npm install -g @anthropic-ai/claude-code"

    def __init__(
        self,
        config: AdapterConfig | None = None,
        model: str | None = None,
    ) -> None:
        """
        Initialize Claude Code adapter.

        Args:
            config: Adapter configuration
            model: Optional model override (e.g., "sonnet", "opus", "haiku")
        """
        super().__init__(config)
        self.model = model
        self._cli_path: str | None = None

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    @property
    def description(self) -> str:
        return (
            "Anthropic's Claude Code CLI - an agentic AI coding assistant "
            "for code generation, review, debugging, and complex development tasks. "
            "Uses your existing Claude subscription."
        )

    @property
    def cli_command(self) -> str:
        return self.CLI_COMMAND

    @property
    def skills(self) -> list[AgentSkill]:
        return [
            AgentSkill(
                id="code-generation",
                name="Code Generation",
                description="Generate code from natural language descriptions",
                tags=["coding", "generation", "development"],
                examples=[
                    "Write a Python function to parse JSON",
                    "Create a React component for a login form",
                    "Implement a binary search algorithm in Go",
                ],
            ),
            AgentSkill(
                id="code-review",
                name="Code Review",
                description="Review and analyze code for issues, bugs, and improvements",
                tags=["coding", "review", "analysis", "quality"],
                examples=[
                    "Review this code for security vulnerabilities",
                    "Suggest improvements for this function",
                    "Find potential bugs in this module",
                ],
            ),
            AgentSkill(
                id="debugging",
                name="Debugging Assistance",
                description="Help debug and fix code issues",
                tags=["coding", "debugging", "troubleshooting", "fix"],
                examples=[
                    "Why is this test failing?",
                    "Help me fix this null pointer exception",
                    "Debug this async race condition",
                ],
            ),
            AgentSkill(
                id="refactoring",
                name="Code Refactoring",
                description="Improve code structure and maintainability",
                tags=["coding", "refactoring", "cleanup", "optimization"],
                examples=[
                    "Refactor this function to be more readable",
                    "Extract common logic into a utility",
                    "Optimize this database query",
                ],
            ),
            AgentSkill(
                id="explanation",
                name="Code Explanation",
                description="Explain how code works",
                tags=["coding", "explanation", "documentation", "learning"],
                examples=[
                    "Explain how this algorithm works",
                    "What does this regex do?",
                    "Walk me through this codebase",
                ],
            ),
        ]

    async def initialize(self) -> None:
        """Initialize adapter and verify CLI availability."""
        # Find CLI
        self._cli_path = shutil.which(self.CLI_COMMAND)
        if not self._cli_path:
            raise CLINotFoundError(
                adapter=self.name,
                cli_command=self.CLI_COMMAND,
                install_hint=self.INSTALL_HINT,
            )

        # Verify CLI works
        if not await self.health_check():
            raise AdapterInitializationError(
                adapter=self.name,
                message="Claude Code CLI health check failed. Run 'claude --version' to verify installation.",
            )

        self._initialized = True

    async def health_check(self) -> bool:
        """Check if Claude CLI is available and responding."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.CLI_COMMAND,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            return proc.returncode == 0
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            return False

    async def execute(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """
        Execute prompt using Claude Code CLI.

        Uses: claude --print --output-format json "prompt"

        Args:
            prompt: The prompt to send
            context: Optional conversation context
            **kwargs: Additional options (model, max_tokens, etc.)

        Returns:
            ExecutionResult with the response
        """
        if not self._initialized:
            await self.initialize()

        # Build command
        cmd = [
            self.CLI_COMMAND,
            "--print",  # Non-interactive mode, output to stdout
            "--output-format",
            "json",
        ]

        # Add model if specified
        model = kwargs.get("model", self.model)
        if model:
            cmd.extend(["--model", model])

        # Build full prompt with context
        full_prompt = prompt
        if context:
            context_text = self.build_context_prompt(context)
            full_prompt = f"{context_text}\n\nUser: {prompt}"

        cmd.append(full_prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout,
            )

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            if proc.returncode != 0:
                return ExecutionResult(
                    success=False,
                    content="",
                    error=stderr_text or f"CLI exited with code {proc.returncode}",
                    exit_code=proc.returncode or 1,
                )

            # Parse JSON output
            content, raw_output = self._parse_output(stdout_text)

            return ExecutionResult(
                success=True,
                content=content,
                raw_output=raw_output,
                exit_code=0,
            )

        except asyncio.TimeoutError:
            raise AdapterTimeoutError(
                adapter=self.name,
                timeout=self.config.timeout,
            )
        except Exception as e:
            raise AdapterExecutionError(
                adapter=self.name,
                message=str(e),
            )

    async def execute_stream(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute with streaming using stream-json output format.

        Uses: claude --print --output-format stream-json "prompt"

        Args:
            prompt: The prompt to send
            context: Optional conversation context
            **kwargs: Additional options

        Yields:
            StreamChunk objects as they arrive
        """
        if not self._initialized:
            await self.initialize()

        cmd = [
            self.CLI_COMMAND,
            "--print",
            "--output-format",
            "stream-json",
        ]

        model = kwargs.get("model", self.model)
        if model:
            cmd.extend(["--model", model])

        full_prompt = prompt
        if context:
            context_text = self.build_context_prompt(context)
            full_prompt = f"{context_text}\n\nUser: {prompt}"

        cmd.append(full_prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        try:
            if proc.stdout is None:
                yield StreamChunk(content="", is_final=True)
                return

            async for line in proc.stdout:
                if line:
                    decoded = line.decode().strip()
                    if decoded:
                        content, metadata = self._parse_stream_chunk(decoded)
                        if content:
                            yield StreamChunk(
                                content=content,
                                is_final=False,
                                metadata=metadata,
                            )

            await proc.wait()

            # Check for errors
            if proc.returncode != 0 and proc.stderr:
                stderr = await proc.stderr.read()
                yield StreamChunk(
                    content="",
                    is_final=True,
                    chunk_type="error",
                    metadata={"error": stderr.decode()},
                )
            else:
                yield StreamChunk(content="", is_final=True)

        except Exception as e:
            yield StreamChunk(
                content="",
                is_final=True,
                chunk_type="error",
                metadata={"error": str(e)},
            )

    def _parse_output(self, output: str) -> tuple[str, dict[str, Any] | None]:
        """
        Parse CLI output, handling both JSON and plain text.

        Args:
            output: Raw CLI output

        Returns:
            Tuple of (content string, raw output dict or None)
        """
        if not output.strip():
            return "", None

        try:
            # Try to parse as JSON
            data = json.loads(output)
            content = self._extract_content(data)
            return content, data
        except json.JSONDecodeError:
            # Plain text output
            return output.strip(), None

    def _extract_content(self, data: dict[str, Any] | list[Any]) -> str:
        """
        Extract text content from JSON output.

        Handles various Claude Code output formats.
        """
        if isinstance(data, str):
            return data

        if isinstance(data, list):
            # Array of messages/responses
            contents = []
            for item in data:
                if isinstance(item, dict):
                    contents.append(self._extract_content(item))
                elif isinstance(item, str):
                    contents.append(item)
            return "\n".join(filter(None, contents))

        if isinstance(data, dict):
            # Try common field names
            for field in ["result", "content", "text", "response", "message", "output"]:
                if field in data:
                    value = data[field]
                    if isinstance(value, str):
                        return value
                    elif isinstance(value, dict):
                        return self._extract_content(value)
                    elif isinstance(value, list):
                        return self._extract_content(value)

            # Handle Claude-specific format with content array
            if "content" not in data and "type" in data:
                if data.get("type") == "text" and "text" in data:
                    return data["text"]

        return str(data)

    def _parse_stream_chunk(self, line: str) -> tuple[str, dict[str, Any]]:
        """
        Parse a streaming JSON chunk.

        Args:
            line: Single line of stream output

        Returns:
            Tuple of (content string, metadata dict)
        """
        try:
            data = json.loads(line)

            # Extract content from various formats
            content = ""
            if isinstance(data, dict):
                if "text" in data:
                    content = data["text"]
                elif "delta" in data and isinstance(data["delta"], dict):
                    content = data["delta"].get("text", "")
                elif "content" in data:
                    if isinstance(data["content"], str):
                        content = data["content"]
                    elif isinstance(data["content"], list):
                        for item in data["content"]:
                            if isinstance(item, dict) and item.get("type") == "text":
                                content += item.get("text", "")

            return content, data

        except json.JSONDecodeError:
            # Plain text line
            return line, {}
