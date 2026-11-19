# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The data of the swatch-style Spoolman spool label (#346, R-346-4).

One frozen model with bounded fields. The Spoolman plugin fills it at lookup
(``integrations/spoolman/swatch.py``), the raw API accepts it as ``data.swatch``, and a stored
job keeps it in its payload, so a re-render prints the same words. Everything here is plain
JSON: the opened date is ISO text, not a ``date`` object (the tape job payload is a JSON
column).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.sheets.text import sanitise_text

SWATCH_TEXT_MAX = 64
SWATCH_HEXES_MAX = 16

_HEX = re.compile(r"[0-9A-F]{6}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _text(value: str) -> str:
    return sanitise_text(value, max_len=SWATCH_TEXT_MAX)


def _hex(value: str) -> str:
    code = value.strip().removeprefix("#").upper()
    if len(code) == 8:  # RRGGBBAA: the alpha does not print
        code = code[:6]
    if not _HEX.fullmatch(code):
        raise ValueError("a colour is six hex digits (RRGGBB)")
    return code


def _date(value: str) -> str:
    if not _DATE.fullmatch(value):
        raise ValueError("the opened date is YYYY-MM-DD")
    dt.date.fromisoformat(value)  # refuses 2026-02-30
    return value


_Text = Annotated[str, AfterValidator(_text)]
_Hex = Annotated[str, AfterValidator(_hex)]
_Temp = Annotated[int, Field(ge=0, le=600)]
_Hours = Annotated[float, Field(ge=0, le=1000)]
_Factor = Annotated[float, Field(ge=0, le=10)]
_Grams = Annotated[float, Field(ge=0, le=100_000)]


class SpoolSwatch(BaseModel):
    """What the swatch label prints for one spool; every field but the id is optional."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    spool_id: int = Field(ge=1)
    language: Literal["en", "de"] = "en"
    vendor: _Text | None = None
    title: _Text | None = None
    """Text on the black bar (the material by default)."""
    color_name: _Text | None = None
    """The colour line under the bar (the filament name by default)."""
    location: _Text | None = None
    lot: _Text | None = None
    color_hexes: tuple[_Hex, ...] = Field(default=(), max_length=SWATCH_HEXES_MAX)
    nozzle_c: tuple[_Temp, _Temp] | None = None
    bed_c: _Temp | None = None
    drying_c: _Temp | None = None
    drying_h: tuple[_Hours, _Hours] | None = None
    pressure_advance: _Factor | None = None
    flow_ratio: _Factor | None = None
    spool_weight_g: _Grams | None = None
    net_weight_g: _Grams | None = None
    diameter_mm: Annotated[float, Field(ge=0, le=10)] | None = None
    density_g_cm3: Annotated[float, Field(ge=0, le=30)] | None = None
    opened: Annotated[str, AfterValidator(_date)] | None = None

    @model_validator(mode="after")
    def _ranges_ascend(self) -> Self:
        for name in ("nozzle_c", "drying_h"):
            pair = getattr(self, name)
            if pair is not None and pair[0] > pair[1]:
                raise ValueError(f"{name}: the low end is above the high end")
        return self
