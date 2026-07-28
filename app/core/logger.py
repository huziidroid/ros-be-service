"""
Logging configuration — structured JSON output.

extra={...} fields on any log call are serialised into the JSON object
alongside timestamp, level, logger, and message.

Usage:
  logger = logging.getLogger(__name__)
  logger.info("order_created", extra={"order_id": "123", "tenant_id": "abc"})
"""

import json
import logging
from logging.config import dictConfig

from app.core.settings import Settings


# LogRecord internal fields — never echoed as extras.
_INTERNAL_FIELDS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",  # set by Formatter.format() before we read __dict__
    }
)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record, including all extra= fields."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        log_data: dict[str, object] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # Merge any caller-supplied extra= fields
        for key, value in record.__dict__.items():
            if key not in _INTERNAL_FIELDS:
                log_data[key] = value

        if record.exc_info:
            log_data["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def configure_logging(settings: Settings) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": JsonFormatter,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                },
            },
            "root": {
                "level": settings.log_level.upper(),
                "handlers": ["console"],
            },
        }
    )
