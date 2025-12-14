"""
Ollama adapter using Python SDK.

Connects to local Ollama instance for open-source model execution.
100% free, privacy-focused local inference.

Reference: https://github.com/ollama/ollama-python
"""

from __future__ import annotations

import asyncio
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
)

# Optional dependency - gracefully handle if not installed
try:
    import ollama
    from ollama import AsyncClient

    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    ollama = None  # type: ignore[assignment]
    AsyncClient = None  # type: ignore[misc, assignment]


class OllamaAdapter(BaseAdapter):
    """
    Adapter for Ollama local LLM server.

    Uses the Ollama Python SDK to communicate with a local Ollama instance.
    Provides privacy-focused, cost-free local inference.

    Cost Model:
        100% FREE - runs entirely on local hardware.
        No API calls, no data leaves your machine.

    Authentication:
        None required - local server.

    Requirements:
        - Ollama installed and running: https://ollama.ai
        - At least one model pulled: ollama pull llama3.2
        - Python SDK: pip install ollama

    Example:
        >>> adapter = OllamaAdapter(model="llama3.2")
        >>> await adapter.initialize()
        >>> result = await adapter.execute("Write a haiku about coding")
        >>> print(result.content)
    """

    DEFAULT_HOST = "http://localhost:11434"
    DEFAULT_MODEL = "llama3.2"

    def __init__(
        self,
        config: AdapterConfig | None = None,
        host: str | None = None,
        model: str | None = None,
    ) -> None:
        """
        Initialize Ollama adapter.

        Args:
            config: Adapter configuration
            host: Ollama server URL (default: http://localhost:11434)
            model: Model to use (default: llama3.2)
        """
        super().__init__(config)
        self.host = host or self.DEFAULT_HOST
        self.model = model or self.DEFAULT_MODEL
        self._client: AsyncClient | None = None
        self._available_models: list[str] = []

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def display_name(self) -> str:
        return f"Ollama ({self.model})"

    @property
    def description(self) -> str:
        return (
            f"Local Ollama instance running {self.model}. "
            "Provides 100% free, privacy-focused local inference. "
            "No data leaves your machine."
        )

    @property
    def cli_command(self) -> str | None:
        return "ollama"  # For reference, though we use SDK

    @property
    def skills(self) -> list[AgentSkill]:
        return [
            AgentSkill(
                id="local-inference",
                name="Local Inference",
                description="Privacy-focused local model inference",
                tags=["local", "privacy", "inference", "free"],
                examples=[
                    "Summarize this document locally",
                    "Generate code without cloud services",
                    "Analyze sensitive data privately",
                ],
            ),
            AgentSkill(
                id="text-generation",
                name="Text Generation",
                description="General text generation and completion",
                tags=["generation", "completion", "text", "creative"],
                examples=[
                    "Write a blog post about AI",
                    "Continue this story",
                    "Generate product descriptions",
                ],
            ),
            AgentSkill(
                id="chat",
                name="Conversational AI",
                description="Multi-turn conversational capabilities",
                tags=["chat", "conversation", "assistant"],
                examples=[
                    "Help me brainstorm ideas",
                    "Explain this concept",
                    "Answer my questions",
                ],
            ),
            AgentSkill(
                id="code-assistance",
                name="Code Assistance",
                description="Code generation and explanation (model dependent)",
                tags=["coding", "development"],
                examples=[
                    "Write a Python function",
                    "Explain this code",
                    "Fix this bug",
                ],
            ),
        ]

    async def initialize(self) -> None:
        """Initialize Ollama client and verify connection."""
        if not OLLAMA_AVAILABLE:
            raise AdapterInitializationError(
                adapter=self.name,
                message=(
                    "Ollama Python package not installed. "
                    "Install with: pip install ollama"
                ),
            )

        self._client = AsyncClient(host=self.host)

        # Check connection
        if not await self.health_check():
            raise AdapterInitializationError(
                adapter=self.name,
                message=(
                    f"Cannot connect to Ollama at {self.host}. "
                    "Make sure Ollama is running: ollama serve"
                ),
            )

        # Get available models
        try:
            models_response = await self._client.list()
            self._available_models = [
                m.get("name", "") for m in models_response.get("models", [])
            ]
        except Exception:
            self._available_models = []

        # Check if requested model is available
        model_available = any(
            self.model in name or name.startswith(self.model.split(":")[0])
            for name in self._available_models
        )

        if not model_available and self._available_models:
            raise AdapterInitializationError(
                adapter=self.name,
                message=(
                    f"Model '{self.model}' not found. "
                    f"Available models: {', '.join(self._available_models)}. "
                    f"Pull with: ollama pull {self.model}"
                ),
            )
        elif not model_available:
            raise AdapterInitializationError(
                adapter=self.name,
                message=(
                    f"No models available. Pull a model first: ollama pull {self.model}"
                ),
            )

        self._initialized = True

    async def health_check(self) -> bool:
        """Check if Ollama server is running."""
        try:
            if self._client is None:
                if not OLLAMA_AVAILABLE:
                    return False
                self._client = AsyncClient(host=self.host)
            await self._client.list()
            return True
        except Exception:
            return False

    async def execute(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """
        Execute prompt using Ollama.

        Args:
            prompt: The prompt to send
            context: Optional conversation context
            **kwargs: Additional options (temperature, etc.)

        Returns:
            ExecutionResult with the response
        """
        if not self._initialized:
            await self.initialize()

        if self._client is None:
            raise AdapterExecutionError(
                adapter=self.name,
                message="Client not initialized",
            )

        # Build messages for chat format
        messages = self._build_messages(prompt, context)

        try:
            response = await self._client.chat(
                model=kwargs.get("model", self.model),
                messages=messages,
                stream=False,
                options=self._get_options(kwargs),
            )

            content = response.get("message", {}).get("content", "")

            return ExecutionResult(
                success=True,
                content=content,
                raw_output=response,
                exit_code=0,
                metadata={
                    "model": response.get("model", self.model),
                    "total_duration": response.get("total_duration"),
                    "eval_count": response.get("eval_count"),
                },
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
        """Execute with streaming response."""
        if not self._initialized:
            await self.initialize()

        if self._client is None:
            yield StreamChunk(content="", is_final=True)
            return

        messages = self._build_messages(prompt, context)

        try:
            stream = await self._client.chat(
                model=kwargs.get("model", self.model),
                messages=messages,
                stream=True,
                options=self._get_options(kwargs),
            )

            async for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                done = chunk.get("done", False)

                if content or done:
                    yield StreamChunk(
                        content=content,
                        is_final=done,
                        metadata={
                            "model": chunk.get("model", self.model),
                        }
                        if done
                        else {},
                    )

        except Exception as e:
            yield StreamChunk(
                content="",
                is_final=True,
                chunk_type="error",
                metadata={"error": str(e)},
            )

    def _build_messages(
        self,
        prompt: str,
        context: list[Message] | None,
    ) -> list[dict[str, str]]:
        """
        Build Ollama message format from A2A messages.

        Args:
            prompt: Current prompt
            context: Previous messages

        Returns:
            List of message dicts for Ollama
        """
        messages: list[dict[str, str]] = []

        if context:
            for msg in context:
                role = "user" if msg.role.value == "user" else "assistant"
                content = self.message_to_prompt(msg)
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": prompt})
        return messages

    def _get_options(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Build Ollama options from kwargs."""
        options = {}

        if "temperature" in kwargs:
            options["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            options["top_p"] = kwargs["top_p"]
        if "top_k" in kwargs:
            options["top_k"] = kwargs["top_k"]
        if "num_ctx" in kwargs:
            options["num_ctx"] = kwargs["num_ctx"]

        return options

    async def list_models(self) -> list[str]:
        """List available models on the Ollama server."""
        if not self._initialized:
            await self.initialize()

        if self._client is None:
            return []

        try:
            response = await self._client.list()
            return [m.get("name", "") for m in response.get("models", [])]
        except Exception:
            return []

    async def pull_model(self, model: str) -> bool:
        """
        Pull a model from Ollama registry.

        Args:
            model: Model name to pull

        Returns:
            True if successful
        """
        if self._client is None:
            return False

        try:
            await self._client.pull(model)
            return True
        except Exception:
            return False
