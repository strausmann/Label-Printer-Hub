"""app.auth.sessions: issuing, limits, purge and cookie naming (spec 8.1)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.config import Settings
from app.models.ui_session import UiSession
from sqlalchemy import func, select


def _settings(public_url: str) -> Settings:
    return Settings(_env_file=None, public_url=public_url)  # type: ignore[arg-type]


def test_token_hash_is_sha256_hex() -> None:
    from app.auth import sessions

    digest = sessions.hash_token("fake-token")
    assert len(digest) == 64
    assert digest != "fake-token"
    assert sessions.hash_token("fake-token") == digest


def test_cookie_names_follow_scheme() -> None:
    from app.auth import sessions

    assert sessions.cookie_names(_settings("https://hub.example.invalid")) == (
        "__Host-lph_session",
        "__Host-lph_csrf",
    )
    assert sessions.cookie_names(_settings("http://localhost:8000")) == ("lph_session", "lph_csrf")


def test_insecure_warning_only_for_http(caplog: pytest.LogCaptureFixture) -> None:
    from app.auth import sessions

    with caplog.at_level(logging.WARNING, logger="app.auth.sessions"):
        sessions.warn_if_insecure(_settings("https://hub.example.invalid"))
    assert not caplog.records
    with caplog.at_level(logging.WARNING, logger="app.auth.sessions"):
        sessions.warn_if_insecure(_settings("http://hub.example.invalid"))
    assert any("cookies are sent unencrypted" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_create_session_stores_only_hash_and_expires_in_12h(async_session_factory) -> None:
    from app.auth import sessions

    async with async_session_factory() as db:
        row, token = await sessions.create_session(
            db, source="api-key", scope="print", api_key_id=uuid4(), allowed_printer_ids=[]
        )
        assert row.token_hash == sessions.hash_token(token)
        assert token not in (row.token_hash, row.csrf_token)
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        assert expires - created == timedelta(hours=12)


@pytest.mark.asyncio
async def test_twenty_first_session_revokes_oldest(async_session_factory) -> None:
    from app.auth import sessions

    key_id = uuid4()
    async with async_session_factory() as db:
        first, _ = await sessions.create_session(
            db, source="api-key", scope="print", api_key_id=key_id, allowed_printer_ids=[]
        )
        for _ in range(20):
            await sessions.create_session(
                db, source="api-key", scope="print", api_key_id=key_id, allowed_printer_ids=[]
            )
        active = await db.scalar(
            select(func.count())
            .select_from(UiSession)
            .where(UiSession.api_key_id == key_id, UiSession.revoked_at.is_(None))  # type: ignore[union-attr]
        )
        assert active == 20
        await db.refresh(first)
        assert first.revoked_at is not None


@pytest.mark.asyncio
async def test_session_limit_applies_per_sso_user(async_session_factory) -> None:
    from app.auth import sessions

    async with async_session_factory() as db:
        for _ in range(21):
            await sessions.create_session(
                db,
                source="pangolin-sso",
                scope="admin",
                api_key_id=None,
                allowed_printer_ids=[],
                user="alice",
            )
        other, _ = await sessions.create_session(
            db,
            source="pangolin-sso",
            scope="admin",
            api_key_id=None,
            allowed_printer_ids=[],
            user="bob",
        )
        active_alice = await db.scalar(
            select(func.count())
            .select_from(UiSession)
            .where(UiSession.user == "alice", UiSession.revoked_at.is_(None))  # type: ignore[union-attr]
        )
        assert active_alice == 20
        assert other.revoked_at is None


@pytest.mark.asyncio
async def test_purge_removes_only_sessions_expired_over_a_day(async_session_factory) -> None:
    from app.auth import sessions

    now = datetime.now(UTC)
    async with async_session_factory() as db:
        for label, expires in (
            ("old", now - timedelta(days=1, minutes=1)),
            ("recent", now - timedelta(hours=2)),
            ("live", now + timedelta(hours=2)),
        ):
            db.add(
                UiSession(
                    token_hash=f"hash-{label}",
                    csrf_token="fake",
                    source="api-key",
                    scope="print",
                    expires_at=expires,
                )
            )
        await db.commit()
    deleted = await sessions.purge_expired(async_session_factory)
    assert deleted == 1
    async with async_session_factory() as db:
        left = set((await db.execute(select(UiSession.token_hash))).scalars())
    assert left == {"hash-recent", "hash-live"}
