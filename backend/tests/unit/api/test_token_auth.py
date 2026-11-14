# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for ``require_print_token``: a print-scope API key passed as the URL ``token`` (#281).

Grocy's label printer webhook sends no headers of its own, so the key travels in the
query string. Every failure of the token itself must answer the same 401, an admin key
is refused, and the token never reaches a response body.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
import pytest
import pytest_asyncio
from app.api.dependencies.token_auth import (
    MAX_TOKEN_LENGTH,
    TOKEN_QUERY_PARAM,
    require_print_token,
)
from app.auth.dependencies import AuthContext
from app.auth.verifier import _cache as verifier_cache
from app.db.session import get_session
from app.models.api_key import ApiKey
from app.repositories import api_keys as api_keys_repo
from app.services.rate_limiter import _rate_limiter
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


def _key(word: str, fill: str) -> str:
    """A made-up key in the real format (``lh_pat_`` + 43 chars), built at runtime so the
    source holds no literal that the repository's secret scanner would flag."""
    return "lh_pat_" + word + fill * (43 - len(word))


# Fixed test keys. Never real secrets.
PRINT_KEY = _key("print", "A")
READ_KEY = _key("read", "B")
ADMIN_KEY = _key("admin", "C")
DISABLED_KEY = _key("disabled", "D")
EXPIRED_KEY = _key("expired", "E")
LIMITED_KEY = _key("limited", "F")
NOSCOPE_KEY = _key("noscope", "H")
UNKNOWN_KEY = _key("unknown", "G")
ADMIN_LIMITED_KEY = _key("adminlimited", "J")
# Same 16-character prefix as PRINT_KEY, wrong secret.
WRONG_SECRET = PRINT_KEY[:16] + "Z" * (len(PRINT_KEY) - 16)

INVALID_TOKEN_BODY = {
    "detail": {
        "error_code": "invalid_token",
        "error_message": "The token is missing or not valid.",
    }
}


def test_constants() -> None:
    assert TOKEN_QUERY_PARAM == "token"
    assert MAX_TOKEN_LENGTH == 128


def _row(plaintext: str, scopes: list[str], **extra: Any) -> ApiKey:
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    extra.setdefault("enabled", True)
    return ApiKey(
        name=f"key-{scopes[0] if scopes else 'none'}",
        key_hash=hashed,
        key_prefix=plaintext[:16],
        scopes=scopes,
        allowed_printer_ids=[],
        **extra,
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    _rate_limiter.clear()
    verifier_cache.clear()
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        s.add(_row(PRINT_KEY, ["print"]))
        s.add(_row(READ_KEY, ["read"]))
        s.add(_row(ADMIN_KEY, ["admin"]))
        s.add(_row(DISABLED_KEY, ["print"], enabled=False))
        s.add(_row(EXPIRED_KEY, ["print"], expires_at=datetime.now(UTC) - timedelta(days=1)))
        s.add(_row(LIMITED_KEY, ["print"], rate_limit_per_minute=1))
        s.add(_row(NOSCOPE_KEY, []))
        s.add(_row(ADMIN_LIMITED_KEY, ["admin"], rate_limit_per_minute=1))
        await s.commit()

    app = FastAPI()

    @app.post("/hook")
    async def hook(auth: AuthContext = Depends(require_print_token)) -> dict[str, Any]:
        return {
            "scope": auth.scope,
            "api_key_id": str(auth.api_key_id) if auth.api_key_id else None,
        }

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://hub.example.invalid") as c:
        c.session_factory = factory  # type: ignore[attr-defined]
        yield c
    await eng.dispose()
    _rate_limiter.clear()
    verifier_cache.clear()


@pytest.mark.asyncio
async def test_print_key_in_query_is_accepted(client: AsyncClient) -> None:
    r = await client.post(f"/hook?{TOKEN_QUERY_PARAM}={PRINT_KEY}")
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "print"
    assert UUID(r.json()["api_key_id"])


@pytest.mark.asyncio
async def test_header_wins_over_query(client: AsyncClient) -> None:
    # The query carries an admin key that would be refused; the header's print key wins.
    r = await client.post(f"/hook?token={ADMIN_KEY}", headers={"X-Label-Hub-Key": PRINT_KEY})
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "print"
    # And the other way round: a bad header is not rescued by a good query token.
    r = await client.post(f"/hook?token={PRINT_KEY}", headers={"X-Label-Hub-Key": READ_KEY})
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "insufficient_scope"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "",
        "?token=",
        "?token=short",
        f"?token={UNKNOWN_KEY}",
        f"?token={DISABLED_KEY}",
        f"?token={EXPIRED_KEY}",
        f"?token={WRONG_SECRET}",
    ],
    ids=["missing", "empty", "short", "unknown", "disabled", "expired", "wrong-secret"],
)
async def test_bad_token_is_one_401(client: AsyncClient, query: str) -> None:
    r = await client.post(f"/hook{query}")
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY


