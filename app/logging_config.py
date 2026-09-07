"""Structured JSON logging (§9): every log line is a JSON object shipped to stdout,
captured by the deployment platform's log viewer. No separate log aggregator is used
at this scale (ADR: technical observability stays lightweight).
"""

import json
import logging
import sys
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Allow callers to attach structured context via logger.info(msg, extra={"context": {...}})
        context = getattr(record, "context", None)
        if context:
            payload["context"] = context

        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
