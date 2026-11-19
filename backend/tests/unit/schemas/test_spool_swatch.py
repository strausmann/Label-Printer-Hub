# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The swatch label's data model (#346, R-346-4)."""

from __future__ import annotations

import json
import math

import pytest
from app.schemas.label_data import LabelData
from app.schemas.spool_swatch import SpoolSwatch
from pydantic import ValidationError


def _swatch(**kw: object) -> SpoolSwatch:
    base: dict[str, object] = {"spool_id": 12}
    base.update(kw)
    return SpoolSwatch.model_validate(base)


def test_text_over_64_characters_is_refused() -> None:
    _swatch(vendor="x" * 64)
    for name in ("vendor", "title", "color_name", "location", "lot"):
        with pytest.raises(ValidationError):
            _swatch(**{name: "x" * 65})


def test_hex_codes_are_normalised_and_alpha_dropped() -> None:
    swatch = _swatch(color_hexes=("7f3696ff", "#006ec9", "FFFFFF"))
    assert swatch.color_hexes == ("7F3696", "006EC9", "FFFFFF")
    with pytest.raises(ValidationError):
        _swatch(color_hexes=("12345",))
    with pytest.raises(ValidationError):
        _swatch(color_hexes=("GGGGGG",))


def test_more_than_16_hex_codes_are_refused() -> None:
    _swatch(color_hexes=("000000",) * 16)
    with pytest.raises(ValidationError):
        _swatch(color_hexes=("000000",) * 17)


def test_out_of_range_temperature_is_refused() -> None:
    _swatch(bed_c=600, nozzle_c=(0, 600), drying_c=600)
    with pytest.raises(ValidationError):
        _swatch(bed_c=601)
    with pytest.raises(ValidationError):
        _swatch(nozzle_c=(200, 601))
    with pytest.raises(ValidationError):
        _swatch(drying_c=601)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_are_refused(bad: float) -> None:
    for name in ("pressure_advance", "flow_ratio", "spool_weight_g", "diameter_mm"):
        with pytest.raises(ValidationError):
            _swatch(**{name: bad})
    with pytest.raises(ValidationError):
        _swatch(drying_h=(1.0, bad))


def test_a_range_with_low_above_high_is_refused() -> None:
    _swatch(nozzle_c=(215, 215), drying_h=(8.0, 8.0))
    with pytest.raises(ValidationError):
        _swatch(nozzle_c=(230, 210))
    with pytest.raises(ValidationError):
        _swatch(drying_h=(8.0, 6.0))


def test_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        _swatch(remaining_weight=500)


def test_label_data_round_trips_with_swatch() -> None:
    swatch = _swatch(vendor="TecBears", title="PETG", nozzle_c=(220, 240), opened="2026-11-03")
    label = LabelData(source_app="spoolman", qr_payload="https://x.example/s/12", swatch=swatch)
    again = LabelData.model_validate(label.model_dump())
    assert again == label
    assert LabelData.model_validate_json(label.model_dump_json()) == label


def test_model_dump_is_json_serialisable() -> None:
    swatch = _swatch(
        vendor="TecBears",
        color_hexes=("FF5F00",),
        nozzle_c=(220, 240),
        drying_h=(6.0, 8.0),
        opened="2026-11-03",
    )
    label = LabelData(source_app="spoolman", qr_payload="u", swatch=swatch)
    json.dumps(label.model_dump())


def test_opened_must_be_a_real_date() -> None:
    _swatch(opened="2026-02-28")
    with pytest.raises(ValidationError):
        _swatch(opened="2026-02-30")
    with pytest.raises(ValidationError):
        _swatch(opened="03.11.2026")


def test_spool_id_is_at_least_one() -> None:
    with pytest.raises(ValidationError):
        _swatch(spool_id=0)
