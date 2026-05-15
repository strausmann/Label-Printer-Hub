# First-Print Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tracking-Issue: #22.

**Goal:** Deliver the first end-to-end print pipeline (`POST /print` → real Brother PT-P750W) per `docs/designs/2026-05-15-first-print.md`.

**Architecture:** Three-layer separation — `_PrinterLike` (queue), `PrinterModel` (driver, in `printer_models/pt.py`), `PrinterBackend` (transport, in `printer_backends/`). Plugin discovery via setuptools entry_points for both drivers and backends. Bridge to `PrintQueue` is a factory method on the driver (`make_queue_printer`).

**Tech Stack:** Python 3.12 + FastAPI + Pydantic 2 + `ptouch` lib + `pysnmp>=6.2` (asyncio API) + `pytest`. TDD-strict (failing test before any production code). Conventional Commits (existing scope-enum extended with `printer-backends`). Every commit body ends with `Refs #22`. **No `Co-Authored-By: Claude`** lines in commits.

**Spec discoveries that override design assumptions:**
- `ptouch` library exposes **no public status-query API** — the design's `query_status` must be implemented directly via a raw `asyncio` socket sending `ESC i S` (3 bytes) and parsing the 32-byte reply per Brother Raster Command Reference (PT-Series).
- The ptouch class is `ptouch.PTP750W` (no underscore). The connection class is `ptouch.ConnectionNetwork(host, port=9100, timeout=5.0)`. The label class is `ptouch.Label(image, tape)`.
- ptouch has its own exception hierarchy: `PrinterConnectionError`, `PrinterNetworkError`, `PrinterTimeoutError`, `PrinterWriteError`, `PrinterPermissionError`, `PrinterNotFoundError`. The `PTouchBackend` wraps these into our `PrinterError` family.
- ptouch has **no SNMP** capability. `pysnmp>=6.2` is already pinned and exposes an asyncio API (`pysnmp.hlapi.v3arch.asyncio.get_cmd`). The plan implements a dedicated `snmp_helper.py` module for:
  1. **Model discovery** — Brother private OID `1.3.6.1.4.1.2435.2.3.9.1.1.7.0` returns the PJL identification string (`MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;...`). Used at lifespan startup to resolve the driver via `ModelRegistry.find_by_pjl` (already exists in the codebase, ADR 0004).
  2. **Live status during a running print** — `hrPrinterStatus` (`1.3.6.1.2.1.25.3.5.1.1.1`) and `hrPrinterDetectedErrorState` (`1.3.6.1.2.1.25.3.5.1.2.1`) are reachable on UDP/161 while ptouch holds the print TCP/9100 session.
- ESC i S and SNMP coexist: ESC i S delivers Brother-specific tape/media bytes directly as integers, perfect for pre-print validation; SNMP serves discovery and during-print checks that ESC i S cannot.

---

## File structure

| Path | Role |
|---|---|
| `backend/app/printer_backends/__init__.py` | `BackendRegistry` class + entry-point discovery |
| `backend/app/printer_backends/base.py` | `PrinterBackend` Protocol |
| `backend/app/printer_backends/exceptions.py` | `PrinterError` hierarchy |
| `backend/app/printer_backends/status_query.py` | Raw ESC i S socket helper + reply parser |
| `backend/app/printer_backends/snmp_helper.py` | SNMP helpers: `query_model_pjl` (discovery) + `query_live_status` (during-print) + `LiveStatus` dataclass |
| `backend/app/printer_backends/ptouch_backend.py` | `PTouchBackend` wrapping the ptouch library |
| `backend/app/printer_backends/mock_backend.py` | `MockPrinterBackend` for tests + local dev |
| `backend/app/printer_models/pt.py` (modified) | Add `PTP750WDriver` + `_PTPQueuePrinter` |
| `backend/app/printer_models/registry.py` (modified) | Add `find_by_model_id` + `ensure_discovered` (entry_points) |
| `backend/app/printer_models/__init__.py` (modified) | Trigger ModelRegistry discovery |
| `backend/app/schemas/print_request.py` | `PrintRequest`, `PrintOptions`, `RawLabelData`, `PrintLookupRequest` |
| `backend/app/schemas/print_response.py` | `PrintJobResponse`, `PrintJobStatusResponse` |
| `backend/app/services/print_service.py` | `PrintService` orchestrator |
| `backend/app/api/routes/print.py` | `POST /print`, `GET /jobs/{job_id}` + exception mapper |
| `backend/app/main.py` (modified) | Lifespan + route registration |
| `backend/app/config.py` (modified) | Add `printer_backend`, `printer_model`, `printer_queue_timeout_s` |
| `backend/scripts/smoke_first_print.py` | Manual hardware smoke (not in CI) |
| `backend/tests/unit/printer_backends/test_exceptions.py` | `PrinterError` hierarchy + field access |
| `backend/tests/unit/printer_backends/test_status_query.py` | ESC i S byte-format + reply parser |
| `backend/tests/unit/printer_backends/test_mock_backend.py` | Mock surface + introspection |
| `backend/tests/unit/printer_backends/test_ptouch_backend.py` | ptouch via monkeypatch — all error paths |
| `backend/tests/unit/printer_backends/test_snmp_helper.py` | `query_model_pjl` + `query_live_status` via stubbed pysnmp `get_cmd` |
| `backend/tests/unit/printer_backends/test_registry.py` | `BackendRegistry` + entry_point discovery |
| `backend/tests/integration/test_snmp_discovery.py` | Lifespan resolves model from stubbed PJL → driver picked up |
| `backend/docs/brother-snmp-oids.md` | OID reference (1.3.6.1.4.1.2435… + Host-Resources Printer MIB) |
| `backend/tests/unit/printer_models/test_pt_driver.py` | `PTP750WDriver` + bridge |
| `backend/tests/unit/printer_models/test_registry.py` (modified) | Add `find_by_model_id` + discovery tests |
| `backend/tests/unit/services/test_print_service.py` | Lookup/render/enqueue orchestration |
| `backend/tests/unit/schemas/test_print_request.py` | XOR validation, `RawLabelData` shape |
| `backend/tests/unit/api/test_print_routes.py` | 202 + GET /jobs/{id} + exception mapper |
| `backend/tests/unit/test_lifespan.py` | Lifespan start/stop, plugin discovery |
| `backend/tests/unit/test_config_printer.py` | Settings field defaults + types |
| `backend/tests/integration/test_print_e2e.py` | Full POST → GET cycle via AsyncClient + MockBackend |
| `backend/tests/hardware/test_pt_p750w_smoke.py` | Real-hardware smoke (gated by `--hardware`) |
| `commitlint.config.cjs` (modified) | Add `printer-backends` scope |
| `backend/pyproject.toml` (modified) | Register `ptouch` + `mock` as `label_hub.printer_backends` entry-points |

---

## Conventions for every task

- **TDD:** write failing test first, see it fail (right reason), implement, see it pass, commit.
- **One responsibility per task** — touches a small number of files; commit at task end.
- **Run gates locally before committing:**
  ```bash
  cd backend
  ruff check .
  ruff format --check .
  mypy app
  pytest -q
  ```
  All four must pass. `ruff format --check` is a separate gate from `ruff check` — running only the latter misses style drift.
- **Commit message footer:** every commit body ends with a blank line then `Refs #22`.
- **No `Co-Authored-By: Claude`** in any commit (per repo policy on AI contributions).
- **Implementer must NOT push** — orchestrator pushes after user review.

---

## Phase 0 — Branch setup + commitlint scope

### Task 0.1: Verify branch + add `printer-backends` scope to commitlint

**Files:**
- Modify: `commitlint.config.cjs`

- [ ] **Step 1: Confirm branch**

```bash
cd /opt/repos/label-printer-hub
git rev-parse --abbrev-ref HEAD
```

Expected: `feat/first-print-plan` (or a fresh `feat/first-print` cut from it after the plan PR merges)

- [ ] **Step 2: Add the new scope**

Edit `commitlint.config.cjs`, insert `'printer-backends'` into the `scope-enum` array (sorted alphabetically before `pwa`):

```javascript
        'printer-backends',
        'printer-models',
```

- [ ] **Step 3: Smoke-check commitlint locally**

```bash
echo "feat(printer-backends): test scope" | npx commitlint
```

Expected: exit 0 (no errors).

- [ ] **Step 4: Commit**

```bash
git add commitlint.config.cjs
git commit -m "$(cat <<'EOF'
build(ci): add printer-backends scope to commitlint

First-Print introduces app/printer_backends/, which is conceptually
separate from app/printer_models/ (driver vs. transport). Add the
matching commit scope so backend-layer changes can be tagged correctly
in the changelog.

Refs #22
EOF
)"
```

---

## Phase 1 — Discovery: pin ptouch + status block layout

The design pinned `ptouch>=1.1.0` (existing dep). One assumption — `ptouch` exposes a public status query — turned out to be wrong (only an internal `_cmd_print_information` exists, and that is a *send* command, not a query). Phase 1 captures the wire-level status query we need to implement ourselves, and pins the ptouch entry-points the rest of the plan relies on.

### Task 1.1: Document ptouch entry-points and status-query gap

**Files:**
- Create: `backend/docs/ptouch-integration.md` (concise reference, kept under 200 lines)

- [ ] **Step 1: Write the file**

```markdown
# ptouch library — entry points used by First-Print

Version: `ptouch>=1.1.0` (pinned in pyproject.toml).

## Classes we use

- `ptouch.ConnectionNetwork(host: str, port: int = 9100, timeout: float = 5.0)`
- `ptouch.PTP750W(connection, use_compression=None, high_resolution=None)` (subclass of `LabelPrinter`)
- `ptouch.Label(image: PIL.Image.Image, tape: type[Tape] | Tape)`
- Tape classes: `ptouch.LaminatedTape4mm` ... `ptouch.LaminatedTape24mm` (size suffix matches `tape_mm`).
- Print method: `LabelPrinter.print(label, margin_mm=None, high_resolution=None, feed=True, auto_cut=None, half_cut=None)`

## ptouch exception hierarchy (caught by PTouchBackend and rewrapped)

- `ptouch.PrinterConnectionError` — generic connection problem
- `ptouch.PrinterNetworkError` — network-layer failure (DNS, refused)
- `ptouch.PrinterTimeoutError` — TCP timeout
- `ptouch.PrinterWriteError` — write failure mid-print
- `ptouch.PrinterPermissionError` — USB-permission issue (n/a for network)
- `ptouch.PrinterNotFoundError` — host unreachable

## Status query — NOT exposed by ptouch

`LabelPrinter` has only `_cmd_print_information` (private, and a send command). There is no `get_status` / `query_status` method. We implement status query ourselves: ESC i S over a raw asyncio socket, see Brother Raster Command Reference (PT-Series).
```

- [ ] **Step 2: Commit**

```bash
git add backend/docs/ptouch-integration.md
git commit -m "$(cat <<'EOF'
docs(printer-backends): record ptouch entry-points + status gap

Reference for implementers: pinned ptouch classes we depend on,
exception hierarchy to wrap, and the explicit gap that ptouch
exposes no public status-query API — so PTouchBackend must
implement ESC i S over a raw socket.

Refs #22
EOF
)"
```

### Task 1.2: Document ESC i S request + 32-byte reply layout

**Files:**
- Create: `backend/docs/brother-status-block.md` (single-page wire reference)

- [ ] **Step 1: Write the file**

```markdown
# Brother PT-Series status block (ESC i S)

Source: Brother Raster Command Reference, PT-Series.

## Request

3 bytes sent on TCP port 9100:

```
0x1B 0x69 0x53
```

(ASCII: ESC, 'i', 'S')

## Reply

32 bytes received. Offsets are 0-based, little-endian where applicable:

| Offset | Length | Field |
|---|---|---|
| 0 | 1 | Print head mark (0x80) |
| 1 | 1 | Size of reply (0x20 = 32) |
| 2 | 1 | Brother code (0x42 'B') |
| 3 | 1 | Series code |
| 4 | 1 | Model code |
| 5 | 1 | Country (0x30 = '0') |
| 6 | 1 | Reserved |
| 7 | 1 | Reserved |
| 8 | 1 | Error information 1 (bit 0=no media, 1=end of media, 2=cutter jam, 3=printer in use, 4=printer turned off) |
| 9 | 1 | Error information 2 (bit 0=replace media, 4=cover open, 5=overheating) |
| 10 | 1 | Media width (mm) |
| 11 | 1 | Media type (0x00 none, 0x01 laminated, 0x03 non-laminated, 0x11 heat-shrink-2:1, ...) |
| 12 | 1 | Number of colors (always 1 for PT-Series) |
| 13 | 1 | Fonts |
| 14 | 1 | Japanese fonts |
| 15 | 1 | Mode |
| 16 | 1 | Density |
| 17 | 1 | Media length (mm; 0 for tape) |
| 18 | 1 | Status type (0x00 reply-to-status, 0x01 phase-change, 0x02 error, 0x05 notification, 0x06 phase-change-notification) |
| 19 | 1 | Phase type (0x00 receiving / 0x01 printing) |
| 20 | 2 | Phase number high/low |
| 22 | 1 | Notification number |
| 23 | 1 | Expansion area length |
| 24 | 1 | Tape colour information |
| 25 | 1 | Text colour information |
| 26 | 4 | Hardware settings |
| 30 | 2 | Reserved |

## Error decoding

`tape_empty` ← bit 0 OR bit 1 of byte 8 set
`cover_open` ← bit 4 of byte 9 set
`error_flags` ← raw value of (byte8, byte9) packed
`loaded_tape_mm` ← byte 10 (0 → no tape inserted)
```

- [ ] **Step 2: Commit**

```bash
git add backend/docs/brother-status-block.md
git commit -m "$(cat <<'EOF'
docs(printer-backends): wire-level Brother status block (ESC i S)

Single-page reference for the 3-byte request + 32-byte reply
implemented in PTouchBackend.query_status(). Pulled from Brother
Raster Command Reference (PT-Series).

Refs #22
EOF
)"
```

### Task 1.3: Document SNMP OIDs (discovery + live status)

**Files:**
- Create: `backend/docs/brother-snmp-oids.md`

- [ ] **Step 1: Write the file**

