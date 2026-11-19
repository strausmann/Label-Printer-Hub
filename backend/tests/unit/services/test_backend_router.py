# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The print preflight asks with the printer's stored SNMP community (#296, R-296-6).

``PrintService`` calls ``preflight_check()`` without a community, so the backend the router
builds must carry the stored one; otherwise a printer with a custom community discovers fine
but every print fails as "offline". The SNMP query is patched and records its argument.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.printer_backends.snmp_helper import PreflightStatus
from app.services.backend_router import BackendRouter, PrinterYAMLConfig, SNMPConfig
from app.services.printer_runtime import tape_config

PLANTED = "s3cret-t1-community"

_CASES = [
    ("ptouch", "PT-P750W", "app.printer_backends.ptouch_backend.query_preflight"),
    ("brother_ql", "QL-820NWB", "app.printer_backends.brother_ql_backend.query_preflight"),
]


def _recorder(seen: list[tuple[str, str]]) -> Any:
    async def fake_preflight(
        host: str, *, community: str = "public", timeout_s: float = 3.0
    ) -> PreflightStatus:
        seen.append((host, community))
        return PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, error_flags=[])

    return fake_preflight


@pytest.mark.asyncio
@pytest.mark.parametrize(("backend", "model", "target"), _CASES)
async def test_preflight_uses_stored_community(
    monkeypatch: pytest.MonkeyPatch, backend: str, model: str, target: str
) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(target, _recorder(seen))
    cfg = PrinterYAMLConfig(
        slug="workshop",
        name="workshop",
        backend=backend,  # type: ignore[arg-type]
        model=model,
        host="192.0.2.10",
        snmp=SNMPConfig(discover=True, community=PLANTED),
        cut_defaults={"half_cut": False},  # type: ignore[arg-type]
    )
    printer_backend = BackendRouter([cfg]).get("workshop")
    assert printer_backend is not None
    await printer_backend.preflight_check()
    assert seen == [("192.0.2.10", PLANTED)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("backend", "model", "target"), _CASES)
async def test_preflight_uses_community_of_the_stored_row(
    monkeypatch: pytest.MonkeyPatch, backend: str, model: str, target: str
) -> None:
    """From the DB row through ``tape_config`` to the backend the router builds."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(target, _recorder(seen))
    row = SimpleNamespace(
        slug="workshop",
        name="workshop",
        backend=backend,
        model=model,
        connection={"host": "192.0.2.10", "port": 9100, "snmp": {"community": PLANTED}},
        queue_timeout_s=30,
        cut_defaults_half_cut=False,
    )
    printer_backend = BackendRouter([tape_config(row)]).get("workshop")
    assert printer_backend is not None
    await printer_backend.preflight_check()
    assert seen == [("192.0.2.10", PLANTED)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("backend", "model", "target"), _CASES)
async def test_preflight_explicit_community_still_wins(
    monkeypatch: pytest.MonkeyPatch, backend: str, model: str, target: str
) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(target, _recorder(seen))
    cfg = PrinterYAMLConfig(
        slug="workshop",
        name="workshop",
        backend=backend,  # type: ignore[arg-type]
        model=model,
        host="192.0.2.10",
        snmp=SNMPConfig(discover=True, community=PLANTED),
        cut_defaults={"half_cut": False},  # type: ignore[arg-type]
    )
    printer_backend = BackendRouter([cfg]).get("workshop")
    assert printer_backend is not None
    await printer_backend.preflight_check(community="other")
    assert seen == [("192.0.2.10", "other")]
