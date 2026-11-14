# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The QL layout bounds its work and its image size, whatever the text (#258 security review).

Label data does not only come from the request schema (which caps lengths): integration
lookups return whatever the upstream system holds. The renderer must therefore bound the text
measuring work and never allocate an image beyond a documented maximum length.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from app.printer_backends.exceptions import QrPayloadTooLongError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_data_item import LabelDataItem
from app.schemas.label_layout import LabelOrientation, QlLayoutPreset
from app.schemas.print_request import PrintRequest, RawLabelData, RawListingItem
from app.services import ql_layout
from app.services.layout_engine import LayoutEngine
from PIL import ImageFont
from pydantic import ValidationError

_QR = "https://example.invalid/hardware/19"
_MEASURE_BUDGET = 700
"""Upper bound of font metric calls (``getlength`` + ``getbbox`` + ``font_variant``) for one
label. The bounded layout needs at most about 630 for the worst schema-allowed label; the
unbounded code needed hundreds of thousands, and the 1st-review layout about 15 000 (I1)."""
_METRIC_CALLS = ("getlength", "getbbox", "font_variant")
_BBOX_BUDGET = 60
"""``getbbox`` calls for one label: once per laid-out line plus one cap height per font
(at most 52 for the worst label). Without the line-metric cache it is 70-250."""


