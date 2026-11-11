"""The lookup endpoint needs a key or session (read scope); it is no longer public.

The server-rendered QR pages that justified an anonymous lookup are gone: the browser
reads the item through this endpoint after signing in. All keys are obviously fake.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey
from app.schemas.label_data import LabelData

_LABEL = LabelData(
    title="ThinkPad X1 Carbon",
    primary_id="ASSET-001",
    qr_payload="https://snipeit.example.invalid/hardware/42",
    source_app="snipeit",
    secondary=(),
)


async def _insert_key(scopes: list[str]) -> str:
    import app.db.engine as _engine_module

    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _engine_module.async_session() as s:
        s.add(
            ApiKey(
                name=f"lookup-auth-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=[],
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return plaintext


@pytest.mark.asyncio
async def test_lookup_without_credentials_is_401(api_client_with_seed):
    with patch(
        "app.api.routes.lookup._lookup_service.lookup", new=AsyncMock(return_value=_LABEL)
    ) as svc:
        resp = await api_client_with_seed.get("/api/v1/lookup/snipeit/ASSET-001")
    assert resp.status_code == 401
    svc.assert_not_called()  # nothing reached the integration


@pytest.mark.asyncio
async def test_lookup_with_a_read_key_is_200(api_client_with_seed):
    key = await _insert_key(["read"])
    with patch("app.api.routes.lookup._lookup_service.lookup", new=AsyncMock(return_value=_LABEL)):
        resp = await api_client_with_seed.get(
            "/api/v1/lookup/snipeit/ASSET-001", headers={"X-Label-Hub-Key": key}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "ThinkPad X1 Carbon"
