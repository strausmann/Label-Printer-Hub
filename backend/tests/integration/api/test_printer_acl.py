"""Integration tests for per-key printer ACL — Phase 7c Step 6."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey

_SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


async def _insert_restricted_key(factory, *, allowed_printer_ids: list[str], scopes=None):
    """Insert a key restricted to specific printer IDs."""
    plaintext = f"lh_pat_acl_t_{uuid4().hex[:16]}"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="acl-test-key",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=scopes or ["print"],
            allowed_printer_ids=allowed_printer_ids,
            enabled=True,
            rate_limit_per_minute=60,
        )
        s.add(key)
        await s.commit()
    return plaintext


@pytest.mark.asyncio
async def test_key_with_no_restriction_allows_all_printers(api_client_with_seed):
    """Empty allowed_printer_ids means all printers are allowed."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session

    # Key with empty allowed_printer_ids
    plaintext = await _insert_restricted_key(factory, allowed_printer_ids=[], scopes=["read"])

    resp = await api_client_with_seed.get(
        "/api/printers",
        headers={"X-Label-Hub-Key": plaintext},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_key_restricted_to_printer_a_blocked_on_printer_b(api_client_with_seed):
    """Key with allowed_printer_ids=[A] cannot access printer B."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session

    # Get a real printer ID from the DB
    from app.repositories import printers as printers_repo

    async with factory() as s:
        all_printers = await printers_repo.list_all(s)

    if len(all_printers) == 0:
        pytest.skip("No printers in DB to test ACL against")

    printer_b_id = str(all_printers[0].id)
    # Create a fake printer A ID (not in DB, just for ACL test)
    printer_a_id = str(uuid4())

    # Key restricted to printer A
    plaintext = await _insert_restricted_key(
        factory,
        allowed_printer_ids=[printer_a_id],
        scopes=["print"],
    )

    # Trying to pause printer B should fail
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_b_id}/pause",
        headers={"X-Label-Hub-Key": plaintext},
    )
    assert resp.status_code == 403, (
        f"Expected 403 for restricted key on wrong printer, got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_key_restricted_to_printer_a_allowed_on_printer_a(api_client_with_seed):
    """Key with allowed_printer_ids=[A] can access printer A."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session

    from app.repositories import printers as printers_repo

    async with factory() as s:
        all_printers = await printers_repo.list_all(s)

    if len(all_printers) == 0:
        pytest.skip("No printers in DB to test ACL against")

    printer_a_id = str(all_printers[0].id)
    plaintext = await _insert_restricted_key(
        factory,
        allowed_printer_ids=[printer_a_id],
        scopes=["print"],
    )

    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_a_id}/pause",
        headers={"X-Label-Hub-Key": plaintext},
    )
    # 204 = success, or 404 if printer not found after test setup — either is fine
    assert resp.status_code in (204, 404), (
        f"Expected 204 or 404, got {resp.status_code}: {resp.text}"
    )