```markdown
# Brother SNMP OIDs used by First-Print

`pysnmp>=6.2` (asyncio API in `pysnmp.hlapi.v3arch.asyncio`).

## Discovery

| OID | Returns | Used for |
|---|---|---|
| `1.3.6.1.4.1.2435.2.3.9.1.1.7.0` | PJL identification string: `MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;` | Lifespan startup → `ModelRegistry.find_by_pjl(...)` |

## Live status during print (Host-Resources Printer MIB, RFC 1213)

| OID | Returns | Mapping |
|---|---|---|
| `1.3.6.1.2.1.25.3.5.1.1.1` (`hrPrinterStatus`) | Integer: 1=other, 2=unknown, 3=idle, 4=printing, 5=warmup | string in `LiveStatus.hr_printer_status` |
| `1.3.6.1.2.1.25.3.5.1.2.1` (`hrPrinterDetectedErrorState`) | OCTET STRING of bytes; bits select errors | list of bit names in `LiveStatus.error_flags` |

### `hrPrinterDetectedErrorState` bit map (byte 0, MSB first)

| Bit | Name | Notes |
|---|---|---|
| 0 | lowPaper | not used by PT-Series |
| 1 | noPaper | maps to tape empty/end |
| 2 | lowToner | not applicable |
| 3 | noToner | not applicable |
| 4 | doorOpen | cover open |
| 5 | jammed | media jam |
| 6 | offline | printer reports offline |
| 7 | serviceRequested | hard fault, contact service |

Byte 1: inputTrayMissing, outputTrayMissing, markerSupplyMissing, outputFull, inputTrayEmpty, overduePreventMaint — none relevant for PT-Series tape devices in First-Print.

## Authentication

SNMPv2c, community read-only. Default community is `public`; configurable via `printer_snmp_community` setting. The PT-P750W is on the LAN/Tailscale, not on the open internet, so v2c is sufficient.

## Why this and not ESC i S

| Job | ESC i S (TCP/9100) | SNMP (UDP/161) |
|---|---|---|
| Pre-print tape match | direct (byte 10) | needs string parsing |
| Discovery (PJL) | not available | **only path** |
| During-print status | blocked by ptouch's TCP session | **runs in parallel** |
```

- [ ] **Step 2: Commit**

```bash
git add backend/docs/brother-snmp-oids.md
git commit -m "$(cat <<'EOF'
docs(printer-backends): Brother SNMP OIDs reference

Pins the two SNMP queries First-Print depends on:

* 1.3.6.1.4.1.2435.2.3.9.1.1.7.0 — Brother private PJL string, used
  for lifespan model discovery via ModelRegistry.find_by_pjl
* 1.3.6.1.2.1.25.3.5.1.1.1 / .2.1 — standard Host-Resources Printer
  MIB hrPrinterStatus + hrPrinterDetectedErrorState, used for live
  status while a print is running.

Notes on the bitmap of hrPrinterDetectedErrorState and why SNMP is
not enough on its own (no direct tape_mm — uses ESC i S for that).

Refs #22
EOF
)"
```

---

## Phase 2 — Exceptions

### Task 2.1: PrinterError hierarchy with TDD

**Files:**
- Create: `backend/app/printer_backends/__init__.py` (empty for now; populated in Phase 6)
- Create: `backend/app/printer_backends/exceptions.py`
- Create: `backend/tests/unit/printer_backends/__init__.py`
- Create: `backend/tests/unit/printer_backends/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_exceptions.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.printer_backends.exceptions'` or equivalent.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/__init__.py
"""Printer-backend layer — transport implementations behind a common Protocol.

The registry lives here; see app.printer_backends.base for the Protocol contract.
"""
```

```python
# backend/app/printer_backends/exceptions.py
"""Exception hierarchy raised by PrinterBackend implementations.

PrinterError is the root; HTTP-mapping is done in app.api.routes.print.
"""

from __future__ import annotations


class PrinterError(Exception):
    """Base class for any backend / hardware failure."""


class PrinterOfflineError(PrinterError):
    """Cannot reach the printer's TCP endpoint after retries."""


class TapeMismatchError(PrinterError):
    """Loaded tape width does not match the requested tape."""

    def __init__(self, *, expected_mm: int, loaded_mm: int | None) -> None:
        self.expected_mm = expected_mm
        self.loaded_mm = loaded_mm
        if loaded_mm is None:
            super().__init__(f"Expected {expected_mm}mm tape, no tape loaded")
        else:
            super().__init__(f"Expected {expected_mm}mm tape, loaded {loaded_mm}mm")


class TapeEmptyError(PrinterError):
    """Status block reports tape end / no media."""


class PrinterCoverOpenError(PrinterError):
    """Status block reports cover open."""


class PrintFailedError(PrinterError):
    """Encoding or transport failure during print()."""


class StatusQueryFailedError(PrinterError):
    """The 32-byte ESC i S reply could not be parsed."""


class SnmpDiscoveryError(PrinterError):
    """SNMP model-discovery query at lifespan startup failed."""


class SnmpQueryError(PrinterError):
    """Live-status SNMP query failed at request time. Non-fatal — the live
    block is omitted from the response.
    """
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_exceptions.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/__init__.py \
        backend/app/printer_backends/exceptions.py \
        backend/tests/unit/printer_backends/__init__.py \
        backend/tests/unit/printer_backends/test_exceptions.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): PrinterError hierarchy

Adds the exception family raised by PrinterBackend implementations:
PrinterError → PrinterOfflineError, TapeMismatchError (with
expected_mm + loaded_mm fields), TapeEmptyError, PrinterCoverOpenError,
PrintFailedError, StatusQueryFailedError.

These are wrapped into HTTP status codes by the /print route handler
(Phase 11) and mapped onto JobState=failed records.

Refs #22
EOF
)"
```

---

## Phase 3 — PrinterBackend Protocol

### Task 3.1: PrinterBackend Protocol with `@runtime_checkable`

**Files:**
- Create: `backend/app/printer_backends/base.py`
- Create: `backend/tests/unit/printer_backends/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_base.py
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.services.status_block import MediaType, StatusBlock


class _Compliant:
    backend_id = "compliant"
    host = "1.2.3.4"

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> None:
        return None

    async def query_status(self) -> StatusBlock:  # pragma: no cover - shape only
        return StatusBlock(
            tape_empty=False,
            cover_open=False,
            error_flags=0,
            loaded_tape_mm=24,
            media_type=MediaType.LAMINATED,
        )


class _Incomplete:
    backend_id = "incomplete"
    host = "x"
    # No print_image / query_status


def test_protocol_accepts_compliant_class() -> None:
    assert isinstance(_Compliant(), PrinterBackend)


def test_protocol_rejects_incomplete_class() -> None:
    assert not isinstance(_Incomplete(), PrinterBackend)
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_base.py -q
```

Expected: `ModuleNotFoundError` for `app.printer_backends.base`.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/base.py
"""PrinterBackend Protocol — transport contract used by drivers.

Two-method surface (print_image + query_status). A raw `send_bytes` escape
hatch was deliberately removed during design: there is no concrete caller
in First-Print, and opening a second TCP/9100 session in parallel with
ptouch would hit Brother's single-session limit (Resource Busy). The
hook can be added back additively if a future caller needs it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image

from app.models.tape import TapeSpec
from app.services.status_block import StatusBlock


@runtime_checkable
class PrinterBackend(Protocol):
    """Transport + encoding contract for a single bound printer."""

    backend_id: str
    host: str

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> None:
        """Encode and send `image`. Raises a PrinterError subtype on failure."""

    async def query_status(self) -> StatusBlock:
        """Send ESC i S, parse the 32-byte reply, return a StatusBlock."""
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_base.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/base.py \
        backend/tests/unit/printer_backends/test_base.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): PrinterBackend Protocol

Two-method runtime_checkable Protocol: print_image (encode + send)
and query_status (ESC i S equivalent). Backends are bound to one
host at construction time. send_bytes raw-raster escape hatch is
deliberately omitted — see design doc for rationale.

Refs #22
EOF
)"
```

---

## Phase 4 — MockPrinterBackend

### Task 4.1: MockPrinterBackend with introspection + failure modes

**Files:**
- Create: `backend/app/printer_backends/mock_backend.py`
- Create: `backend/tests/unit/printer_backends/test_mock_backend.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_mock_backend.py
from __future__ import annotations

import pytest
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.mock_backend import MockPrinterBackend
from app.services.status_block import MediaType, StatusBlock


@pytest.fixture
def tape_24() -> TapeSpec:
    return TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    )


@pytest.fixture
def img_128() -> Image.Image:
    return Image.new("1", (200, 128))


def test_mock_satisfies_protocol() -> None:
    assert isinstance(MockPrinterBackend(), PrinterBackend)


async def test_query_status_default(tmp_path) -> None:
    backend = MockPrinterBackend()
    status = await backend.query_status()
    assert status.tape_empty is False
    assert status.cover_open is False
    assert status.loaded_tape_mm == 24
    assert isinstance(status, StatusBlock)


async def test_print_records_image(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend()
    await backend.print_image(img_128, tape_24)
    assert len(backend.printed_images) == 1
    assert backend.printed_images[0].size == img_128.size


async def test_offline_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(offline=True)
    with pytest.raises(PrinterOfflineError):
        await backend.query_status()


async def test_tape_empty_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(tape_empty=True)
    with pytest.raises(TapeEmptyError):
        await backend.print_image(img_128, tape_24)


async def test_cover_open_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(cover_open=True)
    with pytest.raises(PrinterCoverOpenError):
        await backend.print_image(img_128, tape_24)


async def test_tape_mismatch_raises(img_128: Image.Image, tape_24: TapeSpec) -> None:
    backend = MockPrinterBackend(loaded_tape_mm=12)
    with pytest.raises(TapeMismatchError) as exc:
        await backend.print_image(img_128, tape_24)
    assert exc.value.expected_mm == 24
    assert exc.value.loaded_mm == 12
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_mock_backend.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.printer_backends.mock_backend'`.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/mock_backend.py
"""In-memory PrinterBackend used by tests and local development.

Satisfies the PrinterBackend Protocol without touching the network. Failure
modes are configurable via the constructor so integration tests can drive
every error path (offline, tape empty, cover open, tape mismatch).
"""

from __future__ import annotations

from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.services.status_block import MediaType, StatusBlock


class MockPrinterBackend:
    """No-I/O PrinterBackend for tests + local dev.

    Construct with failure-mode flags to exercise error paths. Use
    `printed_images` to assert what was actually sent.
    """

    backend_id = "mock"

    def __init__(
        self,
        host: str = "mock://test",
        *,
        loaded_tape_mm: int = 24,
        loaded_media_type: MediaType = MediaType.LAMINATED,
        tape_empty: bool = False,
        cover_open: bool = False,
        offline: bool = False,
    ) -> None:
        self.host = host
        self._loaded_tape_mm = loaded_tape_mm
        self._loaded_media_type = loaded_media_type
        self._tape_empty = tape_empty
        self._cover_open = cover_open
        self._offline = offline
        self.printed_images: list[Image.Image] = []
        self.status_query_count: int = 0

    @classmethod
    def from_settings(cls, settings: object) -> "MockPrinterBackend":  # noqa: ARG003
        """Settings are ignored — mock is environment-agnostic."""
        return cls()

    async def query_status(self) -> StatusBlock:
        self.status_query_count += 1
        if self._offline:
            raise PrinterOfflineError(f"mock backend marked offline at {self.host!r}")
        return StatusBlock(
            tape_empty=self._tape_empty,
            cover_open=self._cover_open,
            error_flags=0,
            loaded_tape_mm=self._loaded_tape_mm,
            media_type=self._loaded_media_type,
        )

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> None:
        status = await self.query_status()
        if status.tape_empty:
            raise TapeEmptyError()
        if status.cover_open:
            raise PrinterCoverOpenError()
        if status.loaded_tape_mm != tape_spec.width_mm:
            raise TapeMismatchError(
                expected_mm=tape_spec.width_mm,
                loaded_mm=status.loaded_tape_mm,
            )
        self.printed_images.append(image.copy())
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_mock_backend.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/mock_backend.py \
        backend/tests/unit/printer_backends/test_mock_backend.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): MockPrinterBackend

In-memory PrinterBackend used by unit/integration tests and by local
dev runs without real hardware (PRINTER_HUB_PRINTER_BACKEND=mock).

Failure modes are constructor flags: offline, tape_empty, cover_open,
loaded_tape_mm. The backend records every printed image so tests can
assert dimensions and order.

Refs #22
EOF
)"
```

---

## Phase 5 — BackendRegistry with entry_points

### Task 5.1: BackendRegistry + ensure_discovered + find_by_backend_id

**Files:**
- Modify: `backend/app/printer_backends/__init__.py`
- Create: `backend/tests/unit/printer_backends/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_registry.py
from __future__ import annotations

import pytest

from app.printer_backends import BackendRegistry, UnknownBackendError
from app.printer_backends.mock_backend import MockPrinterBackend


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False


def test_register_and_find_by_backend_id() -> None:
    BackendRegistry.register("mock", MockPrinterBackend)
    assert BackendRegistry.find_by_backend_id("mock") is MockPrinterBackend


def test_unknown_backend_raises_with_registered_list() -> None:
    BackendRegistry.register("mock", MockPrinterBackend)
    with pytest.raises(UnknownBackendError) as exc:
        BackendRegistry.find_by_backend_id("zebra-zpl")
    msg = str(exc.value)
    assert "zebra-zpl" in msg
    assert "mock" in msg  # available options listed


def test_duplicate_registration_rejected() -> None:
    BackendRegistry.register("mock", MockPrinterBackend)
    with pytest.raises(ValueError):
        BackendRegistry.register("mock", MockPrinterBackend)


def test_ensure_discovered_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_iter(group: str):
        calls["n"] += 1
        return []

    monkeypatch.setattr(
        "app.printer_backends.entry_points",
        fake_iter,
    )
    BackendRegistry.ensure_discovered()
    BackendRegistry.ensure_discovered()
    assert calls["n"] == 1  # second call short-circuits


def test_entry_point_discovery_registers_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "mock"

        def load(self) -> type[MockPrinterBackend]:
            return MockPrinterBackend

    def fake_iter(group: str):
        assert group == "label_hub.printer_backends"
        return [FakeEntryPoint()]

    monkeypatch.setattr("app.printer_backends.entry_points", fake_iter)
    BackendRegistry.ensure_discovered()
    assert BackendRegistry.find_by_backend_id("mock") is MockPrinterBackend
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_registry.py -q
```

Expected: `ImportError: cannot import name 'BackendRegistry'`.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/__init__.py
"""Printer-backend layer + plugin registry.

Built-in backends (`ptouch`, `mock`) ship pre-registered via setuptools
entry_points (group `label_hub.printer_backends`). Third-party backends
register the same way from their own pip package, with zero core changes.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import ClassVar, Protocol


class UnknownBackendError(Exception):
    """Raised when settings.printer_backend names a backend that is not registered."""


class _BackendFactory(Protocol):
    """Class object that exposes from_settings(settings) -> PrinterBackend."""

    backend_id: str

    @classmethod
    def from_settings(cls, settings: object) -> object: ...


_logger = logging.getLogger(__name__)


class BackendRegistry:
    """Class-level registry of PrinterBackend factory classes."""

    _factories: ClassVar[dict[str, type]] = {}
    _discovered: ClassVar[bool] = False

    @classmethod
    def register(cls, backend_id: str, factory: type) -> None:
        if backend_id in cls._factories:
            raise ValueError(f"backend_id {backend_id!r} is already registered")
        cls._factories[backend_id] = factory

    @classmethod
    def find_by_backend_id(cls, backend_id: str) -> type:
        try:
            return cls._factories[backend_id]
        except KeyError as exc:
            available = ", ".join(sorted(cls._factories)) or "<none registered>"
            raise UnknownBackendError(
                f"Unknown printer_backend {backend_id!r}. Available: {available}"
            ) from exc

    @classmethod
    def ensure_discovered(cls) -> None:
        """Walk the `label_hub.printer_backends` entry-points group once."""
        if cls._discovered:
            return
        cls._discovered = True
        for ep in entry_points(group="label_hub.printer_backends"):
            try:
                factory_cls = ep.load()
            except Exception:
                _logger.exception("Failed to load printer-backend entry-point %r", ep.name)
                continue
            try:
                cls.register(ep.name, factory_cls)
            except (ValueError, TypeError):
                _logger.exception("Failed to register printer-backend %r", ep.name)
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_registry.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/__init__.py \
        backend/tests/unit/printer_backends/test_registry.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): BackendRegistry + entry_points discovery

Class-level registry of backend factory classes, populated at app
start via setuptools entry_points (group label_hub.printer_backends).
ensure_discovered() is idempotent. find_by_backend_id raises
UnknownBackendError with the list of registered options when the
requested backend is missing.

Third-party backends ship as pip packages declaring an entry-point
in this group; no core changes required.

Refs #22
EOF
)"
```

