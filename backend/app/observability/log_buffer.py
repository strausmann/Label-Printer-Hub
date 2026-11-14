# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Log sinks for WARNING+ records: the System page ring buffer and the container output.

uvicorn configures only its own loggers (``uvicorn``, ``uvicorn.error``, ``uvicorn.access``; the
first two write to stderr, none propagate to root). Records from ``app.*`` would reach neither
``docker logs`` nor anything else without the console handler below.
"""

from __future__ import annotations

import logging
import sys
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


CONSOLE_HANDLER_NAME = "labelyard-console"
CONSOLE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _console_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(CONSOLE_HANDLER_NAME)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    return handler


def install_log_buffer() -> None:
    """Attach the in-app buffer and a stderr handler to the root logger (idempotent).

    The stderr handler (WARNING and above, one line per record) is what puts application
    warnings into ``docker logs``; the buffer feeds the hub's log view. uvicorn's own loggers
    do not propagate to root, so none of their lines is written twice.
    """
    root = logging.getLogger()
    if LOG_BUFFER not in root.handlers:
        root.addHandler(LOG_BUFFER)
    if not any(h.get_name() == CONSOLE_HANDLER_NAME for h in root.handlers):
        root.addHandler(_console_handler())