@pytest.mark.asyncio
async def test_key_without_scopes_is_the_same_401(client: AsyncClient) -> None:
    # key_no_scopes is a 401 of _validate_api_key too; it must not be told apart.
    r = await client.post(f"/hook?token={NOSCOPE_KEY}")
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY


@pytest.mark.asyncio
async def test_read_key_is_403_insufficient_scope(client: AsyncClient) -> None:
    r = await client.post(f"/hook?token={READ_KEY}")
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_admin_key_is_403_token_scope_too_wide(client: AsyncClient) -> None:
    r = await client.post(f"/hook?token={ADMIN_KEY}")
    assert r.status_code == 403
    assert r.json() == {
        "detail": {
            "error_code": "token_scope_too_wide",
            "error_message": "Use a key with the print scope for a URL token.",
        }
    }
    assert ADMIN_KEY not in r.text


@pytest.mark.asyncio
async def test_overlong_token_with_valid_prefix_is_401_not_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _spy(session: AsyncSession, prefix: str) -> None:
        calls.append(prefix)
        return None

    monkeypatch.setattr(api_keys_repo, "get_by_prefix", _spy)
    token = PRINT_KEY[:16] + "x" * 300
    r = await client.post(f"/hook?token={token}")
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY
    assert token not in r.text
    assert calls == [], "a token over 128 characters must be refused before any lookup"


@pytest.mark.asyncio
async def test_token_over_bcrypt_limit_but_within_128_is_401_not_500(client: AsyncClient) -> None:
    # bcrypt >= 5 raises ValueError on more than 72 bytes; a real prefix reaches bcrypt.
    token = PRINT_KEY + "y" * (MAX_TOKEN_LENGTH - len(PRINT_KEY))
    assert len(token) == MAX_TOKEN_LENGTH
    r = await client.post(f"/hook?token={token}")
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY


@pytest.mark.asyncio
async def test_encoded_parameter_name_is_not_a_token(client: AsyncClient) -> None:
    r = await client.post(f"/hook?to%6Ben={PRINT_KEY}")
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["?TOKEN={k}", "?Token={k}", "?a=1;token={k}", "?%74oken={k}"],
    ids=["upper", "title", "semicolon", "enc-t"],
)
async def test_look_alikes_the_filter_hides_are_not_accepted(
    client: AsyncClient, query: str
) -> None:
    # The reader stays literal; the log filter redacts these too (a superset).
    r = await client.post("/hook" + query.format(k=PRINT_KEY))
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY


@pytest.mark.asyncio
async def test_percent_encoded_value_is_decoded(client: AsyncClient) -> None:
    encoded = PRINT_KEY.replace("_", "%5F")
    r = await client.post(f"/hook?x=1&token={encoded}&y=2")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_similar_parameter_names_are_not_a_token(client: AsyncClient) -> None:
    r = await client.post(f"/hook?xtoken={PRINT_KEY}&tokenizer={PRINT_KEY}")
    assert r.status_code == 401
    assert r.json() == INVALID_TOKEN_BODY


@pytest.mark.asyncio
async def test_rate_limit_applies(client: AsyncClient) -> None:
    first = await client.post(f"/hook?token={LIMITED_KEY}")
    assert first.status_code == 200, first.text
    second = await client.post(f"/hook?token={LIMITED_KEY}")
    assert second.status_code == 429
    assert second.json()["detail"]["error_code"] == "rate_limit_exceeded"
    assert second.headers["Retry-After"]
    assert LIMITED_KEY not in second.text


async def _last_used(client: AsyncClient, plaintext: str) -> tuple[Any, Any]:
    async with client.session_factory() as s:  # type: ignore[attr-defined]
        row = await api_keys_repo.get_by_prefix(s, plaintext[:16])
        assert row is not None
        return row.last_used_at, row.last_used_ip


@pytest.mark.asyncio
async def test_refused_admin_key_uses_no_rate_limit_slot(client: AsyncClient) -> None:
    # Over its limit an admin key must still be refused for its scope, not answered with a
    # 429 that names the key to Grocy's user.
    for _ in range(3):
        r = await client.post(f"/hook?token={ADMIN_LIMITED_KEY}")
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["error_code"] == "token_scope_too_wide"


@pytest.mark.asyncio
async def test_refused_admin_key_is_not_marked_as_used(client: AsyncClient) -> None:
    r = await client.post(f"/hook?token={ADMIN_KEY}")
    assert r.status_code == 403
    assert await _last_used(client, ADMIN_KEY) == (None, None)


@pytest.mark.asyncio
async def test_accepted_print_key_is_marked_as_used(client: AsyncClient) -> None:
    # Positive control for the test above: an accepted key does get its timestamp.
    r = await client.post(f"/hook?token={PRINT_KEY}")
    assert r.status_code == 200
    used_at, _ip = await _last_used(client, PRINT_KEY)
    assert used_at is not None
