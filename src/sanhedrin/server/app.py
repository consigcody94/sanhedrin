"""
FastAPI A2A Server Application.

Exposes AI CLI adapters as A2A Protocol-compliant agents.

Endpoints:
- GET /.well-known/agent.json - Agent Card discovery
- POST /a2a - JSON-RPC 2.0 endpoint (non-streaming)
- POST /a2a/stream - JSON-RPC 2.0 with SSE streaming
- GET /health - Health check
- GET /metrics - Prometheus-style metrics
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from sanhedrin.adapters import get_adapter, register_default_adapters
from sanhedrin.adapters.base import BaseAdapter
from sanhedrin.core.types import JSONRPCRequest, JSONRPCErrorResponse, JSONRPCError
from sanhedrin.server.task_manager import TaskManager
from sanhedrin.server.handlers import JSONRPCHandler
from sanhedrin.server.agent_card import AgentCardBuilder
from sanhedrin.auth import (
    SecurityMiddleware,
    SecurityConfig,
    APIKeyConfig,
    RateLimitConfig,
    create_security_config_from_env,
)


# Configure logging
logging.basicConfig(
    level=os.environ.get("SANHEDRIN_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sanhedrin.server")


# Global state (protected by asyncio locks for thread safety)
_adapter: BaseAdapter | None = None
_task_manager: TaskManager | None = None
_handler: JSONRPCHandler | None = None
_agent_card_builder: AgentCardBuilder | None = None
_cleanup_task: asyncio.Task[None] | None = None
_state_lock = asyncio.Lock()

# Metrics
_metrics = {
    "requests_total": 0,
    "requests_success": 0,
    "requests_error": 0,
    "tasks_created": 0,
    "tasks_completed": 0,
    "tasks_failed": 0,
    "startup_time": None,
    "last_cleanup": None,
    "tasks_cleaned": 0,
}


def get_adapter_name() -> str:
    """Get adapter name from environment."""
    return os.environ.get("SANHEDRIN_ADAPTER", "claude-code")


def get_base_url() -> str:
    """Get base URL from environment."""
    host = os.environ.get("SANHEDRIN_HOST", "localhost")
    port = os.environ.get("SANHEDRIN_PORT", "8000")
    return os.environ.get("SANHEDRIN_BASE_URL", f"http://{host}:{port}")


def get_cors_origins() -> list[str]:
    """Get allowed CORS origins from environment."""
    origins_str = os.environ.get("SANHEDRIN_CORS_ORIGINS", "")
    if not origins_str:
        # Default to no CORS in production, localhost in development
        if os.environ.get("SANHEDRIN_ENV", "production") == "development":
            return ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:3000"]
        return []
    return [o.strip() for o in origins_str.split(",") if o.strip()]


async def cleanup_tasks_periodically() -> None:
    """Background task to clean up old completed tasks."""
    global _metrics
    cleanup_interval = int(os.environ.get("SANHEDRIN_CLEANUP_INTERVAL", "300"))  # 5 min
    max_task_age = int(os.environ.get("SANHEDRIN_TASK_MAX_AGE", "3600"))  # 1 hour

    logger.info(f"Task cleanup started (interval: {cleanup_interval}s, max_age: {max_task_age}s)")

    while True:
        try:
            await asyncio.sleep(cleanup_interval)

            if _task_manager is not None:
                cleaned = _task_manager.cleanup_completed(max_age_seconds=max_task_age)
                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} old tasks")
                    _metrics["tasks_cleaned"] += cleaned
                _metrics["last_cleanup"] = datetime.now(timezone.utc).isoformat()

        except asyncio.CancelledError:
            logger.info("Task cleanup stopped")
            break
        except Exception as e:
            logger.error(f"Error in task cleanup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan handler.

    Initializes adapter and task manager on startup.
    Handles graceful shutdown with task draining.
    """
    global _adapter, _task_manager, _handler, _agent_card_builder, _cleanup_task, _metrics

    logger.info("Starting Sanhedrin A2A Server...")
    start_time = time.time()

    # Register all adapters
    register_default_adapters()
    logger.debug("Registered default adapters")

    # Get configured adapter
    adapter_name = get_adapter_name()
    logger.info(f"Loading adapter: {adapter_name}")

    async with _state_lock:
        _adapter = get_adapter(adapter_name)

        # Initialize adapter
        await _adapter.initialize()
        logger.info(f"Adapter {adapter_name} initialized successfully")

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

    # Start background cleanup task
    _cleanup_task = asyncio.create_task(cleanup_tasks_periodically())

    _metrics["startup_time"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"Server started in {time.time() - start_time:.2f}s")

    yield

    # Graceful shutdown
    logger.info("Shutting down Sanhedrin A2A Server...")

    # Cancel cleanup task
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass

    # Wait for in-flight requests (grace period)
    grace_period = int(os.environ.get("SANHEDRIN_SHUTDOWN_GRACE", "5"))
    logger.info(f"Waiting {grace_period}s for in-flight requests...")
    await asyncio.sleep(grace_period)

    async with _state_lock:
        _adapter = None
        _task_manager = None
        _handler = None

    logger.info("Server shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Sanhedrin A2A Server",
    description="A2A Protocol Multi-Agent Coordination Server",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# Configure CORS properly - restrict origins in production
cors_origins = get_cors_origins()
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
        max_age=3600,
    )
    logger.info(f"CORS enabled for origins: {cors_origins}")