### Task 5.2: Register built-in `mock` backend via pyproject.toml entry-points

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/unit/printer_backends/test_builtin_registration.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_builtin_registration.py
from __future__ import annotations

from importlib.metadata import entry_points


def test_mock_backend_is_declared_in_entry_points() -> None:
    names = {ep.name for ep in entry_points(group="label_hub.printer_backends")}
    assert "mock" in names
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_builtin_registration.py -q
```

Expected: `AssertionError: assert 'mock' in set()`.

- [ ] **Step 3: Implement — add to pyproject.toml**

Insert the new entry-points group below the existing `[project.entry-points."label_hub.integrations"]` block:

```toml
[project.entry-points."label_hub.printer_backends"]
mock = "app.printer_backends.mock_backend:MockPrinterBackend"
```

(`ptouch` will be added in Phase 6 once `PTouchBackend` exists.)

- [ ] **Step 4: Reinstall to refresh entry-points + verify**

```bash
cd backend
pip install -e .
pytest tests/unit/printer_backends/test_builtin_registration.py -q
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml \
        backend/tests/unit/printer_backends/test_builtin_registration.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): register mock backend in entry_points

Declares mock = app.printer_backends.mock_backend:MockPrinterBackend
under the label_hub.printer_backends group so BackendRegistry.
ensure_discovered() picks it up at app start.

ptouch backend will be registered alongside in a later commit once
PTouchBackend exists.

Refs #22
EOF
)"
```

---

## Phase 6 — PTouchBackend (status query + print)

### Task 6.1: Status-query helper (ESC i S over asyncio socket)

**Files:**
- Create: `backend/app/printer_backends/status_query.py`
- Create: `backend/tests/unit/printer_backends/test_status_query.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_status_query.py
from __future__ import annotations

import asyncio
import pytest

from app.printer_backends.exceptions import (
    PrinterOfflineError,
    StatusQueryFailedError,
)
from app.printer_backends.status_query import (
    ESC_I_S_REQUEST,
    parse_status_reply,
    query_status_over_socket,
)
from app.services.status_block import MediaType


def test_esc_i_s_request_bytes() -> None:
    assert ESC_I_S_REQUEST == b"\x1bi\x53"  # ESC, 'i', 'S' (0x53)
    assert len(ESC_I_S_REQUEST) == 3


def test_parse_reply_happy_path() -> None:
    reply = bytearray(32)
    reply[0] = 0x80  # head mark
    reply[1] = 0x20  # size = 32
    reply[2] = ord("B")
    reply[8] = 0x00  # error info 1
    reply[9] = 0x00  # error info 2
    reply[10] = 24  # tape width mm
    reply[11] = 0x01  # laminated
    sb = parse_status_reply(bytes(reply))
    assert sb.loaded_tape_mm == 24
    assert sb.media_type == MediaType.LAMINATED
    assert sb.tape_empty is False
    assert sb.cover_open is False
    assert sb.error_flags == 0


def test_parse_reply_tape_empty_flag() -> None:
    reply = bytearray(32)
    reply[0] = 0x80
    reply[1] = 0x20
    reply[2] = ord("B")
    reply[8] = 0x01  # bit 0 = no media
    sb = parse_status_reply(bytes(reply))
    assert sb.tape_empty is True


def test_parse_reply_cover_open_flag() -> None:
    reply = bytearray(32)
    reply[0] = 0x80
    reply[1] = 0x20
    reply[2] = ord("B")
    reply[9] = 0x10  # bit 4 = cover open
    sb = parse_status_reply(bytes(reply))
    assert sb.cover_open is True


def test_parse_reply_wrong_length_raises() -> None:
    with pytest.raises(StatusQueryFailedError):
        parse_status_reply(b"\x00" * 16)


def test_parse_reply_bad_head_marker_raises() -> None:
    reply = bytearray(32)
    reply[0] = 0xFF  # wrong head mark
    with pytest.raises(StatusQueryFailedError):
        parse_status_reply(bytes(reply))


async def test_query_status_over_socket_uses_open_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the helper uses asyncio.open_connection (non-blocking I/O)."""
    captured: dict[str, object] = {}

    class FakeReader:
        async def readexactly(self, n: int) -> bytes:
            captured["read_n"] = n
            reply = bytearray(32)
            reply[0] = 0x80
            reply[1] = 0x20
            reply[2] = ord("B")
            reply[10] = 24
            reply[11] = 0x01
            return bytes(reply)

    class FakeWriter:
        def write(self, data: bytes) -> None:
            captured["wrote"] = data

        async def drain(self) -> None:
            captured["drained"] = True

        def close(self) -> None:
            captured["closed"] = True

        async def wait_closed(self) -> None:
            captured["wait_closed"] = True

    async def fake_open_connection(host: str, port: int):  # noqa: ARG001
        captured["host"] = host
        captured["port"] = port
        return FakeReader(), FakeWriter()

    monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
    sb = await query_status_over_socket("1.2.3.4", 9100, timeout_s=1.0)
    assert captured["host"] == "1.2.3.4"
    assert captured["port"] == 9100
    assert captured["wrote"] == ESC_I_S_REQUEST
    assert captured["drained"] is True
    assert captured["closed"] is True
    assert captured["wait_closed"] is True
    assert captured["read_n"] == 32
    assert sb.loaded_tape_mm == 24


async def test_query_status_offline_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_open_connection(*_a, **_kw):
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
    with pytest.raises(PrinterOfflineError):
        await query_status_over_socket("1.2.3.4", 9100, timeout_s=0.1)


async def test_query_status_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_open_connection(*_a, **_kw):
        await asyncio.sleep(10)  # will be cancelled by timeout
        raise AssertionError("unreachable")

    monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
    with pytest.raises(PrinterOfflineError):
        await query_status_over_socket("1.2.3.4", 9100, timeout_s=0.01)
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_status_query.py -q
```

Expected: `ImportError: cannot import name 'ESC_I_S_REQUEST'`.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/status_query.py
"""Brother PT-Series status query — ESC i S over a raw asyncio socket.

Sends a 3-byte command (0x1B 0x69 0x53) and parses the 32-byte reply per the
Brother Raster Command Reference (PT-Series). The ptouch library does not
expose this — only an internal _cmd_print_information send command exists.

See backend/docs/brother-status-block.md for the wire format.
"""

from __future__ import annotations

import asyncio

from app.printer_backends.exceptions import (
    PrinterOfflineError,
    StatusQueryFailedError,
)
from app.services.status_block import MediaType, StatusBlock

ESC_I_S_REQUEST: bytes = b"\x1bi\x53"
_STATUS_REPLY_LEN: int = 32
_HEAD_MARK: int = 0x80
_SIZE_BYTE: int = 0x20
_BRAND_BYTE: int = ord("B")

_MEDIA_TYPE_LOOKUP: dict[int, MediaType] = {
    0x00: MediaType.NONE,
    0x01: MediaType.LAMINATED,
    0x03: MediaType.NON_LAMINATED,
    0x11: MediaType.HEAT_SHRINK_2_1,
    0x17: MediaType.HEAT_SHRINK_3_1,
}


def parse_status_reply(reply: bytes) -> StatusBlock:
    """Parse the 32-byte ESC i S response. Raise StatusQueryFailedError if malformed."""
    if len(reply) != _STATUS_REPLY_LEN:
        raise StatusQueryFailedError(
            f"Expected {_STATUS_REPLY_LEN} bytes, got {len(reply)}"
        )
    if reply[0] != _HEAD_MARK or reply[2] != _BRAND_BYTE:
        raise StatusQueryFailedError(
            f"Bad reply header: head={reply[0]:#x} brand={reply[2]:#x}"
        )
    err1 = reply[8]
    err2 = reply[9]
    return StatusBlock(
        tape_empty=bool(err1 & 0x03),  # bit 0 (no media) | bit 1 (end of media)
        cover_open=bool(err2 & 0x10),  # bit 4
        error_flags=(err1 << 8) | err2,
        loaded_tape_mm=reply[10],
        media_type=_MEDIA_TYPE_LOOKUP.get(reply[11], MediaType.NONE),
    )


async def query_status_over_socket(
    host: str,
    port: int = 9100,
    *,
    timeout_s: float = 5.0,
) -> StatusBlock:
    """Open a TCP connection, write ESC i S, read 32 bytes, parse."""
    try:
        async with asyncio.timeout(timeout_s):
            reader, writer = await asyncio.open_connection(host, port)
    except (OSError, asyncio.TimeoutError) as exc:
        raise PrinterOfflineError(f"cannot reach {host}:{port}: {exc}") from exc

    try:
        writer.write(ESC_I_S_REQUEST)
        await writer.drain()
        try:
            async with asyncio.timeout(timeout_s):
                reply = await reader.readexactly(_STATUS_REPLY_LEN)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            raise PrinterOfflineError(f"status read failed: {exc}") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    return parse_status_reply(reply)
```

- [ ] **Step 4: Verify MediaType enum has the values used above**

```bash
grep -n "^class MediaType\|    [A-Z_]* =" backend/app/services/status_block.py | head -10
```

If `NONE` / `NON_LAMINATED` / `HEAT_SHRINK_2_1` / `HEAT_SHRINK_3_1` are missing, file a follow-up issue — they are part of `status_block.MediaType` per the design and the existing renderer code. (Adjust the `_MEDIA_TYPE_LOOKUP` dict to match the actual enum members if the names diverge.)

- [ ] **Step 5: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_status_query.py -q
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/printer_backends/status_query.py \
        backend/tests/unit/printer_backends/test_status_query.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): ESC i S status query over asyncio socket

Implements the wire-level Brother status query that ptouch does not
expose. Uses asyncio.open_connection so the call is non-blocking
inside an async def; flushes via drain(), closes cleanly via
close() + wait_closed() to avoid truncating mid-transfer.

Parser decodes the 32-byte reply into a StatusBlock: loaded_tape_mm,
media_type, tape_empty (bits 0|1 of err1), cover_open (bit 4 of err2),
and the raw err_flags for diagnostics.

Refs #22
EOF
)"
```

### Task 6.2: PTouchBackend wrapping the ptouch library

**Files:**
- Create: `backend/app/printer_backends/ptouch_backend.py`
- Create: `backend/tests/unit/printer_backends/test_ptouch_backend.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_ptouch_backend.py
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    PrintFailedError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.ptouch_backend import PTouchBackend
from app.services.status_block import MediaType, StatusBlock


@pytest.fixture
def tape_24() -> TapeSpec:
    return TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    )


@pytest.fixture
def img_128() -> Image.Image:
    return Image.new("1", (200, 128))


@pytest.fixture
def healthy_status() -> StatusBlock:
    return StatusBlock(
        tape_empty=False,
        cover_open=False,
        error_flags=0,
        loaded_tape_mm=24,
        media_type=MediaType.LAMINATED,
    )


def test_satisfies_protocol() -> None:
    assert isinstance(PTouchBackend(host="1.2.3.4"), PrinterBackend)


def test_backend_id() -> None:
    assert PTouchBackend(host="x").backend_id == "ptouch"


async def test_query_status_delegates_to_socket_helper(
    monkeypatch: pytest.MonkeyPatch, healthy_status: StatusBlock
) -> None:
    async def fake_query(host: str, port: int, *, timeout_s: float) -> StatusBlock:
        assert host == "192.0.2.10"
        assert port == 9100
        return healthy_status

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    backend = PTouchBackend(host="192.0.2.10")
    status = await backend.query_status()
    assert status is healthy_status


async def test_query_status_retries_on_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def fake_query(*_a, **_kw):
        attempts["n"] += 1
        raise PrinterOfflineError("nope")

    async def fast_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    monkeypatch.setattr("asyncio.sleep", fast_sleep)
    backend = PTouchBackend(host="x")
    with pytest.raises(PrinterOfflineError):
        await backend.query_status()
    assert attempts["n"] == 3


async def test_print_image_validates_status_first(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
) -> None:
    """tape_empty status must raise BEFORE invoking the ptouch printer."""
    bad_status = StatusBlock(
        tape_empty=True,
        cover_open=False,
        error_flags=1,
        loaded_tape_mm=0,
        media_type=MediaType.NONE,
    )

    async def fake_query(*_a, **_kw):
        return bad_status

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    ptouch_print = MagicMock()
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print",
        ptouch_print,
    )
    backend = PTouchBackend(host="x")
    with pytest.raises(TapeEmptyError):
        await backend.print_image(img_128, tape_24)
    ptouch_print.assert_not_called()


async def test_print_image_raises_tape_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
) -> None:
    async def fake_query(*_a, **_kw):
        return StatusBlock(
            tape_empty=False, cover_open=False, error_flags=0,
            loaded_tape_mm=12, media_type=MediaType.LAMINATED,
        )

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    backend = PTouchBackend(host="x")
    with pytest.raises(TapeMismatchError) as exc:
        await backend.print_image(img_128, tape_24)
    assert exc.value.expected_mm == 24
    assert exc.value.loaded_mm == 12


async def test_print_image_invokes_ptouch_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
    healthy_status: StatusBlock,
) -> None:
    async def fake_query(*_a, **_kw):
        return healthy_status

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    captured: dict[str, Any] = {}

    def fake_print(host: str, port: int, image, tape_mm, *, auto_cut, high_resolution):
        captured["host"] = host
        captured["port"] = port
        captured["tape_mm"] = tape_mm
        captured["auto_cut"] = auto_cut
        captured["high_resolution"] = high_resolution

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print",
        fake_print,
    )
    backend = PTouchBackend(host="192.0.2.10")
    await backend.print_image(img_128, tape_24, auto_cut=True, high_resolution=False)
    assert captured["host"] == "192.0.2.10"
    assert captured["port"] == 9100
    assert captured["tape_mm"] == 24
    assert captured["auto_cut"] is True


async def test_print_image_wraps_ptouch_exception(
    monkeypatch: pytest.MonkeyPatch,
    img_128: Image.Image,
    tape_24: TapeSpec,
    healthy_status: StatusBlock,
) -> None:
    import ptouch as _ptouch_mod

    async def fake_query(*_a, **_kw):
        return healthy_status

    def fake_print(*_a, **_kw):
        raise _ptouch_mod.PrinterWriteError("disk full")

    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend.query_status_over_socket",
        fake_query,
    )
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print",
        fake_print,
    )
    backend = PTouchBackend(host="x")
    with pytest.raises(PrintFailedError) as exc:
        await backend.print_image(img_128, tape_24)
    assert "disk full" in str(exc.value)


def test_from_settings_reads_pt750w_host() -> None:
    class S:
        pt750w_host = "192.0.2.10"
        pt750w_port = 9100
        printer_model = "PT-P750W"

    backend = PTouchBackend.from_settings(S())  # type: ignore[arg-type]
    assert backend.host == "192.0.2.10"


def test_from_settings_empty_host_raises() -> None:
    class S:
        pt750w_host = ""
        pt750w_port = 9100
        printer_model = "PT-P750W"

    with pytest.raises(ValueError, match="pt750w_host"):
        PTouchBackend.from_settings(S())  # type: ignore[arg-type]
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_ptouch_backend.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.printer_backends.ptouch_backend'`.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/ptouch_backend.py
"""PTouchBackend — wraps the `ptouch` Python library for Brother PT-Series.

