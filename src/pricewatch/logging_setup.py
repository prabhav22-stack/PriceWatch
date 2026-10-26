"""Structured logging setup with automated credential and token scrubbing."""

import logging
import sys
import re
from typing import Any, MutableMapping
import structlog


_SENSITIVE_PATTERNS = [
    re.compile(r"bot\d+:[A-Za-z0-9_-]+"),      # Telegram bot token in URLs
    re.compile(r"sbp_[a-f0-9]{40}"),           # Supabase access token
    re.compile(r"ghp_[A-Za-z0-9]{36}"),        # GitHub token
    re.compile(r"rnd_[A-Za-z0-9]{28}"),        # Render API key
    re.compile(r"://[^:]+:([^@]+)@"),           # Passwords in URLs (postgres://user:pass@host)
]


def scrub_secrets(
    logger: logging.Logger, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Scrub known secret formats from event messages and string parameters."""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            for pattern in _SENSITIVE_PATTERNS:
                value = pattern.sub("[REDACTED_SECRET]", value)
            event_dict[key] = value
    return event_dict


def setup_logging(log_level: str = "INFO", json_format: bool = False) -> None:
    """Configure structlog and standard logging."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        scrub_secrets,
    ]

    if json_format:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str = "pricewatch") -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger."""
    return structlog.get_logger(name)
