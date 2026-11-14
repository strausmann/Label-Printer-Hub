"""Tests for the log filter that hides the URL ``token`` (#281, R-281-2).

Grocy calls the label webhook with the key in the query string; uvicorn writes that URL
to its access log. The filter replaces the value of every literal ``token=`` parameter
with ``***`` before any handler formats the record.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
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


# Built at runtime: a literal in the key format would trip the repository's secret scanner.
LIVE_KEY = "lh_pat_" + "Q" * 43


def _access_record(target: str) -> logging.LogRecord:
    """A record exactly as uvicorn.access emits it."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.1:5000", "POST", target, "1.1", 401),
        None,
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (f"/hook?TOKEN={LIVE_KEY}", "/hook?TOKEN=***"),
        (f"/hook?Token={LIVE_KEY}&x=1", "/hook?Token=***&x=1"),
        (f"/hook?a=1;token={LIVE_KEY}", "/hook?a=1;token=***"),
        (f"/hook?token={LIVE_KEY};b=2", "/hook?token=***;b=2"),
        (f"/hook?to%6Ben={LIVE_KEY}", "/hook?to%6Ben=***"),
        (f"/hook?%74oken={LIVE_KEY}", "/hook?%74oken=***"),
        (f"/hook?%74O%6bE%6E={LIVE_KEY}", "/hook?%74O%6bE%6E=***"),
    ],
    ids=["upper", "title", "semicolon-before", "semicolon-after", "enc-k", "enc-t", "enc-mixed"],
)
def test_token_look_alikes_are_redacted(target: str, expected: str) -> None:
    record = _access_record(target)
    QueryTokenRedactor().filter(record)
    message = record.getMessage()
    assert f'"POST {expected} HTTP/1.1" 401' in message
    assert "Q" * 20 not in message


@pytest.mark.parametrize(
    "target",
    [
        f"/api/v1/things/{LIVE_KEY}",
        f"/hook?key={LIVE_KEY}",
        f"/hook?xtoken={LIVE_KEY}",
    ],
    ids=["in-path", "other-param", "prefixed-name"],
)
def test_key_shaped_value_is_redacted_anywhere(target: str) -> None:
    record = _access_record(target)
    QueryTokenRedactor().filter(record)
    message = record.getMessage()
    assert "lh_pat_***" in message
    assert "Q" * 20 not in message


# A key with "-" and "_" inside its body, so encoded separators can be tested.
DASH_KEY = "lh_pat_" + "R" * 20 + "-" + "R" * 10 + "_" + "R" * 11


def _enc(key: str, upper: bool = False, double: bool = False) -> str:
    """Percent-encode every "_" and "-" of a key, as an over-eager encoder would."""
    pct = "%25" if double else "%"
    under, dash = ("5F", "2D") if upper else ("5f", "2d")
    return key.replace("_", f"{pct}{under}").replace("-", f"{pct}{dash}")


@pytest.mark.parametrize(
    "target",
    [
        f"/hook?k={_enc(DASH_KEY)}",
        f"/hook?k={_enc(DASH_KEY, upper=True)}",
        f"/hook?k={_enc(DASH_KEY, double=True)}",
        f"/hook?k=lh_pat_{'R' * 20}%2D{'R' * 10}_{'R' * 11}",
        f"/hook?%54oken={_enc(DASH_KEY)}",
        f"/hook?%2574oken={_enc(DASH_KEY, double=True)}",
        f"/hook?%54%4F%4B%45%4E={_enc(DASH_KEY, upper=True)}",
        f"/api/v1/things/{_enc(DASH_KEY)}/more",
    ],
    ids=[
        "enc-lower",
        "enc-upper",
        "double-enc",
        "dash-only",
        "name-%54",
        "name-double",
        "name-all-upper-hex",
        "in-path",
    ],
)
def test_percent_encoded_key_is_redacted(target: str) -> None:
    record = _access_record(target)
    QueryTokenRedactor().filter(record)
    message = record.getMessage()
    assert "R" * 10 not in message, message
    assert "***" in message


def test_key_shaped_value_in_plain_message_is_redacted() -> None:
    record = logging.LogRecord(
        "uvicorn.error", logging.ERROR, __file__, 1, f"boom near {LIVE_KEY}.", None, None
    )
    QueryTokenRedactor().filter(record)
    assert record.getMessage() == "boom near lh_pat_***."


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


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_redaction_reaches_parent_handlers(clean_filters: None) -> None:
    """Outcome: a handler on a parent logger (where uvicorn's own config puts its console
    handler) only ever sees the redacted record.

    uvicorn's logging config may have run earlier in the process (it sets ``uvicorn`` to
    not propagate), so the test pins ``propagate`` and the level for its duration instead
    of relying on whatever state an earlier test left behind.
    """
    install_query_token_redaction()
    child = logging.getLogger("uvicorn.error")
    parent = logging.getLogger("uvicorn")
    saved = (child.propagate, child.level, child.disabled, parent.level, parent.disabled)
    handler = _ListHandler()
    parent.addHandler(handler)
    child.propagate, child.disabled, parent.disabled = True, False, False
    child.setLevel(logging.INFO)
    try:
        child.warning("probe %s", f"/api/v1/webhook/grocy/label?token={SECRET}")
    finally:
        parent.removeHandler(handler)
        child.propagate, _, child.disabled, _, parent.disabled = saved
        child.setLevel(saved[1])
        parent.setLevel(saved[3])
    assert handler.messages == ["probe /api/v1/webhook/grocy/label?token=***"]
