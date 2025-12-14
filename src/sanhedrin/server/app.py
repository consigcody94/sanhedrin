"""
FastAPI A2A Server Application.

Exposes AI CLI adapters as A2A Protocol-compliant agents.

Endpoints:
- GET /.well-known/agent.json - Agent Card discovery
- POST /a2a - JSON-RPC 2.0 endpoint (non-streaming)
- POST /a2a/stream - JSON-RPC 2.0 with SSE streaming
- GET /health - Health check
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from sanhedrin.adapters import get_adapter, register_default_adapters
from sanhedrin.adapters.base import BaseAdapter
from sanhedrin.core.types import JSONRPCRequest, JSONRPCResponse
from sanhedrin.server.task_manager import TaskManager
from sanhedrin.server.handlers import JSONRPCHandler
from sanhedrin.server.agent_card import AgentCardBuilder


# Global state
_adapter: BaseAdapter | None = None
_task_manager: TaskManager | None = None
_handler: JSONRPCHandler | None = None
_agent_card_builder: AgentCardBuilder | None = None


def get_adapter_name() -> str:
    """Get adapter name from environment."""
    return os.environ.get("SANHEDRIN_ADAPTER", "claude-code")


def get_base_url() -> str:
    """Get base URL from environment."""
    host = os.environ.get("SANHEDRIN_HOST", "localhost")
    port = os.environ.get("SANHEDRIN_PORT", "8000")
    return os.environ.get("SANHEDRIN_BASE_URL", f"http://{host}:{port}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan handler.

    Initializes adapter and task manager on startup.
    """
    global _adapter, _task_manager, _handler, _agent_card_builder

    # Register all adapters
    register_default_adapters()

    # Get configured adapter
    adapter_name = get_adapter_name()
    _adapter = get_adapter(adapter_name)

    # Initialize adapter
    await _adapter.initialize()

    # Create task manager and handler
    _task_manager = TaskManager(_adapter)
    _handler = JSONRPCHandler(_task_manager)

    # Create agent card builder
    _agent_card_builder = AgentCardBuilder(
        _adapter,
        get_base_url(),
        provider_name="Sanhedrin",
        provider_url="https://github.com/sanhedrin",
    )

    yield

    # Cleanup on shutdown
    _adapter = None
    _task_manager = None
    _handler = None


# Create FastAPI app
app = FastAPI(
    title="Sanhedrin A2A Server",
    description="A2A Protocol Multi-Agent Coordination Server",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/.well-known/agent.json")
async def get_agent_card() -> JSONResponse:
    """
    Agent Card discovery endpoint.

    Returns the A2A Agent Card describing this agent's capabilities.
    """
    if _agent_card_builder is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    card = _agent_card_builder.to_dict()
    return JSONResponse(content=card)


@app.post("/a2a")
async def handle_jsonrpc(request: Request) -> JSONResponse:
    """
    JSON-RPC 2.0 endpoint for non-streaming requests.

    Supports methods:
    - message/send: Send message and get response
    - tasks/get: Get task by ID
    - tasks/cancel: Cancel a task
    """
    if _handler is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    try:
        body = await request.json()
        rpc_request = JSONRPCRequest(**body)
        response = await _handler.handle(rpc_request)

        return JSONResponse(
            content=response.model_dump(by_alias=True, exclude_none=True)
        )

    except Exception as e:
        error_response = JSONRPCResponse(
            id=None,
            error={
                "code": -32700,
                "message": f"Parse error: {str(e)}",
            },
        )
        return JSONResponse(
            content=error_response.model_dump(by_alias=True, exclude_none=True),
            status_code=400,
        )


@app.post("/a2a/stream")
async def handle_jsonrpc_stream(request: Request) -> StreamingResponse:
    """
    JSON-RPC 2.0 endpoint with SSE streaming.

    Supports:
    - message/stream: Send message with streaming response

    Returns Server-Sent Events (SSE) stream.
    """
    if _handler is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    try:
        body = await request.json()
        rpc_request = JSONRPCRequest(**body)

        async def event_generator() -> AsyncIterator[str]:
            async for event in _handler.handle_stream(rpc_request):
                yield event

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Parse error: {str(e)}")


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Health check endpoint.

    Returns adapter status and basic server info.
    """
    if _adapter is None:
        return {
            "status": "initializing",
            "adapter": None,
        }

    is_healthy = await _adapter.health_check()

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "adapter": {
            "name": _adapter.name,
            "display_name": _adapter.display_name,
            "initialized": _adapter.is_initialized,
        },
        "tasks": len(_task_manager) if _task_manager else 0,
    }


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with basic info."""
    return {
        "name": "Sanhedrin A2A Server",
        "version": "0.1.0",
        "protocol": "A2A v0.3",
        "agent_card": "/.well-known/agent.json",
        "docs": "/docs",
    }


def create_app(
    adapter_name: str | None = None,
    base_url: str | None = None,
) -> FastAPI:
    """
    Factory function to create configured app.

    Args:
        adapter_name: Override default adapter
        base_url: Override base URL

    Returns:
        Configured FastAPI app
    """
    if adapter_name:
        os.environ["SANHEDRIN_ADAPTER"] = adapter_name
    if base_url:
        os.environ["SANHEDRIN_BASE_URL"] = base_url

    return app


# For running with uvicorn directly
def serve(
    adapter: str = "claude-code",
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """
    Start the server.

    Args:
        adapter: Adapter name to use
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload for development
    """
    import uvicorn

    os.environ["SANHEDRIN_ADAPTER"] = adapter
    os.environ["SANHEDRIN_HOST"] = host
    os.environ["SANHEDRIN_PORT"] = str(port)

    uvicorn.run(
        "sanhedrin.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )
