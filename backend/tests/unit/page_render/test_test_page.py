"""The test page: a frame on the printable area, who/where/when, a QR to the printer (#228)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.models.printer import Printer
from app.page_render.test_page import build_test_page_payload, render_test_page
from app.page_render.transform import PT_PER_MM
from app.schemas.capabilities import HardwareMargins
from app.services.page_jobs import PagePayload

from tests.helpers import pdf_inspect as pi

K = PT_PER_MM
NOW = datetime(2026, 11, 9, 14, 5, tzinfo=timezone(timedelta(hours=1)))
URL = "https://hub.example.invalid/printers/11111111-1111-1111-1111-111111111111"
MARGINS = HardwareMargins(top=4.2, left=6.0, bottom=4.2, right=6.0)


def _printer(**over: object) -> Printer:
    fields: dict[str, object] = {
        "name": "Office laser",
        "slug": "office",
        "model": "m",
        "backend": "ipp",
        "connection": {"uri": "ipps://scan:s3cret@printer.example.invalid/ipp/print"},
    }
    fields.update(over)
    return Printer(**fields)  # type: ignore[arg-type]


def _payload(margins: HardwareMargins | None = MARGINS, **over: object) -> PagePayload:
    args: dict[str, object] = {
        "printer": _printer(),
        "tray": "tray-2",
        "media": "A4",
        "margins_mm": margins,
        "now": NOW,
        "version": "1.5.0",
        "printer_url": URL,
    }
    args.update(over)
    return build_test_page_payload(**args)  # type: ignore[arg-type]


def _pdf(payload: PagePayload) -> bytes:
    return render_test_page(payload, compress=False)


def _frames(pdf: bytes) -> list[list[float]]:
    return [a for op, a in pi.operations(pdf) if op == "re"]


def test_payload_describes_a_test_page_job() -> None:
    p = _payload()
    assert p.kind == "test_page"
    assert p.media == "A4"
    assert p.tray == "tray-2"
    assert p.render_dpi == 600
    assert p.job_name == "Test page · tray-2"
    assert p.calibration is None


def test_frame_matches_the_reported_margins() -> None:
    [frame] = _frames(_pdf(_payload()))
    x, y, w, h = frame
    assert x == pytest.approx(6.0 * K, abs=0.5 * K)
    assert y == pytest.approx(4.2 * K, abs=0.5 * K)  # bottom edge, measured from the page bottom
    assert w == pytest.approx((210 - 12.0) * K, abs=0.5 * K)
    assert h == pytest.approx((297 - 8.4) * K, abs=0.5 * K)


def test_test_page_without_margins_draws_inset_frame() -> None:
    pdf = _pdf(_payload(margins=None))
    [frame] = _frames(pdf)
    x, y, w, h = frame
    assert x == pytest.approx(5.0 * K, abs=0.5 * K)
    assert y == pytest.approx(5.0 * K, abs=0.5 * K)
    assert w == pytest.approx(200.0 * K, abs=0.5 * K)
    assert h == pytest.approx(287.0 * K, abs=0.5 * K)
    assert "Margins not reported" in pi.texts(pdf)


def test_reported_margins_do_not_print_the_not_reported_line() -> None:
    assert "Margins not reported" not in pi.texts(_pdf(_payload()))


def test_page_carries_name_tray_time_and_version() -> None:
    texts = " | ".join(pi.texts(_pdf(_payload())))
    assert "Office laser" in texts
    assert "tray-2" in texts
    assert "2026-11-09 14:05" in texts
    assert "Printer Hub test page 1.5.0" in texts


def test_letter_page_size() -> None:
    pdf = _pdf(_payload(media="Letter"))
    assert pi.media_box(pdf) == pytest.approx((0, 0, 612, 792), abs=1e-3)


def test_page_has_one_qr_image_in_bilevel() -> None:
    [qr] = pi.placed_images(_pdf(_payload()))
    assert qr.image.mode == "1"
    assert qr.w_pt == pytest.approx(qr.h_pt)


def test_test_page_is_not_calibration_page() -> None:
    pdf = _pdf(_payload())
    joined = " | ".join(pi.texts(pdf))
    assert "Test page" in joined
    assert "Calibration" not in joined
    assert b"Calibration page" not in pdf  # not in the document title either


def test_page_never_prints_connection_details() -> None:
    pdf = _pdf(_payload())
    joined = " | ".join(pi.texts(pdf))
    for leak in ("s3cret", "scan:", "ipps://", "printer.example.invalid"):
        assert leak not in joined
        assert leak.encode() not in pdf
    # ... and not in the stored payload, which is what the job row and a retry carry
    stored = _payload().model_dump_json()
    for leak in ("s3cret", "ipps://", "printer.example.invalid"):
        assert leak not in stored


def test_render_is_deterministic() -> None:
    assert _pdf(_payload()) == _pdf(_payload())


def test_page_is_gray_only() -> None:
    assert pi.colour_operators(_pdf(_payload())) == set()


def test_absurd_reported_margins_fall_back_to_the_inset_frame() -> None:
    pdf = _pdf(_payload(margins=HardwareMargins(top=140, left=0, bottom=140, right=0)))
    [frame] = _frames(pdf)
    assert frame[0] == pytest.approx(5.0 * K, abs=0.5 * K)
    assert "Margins not reported" in pi.texts(pdf)


def test_a_very_long_printer_name_is_shortened_to_fit_the_frame() -> None:
    long_name = "W" * 200
    pdf = _pdf(_payload(printer=_printer(name=long_name)))
    shown = [t for t in pi.texts(pdf) if t.startswith("W")]
    assert shown and shown[0].endswith("…") and len(shown[0]) < 60
