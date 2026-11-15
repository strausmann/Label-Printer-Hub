# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Printer attributes → probe summary and hub status (spec 11.1, 11.3). Pure, no I/O.

Everything here reads an answer from a device on the network, so none of it may
trust that answer. The rules, applied to every attribute alike:

* A value of the wrong type (text where numbers belong, a collection where a
  keyword belongs, a boolean where an integer belongs) is skipped. Out-of-band
  values (``no-value``, ``unsupported``) mean "nothing" and are skipped quietly.
* Every list is cut to ``MAX_ENTRIES`` entries and every string to
  ``MAX_TEXT`` characters; keywords with control characters or over the length
  limit are dropped. Printer-controlled content in the result is therefore
  bounded no matter what was sent.
* Mapping never raises. What cannot be understood is left out, and the oddity is
  logged **once per process** at WARNING (``_warn_once``): attribute name and
  kind of anomaly only, never a value, never the printer's address.
* Membership questions ("does the printer list ``application/pdf``?") scan every
  value the codec delivered, not the cut-down list, so a long
  ``job-creation-attributes-supported`` cannot hide ``media-col`` behind the cut.

Whether the printer honours an attribute cannot be learned from Validate-Job or
a successful Print-Job (status ``successful-ok-ignored-or-substituted-attributes``
is success, see the interop note); the questions the hub has are answered from
this summary.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from app.printer_backends.ipp.codec import Collection, OutOfBand, Range, Resolution, Value

logger = logging.getLogger(__name__)

PRINTER_ATTRS: tuple[str, ...] = (
    "printer-make-and-model",
    "printer-uuid",  # hardware identity (#231); read by the status producer, not mapped
    "ipp-versions-supported",
    "document-format-supported",
    "document-format-version-supported",
    "printer-resolution-supported",
    "media-supported",
    "media-default",
    "media-size-supported",
    "media-type-supported",
    "media-source-supported",
    "media-col-supported",
    "job-creation-attributes-supported",
    "printer-is-accepting-jobs",
    "media-col-ready",
    "media-ready",
    "print-color-mode-supported",
    "print-scaling-supported",
    "sides-supported",
    "media-top-margin-supported",
    "media-bottom-margin-supported",
    "media-left-margin-supported",
    "media-right-margin-supported",
    "printer-state",
    "printer-state-reasons",
    "marker-names",
    "marker-colors",
    "marker-levels",
    "marker-low-levels",
    "marker-types",
    "queued-job-count",
)
"""Requested with Get-Printer-Attributes by the probe and the status producer."""

MAX_ENTRIES = 64
"""Most entries of any list in a result (spec: printer-controlled content is bounded)."""

MAX_TEXT = 120
"""Longest string in a result; a longer name is cut, a longer keyword is dropped."""

MAX_REASONS = 32
"""Most state reasons kept."""

_REASON = re.compile(r"[a-z0-9-]{1,64}")
_SUFFIXES: tuple[tuple[str, Literal["report", "warning", "error"]], ...] = (
    ("-report", "report"),
    ("-warning", "warning"),
    ("-error", "error"),
)
# Spec 11.3: low supplies are shown, never blocking. Without a suffix they would count
# as errors (OC-20), so these four are the exception.
_LOW_SUPPLY = frozenset({"toner-low", "marker-supply-low", "media-low", "developer-low"})
_LOW_REASONS = frozenset({"toner-low", "marker-supply-low"})
_EMPTY_REASONS = frozenset({"toner-empty", "marker-supply-empty"})
_STATES: dict[int, Literal["idle", "printing", "stopped"]] = {
    3: "idle",
    4: "printing",
    5: "stopped",
}
_DPCM_TO_DPI = 2.54
_SOME_REMAINING = -3
_MAX_REASON_LENGTH = 64


# ---------------------------------------------------------------------------- models


class Margins(BaseModel):
    """Smallest unprintable margin per side, hundredths of mm."""

    top: int
    left: int
    bottom: int
    right: int


