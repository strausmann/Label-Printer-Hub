# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Spoolman spool payload -> ``SpoolSwatch`` (#346, R-346-3 to R-346-5).

Each field is read and validated on its own: a bad field drops only its own row, never the
label. Plain fields are coerced defensively (a number where a number belongs, a string where a
string belongs, an object where an object belongs). Extra-field values are JSON text: longer
than ``EXTRA_RAW_MAX`` characters is dropped before parsing, every parser error is caught, and a
value is taken only in the shape of its field type. A dropped field is logged at DEBUG with its
name or configured key, never its value. ``build_swatch`` never raises.

Remaining weight, used weight and price are never read: they change, and the QR leads to the
live values.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import zoneinfo
from collections.abc import Callable, Mapping
from typing import Any, Final, Literal, NamedTuple

from pydantic import ValidationError

from app.schemas.spool_swatch import SWATCH_HEXES_MAX, SWATCH_TEXT_MAX, SpoolSwatch
from app.sheets.text import log_value, sanitise_text

_log = logging.getLogger(__name__)

EXTRA_RAW_MAX: Final = 1024
"""Longest extra-field value (characters) that is parsed at all."""

ExtraKind = Literal["integer", "float", "integer_range", "float_range"]
ExtraValue = int | float | tuple[int, int] | tuple[float, float]


class SwatchKeys(NamedTuple):
    """The configurable extra-field keys (settings ``integrations.spoolman.label.*``)."""

    nozzle: str
    pressure_advance: str
    flow_ratio: str
    drying_temp: str
    drying_time: str


DEFAULT_SWATCH_KEYS: Final = SwatchKeys(
    nozzle="nozzle_temperature",
    pressure_advance="flowdynamics",
    flow_ratio="flowrate",
    drying_temp="drying_condiftions_temp",  # Spoolman's spelling
    drying_time="drying_condiftions_time",
)


def _number(value: object, *, integer: bool) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if integer:
        return value if isinstance(value, int) else None
    return float(value)


def parse_extra(raw: object, kind: ExtraKind) -> ExtraValue | None:
    """One extra-field value (JSON text) in the shape of ``kind``, else ``None``.

    A range with one ``null`` end is the other end twice. Never raises.
    """
    if not isinstance(raw, str) or len(raw) > EXTRA_RAW_MAX:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        return None
    integer = kind in ("integer", "integer_range")
    if kind in ("integer", "float"):
        return _number(value, integer=integer)
    if not isinstance(value, list) or len(value) != 2:
        return None
    low, high = (None if v is None else _number(v, integer=integer) for v in value)
    if (value[0] is not None and low is None) or (value[1] is not None and high is None):
        return None
    if low is None and high is None:
        return None
    low = high if low is None else low
    high = low if high is None else high
    return (low, high)  # type: ignore[return-value]


