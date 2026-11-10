"""The QL layout bounds its work and its image size, whatever the text (#258 security review).

Label data does not only come from the request schema (which caps lengths): integration
lookups return whatever the upstream system holds. The renderer must therefore bound the text
measuring work and never allocate an image beyond a documented maximum length.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_data_item import LabelDataItem
from app.schemas.label_layout import LabelOrientation
from app.schemas.print_request import PrintRequest
from app.services import ql_layout
from app.services.layout_engine import LayoutEngine
from PIL import ImageFont
from pydantic import ValidationError

_QR = "https://example.invalid/hardware/19"
_MEASURE_BUDGET = 3000
"""Generous upper bound of ``getlength`` calls for one label; the unbounded code needs
hundreds of thousands for the inputs below."""


@pytest.fixture
def measured(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    calls = [0]
    real = ImageFont.FreeTypeFont.getlength

    def counting(self: ImageFont.FreeTypeFont, *args: object, **kwargs: object) -> float:
        calls[0] += 1
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ImageFont.FreeTypeFont, "getlength", counting)
    yield calls


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
    )
    assert len(fields) == 1 + ql_layout.MAX_LISTING_ROWS
    lines = ql_layout._along_lines(fields, 2000, 672, hidden, listing=True)
    shown = len(lines) - 2  # minus the code line and the "+N more" line
    assert lines[-1].text == f"+{1000 - shown} more"


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
