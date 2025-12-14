"""
Sanhedrin CLI.

Command-line interface for the A2A Protocol Multi-Agent System.

Commands:
- serve: Start an A2A server with specified adapter
- discover: Fetch and display an agent's card
- send: Send a message to an agent
- catalog: Manage agent catalog
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

app = typer.Typer(
    name="sanhedrin",
    help="A2A Protocol Multi-Agent Coordination System",
    no_args_is_help=True,
)

console = Console()


@app.command()
def serve(
    adapter: str = typer.Option(
        "claude-code",
        "--adapter",
        "-a",
        help="Adapter to use (claude-code, gemini-cli, codex-cli, ollama)",
    ),
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        "-h",
        help="Host to bind to",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port to bind to",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        "-r",
        help="Enable auto-reload for development",
    ),
) -> None:
    """
    Start an A2A server with the specified adapter.

    Examples:
        sanhedrin serve --adapter claude-code
        sanhedrin serve -a ollama -p 8001
    """
    console.print(
        Panel(
            f"[bold green]Starting Sanhedrin A2A Server[/bold green]\n\n"
            f"Adapter: [cyan]{adapter}[/cyan]\n"
            f"URL: [cyan]http://{host}:{port}[/cyan]\n"
            f"Agent Card: [cyan]http://{host}:{port}/.well-known/agent.json[/cyan]",
            title="⚖️ Sanhedrin",
        )
    )

    try:
        from sanhedrin.server import serve as start_server

        start_server(adapter=adapter, host=host, port=port, reload=reload)
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] Server dependencies not installed. "
            f"Run: pip install sanhedrin[server]\n{e}"
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error starting server:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def discover(
    url: str = typer.Argument(
        ...,
        help="Agent URL (e.g., http://localhost:8000)",
    ),
) -> None:
    """
    Fetch and display an agent's card.

    Example:
        sanhedrin discover http://localhost:8000
    """
    import httpx

    # Normalize URL
    base_url = url.rstrip("/")
    card_url = f"{base_url}/.well-known/agent.json"

    console.print(f"Fetching agent card from [cyan]{card_url}[/cyan]...")

    try:
        response = httpx.get(card_url, timeout=10.0)
        response.raise_for_status()
        card = response.json()

        # Display card
        console.print()
        console.print(Panel(f"[bold]{card.get('name', 'Unknown')}[/bold]", title="Agent"))
        console.print(f"[dim]Description:[/dim] {card.get('description', 'N/A')}")
        console.print(f"[dim]URL:[/dim] {card.get('url', 'N/A')}")
        console.print(f"[dim]Version:[/dim] {card.get('version', 'N/A')}")

        # Capabilities
        caps = card.get("capabilities", {})
        console.print(f"\n[bold]Capabilities:[/bold]")
        console.print(f"  Streaming: {'✅' if caps.get('streaming') else '❌'}")
        console.print(f"  Push Notifications: {'✅' if caps.get('pushNotifications') else '❌'}")

        # Skills
        skills = card.get("skills", [])
        if skills:
            console.print(f"\n[bold]Skills ({len(skills)}):[/bold]")
            table = Table(show_header=True, header_style="bold")
            table.add_column("ID")
            table.add_column("Name")
            table.add_column("Tags")

            for skill in skills:
                table.add_row(
                    skill.get("id", ""),
                    skill.get("name", ""),
                    ", ".join(skill.get("tags", [])),
                )

            console.print(table)

        # Raw JSON
        console.print(f"\n[dim]Raw JSON:[/dim]")
        console.print(Syntax(json.dumps(card, indent=2), "json"))

    except httpx.RequestError as e:
        console.print(f"[red]Connection error:[/red] {e}")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP error:[/red] {e.response.status_code}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def send(
    url: str = typer.Argument(
        ...,
        help="Agent URL (e.g., http://localhost:8000)",
    ),
    message: str = typer.Argument(
        ...,
        help="Message to send",
    ),
    stream: bool = typer.Option(
        False,
        "--stream",
        "-s",
        help="Use streaming response",
    ),
) -> None:
    """
    Send a message to an agent.

    Examples:
        sanhedrin send http://localhost:8000 "Write hello world in Python"
        sanhedrin send http://localhost:8000 "Explain recursion" --stream
    """
    import httpx

    base_url = url.rstrip("/")

    # Build JSON-RPC request
    rpc_request = {
        "jsonrpc": "2.0",
        "id": "cli-1",
        "method": "message/stream" if stream else "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"text": message}],
            }
        },
    }

    endpoint = f"{base_url}/a2a/stream" if stream else f"{base_url}/a2a"

    console.print(f"Sending to [cyan]{endpoint}[/cyan]...")
    console.print()

    try:
        if stream:
            # Streaming response
            with httpx.stream(
                "POST",
                endpoint,
                json=rpc_request,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                        result = data.get("result", {})

                        # Extract artifact content
                        artifact = result.get("artifact", {})
                        if artifact:
                            for part in artifact.get("parts", []):
                                if "text" in part:
                                    console.print(part["text"], end="")

                        # Check for final status
                        if result.get("final"):
                            console.print()
                            break
        else:
            # Non-streaming
            response = httpx.post(
                endpoint,
                json=rpc_request,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                console.print(f"[red]Error:[/red] {data['error'].get('message', 'Unknown')}")
                raise typer.Exit(1)

            result = data.get("result", {})

            # Display response
            for msg in result.get("history", []):
                if msg.get("role") == "agent":
                    for part in msg.get("parts", []):
                        if "text" in part:
                            console.print(part["text"])

    except httpx.RequestError as e:
        console.print(f"[red]Connection error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def list_adapters() -> None:
    """
    List available adapters.
    """
    from sanhedrin.adapters import register_default_adapters, get_registry

    register_default_adapters()
    registry = get_registry()

    console.print(Panel("[bold]Available Adapters[/bold]", title="⚖️ Sanhedrin"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Aliases")

    # Group by adapter class
    seen_classes = {}
    for name in registry.list_adapters():
        adapter_class = registry.get(name)
        class_name = adapter_class.__name__

        if class_name not in seen_classes:
            seen_classes[class_name] = [name]
        else:
            seen_classes[class_name].append(name)

    for class_name, names in seen_classes.items():
        primary = names[0]
        aliases = ", ".join(names[1:]) if len(names) > 1 else "-"
        table.add_row(primary, aliases)

    console.print(table)


@app.command()
def version() -> None:
    """Show version information."""
    from sanhedrin import __version__

    console.print(
        Panel(
            f"[bold]Sanhedrin[/bold] v{__version__}\n\n"
            "A2A Protocol Multi-Agent Coordination System\n"
            "[dim]https://github.com/sanhedrin[/dim]",
            title="⚖️",
        )
    )


def main() -> None:
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
