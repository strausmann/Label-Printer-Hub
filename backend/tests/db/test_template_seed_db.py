"""Tests for TemplateLoader.seed_db() — the canonical YAML-to-DB conversion.

These tests exercise the public classmethod directly, using a controlled set
of YAML-parsed TemplateSchema objects loaded into the class cache so there is
no dependency on the real seed-template directory or IntegrationRegistry.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models.template import Template
from app.repositories import templates as templates_repo
from app.services.template_loader import TemplateLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_stub_cache(ids: list[str]) -> dict:
    """Build synthetic TemplateSchema objects and inject them into the class
    cache without touching the filesystem or IntegrationRegistry.

    Uses ``TemplateSchema`` directly so the objects match exactly what a
    real YAML load produces, making the conversion path in seed_db identical
    to the production path.
    """
    from app.schemas.template import TemplateSchema

    cache = {}
    for id_ in ids:
        cache[id_] = TemplateSchema(
            id=id_,
            name=f"Template {id_}",
            app=None,  # generic — no integration dependency
            tape_mm=12,
            schema_version=1,
            elements=(
                {
                    "type": "qr",
                    "x": 0,
                    "y": 0,
                    "size": 80,
                    "data_field": "url",
                },
            ),
        )
    return cache


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_db_idempotent(session):
    """seed_db called twice returns the same count with no duplicate rows."""
    original_cache = dict(TemplateLoader._cache)
    try:
        TemplateLoader._cache = _load_stub_cache(["alpha", "beta", "gamma"])

        count_first = await TemplateLoader.seed_db(session)
        count_second = await TemplateLoader.seed_db(session)

        assert count_first == 3
        assert count_second == 3

        rows = await templates_repo.list_all(session)
        assert len(rows) == 3

        # Verify all three keys are present
        keys = {r.key for r in rows}
        assert keys == {"alpha", "beta", "gamma"}

        # All rows must be marked as seed
        assert all(r.source == "seed" for r in rows)
    finally:
        TemplateLoader._cache = original_cache


@pytest.mark.asyncio
async def test_seed_db_user_template_survives(session):
    """A user-created template with a non-conflicting key is untouched by seed_db."""
    original_cache = dict(TemplateLoader._cache)
    try:
        # Create a user row in the DB first
        user_tpl = Template(
            key="my-custom-label",
            name="My Company Label",
            printer_model="pt-series",
            tape_width_mm=18,
            definition={"custom": True},
            source="user",
        )
        await templates_repo.create_user_template(session, user_tpl)

        # Seed the cache with different keys
        TemplateLoader._cache = _load_stub_cache(["seed-a", "seed-b"])
        await TemplateLoader.seed_db(session)

        # The user row must still exist and be unchanged
        found = await templates_repo.get_by_key(session, "my-custom-label")
        assert found is not None
        assert found.source == "user"
        assert found.name == "My Company Label"
        assert found.tape_width_mm == 18

        # Total rows = 1 user + 2 seed
        all_rows = await templates_repo.list_all(session)
        assert len(all_rows) == 3
    finally:
        TemplateLoader._cache = original_cache
