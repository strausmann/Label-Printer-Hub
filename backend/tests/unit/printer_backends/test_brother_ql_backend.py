# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase 1i Sub-Task G: BrotherQLBackend tests."""

from __future__ import annotations

import logging

import pytest
from app.models.tape import TapeSpec
from app.printer_backends.brother_ql_backend import BrotherQLBackend
from app.schemas.label_layout import LabelOrientation
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry
from PIL import Image


@pytest.fixture
def tape_spec_62() -> TapeSpec:
    """QL-Series 62mm continuous-length tape spec (DK-2205 etc.)."""
    return TapeSpec(
        width_mm=62,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=696,
        print_area_dots=696,
        bytes_per_raster=90,
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    )


@pytest.fixture
def dummy_image() -> Image.Image:
    """Minimal 696x200 white image — matches QL-820NWB 62mm print width."""
    return Image.new("RGB", (696, 200), "white")


@pytest.mark.anyio
async def test_print_image_calls_brother_ql_send(
    monkeypatch: pytest.MonkeyPatch,
    dummy_image: Image.Image,
    tape_spec_62: TapeSpec,
) -> None:
    """Phase 1i G: print_image -> convert + helpers.send via asyncio.to_thread."""
    send_calls: list[tuple] = []

    def fake_send(data, identifier, **kwargs):
        send_calls.append((identifier, len(data), kwargs))

    monkeypatch.setattr("app.printer_backends.brother_ql_backend._helpers_send", fake_send)

    backend = BrotherQLBackend(host="192.0.2.11", port=9100, model_id="QL-820NWB")
    await backend.print_image(dummy_image, tape_spec_62, auto_cut=True, last_page=True)
    assert len(send_calls) == 1
    identifier, payload_len, _kwargs = send_calls[0]
    assert identifier == "tcp://192.0.2.11:9100"
    assert payload_len > 0


@pytest.mark.anyio
async def test_half_cut_ignored_on_ql_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    dummy_image: Image.Image,
    tape_spec_62: TapeSpec,
) -> None:
    """half_cut=True wird vom QL-Backend ignoriert + Warning geloggt."""
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda *a, **k: None,
    )
    backend = BrotherQLBackend(host="x", port=9100, model_id="QL-820NWB")
    with caplog.at_level(logging.WARNING, logger="app.printer_backends.brother_ql_backend"):
        await backend.print_image(dummy_image, tape_spec_62, half_cut=True)
    assert any("half_cut" in rec.message.lower() for rec in caplog.records)


def test_half_cut_supported_is_false() -> None:
    assert BrotherQLBackend.half_cut_supported is False


# ---------------------------------------------------------------------------
# preflight_check — Phase 1i hotfix (Task 8b)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_preflight_check_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight_check returns PreflightStatus on healthy printer."""
    from app.printer_backends.snmp_helper import PreflightStatus

    async def fake_preflight(
        host: str, *, community: str = "public", timeout_s: float = 3.0
    ) -> PreflightStatus:
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=62,
            error_flags=[],
        )

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", fake_preflight)
    backend = BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB")
    result = await backend.preflight_check()
    assert result.hr_printer_status == "idle"
    assert result.loaded_tape_mm == 62


