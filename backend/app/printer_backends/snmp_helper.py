"""SNMP query helpers — discovery (PJL string) + live status + preflight.

Uses pysnmp's asyncio API; the call is fully non-blocking, no thread
dispatch needed. SNMPv2c with a configurable community (default 'public').

pysnmp 7.x API note: UdpTransportTarget no longer accepts the address in
__init__; use ``await UdpTransportTarget.create((host, port), ...)`` instead.
"""

from __future__ import annotations

__all__ = [
    "LiveStatus",
    "PreflightStatus",
    "SnmpQueryError",
    "decode_error_flags",
    "parse_loaded_tape_mm",
    "query_live_status",
    "query_loaded_tape_mm",
    "query_model_pjl",
    "query_preflight",
]

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from app.printer_backends.exceptions import SnmpDiscoveryError, SnmpQueryError

_logger = logging.getLogger(__name__)

# Lazy SnmpEngine singleton.
#
# Rationale: a module-level ``SnmpEngine()`` created at import time binds to
# whatever asyncio event loop is active at that moment.  In test suites that
# spin up a fresh event loop for each test session the previously-bound engine
# raises ``RuntimeError: Event loop is closed`` on the next query.
#
# The lazy accessor ``_get_engine()`` detects a closed loop and re-creates the
# engine, giving each event-loop lifetime a healthy singleton while still
# avoiding the per-query overhead of constructing a new engine (MIB loading,
# dispatcher initialisation).
_SNMP_ENGINE: SnmpEngine | None = None


def _get_engine() -> SnmpEngine:
    """Return the module-level SnmpEngine singleton, creating it on first call.

    If the current asyncio event loop is closed (common in test suites that
    replace the loop between sessions) the stale engine is discarded and a
    fresh one is created for the new loop.
    """
    global _SNMP_ENGINE
    if _SNMP_ENGINE is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                _SNMP_ENGINE = None
        except RuntimeError:
            # No running event loop — treat the engine as stale.
            _SNMP_ENGINE = None
    if _SNMP_ENGINE is None:
        _SNMP_ENGINE = SnmpEngine()
    return _SNMP_ENGINE


BROTHER_PJL_OID = "1.3.6.1.4.1.2435.2.3.9.1.1.7.0"
HR_PRINTER_STATUS_OID = "1.3.6.1.2.1.25.3.5.1.1.1"
HR_PRINTER_DETECTED_ERROR_STATE_OID = "1.3.6.1.2.1.25.3.5.1.2.1"
PRT_INPUT_MEDIA_TYPE_OID = "1.3.6.1.2.1.43.8.2.1.12.1.1"

_PRINTER_STATUS_MAP: dict[int, Literal["other", "unknown", "idle", "printing", "warmup"]] = {
    1: "other",
    2: "unknown",
    3: "idle",
    4: "printing",
    5: "warmup",
}

# (byte_index, bitmask, flag_name) — RFC 3805 hrPrinterDetectedErrorState
_ERROR_BITS: tuple[tuple[int, int, str], ...] = (
    (0, 0x80, "lowPaper"),
    (0, 0x40, "noPaper"),
    (0, 0x20, "lowToner"),
    (0, 0x10, "noToner"),
    (0, 0x08, "doorOpen"),
    (0, 0x04, "jammed"),
    (0, 0x02, "offline"),
    (0, 0x01, "serviceRequested"),
    (1, 0x80, "inputTrayMissing"),
    (1, 0x40, "outputTrayMissing"),
    (1, 0x20, "markerSupplyMissing"),
    (1, 0x10, "outputFull"),
    (1, 0x08, "inputTrayEmpty"),
    (1, 0x04, "overduePreventMaint"),
)


def decode_error_flags(blob: bytes) -> list[str]:
    """Decode the hrPrinterDetectedErrorState OCTET STRING into bit names."""
    out: list[str] = []
    for byte_idx, mask, name in _ERROR_BITS:
        if byte_idx < len(blob) and blob[byte_idx] & mask:
            out.append(name)
    return out


@dataclass(frozen=True)
class LiveStatus:
    """Live phase + error flags read from SNMP during a print."""

    hr_printer_status: Literal["other", "unknown", "idle", "printing", "warmup"]
    error_flags: list[str] = field(default_factory=list)


_TAPE_MM_RE = re.compile(r"^\s*(\d+)\s*mm", re.IGNORECASE)


def parse_loaded_tape_mm(text: str) -> int | None:
    """Parse prtInputMediaType reply like '12mm(0.47")' → 12.

    Returns None for empty / unparsable replies (no tape inserted).
    """
    if not text:
        return None
    match = _TAPE_MM_RE.match(text)
    if not match:
        return None
    return int(match.group(1))


@dataclass(frozen=True)
class PreflightStatus:
    """Combined preflight: printer status + loaded tape + error bitmap."""

    hr_printer_status: Literal["other", "unknown", "idle", "printing", "warmup"]
    loaded_tape_mm: int | None
    error_flags: list[str] = field(default_factory=list)


