"""
Input validation and sanitization utilities.

Provides validation for user inputs, prompts, and configuration values
to prevent security issues and ensure data quality.
"""

from __future__ import annotations

import re
import html
from dataclasses import dataclass
from typing import Any


# Validation limits
MAX_PROMPT_LENGTH = 100_000  # 100KB max prompt
MAX_MESSAGE_PARTS = 50  # Max parts per message
MAX_CONTEXT_MESSAGES = 100  # Max messages in context
MAX_TASK_ID_LENGTH = 128
MAX_CONTEXT_ID_LENGTH = 128
MAX_METADATA_SIZE = 10_000  # 10KB max metadata JSON


@dataclass
class ValidationResult:
    """Result of validation operation."""

    valid: bool
    error: str | None = None
    sanitized_value: Any = None


class ValidationError(Exception):
    """Validation failed."""

    def __init__(self, message: str, field: str | None = None) -> None:
        self.message = message
        self.field = field
        super().__init__(message)


def validate_prompt_length(prompt: str, max_length: int = MAX_PROMPT_LENGTH) -> ValidationResult:
    """
    Validate prompt length.

    Args:
        prompt: The prompt to validate
        max_length: Maximum allowed length

    Returns:
        ValidationResult
    """
    if not isinstance(prompt, str):
        return ValidationResult(
            valid=False,
            error="Prompt must be a string",
        )

    if len(prompt) > max_length:
        return ValidationResult(
            valid=False,
            error=f"Prompt exceeds maximum length of {max_length} characters",
        )

    return ValidationResult(valid=True, sanitized_value=prompt)


def sanitize_prompt(prompt: str) -> str:
    """
    Sanitize a prompt for safe CLI execution.

    Removes or escapes potentially dangerous characters while
    preserving the prompt's meaning.

    Args:
        prompt: The prompt to sanitize

    Returns:
        Sanitized prompt
    """
    if not prompt:
        return ""

    # Remove null bytes (can cause issues in C-based programs)
    sanitized = prompt.replace("\x00", "")

    # Remove other control characters except newlines and tabs
    sanitized = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)

    return sanitized


def validate_task_id(task_id: str) -> ValidationResult:
    """
    Validate task ID format.

    Args:
        task_id: The task ID to validate

    Returns:
        ValidationResult
    """
    if not task_id:
        return ValidationResult(valid=False, error="Task ID is required")

    if len(task_id) > MAX_TASK_ID_LENGTH:
        return ValidationResult(
            valid=False,
            error=f"Task ID exceeds maximum length of {MAX_TASK_ID_LENGTH}",
        )

    # Allow UUIDs, alphanumeric with hyphens/underscores
    if not re.match(r"^[a-zA-Z0-9\-_]+$", task_id):
        return ValidationResult(
            valid=False,
            error="Task ID contains invalid characters",
        )

    return ValidationResult(valid=True, sanitized_value=task_id)


def validate_context_id(context_id: str) -> ValidationResult:
    """
    Validate context ID format.

    Args:
        context_id: The context ID to validate

    Returns:
        ValidationResult
    """
    if not context_id:
        return ValidationResult(valid=False, error="Context ID is required")

    if len(context_id) > MAX_CONTEXT_ID_LENGTH:
        return ValidationResult(
            valid=False,
            error=f"Context ID exceeds maximum length of {MAX_CONTEXT_ID_LENGTH}",
        )

    if not re.match(r"^[a-zA-Z0-9\-_]+$", context_id):
        return ValidationResult(
            valid=False,
            error="Context ID contains invalid characters",
        )

    return ValidationResult(valid=True, sanitized_value=context_id)


def validate_message_parts_count(parts: list[Any]) -> ValidationResult:
    """
    Validate message parts count.

    Args:
        parts: List of message parts

    Returns:
        ValidationResult
    """
    if len(parts) > MAX_MESSAGE_PARTS:
        return ValidationResult(
            valid=False,
            error=f"Message exceeds maximum of {MAX_MESSAGE_PARTS} parts",
        )

    return ValidationResult(valid=True)


def validate_context_length(context: list[Any]) -> ValidationResult:
    """
    Validate context message count.

    Args:
        context: List of context messages

    Returns:
        ValidationResult
    """
    if len(context) > MAX_CONTEXT_MESSAGES:
        return ValidationResult(
            valid=False,
            error=f"Context exceeds maximum of {MAX_CONTEXT_MESSAGES} messages",
        )

    return ValidationResult(valid=True)