@pytest.mark.anyio
async def test_preflight_check_raises_tape_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight_check raises TapeEmptyError when noPaper bit is set."""
    from app.printer_backends.exceptions import TapeEmptyError
    from app.printer_backends.snmp_helper import PreflightStatus

    async def fake_preflight(
        host: str, *, community: str = "public", timeout_s: float = 3.0
    ) -> PreflightStatus:
        return PreflightStatus(
            hr_printer_status="other",
            loaded_tape_mm=None,
            error_flags=["noPaper"],
        )

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", fake_preflight)
    backend = BrotherQLBackend(host="x", model_id="QL-820NWB")
    with pytest.raises(TapeEmptyError):
        await backend.preflight_check()


@pytest.mark.anyio
async def test_print_images_delegates_to_loop_helper(
    monkeypatch: pytest.MonkeyPatch,
    tape_spec_62: TapeSpec,
) -> None:
    """BrotherQLBackend.print_images delegates to default_print_images_loop with half_cut=False."""
    captured: dict[str, object] = {}

    async def fake_loop(backend, images, tape_spec, **kwargs):
        captured["backend"] = backend
        captured["num_images"] = len(images)
        captured["tape_mm"] = tape_spec.width_mm
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend.default_print_images_loop",
        fake_loop,
    )

    backend = BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB")
    images = [Image.new("1", (696, 200), color=1) for _ in range(3)]

    await backend.print_images(
        images,
        tape_spec_62,
        auto_cut=True,
        high_resolution=False,
        half_cut=True,  # caller passes True; QL erzwingt False
    )

    assert captured["backend"] is backend
    assert captured["num_images"] == 3
    assert captured["tape_mm"] == 62
    assert captured["auto_cut"] is True
    assert captured["high_resolution"] is False
    # QL-Series hat kein Half-Cut — Backend-Capability erzwingt half_cut=False
    assert captured["half_cut"] is False


@pytest.mark.anyio
async def test_preflight_check_raises_offline_on_snmp_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """preflight_check raises PrinterOfflineError when SNMP query fails."""
    from app.printer_backends.exceptions import PrinterOfflineError
    from app.printer_backends.snmp_helper import PreflightStatus, SnmpQueryError

    async def fake_preflight(
        host: str, *, community: str = "public", timeout_s: float = 3.0
    ) -> PreflightStatus:
        raise SnmpQueryError("timeout")

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", fake_preflight)
    backend = BrotherQLBackend(host="unreachable", model_id="QL-820NWB")
    with pytest.raises(PrinterOfflineError, match="preflight SNMP failed"):
        await backend.preflight_check()


@pytest.mark.anyio
async def test_preflight_check_no_duplicate_prefix_when_snmp_error_already_has_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #105: PrinterOfflineError darf 'preflight SNMP failed' nicht doppelt enthalten.

    query_preflight() erzeugt SnmpQueryError-Messages die bereits mit
    'preflight SNMP failed: ' beginnen (snmp_helper.py Zeile 191).
    Das BrotherQLBackend darf dann den Prefix NICHT nochmal voranstellen.
    """
    from app.printer_backends.exceptions import PrinterOfflineError
    from app.printer_backends.snmp_helper import PreflightStatus, SnmpQueryError

    # Simuliert was snmp_helper.query_preflight() bei SNMP-Fehler wirft —
    # die Message beginnt bereits mit "preflight SNMP failed: ".
    already_prefixed_msg = "preflight SNMP failed: UDP transport error"

    async def fake_preflight(
        host: str, *, community: str = "public", timeout_s: float = 3.0
    ) -> PreflightStatus:
        raise SnmpQueryError(already_prefixed_msg)

    monkeypatch.setattr("app.printer_backends.brother_ql_backend.query_preflight", fake_preflight)
    backend = BrotherQLBackend(host="unreachable", model_id="QL-820NWB")
    with pytest.raises(PrinterOfflineError) as exc_info:
        await backend.preflight_check()

    error_msg = str(exc_info.value)
    # Darf nur EINMAL "preflight SNMP failed" enthalten
    assert error_msg.count("preflight SNMP failed") == 1, (
        f"Duplicate prefix in error message: {error_msg!r}"
    )


@pytest.mark.anyio
async def test_ql820_raster_starts_with_400_invalidate_bytes(
    monkeypatch: pytest.MonkeyPatch,
    dummy_image: Image.Image,
    tape_spec_62: TapeSpec,
) -> None:
    """#256: brother-ql-next sends 400 invalidate bytes for the QL-820NWB (brother-ql: 200).

    ``convert`` writes ``ESC i a 1`` (raster mode), then the invalidate bytes, then ``ESC @``
    (initialise). Asserts on the exact bytes handed to ``helpers.send``, so a library that goes
    back to 200 turns this red.
    """
    sent: list[bytes] = []
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda data, identifier, **kwargs: sent.append(bytes(data)),
    )

    backend = BrotherQLBackend(host="192.0.2.11", port=9100, model_id="QL-820NWB")
    await backend.print_image(dummy_image, tape_spec_62, auto_cut=True, last_page=True)

    (raster,) = sent
    assert raster.startswith(b"\x1bia\x01" + b"\x00" * 400 + b"\x1b\x40")


@pytest.mark.anyio
async def test_raster_shorter_than_the_model_minimum_is_padded_not_refused(
    monkeypatch: pytest.MonkeyPatch,
    tape_spec_62: TapeSpec,
) -> None:
    """#256: brother-ql-next refuses a raster under 150 dots (QL-820NWB); the backend pads it.

    A 70-row label used to go out as it was. Now it is padded with white rows at the end, so the
    print is accepted and the extra rows are blank tape.
    """
    seen: list[Image.Image] = []
    from app.printer_backends import brother_ql_backend

    real = brother_ql_backend.convert

    def spy(qlr, images, *args, **kwargs):
        seen.extend(images)
        return real(qlr, images, *args, **kwargs)

    monkeypatch.setattr(brother_ql_backend, "convert", spy)
    monkeypatch.setattr(brother_ql_backend, "_helpers_send", lambda *a, **k: None)

    image = Image.new("RGB", (696, 70), "black")
    await BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB").print_image(
        image, tape_spec_62, auto_cut=True, last_page=True
    )

    (sent_image,) = seen
    assert sent_image.size == (696, 150)
    assert sent_image.getpixel((10, 10)) == (0, 0, 0)  # content kept at the top
    assert sent_image.getpixel((10, 149)) == (255, 255, 255)  # padding is white


