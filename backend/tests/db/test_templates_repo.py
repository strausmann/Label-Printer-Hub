"""Tests for the templates repository — seed/user split contract."""
import pytest

from app.models.template import Template
from app.repositories import templates


def _seed(key: str, name: str = "x", w: int = 12) -> Template:
    return Template(
        key=key, name=name, printer_model="pt-series", tape_width_mm=w,
        definition={"elements": []}, source="seed",
    )


@pytest.mark.asyncio
async def test_seed_idempotent(session):
    await templates.upsert_seed(session, [_seed("a"), _seed("b")])
    await templates.upsert_seed(session, [_seed("a"), _seed("b")])
    all_ = await templates.list_all(session)
    assert len(all_) == 2


@pytest.mark.asyncio
async def test_seed_does_not_overwrite_user(session):
    user = Template(key="custom", name="user-edited", printer_model="pt-series",
                    tape_width_mm=12, definition={"v": 1}, source="user")
    await templates.create_user_template(session, user)

    # Try to upsert a seed with the same key
    await templates.upsert_seed(session, [_seed("custom", name="seed-name")])

    found = await templates.get_by_key(session, "custom")
    assert found.source == "user"
    assert found.name == "user-edited"