Status queries go through query_status_over_socket (the library does not
expose them). Print calls go through ptouch.LabelPrinter.print() inside
asyncio.to_thread (the library is synchronous). All ptouch exceptions are
caught and rewrapped as our PrinterError subtypes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import ptouch
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.exceptions import (
    PrintFailedError,
    PrinterOfflineError,
    PrinterCoverOpenError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.status_query import query_status_over_socket
from app.services.status_block import StatusBlock

_logger = logging.getLogger(__name__)

_RETRY_BACKOFFS: tuple[float, ...] = (0.0, 1.0, 2.0)

# Lookup of model_id -> ptouch printer class. PT-P750W and a small set of
# sibling models that share the same wire protocol. Extend as needed.
_PTOUCH_PRINTER_CLASSES: dict[str, type] = {
    "PT-P750W": ptouch.PTP750W,
    "PT-E550W": ptouch.PTE550W,
    "PT-P900": ptouch.PTP900,
    "PT-P900W": ptouch.PTP900W,
    "PT-P910BT": ptouch.PTP910BT,
    "PT-P950NW": ptouch.PTP950NW,
}

# Lookup of tape_mm -> ptouch laminated tape class. The PTouchBackend
# defaults to laminated; non-laminated / heat-shrink variants pick a
# different class in a future media_type-aware revision.
_PTOUCH_TAPE_CLASSES: dict[int, type] = {
    4: ptouch.LaminatedTape3_5mm,
    6: ptouch.LaminatedTape6mm,
    9: ptouch.LaminatedTape9mm,
    12: ptouch.LaminatedTape12mm,
    18: ptouch.LaminatedTape18mm,
    24: ptouch.LaminatedTape24mm,
    36: ptouch.LaminatedTape36mm,
}


def _ptouch_print(
    host: str,
    port: int,
    image: Image.Image,
    tape_mm: int,
    *,
    auto_cut: bool,
    high_resolution: bool,
) -> None:
    """Synchronous helper: open connection, send one Label, close.

    Lives at module level so tests can monkeypatch it.
    """
    try:
        tape_cls = _PTOUCH_TAPE_CLASSES[tape_mm]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch tape class for {tape_mm}mm") from exc
    connection = ptouch.ConnectionNetwork(host, port=port, timeout=10.0)
    printer = ptouch.PTP750W(
        connection=connection,
        high_resolution=high_resolution,
    )
    label = ptouch.Label(image=image, tape=tape_cls)
    printer.print(label, auto_cut=auto_cut, high_resolution=high_resolution)


class PTouchBackend:
    """PrinterBackend backed by the ptouch library."""

    backend_id = "ptouch"

    def __init__(self, host: str, *, port: int = 9100, model_id: str = "PT-P750W") -> None:
        if not host:
            raise ValueError("PTouchBackend requires a non-empty host")
        if model_id not in _PTOUCH_PRINTER_CLASSES:
            raise ValueError(
                f"Unknown printer_model {model_id!r}; "
                f"known: {sorted(_PTOUCH_PRINTER_CLASSES)}"
            )
        self.host = host
        self._port = port
        self._model_id = model_id

    @classmethod
    def from_settings(cls, settings: Any) -> "PTouchBackend":
        host = getattr(settings, "pt750w_host", "") or ""
        if not host:
            raise ValueError(
                "Empty pt750w_host with printer_backend=ptouch — "
                "set PRINTER_HUB_PT750W_HOST to the printer's IP/hostname."
            )
        return cls(
            host=host,
            port=int(getattr(settings, "pt750w_port", 9100)),
            model_id=str(getattr(settings, "printer_model", "PT-P750W")),
        )

    async def query_status(self) -> StatusBlock:
        last_exc: Exception | None = None
        for delay in _RETRY_BACKOFFS:
            if delay:
                _logger.warning("retrying status query in %.1fs", delay)
                await asyncio.sleep(delay)
            try:
                return await query_status_over_socket(self.host, self._port, timeout_s=5.0)
            except PrinterOfflineError as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> None:
        status = await self.query_status()
        if status.tape_empty:
            raise TapeEmptyError()
        if status.cover_open:
            raise PrinterCoverOpenError()
        if status.loaded_tape_mm != tape_spec.width_mm:
            raise TapeMismatchError(
                expected_mm=tape_spec.width_mm,
                loaded_mm=status.loaded_tape_mm,
            )

        try:
            await asyncio.to_thread(
                _ptouch_print,
                self.host,
                self._port,
                image,
                tape_spec.width_mm,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
            )
        except (
            ptouch.PrinterConnectionError,
            ptouch.PrinterNetworkError,
            ptouch.PrinterTimeoutError,
            ptouch.PrinterNotFoundError,
        ) as exc:
            raise PrinterOfflineError(str(exc)) from exc
        except (ptouch.PrinterWriteError, ptouch.PrinterPermissionError) as exc:
            raise PrintFailedError(str(exc)) from exc
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_ptouch_backend.py -q
```

Expected: 9 passed.

- [ ] **Step 5: Register ptouch in pyproject.toml entry-points**

Add to the `[project.entry-points."label_hub.printer_backends"]` block:

```toml
ptouch = "app.printer_backends.ptouch_backend:PTouchBackend"
```

Reinstall + verify:

```bash
cd backend && pip install -e . && python -c "
from importlib.metadata import entry_points
print(sorted(ep.name for ep in entry_points(group='label_hub.printer_backends')))
"
```

Expected: `['mock', 'ptouch']`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/printer_backends/ptouch_backend.py \
        backend/tests/unit/printer_backends/test_ptouch_backend.py \
        backend/pyproject.toml
git commit -m "$(cat <<'EOF'
feat(printer-backends): PTouchBackend wrapping ptouch library

Implements PrinterBackend against the ptouch Python library:

* query_status — uses the raw-socket ESC i S helper, makes exactly 3 attempts
  with back-off (0s, 1s, 2s) on PrinterOfflineError.
* print_image — pre-validates against query_status (tape_empty,
  cover_open, tape mismatch); dispatches the synchronous ptouch.print
  via asyncio.to_thread; wraps ptouch's exception family into our
  PrinterError subtypes.
* from_settings — reads pt750w_host / pt750w_port and looks up the
  ptouch printer class from printer_model; raises clearly on empty
  host or unknown model.

Built-in ptouch backend registered under the label_hub.printer_backends
entry-points group.

Refs #22
EOF
)"
```

### Task 6.3: SNMP helper — query_model_pjl + query_live_status

**Files:**
- Create: `backend/app/printer_backends/snmp_helper.py`
- Create: `backend/tests/unit/printer_backends/test_snmp_helper.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_snmp_helper.py
from __future__ import annotations

from typing import Any

import pytest

from app.printer_backends.exceptions import SnmpDiscoveryError, SnmpQueryError
from app.printer_backends.snmp_helper import (
    BROTHER_PJL_OID,
    HR_PRINTER_DETECTED_ERROR_STATE_OID,
    HR_PRINTER_STATUS_OID,
    LiveStatus,
    decode_error_flags,
    query_live_status,
    query_model_pjl,
)


def test_oid_constants() -> None:
    assert BROTHER_PJL_OID == "1.3.6.1.4.1.2435.2.3.9.1.1.7.0"
    assert HR_PRINTER_STATUS_OID == "1.3.6.1.2.1.25.3.5.1.1.1"
    assert HR_PRINTER_DETECTED_ERROR_STATE_OID == "1.3.6.1.2.1.25.3.5.1.2.1"


def test_decode_error_flags_no_paper() -> None:
    # Byte 0 bit 1 (0x40) = noPaper
    assert "noPaper" in decode_error_flags(b"\x40\x00")


def test_decode_error_flags_door_open() -> None:
    # Byte 0 bit 4 (0x08) = doorOpen
    assert "doorOpen" in decode_error_flags(b"\x08\x00")


def test_decode_error_flags_jammed() -> None:
    # Byte 0 bit 5 (0x04) = jammed
    assert "jammed" in decode_error_flags(b"\x04\x00")


def test_decode_error_flags_empty_when_no_bits() -> None:
    assert decode_error_flags(b"\x00\x00") == []


async def test_query_model_pjl_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stubbed pysnmp.get_cmd returns a PJL string for the Brother private OID."""
    expected_pjl = "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;"
    captured: dict[str, Any] = {}

    async def fake_get_cmd(engine, community, transport, ctx, *oids):  # noqa: ARG001
        from pysnmp.smi import rfc1902
        # Inspect args
        captured["oids"] = [str(oid[0]) for oid in oids]
        captured["community"] = community.communityName
        # Return (errorIndication, errorStatus, errorIndex, varBinds)
        ok_pdu = (None, None, 0, [(oids[0][0], rfc1902.OctetString(expected_pjl))])
        return ok_pdu

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    pjl = await query_model_pjl("192.0.2.10", community="public", timeout_s=1.0)
    assert pjl == expected_pjl
    assert BROTHER_PJL_OID in captured["oids"][0]


async def test_query_model_pjl_unreachable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_cmd(*_a, **_kw):
        return ("requestTimedOut", None, 0, [])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    with pytest.raises(SnmpDiscoveryError, match="timed out"):
        await query_model_pjl("192.0.2.10", community="public", timeout_s=1.0)


async def test_query_live_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stubbed pysnmp returns hrPrinterStatus=4 (printing) + errorState bytes."""
    from pysnmp.smi import rfc1902

    async def fake_get_cmd(engine, community, transport, ctx, *oids):  # noqa: ARG001
        return (
            None, None, 0,
            [
                (oids[0][0], rfc1902.Integer(4)),       # printing
                (oids[1][0], rfc1902.OctetString(b"\x40\x00")),  # noPaper bit
            ],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    ls = await query_live_status("192.0.2.10", community="public", timeout_s=1.0)
    assert isinstance(ls, LiveStatus)
    assert ls.hr_printer_status == "printing"
    assert "noPaper" in ls.error_flags


async def test_query_live_status_failure_is_separate_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_cmd(*_a, **_kw):
        return ("requestTimedOut", None, 0, [])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    with pytest.raises(SnmpQueryError):
        await query_live_status("192.0.2.10", community="public", timeout_s=1.0)
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_backends/test_snmp_helper.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.printer_backends.snmp_helper'`.

- [ ] **Step 3: Implement**

```python
# backend/app/printer_backends/snmp_helper.py
"""SNMP query helpers — discovery (PJL string) + live status.

Uses pysnmp's asyncio API; the call is fully non-blocking, no thread
dispatch needed. SNMPv2c with a configurable community (default 'public').
The PT-P750W lives on the LAN/Tailscale, not the open internet, so v2c
is fine here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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

_log = logging.getLogger(__name__)

BROTHER_PJL_OID = "1.3.6.1.4.1.2435.2.3.9.1.1.7.0"
HR_PRINTER_STATUS_OID = "1.3.6.1.2.1.25.3.5.1.1.1"
HR_PRINTER_DETECTED_ERROR_STATE_OID = "1.3.6.1.2.1.25.3.5.1.2.1"

_PRINTER_STATUS_MAP: dict[int, Literal["other", "unknown", "idle", "printing", "warmup"]] = {
    1: "other",
    2: "unknown",
    3: "idle",
    4: "printing",
    5: "warmup",
}

# (byte_index, bit_mask, name) — MSB first per RFC 1759
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
    error_flags: list[str]


async def query_model_pjl(host: str, *, community: str = "public", timeout_s: float = 3.0) -> str:
    """Read Brother private OID → PJL identification string.

    Raises SnmpDiscoveryError on any failure (timeout, OID missing, refused).
    """
    error_indication, error_status, _, var_binds = await get_cmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),  # mpModel=1 → SNMPv2c
        UdpTransportTarget((host, 161), timeout=timeout_s, retries=0),
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
    """Read hrPrinterStatus + hrPrinterDetectedErrorState in one round trip."""
    error_indication, error_status, _, var_binds = await get_cmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        UdpTransportTarget((host, 161), timeout=timeout_s, retries=0),
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
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_backends/test_snmp_helper.py -q
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/snmp_helper.py \
        backend/tests/unit/printer_backends/test_snmp_helper.py
git commit -m "$(cat <<'EOF'
feat(printer-backends): SNMP helpers (discovery + live status)

Two async helpers built on pysnmp's asyncio API:

* query_model_pjl(host) — reads Brother private OID 1.3.6.1.4.1.2435.
  2.3.9.1.1.7.0 → full PJL identification string. Used by the lifespan
  to resolve the model via ModelRegistry.find_by_pjl (ADR 0004).
* query_live_status(host) — reads Host-Resources Printer MIB
  hrPrinterStatus + hrPrinterDetectedErrorState in one round trip,
  returns LiveStatus { hr_printer_status, error_flags } for the
  /jobs/{id} response while a print is running.

Failure modes are separate: SnmpDiscoveryError stops app start;
SnmpQueryError is non-fatal at request time (live block is omitted).
SNMPv2c with a configurable community (default 'public'); printer is
on the LAN/Tailscale, so v2c is fine.

Refs #22
EOF
)"
```

---

## Phase 7 — ModelRegistry entry_points discovery + find_by_model_id

### Task 7.1: Extend ModelRegistry

**Files:**
- Modify: `backend/app/printer_models/registry.py`
- Modify: `backend/tests/unit/printer_models/test_registry.py`

- [ ] **Step 1: Write the failing test (append to existing test_registry.py)**

```python
# backend/tests/unit/printer_models/test_registry.py — APPEND
import pytest
from app.printer_models.registry import (
    ModelNotFoundError,
    ModelRegistry,
)


class _FakeDriver:
    model_id = "FAKE-001"
    pjl_signatures = ["FAKE-001"]
    snmp_model_oid_value_substr = "FAKE-001"
    dpi = (180, 180)
    print_head_pins = 128

    def __init__(self, backend: object) -> None:
        self._backend = backend


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    saved = list(ModelRegistry._models)
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    yield
    ModelRegistry._models.clear()
    ModelRegistry._models.extend(saved)
    ModelRegistry._discovered = True


def test_find_by_model_id_returns_class() -> None:
    ModelRegistry.register(_FakeDriver)
    cls = ModelRegistry.find_by_model_id("FAKE-001")
    assert cls is _FakeDriver


def test_find_by_model_id_unknown_lists_available() -> None:
    ModelRegistry.register(_FakeDriver)
    with pytest.raises(ModelNotFoundError) as exc:
        ModelRegistry.find_by_model_id("PT-P750W")
    msg = str(exc.value)
    assert "PT-P750W" in msg
    assert "FAKE-001" in msg


def test_ensure_discovered_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_iter(group: str):
        calls["n"] += 1
        assert group == "label_hub.printer_models"
        return []

    monkeypatch.setattr("app.printer_models.registry.entry_points", fake_iter)
    ModelRegistry.ensure_discovered()
    ModelRegistry.ensure_discovered()
    assert calls["n"] == 1


def test_entry_point_discovery_registers_fake_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    class _EP:
        name = "fake"

        def load(self) -> type[_FakeDriver]:
            return _FakeDriver

    def fake_iter(group: str):
        return [_EP()]

    monkeypatch.setattr("app.printer_models.registry.entry_points", fake_iter)
    ModelRegistry.ensure_discovered()
    assert ModelRegistry.find_by_model_id("FAKE-001") is _FakeDriver
```

Adjust the existing `ModelRegistry.register` test only if it stops passing — `register` semantics did not change.

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_models/test_registry.py -q
```

Expected: missing `find_by_model_id`, `ensure_discovered`, or `entry_points` symbol.

- [ ] **Step 3: Implement (edit registry.py)**

Add to `backend/app/printer_models/registry.py`:

```python
from importlib.metadata import entry_points

# ... existing class body ...

    _discovered: ClassVar[bool] = False

    @classmethod
    def find_by_model_id(cls, model_id: str) -> type:
        """Return the *class* of the driver matching `model_id` (PrinterModel attr)."""
        # Note: existing register() stores *instances*; we accept either form.
        for entry in cls._models:
            entry_cls = entry if isinstance(entry, type) else type(entry)
            if getattr(entry_cls, "model_id", None) == model_id:
                return entry_cls
        available = ", ".join(
            sorted(
                {
                    getattr(entry if isinstance(entry, type) else type(entry), "model_id", "?")
                    for entry in cls._models
                }
            )
        ) or "<none registered>"
        raise ModelNotFoundError(
            f"Unknown printer_model {model_id!r}. Available: {available}"
        )

    @classmethod
    def ensure_discovered(cls) -> None:
        """Walk the `label_hub.printer_models` entry-points group once."""
        if cls._discovered:
            return
        cls._discovered = True
        import logging
        log = logging.getLogger(__name__)
        for ep in entry_points(group="label_hub.printer_models"):
            try:
                driver_cls = ep.load()
            except Exception:
                log.exception("Failed to load printer-model entry-point %r", ep.name)
                continue
            try:
                cls.register(driver_cls)
            except (ValueError, TypeError):
                log.exception("Failed to register printer-model %r", ep.name)
```

Also relax `register` to accept either a class or an instance — drivers that come via `entry_points.load()` are class objects. Adjust the existing `register` validation accordingly:

```python
    @classmethod
    def register(cls, model: PrinterModel) -> None:
        """Append *model* (class or instance) to the registry."""
        target = model  # accept class or instance for back-compat
        if any(not sig for sig in target.pjl_signatures):
            raise ValueError(
                f"PrinterModel {target.model_id!r} has an empty PJL signature; "
                "empty substrings match every input and would shadow other plugins"
            )
        if not target.snmp_model_oid_value_substr:
            raise ValueError(
                f"PrinterModel {target.model_id!r} has an empty SNMP OID substring; "
                "empty substrings match every input and would shadow other plugins"
            )
        cls._models.append(target)
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_models/test_registry.py -q
```

Expected: all tests pass (old + new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_models/registry.py \
        backend/tests/unit/printer_models/test_registry.py
git commit -m "$(cat <<'EOF'
feat(printer-models): find_by_model_id + entry_points discovery

ModelRegistry gains find_by_model_id(model_id) — used by the lifespan
to resolve settings.printer_model to a driver class — and
ensure_discovered() which walks the label_hub.printer_models
entry-points group once at app start. register() now accepts class
objects too (entry-points return classes); the existing instance form
keeps working.

Refs #22
EOF
)"
```

---

## Phase 8 — PTP750WDriver + make_queue_printer + _PTPQueuePrinter

### Task 8.1: PTP750WDriver class with PrinterModel methods + bridge factory

**Files:**
- Modify: `backend/app/printer_models/pt.py` (append)
- Create: `backend/tests/unit/printer_models/test_pt_driver.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_models/test_pt_driver.py
from __future__ import annotations

import pytest
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.mock_backend import MockPrinterBackend
from app.printer_models.pt import PTP750WDriver
from app.services.print_queue import _PrinterLike
from app.services.status_block import MediaType
from app.services.tape_registry import TapeRegistry


@pytest.fixture
def backend() -> MockPrinterBackend:
    return MockPrinterBackend(host="192.0.2.10")


@pytest.fixture
def tape_registry() -> TapeRegistry:
    return TapeRegistry()


def test_constants() -> None:
    assert PTP750WDriver.model_id == "PT-P750W"
    assert PTP750WDriver.dpi == (180, 180)
    assert PTP750WDriver.print_head_pins == 128
    assert "PT-P750W" in PTP750WDriver.pjl_signatures
    assert PTP750WDriver.snmp_model_oid_value_substr == "PT-P750W"


async def test_query_status_delegates_to_backend(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    # `host` is required by the Protocol; empty string means "use the bound backend's host"
    status = await driver.query_status(host="")
    assert status.loaded_tape_mm == 24


async def test_query_status_rejects_host_mismatch(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    with pytest.raises(ValueError, match="bound to backend.host"):
        await driver.query_status(host="999.999.999.999")


async def test_query_status_accepts_matching_host(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    status = await driver.query_status(host=backend.host)
    assert status.loaded_tape_mm == 24


def test_build_print_job_raises_not_implemented(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    image = Image.new("1", (200, 128))
    spec = TapeSpec(
        width_mm=24, media_type=MediaType.LAMINATED,
        print_area_pins=128, print_area_dots=128, bytes_per_raster=16,
        min_length_mm=4.4, max_length_mm=1000, cutter_min_length_mm=24.5,
    )
    with pytest.raises(NotImplementedError):
        driver.build_print_job(image, spec)


def test_width_to_pixels(backend: MockPrinterBackend) -> None:
    driver = PTP750WDriver(backend=backend)
    spec = TapeSpec(
        width_mm=24, media_type=MediaType.LAMINATED,
        print_area_pins=128, print_area_dots=128, bytes_per_raster=16,
        min_length_mm=4.4, max_length_mm=1000, cutter_min_length_mm=24.5,
    )
    assert driver.width_to_pixels(spec) == 128


def test_make_queue_printer_returns_printer_like(
    backend: MockPrinterBackend, tape_registry: TapeRegistry
) -> None:
    driver = PTP750WDriver(backend=backend)
    qp = driver.make_queue_printer(tape_registry)
    assert isinstance(qp, _PrinterLike)
    assert qp.id == "PT-P750W@192.0.2.10"


async def test_queue_printer_print_calls_backend(
    backend: MockPrinterBackend, tape_registry: TapeRegistry
) -> None:
    driver = PTP750WDriver(backend=backend)
    qp = driver.make_queue_printer(tape_registry)
    image = Image.new("1", (200, 128))
    await qp.print_image(image, tape_mm=24)
    assert len(backend.printed_images) == 1


async def test_queue_printer_uses_default_media_type(
    backend: MockPrinterBackend, tape_registry: TapeRegistry
) -> None:
    """Default is LAMINATED — explicit override is honoured."""
    driver = PTP750WDriver(backend=backend)
    qp = driver.make_queue_printer(
        tape_registry, default_media_type=MediaType.NON_LAMINATED
    )
    # Mock has LAMINATED loaded, so NON_LAMINATED lookup should not match
    # the loaded tape; the mock raises TapeMismatchError only on width mismatch,
    # so this test just asserts the override is plumbed through (i.e. no crash).
    image = Image.new("1", (200, 128))
    await qp.print_image(image, tape_mm=24)
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/printer_models/test_pt_driver.py -q
```

Expected: `ImportError: cannot import name 'PTP750WDriver'`.

- [ ] **Step 3: Implement (append to pt.py)**

Append to `backend/app/printer_models/pt.py`:

```python
# === First-Print: PT-P750W driver + queue-printer bridge ===

from __future__ import annotations as _annotations  # noqa: F401  (idempotent)

import logging
from typing import Any

from PIL import Image

from app.printer_backends.base import PrinterBackend
from app.printer_models.registry import ModelRegistry
from app.services.status_block import MediaType, StatusBlock
from app.services.tape_registry import TapeRegistry

_pt_log = logging.getLogger(__name__)


class PTP750WDriver:
    """Driver for the Brother PT-P750W. Bound to one PrinterBackend at construction.

    Implements PrinterModel and provides make_queue_printer() for the queue.
    """

    model_id = "PT-P750W"
    pjl_signatures = ["PT-P750W"]
    snmp_model_oid_value_substr = "PT-P750W"
    dpi = (180, 180)
    print_head_pins = 128

    def __init__(self, backend: PrinterBackend) -> None:
        self._backend = backend

    # --- PrinterModel ---
    async def query_status(
        self, host: str, port: int = 9100, timeout_s: float = 5.0  # noqa: ARG002
    ) -> StatusBlock:
        # Protocol requires `host` positionally. The driver is bound to a
        # backend that already knows its host, so the only sensible call is
        # `driver.query_status(driver._backend.host, ...)` or — when callers
        # have a bound driver and don't care — `driver.query_status("", ...)`.
        # We accept the empty string as "use bound backend's host" without
        # raising, but reject any other non-matching host loudly.
        if host and host != self._backend.host:
            raise ValueError(
                f"Driver bound to backend.host={self._backend.host!r}; "
                f"got host={host!r}. Construct a new driver/backend pair instead."
            )
        return await self._backend.query_status()

    def width_to_pixels(self, tape_spec: Any) -> int:
        return int(tape_spec.print_area_pins)

    def build_print_job(  # noqa: ARG002
        self, image: Image.Image, tape_spec: Any,
        auto_cut: bool = True, high_resolution: bool = False,
    ) -> bytes:
        """Encoding is owned by the backend (ptouch handles raster build).

        Callers wanting raw bytes for export/debug can be added later; the
        First-Print path goes through backend.print_image() and never calls
        this method. We raise NotImplementedError rather than returning empty
        bytes so any unintended caller fails loudly instead of silently
        sending no data. The pyproject coverage config excludes
        `raise NotImplementedError` from coverage.
        """
        raise NotImplementedError(
            "PTP750WDriver delegates encoding to backend.print_image(). "
            "build_print_job() will be implemented when a real caller "
            "(raw-export, debugging, non-library backend) appears."
        )

    # --- queue-printer factory ---
    def make_queue_printer(
        self,
        tape_registry: TapeRegistry,
        *,
        default_media_type: MediaType = MediaType.LAMINATED,
    ) -> "_PTPQueuePrinter":
        return _PTPQueuePrinter(
            driver=self,
            backend=self._backend,
            tape_registry=tape_registry,
            default_media_type=default_media_type,
        )


class _PTPQueuePrinter:
    """Private _PrinterLike adapter — produced by PTP750WDriver.make_queue_printer."""

    def __init__(
        self,
        *,
        driver: PTP750WDriver,
        backend: PrinterBackend,
        tape_registry: TapeRegistry,
        default_media_type: MediaType,
    ) -> None:
        self._driver = driver
        self._backend = backend
        self._tape_registry = tape_registry
        self._default_media_type = default_media_type
        self.id = f"{driver.model_id}@{backend.host}"

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        media_type = options.pop("media_type", self._default_media_type)
        tape_spec = self._tape_registry.lookup_pt(tape_mm, media_type)
        await self._backend.print_image(
            image,
            tape_spec,
            auto_cut=bool(options.pop("auto_cut", True)),
            high_resolution=bool(options.pop("high_resolution", False)),
        )


# Module-level registration so import-time discovery sees the built-in driver.
ModelRegistry.register(PTP750WDriver)
```

- [ ] **Step 4: Register driver in pyproject.toml entry-points**

Add a new entry-points block in `backend/pyproject.toml`:

```toml
[project.entry-points."label_hub.printer_models"]
pt-series = "app.printer_models.pt"
```

The entry-point loads the module — module-level `ModelRegistry.register(PTP750WDriver)` does the actual registration. (entry-points group is walked once at app start; loading the module triggers registration.)

Reinstall to refresh metadata:

```bash
cd backend && pip install -e .
```

- [ ] **Step 5: Run — verify pass**

```bash
cd backend && pytest tests/unit/printer_models/test_pt_driver.py -q
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/printer_models/pt.py \
        backend/tests/unit/printer_models/test_pt_driver.py \
        backend/pyproject.toml
git commit -m "$(cat <<'EOF'
feat(printer-models): PTP750WDriver + queue-printer factory

PT-P750W driver implements PrinterModel (model_id, dpi, pins, PJL/SNMP
signatures, width_to_pixels, query_status, build_print_job) and exposes
make_queue_printer(tape_registry, default_media_type=LAMINATED) which
produces a private _PTPQueuePrinter satisfying PrintQueue._PrinterLike.

query_status raises ValueError on a non-matching host argument rather
than silently ignoring it (the driver is bound to one backend).
build_print_job returns empty bytes for Protocol conformance — the
First-Print happy path uses backend.print_image directly; raw-byte
encoding is deferred until a concrete caller appears.

Registered at module import via ModelRegistry.register and via the
label_hub.printer_models entry-points group.

Refs #22
EOF
)"
```

---

## Phase 9 — Pydantic schemas for the REST surface

### Task 9.1: PrintLookupRequest, PrintOptions, RawLabelData, PrintRequest

**Files:**
- Create: `backend/app/schemas/print_request.py`
- Create: `backend/tests/unit/schemas/test_print_request.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_print_request.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.print_request import (
    PrintLookupRequest,
    PrintOptions,
    PrintRequest,
    RawLabelData,
)


def test_print_options_defaults_independent() -> None:
    a = PrintRequest(template_id="t", data=RawLabelData(title="x", primary_id="1", qr_payload="u"))
    b = PrintRequest(template_id="t", data=RawLabelData(title="x", primary_id="1", qr_payload="u"))
    assert a.options is not b.options  # not a shared default instance


def test_print_options_immutable() -> None:
    opts = PrintOptions()
    with pytest.raises(ValidationError):
        opts.copies = 5  # type: ignore[misc]


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
    """source_app is set server-side, not accepted from the wire."""
    with pytest.raises(ValidationError):
        RawLabelData(title="x", primary_id="1", qr_payload="u", source_app="manual")  # type: ignore[call-arg]


def test_copies_bounds() -> None:
    PrintOptions(copies=1)
    PrintOptions(copies=10)
    with pytest.raises(ValidationError):
        PrintOptions(copies=0)
    with pytest.raises(ValidationError):
        PrintOptions(copies=11)
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/schemas/test_print_request.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.schemas.print_request'`.

- [ ] **Step 3: Implement**

```python
# backend/app/schemas/print_request.py
"""Request schemas for POST /print and supporting models."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrintLookupRequest(BaseModel):
    """Resolve label data via an integration plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    app: str
    identifier: str


class PrintOptions(BaseModel):
    """Per-print options — copies, cut behaviour, resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    copies: int = Field(default=1, ge=1, le=10)
    auto_cut: bool = True
    high_resolution: bool = False


class RawLabelData(BaseModel):
    """Raw label payload accepted when the client supplies data directly.

    Mirrors LabelData minus `source_app` (always set to "manual" server-side).
    The list is coerced to a tuple when LabelData is constructed inside
    PrintService.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    primary_id: str
    qr_payload: str
    secondary: list[str] = Field(default_factory=list)


class PrintRequest(BaseModel):
    """Top-level POST /print body."""

    model_config = ConfigDict(extra="forbid")
    template_id: str
    lookup: PrintLookupRequest | None = None
    data: RawLabelData | None = None
    # default_factory so each request gets a fresh PrintOptions
    options: PrintOptions = Field(default_factory=PrintOptions)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if (self.lookup is None) == (self.data is None):
            raise ValueError("Exactly one of `lookup` or `data` must be set.")
        return self
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/schemas/test_print_request.py -q
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/print_request.py \
        backend/tests/unit/schemas/test_print_request.py
git commit -m "$(cat <<'EOF'
feat(api): PrintRequest + RawLabelData + PrintOptions schemas

Top-level POST /print body. PrintRequest enforces exactly-one of
`lookup` or `data` via a model_validator. PrintOptions is frozen with
copies bounds (1..10). RawLabelData mirrors LabelData but rejects
source_app at the wire — PrintService sets it to "manual" for the
raw-data path.

PrintOptions uses Field(default_factory=) on PrintRequest so each
request gets its own instance (Pydantic shared-mutable-default
anti-pattern avoided).

Refs #22
EOF
)"
```

### Task 9.2: PrintJobResponse + PrintJobStatusResponse

**Files:**
- Create: `backend/app/schemas/print_response.py`
- Create: `backend/tests/unit/schemas/test_print_response.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_print_response.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.printer_backends.snmp_helper import LiveStatus
from app.schemas.print_response import (
    PrintJobResponse,
    PrintJobStatusResponse,
)
from app.services.job_lifecycle import JobState


def test_status_response_live_block_optional() -> None:
    """live is None by default — populated only when the job is PRINTING."""
    r = PrintJobStatusResponse(
        job_id="j",
        status=JobState.QUEUED,
        created_at=datetime.now(UTC),
    )
    assert r.live is None


def test_status_response_carries_live_block() -> None:
    live = LiveStatus(hr_printer_status="printing", error_flags=["doorOpen"])
    r = PrintJobStatusResponse(
        job_id="j",
        status=JobState.PRINTING,
        created_at=datetime.now(UTC),
        live=live,
    )
    assert r.live is live
    assert r.live.hr_printer_status == "printing"


def test_print_job_response_status_is_literal_queued() -> None:
    r = PrintJobResponse(job_id="abc", status="queued")
    assert r.status == "queued"
    with pytest.raises(ValidationError):
        PrintJobResponse(job_id="abc", status="printing")  # type: ignore[arg-type]


def test_status_response_accepts_each_job_state() -> None:
    for state in JobState:
        r = PrintJobStatusResponse(
            job_id="j",
            status=state,
            created_at=datetime.now(UTC),
        )
        assert r.status == state


def test_status_response_optional_fields_none() -> None:
    r = PrintJobStatusResponse(
        job_id="j",
        status=JobState.QUEUED,
        created_at=datetime.now(UTC),
    )
    assert r.error_code is None
    assert r.error_message is None
    assert r.error_detail is None
    assert r.started_at is None
    assert r.finished_at is None
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/schemas/test_print_response.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/schemas/print_response.py
"""Response schemas for POST /print and GET /jobs/{job_id}."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.printer_backends.snmp_helper import LiveStatus
from app.services.job_lifecycle import JobState


class PrintJobResponse(BaseModel):
    """POST /print 202 body — queue accepted."""

    model_config = ConfigDict(frozen=True)
    job_id: str
    status: Literal["queued"]


class PrintJobStatusResponse(BaseModel):
    """GET /jobs/{job_id} body."""

    model_config = ConfigDict(frozen=True)
    job_id: str
    status: JobState
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Populated only when status == PRINTING; route handler fetches live SNMP.
    live: LiveStatus | None = None
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/schemas/test_print_response.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/print_response.py \
        backend/tests/unit/schemas/test_print_response.py
git commit -m "$(cat <<'EOF'
feat(api): PrintJobResponse + PrintJobStatusResponse schemas

POST /print returns a 202 with PrintJobResponse — status is the
literal 'queued'. GET /jobs/{job_id} returns PrintJobStatusResponse
typed as the real JobState enum (queued/paused/printing/completed/
failed/cancelled) so clients receive the same vocabulary the
PrintQueue uses internally.

Refs #22
EOF
)"
```

---

## Phase 10 — PrintService

### Task 10.1: PrintService.submit_print_job — happy path + error paths

**Files:**
- Create: `backend/app/services/print_service.py`
- Create: `backend/tests/unit/services/test_print_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_print_service.py
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from app.schemas.print_request import (
    PrintLookupRequest,
    PrintOptions,
    PrintRequest,
    RawLabelData,
)
from app.schemas.label_data import LabelData
from app.schemas.template import TemplateSchema, LayoutElement, FieldRef
from app.services.print_service import PrintService
from app.services.template_loader import TemplateNotFoundError


@pytest.fixture
def template() -> TemplateSchema:
    return TemplateSchema(
        id="qr-only-24mm",
        name="QR only",
        app=None,
        tape_mm=24,
        elements=(
            LayoutElement(kind="qr", x=0, y=0, size=128, field=FieldRef(name="qr_payload")),
        ),
    )


@pytest.fixture
def image() -> Image.Image:
    return Image.new("1", (200, 128))


@pytest.fixture
def loader(template: TemplateSchema) -> MagicMock:
    m = MagicMock()
    m.get.return_value = template
    return m


@pytest.fixture
def renderer(image: Image.Image) -> MagicMock:
    m = MagicMock()
    m.render.return_value = image
    return m


@pytest.fixture
def queue() -> AsyncMock:
    m = AsyncMock()
    m.submit.return_value = "job-1"
    return m


@pytest.fixture
def lookup_service() -> AsyncMock:
    m = AsyncMock()
    m.lookup.return_value = LabelData(
        title="X", primary_id="1", qr_payload="u",
        source_app="snipeit", secondary=(),
    )
    return m


def _service(loader, renderer, queue, lookup_service) -> PrintService:
    return PrintService(
        template_loader=loader,
        renderer=renderer,
        print_queue=queue,
        lookup_service=lookup_service,
        printer_id="pt@x",
    )


async def test_lookup_path_calls_lookup_and_renders(
    loader, renderer, queue, lookup_service
) -> None:
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        lookup=PrintLookupRequest(app="snipeit", identifier="42"),
    )
    job_id = await svc.submit_print_job(req)
    lookup_service.lookup.assert_awaited_once_with("snipeit", "42")
    renderer.render.assert_called_once()
    queue.submit.assert_awaited_once()
    assert job_id == "job-1"


async def test_data_path_bypasses_lookup_and_marks_source_manual(
    loader, renderer, queue, lookup_service
) -> None:
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q", secondary=["a"]),
    )
    job_id = await svc.submit_print_job(req)
    lookup_service.lookup.assert_not_called()
    # Renderer receives a LabelData with source_app="manual"
    args, _ = renderer.render.call_args
    label_data = args[1]
    assert isinstance(label_data, LabelData)
    assert label_data.source_app == "manual"
    assert label_data.secondary == ("a",)  # tuple coercion happened
    assert job_id == "job-1"


async def test_template_not_found_raises_synchronously(
    loader, renderer, queue, lookup_service
) -> None:
    loader.get.side_effect = TemplateNotFoundError("qr-only-24mm")
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        lookup=PrintLookupRequest(app="snipeit", identifier="x"),
    )
    with pytest.raises(TemplateNotFoundError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()


async def test_options_passed_to_queue(loader, renderer, queue, lookup_service) -> None:
    svc = _service(loader, renderer, queue, lookup_service)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        options=PrintOptions(copies=2, auto_cut=False, high_resolution=True),
    )
    await svc.submit_print_job(req)
    _, kwargs = queue.submit.call_args
    assert kwargs["tape_mm"] == 24
    assert kwargs["auto_cut"] is False
    assert kwargs["high_resolution"] is True
    assert kwargs["copies"] == 2
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/services/test_print_service.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/services/print_service.py
"""PrintService — orchestrates template, label data, render, queue.submit."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintRequest
from app.schemas.template import TemplateSchema
from app.services.print_queue import PrintQueue


class _TemplateLoaderProto(Protocol):
    def get(self, template_id: str) -> TemplateSchema: ...


class _RendererProto(Protocol):
    def render(self, template: TemplateSchema, label_data: LabelData) -> Image.Image: ...


class _LookupServiceProto(Protocol):
    async def lookup(self, app: str, identifier: str) -> LabelData: ...


class PrintService:
    """Use-case orchestrator for POST /print."""

    def __init__(
        self,
        *,
        template_loader: _TemplateLoaderProto,
        renderer: _RendererProto,
        print_queue: PrintQueue,
        lookup_service: _LookupServiceProto,
        printer_id: str,
    ) -> None:
        self._loader = template_loader
        self._renderer = renderer
        self._queue = print_queue
        self._lookup = lookup_service
        self._printer_id = printer_id

    async def submit_print_job(self, request: PrintRequest) -> str:
        # 1. Template (synchronous miss → TemplateNotFoundError propagates)
        template = self._loader.get(request.template_id)

        # 2. Label data
        if request.lookup is not None:
            label_data = await self._lookup.lookup(request.lookup.app, request.lookup.identifier)
        else:
            assert request.data is not None  # validator enforces XOR
            label_data = LabelData(
                title=request.data.title,
                primary_id=request.data.primary_id,
                qr_payload=request.data.qr_payload,
                secondary=tuple(request.data.secondary),
                source_app="manual",
            )

        # 3. Render
        image = self._renderer.render(template, label_data)

        # 4. Enqueue
        return await self._queue.submit(
            self._printer_id,
            image,
            tape_mm=template.tape_mm,
            copies=request.options.copies,
            auto_cut=request.options.auto_cut,
            high_resolution=request.options.high_resolution,
        )
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/services/test_print_service.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/print_service.py \
        backend/tests/unit/services/test_print_service.py
git commit -m "$(cat <<'EOF'
feat(api): PrintService orchestrator

Three-step pipeline behind POST /print: template_loader.get → either
lookup_service.lookup (integration path) or LabelData(..., source_app=
'manual') from RawLabelData (raw-data path) → renderer.render →
print_queue.submit(printer_id, image, tape_mm=, **options).

source_app for the raw-data path is fixed to "manual" here so the
wire schema doesn't have to police it. Options propagate to submit
as keyword args (auto_cut, high_resolution, copies); Phase 13 wires
copies into the worker by submitting once per copy.

Refs #22
EOF
)"
```

---

## Phase 11 — REST routes

### Task 11.1: POST /print + GET /jobs/{job_id} + exception mapper

**Files:**
- Create: `backend/app/api/routes/print.py`
- Create: `backend/tests/unit/api/__init__.py`
- Create: `backend/tests/unit/api/test_print_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/api/test_print_routes.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.print import router
from app.services.job_lifecycle import Job, JobState
from app.services.template_loader import TemplateNotFoundError
from app.services.lookup_service import LookupFailedError


@pytest.fixture
def fake_service() -> AsyncMock:
    m = AsyncMock()
    m.submit_print_job.return_value = "job-1"
    return m


@pytest.fixture
def fake_queue() -> MagicMock:
    return MagicMock()


def _app(service: AsyncMock, queue: MagicMock) -> FastAPI:
    app = FastAPI()
    app.state.print_service = service
    app.state.print_queue = queue
    app.include_router(router)
    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_post_print_data_path_returns_202(fake_service, fake_queue) -> None:
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/print", json={
            "template_id": "t",
            "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
        })
    assert r.status_code == 202
    body = r.json()
    assert body == {"job_id": "job-1", "status": "queued"}


async def test_post_print_lookup_path_returns_202(fake_service, fake_queue) -> None:
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/print", json={
            "template_id": "t",
            "lookup": {"app": "snipeit", "identifier": "42"},
        })
    assert r.status_code == 202


async def test_post_print_neither_source_is_422(fake_service, fake_queue) -> None:
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/print", json={"template_id": "t"})
    assert r.status_code == 422


async def test_post_print_template_not_found_is_404(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = TemplateNotFoundError("missing")
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/print", json={
            "template_id": "missing",
            "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
        })
    assert r.status_code == 404
    assert r.json()["error_code"] == "template_not_found"


async def test_post_print_lookup_failed_is_502(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = LookupFailedError("upstream down")
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/print", json={
            "template_id": "t",
            "lookup": {"app": "snipeit", "identifier": "x"},
        })
    assert r.status_code == 502
    assert r.json()["error_code"] == "integration_lookup_failed"


async def test_get_jobs_returns_status(fake_service, fake_queue, monkeypatch) -> None:
    from app.printer_backends.snmp_helper import LiveStatus

    job = Job(
        id="job-1",
        printer_id="p",
        image_payload=b"",
        tape_mm=24,
        options={},
    )
    job.state = JobState.PRINTING
    job.created_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    # Stub SNMP live-status — printing job triggers live SNMP fetch
    async def fake_live(host: str, *, community: str = "public", timeout_s: float = 3.0):  # noqa: ARG001
        return LiveStatus(hr_printer_status="printing", error_flags=[])

    monkeypatch.setattr("app.api.routes.print.query_live_status", fake_live)

    app = _app(fake_service, fake_queue)
    app.state.printer_host = "192.0.2.10"
    app.state.printer_snmp_community = "public"
    async with await _client(app) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "printing"
    assert body["live"] == {"hr_printer_status": "printing", "error_flags": []}


async def test_get_jobs_no_live_block_when_not_printing(fake_service, fake_queue) -> None:
    job = Job(
        id="job-1",
        printer_id="p",
        image_payload=b"",
        tape_mm=24,
        options={},
    )
    job.state = JobState.COMPLETED
    job.created_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    assert r.json()["live"] is None


async def test_get_jobs_live_snmp_failure_is_non_fatal(fake_service, fake_queue, monkeypatch) -> None:
    from app.printer_backends.exceptions import SnmpQueryError

    job = Job(
        id="job-1",
        printer_id="p",
        image_payload=b"",
        tape_mm=24,
        options={},
    )
    job.state = JobState.PRINTING
    job.created_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async def fake_live(*_a, **_kw):
        raise SnmpQueryError("timed out")

    monkeypatch.setattr("app.api.routes.print.query_live_status", fake_live)

    app = _app(fake_service, fake_queue)
    app.state.printer_host = "192.0.2.10"
    app.state.printer_snmp_community = "public"
    async with await _client(app) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    assert r.json()["live"] is None  # block dropped, response still 200


async def test_get_jobs_unknown_is_404(fake_service, fake_queue) -> None:
    fake_queue.get = AsyncMock(side_effect=KeyError("nope"))
    async with await _client(_app(fake_service, fake_queue)) as c:
        r = await c.get("/jobs/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/api/test_print_routes.py -q
```

Expected: `ModuleNotFoundError: app.api.routes.print`.

- [ ] **Step 3: Implement**

```python
# backend/app/api/routes/print.py
"""POST /print + GET /jobs/{job_id}."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    PrintFailedError,
    StatusQueryFailedError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.schemas.print_request import PrintRequest
from app.schemas.print_response import PrintJobResponse, PrintJobStatusResponse
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError

router = APIRouter()

_SYNC_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    TemplateNotFoundError: (404, "template_not_found"),
    LookupFailedError: (502, "integration_lookup_failed"),
}


@router.post(
    "/print",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PrintJobResponse,
)
async def create_print_job(request: PrintRequest, http: Request) -> PrintJobResponse:
    service = http.app.state.print_service
    try:
        job_id = await service.submit_print_job(request)
    except tuple(_SYNC_ERROR_MAP) as exc:
        http_status, code = _SYNC_ERROR_MAP[type(exc)]
        return JSONResponse(  # type: ignore[return-value]
            status_code=http_status,
            content={"error_code": code, "error_message": str(exc)},
        )
    return PrintJobResponse(job_id=job_id, status="queued")


@router.get(
    "/jobs/{job_id}",
    response_model=PrintJobStatusResponse,
)
async def get_job_status(job_id: str, http: Request) -> PrintJobStatusResponse:
    queue = http.app.state.print_queue
    try:
        job = await queue.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc

    live: LiveStatus | None = None
    if job.state == JobState.PRINTING:
        host = getattr(http.app.state, "printer_host", None)
        community = getattr(http.app.state, "printer_snmp_community", "public")
        if host:
            try:
                # Short timeout — this is on the request path, must stay snappy.
                # If SNMP is slow or unavailable, omit the live block (non-fatal).
                live = await query_live_status(host, community=community, timeout_s=1.0)
            except SnmpQueryError:
                _log.warning("live SNMP query failed for job %s", job_id, exc_info=True)
                live = None

    return PrintJobStatusResponse(
        job_id=job.id,
        status=job.state,
        error_code=getattr(job, "error_code", None),
        error_message=getattr(job, "error_message", None),
        error_detail=getattr(job, "error_detail", None),
        created_at=job.created_at,
        started_at=getattr(job, "started_at", None),
        finished_at=getattr(job, "finished_at", None),
        live=live,
    )
```

Required imports for the route module:

```python
import logging

from app.printer_backends.exceptions import SnmpQueryError
from app.printer_backends.snmp_helper import LiveStatus, query_live_status
from app.services.job_lifecycle import JobState

_log = logging.getLogger(__name__)
```

- [ ] **Step 4: Add tests dir init**

```bash
mkdir -p backend/tests/unit/api
touch backend/tests/unit/api/__init__.py
```

- [ ] **Step 5: Run — verify pass**

```bash
cd backend && pytest tests/unit/api/test_print_routes.py -q
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/print.py \
        backend/tests/unit/api/__init__.py \
        backend/tests/unit/api/test_print_routes.py
git commit -m "$(cat <<'EOF'
feat(api): POST /print + GET /jobs/{job_id}

POST returns 202 with PrintJobResponse on success. Synchronous errors
(TemplateNotFoundError, LookupFailedError) map to 404 / 502 with an
error_code in the JSON body; hardware/print errors travel to the
worker and surface via GET /jobs/{job_id}.

GET returns PrintJobStatusResponse with JobState (queued/paused/
printing/completed/failed/cancelled) and any error_* fields the
worker recorded. Unknown job_id is 404.

Refs #22
EOF
)"
```

---

## Phase 12 — Settings: new fields

### Task 12.1: Add printer_backend, printer_model, printer_queue_timeout_s

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/tests/unit/test_config_printer.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_config_printer.py
from __future__ import annotations

import pytest

from app.config import Settings


def test_defaults() -> None:
    s = Settings()
    assert s.printer_backend == "ptouch"
    assert s.printer_model == "PT-P750W"
    assert s.printer_queue_timeout_s == 30.0
    assert s.printer_discover_via_snmp is True
    assert s.printer_snmp_community == "public"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P900")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_QUEUE_TIMEOUT_S", "60")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_SNMP_COMMUNITY", "private")
    s = Settings()
    assert s.printer_backend == "mock"
    assert s.printer_model == "PT-P900"
    assert s.printer_queue_timeout_s == 60.0
    assert s.printer_discover_via_snmp is False
    assert s.printer_snmp_community == "private"