@pytest.mark.anyio
async def test_batch_pads_short_labels_too(
    monkeypatch: pytest.MonkeyPatch,
    tape_spec_62: TapeSpec,
) -> None:
    """The batch path pads each label like the single path does."""
    from app.printer_backends import brother_ql_backend

    seen: list[Image.Image] = []
    real = brother_ql_backend.convert

    def spy(qlr, images, *args, **kwargs):
        seen.extend(images)
        return real(qlr, images, *args, **kwargs)

    monkeypatch.setattr(brother_ql_backend, "convert", spy)
    monkeypatch.setattr(brother_ql_backend, "_helpers_send", lambda *a, **k: None)

    backend = BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB")
    await backend.print_images(
        [Image.new("RGB", (696, 70), "black"), Image.new("RGB", (696, 300), "black")],
        tape_spec_62,
    )
    assert [im.height for im in seen] == [150, 300]


# --- #256 review round 1: the library's raster limits ---------------------------------------


@pytest.fixture
def _send_spy(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    out: list[bytes] = []
    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend._helpers_send",
        lambda data, identifier, **kwargs: out.append(bytes(data)),
    )
    return out


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("high_resolution", "rows", "max_mm"),
    [
        (False, 11812, 1000),  # 11811 dots at 300 dpi = 1000 mm (shown rounded)
        (True, 11812, 500),  # 11811 dots at 600 dpi = 500 mm (shown rounded)
    ],
)
async def test_label_over_the_library_raster_limit_is_refused_as_too_long(
    high_resolution: bool,
    rows: int,
    max_mm: int,
    tape_spec_62: TapeSpec,
    _send_spy: list[bytes],
) -> None:
    """#256 M1: brother-ql-next refuses rasters over 11811 dots; that is a 422, not a raw error."""
    from app.printer_backends.exceptions import TapeLabelTooLongError

    # At 600 dpi the fitted image is doubled, so the source has half the rows and half the width.
    width, height = (348, rows // 2) if high_resolution else (696, rows)
    image = Image.new("RGB", (width, height), "white")
    backend = BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB")

    with pytest.raises(TapeLabelTooLongError) as err:
        backend.check_label_lengths(
            [image],
            tape_spec_62,
            high_resolution=high_resolution,
            orientation=LabelOrientation.ACROSS,
        )
    assert err.value.max_mm == max_mm
    assert err.value.nothing_sent

    with pytest.raises(TapeLabelTooLongError):  # the worker backstop refuses it too
        await backend.print_image(
            image,
            tape_spec_62,
            high_resolution=high_resolution,
            orientation=LabelOrientation.ACROSS,
        )
    with pytest.raises(TapeLabelTooLongError):
        await backend.print_images(
            [image],
            tape_spec_62,
            high_resolution=high_resolution,
            orientation=LabelOrientation.ACROSS,
        )
    assert _send_spy == []


@pytest.mark.anyio
async def test_label_at_the_library_raster_limit_still_prints(
    tape_spec_62: TapeSpec, _send_spy: list[bytes]
) -> None:
    image = Image.new("RGB", (696, 11811), "white")
    await BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB").print_image(
        image, tape_spec_62, orientation=LabelOrientation.ACROSS
    )
    assert len(_send_spy) == 1


@pytest.mark.anyio
async def test_wide_short_image_is_padded_for_its_scaled_height(
    tape_spec_62: TapeSpec, _send_spy: list[bytes]
) -> None:
    """#256 M2: 1400x200 across is scaled to 696x99 by convert; the padding is computed on that."""
    await BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB").print_image(
        Image.new("RGB", (1400, 200), "white"),
        tape_spec_62,
        orientation=LabelOrientation.ACROSS,
    )
    assert len(_send_spy) == 1


def test_submit_time_length_includes_the_padding(tape_spec_62: TapeSpec) -> None:
    """#256 L1: a 12 mm label under 150 dots is measured with the padding it is sent with."""
    spec = TapeRegistry.lookup_ql(12, MediaType.CONTINUOUS_LENGTH_TAPE)
    (length,) = BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB").check_label_lengths(
        [Image.new("RGB", (106, 70), "white")], spec, orientation=LabelOrientation.ACROSS
    )
    assert length == pytest.approx(150 * 25.4 / 300)


def test_die_cut_label_is_not_padded() -> None:
    """#256 L2: only endless media are padded; a die-cut label has a fixed length."""
    from app.printer_backends.brother_ql_backend import _pad_to_min_length

    image = Image.new("RGB", (306, 100), "white")
    assert _pad_to_min_length(image, "QL-820NWB", "17x54").size == (306, 100)
    assert _pad_to_min_length(image, "QL-820NWB", "29").size == (306, 150)
