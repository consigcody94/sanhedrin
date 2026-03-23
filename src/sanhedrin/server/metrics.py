"""
Prometheus metrics for Sanhedrin.

Uses prometheus_client for thread-safe counters, gauges, and histograms.
Falls back to a simple dict if prometheus_client is not installed.
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    requests_total = Counter(
        "sanhedrin_requests_total",
        "Total number of requests",
        ["method", "status_class"],
    )
    request_duration = Histogram(
        "sanhedrin_request_duration_seconds",
        "Request duration in seconds",
        ["method"],
    )
    tasks_created = Counter("sanhedrin_tasks_created_total", "Total tasks created")
    tasks_completed = Counter("sanhedrin_tasks_completed_total", "Completed tasks")
    tasks_failed = Counter("sanhedrin_tasks_failed_total", "Failed tasks")
    tasks_active = Gauge("sanhedrin_tasks_active", "Currently active tasks")
    tasks_cleaned = Counter("sanhedrin_tasks_cleaned_total", "Tasks cleaned up")

    PROMETHEUS_AVAILABLE = True

    def get_metrics_output() -> tuple[bytes, str]:
        """Generate Prometheus metrics output."""
        return generate_latest(), CONTENT_TYPE_LATEST

except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Fallback no-op metrics when prometheus_client is not installed
    class _NoOpMetric:
        def inc(self, amount: float = 1) -> None: ...
        def dec(self, amount: float = 1) -> None: ...
        def set(self, value: float) -> None: ...
        def observe(self, amount: float) -> None: ...
        def labels(self, *_args: Any, **_kwargs: Any) -> _NoOpMetric:
            return self

    _noop = _NoOpMetric()
    requests_total = _noop  # type: ignore[assignment]
    request_duration = _noop  # type: ignore[assignment]
    tasks_created = _noop  # type: ignore[assignment]
    tasks_completed = _noop  # type: ignore[assignment]
    tasks_failed = _noop  # type: ignore[assignment]
    tasks_active = _noop  # type: ignore[assignment]
    tasks_cleaned = _noop  # type: ignore[assignment]

    def get_metrics_output() -> tuple[bytes, str]:
        return b"# prometheus_client not installed\n", "text/plain"
