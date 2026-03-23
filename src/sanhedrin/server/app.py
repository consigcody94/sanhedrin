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
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from sanhedrin.adapters import get_adapter, register_default_adapters
from sanhedrin.auth import (
    APIKeyConfig,
    RateLimitConfig,
    SecurityConfig,
    SecurityMiddleware,
)
from sanhedrin.config.settings import get_settings
from sanhedrin.core.errors import SanhedrinError
from sanhedrin.core.types import (
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    JSONRPCSuccessResponse,
)
from sanhedrin.logging import configure_logging
from sanhedrin.server import metrics as prom
from sanhedrin.server.agent_card import AgentCardBuilder
from sanhedrin.server.handlers import JSONRPCHandler
from sanhedrin.server.task_manager import TaskManager

logger = logging.getLogger("sanhedrin.server")


async def cleanup_tasks_periodically(app: FastAPI) -> None:
    """Background task to clean up old completed tasks."""
    settings = get_settings()
    cleanup_interval = settings.task.cleanup_interval
    max_task_age = settings.task.task_max_age

    logger.info(
        "Task cleanup started (interval: %ds, max_age: %ds)",
        cleanup_interval,
        max_task_age,
    )

    while True:
        try:
            await asyncio.sleep(cleanup_interval)

            task_manager: TaskManager | None = getattr(app.state, "task_manager", None)
            if task_manager is not None:
                cleaned = task_manager.cleanup_completed(max_age_seconds=max_task_age)
                if cleaned > 0:
                    logger.info("Cleaned up %d old tasks", cleaned)
                    prom.tasks_cleaned.inc(cleaned)

        except asyncio.CancelledError:
            logger.info("Task cleanup stopped")
            break
        except Exception as e:
            logger.error("Error in task cleanup: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan handler.

    Initializes adapter and task manager on startup.
    Handles graceful shutdown with task draining.
    """
    settings = get_settings()

    # Configure structured logging
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.log_json,
    )

    logger.info("Starting Sanhedrin A2A Server...")
    start_time = time.time()

    # Register all adapters
    register_default_adapters()
    logger.debug("Registered default adapters")

    # Get configured adapter
    adapter_name = settings.adapter.adapter
    logger.info("Loading adapter: %s", adapter_name)

    adapter = get_adapter(adapter_name)
    await adapter.initialize()
    logger.info("Adapter %s initialized successfully", adapter_name)

    # Create task manager and handler
    task_manager = TaskManager(adapter)
    handler = JSONRPCHandler(task_manager)

    # Create agent card builder
    agent_card_builder = AgentCardBuilder(
        adapter,
        settings.get_base_url(),
        provider_name=settings.provider_name,
        provider_url=settings.provider_url,
    )

    # Store on app.state for dependency injection
    app.state.adapter = adapter
    app.state.task_manager = task_manager
    app.state.handler = handler
    app.state.agent_card_builder = agent_card_builder

    logger.info("Server started in %.2fs", time.time() - start_time)

    # Use TaskGroup for structured concurrency
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(cleanup_tasks_periodically(app))
            yield
            # TaskGroup cancels all tasks on scope exit
    except* asyncio.CancelledError:
        pass

    # Graceful shutdown
    logger.info("Shutting down Sanhedrin A2A Server...")
    grace_period = settings.server.shutdown_grace_period
    logger.info("Waiting %ds for in-flight requests...", grace_period)
    await asyncio.sleep(grace_period)

    app.state.adapter = None
    app.state.task_manager = None
    app.state.handler = None

    logger.info("Server shutdown complete")


def _create_security_config() -> SecurityConfig:
    """Create security config from Settings."""
    settings = get_settings()
    return SecurityConfig(
        api_key=APIKeyConfig(
            enabled=settings.security.auth_enabled,
            keys=set(settings.security.api_keys_list),
        ),
        rate_limit=RateLimitConfig(
            enabled=settings.security.rate_limit_enabled,
            requests_per_minute=settings.security.rate_limit_per_minute,
            requests_per_hour=settings.security.rate_limit_per_hour,
            burst_size=settings.security.rate_limit_burst,
        ),
    )


# Create FastAPI app
app = FastAPI(
    title="Sanhedrin A2A Server",
    description="A2A Protocol Multi-Agent Coordination Server",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS from settings
_settings = get_settings()
_cors_origins = _settings.security.cors_origins_list
if not _cors_origins and _settings.is_development:
    _cors_origins = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
    ]

if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
        max_age=3600,
    )

# Add security middleware
app.add_middleware(SecurityMiddleware, config=_create_security_config())


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Any:
    """Log requests and track metrics."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.time()

    logger.debug("[%s] %s %s", request_id, request.method, request.url.path)

    try:
        response = await call_next(request)
        duration = time.time() - start

        status_class = f"{response.status_code // 100}xx"
        prom.requests_total.labels(
            method=request.method, status_class=status_class
        ).inc()
        prom.request_duration.labels(method=request.method).observe(duration)

        logger.info(
            "[%s] %s %s - %d (%.3fs)",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"

        return response
    except Exception as e:
        prom.requests_total.labels(method=request.method, status_class="5xx").inc()
        logger.error("[%s] Request failed: %s", request_id, e)
        raise


def _get_handler(request: Request) -> JSONRPCHandler:
    """Get handler from app state."""
    handler: JSONRPCHandler | None = getattr(request.app.state, "handler", None)
    if handler is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    return handler


@app.get("/.well-known/agent.json")
async def get_agent_card(request: Request) -> JSONResponse:
    """
    Agent Card discovery endpoint.

    Returns the A2A Agent Card describing this agent's capabilities.
    """
    builder: AgentCardBuilder | None = getattr(
        request.app.state, "agent_card_builder", None
    )
    if builder is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    card = builder.to_dict()
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
    handler = _get_handler(request)

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
            prom.tasks_created.inc()

        response = await handler.handle(rpc_request)

        # Track completion by response type
        if rpc_request.method == "message/send":
            if isinstance(response, JSONRPCSuccessResponse):
                prom.tasks_completed.inc()
            elif isinstance(response, JSONRPCErrorResponse):
                prom.tasks_failed.inc()

        return JSONResponse(
            content=response.model_dump(by_alias=True, exclude_none=True)
        )

    except json.JSONDecodeError as e:
        logger.warning("JSON parse error: %s", e)
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
    except ValueError as e:
        logger.warning("Invalid request: %s", e)
        error_response = JSONRPCErrorResponse(
            id=None,
            error=JSONRPCError(
                code=-32600,
                message=f"Invalid request: {e!s}",
            ),
        )
        return JSONResponse(
            content=error_response.model_dump(by_alias=True, exclude_none=True),
            status_code=400,
        )
    except SanhedrinError as e:
        logger.error("Application error: %s", e)
        error_response = JSONRPCErrorResponse(
            id=None,
            error=JSONRPCError(
                code=e.code,
                message=e.message,
            ),
        )
        return JSONResponse(
            content=error_response.model_dump(by_alias=True, exclude_none=True),
            status_code=400,
        )
    except Exception as e:
        logger.error("Internal error: %s", e)
        error_response = JSONRPCErrorResponse(
            id=None,
            error=JSONRPCError(
                code=-32603,
                message="Internal error",
            ),
        )
        return JSONResponse(
            content=error_response.model_dump(by_alias=True, exclude_none=True),
            status_code=500,
        )


@app.post("/a2a/stream")
async def handle_jsonrpc_stream(request: Request) -> StreamingResponse:
    """
    JSON-RPC 2.0 endpoint with SSE streaming.

    Supports:
    - message/stream: Send message with streaming response

    Returns Server-Sent Events (SSE) stream.
    """
    handler = _get_handler(request)

    try:
        body = await request.json()

        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")

        rpc_request = JSONRPCRequest(**body)

        async def event_generator() -> AsyncIterator[str]:
            async for event in handler.handle_stream(rpc_request):
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
        raise HTTPException(status_code=400, detail=f"Invalid request: {e!s}") from e
    except Exception as e:
        logger.error("Stream request error: %s", e)
        raise HTTPException(status_code=400, detail="Parse error") from e


@app.get("/health")
async def health_check(request: Request) -> dict[str, Any]:
    """
    Health check endpoint.

    Returns adapter status and basic server info.
    """
    adapter = getattr(request.app.state, "adapter", None)
    task_manager = getattr(request.app.state, "task_manager", None)

    if adapter is None:
        return {
            "status": "initializing",
            "adapter": None,
        }

    is_healthy = await adapter.health_check()

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "adapter": {
            "name": adapter.name,
            "display_name": adapter.display_name,
            "initialized": adapter.is_initialized,
        },
        "tasks": len(task_manager) if task_manager else 0,
    }


@app.get("/metrics")
async def get_metrics(request: Request) -> PlainTextResponse:
    """
    Prometheus-style metrics endpoint.

    Returns metrics in text format for scraping.
    """
    # Update active tasks gauge
    task_manager = getattr(request.app.state, "task_manager", None)
    prom.tasks_active.set(len(task_manager) if task_manager else 0)

    output, content_type = prom.get_metrics_output()
    return PlainTextResponse(output, media_type=content_type)


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
    import os

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
    import os

    import uvicorn

    os.environ["SANHEDRIN_ADAPTER"] = adapter
    os.environ["SANHEDRIN_HOST"] = host
    os.environ["SANHEDRIN_PORT"] = str(port)

    logger.info("Starting server on %s:%d with adapter %s", host, port, adapter)

    uvicorn.run(
        "sanhedrin.server.app:app",
        host=host,
        port=port,
        reload=reload,
        access_log=True,
    )
