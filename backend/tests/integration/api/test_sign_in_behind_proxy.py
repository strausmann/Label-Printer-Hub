# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The per-client sign-in rate limit behind a reverse proxy (#160).

The bucket is keyed by ``request.client.host``. uvicorn's ``ProxyHeadersMiddleware`` (fed by
``FORWARDED_ALLOW_IPS``) replaces that with the forwarded client only when the TCP peer is a
trusted proxy, and then takes the right-most address that is not itself trusted. The tests put
the same middleware around the real app, as ``tests/unit/observability/test_access_log.py``
does around a small one. All addresses are documentation addresses; the key is fake.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from app.config import get_settings
from app.services.rate_limiter import _sign_in_rate_limiter
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from tests.integration.api.conftest import _client_for

TRUSTED = "127.0.0.1"
DOCKERFILE = Path(__file__).resolve().parents[3] / "Dockerfile"
BAD_KEY = {"key": "lh_pat_not-a-real-key-0123456789"}


def _proxy_flags(dockerfile: str) -> tuple[bool, bool]:
    """(``--proxy-headers`` given, ``--forwarded-allow-ips`` given) in the uvicorn command."""
    return (
        re.search(r"(?<![\w-])--proxy-headers\b", dockerfile) is not None,
        re.search(r"--forwarded-allow-ips\b", dockerfile) is not None,
    )


@pytest.fixture(autouse=True)
def _fresh_sign_in_limiter():
    _sign_in_rate_limiter.clear()
    yield
    _sign_in_rate_limiter.clear()


@pytest.fixture
async def hub(dist, monkeypatch):
    """The full app (its lifespan starts on the first request), wrapped like uvicorn does."""
    app = await _client_for(dist, monkeypatch)
    yield app
    get_settings.cache_clear()


def _client(
    app, peer: str, *, proxy_headers: bool = True, trusted: str = TRUSTED
) -> httpx.AsyncClient:
    outer = ProxyHeadersMiddleware(app, trusted_hosts=trusted) if proxy_headers else app
    transport = httpx.ASGITransport(app=outer, client=(peer, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://hub.example.invalid")


async def _fail_sign_ins(client: httpx.AsyncClient, count: int, **headers: str) -> list[int]:
    codes = []
    for _ in range(count):
        resp = await client.post("/api/v1/auth/session", json=BAD_KEY, headers=headers)
        # The response that sets the cookies is never kept by a shared cache (also 401 and 429).
        assert resp.headers["cache-control"] == "no-store"
        codes.append(resp.status_code)
    return codes


async def test_untrusted_peer_spoofed_header_uses_the_peer(hub) -> None:
    spoof = {"X-Forwarded-For": "203.0.113.9"}
    async with _client(hub, "198.51.100.7") as client:
        codes = await _fail_sign_ins(client, 11, **spoof)
    assert codes[:10] == [401] * 10
    assert codes[10] == 429  # the 11th: one bucket for the peer, whatever the header says
    # Another peer sending the same header has its own, untouched bucket.
    async with _client(hub, "198.51.100.8") as client:
        assert await _fail_sign_ins(client, 1, **spoof) == [401]


async def test_trusted_peer_uses_the_right_most_untrusted_address(hub) -> None:
    async with _client(hub, TRUSTED) as client:
        codes = await _fail_sign_ins(client, 1, **{"X-Forwarded-For": "203.0.113.1, 203.0.113.2"})
    assert codes == [401]
    keys = set(_sign_in_rate_limiter._buckets)
    assert keys == {"203.0.113.2"}


async def test_without_the_middleware_the_bucket_key_is_the_proxy_address(hub) -> None:
    """Pins what the middleware changes: without it the key is the proxy itself."""
    async with _client(hub, TRUSTED, proxy_headers=False) as client:
        await _fail_sign_ins(client, 1, **{"X-Forwarded-For": "203.0.113.1, 203.0.113.2"})
    assert set(_sign_in_rate_limiter._buckets) == {TRUSTED}


async def test_second_trusted_proxy_in_the_chain_is_skipped(hub) -> None:
    """With two trusted hops the key is the right-most address that is NOT trusted.

    A plain "last entry" would give the second proxy, "first entry" would give the spoofed one.
    """
    async with _client(hub, TRUSTED, trusted=f"{TRUSTED},198.51.100.50") as client:
        await _fail_sign_ins(
            client, 1, **{"X-Forwarded-For": "203.0.113.66, 203.0.113.1, 198.51.100.50"}
        )
    assert set(_sign_in_rate_limiter._buckets) == {"203.0.113.1"}


def test_the_image_command_keeps_the_proxy_flags() -> None:
    """Production gets the trusted proxies from uvicorn's flags in the Dockerfile CMD."""
    assert _proxy_flags(DOCKERFILE.read_text(encoding="utf-8")) == (True, True)


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ('--proxy-headers --forwarded-allow-ips="${X}"', (True, True)),
        ('--forwarded-allow-ips="${X}"', (False, True)),
        ("--proxy-headers", (True, False)),
        ("--no-proxy-headers --forwarded-allow-ips=1", (False, True)),
    ],
)
def test_proxy_flag_guard_notices_a_missing_flag(cmd: str, expected: tuple[bool, bool]) -> None:
    assert _proxy_flags(f"CMD exec uvicorn app.main:app {cmd}") == expected


async def test_two_clients_behind_one_proxy_have_separate_buckets(hub) -> None:
    async with _client(hub, TRUSTED) as client:
        first = await _fail_sign_ins(client, 11, **{"X-Forwarded-For": "203.0.113.1"})
        second = await _fail_sign_ins(client, 1, **{"X-Forwarded-For": "203.0.113.2"})
    assert first[10] == 429
    assert second == [401]
