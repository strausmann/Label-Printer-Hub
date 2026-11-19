# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""An over-long API key is an invalid key, not a server error (#321).

bcrypt 5 raises ``ValueError`` for more than 72 bytes. A header value that starts with a
real 16-character prefix reached that call and answered 500.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import bcrypt
import pytest
import pytest_asyncio
from app.auth.dependencies import MAX_KEY_LENGTH, require_scope
from app.auth.verifier import _cache as verifier_cache
from app.config import Settings
from app.db.session import get_session
from app.models.api_key import ApiKey
from app.repositories import api_keys as api_keys_repo
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# Built at runtime: a literal in the key format would trip the repository's secret scanner.
KEY = "lh_pat_" + "overlong" + "K" * 35
UNKNOWN_BODY = {
    "detail": {"error_code": "invalid_key", "error_message": "Invalid or unknown API key"}
}


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    verifier_cache.clear()
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        s.add(
            ApiKey(
                name="overlong",
                key_hash=bcrypt.hashpw(KEY.encode(), bcrypt.gensalt(rounds=4)).decode(),
                key_prefix=KEY[:16],
                scopes=["print"],
                allowed_printer_ids=[],
                enabled=True,
            )
        )
        await s.commit()
    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/t")
    async def ep(ctx: Any = Depends(require_scope("read", settings=settings))) -> dict[str, str]:
        return {"scope": ctx.scope}

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://hub.example.invalid") as c:
        yield c
    await eng.dispose()
    verifier_cache.clear()


def test_limit_matches_the_url_token_limit() -> None:
    from app.api.dependencies.token_auth import MAX_TOKEN_LENGTH

    assert MAX_KEY_LENGTH == MAX_TOKEN_LENGTH == 128


@pytest.mark.asyncio
async def test_real_prefix_plus_300_chars_is_401_like_an_unknown_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = api_keys_repo.get_by_prefix

    async def _spy(session: AsyncSession, prefix: str) -> ApiKey | None:
        calls.append(prefix)
        return await real(session, prefix)

    monkeypatch.setattr(api_keys_repo, "get_by_prefix", _spy)
    token = KEY[:16] + "x" * 300
    r = await client.get("/t", headers={"X-Label-Hub-Key": token})
    assert r.status_code == 401
    assert r.json() == UNKNOWN_BODY
    assert token not in r.text
    assert calls == [], "the length is checked before the key lookup"


@pytest.mark.asyncio
async def test_key_within_the_limit_but_over_72_bytes_is_401(client: AsyncClient) -> None:
    # Within the length limit, over bcrypt's 72 bytes, with a real prefix: reaches bcrypt.
    token = KEY + "y" * 30
    assert len(token) <= MAX_KEY_LENGTH and len(token.encode()) > 72
    r = await client.get("/t", headers={"X-Label-Hub-Key": token})
    assert r.status_code == 401
    assert r.json() == UNKNOWN_BODY


@pytest.mark.asyncio
async def test_real_key_still_works(client: AsyncClient) -> None:
    r = await client.get("/t", headers={"X-Label-Hub-Key": KEY})
    assert r.status_code == 200
