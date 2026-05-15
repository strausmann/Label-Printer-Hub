from __future__ import annotations

import pytest
from app.schemas.print_request import (
    PrintLookupRequest,
    PrintOptions,
    PrintRequest,
    RawLabelData,
)
from pydantic import ValidationError


def test_print_options_defaults_independent() -> None:
    a = PrintRequest(template_id="t", data=RawLabelData(title="x", primary_id="1", qr_payload="u"))
    b = PrintRequest(template_id="t", data=RawLabelData(title="x", primary_id="1", qr_payload="u"))
    assert a.options is not b.options


def test_print_options_immutable() -> None:
    opts = PrintOptions()
    with pytest.raises(ValidationError):
        opts.copies = 5


def test_lookup_xor_data_rejects_both() -> None:
    with pytest.raises(ValidationError, match="Exactly one"):
        PrintRequest(
            template_id="t",
            lookup=PrintLookupRequest(app="snipeit", identifier="123"),
            data=RawLabelData(title="x", primary_id="1", qr_payload="u"),
        )


def test_lookup_xor_data_rejects_neither() -> None:
    with pytest.raises(ValidationError, match="Exactly one"):
        PrintRequest(template_id="t")


def test_lookup_only_accepted() -> None:
    r = PrintRequest(template_id="t", lookup=PrintLookupRequest(app="snipeit", identifier="123"))
    assert r.lookup is not None
    assert r.data is None


def test_data_only_accepted() -> None:
    r = PrintRequest(
        template_id="t",
        data=RawLabelData(title="x", primary_id="1", qr_payload="u", secondary=["a", "b"]),
    )
    assert r.data is not None
    assert r.lookup is None
    assert r.data.secondary == ["a", "b"]


def test_raw_label_data_default_secondary_empty() -> None:
    d = RawLabelData(title="x", primary_id="1", qr_payload="u")
    assert d.secondary == []


def test_raw_label_data_rejects_source_app_field() -> None:
    with pytest.raises(ValidationError):
        RawLabelData(title="x", primary_id="1", qr_payload="u", source_app="manual")


def test_copies_bounds() -> None:
    PrintOptions(copies=1)
    PrintOptions(copies=10)
    with pytest.raises(ValidationError):
        PrintOptions(copies=0)
    with pytest.raises(ValidationError):
        PrintOptions(copies=11)


def test_on_tape_mismatch_defaults_to_fail() -> None:
    r = PrintRequest(template_id="t", data=RawLabelData(title="x", primary_id="1", qr_payload="u"))
    assert r.on_tape_mismatch == "fail"


def test_on_tape_mismatch_accepts_queue() -> None:
    r = PrintRequest(
        template_id="t",
        data=RawLabelData(title="x", primary_id="1", qr_payload="u"),
        on_tape_mismatch="queue",
    )
    assert r.on_tape_mismatch == "queue"


def test_on_tape_mismatch_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        PrintRequest(
            template_id="t",
            data=RawLabelData(title="x", primary_id="1", qr_payload="u"),
            on_tape_mismatch="abort",  # not in the Literal set
        )
