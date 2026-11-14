"""Tests for the log filter that hides the URL ``token`` (#281, R-281-2).

Grocy calls the label webhook with the key in the query string; uvicorn writes that URL
to its access log. The filter replaces the value of every literal ``token=`` parameter
with ``***`` before any handler formats the record.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from app.observability.log_buffer import LOG_BUFFER
from app.observability.redact_query import QueryTokenRedactor, install_query_token_redaction

# A made-up value in the key's shape; never a real key.
SECRET = "lh_abcdef0123456789"
TARGET_LOGGERS = ("uvicorn.access", "uvicorn.error")


@pytest.fixture
def clean_filters() -> Iterator[None]:
    saved = {name: list(logging.getLogger(name).filters) for name in TARGET_LOGGERS}
    for name in TARGET_LOGGERS:
        logger = logging.getLogger(name)
        for f in list(logger.filters):
            if isinstance(f, QueryTokenRedactor):
                logger.removeFilter(f)
    yield
    for name, filters in saved.items():
        logger = logging.getLogger(name)
        for f in list(logger.filters):
            logger.removeFilter(f)
        for f in filters:
            logger.addFilter(f)


def _redactors(name: str) -> list[logging.Filter]:
    return [f for f in logging.getLogger(name).filters if isinstance(f, QueryTokenRedactor)]


def test_access_record_token_is_redacted_in_args() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "192.0.2.1:5000",
            "POST",
            f"/api/v1/webhook/grocy/label?token={SECRET}&x=1",
            "1.1",
            202,
        ),
        None,
    )
    assert QueryTokenRedactor().filter(record) is True
    message = record.getMessage()
    assert "token=***&x=1" in message
    assert "lh_abcdef" not in message
    assert "192.0.2.1:5000" in message and " 202" in message


def test_token_in_plain_message_is_redacted() -> None:
    record = logging.LogRecord(
        "uvicorn.error",
        logging.WARNING,
        __file__,
        1,
        f'Invalid request "POST /api/v1/webhook/grocy/label?a=1&token={SECRET} HTTP/1.1"',
        None,
        None,
    )
    QueryTokenRedactor().filter(record)
    message = record.getMessage()
    assert "?a=1&token=*** HTTP/1.1" in message
    assert SECRET not in message


def test_mapping_args_are_redacted() -> None:
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "%(url)s", None, None)
    record.args = {"url": f"/hook?token={SECRET}"}
    QueryTokenRedactor().filter(record)
    assert record.getMessage() == "/hook?token=***"


def test_other_parameters_untouched() -> None:
    url = "/api/v1/jobs?tokenizer=1&page=2&xtoken=3"
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s", (url,), None)
    QueryTokenRedactor().filter(record)
    assert record.getMessage() == url


def test_install_is_idempotent(clean_filters: None) -> None:
    install_query_token_redaction()
    install_query_token_redaction()
    for name in TARGET_LOGGERS:
        assert len(_redactors(name)) == 1, name


def test_create_app_installs_query_token_redaction(clean_filters: None) -> None:
    from app.main import create_app

    create_app()
    for name in TARGET_LOGGERS:
        assert len(_redactors(name)) == 1, name


def test_redaction_reaches_propagated_handlers(clean_filters: None) -> None:
    """Outcome: the System page's log buffer (a root handler) never sees the token."""
    install_query_token_redaction()
    LOG_BUFFER.clear()
    root = logging.getLogger()
    added = LOG_BUFFER not in root.handlers
    if added:
        root.addHandler(LOG_BUFFER)
    try:
        logging.getLogger("uvicorn.error").warning(
            "probe %s", f"/api/v1/webhook/grocy/label?token={SECRET}"
        )
        messages = [entry["message"] for entry in LOG_BUFFER.snapshot(50)]
    finally:
        if added:
            root.removeHandler(LOG_BUFFER)
        LOG_BUFFER.clear()
    assert any("token=***" in m for m in messages), messages
    assert not any(SECRET in m for m in messages)
