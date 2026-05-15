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
