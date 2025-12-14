"""
Gemini CLI adapter.

Wraps Google's Gemini CLI for A2A-compatible execution.
Uses subprocess to invoke `gemini` for cost-effective operation
using the user's existing Google account.

Reference: https://github.com/google-gemini/gemini-cli
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


class GeminiCLIAdapter(BaseAdapter):
    """
    Adapter for Google Gemini CLI.

    Invokes the locally installed `gemini` command via subprocess.
    Uses your Google account authentication.

    Cost Model:
        Uses your existing Google/Gemini subscription.
        Free tier available for limited usage.

    Authentication:
        - OAuth (default): Uses Gemini CLI's built-in Google auth
        - API Key: Set GOOGLE_API_KEY or GEMINI_API_KEY

    Example:
        >>> adapter = GeminiCLIAdapter()
        >>> await adapter.initialize()
        >>> result = await adapter.execute("Explain quantum computing")
        >>> print(result.content)
    """

    CLI_COMMAND = "gemini"
    INSTALL_HINT = "Install via npm: npm install -g @google/gemini-cli"

    def __init__(
        self,
        config: AdapterConfig | None = None,
        model: str | None = None,
    ) -> None:
        """
        Initialize Gemini CLI adapter.

        Args:
            config: Adapter configuration
            model: Optional model override
        """
        super().__init__(config)
        self.model = model
        self._cli_path: str | None = None

    @property
    def name(self) -> str:
        return "gemini-cli"

    @property
    def display_name(self) -> str:
        return "Gemini CLI"

    @property
    def description(self) -> str:
        return (
            "Google's Gemini CLI - an open-source AI agent with access to "
            "Gemini models, 1M+ token context, web search grounding, and "
            "built-in tools. Uses your Google account."
        )

    @property
    def cli_command(self) -> str:
        return self.CLI_COMMAND

    @property
    def skills(self) -> list[AgentSkill]:
        return [
            AgentSkill(
                id="general-reasoning",
                name="General Reasoning",
                description="Advanced reasoning and problem-solving capabilities",
                tags=["reasoning", "analysis", "problem-solving", "thinking"],
                examples=[
                    "Explain the tradeoffs between microservices and monoliths",
                    "Help me design a system architecture",
                    "What are the implications of this decision?",
                ],
            ),
            AgentSkill(
                id="code-assistance",
                name="Code Assistance",
                description="Code generation, review, and debugging",
                tags=["coding", "development", "debugging", "review"],
                examples=[
                    "Write a Go function for rate limiting",
                    "Review this TypeScript code",
                    "Help me debug this Python script",
                ],
            ),
            AgentSkill(
                id="web-search",
                name="Web Search Grounding",
                description="Answer questions with up-to-date web information",
                tags=["search", "research", "current-events", "facts"],
                examples=[
                    "What are the latest features in Python 3.13?",
                    "Find recent papers on transformer architectures",
                    "What happened in tech news today?",
                ],
            ),
            AgentSkill(
                id="long-context",
                name="Long Context Analysis",
                description="Analyze large documents and codebases (1M+ tokens)",
                tags=["analysis", "documents", "large-context"],
                examples=[
                    "Summarize this entire codebase",
                    "Analyze these log files",
                    "Review this large document",
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
                message="Gemini CLI health check failed. Run 'gemini --version' to verify.",
            )

        self._initialized = True

    async def health_check(self) -> bool:
        """Check if Gemini CLI is available."""
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
        Execute prompt using Gemini CLI.

        Args:
            prompt: The prompt to send
            context: Optional conversation context
            **kwargs: Additional options

        Returns:
            ExecutionResult with the response
        """
        if not self._initialized:
            await self.initialize()

        # Build full prompt with context
        full_prompt = prompt
        if context:
            context_text = self.build_context_prompt(context)
            full_prompt = f"{context_text}\n\nUser: {prompt}"

        # Gemini CLI accepts prompt via stdin or as argument
        cmd = [self.CLI_COMMAND, "--output-format", "json"]

        if self.model:
            cmd.extend(["--model", self.model])

        # Pass prompt as stdin for better handling of special characters
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._get_env(),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=full_prompt.encode()),
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
        """Execute with streaming output."""
        if not self._initialized:
            await self.initialize()

        full_prompt = prompt
        if context:
            context_text = self.build_context_prompt(context)
            full_prompt = f"{context_text}\n\nUser: {prompt}"

        cmd = [self.CLI_COMMAND, "--output-format", "stream-json"]

        if self.model:
            cmd.extend(["--model", self.model])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._get_env(),
        )

        try:
            # Send prompt to stdin
            if proc.stdin:
                proc.stdin.write(full_prompt.encode())
                await proc.stdin.drain()
                proc.stdin.close()

            if proc.stdout is None:
                yield StreamChunk(content="", is_final=True)
                return

            async for line in proc.stdout:
                if line:
                    content = line.decode().strip()
                    if content:
                        # Try to parse as JSON
                        try:
                            data = json.loads(content)
                            text = self._extract_content(data)
                            yield StreamChunk(
                                content=text,
                                is_final=False,
                                metadata=data if isinstance(data, dict) else {},
                            )
                        except json.JSONDecodeError:
                            yield StreamChunk(content=content, is_final=False)

            await proc.wait()
            yield StreamChunk(content="", is_final=True)

        except Exception as e:
            yield StreamChunk(
                content="",
                is_final=True,
                chunk_type="error",
                metadata={"error": str(e)},
            )

    def _get_env(self) -> dict[str, str]:
        """Get environment with API keys."""
        env = os.environ.copy()
        # Gemini CLI looks for these
        return env

    def _parse_output(self, output: str) -> tuple[str, dict[str, Any] | None]:
        """Parse CLI output."""
        if not output.strip():
            return "", None

        try:
            data = json.loads(output)
            content = self._extract_content(data)
            return content, data
        except json.JSONDecodeError:
            return output.strip(), None

    def _extract_content(self, data: Any) -> str:
        """Extract text content from JSON output."""
        if isinstance(data, str):
            return data

        if isinstance(data, list):
            contents = []
            for item in data:
                contents.append(self._extract_content(item))
            return "\n".join(filter(None, contents))

        if isinstance(data, dict):
            for field in ["text", "content", "response", "result", "output", "message"]:
                if field in data:
                    value = data[field]
                    if isinstance(value, str):
                        return value
                    return self._extract_content(value)

        return str(data) if data else ""
