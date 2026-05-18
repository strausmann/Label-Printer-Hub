"""Tests for the ApiKey repository — Phase 7c."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.api_key import ApiKey
from app.repositories import api_keys as repo


def _make_key(
    *,
    name="test-key",
    key_hash=r"\$2b\$12\$fake",
    key_prefix="lh_ab12cd34",
    scopes=None,
    allowed_printer_ids=None,
    rate_limit_per_minute=60,
    enabled=True,
    expires_at=None,
) -> ApiKey:
    return ApiKey(
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=scopes or ["read"],
        allowed_printer_ids=allowed_printer_ids or [],
        rate_limit_per_minute=rate_limit_per_minute,
        enabled=enabled,
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_create_inserts_and_returns_key(session):
    key = _make_key(name="plex-print", scopes=["read", "print"])
    created = await repo.create(session, key)
    assert created.id is not None
    assert created.name == "plex-print"
    assert created.scopes == ["read", "print"]
    assert created.enabled is True


@pytest.mark.asyncio
async def test_create_multiple_keys(session):
    k1 = await repo.create(session, _make_key(name="key1", key_prefix="lh_aaaaaaaaaa"))
    k2 = await repo.create(session, _make_key(name="key2", key_prefix="lh_bbbbbbbbbb"))
    assert k1.id != k2.id


@pytest.mark.asyncio
async def test_get_by_prefix_returns_matching_key(session):
    key = _make_key(key_prefix="lh_ab12cd34XX")
    await repo.create(session, key)
    found = await repo.get_by_prefix(session, "lh_ab12cd34XX")
    assert found is not None
    assert found.key_prefix == "lh_ab12cd34XX"


@pytest.mark.asyncio
async def test_get_by_prefix_returns_none_for_unknown(session):
    found = await repo.get_by_prefix(session, "lh_notexist")
    assert found is None


@pytest.mark.asyncio
async def test_list_active_returns_only_enabled_non_expired(session):
    enabled = _make_key(name="enabled", key_prefix="lh_aaaaaaaaaa", enabled=True)
    disabled = _make_key(name="disabled", key_prefix="lh_bbbbbbbbbb", enabled=False)
    expired = _make_key(
        name="expired",
        key_prefix="lh_cccccccccc",
        enabled=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    future = _make_key(
        name="future-expiry",
        key_prefix="lh_dddddddddd",
        enabled=True,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    for k in [enabled, disabled, expired, future]:
        await repo.create(session, k)
    active = await repo.list_active(session)
    names = {k.name for k in active}
    assert "enabled" in names
    assert "future-expiry" in names
    assert "disabled" not in names
    assert "expired" not in names


@pytest.mark.asyncio
async def test_list_active_empty_when_no_keys(session):
    assert await repo.list_active(session) == []


@pytest.mark.asyncio
async def test_revoke_sets_enabled_false(session):
    key = await repo.create(session, _make_key(name="to-revoke"))
    revoked = await repo.revoke(session, key.id)
    assert revoked is not None
    assert revoked.enabled is False


@pytest.mark.asyncio
async def test_revoke_nonexistent_key_returns_none(session):
    assert await repo.revoke(session, uuid4()) is None


@pytest.mark.asyncio
async def test_revoked_key_not_in_list_active(session):
    key = await repo.create(session, _make_key(name="to-revoke-2"))
    await repo.revoke(session, key.id)
    names = {k.name for k in await repo.list_active(session)}
    assert "to-revoke-2" not in names


@pytest.mark.asyncio
async def test_update_last_used_sets_timestamp_and_ip(session):
    key = await repo.create(session, _make_key(name="used-key"))
    assert key.last_used_at is None
    before = datetime.now(UTC).replace(tzinfo=None)
    updated = await repo.update_last_used(session, key.id, ip="192.0.2.10")
    after = datetime.now(UTC).replace(tzinfo=None)
    assert updated is not None
    assert updated.last_used_ip == "192.0.2.10"
    assert updated.last_used_at is not None
    luat = (
        updated.last_used_at.replace(tzinfo=None)
        if updated.last_used_at.tzinfo
        else updated.last_used_at
    )
    assert before <= luat <= after


@pytest.mark.asyncio
async def test_update_last_used_nonexistent_returns_none(session):
    assert await repo.update_last_used(session, uuid4(), ip="192.0.2.1") is None


@pytest.mark.asyncio
async def test_get_by_id_returns_key(session):
    key = await repo.create(session, _make_key(name="fetchable"))
    fetched = await repo.get(session, key.id)
    assert fetched is not None
    assert fetched.name == "fetchable"


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(session):
    assert await repo.get(session, uuid4()) is None