else:
    logger.info("CORS disabled (no origins configured)")


# Add security middleware
security_config = create_security_config_from_env()
app.add_middleware(SecurityMiddleware, config=security_config)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log requests and track metrics."""
    global _metrics

    request_id = request.headers.get("X-Request-ID", "")
    start = time.time()

    logger.debug(f"[{request_id}] {request.method} {request.url.path}")
    _metrics["requests_total"] += 1

    try:
        response = await call_next(request)
        duration = time.time() - start

        if response.status_code < 400:
            _metrics["requests_success"] += 1
        else:
            _metrics["requests_error"] += 1

        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"- {response.status_code} ({duration:.3f}s)"
        )

        response.headers["X-Request-ID"] = request_id or "-"
        response.headers["X-Response-Time"] = f"{duration:.3f}s"

        return response
    except Exception as e:
        _metrics["requests_error"] += 1
        logger.error(f"[{request_id}] Request failed: {e}")
        raise


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
    global _metrics

    if _handler is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    try:
        body = await request.json()

        # Input validation
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")

        # Validate required fields
        if "method" not in body:
            raise ValueError("Missing required field: method")

        rpc_request = JSONRPCRequest(**body)

        # Track task creation
        if rpc_request.method == "message/send":
            _metrics["tasks_created"] += 1

        response = await _handler.handle(rpc_request)

        # Track completion - check response type
        if hasattr(response, 'result') and response.result:
            if rpc_request.method == "message/send":
                _metrics["tasks_completed"] += 1
        elif hasattr(response, 'error') and response.error:
            if rpc_request.method == "message/send":
                _metrics["tasks_failed"] += 1

        return JSONResponse(
            content=response.model_dump(by_alias=True, exclude_none=True)
        )

    except ValueError as e:
        logger.warning(f"Invalid request: {e}")
        error_response = JSONRPCErrorResponse(
            id=None,
            error=JSONRPCError(
                code=-32600,
                message=f"Invalid request: {str(e)}",
            ),
        )
        return JSONResponse(
            content=error_response.model_dump(by_alias=True, exclude_none=True),
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Request processing error: {e}")
        error_response = JSONRPCErrorResponse(
            id=None,
            error=JSONRPCError(
                code=-32700,
                message="Parse error",
            ),
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

        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")

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

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
    except Exception as e:
        logger.error(f"Stream request error: {e}")
        raise HTTPException(status_code=400, detail="Parse error")


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


@app.get("/metrics")
async def get_metrics() -> PlainTextResponse:
    """
    Prometheus-style metrics endpoint.

    Returns metrics in text format for scraping.
    """
    lines = [
        "# HELP sanhedrin_requests_total Total number of requests",
        "# TYPE sanhedrin_requests_total counter",
        f'sanhedrin_requests_total {_metrics["requests_total"]}',
        "",
        "# HELP sanhedrin_requests_success Successful requests",
        "# TYPE sanhedrin_requests_success counter",
        f'sanhedrin_requests_success {_metrics["requests_success"]}',
        "",
        "# HELP sanhedrin_requests_error Failed requests",
        "# TYPE sanhedrin_requests_error counter",
        f'sanhedrin_requests_error {_metrics["requests_error"]}',
        "",
        "# HELP sanhedrin_tasks_created Total tasks created",
        "# TYPE sanhedrin_tasks_created counter",
        f'sanhedrin_tasks_created {_metrics["tasks_created"]}',
        "",
        "# HELP sanhedrin_tasks_completed Successfully completed tasks",
        "# TYPE sanhedrin_tasks_completed counter",
        f'sanhedrin_tasks_completed {_metrics["tasks_completed"]}',
        "",
        "# HELP sanhedrin_tasks_failed Failed tasks",
        "# TYPE sanhedrin_tasks_failed counter",
        f'sanhedrin_tasks_failed {_metrics["tasks_failed"]}',
        "",
        "# HELP sanhedrin_tasks_active Currently active tasks",
        "# TYPE sanhedrin_tasks_active gauge",
        f'sanhedrin_tasks_active {len(_task_manager) if _task_manager else 0}',
        "",
        "# HELP sanhedrin_tasks_cleaned Tasks cleaned up",
        "# TYPE sanhedrin_tasks_cleaned counter",
        f'sanhedrin_tasks_cleaned {_metrics["tasks_cleaned"]}',
    ]

    return PlainTextResponse("\n".join(lines), media_type="text/plain")


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with basic info."""
    return {
        "name": "Sanhedrin A2A Server",
        "version": "0.1.0",
        "protocol": "A2A v0.3",
        "agent_card": "/.well-known/agent.json",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
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
    host: str = "127.0.0.1",  # Default to localhost for security
    port: int = 8000,
    reload: bool = False,
) -> None:
    """
    Start the server.

    Args:
        adapter: Adapter name to use
        host: Host to bind to (default: 127.0.0.1 for security)
        port: Port to bind to
        reload: Enable auto-reload for development
    """
    import uvicorn

    os.environ["SANHEDRIN_ADAPTER"] = adapter
    os.environ["SANHEDRIN_HOST"] = host
    os.environ["SANHEDRIN_PORT"] = str(port)

    logger.info(f"Starting server on {host}:{port} with adapter {adapter}")

    uvicorn.run(
        "sanhedrin.server.app:app",
        host=host,
        port=port,
        reload=reload,
        access_log=True,
    )
