"""Integration tests for auth dependency wiring on all routes — Phase 7c Step 4.

Tests that each category of endpoint:
1. Returns 401 without any auth
2. Returns 200/204 with a valid auth header of the correct scope
"""

from __future__ import annotations

from pathlib import Path

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey

_SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


async def _make_print_key(factory):
    """Insert an api-key with print scope and return (plaintext, ApiKey)."""
    plaintext = "lh_pat_print_integ_wiring_test_step4_001"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="wiring-test-print",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["print"],
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()
    return plaintext


async def _make_read_key(factory):
    plaintext = "lh_pat_read_integ_wiring_test_step4_002"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="wiring-test-read",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["read"],
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()
    return plaintext


async def _make_admin_key(factory):
    plaintext = "lh_pat_admin_integ_wiring_test_step4_003"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="wiring-test-admin",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["admin"],
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()
    return plaintext


# --------------------------------------------------------------------------
# Helper: build app client with DB patched
# --------------------------------------------------------------------------


def _make_client_ctx(factory):
    import app.db.session as _session_module
    from app.main import create_app

    _session_module.async_session = factory

    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()

    from app.services.template_loader import TemplateLoader

    original_cache = dict(TemplateLoader._cache)
    TemplateLoader.load_dir(_SEED_DIR)

    app = create_app()
    return app, original_cache, TemplateLoader


@pytest.mark.asyncio
async def test_get_printers_without_auth_returns_401(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/printers")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_get_printers_with_read_key_returns_200(api_client_with_seed):
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    read_key = await _make_read_key(factory)

    resp = await api_client_with_seed.get(
        "/api/printers",
        headers={"X-Label-Hub-Key": read_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_get_templates_without_auth_returns_401(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/templates")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_get_templates_with_read_key_returns_200(api_client_with_seed):
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    read_key = await _make_read_key(factory)

    resp = await api_client_with_seed.get(
        "/api/templates",
        headers={"X-Label-Hub-Key": read_key},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


@pytest.mark.asyncio
async def test_get_jobs_without_auth_returns_401(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/jobs")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_readiness_without_auth_returns_401(api_client_with_seed):
    """Readiness endpoint requires read scope."""
    resp = await api_client_with_seed.get("/readiness")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_healthz_is_public_no_auth(api_client_with_seed):
    """healthz endpoint is always publicly accessible (no auth required)."""
    resp = await api_client_with_seed.get("/healthz")
    assert resp.status_code == 200, f"healthz should be public: {resp.status_code}"


@pytest.mark.asyncio
async def test_pangolin_sso_header_grants_read(api_client_with_seed):
    """Pangolin-SSO header (X-Pangolin-User) grants read access."""
    resp = await api_client_with_seed.get(
        "/api/printers",
        headers={"X-Pangolin-User": "testuser@example.com"},
    )
    assert resp.status_code == 200, f"SSO should grant read: {resp.status_code}"
