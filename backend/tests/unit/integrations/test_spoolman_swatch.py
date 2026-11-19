# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Spoolman spool -> ``SpoolSwatch`` (#346, R-346-3/4/5). Fictitious data only."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any
from unittest.mock import patch

import pytest
from app.integrations.spoolman.swatch import (
    EXTRA_RAW_MAX,
    SwatchKeys,
    build_swatch,
    parse_extra,
)

KEYS = SwatchKeys(
    nozzle="nozzle_temperature",
    pressure_advance="flowdynamics",
    flow_ratio="flowrate",
    drying_temp="drying_condiftions_temp",
    drying_time="drying_condiftions_time",
)


def _full() -> dict[str, Any]:
    return {
        "id": 12,
        "filament": {
            "vendor": {"name": "TecBears"},
            "name": "Orange",
            "material": "PETG",
            "color_hex": "FF5F00",
            "settings_extruder_temp": 235,
            "settings_bed_temp": 80,
            "spool_weight": 200,
            "weight": 750,
            "diameter": 1.75,
            "density": 1.27,
            "extra": {
                "nozzle_temperature": "[220, 240]",
                "flowdynamics": "0.031",
                "flowrate": "0.95",
                "drying_condiftions_temp": "65",
                "drying_condiftions_time": "[6, 8]",
            },
            "price": 19.99,
        },
        "extra": {"flowdynamics": "0.029", "flowrate": "0.96"},
        "spool_weight": 124,
        "initial_weight": 1000,
        "location": "Shelf A2",
        "lot_nr": "X-0001",
        "first_used": "2026-11-03T08:00:00Z",
        "remaining_weight": 850.5,
        "used_weight": 149.5,
        "price": 24.5,
    }


def _build(payload: dict[str, Any], **kw: Any) -> Any:
    args: dict[str, Any] = {
        "keys": KEYS,
        "title_source": "material",
        "language": "en",
        "time_zone": "UTC",
    }
    args.update(kw)
    return build_swatch(payload, **args)


def test_full_spool_maps_every_field() -> None:
    swatch = _build(_full())
    assert swatch is not None
    assert swatch.spool_id == 12
    assert swatch.vendor == "TecBears"
    assert swatch.title == "PETG"
    assert swatch.color_name == "Orange"
    assert swatch.color_hexes == ("FF5F00",)
    assert swatch.nozzle_c == (220, 240)
    assert swatch.bed_c == 80
    assert swatch.pressure_advance == pytest.approx(0.029)
    assert swatch.flow_ratio == pytest.approx(0.96)
    assert swatch.drying_c == 65
    assert swatch.drying_h == (6.0, 8.0)
    assert swatch.spool_weight_g == 124
    assert swatch.net_weight_g == 1000
    assert swatch.location == "Shelf A2"
    assert swatch.diameter_mm == pytest.approx(1.75)
    assert swatch.density_g_cm3 == pytest.approx(1.27)
    assert swatch.lot == "X-0001"
    assert swatch.opened == "2026-11-03"
    assert swatch.language == "en"


def test_spool_extra_overrides_filament_extra() -> None:
    payload = _full()
    swatch = _build(payload)
    assert swatch.pressure_advance == pytest.approx(0.029)
    assert swatch.flow_ratio == pytest.approx(0.96)
    del payload["extra"]
    swatch = _build(payload)
    assert swatch.pressure_advance == pytest.approx(0.031)
    assert swatch.flow_ratio == pytest.approx(0.95)


def test_nozzle_falls_back_to_extruder_temp() -> None:
    payload = _full()
    del payload["filament"]["extra"]["nozzle_temperature"]
    assert _build(payload).nozzle_c == (235, 235)


def test_spool_weights_win_over_filament_weights() -> None:
    payload = _full()
    swatch = _build(payload)
    assert (swatch.spool_weight_g, swatch.net_weight_g) == (124, 1000)
    del payload["spool_weight"], payload["initial_weight"]
    swatch = _build(payload)
    assert (swatch.spool_weight_g, swatch.net_weight_g) == (200, 750)


def test_multi_colour_hexes_win_over_color_hex() -> None:
    payload = _full()
    payload["filament"]["multi_color_hexes"] = "7f3696ff,006EC9, FFFFFF"
    assert _build(payload).color_hexes == ("7F3696", "006EC9", "FFFFFF")


def test_title_source_material_puts_material_on_the_bar() -> None:
    swatch = _build(_full(), title_source="material")
    assert (swatch.title, swatch.color_name) == ("PETG", "Orange")


def test_title_source_name_puts_the_name_on_the_bar() -> None:
    payload = _full()
    payload["filament"]["name"] = "HT-PLA Pro"
    payload["filament"]["material"] = "PLA"
    swatch = _build(payload, title_source="name")
    assert (swatch.title, swatch.color_name) == ("HT-PLA Pro", "PLA")


