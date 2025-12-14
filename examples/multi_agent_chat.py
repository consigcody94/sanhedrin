#!/usr/bin/env python3
"""
Multi-Agent Chat Example.

Demonstrates orchestration with multiple agents using the catalog
and router for intelligent task routing.

Usage:
    python examples/multi_agent_chat.py

Requirements:
    - pip install sanhedrin[ollama]
    - At least one CLI tool installed (claude, gemini, codex, or ollama)
"""

import asyncio
from sanhedrin.adapters import get_adapter, register_default_adapters
from sanhedrin.orchestration import AgentCatalog, AgentRouter, RoutingStrategy


async def main():
    """Run multi-agent orchestration demo."""

    # Create catalog
    catalog = AgentCatalog()

    # Register available adapters
    register_default_adapters()

    # Try to register multiple agents
    # (These will fail gracefully if CLIs aren't installed)

    adapters_to_try = [
        ("claude", "claude-code"),
        ("ollama", "ollama"),
        # ("gemini", "gemini-cli"),
        # ("codex", "codex-cli"),
    ]

    for name, adapter_type in adapters_to_try:
        try:
            adapter = get_adapter(adapter_type)
            await catalog.register(name, adapter, initialize=True)
            print(f"✅ Registered {name}")
        except Exception as e:
            print(f"⚠️ Could not register {name}: {e}")

    if len(catalog) == 0:
        print("❌ No agents available. Install at least one CLI tool.")
        return

    print(f"\n📋 Catalog has {len(catalog)} agent(s)")
    print(f"   Skills: {catalog.all_skills}")
    print(f"   Tags: {catalog.all_tags}")

    # Create router
    router = AgentRouter(catalog, strategy=RoutingStrategy.SKILL_MATCH)

    # Route tasks to appropriate agents
    tasks = [
        {"message": "Write a sorting algorithm", "tags": ["coding"]},
        {"message": "Explain quantum computing", "tags": ["reasoning"]},
        {"message": "Review this code for bugs", "tags": ["coding", "review"]},
    ]

    print("\n" + "=" * 60)
    print("Routing tasks to agents...")
    print("=" * 60)

    for task in tasks:
        # Route to best agent
        agent_entry = router.route({"tags": task["tags"]})

        if agent_entry:
            print(f"\n📌 Task: {task['message']}")
            print(f"   Tags: {task['tags']}")
            print(f"   Routed to: {agent_entry.name}")

            # Execute
            result = await agent_entry.adapter.execute(task["message"])

            if result.success:
                # Show first 200 chars
                preview = result.content[:200] + "..." if len(result.content) > 200 else result.content
                print(f"   Response: {preview}")
            else:
                print(f"   Error: {result.error}")
        else:
            print(f"\n❌ No agent found for: {task['message']}")


async def round_robin_demo():
    """Demonstrate round-robin load balancing."""

    catalog = AgentCatalog()

    # Register multiple instances of same adapter for load balancing demo
    for i in range(3):
        try:
            adapter = get_adapter("ollama")
            await catalog.register(f"ollama-{i}", adapter, initialize=True)
        except Exception:
            pass

    if len(catalog) == 0:
        print("Need Ollama for this demo")
        return

    router = AgentRouter(catalog, strategy=RoutingStrategy.ROUND_ROBIN)

    print("Round-robin routing demo:")
    for i in range(6):
        agent = router.route()
        if agent:
            print(f"  Request {i+1} -> {agent.name}")


if __name__ == "__main__":
    asyncio.run(main())
