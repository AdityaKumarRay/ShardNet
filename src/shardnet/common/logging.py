"""Shared logging setup with JSON output."""

import logging
import sys
from typing import Any, cast

import structlog
from structlog.typing import FilteringBoundLogger


def _resolve_log_level(level: str) -> int:
    resolved = getattr(logging, level.upper(), None)
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: str = "INFO") -> None:
    """Configure standard and structured logging consistently."""

    numeric_level = _resolve_log_level(level)
    logging.basicConfig(level=numeric_level, format="%(message)s", stream=sys.stdout, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(**context: Any) -> FilteringBoundLogger:
    """Create a logger enriched with consistent contextual fields."""

    return cast(FilteringBoundLogger, structlog.get_logger().bind(**context))