def test_empty_bar_source_prints_the_id() -> None:
    from app.services.spool_swatch import swatch_text

    payload = _full()
    payload["filament"]["material"] = ""
    swatch = _build(payload)
    assert swatch.title is None
    assert swatch_text(swatch).title == "#12"
    assert swatch.color_name == "Orange"


def test_missing_vendor_leaves_the_line_empty() -> None:
    payload = _full()
    del payload["filament"]["vendor"]
    swatch = _build(payload)
    assert swatch.vendor is None


def test_no_extra_field_is_read_for_the_colour() -> None:
    payload = _full()
    payload["filament"]["extra"]["color_name"] = '"Sunset"'
    payload["extra"]["color"] = '"Sunset"'
    swatch = _build(payload)
    assert swatch.color_name == "Orange"


def test_malformed_extra_drops_only_its_row() -> None:
    payload = _full()
    payload["filament"]["extra"]["nozzle_temperature"] = "[210,"
    swatch = _build(payload)
    assert swatch.nozzle_c is None
    assert swatch.bed_c == 80
    assert swatch.pressure_advance == pytest.approx(0.029)
    assert swatch.drying_h == (6.0, 8.0)
    assert swatch.location == "Shelf A2"


def test_wrong_shape_is_left_out() -> None:
    payload = _full()
    payload["extra"]["flowdynamics"] = "[1, 2]"
    payload["filament"]["extra"]["flowdynamics"] = "[1, 2]"
    payload["filament"]["extra"]["drying_condiftions_time"] = "0.5"
    swatch = _build(payload)
    assert swatch.pressure_advance is None
    assert swatch.drying_h is None
    assert swatch.drying_c == 65


def test_range_with_one_null_end() -> None:
    payload = _full()
    payload["filament"]["extra"]["nozzle_temperature"] = "[null, 230]"
    assert _build(payload).nozzle_c == (230, 230)
    payload["filament"]["extra"]["nozzle_temperature"] = "[210, null]"
    assert _build(payload).nozzle_c == (210, 210)
    payload["filament"]["extra"]["nozzle_temperature"] = "[null, null]"
    assert _build(payload).nozzle_c is None  # set but empty: the row is left out


def test_wrong_typed_plain_fields_are_left_out() -> None:
    payload = _full()
    payload["spool_weight"] = "abc"
    del payload["filament"]["spool_weight"]
    payload["filament"]["settings_bed_temp"] = [1]
    payload["filament"]["vendor"] = "x"
    payload["filament"]["diameter"] = {}
    swatch = _build(payload)
    assert swatch is not None
    assert swatch.spool_weight_g is None
    assert swatch.bed_c is None
    assert swatch.vendor is None
    assert swatch.diameter_mm is None
    assert swatch.net_weight_g == 1000
    assert swatch.title == "PETG"
    assert swatch.location == "Shelf A2"


def test_booleans_are_not_numbers() -> None:
    payload = _full()
    payload["filament"]["settings_bed_temp"] = True
    assert _build(payload).bed_c is None


def test_hostile_values_are_left_out_and_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    payload = _full()
    payload["extra"]["flowdynamics"] = "<script>alert(1)</script>"
    payload["filament"]["extra"]["flowdynamics"] = "<script>alert(1)</script>"
    payload["filament"]["extra"]["nozzle_temperature"] = "[" * 5000 + "]" * 5000
    payload["location"] = "<b>x</b>"
    with caplog.at_level(logging.DEBUG, logger="app.integrations.spoolman.swatch"):
        swatch = _build(payload)
    assert swatch is not None
    assert swatch.pressure_advance is None
    assert swatch.nozzle_c is None
    assert swatch.location == "<b>x</b>"
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("flowdynamics" in r.getMessage() for r in debug)
    assert any("nozzle_temperature" in r.getMessage() for r in debug)
    text = caplog.text
    assert "<script>" not in text
    assert "[[[" not in text


def test_overlong_extra_is_dropped_before_parsing() -> None:
    raw = "1" * (EXTRA_RAW_MAX + 1)
    with patch("app.integrations.spoolman.swatch.json.loads", side_effect=AssertionError):
        assert parse_extra(raw, "integer") is None
    assert parse_extra("7", "integer") == 7


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        ("65", "integer", 65),
        ("65.0", "integer", None),
        ('"65"', "integer", None),
        ("0.029", "float", 0.029),
        ('"0.029"', "float", None),
        ("1", "float", 1.0),
        ("[210, 230]", "integer_range", (210, 230)),
        ("[6, 8]", "float_range", (6.0, 8.0)),
        ("[6.5, 8]", "float_range", (6.5, 8.0)),
        ("[1, 2, 3]", "integer_range", None),
        ("true", "integer", None),
        ("NaN", "float", None),
        ("Infinity", "float", None),
        ('"abc"', "float", None),
        (None, "float", None),
        (7, "integer", None),
    ],
)
def test_parse_extra(raw: object, kind: Any, expected: object) -> None:
    assert parse_extra(raw, kind) == expected