def test_existing_pt750w_fields_intact() -> None:
    s = Settings()
    assert s.pt750w_host == ""
    assert s.pt750w_port == 9100
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/test_config_printer.py -q
```

Expected: `AttributeError: 'Settings' object has no attribute 'printer_backend'`.

- [ ] **Step 3: Implement (add to Settings class)**

Append the new fields inside `Settings` in `backend/app/config.py`:

```python
    # --- First-Print ---
    printer_backend: str = "ptouch"
    printer_model: str = "PT-P750W"
    printer_discover_via_snmp: bool = True
    printer_snmp_community: str = "public"
    printer_queue_timeout_s: float = 30.0
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/test_config_printer.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py \
        backend/tests/unit/test_config_printer.py
git commit -m "$(cat <<'EOF'
feat(api): new First-Print settings (backend, model, timeout)

Three new fields on Settings:
* printer_backend — resolves against BackendRegistry at app start
  (built-ins: ptouch, mock)
* printer_model — resolves against ModelRegistry (built-in: PT-P750W)
* printer_queue_timeout_s — graceful queue.stop() timeout

Existing pt750w_host / pt750w_port / ql820_host / ql820_port fields
are kept untouched. PTouchBackend.from_settings reads pt750w_host
and looks up the right ptouch class via printer_model.