@pytest.fixture
def measured(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Counts every font metric call, not only ``getlength`` (review I1).

    ``measured[0]``: all metric calls; ``measured[1]``: ``getbbox`` alone.
    """
    calls = [0, 0]

    def counting(real: Callable[..., Any], name: str) -> Callable[..., Any]:
        def wrapper(self: ImageFont.FreeTypeFont, *args: Any, **kwargs: Any) -> Any:
            calls[0] += 1
            if name == "getbbox":
                calls[1] += 1
            return real(self, *args, **kwargs)

        return wrapper

    for name in _METRIC_CALLS:
        monkeypatch.setattr(
            ImageFont.FreeTypeFont, name, counting(getattr(ImageFont.FreeTypeFont, name), name)
        )
    yield calls


def _worst_schema_label() -> LabelData:
    """Every free text at the request caps: 512-char id and title, 10 secondary lines and
    100 listing rows of 510 chars (words, so the wrapping path runs)."""
    words = ("word " * 103)[:510]
    raw = RawLabelData(
        primary_id="P" * 512,
        title=("word " * 103)[:512],
        qr_payload="https://example.invalid/" + "a" * 90,
        secondary=tuple(words for _ in range(10)),
        items=tuple(RawListingItem(item=words) for _ in range(100)),
    )
    return LabelData(source_app="manual", **raw.model_dump())


_WORST_CASES = (
    [(ContentType.QR_WITH_LISTING, LabelOrientation.ACROSS, preset) for preset in QlLayoutPreset]
    + [(ContentType.QR_THREE_LINES, LabelOrientation.ACROSS, preset) for preset in QlLayoutPreset]
    + [
        (ContentType.QR_WITH_LISTING, LabelOrientation.ALONG, None),
        (ContentType.QR_THREE_LINES, LabelOrientation.ALONG, None),
    ]
)


@pytest.mark.parametrize(("content_type", "orientation", "preset"), _WORST_CASES)
def test_worst_schema_allowed_label_stays_within_the_metric_budget(
    content_type: ContentType,
    orientation: LabelOrientation,
    preset: QlLayoutPreset | None,
    measured: list[int],
) -> None:
    LayoutEngine().render(
        62, content_type, _worst_schema_label(), orientation=orientation, preset=preset
    )
    assert measured[0] < _MEASURE_BUDGET
    assert measured[1] <= _BBOX_BUDGET  # line metrics are measured once per line


def test_worst_schema_allowed_label_costs_at_most_20x_the_reference_label() -> None:
    """Relative wall-clock sanity bound (never an absolute threshold): best of 5 runs each,
    after a warm-up, so font loading and scheduler noise do not decide the result. The
    uncached layout was about 200x the reference."""
    engine = LayoutEngine()
    reference = LabelData(
        source_app="manual",
        primary_id="ST00019",
        title="DOCKER1",
        secondary=("Dell OptiPlex 3070 Micro", "S/N 72104Z2"),
        qr_payload=_QR,
    )
    worst = _worst_schema_label()

    def best(content_type: ContentType, data: LabelData) -> float:
        engine.render(62, content_type, data)  # warm-up
        runs = []
        for _ in range(5):
            start = time.perf_counter()
            engine.render(62, content_type, data)
            runs.append(time.perf_counter() - start)
        return min(runs)

    base = best(ContentType.QR_THREE_LINES, reference)
    for content_type in (ContentType.QR_WITH_LISTING, ContentType.QR_THREE_LINES):
        assert best(content_type, worst) <= 20 * base


def _render(data: LabelData, content_type: ContentType, orientation: LabelOrientation):  # type: ignore[no-untyped-def]
    return LayoutEngine().render(62, content_type, data, orientation=orientation)


@pytest.mark.parametrize("orientation", list(LabelOrientation))
def test_a_huge_title_costs_bounded_measuring_work(
    orientation: LabelOrientation, measured: list[int]
) -> None:
    title = "word " * 40_000  # 200 000 characters from an upstream lookup
    _render(
        LabelData(source_app="snipeit", primary_id="X1", title=title, qr_payload=_QR),
        ContentType.QR_TWO_LINES,
        orientation,
    )
    assert measured[0] < _MEASURE_BUDGET


def test_a_huge_unbroken_word_costs_bounded_measuring_work(measured: list[int]) -> None:
    _render(
        LabelData(source_app="snipeit", primary_id="X1", title="W" * 100_000, qr_payload=_QR),
        ContentType.QR_TWO_LINES,
        LabelOrientation.ACROSS,
    )
    assert measured[0] < _MEASURE_BUDGET


@pytest.mark.parametrize("orientation", list(LabelOrientation))
def test_a_huge_listing_costs_bounded_work_and_says_how_many_are_left(
    orientation: LabelOrientation, measured: list[int]
) -> None:
    items = tuple(LabelDataItem(item=f"Box {n}") for n in range(20_000))
    image = _render(
        LabelData(source_app="hangar", primary_id="K1", items=items, qr_payload=_QR),
        ContentType.QR_WITH_LISTING,
        orientation,
    )
    assert measured[0] < _MEASURE_BUDGET
    assert image.width * image.height <= 696 * ql_layout.ALONG_MAX_LENGTH_PX


def test_rows_left_out_of_the_layout_still_count_in_more() -> None:
    fields, hidden = ql_layout._fields(
        ContentType.QR_WITH_LISTING,
        LabelData(
            source_app="hangar",
            primary_id="K1",
            items=tuple(LabelDataItem(item=f"Box {n}") for n in range(1000)),
            qr_payload=_QR,
        ),
        ql_layout.MAX_LISTING_ROWS_ALONG,
    )
    assert len(fields) == 1 + ql_layout.MAX_LISTING_ROWS_ALONG
    lines = ql_layout._along_lines(fields, 2000, 672, hidden, listing=True)
    shown = len(lines) - 2  # minus the code line and the "+N" line
    assert lines[-1].text == f"+{1000 - shown}"


def test_overflow_marker_is_language_neutral() -> None:
    """The marker is printed on the label, whatever language it is read in: a number, no word."""
    fields, hidden = ql_layout._fields(
        ContentType.QR_WITH_LISTING,
        LabelData(
            source_app="hangar",
            primary_id="K1",
            items=tuple(LabelDataItem(item=f"Box {n}") for n in range(1000)),
            qr_payload=_QR,
        ),
        ql_layout.MAX_LISTING_ROWS_ALONG,
    )
    marker = ql_layout._along_lines(fields, 2000, 672, hidden, listing=True)[-1].text
    assert re.fullmatch(r"\+[0-9]+", marker), marker
    preset = next(iter(QlLayoutPreset))
    across = ql_layout._across_lines(ContentType.QR_WITH_LISTING, _worst_schema_label(), preset)
    assert re.fullmatch(r"\+[0-9]+", across[-1].text), across[-1].text


def test_along_label_length_is_capped_for_a_very_long_line() -> None:
    image = _render(
        LabelData(source_app="manual", primary_id="C1", title="x" * 20_000, qr_payload=_QR),
        ContentType.QR_TWO_LINES,
        LabelOrientation.ALONG,
    )
    assert image.height == 696
    assert image.width <= ql_layout.ALONG_MAX_LENGTH_PX


def test_along_cap_cuts_the_line_with_an_ellipsis() -> None:
    lines = ql_layout._along_lines(
        [("y" * 5000, ql_layout._Role.TITLE)], text_width=500, room=600, hidden=0
    )
    assert len(lines) == 1
    assert lines[0].text.endswith(ql_layout.ELLIPSIS)
    assert lines[0].font.getlength(lines[0].text) <= 500


def test_across_label_length_stays_within_its_maximum() -> None:
    data = LabelData(
        source_app="snipeit",
        primary_id="P" * 5000,
        title="t " * 5000,
        secondary=tuple("s " * 2000 for _ in range(50)),
        qr_payload=_QR,
    )
    image = _render(data, ContentType.QR_THREE_LINES, LabelOrientation.ACROSS)
    assert image.width == 696
    assert image.height <= ql_layout.ACROSS_MAX_LENGTH_PX


@pytest.mark.parametrize(
    "data",
    [
        {"title": "t" * 513},
        {"primary_id": "p" * 513},
        {"qr_payload": "q" * 513},
        {"secondary": ["s"] * 11},
        {"secondary": ["s" * 513]},
        {"items": [{"item": "i"}] * 101},
        {"items": [{"item": "i" * 513}]},
    ],
)
def test_the_print_request_caps_free_text(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PrintRequest.model_validate({"content_type": "qr_two_lines", "data": data})


# --- review fix round 1 ------------------------------------------------------------------


@pytest.mark.parametrize("length", [2400, 2600, 5000])
def test_along_payload_beyond_version_40_is_refused_not_a_value_error(length: int) -> None:
    """Review M1: lookup data is not capped; qrcode raises ValueError beyond version 40."""
    data = LabelData(source_app="snipeit", primary_id="X", qr_payload="h" * length)
    with pytest.raises(QrPayloadTooLongError):
        _render(data, ContentType.QR_ONE_LINE, LabelOrientation.ALONG)


def test_along_many_secondary_lines_stay_inside_the_band_and_mark_the_cut() -> None:
    """Review M2: ten secondary lines overflowed the 696 px band without a marker."""
    data = LabelData(
        source_app="manual",
        primary_id="ST00019",
        title="DOCKER1",
        secondary=tuple(f"Line {n} of the secondary text" for n in range(10)),
        qr_payload=_QR,
    )
    fields, hidden = ql_layout._fields(
        ContentType.QR_THREE_LINES, data, ql_layout.MAX_LISTING_ROWS_ALONG
    )
    room = ql_layout.QL62_PRINTABLE_PX - 2 * ql_layout.TEXT_RIGHT_PX
    lines = ql_layout._along_lines(fields, 1500, room, hidden)
    assert sum(line.height for line in lines) <= room
    assert len(lines) < len(fields)
    assert lines[-1].text.endswith(ql_layout.ELLIPSIS)
    image = _render(data, ContentType.QR_THREE_LINES, LabelOrientation.ALONG)
    assert image.height == 696


def test_dropped_fields_leave_a_visible_ellipsis() -> None:
    """Review M4: trailing fields were dropped at the maximum length without any marker.

    With today's caps an across label only reaches the drop step through the fit helper
    itself (12 one-line fields stay below 50 mm), so the step is tested there directly.
    """
    font = ql_layout._font(ql_layout._Role.DETAIL, 30)
    blocks = [[ql_layout._Line(f"Field {n}", font)] for n in range(12)]
    pitch = blocks[0][0].height
    lines = ql_layout._fit_blocks(blocks, 5 * pitch, 400, None, font)
    assert [line.text for line in lines[:4]] == ["Field 0", "Field 1", "Field 2", "Field 3"]
    assert lines[-1].text.endswith(ql_layout.ELLIPSIS)
    assert sum(line.height for line in lines) <= 5 * pitch


@pytest.mark.parametrize("preset", list(QlLayoutPreset))
def test_worst_across_label_stays_within_50mm(preset: QlLayoutPreset) -> None:
    data = _worst_schema_label()
    for content_type in (ContentType.QR_THREE_LINES, ContentType.QR_WITH_LISTING):
        lines = ql_layout._across_lines(content_type, data, preset)
        limit = ql_layout.ACROSS_MAX_LENGTH_PX - 2 * ql_layout.ACROSS_PRESETS[preset].margin_px
        assert sum(line.height for line in lines) <= limit
    listing = ql_layout._across_lines(ContentType.QR_WITH_LISTING, data, preset)
    assert re.fullmatch(r"\+[0-9]+", listing[-1].text)


def test_across_fit_without_overflow_adds_no_marker() -> None:
    lines = ql_layout._across_lines(
        ContentType.QR_THREE_LINES,
        LabelData(
            source_app="manual",
            primary_id="ST00019",
            title="DOCKER1",
            secondary=("Dell OptiPlex 3070 Micro", "S/N 72104Z2"),
            qr_payload=_QR,
        ),
        QlLayoutPreset.COMPACT,
    )
    assert [line.text for line in lines] == [
        "ST00019",
        "DOCKER1",
        "Dell OptiPlex 3070 Micro",
        "S/N 72104Z2",
    ]
