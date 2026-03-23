"""
Authentication middleware for Sanhedrin.

Provides API key and JWT authentication with rate limiting support.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Security headers
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class APIKeyConfig:
    """Configuration for API key authentication."""

    enabled: bool = False
    keys: set[str] = field(default_factory=set)
    key_hash_algorithm: str = "sha256"
    header_name: str = "X-API-Key"
    query_param_name: str = "api_key"
    allow_query_param: bool = False


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    enabled: bool = True
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10


@dataclass
class SecurityConfig:
    """Complete security configuration."""

    api_key: APIKeyConfig = field(default_factory=APIKeyConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    # Paths that don't require authentication
    public_paths: set[str] = field(
        default_factory=lambda: {
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/.well-known/agent.json",
        }
    )


class RateLimiter:
    """Token bucket rate limiter with sliding window."""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self._buckets: dict[str, dict[str, Any]] = {}
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()

    def _get_bucket_key(self, identifier: str) -> str:
        """Generate bucket key from identifier."""
        return hashlib.sha256(identifier.encode()).hexdigest()[:16]

    def _cleanup_old_buckets(self) -> None:
        """Remove expired buckets."""
        now = time.time()
        expired = [
            k for k, v in self._buckets.items() if now - v.get("last_access", 0) > 3600
        ]
        for key in expired:
            del self._buckets[key]

    def is_allowed(self, identifier: str) -> tuple[bool, dict[str, int]]:
        """
        Check if request is allowed under rate limits.

        Args:
            identifier: Client identifier (IP, API key, etc.)

        Returns:
            Tuple of (allowed, limit_info)
        """
        now = time.time()
        key = self._get_bucket_key(identifier)

        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": self.config.burst_size,
                "last_refill": now,
                "minute_count": 0,
                "minute_start": now,
                "hour_count": 0,
                "hour_start": now,
                "last_access": now,
            }

        bucket = self._buckets[key]
        bucket["last_access"] = now

        # Refill tokens (1 per second up to burst_size)
        elapsed = now - bucket["last_refill"]
        new_tokens = min(self.config.burst_size, bucket["tokens"] + elapsed)
        bucket["tokens"] = new_tokens
        bucket["last_refill"] = now

        # Reset minute counter
        if now - bucket["minute_start"] >= 60:
            bucket["minute_count"] = 0
            bucket["minute_start"] = now

        # Reset hour counter
        if now - bucket["hour_start"] >= 3600:
            bucket["hour_count"] = 0
            bucket["hour_start"] = now

        # Check limits
        limit_info = {
            "remaining_tokens": int(bucket["tokens"]),
            "minute_remaining": self.config.requests_per_minute
            - bucket["minute_count"],
            "hour_remaining": self.config.requests_per_hour - bucket["hour_count"],
        }

        if bucket["tokens"] < 1:
            return False, limit_info

        if bucket["minute_count"] >= self.config.requests_per_minute:
            return False, limit_info

        if bucket["hour_count"] >= self.config.requests_per_hour:
            return False, limit_info

        # Consume
        bucket["tokens"] -= 1
        bucket["minute_count"] += 1
        bucket["hour_count"] += 1

        limit_info["remaining_tokens"] = int(bucket["tokens"])
        limit_info["minute_remaining"] = (
            self.config.requests_per_minute - bucket["minute_count"]
        )
        limit_info["hour_remaining"] = (
            self.config.requests_per_hour - bucket["hour_count"]
        )

        # Periodic time-based cleanup
        now_check = time.time()
        if now_check - self._last_cleanup > self._cleanup_interval:
            self._cleanup_old_buckets()
            self._last_cleanup = now_check

        return True, limit_info


class APIKeyValidator:
    """Validates API keys with timing-safe comparison."""

    def __init__(self, config: APIKeyConfig) -> None:
        self.config = config
        self._hashed_keys: set[str] = set()
        for key in config.keys:
            self._hashed_keys.add(self._hash_key(key))

    def _hash_key(self, key: str) -> str:
        """Hash an API key."""
        return hashlib.sha256(key.encode()).hexdigest()

    def add_key(self, key: str) -> None:
        """Add a new API key."""
        self.config.keys.add(key)
        self._hashed_keys.add(self._hash_key(key))

    def remove_key(self, key: str) -> None:
        """Remove an API key."""
        self.config.keys.discard(key)
        self._hashed_keys.discard(self._hash_key(key))

    def validate(self, key: str | None) -> bool:
        """
        Validate an API key using timing-safe comparison.

        Args:
            key: The API key to validate

        Returns:
            True if valid
        """
        if not key:
            return False

        key_hash = self._hash_key(key)

        # Timing-safe comparison against all valid hashes
        for valid_hash in self._hashed_keys:
            if hmac.compare_digest(key_hash, valid_hash):
                return True

        return False


def generate_api_key(prefix: str = "sk") -> str:
    """
    Generate a secure random API key.

    Args:
        prefix: Key prefix (e.g., "sk" for secret key)

    Returns:
        API key in format: prefix_randomstring
    """
    random_part = secrets.token_urlsafe(32)
    return f"{prefix}_{random_part}"


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Security middleware with authentication and rate limiting.

    Handles:
    - API key validation
    - Rate limiting per client
    - Security headers
    - Request logging hooks
    """

    def __init__(
        self,
        app: Any,
        config: SecurityConfig | None = None,
    ) -> None:
        super().__init__(app)
        self.config = config or SecurityConfig()
        self.api_key_validator = APIKeyValidator(self.config.api_key)
        self.rate_limiter = RateLimiter(self.config.rate_limit)

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting."""
        # Prefer API key if available
        api_key = self._extract_api_key(request)
        if api_key:
            return f"key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"

        # Fall back to IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"

        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    def _extract_api_key(self, request: Request) -> str | None:
        """Extract API key from request."""
        # Check header
        api_key = request.headers.get(self.config.api_key.header_name)
        if api_key:
            return api_key

        # Check Authorization header (Bearer token style)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]

        # Check query param if allowed (deprecated — keys visible in logs/history)
        if self.config.api_key.allow_query_param:
            api_key = request.query_params.get(self.config.api_key.query_param_name)
            if api_key:
                logger.warning(
                    "API key passed via query parameter — this is deprecated and insecure. "
                    "Use the %s header or Authorization: Bearer instead.",
                    self.config.api_key.header_name,
                )
                return api_key

        return None

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        # Exact match
        if path in self.config.public_paths:
            return True

        # Check for path prefixes (for docs, static files, etc.)
        for public_path in self.config.public_paths:
            if public_path.endswith("*") and path.startswith(public_path[:-1]):
                return True

        return False

    def _add_security_headers(self, response: Response) -> None:
        """Add security headers to response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request through security middleware."""
        path = request.url.path

        # Skip auth for public paths
        is_public = self._is_public_path(path)

        # Authenticate if required
        if self.config.api_key.enabled and not is_public:
            api_key = self._extract_api_key(request)
            if not self.api_key_validator.validate(api_key):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing API key",
                    headers={"WWW-Authenticate": "ApiKey"},
                )

        # Rate limiting
        if self.config.rate_limit.enabled:
            client_id = self._get_client_id(request)
            allowed, limit_info = self.rate_limiter.is_allowed(client_id)

            if not allowed:
                response = Response(
                    content='{"error": "Rate limit exceeded"}',
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    media_type="application/json",
                )
                response.headers["Retry-After"] = "60"
                response.headers["X-RateLimit-Remaining"] = str(
                    limit_info["minute_remaining"]
                )
                return response

        # Process request
        response = await call_next(request)

        # Add security headers
        self._add_security_headers(response)

        return response


def create_security_config_from_env() -> SecurityConfig:
    """Create security config from environment variables."""
    import os

    api_keys_str = os.environ.get("SANHEDRIN_API_KEYS", "")
    api_keys = {k.strip() for k in api_keys_str.split(",") if k.strip()}

    return SecurityConfig(
        api_key=APIKeyConfig(
            enabled=os.environ.get("SANHEDRIN_AUTH_ENABLED", "false").lower() == "true",
            keys=api_keys,
        ),
        rate_limit=RateLimitConfig(
            enabled=os.environ.get("SANHEDRIN_RATE_LIMIT_ENABLED", "true").lower()
            == "true",
            requests_per_minute=int(
                os.environ.get("SANHEDRIN_RATE_LIMIT_PER_MINUTE", "60")
            ),
            requests_per_hour=int(
                os.environ.get("SANHEDRIN_RATE_LIMIT_PER_HOUR", "1000")
            ),
        ),
    )
