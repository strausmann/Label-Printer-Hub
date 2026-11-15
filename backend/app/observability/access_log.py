# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Access log in nginx combined format (#366).

One line per HTTP request, on stdout, in the format nginx calls ``combined``::

    $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent
    "$http_referer" "$http_user_agent"

so a log tool that reads nginx logs (CrowdSec's ``crowdsecurity/nginx-logs`` parser, for
example) reads the hub's container log without a parser of its own. The line replaces
uvicorn's access line; it has its own logger (:data:`ACCESS_LOGGER_NAME`) that does not
propagate, so it never reaches the application log, the log buffer or stderr.

What the line holds:

- ``$remote_addr`` is ``scope["client"]``: the address uvicorn's proxy-header middleware
  leaves there after ``FORWARDED_ALLOW_IPS``, the same value ``request.client.host`` (and so
  the rate limiter) reads.
- No secret. A URL ``token`` holding a hub API key shows the key's public prefix (the part
  stored as ``ApiKey.key_prefix`` and shown in the key list) followed by ``***``; any other
  ``token`` value, and the value of every parameter whose name looks like a key, token,
  secret or password, becomes ``***``. A value in the shape of a hub key anywhere else in the
  request line, the referer or the user agent becomes ``lh_pat_***``. No header value is
  written except the referer and the user agent.
- ``$remote_user`` is the public prefix of a key sent in the ``X-Label-Hub-Key`` header, else
  ``-``. It comes from the string alone: no lookup, so a guessed key is shown the same way.
- ``"``, ``\\`` and every byte below 0x20 or above 0x7e are written as ``\\xHH``, as nginx
  does, so a client cannot end a field or start a second line.