async def query_loaded_tape_mm(
    host: str, *, community: str = "public", timeout_s: float = 3.0
) -> int | None:
    """Query prtInputMediaType OID and return the loaded tape width in mm."""
    error_indication, error_status, _, var_binds = await get_cmd(
        _get_engine(),
        CommunityData(community, mpModel=1),
        await UdpTransportTarget.create((host, 161), timeout=timeout_s, retries=0),
        ContextData(),
        ObjectType(ObjectIdentity(PRT_INPUT_MEDIA_TYPE_OID)),
    )
    if error_indication:
        raise SnmpQueryError(f"prtInputMediaType failed: {error_indication}")
    if error_status:
        raise SnmpQueryError(f"prtInputMediaType returned error: {error_status}")
    if not var_binds:
        return None
    return parse_loaded_tape_mm(str(var_binds[0][1]))


async def query_preflight(
    host: str, *, community: str = "public", timeout_s: float = 3.0
) -> PreflightStatus:
    """Single round-trip: status + error-state + loaded tape.

    Used by PTouchBackend.preflight_check() to validate before sending a
    print job. Raises SnmpQueryError on transport failure.
    """
    error_indication, error_status, _, var_binds = await get_cmd(
        _get_engine(),
        CommunityData(community, mpModel=1),
        await UdpTransportTarget.create((host, 161), timeout=timeout_s, retries=0),
        ContextData(),
        ObjectType(ObjectIdentity(HR_PRINTER_STATUS_OID)),
        ObjectType(ObjectIdentity(HR_PRINTER_DETECTED_ERROR_STATE_OID)),
        ObjectType(ObjectIdentity(PRT_INPUT_MEDIA_TYPE_OID)),
    )
    if error_indication:
        raise SnmpQueryError(f"preflight SNMP failed: {error_indication}")
    if error_status:
        raise SnmpQueryError(f"preflight SNMP returned error: {error_status}")
    if len(var_binds) < 3:
        raise SnmpQueryError("incomplete preflight reply")

    raw_status = int(var_binds[0][1])
    raw_error_blob = bytes(var_binds[1][1])
    raw_media_text = str(var_binds[2][1])

    return PreflightStatus(
        hr_printer_status=_PRINTER_STATUS_MAP.get(raw_status, "other"),
        loaded_tape_mm=parse_loaded_tape_mm(raw_media_text),
        error_flags=decode_error_flags(raw_error_blob),
    )


async def query_model_pjl(host: str, *, community: str = "public", timeout_s: float = 3.0) -> str:
    """Read Brother private OID → PJL identification string.

    Raises SnmpDiscoveryError on any failure (timeout, OID missing, refused).

    pysnmp 7.x requires ``await UdpTransportTarget.create(...)`` for address
    resolution; the monkeypatched get_cmd in tests bypasses this entirely.
    """
    transport = await UdpTransportTarget.create(
        (host, 161),
        timeout=timeout_s,
        retries=0,
    )
    error_indication, error_status, _, var_binds = await get_cmd(
        _get_engine(),
        CommunityData(community, mpModel=1),
        transport,
        ContextData(),
        ObjectType(ObjectIdentity(BROTHER_PJL_OID)),
    )
    if error_indication:
        raise SnmpDiscoveryError(f"SNMP discovery timed out / failed: {error_indication}")
    if error_status:
        raise SnmpDiscoveryError(f"SNMP returned error status: {error_status}")
    if not var_binds:
        raise SnmpDiscoveryError("Empty SNMP reply for PJL OID")
    return str(var_binds[0][1])


async def query_live_status(
    host: str, *, community: str = "public", timeout_s: float = 3.0
) -> LiveStatus:
    """Read hrPrinterStatus + hrPrinterDetectedErrorState in one round trip.

    Raises SnmpQueryError on any failure; this is non-fatal at request time
    (the live block is omitted from the /jobs/{id} response).
    """
    transport = await UdpTransportTarget.create(
        (host, 161),
        timeout=timeout_s,
        retries=0,
    )
    error_indication, error_status, _, var_binds = await get_cmd(
        _get_engine(),
        CommunityData(community, mpModel=1),
        transport,
        ContextData(),
        ObjectType(ObjectIdentity(HR_PRINTER_STATUS_OID)),
        ObjectType(ObjectIdentity(HR_PRINTER_DETECTED_ERROR_STATE_OID)),
    )
    if error_indication:
        raise SnmpQueryError(f"SNMP live-status timed out / failed: {error_indication}")
    if error_status:
        raise SnmpQueryError(f"SNMP returned error status: {error_status}")
    if len(var_binds) < 2:
        raise SnmpQueryError("Incomplete SNMP reply")

    raw_status = int(var_binds[0][1])
    raw_error_blob = bytes(var_binds[1][1])
    return LiveStatus(
        hr_printer_status=_PRINTER_STATUS_MAP.get(raw_status, "other"),
        error_flags=decode_error_flags(raw_error_blob),
    )