def _obj(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        cleaned = sanitise_text(value[: 4 * SWATCH_TEXT_MAX], max_len=4 * SWATCH_TEXT_MAX)
    except ValueError:
        return None
    cleaned = cleaned[:SWATCH_TEXT_MAX].strip()
    return cleaned or None


def _hexes(filament: Mapping[str, Any]) -> tuple[str, ...]:
    multi = filament.get("multi_color_hexes")
    raw = multi if isinstance(multi, str) and multi.strip() else filament.get("color_hex")
    if not isinstance(raw, str):
        return ()
    codes: list[str] = []
    for part in raw.split(",")[: 4 * SWATCH_HEXES_MAX]:
        code = part.strip().removeprefix("#").upper()
        if len(code) == 8:
            code = code[:6]
        if len(code) == 6 and all(c in "0123456789ABCDEF" for c in code):
            codes.append(code)
    return tuple(codes[:SWATCH_HEXES_MAX])


def _opened(value: object, time_zone: str) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)  # Spoolman without an offset: UTC
    try:
        zone: dt.tzinfo = zoneinfo.ZoneInfo(time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        zone = dt.UTC
    return moment.astimezone(zone).date().isoformat()


class _Reader:
    """Reads one spool payload; every lookup is guarded and logs only names."""

    def __init__(self, spool_id: int, payload: Mapping[str, Any]) -> None:
        self.spool_id = spool_id
        self.spool = payload
        self.filament = _obj(payload.get("filament"))

    def drop(self, name: str) -> None:
        _log.debug("Spoolman spool %s: field %s left out", self.spool_id, log_value(name))

    def extra(self, owner: Mapping[str, Any], key: str, kind: ExtraKind) -> ExtraValue | None:
        if not key:
            return None
        extra = _obj(owner.get("extra"))
        if key not in extra:
            return None
        value = parse_extra(extra[key], kind)
        if value is None:
            self.drop(key)
        return value

    def extra_first(self, key: str, kind: ExtraKind) -> ExtraValue | None:
        """Spool extra first, then the filament's."""
        spool = self.extra(self.spool, key, kind)
        return spool if spool is not None else self.extra(self.filament, key, kind)

    def plain(self, owner: Mapping[str, Any], name: str, *, integer: bool) -> int | float | None:
        if name not in owner or owner[name] is None:
            return None
        value = _number(owner[name], integer=integer)
        if value is None:
            self.drop(name)
        return value


def _guard[T](reader: _Reader, name: str, read: Callable[[], T]) -> T | None:
    try:
        return read()
    except Exception:
        reader.drop(name)
        return None


def _in_range(value: Any, low: float, high: float) -> Any:
    if value is None:
        return None
    parts = value if isinstance(value, tuple) else (value,)
    return value if all(low <= p <= high for p in parts) else None


def build_swatch(
    payload: Mapping[str, Any],
    *,
    keys: SwatchKeys,
    title_source: Literal["material", "name"],
    language: str,
    time_zone: str,
) -> SpoolSwatch | None:
    """The swatch data of one spool, or ``None`` if not even the id is usable. Never raises."""
    try:
        return _build(payload, keys, title_source, language, time_zone)
    except Exception as exc:
        spool_id = payload.get("id") if isinstance(payload, Mapping) else None
        _log.info(
            "Spoolman spool %s: swatch not built (%s)", log_value(spool_id), type(exc).__name__
        )
        return None


def _build(
    payload: Mapping[str, Any],
    keys: SwatchKeys,
    title_source: Literal["material", "name"],
    language: str,
    time_zone: str,
) -> SpoolSwatch | None:
    spool_id = payload.get("id")
    if isinstance(spool_id, bool) or not isinstance(spool_id, int) or spool_id < 1:
        return None
    r = _Reader(spool_id, payload)
    fil = r.filament
    fields: dict[str, Any] = {}

    def put(name: str, read: Callable[[], Any], low: float | None = None, high: float = 0) -> None:
        value = _guard(r, name, read)
        if value is not None and low is not None and _in_range(value, low, high) is None:
            r.drop(name)
            value = None
        if value is not None:
            fields[name] = value

    def vendor() -> str | None:
        found = fil.get("vendor")
        # An object is expected; anything else raises here and the guard drops the field.
        return None if found is None else _text(found.get("name"))

    put("vendor", vendor)
    material = _guard(r, "material", lambda: _text(fil.get("material")))
    name = _guard(r, "name", lambda: _text(fil.get("name")))
    bar, line = (material, name) if title_source == "material" else (name, material)
    if bar is not None:
        fields["title"] = bar
    if line is not None and line != bar:
        fields["color_name"] = line
    put("location", lambda: _text(payload.get("location")))
    put("lot", lambda: _text(payload.get("lot_nr")))
    put("color_hexes", lambda: _hexes(fil) or None)

    def nozzle() -> Any:
        if keys.nozzle and keys.nozzle in _obj(fil.get("extra")):
            return r.extra(fil, keys.nozzle, "integer_range")  # set but unusable: no row
        temp = r.plain(fil, "settings_extruder_temp", integer=True)
        return None if temp is None else (temp, temp)

    put("nozzle_c", nozzle, 0, 600)
    put("bed_c", lambda: r.plain(fil, "settings_bed_temp", integer=True), 0, 600)
    put("pressure_advance", lambda: r.extra_first(keys.pressure_advance, "float"), 0, 10)
    put("flow_ratio", lambda: r.extra_first(keys.flow_ratio, "float"), 0, 10)
    put("drying_c", lambda: r.extra(fil, keys.drying_temp, "integer"), 0, 600)
    put("drying_h", lambda: r.extra(fil, keys.drying_time, "float_range"), 0, 1000)

    def weight(spool_name: str, filament_name: str) -> Any:
        found = r.plain(payload, spool_name, integer=False)
        return found if found is not None else r.plain(fil, filament_name, integer=False)

    put("spool_weight_g", lambda: weight("spool_weight", "spool_weight"), 0, 100_000)
    put("net_weight_g", lambda: weight("initial_weight", "weight"), 0, 100_000)
    put("diameter_mm", lambda: r.plain(fil, "diameter", integer=False), 0, 10)
    put("density_g_cm3", lambda: r.plain(fil, "density", integer=False), 0, 30)
    put("opened", lambda: _opened(payload.get("first_used"), time_zone))

    fields["language"] = language if language in ("en", "de") else "en"
    try:
        return SpoolSwatch(spool_id=spool_id, **fields)
    except ValidationError as exc:
        _log.info("Spoolman spool %s: swatch not built (%s)", spool_id, type(exc).__name__)
        return None
