# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Application log records reach the container output (stderr), not only the in-app buffer (#324).

Without a stderr handler on the root logger, ``docker logs`` never shows the legacy-variable
deprecation line even though the hub's own log view does.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from app.observability import log_buffer


@pytest.fixture
def clean_root() -> Iterator[None]:
    """Start without our console handler, and put the root logger back afterwards."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    for handler in list(root.handlers):
        if handler.get_name() == "labelyard-console":
            root.removeHandler(handler)
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def test_warning_from_app_logger_is_written_to_stderr(
    clean_root: None, capsys: pytest.CaptureFixture[str]
) -> None:
    log_buffer.install_log_buffer()
    logging.getLogger("app.main").warning("legacy names in use: SOME_VARIABLE")
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    assert "WARNING" in lines[0]
    assert "app.main" in lines[0]
    assert "legacy names in use: SOME_VARIABLE" in lines[0]


def test_info_record_is_not_written_to_stderr(
    clean_root: None, capsys: pytest.CaptureFixture[str]
) -> None:
    log_buffer.install_log_buffer()
    logging.getLogger("app.main").info("routine message")
    assert capsys.readouterr().err == ""


def test_installing_twice_writes_the_line_once(
    clean_root: None, capsys: pytest.CaptureFixture[str]
) -> None:
    log_buffer.install_log_buffer()
    log_buffer.install_log_buffer()
    logging.getLogger("app.main").warning("once only")
    assert capsys.readouterr().err.count("once only") == 1


def test_uvicorn_loggers_do_not_double_up(clean_root: None) -> None:
    """uvicorn's own loggers keep their handler and do not propagate to root."""
    from uvicorn.config import LOGGING_CONFIG

    log_buffer.install_log_buffer()
    for name in ("uvicorn", "uvicorn.access"):
        assert LOGGING_CONFIG["loggers"][name]["propagate"] is False
    assert "propagate" not in LOGGING_CONFIG["loggers"]["uvicorn.error"]  # reaches "uvicorn" only
