#!/usr/bin/env python3
"""
A2A Protocol Client Example.

Demonstrates connecting to an A2A-compliant agent server and
sending messages using the JSON-RPC protocol.

Usage:
    # First, start the server in another terminal:
    sanhedrin serve --adapter claude-code

    # Then run this client:
    python examples/a2a_client.py

Requirements:
    - pip install sanhedrin httpx
    - A running Sanhedrin server
"""

import asyncio
import json
import httpx


class A2AClient:
    """Simple A2A Protocol client."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)
        self._request_id = 0

    def _next_id(self) -> str:
        self._request_id += 1
        return f"req-{self._request_id}"

    async def discover(self) -> dict:
        """Fetch agent card."""
        response = await self.client.get(
            f"{self.base_url}/.well-known/agent.json"
        )
        response.raise_for_status()
        return response.json()

    async def send_message(self, message: str) -> dict:
        """Send a message and get response."""
        rpc_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"text": message}],
                }
            },
        }

        response = await self.client.post(
            f"{self.base_url}/a2a",
            json=rpc_request,
        )
        response.raise_for_status()
        return response.json()

    async def send_message_stream(self, message: str):
        """Send a message with streaming response."""
        rpc_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "message/stream",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"text": message}],
                }
            },
        }

        async with self.client.stream(
            "POST",
            f"{self.base_url}/a2a/stream",
            json=rpc_request,
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    yield data

    async def get_task(self, task_id: str) -> dict:
        """Get task status."""
        rpc_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tasks/get",
            "params": {"taskId": task_id},
        }

        response = await self.client.post(
            f"{self.base_url}/a2a",
            json=rpc_request,
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()


async def main():
    """Demonstrate A2A client usage."""

    # Connect to local server
    base_url = "http://localhost:8000"
    client = A2AClient(base_url)

    try:
        # Discover agent
        print("🔍 Discovering agent...")
        card = await client.discover()
        print(f"   Name: {card.get('name')}")
        print(f"   Description: {card.get('description')}")
        print(f"   Skills: {[s['name'] for s in card.get('skills', [])]}")
        print()

        # Send a message (non-streaming)
        print("📤 Sending message...")
        prompt = "What is the capital of France?"
        result = await client.send_message(prompt)

        if "error" in result:
            print(f"❌ Error: {result['error']['message']}")
        else:
            task = result.get("result", {})
            print(f"   Task ID: {task.get('taskId')}")
            print(f"   State: {task.get('status', {}).get('state')}")

            # Get agent response from history
            for msg in task.get("history", []):
                if msg.get("role") == "agent":
                    for part in msg.get("parts", []):
                        if "text" in part:
                            print(f"   Response: {part['text']}")

        print()

        # Streaming example
        print("📤 Sending message (streaming)...")
        prompt = "Count from 1 to 5 slowly."
        print(f"   Prompt: {prompt}")
        print("   Response: ", end="", flush=True)

        async for event in client.send_message_stream(prompt):
            result = event.get("result", {})
            artifact = result.get("artifact", {})

            if artifact:
                for part in artifact.get("parts", []):
                    if "text" in part:
                        print(part["text"], end="", flush=True)

            if result.get("final"):
                print()
                break

    except httpx.ConnectError:
        print(f"❌ Could not connect to {base_url}")
        print("   Make sure the server is running:")
        print("   sanhedrin serve --adapter claude-code")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
