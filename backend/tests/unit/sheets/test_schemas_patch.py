"""OpenAPI shape of the sheet type patch body."""

from __future__ import annotations

from app.schemas.sheets import SheetTypePatch


def test_fields_the_endpoint_refuses_to_clear_are_not_nullable() -> None:
    props = SheetTypePatch.model_json_schema()["properties"]
    for name in ("prefix", "product_codes", "allow_qr", "verified"):
        assert "anyOf" not in props[name], name
    # Text fields that null clears stay nullable.
    for name in ("vendor", "description", "source_name", "source_url", "notes"):
        assert any(o.get("type") == "null" for o in props[name]["anyOf"]), name
