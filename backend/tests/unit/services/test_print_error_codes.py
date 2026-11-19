# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one table of known printer and render errors and their description (#378)."""

from __future__ import annotations

from uuid import uuid4

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    LabelTooLongError,
    MediaTypeMismatchError,
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterDisabledError,
    PrinterOfflineError,
    PrinterReportedError,
    QrPayloadTooLongError,
    SnmpQueryError,
    SpoolLabelOnlyTapeError,
    TapeEmptyError,
    TapeMismatchError,
    UnsupportedTapeError,
)
from app.services.lookup_service import LookupFailedError, UnknownAppError
from app.services.print_error_codes import (
    KNOWN_PRINT_ERROR_TYPES,
    describe_print_error,
)
from app.services.print_service import _DEFERRED_FAILURE_MESSAGES

SAMPLES: dict[type[Exception], Exception] = {
    UnknownAppError: UnknownAppError("no such app"),
    LookupFailedError: LookupFailedError("upstream down"),
    PrinterDisabledError: PrinterDisabledError(uuid4(), "tape-a"),
    TapeMismatchError: TapeMismatchError(expected_mm=12, loaded_mm=24),
    TapeEmptyError: TapeEmptyError(),
    NoTapeLoadedError: NoTapeLoadedError(),
    PrinterCoverOpenError: PrinterCoverOpenError(),
    PrinterOfflineError: PrinterOfflineError("unreachable"),
    UnsupportedTapeError: UnsupportedTapeError(tape_mm=70),
    ContentTypeDataMismatchError: ContentTypeDataMismatchError(
        content_type="qr_two_lines", missing_fields=("title",)
    ),
    QrPayloadTooLongError: QrPayloadTooLongError(length=300, max_bytes=100),
    LabelTooLongError: LabelTooLongError(length_mm=1601, max_mm=1000),
    SnmpQueryError: SnmpQueryError("preflight SNMP failed"),
    MediaTypeMismatchError: MediaTypeMismatchError(loaded_kind="die_cut", media_raw="29mm x 90mm"),
    PrinterReportedError: PrinterReportedError(["jammed"]),
}


def test_every_known_class_is_described() -> None:
    assert set(KNOWN_PRINT_ERROR_TYPES) == set(SAMPLES), "a sample per known class"
    for cls in KNOWN_PRINT_ERROR_TYPES:
        known = describe_print_error(SAMPLES[cls])
        # 4xx, or the upstream/printer 502 and 503: never the 500 of an unhandled error.
        assert 400 <= known.status < 500 or known.status in (502, 503), (cls, known.status)
        assert known.code, cls
        assert known.message, cls


def test_a_die_cut_roll_has_a_fixed_message_and_its_detail() -> None:
    """#389: a die-cut roll answers 409 with the loaded kind and the printer's media text."""
    known = describe_print_error(
        MediaTypeMismatchError(loaded_kind="die_cut", media_raw="29mm x 90mm")
    )
    assert (known.status, known.code) == (409, "media_type_mismatch")
    assert known.detail == {"loaded_kind": "die_cut", "media_raw": "29mm x 90mm"}
    assert "continuous tape only" in known.message


def test_a_printer_error_state_names_the_flags_not_the_words() -> None:
    """#389: the flags go to the detail; the app says them in its own words (#376)."""
    known = describe_print_error(PrinterReportedError(["jammed", "serviceRequested"]))
    assert (known.status, known.code) == (409, "printer_error")
    assert known.detail == {"flags": ["jammed", "serviceRequested"]}
    assert "jammed" not in known.message


def test_spool_only_tape_keeps_its_content_types() -> None:
    known = describe_print_error(
        SpoolLabelOnlyTapeError(tape_mm=29, content_types=("qr_one_line",))
    )
    assert (known.status, known.code) == (409, "unsupported_tape")
    assert known.detail == {"tape_mm": 29, "content_types": ["qr_one_line"]}
    assert known.message.startswith("Only the spool label prints on 29 mm tape.")


def test_unsupported_tape_names_the_width() -> None:
    known = describe_print_error(UnsupportedTapeError(tape_mm=70))
    assert (known.status, known.code) == (409, "unsupported_tape")
    assert known.detail == {"tape_mm": 70}
    assert "70" not in known.message, "a fixed sentence, never str(exc)"


def test_unsupported_orientation_has_its_own_sentence() -> None:
    known = describe_print_error(UnsupportedTapeError(tape_mm=12, orientation="across"))
    assert known.message == "The selected orientation is not available for this tape width."
    assert known.detail == {"tape_mm": 12}


def test_lookup_failure_message_is_fixed() -> None:
    known = describe_print_error(LookupFailedError("https://grocy.example.invalid/x secret"))
    assert (known.status, known.code) == (502, "integration_lookup_failed")
    assert "grocy.example.invalid" not in known.message
    assert "secret" not in known.message


def test_content_mismatch_names_the_missing_fields_not_the_exception() -> None:
    known = describe_print_error(SAMPLES[ContentTypeDataMismatchError])
    assert known.detail == {"missing_fields": ["title"]}
    assert "qr_two_lines" not in known.message


def test_tape_mismatch_and_qr_carry_their_numbers() -> None:
    assert describe_print_error(SAMPLES[TapeMismatchError]).detail == {
        "expected_mm": 12,
        "loaded_mm": 24,
    }
    assert describe_print_error(SAMPLES[QrPayloadTooLongError]).detail == {
        "length": 300,
        "max_bytes": 100,
    }


def test_snmp_query_failure_is_503_snmp_query_failed() -> None:
    known = describe_print_error(SnmpQueryError("preflight SNMP failed"))
    assert (known.status, known.code) == (503, "snmp_query_failed")


def test_an_unknown_subclass_maps_by_its_base() -> None:
    class _OddError(TapeEmptyError):
        pass

    known = describe_print_error(_OddError())
    assert (known.status, known.code) == (409, "tape_empty")
    assert known.message == "tape_empty", "a hardware error without text falls back to its code"


def test_deferred_snmp_failure_has_a_message() -> None:
    assert _DEFERRED_FAILURE_MESSAGES["snmp_query_failed"]


def test_offline_and_snmp_answer_fixed_sentences_and_keep_the_cause_for_the_log() -> None:
    """#378 M5: the printer's address or the SNMP error text never reaches the client."""
    offline = describe_print_error(PrinterOfflineError("cannot reach 192.0.2.10:9100: refused"))
    snmp = describe_print_error(SnmpQueryError("preflight SNMP failed: community hunter2"))
    assert offline.message == "The printer could not be reached."
    assert snmp.message == "The printer did not answer the status query."
    assert offline.log_detail == "cannot reach 192.0.2.10:9100: refused"
    assert snmp.log_detail == "preflight SNMP failed: community hunter2"


def test_fixed_classes_carry_no_log_detail() -> None:
    assert describe_print_error(SAMPLES[LookupFailedError]).log_detail is None
    assert describe_print_error(SAMPLES[UnsupportedTapeError]).log_detail is None