class ProbeSummary(BaseModel):
    """What "Read printer" shows (spec 11.1) and what Print-Job attributes are chosen from."""

    make_and_model: str | None
    ipp_versions: list[str]
    pdf_supported: bool
    pdf_versions: list[str]
    resolutions_dpi: list[int]
    media_sizes: list[str]
    media_default: str | None = None
    media_types: list[str]
    media_sources: list[str]
    color_modes: list[str]
    margins_hmm: Margins | None
    media_col_supported: bool
    media_col_members: list[str]
    accepting_jobs: bool | None
    scaling_none_supported: bool
    monochrome_supported: bool
    one_sided_supported: bool
    state: str


class Reason(BaseModel):
    """One ``printer-state-reasons`` keyword without its severity suffix."""

    keyword: str
    severity: Literal["report", "warning", "error"]
    blocking: bool


class Marker(BaseModel):
    """One supply (toner, ink, waste container)."""

    name: str
    color: str | None
    type: str | None
    level_percent: int | None
    some_remaining: bool
    low: bool
    empty: bool


class TrayLoad(BaseModel):
    """One media source and what the printer says is loaded in it.

    ``ready`` is true only when the printer reported media for this tray; ``False`` with
    ``media=None`` also covers "not reported" (printers that only send ``media-ready``,
    which names no tray, cannot be assigned to one of several trays).
    """

    key: str
    media: str | None
    ready: bool


class IppStatusRecord(BaseModel):
    """The mapped status of a page printer (written to ``printer_status_cache.parsed``)."""

    kind: Literal["page"] = "page"
    online: bool
    printer_state: Literal["idle", "printing", "stopped"]
    reasons: list[Reason]
    blocking_reason: str | None
    warnings: list[str]
    markers: list[Marker]
    trays: list[TrayLoad]
    jobs_ahead: int | None
    summary: ProbeSummary


# ---------------------------------------------------------------------------- logging


@functools.cache
def _warn_once(attribute: str, anomaly: str) -> None:
    """Log one WARNING per ``(attribute, anomaly)`` and process; the cache is the memory.

    Both arguments must come from this module, never from the printer: the cache keeps them
    for the life of the process.
    """
    logger.warning("ipp printer attribute anomaly: %s (%s)", attribute, anomaly)


# ---------------------------------------------------------------------------- readers


