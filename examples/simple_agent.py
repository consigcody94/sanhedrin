#!/usr/bin/env python3
"""
Simple Agent Example.

Demonstrates basic adapter usage without the full A2A server.
Directly invokes CLI tools through adapters.

Usage:
    python examples/simple_agent.py

Requirements:
    - pip install sanhedrin
    - Claude Code CLI installed (or change adapter)
"""

import asyncio
from sanhedrin.adapters import get_adapter


async def main():
    """Run a simple prompt through an adapter."""

    # Get an adapter by name
    # Options: claude-code, gemini-cli, codex-cli, ollama
    print("Creating adapter...")
    adapter = get_adapter("claude-code")

    # Alternative: Use Ollama for local inference
    # adapter = get_adapter("ollama", model="llama3.2")

    # Initialize the adapter (verifies CLI is available)
    print("Initializing...")
    await adapter.initialize()

    print(f"Using: {adapter.display_name}")
    print(f"Skills: {[s.name for s in adapter.skills]}")
    print()

    # Execute a prompt
    prompt = "Write a Python function that calculates the fibonacci sequence."
    print(f"Prompt: {prompt}")
    print("-" * 50)

    result = await adapter.execute(prompt)

    if result.success:
        print(result.content)
    else:
        print(f"Error: {result.error}")


async def streaming_example():
    """Demonstrate streaming responses."""

    adapter = get_adapter("claude-code")
    await adapter.initialize()

    prompt = "Explain recursion step by step."
    print(f"Prompt: {prompt}")
    print("-" * 50)

    # Stream the response
    async for chunk in adapter.execute_stream(prompt):
        if chunk.content:
            print(chunk.content, end="", flush=True)
        if chunk.is_final:
            print()  # Final newline
            break


if __name__ == "__main__":
    # Run basic example
    asyncio.run(main())

    # Uncomment for streaming example:
    # asyncio.run(streaming_example())
