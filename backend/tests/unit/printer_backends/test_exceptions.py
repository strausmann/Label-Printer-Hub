# backend/tests/unit/printer_backends/test_exceptions.py
from __future__ import annotations

import pytest
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterError,
    PrinterOfflineError,
    PrintFailedError,
    SnmpDiscoveryError,
    SnmpQueryError,
    StatusQueryFailedError,
    TapeEmptyError,
    TapeMismatchError,
)


class TestHierarchy:
    @pytest.mark.parametrize(
        "exc_cls",
        [
            PrinterOfflineError,
            TapeMismatchError,
            TapeEmptyError,
            PrinterCoverOpenError,
            PrintFailedError,
            StatusQueryFailedError,
            SnmpDiscoveryError,
            SnmpQueryError,
        ],
    )
    def test_subclasses_printer_error(self, exc_cls: type[Exception]) -> None:
        assert issubclass(exc_cls, PrinterError)

    def test_printer_error_is_exception(self) -> None:
        assert issubclass(PrinterError, Exception)


class TestTapeMismatchFields:
    def test_carries_expected_and_loaded(self) -> None:
        err = TapeMismatchError(expected_mm=18, loaded_mm=12)
        assert err.expected_mm == 18
        assert err.loaded_mm == 12

    def test_loaded_can_be_none_for_no_tape(self) -> None:
        err = TapeMismatchError(expected_mm=18, loaded_mm=None)
        assert err.loaded_mm is None

    def test_str_mentions_both_values(self) -> None:
        err = TapeMismatchError(expected_mm=18, loaded_mm=12)
        s = str(err)
        assert "18" in s and "12" in s


from app.printer_backends.exceptions import (  # noqa: E402
    ContentTypeDataMismatchError,
    NoTapeLoadedError,
    UnsupportedTapeError,
)


class TestUnsupportedTapeError:
    def test_carries_tape_mm(self) -> None:
        exc = UnsupportedTapeError(tape_mm=36)
        assert exc.tape_mm == 36
        assert "36" in str(exc)
        assert "supported" in str(exc).lower()


class TestNoTapeLoadedError:
    def test_message_default(self) -> None:
        exc = NoTapeLoadedError()
        assert "no tape" in str(exc).lower()


class TestContentTypeDataMismatchError:
    def test_carries_content_type_and_missing(self) -> None:
        exc = ContentTypeDataMismatchError(
            content_type="qr_two_lines",
            missing_fields=("primary_id", "title"),
        )
        assert exc.content_type == "qr_two_lines"
        assert exc.missing_fields == ("primary_id", "title")
        assert "primary_id" in str(exc) and "title" in str(exc)


from uuid import UUID  # noqa: E402

from app.printer_backends.exceptions import PrinterDisabledError  # noqa: E402

_PRINTER_ID = UUID("12345678-1234-5678-1234-567812345678")
_SLUG = "brother-ql-820nwb"


class TestPrinterDisabledError:
    def test_subclasses_printer_error(self) -> None:
        """Hierarchie: PrinterDisabledError ist ein PrinterError."""
        assert issubclass(PrinterDisabledError, PrinterError)

    def test_stores_printer_id_and_slug(self) -> None:
        """Konstruktor speichert printer_id und slug als Instanzattribute."""
        exc = PrinterDisabledError(_PRINTER_ID, _SLUG)
        assert exc.printer_id == _PRINTER_ID
        assert exc.slug == _SLUG

    def test_str_contains_slug_and_printer_id(self) -> None:
        """str(exc) enthält sowohl slug als auch die UUID des Druckers."""
        exc = PrinterDisabledError(_PRINTER_ID, _SLUG)
        msg = str(exc)
        assert _SLUG in msg
        assert str(_PRINTER_ID) in msg