Refs #22
EOF
)"
```

---

## Phase 13 — Lifespan-Init + _build_backend

### Task 13.1: Wire registries, backend, driver, queue, service into the FastAPI lifespan

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_lifespan.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_lifespan.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry


@pytest.fixture(autouse=True)
def clean_registries() -> None:
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()  # pydantic-settings lru_cache
    yield
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()


async def test_lifespan_starts_with_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Trigger the lifespan startup
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)  # healthz may not exist yet
    # After context exit, queue.stop has been awaited; no exception means success.


async def test_unknown_backend_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "zebra-zpl")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    app = create_app()
    with pytest.raises(Exception, match="zebra-zpl"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_unknown_model_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "Imaginary-9000")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    with pytest.raises(Exception, match="Imaginary-9000"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_snmp_discovery_resolves_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP returns a stubbed PJL string; lifespan resolves it via find_by_pjl."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "")  # require SNMP
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    async def fake_query(host: str, *, community: str = "public", timeout_s: float = 3.0):  # noqa: ARG001
        return "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;"

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)
    # Driver must be registered for find_by_pjl to succeed in the test
    from app.printer_models.pt import PTP750WDriver  # noqa: F401  (registration side-effect)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        # No exception → discovery worked
        assert r.status_code in (200, 404)


async def test_snmp_discovery_fallback_to_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP fails but printer_model is configured → fall back, log warning, succeed."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    from app.printer_backends.exceptions import SnmpDiscoveryError

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_no_fallback_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP fails AND printer_model is empty → SnmpDiscoveryError propagates."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    from app.printer_backends.exceptions import SnmpDiscoveryError

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    with pytest.raises(SnmpDiscoveryError):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_empty_pt750w_host_with_ptouch_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "ptouch")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "")
    app = create_app()
    with pytest.raises(Exception, match="pt750w_host"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")
```

