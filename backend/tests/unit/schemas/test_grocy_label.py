"""The body of Grocy's label printer webhook and the label it becomes (#281, spec section 6).

The bodies are the ones Grocy's ``controllers/Api/*ApiController.php`` build (spec section 6,
Grocy commit ``146f73af``): a name field for the label type, the Grocycode, and for a stock
entry an optional ``due_date``.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.schemas.grocy_label import (
    GROCY_LABEL_BUDGET_S,
    GROCYCODE_PATTERN,
    MAX_GROCY_LABEL_BODY,
    GrocyLabelMismatchError,
    GrocyLabelPayload,
)
from pydantic import ValidationError


def test_constants() -> None:
    assert GROCYCODE_PATTERN == r"^grcy:(p|b|c|r):[0-9]{1,10}(:[^:\s]{1,64}){0,3}$"
    assert MAX_GROCY_LABEL_BODY == 1_048_576
    assert GROCY_LABEL_BUDGET_S == 1.5


def test_product_label() -> None:
    payload = GrocyLabelPayload.model_validate({"product": "Oat milk", "grocycode": "grcy:p:12"})
    assert payload.label_type == "product"
    raw = payload.to_raw_label()
    assert raw.title == "Oat milk"
    assert raw.primary_id == "12"
    assert raw.qr_payload == "grcy:p:12"
    assert raw.secondary == ()


def test_stock_entry_label_carries_its_due_date() -> None:
    payload = GrocyLabelPayload.model_validate(
        {
            "product": "Oat milk",
            "grocycode": "grcy:p:12:63a1b2c3d4e5f",
            "due_date": "DD: 2026-12-01",
        }
    )
    assert payload.label_type == "stock_entry"
    raw = payload.to_raw_label()
    assert raw.primary_id == "12"
    assert raw.qr_payload == "grcy:p:12:63a1b2c3d4e5f"
    assert raw.secondary == ("DD: 2026-12-01",)


def test_stock_entry_without_due_date_has_no_secondary() -> None:
    payload = GrocyLabelPayload.model_validate(
        {"product": "Oat milk", "grocycode": "grcy:p:12:63a1b2c3d4e5f"}
    )
    assert payload.label_type == "stock_entry"
    assert payload.to_raw_label().secondary == ()


def test_due_date_on_a_product_label_is_not_printed() -> None:
    payload = GrocyLabelPayload.model_validate(
        {"product": "Oat milk", "grocycode": "grcy:p:12", "due_date": "DD: 2026-12-01"}
    )
    assert payload.to_raw_label().secondary == ()


@pytest.mark.parametrize(
    ("body", "label_type", "title", "primary_id"),
    [
        ({"chore": "Descale kettle", "grocycode": "grcy:c:3"}, "chore", "Descale kettle", "3"),
        ({"battery": "Smoke alarm", "grocycode": "grcy:b:4"}, "battery", "Smoke alarm", "4"),
        ({"recipe": "Pancakes", "grocycode": "grcy:r:5"}, "recipe", "Pancakes", "5"),
    ],
)
def test_other_label_types(
    body: dict[str, Any], label_type: str, title: str, primary_id: str
) -> None:
    payload = GrocyLabelPayload.model_validate(body)
    assert payload.label_type == label_type
    raw = payload.to_raw_label()
    assert (raw.title, raw.primary_id, raw.qr_payload) == (title, primary_id, body["grocycode"])
    assert raw.secondary == ()


@pytest.mark.parametrize(
    "code",
    [
        "grocy:p:12",  # not the official magic
        "grcy:x:1",  # unknown entity
        "grcy:p:",  # no id
        "grcy:p:abc",  # id not numeric
        "grcy:p:12345678901",  # 11 digits
        "grcy:p:12:a:b:c:d",  # four extra parts
        "grcy:p:12: x",  # whitespace in an extra part
        "grcy:p:12\n",  # trailing line break
        " grcy:p:12",
    ],
)
def test_codes_outside_the_grammar_are_refused(code: str) -> None:
    with pytest.raises(ValidationError):
        GrocyLabelPayload.model_validate({"product": "Oat milk", "grocycode": code})


def test_missing_code_is_refused() -> None:
    with pytest.raises(ValidationError):
        GrocyLabelPayload.model_validate({"product": "Oat milk"})


def test_product_code_with_only_a_chore_name_is_a_mismatch() -> None:
    payload = GrocyLabelPayload.model_validate(
        {"chore": "Descale kettle", "grocycode": "grcy:p:12"}
    )
    with pytest.raises(GrocyLabelMismatchError):
        payload.to_raw_label()


def test_name_that_cleans_to_nothing_is_a_mismatch() -> None:
    payload = GrocyLabelPayload.model_validate({"product": "\x00\x07 ", "grocycode": "grcy:p:12"})
    with pytest.raises(GrocyLabelMismatchError):
        payload.to_raw_label()


def test_unknown_and_non_object_fields_are_ignored() -> None:
    payload = GrocyLabelPayload.model_validate(
        {
            "product": "Oat milk",
            "grocycode": "grcy:p:12:63a1b2c3d4e5f",
            "stock_entry": "not an object",
            "details": {"description": "<img src='data:image/png;base64,AAAA'>"},
            "font_family": "Comic Sans",
        }
    )
    assert payload.label_type == "stock_entry"
    assert not hasattr(payload, "font_family")
    assert not hasattr(payload, "details")


def test_control_characters_are_cleaned() -> None:
    payload = GrocyLabelPayload.model_validate(
        {
            "product": "Oat\x00 milk‮\r\n2 l",
            "grocycode": "grcy:p:12:63a1",
            "due_date": "DD:\x07 2026-12-01",
        }
    )
    raw = payload.to_raw_label()
    assert raw.title == "Oat milk 2 l"
    assert raw.secondary == ("DD: 2026-12-01",)


def test_name_of_512_characters_is_accepted_and_513_refused() -> None:
    ok = GrocyLabelPayload.model_validate({"product": "x" * 512, "grocycode": "grcy:p:1"})
    assert ok.to_raw_label().title == "x" * 512
    with pytest.raises(ValidationError):
        GrocyLabelPayload.model_validate({"product": "x" * 513, "grocycode": "grcy:p:1"})


def test_due_date_over_64_characters_is_refused() -> None:
    with pytest.raises(ValidationError):
        GrocyLabelPayload.model_validate(
            {"product": "Oat milk", "grocycode": "grcy:p:1:2", "due_date": "d" * 65}
        )


def test_a_number_as_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        GrocyLabelPayload.model_validate({"product": 12, "grocycode": "grcy:p:12"})
