#!/usr/bin/env python3
"""
Ollama Local Inference Example.

Demonstrates using Ollama for 100% free, local AI inference.
No API costs, no data leaves your machine.

Usage:
    python examples/ollama_local.py

Requirements:
    - pip install sanhedrin[ollama]
    - Ollama installed: https://ollama.ai
    - A model pulled: ollama pull llama3.2
"""

import asyncio
from sanhedrin.adapters.ollama_adapter import OllamaAdapter


async def main():
    """Run Ollama local inference demo."""

    # Create Ollama adapter
    # Uses llama3.2 by default, but you can specify any model
    adapter = OllamaAdapter(
        model="llama3.2",  # Change to your preferred model
        # host="http://localhost:11434",  # Default Ollama server
    )

    print("🦙 Ollama Local Inference Demo")
    print("=" * 50)
    print("100% FREE - No API costs!")
    print("100% PRIVATE - No data leaves your machine!")
    print()

    # Initialize
    print("Initializing...")
    try:
        await adapter.initialize()
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure Ollama is running:")
        print("  1. Install Ollama: https://ollama.ai")
        print("  2. Run: ollama serve")
        print("  3. Pull a model: ollama pull llama3.2")
        return

    print(f"✅ Connected to Ollama")
    print(f"   Model: {adapter.model}")
    print(f"   Host: {adapter.host}")

    # List available models
    models = await adapter.list_models()
    print(f"   Available models: {models}")
    print()

    # Simple prompt
    print("📝 Simple Prompt Demo")
    print("-" * 50)
    prompt = "Write a haiku about programming."
    print(f"Prompt: {prompt}\n")

    result = await adapter.execute(prompt)
    if result.success:
        print(result.content)
    else:
        print(f"Error: {result.error}")

    print()

    # Streaming demo
    print("🌊 Streaming Demo")
    print("-" * 50)
    prompt = "Explain the concept of recursion in one paragraph."
    print(f"Prompt: {prompt}\n")

    async for chunk in adapter.execute_stream(prompt):
        if chunk.content:
            print(chunk.content, end="", flush=True)
        if chunk.is_final:
            print("\n")
            break

    # Code generation
    print("💻 Code Generation Demo")
    print("-" * 50)
    prompt = "Write a Python function to check if a number is prime."
    print(f"Prompt: {prompt}\n")

    result = await adapter.execute(prompt)
    if result.success:
        print(result.content)

    print("\n✅ All demos complete!")
    print("Remember: All inference happened locally - completely free and private!")


async def benchmark():
    """Simple benchmark for local inference."""
    import time

    adapter = OllamaAdapter(model="llama3.2")
    await adapter.initialize()

    prompts = [
        "What is 2+2?",
        "Name three colors.",
        "What is Python?",
    ]

    print("\n📊 Benchmark")
    print("-" * 50)

    for prompt in prompts:
        start = time.time()
        result = await adapter.execute(prompt)
        elapsed = time.time() - start

        tokens = result.metadata.get("eval_count", 0)
        print(f"Prompt: '{prompt[:30]}...'")
        print(f"  Time: {elapsed:.2f}s, Tokens: {tokens}")


if __name__ == "__main__":
    asyncio.run(main())
    # asyncio.run(benchmark())
