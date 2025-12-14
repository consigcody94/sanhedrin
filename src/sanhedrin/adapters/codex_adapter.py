"""
Codex CLI adapter.

Wraps OpenAI's Codex CLI for A2A-compatible execution.
Uses subprocess to invoke `codex exec` for cost-effective operation
using the user's existing ChatGPT subscription.

Reference: https://github.com/openai/codex
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


class CodexCLIAdapter(BaseAdapter):
    """
    Adapter for OpenAI Codex CLI.

    Invokes the locally installed `codex` command via subprocess.
    Uses `codex exec --json` for programmatic access.

    Cost Model:
        Uses your existing ChatGPT Plus/Pro/Enterprise subscription.
        No additional API costs beyond your subscription.

    Authentication:
        - ChatGPT Subscription (default): Uses Codex CLI's built-in auth
        - API Key: Set CODEX_API_KEY environment variable

    Sandbox Modes:
        - read-only: No file modifications (default)
        - workspace-write: Can modify files in workspace
        - danger-full-access: Full system access (use with caution)

    Example:
        >>> adapter = CodexCLIAdapter(sandbox_mode="workspace-write")
        >>> await adapter.initialize()
        >>> result = await adapter.execute("Create a new Python file with hello world")
        >>> print(result.content)
    """

    CLI_COMMAND = "codex"
    INSTALL_HINT = "Install via npm: npm install -g @openai/codex"

    def __init__(
        self,
        config: AdapterConfig | None = None,
        model: str | None = None,
        sandbox_mode: str = "read-only",
    ) -> None:
        """
        Initialize Codex CLI adapter.

        Args:
            config: Adapter configuration
            model: Optional model override (e.g., "o3", "o3-mini")
            sandbox_mode: Sandbox mode ("read-only", "workspace-write", "danger-full-access")
        """
        super().__init__(config)
        self.model = model
        self.sandbox_mode = sandbox_mode
        self._cli_path: str | None = None

    @property
    def name(self) -> str:
        return "codex-cli"

    @property
    def display_name(self) -> str:
        return "Codex CLI"

    @property
    def description(self) -> str:
        return (
            "OpenAI's Codex CLI - a lightweight coding agent that runs in your terminal. "
            "Powered by GPT models, capable of code generation, file operations, and "
            "agentic development tasks. Uses your ChatGPT subscription."
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
                    "Write a Python script to process CSV files",
                    "Create a REST API endpoint",
                    "Implement a sorting algorithm",
                ],
            ),
            AgentSkill(
                id="file-operations",
                name="File Operations",
                description="Read, write, and modify files in the workspace",
                tags=["files", "editing", "workspace"],
                examples=[
                    "Create a new configuration file",
                    "Update the README with new instructions",
                    "Refactor this file structure",
                ],
            ),
            AgentSkill(
                id="code-execution",
                name="Code Execution",
                description="Execute shell commands and scripts",
                tags=["execution", "shell", "commands"],
                examples=[
                    "Run the test suite",
                    "Install dependencies",
                    "Build the project",
                ],
            ),
            AgentSkill(
                id="project-scaffolding",
                name="Project Scaffolding",
                description="Create new projects and file structures",
                tags=["scaffolding", "setup", "initialization"],
                examples=[
                    "Create a new React project",
                    "Set up a Python package structure",
                    "Initialize a Go module",
                ],
            ),
        ]

    async def initialize(self) -> None:
        """Initialize adapter and verify CLI availability."""
        self._cli_path = shutil.which(self.CLI_COMMAND)
        if not self._cli_path:
            raise CLINotFoundError(
                adapter=self.name,
                cli_command=self.CLI_COMMAND,
                install_hint=self.INSTALL_HINT,
            )

        if not await self.health_check():
            raise AdapterInitializationError(
                adapter=self.name,
                message="Codex CLI health check failed. Run 'codex --version' to verify.",
            )

        self._initialized = True

    async def health_check(self) -> bool:
        """Check if Codex CLI is available."""
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
        Execute prompt using Codex CLI.

        Uses: codex exec --json "prompt"

        Args:
            prompt: The prompt/task to execute
            context: Optional conversation context
            **kwargs: Additional options (sandbox_mode, model, etc.)

        Returns:
            ExecutionResult with the response
        """
        if not self._initialized:
            await self.initialize()

        # Build command
        cmd = [
            self.CLI_COMMAND,
            "exec",
            "--json",
        ]

        # Add sandbox mode
        sandbox = kwargs.get("sandbox_mode", self.sandbox_mode)
        cmd.extend(["--sandbox", sandbox])

        # Add model if specified
        model = kwargs.get("model", self.model)
        if model:
            cmd.extend(["--model", model])

        # Build full prompt with context
        full_prompt = prompt
        if context:
            context_text = self.build_context_prompt(context)
            full_prompt = f"{context_text}\n\nTask: {prompt}"

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

            # Parse JSONL output (Codex outputs one JSON per line)
            content, raw_output = self._parse_jsonl_output(stdout_text)

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
        """Execute with streaming output."""
        if not self._initialized:
            await self.initialize()

        cmd = [
            self.CLI_COMMAND,
            "exec",
            "--json",
        ]

        sandbox = kwargs.get("sandbox_mode", self.sandbox_mode)
        cmd.extend(["--sandbox", sandbox])

        model = kwargs.get("model", self.model)
        if model:
            cmd.extend(["--model", model])

        full_prompt = prompt
        if context:
            context_text = self.build_context_prompt(context)
            full_prompt = f"{context_text}\n\nTask: {prompt}"

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
                        content, metadata = self._parse_event(decoded)
                        if content:
                            yield StreamChunk(
                                content=content,
                                is_final=False,
                                metadata=metadata,
                            )

            await proc.wait()

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

    def _parse_jsonl_output(self, output: str) -> tuple[str, dict[str, Any] | None]:
        """
        Parse JSONL output from Codex CLI.

        Codex outputs one JSON object per line (JSONL format).
        """
        if not output.strip():
            return "", None

        events = []
        contents = []

        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                events.append(event)
                content = self._extract_content(event)
                if content:
                    contents.append(content)
            except json.JSONDecodeError:
                contents.append(line)

        full_content = "\n".join(contents)
        raw_output = {"events": events} if events else None

        return full_content, raw_output

    def _parse_event(self, line: str) -> tuple[str, dict[str, Any]]:
        """Parse a single event line."""
        try:
            data = json.loads(line)
            content = self._extract_content(data)
            return content, data
        except json.JSONDecodeError:
            return line, {}

    def _extract_content(self, data: Any) -> str:
        """Extract text content from event data."""
        if isinstance(data, str):
            return data

        if isinstance(data, dict):
            # Check for common content fields
            for field in ["content", "text", "message", "output", "result"]:
                if field in data:
                    value = data[field]
                    if isinstance(value, str):
                        return value
                    return self._extract_content(value)

            # Check for type-specific handling
            event_type = data.get("type", "")
            if event_type == "message" and "content" in data:
                return self._extract_content(data["content"])

        return ""
