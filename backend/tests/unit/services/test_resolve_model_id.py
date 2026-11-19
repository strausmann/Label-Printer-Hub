# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``_resolve_model_id_from_config`` falls back to the configured model (#166, #207)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.printer_backends.exceptions import SnmpDiscoveryError
from app.printer_models.registry import ModelNotFoundError
from app.services.backend_router import PrinterYAMLConfig, SNMPConfig
from app.services.printer_runtime import _resolve_model_id_from_config
from pyasn1.error import PyAsn1Error
from pysnmp.error import PySnmpError


def _cfg() -> PrinterYAMLConfig:
    return PrinterYAMLConfig.model_construct(
        slug="p1",
        model="QL-820NWB",
        host="printer.example.invalid",
        snmp=SNMPConfig(discover=True, community="public"),
    )


async def test_foreign_pjl_falls_back_to_the_configured_model() -> None:
    with patch(
        "app.services.printer_runtime.query_model_pjl",
        AsyncMock(return_value="MFG:Other;MDL:X-1;"),
    ):
        assert await _resolve_model_id_from_config(_cfg()) == "QL-820NWB"


@pytest.mark.parametrize(
    "error",
    [
        PySnmpError("dns"),
        PyAsn1Error("bad"),
        SnmpDiscoveryError("timeout"),
        OSError("unreachable"),
        TimeoutError("slow"),
    ],
)
async def test_snmp_errors_fall_back(error: Exception) -> None:
    with patch("app.services.printer_runtime.query_model_pjl", AsyncMock(side_effect=error)):
        assert await _resolve_model_id_from_config(_cfg()) == "QL-820NWB"


async def test_foreign_pjl_without_a_configured_model_still_raises() -> None:
    cfg = _cfg()
    cfg.model = ""
    with (
        patch(
            "app.services.printer_runtime.query_model_pjl",
            AsyncMock(return_value="MFG:Other;MDL:X-1;"),
        ),
        pytest.raises(ModelNotFoundError),
    ):
        await _resolve_model_id_from_config(cfg)