def sanitize_html(text: str) -> str:
    """
    Escape HTML characters in text.

    Args:
        text: Text to sanitize

    Returns:
        HTML-escaped text
    """
    return html.escape(text)


def validate_json_size(data: dict[str, Any], max_size: int = MAX_METADATA_SIZE) -> ValidationResult:
    """
    Validate JSON data size.

    Args:
        data: Dictionary to validate
        max_size: Maximum size in bytes

    Returns:
        ValidationResult
    """
    import json

    try:
        size = len(json.dumps(data))
        if size > max_size:
            return ValidationResult(
                valid=False,
                error=f"JSON data exceeds maximum size of {max_size} bytes",
            )
        return ValidationResult(valid=True)
    except (TypeError, ValueError) as e:
        return ValidationResult(valid=False, error=f"Invalid JSON: {e}")


def validate_url(url: str) -> ValidationResult:
    """
    Validate URL format and safety.

    Args:
        url: URL to validate

    Returns:
        ValidationResult
    """
    from urllib.parse import urlparse

    if not url:
        return ValidationResult(valid=False, error="URL is required")

    try:
        parsed = urlparse(url)

        # Must have scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return ValidationResult(valid=False, error="Invalid URL format")

        # Only allow http/https
        if parsed.scheme not in ("http", "https"):
            return ValidationResult(
                valid=False,
                error="Only HTTP and HTTPS URLs are allowed",
            )

        # Block localhost/internal IPs in production
        hostname = parsed.hostname or ""
        blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
        if hostname in blocked_hosts:
            return ValidationResult(
                valid=False,
                error="Internal addresses are not allowed",
            )

        # Block private IP ranges
        if _is_private_ip(hostname):
            return ValidationResult(
                valid=False,
                error="Private IP addresses are not allowed",
            )

        return ValidationResult(valid=True, sanitized_value=url)

    except Exception as e:
        return ValidationResult(valid=False, error=f"Invalid URL: {e}")


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname is a private IP address."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_reserved
    except ValueError:
        # Not an IP address, it's a hostname
        return False


def validate_api_key(key: str) -> ValidationResult:
    """
    Validate API key format.

    Args:
        key: API key to validate

    Returns:
        ValidationResult
    """
    if not key:
        return ValidationResult(valid=False, error="API key is required")

    # Minimum length for security
    if len(key) < 16:
        return ValidationResult(
            valid=False,
            error="API key must be at least 16 characters",
        )

    # Maximum length
    if len(key) > 256:
        return ValidationResult(
            valid=False,
            error="API key exceeds maximum length",
        )

    # Only allow safe characters
    if not re.match(r"^[a-zA-Z0-9\-_]+$", key):
        return ValidationResult(
            valid=False,
            error="API key contains invalid characters",
        )

    return ValidationResult(valid=True, sanitized_value=key)


class InputValidator:
    """
    Centralized input validator.

    Provides methods to validate all types of input data.
    """

    def __init__(
        self,
        max_prompt_length: int = MAX_PROMPT_LENGTH,
        max_context_messages: int = MAX_CONTEXT_MESSAGES,
    ) -> None:
        self.max_prompt_length = max_prompt_length
        self.max_context_messages = max_context_messages

    def validate_prompt(self, prompt: str) -> str:
        """Validate and sanitize a prompt."""
        result = validate_prompt_length(prompt, self.max_prompt_length)
        if not result.valid:
            raise ValidationError(result.error or "Invalid prompt", field="prompt")

        return sanitize_prompt(prompt)

    def validate_task_id(self, task_id: str) -> str:
        """Validate task ID."""
        result = validate_task_id(task_id)
        if not result.valid:
            raise ValidationError(result.error or "Invalid task ID", field="task_id")
        return result.sanitized_value

    def validate_context_id(self, context_id: str) -> str:
        """Validate context ID."""
        result = validate_context_id(context_id)
        if not result.valid:
            raise ValidationError(result.error or "Invalid context ID", field="context_id")
        return result.sanitized_value

    def validate_context(self, context: list[Any]) -> list[Any]:
        """Validate context messages."""
        if len(context) > self.max_context_messages:
            raise ValidationError(
                f"Context exceeds maximum of {self.max_context_messages} messages",
                field="context"
            )
        return context

    def validate_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Validate metadata size."""
        result = validate_json_size(metadata)
        if not result.valid:
            raise ValidationError(result.error or "Invalid metadata", field="metadata")
        return metadata
