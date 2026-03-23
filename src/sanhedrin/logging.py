"""
Structured logging configuration for Sanhedrin.

Uses structlog for JSON output in production and colored console in development.
Falls back gracefully to standard logging if structlog is not installed.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(
    log_level: str = "INFO",
    json_output: bool = False,
) -> None:
    """
    Configure structured logging.

    Args:
        log_level: Log level string (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON logs (for production)
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    try:
        import structlog

        shared_processors: list[structlog.types.Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        if json_output:
            renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
        else:
            renderer = structlog.dev.ConsoleRenderer()

        structlog.configure(
            processors=[
                *shared_processors,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)

        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(level)

    except ImportError:
        # structlog not installed — fall back to standard logging
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            force=True,
        )