def _is_int(value: Value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _usable_text(value: str) -> bool:
    return len(value) <= MAX_TEXT and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _cut(value: str) -> str:
    return "".join(c for c in value[:MAX_TEXT] if ord(c) >= 32 and ord(c) != 127)


def _strings(attrs: Mapping[str, list[Value]], name: str) -> list[str]:
    """Usable string values of ``name``: at most ``MAX_ENTRIES``, keywords over the length
    limit or with control characters dropped."""
    out: list[str] = []
    for value in attrs.get(name, []):
        if isinstance(value, OutOfBand):
            continue
        if not isinstance(value, str):
            _warn_once(name, "wrong-type")
            continue
        if not _usable_text(value):
            _warn_once(name, "unusable-text")
            continue
        if len(out) == MAX_ENTRIES:
            _warn_once(name, "too-many-values")
            break
        out.append(value)
    return out


def _contains(attrs: Mapping[str, list[Value]], name: str, wanted: str) -> bool:
    """Whether any string value of ``name`` equals ``wanted`` (case-insensitive, uncut)."""
    wanted = wanted.lower()
    return any(isinstance(v, str) and v.lower() == wanted for v in attrs.get(name, []))


def _lists_anything(attrs: Mapping[str, list[Value]], name: str) -> bool:
    return any(isinstance(v, str) for v in attrs.get(name, []))


def _first_int(attrs: Mapping[str, list[Value]], name: str) -> int | None:
    values = attrs.get(name, [])
    if not values or isinstance(values[0], OutOfBand):
        return None
    first = values[0]
    if isinstance(first, int) and not isinstance(first, bool):
        return first
    _warn_once(name, "wrong-type")
    return None


def _first_text(attrs: Mapping[str, list[Value]], name: str) -> str | None:
    values = attrs.get(name, [])
    if not values or isinstance(values[0], OutOfBand):
        return None
    if isinstance(values[0], str):
        return _cut(values[0]) or None
    _warn_once(name, "wrong-type")
    return None


def _state_name(attrs: Mapping[str, list[Value]]) -> Literal["idle", "printing", "stopped"] | None:
    """The ``printer-state`` as the hub names it, ``None`` when missing or not 3/4/5."""
    values = attrs.get("printer-state")
    if not values or isinstance(values[0], OutOfBand):
        _warn_once("printer-state", "missing")
        return None
    value = values[0]
    if not _is_int(value):
        _warn_once("printer-state", "wrong-type")
        return None
    state = _STATES.get(value) if isinstance(value, int) else None
    if state is None:
        _warn_once("printer-state", "unknown-value")
    return state


def _resolutions(attrs: Mapping[str, list[Value]]) -> list[int]:
    found: set[int] = set()
    for value in attrs.get("printer-resolution-supported", []):
        if isinstance(value, OutOfBand):
            continue
        if not isinstance(value, Resolution) or value.x <= 0 or value.units not in (3, 4):
            _warn_once("printer-resolution-supported", "unusable-value")
            continue
        found.add(value.x if value.units == 3 else round(value.x * _DPCM_TO_DPI))
    return sorted(found, reverse=True)[:MAX_ENTRIES]


def _margin(attrs: Mapping[str, list[Value]], side: str) -> int | None:
    name = f"media-{side}-margin-supported"
    best: int | None = None
    for value in attrs.get(name, []):
        if isinstance(value, OutOfBand):
            continue
        candidate = value.lower if isinstance(value, Range) else value
        if not (isinstance(candidate, int) and not isinstance(candidate, bool)) or candidate < 0:
            _warn_once(name, "unusable-value")
            continue
        best = candidate if best is None else min(best, candidate)
    return best


def _margins(attrs: Mapping[str, list[Value]]) -> Margins | None:
    top, left, bottom, right = (_margin(attrs, s) for s in ("top", "left", "bottom", "right"))
    if top is None or left is None or bottom is None or right is None:
        return None
    return Margins(top=top, left=left, bottom=bottom, right=right)


def _accepting(attrs: Mapping[str, list[Value]]) -> bool | None:
    values = attrs.get("printer-is-accepting-jobs", [])
    if not values or isinstance(values[0], OutOfBand):
        return None
    if isinstance(values[0], bool):
        return values[0]
    _warn_once("printer-is-accepting-jobs", "wrong-type")
    return None


def _media_col_supported(attrs: Mapping[str, list[Value]]) -> bool:
    """OC-19: ``media-col`` is accepted when ``job-creation-attributes-supported`` lists it;
    when the printer lists no creation attributes at all, when ``media-col-supported`` (the
    collection's members, PWG 5100.7) lists ``media-size``."""
    if _lists_anything(attrs, "job-creation-attributes-supported"):
        return _contains(attrs, "job-creation-attributes-supported", "media-col")
    return _contains(attrs, "media-col-supported", "media-size")


# ---------------------------------------------------------------------------- summarise


def summarise(attrs: Mapping[str, list[Value]]) -> ProbeSummary:
    """The probe summary of a Get-Printer-Attributes answer. Never raises."""
    state = _state_name(attrs)
    return ProbeSummary(
        make_and_model=_first_text(attrs, "printer-make-and-model"),
        ipp_versions=_strings(attrs, "ipp-versions-supported"),
        pdf_supported=_contains(attrs, "document-format-supported", "application/pdf"),
        pdf_versions=_strings(attrs, "document-format-version-supported"),
        resolutions_dpi=_resolutions(attrs),
        media_sizes=_strings(attrs, "media-supported"),
        media_default=_first_text(attrs, "media-default"),
        media_types=_strings(attrs, "media-type-supported"),
        media_sources=_strings(attrs, "media-source-supported"),
        color_modes=_strings(attrs, "print-color-mode-supported"),
        margins_hmm=_margins(attrs),
        media_col_supported=_media_col_supported(attrs),
        media_col_members=_strings(attrs, "media-col-supported"),
        accepting_jobs=_accepting(attrs),
        scaling_none_supported=_contains(attrs, "print-scaling-supported", "none"),
        monochrome_supported=_contains(attrs, "print-color-mode-supported", "monochrome"),
        one_sided_supported=_contains(attrs, "sides-supported", "one-sided"),
        state=state if state is not None else "unknown",
    )


# ---------------------------------------------------------------------------- map_status


def reason_keyword(value: str) -> str | None:
    """A state-reason keyword as it may be shown or published: lower-cased, ``[a-z0-9-]``,
    at most 64 characters; anything else is printer-controlled text and gives ``None``.

    The one filter for printer reasons and job reasons (spec 18: printer text does not
    reach the job record or the event stream).
    """
    value = value.lower() if len(value) <= _MAX_REASON_LENGTH else value
    return value if _REASON.fullmatch(value) is not None else None


def _reasons(attrs: Mapping[str, list[Value]]) -> list[Reason]:
    """Every valid reason in wire order. Not cut: the blocking decision is made over all of
    them (the codec already bounds the count); only the display list is cut."""
    out: list[Reason] = []
    for value in attrs.get("printer-state-reasons", []):
        if isinstance(value, OutOfBand):
            continue
        if not isinstance(value, str):
            _warn_once("printer-state-reasons", "wrong-type")
            continue
        keyword = reason_keyword(value)
        if keyword is None:
            _warn_once("printer-state-reasons", "unusable-keyword")
            continue
        value = keyword
        if value == "none":
            continue
        base, severity = value, None
        for suffix, name in _SUFFIXES:
            if value.endswith(suffix):
                base, severity = value[: -len(suffix)], name
                break
        if not base:
            _warn_once("printer-state-reasons", "unusable-keyword")
            continue
        if severity is None:
            severity = "warning" if base in _LOW_SUPPLY else "error"  # OC-20
        # Only severity "error" blocks (RFC 8011 4.4.12: "-warning" and "-report" leave the printer
        # working), a bare keyword counts as an error (OC-20) except the low supplies. An explicit
        # "-error" blocks also "toner-low-error" (spec 11.3). Blocking only keeps a job queued.
        out.append(
            Reason(
                keyword=base,
                severity=severity,
                blocking=severity == "error",
            )
        )
    return out


def _text_column(attrs: Mapping[str, list[Value]], name: str) -> list[str | None] | None:
    """One text ``marker-*`` list, index-aligned (an unusable entry is ``None``); ``None``
    when the attribute is absent or holds no usable entry."""
    out: list[str | None] = []
    for value in attrs.get(name, [])[:MAX_ENTRIES]:
        if isinstance(value, str):
            out.append(_cut(value) or None)
        else:
            if not isinstance(value, OutOfBand):
                _warn_once(name, "wrong-type")
            out.append(None)
    return None if all(v is None for v in out) else out


def _int_column(attrs: Mapping[str, list[Value]], name: str) -> list[int | None] | None:
    """Like ``_text_column`` for integer lists."""
    out: list[int | None] = []
    for value in attrs.get(name, [])[:MAX_ENTRIES]:
        if isinstance(value, int) and not isinstance(value, bool):
            out.append(value)
        else:
            if not isinstance(value, OutOfBand):
                _warn_once(name, "wrong-type")
            out.append(None)
    return None if all(v is None for v in out) else out


def _is_waste(name: str | None, kind: str | None) -> bool:
    return any("waste" in (text or "").lower() for text in (name, kind))


def _markers(attrs: Mapping[str, list[Value]], reasons: list[Reason]) -> list[Marker]:
    names = _text_column(attrs, "marker-names")
    colors = _text_column(attrs, "marker-colors")
    types = _text_column(attrs, "marker-types")
    levels = _int_column(attrs, "marker-levels")
    lows = _int_column(attrs, "marker-low-levels")
    present = [c for c in (names, colors, types, levels, lows) if c is not None]
    if not present:
        return []
    keywords = {r.keyword for r in reasons}
    reason_low = bool(keywords & _LOW_REASONS)
    reason_empty = bool(keywords & _EMPTY_REASONS)
    count = min(len(c) for c in present)

    def at(column: list[str | None] | None, i: int) -> str | None:
        return column[i] if column is not None and i < len(column) else None

    def level_at(i: int) -> int | None:
        return levels[i] if levels is not None and i < len(levels) else None

    supplies = sum(1 for i in range(count) if not _is_waste(at(names, i), at(types, i)))
    out: list[Marker] = []
    for i in range(count):
        name, kind = at(names, i), at(types, i)
        level = level_at(i)
        low_level = lows[i] if lows is not None and i < len(lows) else None
        percent = level if level is not None and 0 <= level <= 100 else None
        if level is not None and level > 100:
            _warn_once("marker-levels", "out-of-range")
        # A printer-wide reason names no marker. It is applied to a supply whose own level is
        # unknown, or to the only supply; a known level wins, waste containers are never marked.
        by_reason = not _is_waste(name, kind) and (percent is None or supplies == 1)
        out.append(
            Marker(
                name=name or f"marker-{i + 1}",
                color=at(colors, i),
                type=kind,
                level_percent=percent,
                some_remaining=level == _SOME_REMAINING,
                low=(by_reason and reason_low)
                or (percent is not None and low_level is not None and percent <= low_level),
                empty=(by_reason and reason_empty) or percent == 0,
            )
        )
    return out


def _media_description(col: Collection) -> str | None:
    key = _member_text(col, "media-key")
    if key is not None:
        return key
    sizes = col.members.get("media-size", [])
    if not sizes or not isinstance(sizes[0], Collection):
        return None
    x = sizes[0].members.get("x-dimension", [None])[0]
    y = sizes[0].members.get("y-dimension", [None])[0]
    if (
        not (isinstance(x, int) and isinstance(y, int))
        or isinstance(x, bool)
        or isinstance(y, bool)
    ):
        return None
    kind = _member_text(col, "media-type")
    return f"{x}x{y} {kind}" if kind else f"{x}x{y}"


def _member_text(col: Collection, member: str) -> str | None:
    values = col.members.get(member, [])
    if values and isinstance(values[0], str) and _usable_text(values[0]):
        return values[0]
    return None


def _trays(attrs: Mapping[str, list[Value]]) -> list[TrayLoad]:
    keys = list(dict.fromkeys(_strings(attrs, "media-source-supported")))
    if not keys:
        return []
    loaded: dict[str, str | None] = {}
    for value in attrs.get("media-col-ready", [])[:MAX_ENTRIES]:
        if isinstance(value, OutOfBand):
            continue
        if not isinstance(value, Collection):
            _warn_once("media-col-ready", "wrong-type")
            continue
        source = _member_text(value, "media-source")
        if source is not None:
            loaded.setdefault(source, _media_description(value))
    if not loaded:
        ready = _strings(attrs, "media-ready")
        if len(keys) == 1 and ready:
            loaded[keys[0]] = ready[0]
    return [TrayLoad(key=k, media=loaded.get(k), ready=k in loaded) for k in keys]


def map_status(attrs: Mapping[str, list[Value]]) -> IppStatusRecord:
    """Map a Get-Printer-Attributes answer to the hub's page-printer status. Never raises.

    An answer exists, so ``online`` is true; a failed request is the caller's ``online=false``.
    """
    state = _state_name(attrs)
    reasons = _reasons(attrs)
    if state is None:
        reasons.insert(0, Reason(keyword="unknown-state", severity="error", blocking=True))
    blocking = next((r.keyword for r in reasons if r.blocking), None)
    # Decided over all reasons above; only the displayed list is cut, blockers first.
    shown = sorted(reasons, key=lambda r: not r.blocking)[:MAX_REASONS]
    jobs = _first_int(attrs, "queued-job-count")
    return IppStatusRecord(
        online=True,
        printer_state=state or "stopped",
        reasons=shown,
        blocking_reason=blocking,
        warnings=list(dict.fromkeys(r.keyword for r in reasons if r.severity == "warning"))[
            :MAX_REASONS
        ],
        markers=_markers(attrs, reasons),
        trays=_trays(attrs),
        jobs_ahead=jobs if jobs is not None and jobs >= 0 else None,
        summary=summarise(attrs),
    )
