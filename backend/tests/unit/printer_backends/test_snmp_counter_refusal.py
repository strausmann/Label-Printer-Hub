# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#393 review round 2: only an explicit refusal of the counter OID turns the counter off."""

from __future__ import annotations

import pytest
from app.printer_backends.snmp_helper import query_preflight
from pysnmp.proto import rfc1902, rfc1905

pytestmark = pytest.mark.anyio


def _fake(monkeypatch: pytest.MonkeyPatch, first_error: object, counter: object) -> None:
    async def fake_get_cmd(*args, **_kwargs):
        with_counter = len(args) - 4 == 4
        if with_counter and first_error is not None:
            return (None, first_error, 4, [])
        binds = [
            (args[4], rfc1902.Integer(3)),
            (args[5], rfc1902.OctetString(b"\x00\x00")),
            (args[6], rfc1902.OctetString("62mm")),
        ]
        if with_counter:
            binds.append((args[7], counter))
        return (None, None, 0, binds)

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)


@pytest.mark.parametrize(
    ("first_error", "counter", "refused"),
    [
        (rfc1902.Integer(2), None, True),  # noSuchName for the whole request
        (rfc1902.Integer(5), None, False),  # genErr: transient
        (None, rfc1905.noSuchObject, True),
        (None, rfc1905.noSuchInstance, True),
        (None, rfc1902.Counter32(5), False),
    ],
    ids=["noSuchName", "genErr", "noSuchObject", "noSuchInstance", "a counter"],
)
async def test_only_an_explicit_refusal_marks_the_counter_refused(
    monkeypatch: pytest.MonkeyPatch, first_error: object, counter: object, refused: bool
) -> None:
    _fake(monkeypatch, first_error, counter)
    status = await query_preflight("192.0.2.10")
    assert status.counter_refused is refused
    assert status.loaded_tape_mm == 62


def _fake_binds(monkeypatch: pytest.MonkeyPatch, status: object, blob: object) -> None:
    async def fake_get_cmd(*args, **_kwargs):
        binds = [
            (args[4], status),
            (args[5], blob),
            (args[6], rfc1902.OctetString("12mm")),
        ]
        if len(args) - 4 == 4:
            binds.append((args[7], rfc1902.Counter32(5)))
        return (None, None, 0, binds)

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)


@pytest.mark.parametrize(
    ("status", "blob"),
    [
        (rfc1902.OctetString(b"x"), rfc1902.OctetString(b"\x00")),  # int() of a text
        (rfc1902.Integer(3), rfc1902.Counter32(4_000_000_000)),  # bytes(n) would allocate n
        (rfc1902.Integer(3), rfc1902.Counter64(2**64 - 1)),
        (rfc1902.Integer(3), rfc1905.noSuchInstance),
    ],
    ids=["status-is-text", "bitmap-is-a-counter", "bitmap-is-counter64", "bitmap-missing"],
)
async def test_a_value_of_the_wrong_type_is_a_query_error(
    monkeypatch: pytest.MonkeyPatch, status: object, blob: object
) -> None:
    # Run 26, hardening note 2: an agent's value types are not trusted.
    from app.printer_backends.snmp_helper import SnmpQueryError

    _fake_binds(monkeypatch, status, blob)
    with pytest.raises(SnmpQueryError):
        await query_preflight("192.0.2.11")
