"""Tests für PresetService + Preset-Schemas (Phase 1k.3, Refs #104)."""

from __future__ import annotations

import pytest
from app.schemas.content_type import ContentType
from app.schemas.preset import PresetCreatePayload
from pydantic import ValidationError


def test_create_payload_accepts_content_type_enum():
    payload = PresetCreatePayload(
        name="Schublade A",
        content_type=ContentType.QR_THREE_LINES,
        tape_mm=12,
        field_values={"primary_id": "A1", "title": "Schrauben",
                      "qr_payload": "x", "secondary": ["M3"]},
    )
    assert payload.content_type == ContentType.QR_THREE_LINES
    assert payload.tape_mm == 12


def test_create_payload_rejects_empty_name():
    with pytest.raises(ValidationError):
        PresetCreatePayload(name="", content_type=ContentType.QR_ONLY, tape_mm=12)
