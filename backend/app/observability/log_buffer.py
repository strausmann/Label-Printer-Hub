"""In-memory ring buffer of recent WARNING+ log records for the System page."""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

LOG_BUFFER_CAPACITY = 500


class LogBufferHandler(logging.Handler):
    """Keeps the last ``capacity`` records of level >= WARNING.

    Only the formatted message is kept (no ``exc_info``, no ``args``), so nothing
    is stored beyond what the log record already carries.
    """

    def __init__(self, capacity: int = LOG_BUFFER_CAPACITY) -> None:
        super().__init__(level=logging.WARNING)
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.fromtimestamp(record.created, UTC),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        except Exception:  # never let logging break the caller
            self.handleError(record)
            return
        with self._lock:
            self._records.append(entry)

    def snapshot(self, limit: int) -> list[dict[str, Any]]:
        """Newest ``limit`` entries, oldest first."""
        with self._lock:
            items = list(self._records)
        return items[-limit:] if limit > 0 else []

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


LOG_BUFFER = LogBufferHandler()


def install_log_buffer() -> None:
    """Attach the shared handler to the root logger (idempotent)."""
    root = logging.getLogger()
    if LOG_BUFFER not in root.handlers:
        root.addHandler(LOG_BUFFER)
