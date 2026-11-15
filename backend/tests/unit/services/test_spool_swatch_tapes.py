# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The spool label on every QL DK endless width (#346, maintainer ruling 2026-11-15).

54 mm across without the footer, 50 and 38 mm along with everything, 29 mm across with the
core, 62 mm unchanged. Along labels are as long as their content needs, never shorter than
``SWATCH_ALONG_MIN_MM``.
"""

from __future__ import annotations

import hashlib
import itertools

import pytest
from app.printer_backends.exceptions import QrPayloadTooLongError
from app.schemas.label_layout import LabelOrientation
from app.services.spool_swatch import (
    SWATCH_ALONG_MIN_MM,
    SWATCH_TAPES,
    SwatchTier,
    place_swatch,
    render_tape_swatch,
    swatch_for_batch,
    swatch_symbol,
    tape_swatch_layout,
)
from app.services.spool_swatch.font import text_mm, to_px
from app.sheets.planner import MIN_QR_MODULE_HMM
from PIL import Image

from tests.helpers.spool_swatch import SAMPLE_URL, every_row, ink_bbox, swatch

ACROSS, ALONG = LabelOrientation.ACROSS, LabelOrientation.ALONG
DPI = 300
WIDTHS = (29, 38, 50, 54, 62)
EXPECTED = {
    29: (ACROSS, SwatchTier.CORE),
    38: (ALONG, SwatchTier.FULL),
    50: (ALONG, SwatchTier.FULL),
    54: (ACROSS, SwatchTier.NO_FOOTER),
    62: (ACROSS, SwatchTier.FULL),
}
SPOOLS = {
    "every_row": every_row,
    "sparse": swatch,
    "long": lambda: every_row(
        vendor="Polymaker Industrial Filaments",
        color_name="Galaxy Black with Silver Glitter",
        color_hexes=("101010", "C0C0C0", "303030"),
        location="Shelf B, AMS slot 4, top row",
    ),
}


def test_the_ruled_widths_and_nothing_else() -> None:
    assert sorted(SWATCH_TAPES) == list(WIDTHS)


@pytest.mark.parametrize("tape_mm", WIDTHS)
def test_direction_and_tier_per_width(tape_mm: int) -> None:
    orientation, tier = EXPECTED[tape_mm]
    assert SWATCH_TAPES[tape_mm].orientation is orientation
    layout, _, _ = tape_swatch_layout(every_row(), tape_mm)
    assert layout.tier is tier


@pytest.mark.parametrize("tape_mm", WIDTHS)
@pytest.mark.parametrize("spool", SPOOLS)
def test_image_spans_the_tape_in_its_direction(tape_mm: int, spool: str) -> None:
    image = render_tape_swatch(SPOOLS[spool](), SAMPLE_URL, tape_mm)
    dots = SWATCH_TAPES[tape_mm].dots
    # The QL backend prints an across image as is and turns an along image (#258).
    if SWATCH_TAPES[tape_mm].orientation is ACROSS:
        assert image.width == dots
    else:
        assert image.height == dots


@pytest.mark.parametrize(
    ("tape_mm", "length_px"),
    [(29, 238), (54, 350), (62, 425)],
)
def test_across_length_is_the_tier_height(tape_mm: int, length_px: int) -> None:
    assert render_tape_swatch(every_row(), SAMPLE_URL, tape_mm).height == length_px


@pytest.mark.parametrize("tape_mm", [38, 50])
@pytest.mark.parametrize(
    ("spool", "length_px"), [("every_row", 625), ("sparse", 355), ("long", 625)]
)
def test_along_length_follows_the_content(tape_mm: int, spool: str, length_px: int) -> None:
    """A spool with every row needs the full width (its drying value ends at the QR gap); a
    sparse one shrinks to ``SWATCH_ALONG_MIN_MM``."""
    image = render_tape_swatch(SPOOLS[spool](), SAMPLE_URL, tape_mm)
    assert image.width == length_px
    assert image.width * 25.4 / DPI >= SWATCH_ALONG_MIN_MM


@pytest.mark.parametrize("tape_mm", [38, 50])
@pytest.mark.parametrize("spool", SPOOLS)
def test_along_label_is_trimmed_to_what_binds_it(tape_mm: int, spool: str) -> None:
    """No millimetre is left over: a text ends at the QR gap or at the box edge, or the label
    is at its minimum length."""
    sw = SPOOLS[spool]()
    layout, metrics, (width_px, _) = tape_swatch_layout(sw, tape_mm)
    if width_px * 25.4 / DPI < SWATCH_ALONG_MIN_MM + 0.2:
        return
    placement = place_swatch(sw, layout, metrics)
    qr_x, qr_y, edge = layout.qr_box
    slack = []
    for run in placement.runs:
        right = run.x + text_mm(run.text, run.weight, run.cap_mm) * 100 + metrics.run_margin
        beside = run.baseline > qr_y and run.baseline - run.cap_mm * 100 < qr_y + edge
        if beside and run.x < qr_x:
            slack.append(qr_x - metrics.qr_gap - right)
        slack.append(layout.box_w - right)
    assert min(slack) < 100


def test_along_rows_sit_under_the_colour_line() -> None:
    """No gap: the rows end where the box ends, and the box is the tier's height, not the tape's."""
    for tape_mm in (38, 50):
        layout, metrics, _ = tape_swatch_layout(every_row(), tape_mm)
        assert layout.box_h == 3040
        placement = place_swatch(every_row(), layout, metrics)
        first_row = min(b for c in placement.columns for r in c.rows for b in r.baselines)
        assert first_row - layout.colour_bottom < 3 * metrics.row_pitch


@pytest.mark.parametrize("tape_mm", [38, 50])
def test_along_content_is_centred_across_the_tape(tape_mm: int) -> None:
    image = render_tape_swatch(every_row(), SAMPLE_URL, tape_mm)
    _, top, _, bottom = ink_bbox(image)  # type: ignore[misc]
    assert abs(top - (image.height - bottom)) <= 30


def _rect(run) -> tuple[float, float, float, float]:  # type: ignore[no-untyped-def]
    return (
        run.x,
        run.baseline - run.cap_mm * 100,
        run.x + text_mm(run.text, run.weight, run.cap_mm) * 100,
        run.baseline,
    )


def _disjoint(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


@pytest.mark.parametrize("tape_mm", WIDTHS)
@pytest.mark.parametrize("spool", SPOOLS)
def test_nothing_overlaps(tape_mm: int, spool: str) -> None:
    sw = SPOOLS[spool]()
    layout, metrics, _ = tape_swatch_layout(sw, tape_mm)
    placement = place_swatch(sw, layout, metrics)
    qx, qy, edge = layout.qr_box
    qr = (qx, qy, qx + edge, qy + edge)
    bx, by, bw, bh = layout.bar
    bar = (bx, by, bx + bw, by + bh)
    box = (0, 0, layout.box_w, layout.box_h)
    texts = [_rect(r) for r in placement.runs]
    for r, rect in zip(placement.runs, texts, strict=True):
        assert (
            box[0] <= rect[0] and rect[2] <= box[2] + 1 and box[1] <= rect[1] and rect[3] <= box[3]
        ), r
        assert _disjoint(rect, qr), r
        if r.fill != 255:  # dark text stays off the bar; the title is drawn white on it
            assert _disjoint(rect, bar), r
    for (ra, a), (rb, b) in itertools.combinations(zip(placement.runs, texts, strict=True), 2):
        assert _disjoint(a, b), (ra.text, rb.text)


@pytest.mark.parametrize(("tape_mm", "module_px"), [(29, 4), (38, 4), (50, 4), (54, 3), (62, 5)])
def test_qr_modules_reach_the_minimum(tape_mm: int, module_px: int) -> None:
    """The planner's 0.25 mm module minimum (``MIN_QR_MODULE_HMM``), the one the spool label
    already meets on sheets; 54 mm sits at 3 px (0.254 mm), the others at 4 px or more."""
    layout, _, _ = tape_swatch_layout(every_row(), tape_mm)
    symbol = swatch_symbol(SAMPLE_URL, to_px(layout.qr_box[2], DPI))
    assert symbol is not None
    assert symbol[1] == module_px
    assert symbol[1] * 2540 >= MIN_QR_MODULE_HMM * DPI


# SHA-256 of the 62 mm image bytes at 739602d, before the other DK widths (``git archive``).
GOLDEN_62 = {
    "every_row": "024886b2ef822ccbb19ef334dc106356df1c60e19e70cd2f9ffb21c437f24b8d",
    "sparse": "40c11ec60045dd032824a5d72469437d907d47ed55ce79753fe1f6c0f153b0c6",
}


@pytest.mark.parametrize("spool", GOLDEN_62)
def test_62_mm_is_unchanged(spool: str) -> None:
    from app.services.spool_swatch import SWATCH_TAPE_PX

    image = render_tape_swatch(SPOOLS[spool](), SAMPLE_URL, 62)
    assert (image.size, image.mode) == (SWATCH_TAPE_PX, "1")
    assert hashlib.sha256(image.tobytes()).hexdigest() == GOLDEN_62[spool]
    assert image.tobytes() == render_tape_swatch(SPOOLS[spool](), SAMPLE_URL).tobytes()


@pytest.mark.parametrize("tape_mm", WIDTHS)
@pytest.mark.parametrize("batch", [ACROSS, ALONG, None])
def test_batch_hands_over_what_prints_upright(tape_mm: int, batch: LabelOrientation | None) -> None:
    """The backend turns every image of an along batch by 270; whatever the batch, the printed
    bitmap equals the label in its own direction."""
    image = render_tape_swatch(every_row(), SAMPLE_URL, tape_mm)
    handed = swatch_for_batch(image, tape_mm, batch)
    printed = handed.transpose(Image.Transpose.ROTATE_270) if batch is ALONG else handed
    native = SWATCH_TAPES[tape_mm].orientation
    expected = image.transpose(Image.Transpose.ROTATE_270) if native is ALONG else image
    if batch is None:
        printed = handed.transpose(Image.Transpose.ROTATE_270) if native is ALONG else handed
    assert printed.tobytes() == expected.tobytes()
    assert printed.width == SWATCH_TAPES[tape_mm].dots


def _url(length: int) -> str:
    base = "https://labels.example.org/spool/show/12?x="
    return base + "a" * (length - len(base))


def _prints(tape_mm: int, length: int) -> bool:
    try:
        render_tape_swatch(every_row(), _url(length), tape_mm)
    except QrPayloadTooLongError:
        return False
    return True


def _longest_that_prints(tape_mm: int) -> int:
    """The longest payload the tape prints (bytes); payload length is monotone in QR size."""
    low, high = len(SAMPLE_URL), 3000
    while low < high:
        mid = (low + high + 1) // 2
        if _prints(tape_mm, mid):
            low = mid
        else:
            high = mid - 1
    return low


@pytest.mark.parametrize("tape_mm", WIDTHS)
def test_every_printed_qr_keeps_modules_of_at_least_025_mm(tape_mm: int) -> None:
    """Up to the longest payload a tape takes, every module is at least 0.25 mm; one byte more
    is refused with ``qr_payload_too_long``, naming exactly that limit."""
    layout, _, _ = tape_swatch_layout(every_row(), tape_mm)
    box_px = to_px(layout.qr_box[2], DPI)
    longest = _longest_that_prints(tape_mm)
    for length in range(len(SAMPLE_URL), longest + 1, 7):
        symbol = swatch_symbol(_url(length), box_px)
        assert symbol is not None
        assert symbol[1] * 2540 >= MIN_QR_MODULE_HMM * DPI, length
    with pytest.raises(QrPayloadTooLongError) as exc:
        render_tape_swatch(every_row(), _url(longest + 1), tape_mm)
    assert exc.value.max_bytes == longest
    assert exc.value.length == longest + 1


@pytest.mark.parametrize(
    ("tape_mm", "longest"), [(29, 84), (38, 122), (50, 122), (54, 62), (62, 213)]
)
def test_longest_qr_payload_per_width(tape_mm: int, longest: int) -> None:
    """The per-width limit the docs name (bytes, error correction M)."""
    assert _longest_that_prints(tape_mm) == longest


def test_a_url_40_characters_longer_is_refused_on_54mm() -> None:
    with pytest.raises(QrPayloadTooLongError):
        render_tape_swatch(every_row(), SAMPLE_URL + "?" + "a" * 39, 54)