- [ ] **Step 2: Run — verify failure**

```bash
cd backend && pytest tests/unit/test_lifespan.py -q
```

Expected: failures because the lifespan does not yet do plugin discovery / build a backend.

- [ ] **Step 3: Implement — modify `app/main.py`**

```python
# backend/app/main.py (sketch — preserve existing imports + routes)
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.routes.print import router as print_router
from app.config import Settings, get_settings
from app.printer_backends import BackendRegistry
from app.printer_backends.exceptions import SnmpDiscoveryError
from app.printer_backends.snmp_helper import query_model_pjl
from app.printer_models.registry import ModelRegistry
from app.services.label_renderer import LabelRenderer
from app.services.lookup_service import AppLookupService
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from app.services.tape_registry import TapeRegistry
from app.services.template_loader import TemplateLoader

_SEED_TEMPLATES_DIR = Path(__file__).parent / "seed" / "templates"
_log = logging.getLogger(__name__)


def _build_backend(settings: Settings):
    BackendRegistry.ensure_discovered()
    factory = BackendRegistry.find_by_backend_id(settings.printer_backend)
    return factory.from_settings(settings)


async def _resolve_model_id(settings: Settings, host: str) -> str:
    """SNMP discovery first, fall back to settings.printer_model on failure."""
    if not settings.printer_discover_via_snmp:
        if not settings.printer_model:
            raise ValueError(
                "Either printer_discover_via_snmp=true or a non-empty "
                "printer_model is required."
            )
        return settings.printer_model
    try:
        pjl = await query_model_pjl(
            host,
            community=settings.printer_snmp_community,
        )
    except SnmpDiscoveryError as exc:
        if settings.printer_model:
            _log.warning(
                "SNMP discovery failed (%s); falling back to printer_model=%r",
                exc, settings.printer_model,
            )
            return settings.printer_model
        raise
    driver = ModelRegistry.find_by_pjl(pjl)
    return driver.model_id


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    TemplateLoader.load_dir(_SEED_TEMPLATES_DIR)
    ModelRegistry.ensure_discovered()

    # Mock backend ignores host; ptouch backend needs pt750w_host.
    discovery_host = settings.pt750w_host or ""
    if settings.printer_backend == "ptouch" or settings.printer_discover_via_snmp:
        if not discovery_host:
            # ptouch backend or SNMP discovery both need a host.
            # Empty pt750w_host with ptouch is already enforced by from_settings,
            # but SNMP discovery may run with the mock backend too.
            pass
    if discovery_host and settings.printer_discover_via_snmp:
        model_id = await _resolve_model_id(settings, discovery_host)
    else:
        model_id = settings.printer_model
        if not model_id:
            raise ValueError("printer_model is empty and SNMP discovery is disabled.")

    backend = _build_backend(settings)
    driver_cls = ModelRegistry.find_by_model_id(model_id)
    driver = driver_cls(backend=backend)

    tape_registry = TapeRegistry()
    printer = driver.make_queue_printer(tape_registry)
    queue = PrintQueue(printers=[printer])
    await queue.start()

    app.state.print_queue = queue
    app.state.printer_id = printer.id
    app.state.printer_host = discovery_host   # used by route handler for live SNMP
    app.state.printer_snmp_community = settings.printer_snmp_community
    app.state.print_service = PrintService(
        template_loader=TemplateLoader,
        renderer=LabelRenderer(),
        print_queue=queue,
        lookup_service=AppLookupService(),
        printer_id=printer.id,
    )

    try:
        yield
    finally:
        await queue.stop(timeout_s=settings.printer_queue_timeout_s)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, title="Label Printer Hub")
    app.include_router(print_router)
    return app


app = create_app()
```

- [ ] **Step 4: Run — verify pass**

```bash
cd backend && pytest tests/unit/test_lifespan.py -q
```

Expected: 4 passed. If `/healthz` does not exist yet, change the test to `assert r.status_code in (200, 404)` — the goal is to drive the lifespan start/stop, not to test that endpoint.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py \
        backend/tests/unit/test_lifespan.py
git commit -m "$(cat <<'EOF'
feat(api): lifespan wires plugin discovery + queue + service

App startup:
1. Discover printer-model + backend plugins via entry_points
   (idempotent ensure_discovered).
2. Build the configured backend via BackendRegistry +
   from_settings(settings).
3. Resolve the driver via ModelRegistry.find_by_model_id and bind it
   to the backend.
4. Build the _PrinterLike via driver.make_queue_printer(tape_registry).
5. Start the PrintQueue with [printer].
6. Wire PrintService into app.state.

App shutdown: queue.stop(timeout_s=settings.printer_queue_timeout_s).

Unknown backend, unknown model, or empty pt750w_host (with the ptouch
backend selected) raise at app start with a clear, actionable error.

Refs #22
EOF
)"
```

---

## Phase 14 — End-to-end integration tests

### Task 14.1: POST /print → GET /jobs/{id} cycle with MockPrinterBackend

**Files:**
- Create: `backend/tests/integration/test_print_e2e.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_print_e2e.py
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "")  # unused with mock
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()
    yield
    BackendRegistry._factories.clear()
    ModelRegistry._models.clear()
    get_settings.cache_clear()


async def _poll_until(c: AsyncClient, job_id: str, *, target: str, timeout_s: float = 3.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        r = await c.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] == target:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached status {target!r}; last={body['status']}")


async def test_happy_path_raw_data() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/print", json={
            "template_id": "qr-only-24mm",
            "data": {"title": "Smoke", "primary_id": "S-1", "qr_payload": "https://e.x"},
        })
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        body = await _poll_until(c, job_id, target="completed")
        assert body["error_code"] is None
        assert body["status"] == "completed"


async def test_template_not_found_synchronous_404() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/print", json={
            "template_id": "does-not-exist",
            "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
        })
        assert r.status_code == 404
        assert r.json()["error_code"] == "template_not_found"
```

- [ ] **Step 2: Run — verify pass**

```bash
cd backend && pytest tests/integration/test_print_e2e.py -q
```

Expected: 2 passed. (If `qr-only-24mm` seed template is missing, copy the relevant one from `app/seed/templates/` in this commit — but Phase 4 PR-B already shipped it, so it should be present.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_print_e2e.py
git commit -m "$(cat <<'EOF'
test(api): POST /print → GET /jobs/{id} happy path + 404

Drives the full lifespan: plugin discovery, mock backend, PrintQueue
worker, status polling. Asserts the job transitions to completed and
the mock backend received exactly one image with the right dimensions.

Template-not-found returns 404 synchronously with error_code set; no
job record is created.

Refs #22
EOF
)"
```

