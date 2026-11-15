# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the access log in nginx combined format (#366).

The line must parse with CrowdSec's ``crowdsecurity/nginx-logs`` parser, must never carry a
key, and must not let a client forge a second line. The tests drive the pure ASGI middleware
directly, partly behind uvicorn's own proxy-header middleware, which is what fills in the
client address the rate limiter reads.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from app.auth.key_generator import generate_api_key, key_prefix
from app.config import Settings
from app.observability.access_log import (
    ACCESS_LOGGER_NAME,
    AccessLogMiddleware,
    format_time_local,
    install_access_log,
    visible_key,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# A made-up value in the key's shape; never a real key.
SECRET = "lh_pat_abcdefghij0123456789"
PREFIX = "lh_pat_abcdefghi"  # its first 16 characters, as stored in ApiKey.key_prefix
FIXED = datetime(2026, 11, 15, 17, 40, 0, tzinfo=UTC)

# The nginx combined format, field by field (the shape crowdsecurity/nginx-logs expects).
COMBINED = re.compile(
    r"^(?P<addr>\S+) - (?P<user>\S+) \[(?P<time>\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2} "
    r'[+-]\d{4})\] "(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\d+) '
    r'"(?P<referer>[^"]*)" "(?P<agent>[^"]*)"$'
)


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/webhook/grocy/label")
    async def grocy(request: Request) -> PlainTextResponse:
        raise HTTPException(status_code=401, detail="invalid_token")

    @app.get("/whoami")
    async def whoami(request: Request) -> PlainTextResponse:
        # What the rate limiter keys on (request.client.host).
        return PlainTextResponse(request.client.host if request.client else "none")

    @app.get("/limited")
    async def limited() -> PlainTextResponse:
        raise HTTPException(status_code=429, detail="slow down")

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/readiness")
    async def readiness() -> PlainTextResponse:
        return PlainTextResponse("ready")

    return app


def _client(
    lines: list[str],
    *,
    include_probes: bool = False,
    peer: str = "192.0.2.10",
    trusted: str | None = None,
) -> httpx.AsyncClient:
    asgi = AccessLogMiddleware(
        _app(), include_probes=include_probes, write=lines.append, clock=lambda: FIXED
    )
    outer = ProxyHeadersMiddleware(asgi, trusted_hosts=trusted) if trusted else asgi
    transport = httpx.ASGITransport(app=outer, client=(peer, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://hub.example.com")


async def test_line_is_nginx_combined() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        r = await client.get("/whoami?a=1", headers={"user-agent": "probe/1.0", "referer": "-x"})
    assert r.status_code == 200
    assert len(lines) == 1
    m = COMBINED.match(lines[0])
    assert m, lines[0]
    assert m["addr"] == "192.0.2.10"
    assert m["user"] == "-"
    assert m["time"] == "15/Nov/2026:17:40:00 +0000"
    assert m["request"] == "GET /whoami?a=1 HTTP/1.1"
    assert m["status"] == "200"
    assert int(m["bytes"]) == len(r.content)
    assert m["referer"] == "-x"
    assert m["agent"] == "probe/1.0"


async def test_missing_referer_and_agent_are_dashes() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        client.headers.pop("user-agent", None)
        await client.get("/whoami")
    m = COMBINED.match(lines[0])
    assert m and m["referer"] == "-" and m["agent"] == "-"


def test_time_local_keeps_the_offset_and_english_month() -> None:
    plus_two = datetime(2026, 3, 1, 8, 5, 9, tzinfo=timezone(timedelta(hours=2)))
    assert format_time_local(plus_two) == "01/Mar/2026:08:05:09 +0200"


async def test_grocy_url_token_shows_only_the_key_prefix() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        r = await client.post(f"/api/v1/webhook/grocy/label?token={SECRET}&x=1", json={})
    assert r.status_code == 401
    assert SECRET not in lines[0]
    assert PREFIX + SECRET[len(PREFIX)] not in lines[0]  # not one character more
    assert f'"POST /api/v1/webhook/grocy/label?token={PREFIX}***&x=1 HTTP/1.1" 401 ' in lines[0]
    assert COMBINED.match(lines[0])["user"] == "-"  # type: ignore[index]


def test_prefix_is_the_stored_key_prefix() -> None:
    plaintext, stored_prefix, _hash = generate_api_key()
    assert key_prefix(SECRET) == PREFIX
    assert visible_key(plaintext) == stored_prefix


async def test_percent_encoded_token_value_shows_the_prefix() -> None:
    lines: list[str] = []
    encoded = SECRET.replace("_", "%5F")
    async with _client(lines) as client:
        await client.post(f"/api/v1/webhook/grocy/label?token={encoded}", json={})
    assert f"token={PREFIX}***" in lines[0]
    assert "0123456789" not in lines[0]


@pytest.mark.parametrize(
    "value",
    [
        "lh_pat_short",  # not longer than the prefix
        "lh_pat_abcdefghi",  # exactly the prefix, no secret part
        "xx_pat_abcdefghij0123456789",  # wrong scheme
        "lh_pat_abcdefghij01234567.x",  # a character a key never has
        "notakey0123456789abcdef",
    ],
)
async def test_value_not_in_key_format_is_fully_masked(value: str) -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.post(f"/api/v1/webhook/grocy/label?token={value}", json={})
    assert "?token=*** " in lines[0]
    assert value[:8] not in lines[0].split('"')[1].split("?", 1)[1]


async def test_header_key_prefix_is_the_remote_user() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.post(
            "/api/v1/webhook/grocy/label", json={}, headers={"X-Label-Hub-Key": SECRET}
        )
    m = COMBINED.match(lines[0])
    assert m, lines[0]
    assert m["user"] == PREFIX
    assert SECRET not in lines[0]
    assert PREFIX + SECRET[len(PREFIX)] not in lines[0]


async def test_header_value_not_in_key_format_gives_a_dash_user() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.post(
            "/api/v1/webhook/grocy/label",
            json={},
            headers={"X-Label-Hub-Key": "header-key-value-0123456789"},
        )
    assert "header-key-value" not in lines[0]
    assert COMBINED.match(lines[0])["user"] == "-"  # type: ignore[index]


@pytest.mark.parametrize(
    "query",
    [
        "TOKEN=abc12345secret",
        "%74oken=abc12345secret",
        "a=1;token=abc12345secret",
        "api_key=abc12345secret",
        "apiKey=abc12345secret",
        "client_secret=abc12345secret",
        "password=abc12345secret",
        "access_token=abc12345secret",
    ],
)
async def test_secret_looking_params_are_masked(query: str) -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.get(f"/whoami?{query}")
    assert "abc12345secret" not in lines[0]
    assert "=***" in lines[0]


async def test_key_shaped_value_is_masked_anywhere() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.get(
            f"/whoami/{SECRET}?q={SECRET}",
            headers={"referer": f"http://hub.example.com/x?k={SECRET}", "user-agent": SECRET},
        )
    assert "abcdefghij" not in lines[0]


async def test_referer_token_is_masked() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.get("/whoami", headers={"referer": "http://a.example.com/?token=abc12345s"})
    assert "abc12345s" not in lines[0]
    assert '"http://a.example.com/?token=***"' in lines[0]


async def test_crlf_and_quotes_cannot_forge_a_line() -> None:
    lines: list[str] = []
    forged = '1.2.3.4 - - [15/Nov/2026:17:40:00 +0000] "GET / HTTP/1.1" 200 1 "-" "-"'
    async with _client(lines) as client:
        await client.get(
            "/whoami",
            headers={
                "user-agent": f'evil" \r\n{forged}'.encode("latin-1").decode("latin-1"),
                "referer": 'x"y\\z\ttab',
            },
        )
    assert len(lines) == 1
    line = lines[0]
    assert "\n" not in line and "\r" not in line
    m = COMBINED.match(line)
    assert m, line
    assert m["agent"].startswith(r"evil\x22 \x0D\x0A1.2.3.4")
    assert m["referer"] == r"x\x22y\x5Cz\x09tab"


async def test_raw_request_target_is_escaped() -> None:
    lines: list[str] = []
    app = AccessLogMiddleware(_app(), write=lines.append, clock=lambda: FIXED)
    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": '/whoami"\n',
        "raw_path": b'/whoami"\n\xff',
        "query_string": b"x=\x01",
        "headers": [],
        "client": ("192.0.2.10", 1),
        "server": ("hub.example.com", 80),
        "scheme": "http",
        "root_path": "",
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        return None

    await app(scope, receive, send)
    m = COMBINED.match(lines[0])
    assert m, lines[0]
    assert m["request"] == r"GET /whoami\x22\x0A\xFF?x=\x01 HTTP/1.1"


async def test_refusals_keep_their_status() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.post("/api/v1/webhook/grocy/label", json={})
        await client.get("/limited")
        await client.get("/missing")
    statuses = [COMBINED.match(line)["status"] for line in lines]  # type: ignore[index]
    assert statuses == ["401", "429", "404"]


async def test_forwarded_address_from_trusted_proxy() -> None:
    lines: list[str] = []
    async with _client(lines, peer="192.0.2.10", trusted="192.0.2.10") as client:
        r = await client.get("/whoami", headers={"x-forwarded-for": "198.51.100.7"})
    assert r.text == "198.51.100.7"  # what the rate limiter keys on
    assert lines[0].startswith("198.51.100.7 - - [")


async def test_forwarded_header_ignored_from_untrusted_peer() -> None:
    lines: list[str] = []
    async with _client(lines, peer="192.0.2.99", trusted="192.0.2.10") as client:
        r = await client.get("/whoami", headers={"x-forwarded-for": "198.51.100.7"})
    assert r.text == "192.0.2.99"
    assert lines[0].startswith("192.0.2.99 - - [")


async def test_probes_are_left_out_by_default() -> None:
    lines: list[str] = []
    async with _client(lines) as client:
        await client.get("/healthz")
        await client.get("/readiness")
        await client.get("/whoami")
    assert len(lines) == 1 and '"GET /whoami HTTP/1.1"' in lines[0]


async def test_probes_logged_when_included() -> None:
    lines: list[str] = []
    async with _client(lines, include_probes=True) as client:
        await client.get("/healthz")
        await client.get("/readiness")
    assert len(lines) == 2


async def test_streaming_response_is_not_buffered() -> None:
    """Each chunk reaches the server at once; the line is written when the stream ends."""
    lines: list[str] = []
    release = asyncio.Event()

    async def stream(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
        await release.wait()
        await send({"type": "http.response.body", "body": b"data: 2\n\n", "more_body": False})

    app = AccessLogMiddleware(stream, write=lines.append, clock=lambda: FIXED)
    sent: list[Message] = []
    first_chunk = asyncio.Event()

    async def send(message: Message) -> None:
        sent.append(message)
        if message["type"] == "http.response.body":
            first_chunk.set()

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/v1/events",
        "raw_path": b"/api/v1/events",
        "query_string": b"",
        "headers": [],
        "client": ("192.0.2.10", 1),
    }
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(first_chunk.wait(), 1)
    assert sent[-1]["body"] == b"data: 1\n\n"
    assert lines == []  # no line before the stream ends
    release.set()
    await asyncio.wait_for(task, 1)
    assert '"GET /api/v1/events HTTP/1.1" 200 18 ' in lines[0]


async def test_non_http_scopes_pass_through() -> None:
    lines: list[str] = []
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    app = AccessLogMiddleware(inner, write=lines.append)

    async def receive() -> Message:
        return {}

    async def send(message: Message) -> None:
        return None

    await app({"type": "websocket", "path": "/ws"}, receive, send)
    await app({"type": "lifespan"}, receive, send)
    assert seen == ["websocket", "lifespan"] and lines == []


async def test_unhandled_error_is_logged_as_500() -> None:
    lines: list[str] = []

    async def boom(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    app = AccessLogMiddleware(boom, write=lines.append, clock=lambda: FIXED)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        return None

    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/x",
        "query_string": b"",
        "headers": [],
        "client": None,
    }
    with pytest.raises(RuntimeError):
        await app(scope, receive, send)
    assert lines[0].startswith('- - - [15/Nov/2026:17:40:00 +0000] "GET /x HTTP/1.1" 500 0 ')


# --- wiring into the app and the logger ---------------------------------------------------


@pytest.fixture
def restore_loggers() -> Iterator[None]:
    names = (ACCESS_LOGGER_NAME, "uvicorn.access")
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).disabled) for n in names}
    yield
    for n, (handlers, disabled) in saved.items():
        logger = logging.getLogger(n)
        logger.handlers[:] = handlers
        logger.disabled = disabled


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def _has_access_log(app: FastAPI) -> bool:
    return any(m.cls is AccessLogMiddleware for m in app.user_middleware)