def test_configured_keys_are_used() -> None:
    payload = _full()
    payload["filament"]["extra"]["pa_custom"] = "0.044"
    del payload["extra"]
    keys = KEYS._replace(pressure_advance="pa_custom")
    assert _build(payload, keys=keys).pressure_advance == pytest.approx(0.044)


def test_empty_key_reads_nothing() -> None:
    payload = _full()
    payload["extra"][""] = "0.5"
    payload["filament"]["extra"][""] = "0.5"
    keys = KEYS._replace(pressure_advance="", nozzle="")
    swatch = _build(payload, keys=keys)
    assert swatch.pressure_advance is None
    assert swatch.nozzle_c == (235, 235)


def test_key_with_control_characters_is_logged_clean(caplog: pytest.LogCaptureFixture) -> None:
    payload = _full()
    payload["extra"]["pa\x1b[31m"] = "[1"
    keys = KEYS._replace(pressure_advance="pa\x1b[31m")
    with caplog.at_level(logging.DEBUG, logger="app.integrations.spoolman.swatch"):
        _build(payload, keys=keys)
    assert any("pa[31m" in r.getMessage() for r in caplog.records)
    assert "\x1b" not in caplog.text


def test_opened_date_uses_the_hub_time_zone() -> None:
    payload = _full()
    payload["first_used"] = "2026-11-02T23:30:00Z"
    assert _build(payload, time_zone="Europe/Berlin").opened == "2026-11-03"
    assert _build(payload, time_zone="UTC").opened == "2026-11-02"


def test_naive_first_used_counts_as_utc() -> None:
    payload = _full()
    payload["first_used"] = "2026-11-02T23:30:00"
    assert _build(payload, time_zone="Europe/Berlin").opened == "2026-11-03"


def test_unknown_time_zone_falls_back_to_utc() -> None:
    payload = _full()
    payload["first_used"] = "2026-11-02T23:30:00Z"
    assert _build(payload, time_zone="Nowhere/Land").opened == "2026-11-02"


def test_out_of_range_values_are_left_out() -> None:
    payload = _full()
    payload["filament"]["settings_bed_temp"] = 900
    payload["spool_weight"] = -5
    del payload["filament"]["spool_weight"]
    swatch = _build(payload)
    assert swatch.bed_c is None
    assert swatch.spool_weight_g is None
    assert swatch.nozzle_c == (220, 240)


def test_long_text_is_cut_to_64() -> None:
    payload = _full()
    payload["location"] = "L" * 200
    payload["filament"]["vendor"]["name"] = "V" * 70
    swatch = _build(payload)
    assert swatch.location == "L" * 64
    assert swatch.vendor == "V" * 64


def test_remaining_weight_and_price_are_never_read() -> None:
    payload = _full()
    swatch = _build(payload)
    dumped = json.dumps(swatch.model_dump())
    assert "850" not in dumped
    assert "24.5" not in dumped
    assert "19.99" not in dumped
    other = copy.deepcopy(payload)
    other["remaining_weight"] = 1
    other["price"] = 1
    other["used_weight"] = 1
    assert _build(other) == swatch


def test_build_swatch_never_raises_on_garbage() -> None:
    assert _build({"id": "x"}) is None
    assert _build({}) is None
    assert _build({"id": 3, "filament": "nope", "extra": []}) is not None


def test_language_is_stored() -> None:
    assert _build(_full(), language="de").language == "de"


@pytest.mark.parametrize(
    ("key", "raw", "field"),
    [
        ("nozzle_temperature", "[240, 220]", "nozzle_c"),
        ("drying_condiftions_time", "[8, 6]", "drying_h"),
    ],
)
def test_reversed_range_drops_only_its_row(key: str, raw: str, field: str) -> None:
    """Review I1: Spoolman lets a range run high to low; only that row goes, never the label."""
    payload = _full()
    payload["filament"]["extra"][key] = raw
    swatch = _build(payload)
    assert swatch is not None
    assert getattr(swatch, field) is None
    assert swatch.bed_c == 80
    assert swatch.pressure_advance == pytest.approx(0.029)
    assert swatch.drying_c == 65
    assert swatch.location == "Shelf A2"
    if field == "nozzle_c":
        assert swatch.drying_h == (6.0, 8.0)
    else:
        assert swatch.nozzle_c == (220, 240)