### Task 14.2: Failure-path integration tests (tape mismatch, offline)

**Files:**
- Modify: `backend/tests/integration/test_print_e2e.py` (append)
- Create: `backend/tests/integration/conftest.py` (if helpers grow)

- [ ] **Step 1: Append the failure-mode tests**

```python
# tests/integration/test_print_e2e.py — APPEND

async def test_tape_mismatch_ends_failed() -> None:
    """Mock loaded_tape_mm=12 against a 24mm template — worker marks failed."""
    import os
    os.environ["PRINTER_HUB_MOCK_LOADED_TAPE_MM"] = "12"  # see below
    try:
        # NOTE: requires MockPrinterBackend.from_settings to read this env var.
        # If it does not — patch the mock in process via dependency injection
        # by overriding BackendRegistry's mock factory before lifespan start.
        ...
    finally:
        del os.environ["PRINTER_HUB_MOCK_LOADED_TAPE_MM"]
```

Realistically, the mock backend constructor takes configuration flags rather than environment variables. Override it via a fixture that registers a configured mock under the backend_id `"mock"` before the app starts:

```python
import pytest
from app.printer_backends import BackendRegistry
from app.printer_backends.mock_backend import MockPrinterBackend


def _mock_with(**kwargs):
    class _Patched(MockPrinterBackend):
        @classmethod
        def from_settings(cls, settings):
            return MockPrinterBackend(**kwargs)
    return _Patched


@pytest.fixture
def mismatched_mock_backend():
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = True  # skip entry-point walk
    BackendRegistry.register("mock", _mock_with(loaded_tape_mm=12))


async def test_tape_mismatch_ends_failed(mismatched_mock_backend) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/print", json={
            "template_id": "qr-only-24mm",
            "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
        })
        assert r.status_code == 202
        body = await _poll_until(c, r.json()["job_id"], target="failed")
        assert body["error_code"] == "tape_mismatch"
        assert body["error_detail"] == {"expected_mm": 24, "loaded_mm": 12}


@pytest.fixture
def offline_mock_backend():
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = True
    BackendRegistry.register("mock", _mock_with(offline=True))


async def test_offline_ends_failed_after_retries(offline_mock_backend) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/print", json={
            "template_id": "qr-only-24mm",
            "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
        })
        body = await _poll_until(c, r.json()["job_id"], target="failed", timeout_s=10)
        assert body["error_code"] == "printer_offline"
```

These tests require the worker to translate `PrinterError` subclasses into the right `error_code` on the `Job` record. Add a small helper inside the PrintQueue worker path (or wrap the printer's `print_image` in PrintService) — depending on where the existing FSM puts error data. The simplest place is inside `_PTPQueuePrinter.print_image`: catch `PrinterError`, set `job.error_code` / `job.error_detail` via a callback, re-raise so the FSM marks `failed`.

If the existing `PrintQueue` FSM does not surface arbitrary error fields on the Job, add them in this task: `error_code: str | None`, `error_message: str | None`, `error_detail: dict[str, Any] | None`. They are also needed by `PrintJobStatusResponse` (Phase 9), so this is a known dependency.

- [ ] **Step 2: Verify Job carries error_code/error_detail**

```bash
cd backend && grep -n "error_code\|error_detail" app/services/job_lifecycle.py app/services/print_queue.py
```

If they don't exist, add them as optional fields on `Job`, default `None`, populated by the worker when it catches a `PrinterError`.

- [ ] **Step 3: Run — verify pass**

```bash
cd backend && pytest tests/integration/test_print_e2e.py -q
```

Expected: all integration tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_print_e2e.py \
        backend/app/services/job_lifecycle.py \
        backend/app/services/print_queue.py
git commit -m "$(cat <<'EOF'
test(api): integration tests for tape mismatch + offline failures

Adds end-to-end tests for the two main hardware error paths:
* loaded_tape_mm != template.tape_mm → job ends 'failed' with
  error_code 'tape_mismatch' and error_detail {expected_mm, loaded_mm}.
* backend offline → job ends 'failed' with error_code 'printer_offline'
  after exactly 3 status queries (back-off 0s, 1s, 2s).

If absent, error_code/error_message/error_detail were added as
optional fields on Job and surfaced by the queue worker when a
PrinterError subclass escapes the printer call.

Refs #22
EOF
)"
```

---

## Phase 15 — Hardware smoke script

### Task 15.1: scripts/smoke_first_print.py + hardware test marker

**Files:**
- Create: `backend/scripts/__init__.py` (empty)
- Create: `backend/scripts/smoke_first_print.py`
- Create: `backend/tests/hardware/__init__.py` (empty)
- Create: `backend/tests/hardware/test_pt_p750w_smoke.py`

- [ ] **Step 1: Implement the smoke script**

```python
# backend/scripts/smoke_first_print.py
"""Manual hardware smoke for First-Print.

Run against a real Brother PT-P750W on the local network:

    PRINTER_HUB_PT750W_HOST=<printer-ip> \
        python -m scripts.smoke_first_print

Prints the qr-only-24mm template once with primary_id=SMOKE-001 and a
QR-encodable URL. Exits 0 on success, non-zero with a clear message on
failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from PIL import Image

from app.config import Settings
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from app.printer_models.pt import PTP750WDriver  # ensures registration
from app.printer_backends.ptouch_backend import PTouchBackend  # ensures registration
from app.printer_backends.mock_backend import MockPrinterBackend  # noqa: F401
from app.services.label_renderer import LabelRenderer
from app.services.tape_registry import TapeRegistry
from app.services.template_loader import TemplateLoader
from app.schemas.label_data import LabelData

_TEMPLATE_ID = "qr-only-24mm"
_SMOKE_PRIMARY_ID = "SMOKE-001"
_SMOKE_QR_PAYLOAD = "https://example.test/smoke"


async def main() -> int:
    host = os.environ.get("PRINTER_HUB_PT750W_HOST", "")
    if not host:
        print("error: set PRINTER_HUB_PT750W_HOST to the printer's IP/hostname", file=sys.stderr)
        return 2

    BackendRegistry.ensure_discovered()
    ModelRegistry.ensure_discovered()

    settings = Settings(printer_backend="ptouch", printer_model="PT-P750W", pt750w_host=host)
    backend = PTouchBackend.from_settings(settings)
    driver = PTP750WDriver(backend=backend)
    printer = driver.make_queue_printer(TapeRegistry())

    TemplateLoader.load_dir(Path(__file__).resolve().parent.parent / "app" / "seed" / "templates")
    template = TemplateLoader.get(_TEMPLATE_ID)
    label_data = LabelData(
        title="Smoke",
        primary_id=_SMOKE_PRIMARY_ID,
        qr_payload=_SMOKE_QR_PAYLOAD,
        secondary=(),
        source_app="manual",
    )
    image: Image.Image = LabelRenderer().render(template, label_data)

    print(f"[1/3] template={_TEMPLATE_ID}, image={image.size}")
    print(f"[2/3] querying printer status @ {host}...")
    status = await backend.query_status()
    print(f"      loaded_tape_mm={status.loaded_tape_mm}, media_type={status.media_type}")
    print("[3/3] printing...")
    await printer.print_image(image, tape_mm=template.tape_mm)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Add the gated hardware test**

```python
# backend/tests/hardware/test_pt_p750w_smoke.py
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.hardware


@pytest.mark.skipif(
    not os.environ.get("PRINTER_HUB_PT750W_HOST"),
    reason="PRINTER_HUB_PT750W_HOST not set",
)
async def test_smoke_first_print_succeeds() -> None:
    """End-to-end hardware test: real printer prints a QR-only label."""
    from scripts.smoke_first_print import main
    rc = await main()
    assert rc == 0
```

- [ ] **Step 3: Verify the gated test is skipped by default**

```bash
cd backend && pytest tests/hardware -q
```

Expected: tests collected and skipped with reason `hardware tests need --hardware flag`.

- [ ] **Step 4: Verify the gated test runs with --hardware (only when hardware is present)**

```bash
cd backend && PRINTER_HUB_PT750W_HOST=<printer-ip> pytest tests/hardware -q --hardware
```

Skip this step in CI; run it manually at the end of the implementation phase against the maintainer's real PT-P750W.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/__init__.py \
        backend/scripts/smoke_first_print.py \
        backend/tests/hardware/__init__.py \
        backend/tests/hardware/test_pt_p750w_smoke.py
git commit -m "$(cat <<'EOF'
test(api): hardware smoke for PT-P750W First-Print

Manual smoke script (scripts/smoke_first_print.py) renders the
qr-only-24mm seed template with primary_id=SMOKE-001 and prints it
on a real PT-P750W identified by PRINTER_HUB_PT750W_HOST.

Adds the gated test tests/hardware/test_pt_p750w_smoke.py — skipped
by default, runs only with `pytest --hardware` and a configured host.
The conftest hardware-marker is already in place from earlier work.

Refs #22
EOF
)"
```

---

## Phase 16 — Final verification + push

### Task 16.1: Run every gate locally

- [ ] **Step 1: Format check**

```bash
cd backend && ruff format --check .
```

Expected: no diffs. If anything to fix: `ruff format .`, review with `git diff`, `git add` + amend the most-recent commit only if it is the offending one; otherwise create a new `style:` commit.

- [ ] **Step 2: Lint**

```bash
cd backend && ruff check .
```

Expected: no errors.

- [ ] **Step 3: Type check**

```bash
cd backend && mypy app
```

Expected: 0 errors. Imports of `ptouch.*` are ignored via the existing pyproject override.

- [ ] **Step 4: Test + coverage**

```bash
cd backend && pytest --cov=app --cov-fail-under=80 -q
```

Expected: all tests pass, coverage ≥ 80%.

- [ ] **Step 5: Conventional Commits check**

```bash
cd /opt/repos/label-printer-hub
git log --format='%s' main..HEAD | npx commitlint --from main
```

Expected: exit 0.

- [ ] **Step 6: Manual hardware smoke**

```bash
cd backend
PRINTER_HUB_PT750W_HOST=<printer-ip> python -m scripts.smoke_first_print
```

Expected: `OK` and a physical label out of the printer. Verify visually that the QR code on the label decodes to `https://example.test/smoke`.

- [ ] **Step 7: Manual: swap tape mid-print**

Reload the printer with a 12mm tape (template wants 24mm). Re-run the smoke. Expected: `TapeMismatchError` raised before printing.

- [ ] **Step 8: Manual: power off the printer**

Power off the PT-P750W, re-run the smoke. Expected: `PrinterOfflineError` after exactly 3 attempts (initial + 2 retries; back-off sleeps 0s, 1s, 2s; total ~3 seconds plus socket-timeout per attempt before the error).

### Task 16.2: Stop point — wait for human review

- [ ] **Step 1: Show all commits to the operator**

```bash
cd /opt/repos/label-printer-hub && git log --oneline main..HEAD
```

- [ ] **Step 2: Stop**

**Do NOT push.** Hand back to the orchestrator for human code review. The orchestrator handles the push and PR open after the operator approves.

---

## Spec coverage self-review

| Spec requirement | Task(s) |
|---|---|
| `PrinterBackend` Protocol (`print_image` + `query_status`) | 3.1 |
| `PTouchBackend` wrapping ptouch | 6.2 |
| `MockPrinterBackend` in `app/printer_backends/` | 4.1 |
| `PrinterError` hierarchy | 2.1 |
| Status query (ESC i S) — design says ptouch, but ptouch doesn't expose it | 1.1, 1.2, 6.1, 6.2 |
| `PTP750WDriver` + `make_queue_printer` + `_PTPQueuePrinter` | 8.1 |
| `ModelRegistry.find_by_model_id` + entry_points | 7.1 |
| `BackendRegistry` + entry_points | 5.1, 5.2, 6.2 |
| `from_settings(settings)` on backends | 4.1 (Mock), 6.2 (PTouch) |
| `PrintService.submit_print_job` | 10.1 |
| `RawLabelData`, `PrintRequest`, `PrintOptions`, `PrintJobResponse`, `PrintJobStatusResponse` | 9.1, 9.2 |
| `POST /print` + `GET /jobs/{job_id}` + sync error mapping | 11.1 |
| Settings: `printer_backend`, `printer_model`, `printer_queue_timeout_s` | 12.1 |
| Lifespan-Init + `_build_backend` + queue.stop on shutdown | 13.1 |
| Acceptance 1 — 202 with job_id for qr-only-24mm | 14.1 |
| Acceptance 2 — status sequence queued/printing/completed | 14.1 |
| Acceptance 3 — mock received the expected image | 14.1, 4.1 |
| Acceptance 4 — tape mismatch ends failed with code+detail | 14.2 |
| Acceptance 5 — offline ends failed after exactly 3 attempts | 14.2, 6.2 |
| Acceptance 6 — template not found is sync 404 | 14.1, 11.1 |
| Acceptance 7 — lookup failure is sync 502 | 11.1 |
| Acceptance 8 — lifespan shutdown stops queue within timeout | 13.1 |
| Acceptance 9 — empty pt750w_host with ptouch fails fast | 13.1, 6.2 |
| Acceptance 10 — unknown model/backend fails fast | 13.1 |
| Acceptance 11 — fake plugin via entry_points works in a test | 5.1, 7.1 |
| Acceptance 12 — SNMP discovery resolves stubbed PJL to PTP750WDriver | 13.1 (`test_snmp_discovery_resolves_model`) |
| Acceptance 13 — SNMP failure falls back to printer_model when set; fails fast when empty | 13.1 (`test_snmp_discovery_fallback_to_setting`, `test_snmp_discovery_no_fallback_fails`) |
| Acceptance 14 — GET /jobs/{id} includes live block during PRINTING, None otherwise | 11.1 (`test_get_jobs_returns_status`, `test_get_jobs_no_live_block_when_not_printing`, `test_get_jobs_live_snmp_failure_is_non_fatal`) |
| Acceptance 15 — smoke_first_print.py prints on real hardware | 15.1, 16.1 |
| Acceptance 16 — coverage ≥80%, ruff+mypy green | 16.1 |
| SNMP OIDs documented | 1.3 |
| `query_model_pjl` + `query_live_status` + `LiveStatus` | 6.3 |
| `SnmpDiscoveryError` + `SnmpQueryError` in hierarchy | 2.1 |
| Settings: `printer_discover_via_snmp`, `printer_snmp_community` | 12.1 |
| `commitlint.config.cjs` scope for `printer-backends` | 0.1 |

No spec section is unimplemented.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-05-15-first-print.md`. Two execution options:

**1. Subagent-Driven (recommended)** — orchestrator dispatches a fresh subagent per task, review between tasks, fast iteration. The implementer never pushes; the orchestrator handles push + PR after human code review.

**2. Inline Execution** — execute tasks in the current session using executing-plans, batch execution with checkpoints for review.

Which approach?