- ``$status`` is the status the hub answered; ``$body_bytes_sent`` the body bytes it sent.
  The middleware is pure ASGI: it passes every message on at once, so a live event stream
  is never buffered; its line is written when the response ends. Without an answer the
  status is 500 after an error and 499 (nginx's "client closed") after a hang-up or cancel.
- Probes (``/healthz``, ``/readiness``) are left out only when they answer 2xx or 503.
  ``/readiness`` takes a read key, so a refused key there (401, 403, 429) is always logged.
- Requests that uvicorn itself rejects before the app sees them (a malformed request line,
  oversized headers) get no line.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, TextIO
from urllib.parse import unquote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.key_generator import KEY_PREFIX_LENGTH, KEY_SCHEME, key_prefix
from app.observability.redact_query import hide_key_shapes

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.config import Settings

ACCESS_LOGGER_NAME = "labelyard.access"
PROBE_PATHS = frozenset({"/healthz", "/readiness"})
KEY_HEADER = b"x-label-hub-key"
TOKEN_PARAM = "token"
MASK = "***"
CLIENT_CLOSED = 499  # nginx's status for a client that closed the connection before the answer

_HANDLER_NAME = "labelyard-access-stdout"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Fail closed: a parameter is masked whatever its value when its name, lowercased and with
# every separator removed, contains one of these stems.
_SENSITIVE_STEMS = (
    "auth",
    "bearer",
    "cookie",
    "cred",
    "jwt",
    "key",
    "otp",
    "pass",
    "pwd",
    "secret",
    "session",
    "sig",
    "token",
)
# The only exemptions: query parameters of the hub's own API whose name contains a stem but
# never carries a secret. ``new_key`` is the new sheet type key of an import
# (``POST /api/v1/sheet-types/import``, pattern-checked identifier).
_HARMLESS_NAMES = frozenset({"newkey"})
_NON_ALNUM = re.compile(r"[^a-z0-9]")
_KEY_CHARS = re.compile(r"[A-Za-z0-9_-]+")
_NGINX_VERSIONS = {"2": "2.0", "3": "3.0"}  # ASGI writes "2", nginx "HTTP/2.0"
_QUERY_SPLIT = re.compile(r"([&;])")


def format_time_local(moment: datetime) -> str:
    """nginx ``$time_local``: ``15/Nov/2026:17:40:00 +0000`` (English month, any locale)."""
    return (
        f"{moment.day:02d}/{_MONTHS[moment.month - 1]}/{moment.year:04d}:"
        f"{moment:%H:%M:%S} {moment:%z}"
    )


def _now() -> datetime:
    return datetime.fromtimestamp(time.time()).astimezone()


def visible_key(value: str) -> str | None:
    """The public prefix of ``value`` if it has the format of a hub key, else ``None``.

    The format check is only on the string: the scheme, the key's character set and more
    characters than the prefix (a value that is all prefix shows nothing of itself).
    """
    if (
        value.startswith(KEY_SCHEME)
        and len(value) > KEY_PREFIX_LENGTH
        and _KEY_CHARS.fullmatch(value)
    ):
        return key_prefix(value)
    return None


def _escape(text: str) -> str:
    """nginx log escaping: ``"``, ``\\`` and non-printable bytes as ``\\xHH`` (upper hex)."""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in '"\\' or code < 0x20 or code > 0x7E:
            if code > 0xFF:  # not from latin-1 bytes; write its UTF-8 bytes
                out.extend(f"\\x{b:02X}" for b in ch.encode("utf-8"))
            else:
                out.append(f"\\x{code:02X}")
        else:
            out.append(ch)
    return "".join(out)


def _is_sensitive_name(name: str) -> bool:
    flat = _NON_ALNUM.sub("", name.lower())
    return flat not in _HARMLESS_NAMES and any(stem in flat for stem in _SENSITIVE_STEMS)


def _mask_param(part: str) -> str:
    name, sep, value = part.partition("=")
    if not sep:
        return hide_key_shapes(part)
    if name == TOKEN_PARAM:
        prefix = visible_key(unquote(value))
        return f"{name}={prefix}{MASK}" if prefix else f"{name}={MASK}"
    if _is_sensitive_name(unquote(unquote(name))):
        return f"{name}={MASK}"
    return hide_key_shapes(part)


def mask_query(query: str) -> str:
    """Mask the secret parameters of a query string (``&`` and ``;`` separated)."""
    parts = _QUERY_SPLIT.split(query)
    return "".join(p if p in ("&", ";") else _mask_param(p) for p in parts)


def _mask_url(url: str) -> str:
    base, sep, query = url.partition("?")
    return hide_key_shapes(base) + (sep + mask_query(query) if sep else "")


def _field(value: str | None) -> str:
    return _escape(value) if value else "-"


class AccessLogMiddleware:
    """Pure ASGI middleware writing one nginx combined line per HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        include_probes: bool = False,
        write: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.app = app
        self._include_probes = include_probes
        self._write = write or logging.getLogger(ACCESS_LOGGER_NAME).info
        self._clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Decided when the response ends: /readiness takes a key, so a refusal there is logged.
        probe = not self._include_probes and scope.get("path") in PROBE_PATHS

        status: int | None = None
        sent = 0

        async def send_counted(message: Message) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status = int(message["status"])
            elif message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
            await send(message)

        failed = False
        try:
            await self.app(scope, receive, send_counted)
        except asyncio.CancelledError:
            raise
        except BaseException:
            failed = True
            raise
        finally:
            # Also on an error or a dropped connection: the request happened. Without an answer,
            # an error is a 500 (what the server answers) and a hang-up or cancel is nginx's 499.
            final = status if status is not None else (500 if failed else CLIENT_CLOSED)
            if not (probe and (200 <= final < 300 or final == 503)):
                self._log(scope, final, sent)

    def _log(self, scope: Scope, status: int, sent: int) -> None:
        try:
            line = self._line(scope, status, sent)
        except Exception:  # never let the access log break a response
            logging.getLogger(__name__).exception("Could not build the access log line")
            return
        self._write(line)

    def _line(self, scope: Scope, status: int, sent: int) -> str:
        client = scope.get("client")
        addr = str(client[0]) if client else "-"
        referer = agent = None
        user = "-"
        for name, value in scope.get("headers", []):
            lname = name.lower()
            if lname == b"referer":
                referer = _mask_url(value.decode("latin-1"))
            elif lname == b"user-agent":
                agent = hide_key_shapes(value.decode("latin-1"))
            elif lname == KEY_HEADER:
                user = visible_key(value.decode("latin-1")) or "-"
        raw_path = scope.get("raw_path") or scope.get("path", "").encode("utf-8")
        target = hide_key_shapes(raw_path.decode("latin-1"))
        query = scope.get("query_string", b"").decode("latin-1")
        if query:
            target += "?" + mask_query(query)
        version = str(scope.get("http_version", "1.1"))
        version = _NGINX_VERSIONS.get(version, version)
        request = f"{scope.get('method', '-')} {target} HTTP/{version}"
        return (
            f"{_escape(addr)} - {user} [{format_time_local(self._clock())}] "
            f'"{_escape(request)}" {status} {sent} "{_field(referer)}" "{_field(agent)}"'
        )


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever ``sys.stdout`` is at the time of the record."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self) -> TextIO:
        return sys.stdout

    @stream.setter
    def stream(self, _value: TextIO) -> None:
        return None


def _configure_logger() -> None:
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(h.get_name() == _HANDLER_NAME for h in logger.handlers):
        handler = _StdoutHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def install_access_log(app: FastAPI, settings: Settings) -> None:
    """Add the access log as the outermost hub middleware and silence uvicorn's access lines.

    Call it after every other ``add_middleware``. With ``access_log`` off there is no access
    log at all: uvicorn's lines stay off too.
    """
    logging.getLogger("uvicorn.access").disabled = True
    if not settings.access_log:
        return
    _configure_logger()
    app.add_middleware(AccessLogMiddleware, include_probes=settings.access_log_probes)
