"""Repo-Tests für Preset-Aggregat (Phase 1k.3, Refs #104)."""

from __future__ import annotations

import pytest
from app.models.preset import Preset
from app.repositories import presets as preset_repo


@pytest.mark.asyncio
async def test_create_and_get_roundtrip_with_layout_fields(session):
    created = await preset_repo.create(
        session,
        Preset(name="Schublade A", content_type="qr_three_lines", tape_mm=12),
    )
    fetched = await preset_repo.get(session, created.id)
    assert fetched is not None
    assert fetched.name == "Schublade A"
    assert fetched.content_type == "qr_three_lines"
    assert fetched.tape_mm == 12


@pytest.mark.asyncio
async def test_defaults_applied(session):
    created = await preset_repo.create(session, Preset(name="Default-Preset"))
    assert created.content_type == "qr_three_lines"
    assert created.tape_mm == 12
