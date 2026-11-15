# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The e2e control body can set and clear the fake page printer's default paper size."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.e2e_app import E2E_MEDIA_DEFAULT, _fake_state, _new_fake, _PageState, _reset_fake


def test_the_e2e_fake_reports_a4_like_the_real_hp() -> None:
    assert _new_fake().media_default == E2E_MEDIA_DEFAULT == "iso_a4_210x297mm"
    assert _fake_state(_new_fake())["media_default"] == "iso_a4_210x297mm"


def test_the_control_body_takes_a_media_default_and_an_empty_one_clears_it() -> None:
    assert _PageState.model_validate({"media_default": "na_letter_8.5x11in"}).media_default == (
        "na_letter_8.5x11in"
    )
    # "" means "none": ``exclude_none`` would drop a real None, so the body spells it out.
    assert _PageState.model_validate({"media_default": ""}).media_default == ""
    with pytest.raises(ValidationError):
        _PageState.model_validate({"media_default": "x" * 200})


def test_reset_restores_the_default() -> None:
    fake = _new_fake()
    fake.media_default = None
    _reset_fake(fake)
    assert fake.media_default == "iso_a4_210x297mm"


def test_the_control_body_takes_a_printer_uuid_and_an_empty_one_clears_it() -> None:
    uuid = "urn:uuid:11111111-2222-4333-8444-555555555555"
    assert _PageState.model_validate({"printer_uuid": uuid}).printer_uuid == uuid
    assert _PageState.model_validate({"printer_uuid": ""}).printer_uuid == ""
    with pytest.raises(ValidationError):
        _PageState.model_validate({"printer_uuid": "x" * 200})


def test_the_state_reports_the_uuid_and_reset_clears_it() -> None:
    fake = _new_fake()
    assert _fake_state(fake)["printer_uuid"] is None
    fake.printer_uuid = "urn:uuid:11111111-2222-4333-8444-555555555555"
    assert _fake_state(fake)["printer_uuid"] == fake.printer_uuid
    _reset_fake(fake)
    assert fake.printer_uuid is None
