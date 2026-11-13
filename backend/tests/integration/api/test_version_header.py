"""Every API response names the version of the running hub (#288).

A browser tab opened before an update compares this value with the version its own bundle
was built for and reloads once on a mismatch. Static files and the app shell must not carry
it: they are cached by browsers and proxies, so a stale copy would report a wrong version.
"""

from __future__ import annotations

from app.main import HUB_VERSION
from httpx import AsyncClient

HEADER = "x-hub-version"


async def test_api_responses_carry_the_hub_version(spa: AsyncClient) -> None:
    for path in ("/api/v1/info", "/api/definitely-not-there"):
        resp = await spa.get(path)
        assert resp.headers.get(HEADER) == HUB_VERSION, path


async def test_unauthorised_api_response_carries_the_version_too(spa: AsyncClient) -> None:
    resp = await spa.get("/api/v1/printers")
    assert resp.status_code == 401
    assert resp.headers.get(HEADER) == HUB_VERSION


async def test_static_files_and_the_shell_do_not_carry_it(spa: AsyncClient) -> None:
    for path in ("/", "/printers/abc", "/assets/app.js", "/favicon.svg"):
        resp = await spa.get(path)
        assert resp.status_code == 200, path
        assert HEADER not in resp.headers, path


async def test_a_path_that_only_starts_like_the_api_prefix_does_not_carry_it(
    spa: AsyncClient,
) -> None:
    # "/apix" is a client route of the app shell, not an API route.
    resp = await spa.get("/apix")
    assert HEADER not in resp.headers