def test_enabled_by_default_and_probes_excluded() -> None:
    s = _settings()
    assert s.access_log is True
    assert s.access_log_probes is False


@pytest.mark.usefixtures("restore_loggers")
def test_install_adds_middleware_and_silences_uvicorn_access() -> None:
    app = FastAPI()
    install_access_log(app, _settings())
    assert _has_access_log(app)
    assert logging.getLogger("uvicorn.access").disabled


@pytest.mark.usefixtures("restore_loggers")
def test_disabled_by_setting() -> None:
    app = FastAPI()
    install_access_log(app, _settings(access_log=False))
    assert not _has_access_log(app)
    # Off means off: uvicorn's own access lines do not come back either.
    assert logging.getLogger("uvicorn.access").disabled


@pytest.mark.usefixtures("restore_loggers")
def test_logger_writes_bare_lines_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    install_access_log(FastAPI(), _settings())
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    assert logger.propagate is False  # not into the app log, the log buffer or stderr
    logger.info('192.0.2.1 - - [x] "GET / HTTP/1.1" 200 0 "-" "-"')
    out = capsys.readouterr()
    assert out.out == '192.0.2.1 - - [x] "GET / HTTP/1.1" 200 0 "-" "-"\n'
    assert out.err == ""


@pytest.mark.usefixtures("restore_loggers")
def test_install_is_idempotent_for_the_handler() -> None:
    install_access_log(FastAPI(), _settings())
    install_access_log(FastAPI(), _settings())
    handlers = logging.getLogger(ACCESS_LOGGER_NAME).handlers
    assert sum(type(h).__name__ == "_StdoutHandler" for h in handlers) == 1


def test_create_app_installs_the_access_log() -> None:
    from app.main import app

    inner = app._app  # the FastAPI app inside the lifespan wrapper
    assert _has_access_log(inner)
    # Outermost of the hub's own middlewares, so it sees the final status of every response.
    assert inner.user_middleware[0].cls is AccessLogMiddleware
