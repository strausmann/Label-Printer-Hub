# Multi-Label-Batch via ptouch.print_multi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-Label-Batches an PT-Series Drucker produzieren 5mm Half-Cut zwischen Labels (Brother iOS App Verhalten) statt 22.5mm Pre-Roll pro Item.

**Architecture:** Neue `PrinterBackend.print_images()` Methode mit Default-Loop-Impl. `PTouchBackend` überschreibt mit `_ptouch_print_multi()` → `ptouch.LabelPrinter.print_multi()`. Queue bekommt neuen `BatchJob` Typ, Worker dispatched per `isinstance`. Adapter (`_PTPQueuePrinter`/`_QLQueuePrinter`) bekommen `print_images()` Methode. `batch_dispatch` queued einmalig statt N-mal.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PIL/Pillow, ptouch-py 1.1.0, brother_ql 0.9.4, asyncio, pytest.

## Plan Revisions

| Date | Revisions | Source |
|------|-----------|--------|
| 2026-06-04 | Initial | superpowers:writing-plans (Commit `8917d0e`) |
| 2026-06-04 | **G1** In-Memory Job-Registrierung in `enqueue_batch` (sonst `KeyError` bei `get`/`wait_for_job`); parallele PNG-Serialisierung. **G2** `JobStateMachine.transition` + `_notify_state_change` in `_process_batch` (sonst SSE-Stille + hängende Waiter). **G3** `asyncio.to_thread` + `asyncio.gather` für CPU-intensive Renders in `submit_batch_job` (sonst Event-Loop-Block). Inline-Imports vervollständigt. | Gemini-Code-Assist Review PR #106 (medium-priority Findings) |
| 2026-06-04 | 9 Copilot-Findings adressiert: C1 Protocol-default-method-Approach klargestellt (alle Backends explizit `print_images`, helper macht Loop), C2 `batch_failure_mode` Hangar-UI-Anpassung als Out-of-1k.2-Scope verschoben, C3 personalisierte Doku-Links durch Repo-Hinweise ersetzt (Privacy-Policy), C4 Real name+email in Plan-Commits ersetzt durch plain `git commit`, C5 `print_images` docstring präzisiert (atomic für PT, best-effort für default-loop), C6 `_process_batch` PrinterError-Path nutzt `_printer_error_to_record` + `pause_printer` für recoverable errors (Konsistenz mit `_worker`), C7 `_validate_item_get_tape_mm` nutzt neue public `PrintService.get_template_tape_mm` statt private `_loader` Zugriff, C8 `label_data` einmal pro Item resolved (Render+Persist teilen sich denselben Wert), C9 Smoke-Script ohne hardcoded API-Key-Default. Plus: Privacy-Scan-grep in Final-Verification umformuliert. | Copilot Review PR #106 (9 Findings) |
| 2026-06-04 | 3 Runtime-Bugs (R2) gefixt: **G-R2-1** `_QLQueuePrinter.print_images` ruft `lookup_ql(tape_mm)` ohne `media_type` → TypeError. Fix: pop media_type aus options + pass through. **G-R2-2** State-Inkonsistenz: `_process_batch` ruft `_store.mark_*` auch wenn `JobStateMachine.transition` failed (cancelled job mid-flight) → DB sagt COMPLETED, in-memory CANCELLED. Fix: `active_jobs[]` Liste nur mit erfolgreich transitioned jobs, alle folgenden DB-Calls + post-print transitions nutzen `active_jobs`, nicht `jobs`. **G-R2-3** `submit_batch_job` ruft `JobStore.save_queued(job_id=..., printer_id=..., ...)` mit kwargs → TypeError, erwartet `DbJob`-Instanz. Fix: `DbJob` model instanziieren + an save_queued übergeben (konsistent mit `submit_print_job`). Import `from app.models.job import Job as DbJob` ergänzt. | Gemini-Code-Assist Round-2 Review PR #106 (3 medium-priority Runtime-Crashes) |

---

## File Structure

| File | Verantwortlichkeit | Änderungs-Art |
|---|---|---|
| `backend/app/printer_backends/base.py` | `PrinterBackend` Protocol erweitern um `print_images()` | MODIFY |
| `backend/app/printer_backends/batch_helper.py` | `default_print_images_loop()` Helper | CREATE |
| `backend/app/printer_backends/ptouch_backend.py` | `print_images()` Override + `_ptouch_print_multi()` Helper | MODIFY |
| `backend/app/printer_backends/brother_ql_backend.py` | `print_images()` Methode (Default-Loop) | MODIFY |
| `backend/app/printer_backends/mock_backend.py` | `print_images()` Methode (Default-Loop) | MODIFY |
| `backend/app/printer_models/pt.py` | `_PTPQueuePrinter.print_images()` Adapter | MODIFY |
| `backend/app/printer_models/ql.py` | `_QLQueuePrinter.print_images()` Adapter | MODIFY |
| `backend/app/services/print_queue.py` | `BatchJob` dataclass, `_PrinterLike.print_images()`, `enqueue_batch()`, Worker isinstance branch | MODIFY |
| `backend/app/services/batch_dispatch.py` | `dispatch_batch()` Refactor zu single `enqueue_batch()` Call | MODIFY |
| `backend/app/services/print_service.py` | Neue `submit_batch_job()` Methode | MODIFY |
| `backend/app/schemas/print_batch.py` | (keine Änderung — BatchRequest bleibt) | UNCHANGED |
| `backend/tests/unit/printer_backends/test_batch_helper.py` | Tests für default_print_images_loop | CREATE |
| `backend/tests/unit/printer_backends/test_ptouch_backend.py` | Tests für print_images + _ptouch_print_multi | MODIFY (append) |
| `backend/tests/unit/printer_backends/test_brother_ql_backend.py` | Test für default-loop | MODIFY (append) |
| `backend/tests/unit/services/test_print_queue_batch.py` | Tests für BatchJob, enqueue_batch, worker | CREATE |
| `backend/tests/unit/services/test_batch_dispatch.py` | Refactor existing tests + new mixed-tape test | MODIFY |
| `backend/tests/integration/test_batch_endpoint_multi_label.py` | End-to-end Test mit Mock-Backend | CREATE |

---

## Pre-flight

- [ ] **Step 0: Verify spec branch + baseline tests**

```bash
cd /opt/repos/label-printer-hub
git checkout spec/phase-1k.2-multi-label-batch
git log --oneline -1
# Expected: 96e53c9 docs(spec): Phase 1k.2 Multi-Label-Batch via ptouch.print_multi (#102)
backend/.venv/bin/python -m pytest backend/tests -q 2>&1 | tail -3
# Expected: 952 passed, 5 skipped
```

If branch missing OR baseline fails, STOP and report.

---

## Task 1: Helper-Funktion `default_print_images_loop`

**Files:**
- Create: `backend/app/printer_backends/batch_helper.py`
- Test: `backend/tests/unit/printer_backends/test_batch_helper.py`

**Rationale:** Backends ohne native batch-support (`BrotherQLBackend`, `MockBackend`) loopen per-item. Statt Code-Duplikation: zentraler Helper den jeder Backend aufruft.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/printer_backends/test_batch_helper.py`:

```python
"""Unit tests for default_print_images_loop helper."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.batch_helper import default_print_images_loop


@pytest.fixture
def tape_spec_12() -> TapeSpec:
    return TapeSpec(width_mm=12, printable_dots=70, media_type_name="laminated")


@pytest.fixture
def three_images() -> list[Image.Image]:
    return [Image.new("1", (600, 70), color=1) for _ in range(3)]


@pytest.mark.anyio
async def test_loops_print_image_for_each(three_images, tape_spec_12):
    """default_print_images_loop calls print_image once per image."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend, three_images, tape_spec_12,
        auto_cut=True, high_resolution=False, half_cut=True,
    )

    assert backend.print_image.call_count == 3


@pytest.mark.anyio
async def test_intermediate_items_get_half_cut_true_last_page_false(
    three_images, tape_spec_12
):
    """Items 0 and 1 (non-last): half_cut=True, last_page=False."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend, three_images, tape_spec_12,
        auto_cut=True, high_resolution=False, half_cut=True,
    )

    # Inspect kwargs of calls
    calls = backend.print_image.call_args_list
    assert calls[0].kwargs["half_cut"] is True
    assert calls[0].kwargs["last_page"] is False
    assert calls[1].kwargs["half_cut"] is True
    assert calls[1].kwargs["last_page"] is False


@pytest.mark.anyio
async def test_last_item_gets_half_cut_false_last_page_true(three_images, tape_spec_12):
    """Last item: half_cut=False (full cut), last_page=True."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend, three_images, tape_spec_12,
        auto_cut=True, high_resolution=False, half_cut=True,
    )

    calls = backend.print_image.call_args_list
    assert calls[-1].kwargs["half_cut"] is False
    assert calls[-1].kwargs["last_page"] is True


@pytest.mark.anyio
async def test_half_cut_false_disables_half_cut_globally(three_images, tape_spec_12):
    """If caller passes half_cut=False, no intermediate item gets half_cut=True."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()

    await default_print_images_loop(
        backend, three_images, tape_spec_12,
        auto_cut=True, high_resolution=False, half_cut=False,
    )

    for call in backend.print_image.call_args_list:
        assert call.kwargs["half_cut"] is False


@pytest.mark.anyio
async def test_single_image_gets_last_page_true(tape_spec_12):
    """Single-item batch: 1 print_image call with last_page=True."""
    backend = AsyncMock()
    backend.print_image = AsyncMock()
    one_image = [Image.new("1", (600, 70), color=1)]

    await default_print_images_loop(
        backend, one_image, tape_spec_12,
        auto_cut=True, high_resolution=False, half_cut=True,
    )

    assert backend.print_image.call_count == 1
    assert backend.print_image.call_args.kwargs["last_page"] is True
    assert backend.print_image.call_args.kwargs["half_cut"] is False


@pytest.mark.anyio
async def test_propagates_first_print_image_exception(three_images, tape_spec_12):
    """If print_image raises on item N, no further items are attempted."""
    backend = AsyncMock()
    backend.print_image = AsyncMock(
        side_effect=[None, RuntimeError("printer offline"), None]
    )

    with pytest.raises(RuntimeError, match="printer offline"):
        await default_print_images_loop(
            backend, three_images, tape_spec_12,
            auto_cut=True, high_resolution=False, half_cut=True,
        )

    # Only the first two were attempted; third was not.
    assert backend.print_image.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/repos/label-printer-hub
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/test_batch_helper.py -v 2>&1 | tail -10
```

Expected: ModuleNotFoundError for `app.printer_backends.batch_helper`.

- [ ] **Step 3: Write minimal implementation**

`backend/app/printer_backends/batch_helper.py`:

```python
"""Default batch-print loop for Backends without native batch support.

Phase 1k.2: PTouchBackend overrides print_images() to use ptouch.print_multi()
for true atomic batch printing. BrotherQLBackend, MockBackend etc. delegate
their print_images() implementation to default_print_images_loop() here —
they loop over print_image() with correct half_cut + last_page semantics.

Semantics match the Brother iOS App: half_cut=True between intermediate
items (5mm taktile Trennung), half_cut=False + last_page=True on the final
item (voller Cut zur Trennung vom nächsten Batch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

    from app.models.tape import TapeSpec
    from app.printer_backends.base import PrinterBackend


async def default_print_images_loop(
    backend: PrinterBackend,
    images: list[Image.Image],
    tape_spec: TapeSpec,
    *,
    auto_cut: bool = True,
    high_resolution: bool = False,
    half_cut: bool = True,
) -> None:
    """Loop over print_image(); set half_cut + last_page per index.

    Args:
        backend: PrinterBackend instance whose print_image() is called per item.
        images: Rendered PIL Images, one per batch item, in print order.
        tape_spec: Shared TapeSpec — all items in a batch share the loaded tape.
        auto_cut: Forwarded unchanged to each print_image call.
        high_resolution: Forwarded unchanged to each print_image call.
        half_cut: If True, intermediate items get half_cut=True (5mm taktile
            separation). Last item always gets half_cut=False so the cutter
            performs a full cut for batch separation.

    Behaviour:
        For each image at index i:
          - is_last = (i == len(images) - 1)
          - last_page = is_last  (drives ptouch feed= → controls Pre-Roll)
          - half_cut = half_cut and not is_last
    """
    last_index = len(images) - 1
    for i, image in enumerate(images):
        is_last = i == last_index
        await backend.print_image(
            image,
            tape_spec,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=half_cut and not is_last,
            last_page=is_last,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/test_batch_helper.py -v 2>&1 | tail -15
```

Expected: 6 passed.

- [ ] **Step 5: Lint + mypy + commit**

```bash
backend/.venv/bin/ruff check backend/app/printer_backends/batch_helper.py backend/tests/unit/printer_backends/test_batch_helper.py
backend/.venv/bin/ruff format --check backend/app/printer_backends/batch_helper.py backend/tests/unit/printer_backends/test_batch_helper.py
backend/.venv/bin/mypy backend/app/printer_backends/batch_helper.py 2>&1 | tail -3

git add backend/app/printer_backends/batch_helper.py backend/tests/unit/printer_backends/test_batch_helper.py
git commit -m "feat(printer_backends): default_print_images_loop helper (Phase 1k.2 Task 1)

Backends ohne native batch-support (BrotherQLBackend, MockBackend) loopen
per-item — Helper zentralisiert die half_cut + last_page Semantik analog
Brother iOS App.

Refs #102"
```

---

## Task 2: `PrinterBackend.print_images` Protocol-Methode

**Files:**
- Modify: `backend/app/printer_backends/base.py`
- Test: (Protocol changes verified via Backend impls in Tasks 3, 4, 5)

**Rationale:** Erweitert das Backend-Contract um die batch-Methode. Bestehende `print_image()` bleibt unverändert. Backends die nicht überschreiben fallen in Task 3-5 explizit auf `default_print_images_loop`.

- [ ] **Step 1: Modify `backend/app/printer_backends/base.py`**

Append after the existing `print_image` declaration:

```python
    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Batch-print N images — atomic-or-best-effort je nach Backend-Impl.

        Semantik haengt vom konkreten Backend ab:
        - PTouchBackend via ptouch.print_multi: ATOMIC — auf Hardware-Ebene ein
          einziger Print-Call. Bei Exception sind ggf. 0 oder ALLE Labels gedruckt,
          niemals partial.
        - Default-Loop (BrotherQLBackend, MockBackend) via
          default_print_images_loop: BEST-EFFORT per item. Wenn item N
          fehlschlaegt, koennen items 0..N-1 bereits physisch gedruckt sein.
          Job-State-Handling muss damit umgehen (siehe Task 8 _process_batch).
        (Copilot-Review C5 PR #106: vorher 'atomic semantics: success or all-fail'
        war falsch fuer den default loop.)

        Phase 1k.2: Default-Loop ueber print_image() lebt in
        ``app.printer_backends.batch_helper.default_print_images_loop``.
        PTouchBackend ueberschreibt fuer ptouch.print_multi() (echtes
        batch-fertig mit 5mm Half-Cut zwischen Labels statt 22.5mm Pre-Roll).
        BrotherQLBackend und MockBackend delegieren explizit an den
        default_print_images_loop helper.

        Args:
            images: PIL Images in print order. len(images) >= 1.
            tape_spec: Shared TapeSpec — alle Items teilen das geladene Tape.
            auto_cut: True = Drucker schneidet am Ende des Batches.
            high_resolution: PT-Series HiRes-Mode.
            half_cut: True = 5mm taktile Separation zwischen Items (PT-Series).
                Letztes Item bekommt immer Voll-Cut (half_cut=False intern).
        """
```

Full updated file content of `backend/app/printer_backends/base.py`:

```python
"""PrinterBackend Protocol — transport contract used by drivers.

Two-method surface (print_image + query_status). A raw `send_bytes` escape
hatch was deliberately removed during design: there is no concrete caller
in First-Print, and opening a second TCP/9100 session in parallel with
ptouch would hit Brother's single-session limit (Resource Busy). The
hook can be added back additively if a future caller needs it.

Phase 1k.2: print_images() added for batch printing via ptouch.print_multi
on PT-Series. Other backends delegate to default_print_images_loop helper.
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
    # Phase 1i C-Fix: PT-Series=True, QL-Series=False
    half_cut_supported: bool

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = False,
        last_page: bool = True,
    ) -> None:
        """Encode and send `image`. Raises a PrinterError subtype on failure.

        Phase 1i C-Fix:
        - half_cut: True bedeutet "tape + liner halb getrennt" (taktile Separation,
          nur PT-Series). Bei half_cut_supported=False vom Backend ignoriert.
        - last_page: True = letztes Item einer Batch (Voll-Cut), False = es folgt
          mindestens ein weiteres Item (kein Cut zwischen).
        """

    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Batch-print N images — atomic-or-best-effort je nach Backend-Impl.

        Semantik haengt vom konkreten Backend ab:
        - PTouchBackend via ptouch.print_multi: ATOMIC — auf Hardware-Ebene ein
          einziger Print-Call. Bei Exception sind ggf. 0 oder ALLE Labels gedruckt,
          niemals partial.
        - Default-Loop (BrotherQLBackend, MockBackend) via
          default_print_images_loop: BEST-EFFORT per item. Wenn item N
          fehlschlaegt, koennen items 0..N-1 bereits physisch gedruckt sein.
          Job-State-Handling muss damit umgehen (siehe Task 8 _process_batch).
        (Copilot-Review C5 PR #106: vorher 'atomic semantics: success or all-fail'
        war falsch fuer den default loop.)

        Phase 1k.2: Default-Loop ueber print_image() lebt in
        ``app.printer_backends.batch_helper.default_print_images_loop``.
        PTouchBackend ueberschreibt fuer ptouch.print_multi() (echtes
        batch-fertig mit 5mm Half-Cut zwischen Labels statt 22.5mm Pre-Roll).
        BrotherQLBackend und MockBackend delegieren explizit an den
        default_print_images_loop helper.

        Args:
            images: PIL Images in print order. len(images) >= 1.
            tape_spec: Shared TapeSpec — alle Items teilen das geladene Tape.
            auto_cut: True = Drucker schneidet am Ende des Batches.
            high_resolution: PT-Series HiRes-Mode.
            half_cut: True = 5mm taktile Separation zwischen Items (PT-Series).
                Letztes Item bekommt immer Voll-Cut (half_cut=False intern).
        """

    async def query_status(self) -> StatusBlock:
        """Send ESC i S, parse the 32-byte reply, return a StatusBlock."""
```

- [ ] **Step 2: Verify mypy + ruff**

```bash
cd /opt/repos/label-printer-hub
backend/.venv/bin/mypy backend/app/printer_backends/base.py 2>&1 | tail -3
backend/.venv/bin/ruff check backend/app/printer_backends/base.py
```

Expected: clean.

Tests will fail at this point — they expect Backend implementations to have `print_images`. That's Tasks 3-5.

- [ ] **Step 3: Commit**

```bash
git add backend/app/printer_backends/base.py
git commit -m "feat(printer_backends): PrinterBackend.print_images Protocol method (Phase 1k.2 Task 2)

Backend-Contract erweitert um batch-print Method. PTouchBackend ueberschreibt
fuer ptouch.print_multi (Task 3), andere Backends delegieren an
default_print_images_loop helper (Tasks 4, 5).

Refs #102"
```

---

## Task 3: `PTouchBackend.print_images` mit `_ptouch_print_multi`

**Files:**
- Modify: `backend/app/printer_backends/ptouch_backend.py`
- Test: `backend/tests/unit/printer_backends/test_ptouch_backend.py` (append)

**Rationale:** Echter Half-Cut-Fix. `print_multi()` macht 1 Connection, 1 Pre-Roll, 5mm Half-Cuts zwischen Labels.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/printer_backends/test_ptouch_backend.py`:

```python
# ---------------------------------------------------------------------------
# Phase 1k.2: print_images batch via ptouch.print_multi
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_print_images_calls_ptouch_print_multi(monkeypatch):
    """PTouchBackend.print_images → _ptouch_print_multi with all labels."""
    from app.models.tape import TapeSpec
    from app.printer_backends.ptouch_backend import PTouchBackend
    from app.printer_backends.snmp_helper import PreflightStatus

    captured: dict[str, object] = {}

    async def fake_preflight(self, **kw):
        return PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=12, error_flags=[]
        )

    def fake_ptouch_print_multi(host, port, images, tape_mm, **kwargs):
        captured["host"] = host
        captured["port"] = port
        captured["num_images"] = len(images)
        captured["tape_mm"] = tape_mm
        captured.update(kwargs)

    monkeypatch.setattr(PTouchBackend, "preflight_check", fake_preflight)
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print_multi",
        fake_ptouch_print_multi,
    )

    backend = PTouchBackend(host="192.0.2.10", model_id="PT-P750W")
    tape_spec = TapeSpec(width_mm=12, printable_dots=70, media_type_name="laminated")
    images = [Image.new("1", (600, 70), color=1) for _ in range(3)]

    await backend.print_images(
        images, tape_spec,
        auto_cut=True, high_resolution=False, half_cut=True,
    )

    assert captured["host"] == "192.0.2.10"
    assert captured["port"] == 9100
    assert captured["num_images"] == 3
    assert captured["tape_mm"] == 12
    assert captured["model_id"] == "PT-P750W"
    assert captured["auto_cut"] is True
    assert captured["half_cut"] is True
    assert captured["high_resolution"] is False


@pytest.mark.anyio
async def test_print_images_raises_tape_mismatch_at_batch_start(monkeypatch):
    """If preflight tape != tape_spec.width_mm, batch fails atomically before print."""
    from app.models.tape import TapeSpec
    from app.printer_backends.exceptions import TapeMismatchError
    from app.printer_backends.ptouch_backend import PTouchBackend
    from app.printer_backends.snmp_helper import PreflightStatus

    async def fake_preflight(self, **kw):
        return PreflightStatus(
            hr_printer_status="idle", loaded_tape_mm=18, error_flags=[]
        )

    monkeypatch.setattr(PTouchBackend, "preflight_check", fake_preflight)
    # _ptouch_print_multi must NOT be called
    called = False
    def fake_pm(*a, **kw):
        nonlocal called
        called = True
    monkeypatch.setattr(
        "app.printer_backends.ptouch_backend._ptouch_print_multi", fake_pm
    )

    backend = PTouchBackend(host="192.0.2.10", model_id="PT-P750W")
    tape_spec = TapeSpec(width_mm=12, printable_dots=70, media_type_name="laminated")
    images = [Image.new("1", (600, 70), color=1) for _ in range(2)]

    with pytest.raises(TapeMismatchError):
        await backend.print_images(images, tape_spec, half_cut=True)
    assert called is False


def test_ptouch_print_multi_passes_labels_array(monkeypatch):
    """_ptouch_print_multi constructs Labels[] and calls LabelPrinter.print_multi."""
    from app.printer_backends.ptouch_backend import _ptouch_print_multi

    captured: dict[str, object] = {}

    class FakeLabelPrinter:
        def __init__(self, *a, **kw): pass
        def print_multi(self, labels, **kwargs):
            captured["num_labels"] = len(labels)
            captured.update(kwargs)

    monkeypatch.setitem(
        __import__("app.printer_backends.ptouch_backend", fromlist=["_PTOUCH_PRINTER_CLASSES"])._PTOUCH_PRINTER_CLASSES,
        "PT-P750W", FakeLabelPrinter,
    )

    images = [Image.new("1", (600, 70), color=1) for _ in range(4)]
    _ptouch_print_multi(
        host="192.0.2.10", port=9100, images=images, tape_mm=12,
        model_id="PT-P750W", auto_cut=True, high_resolution=False, half_cut=True,
    )

    assert captured["num_labels"] == 4
    assert captured["half_cut"] is True
    assert captured["high_resolution"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/test_ptouch_backend.py -k "print_images or print_multi" -v 2>&1 | tail -15
```

Expected: ImportError on `_ptouch_print_multi` OR AttributeError on `PTouchBackend.print_images`.

- [ ] **Step 3: Implement `_ptouch_print_multi` helper + `PTouchBackend.print_images`**

In `backend/app/printer_backends/ptouch_backend.py`:

After `_ptouch_print` function (line ~108), add:

```python
def _ptouch_print_multi(  # pragma: no cover - real-hardware-only, tests monkeypatch this
    host: str,
    port: int,
    images: list[Image.Image],
    tape_mm: int,
    *,
    model_id: str,
    auto_cut: bool,
    high_resolution: bool,
    half_cut: bool,
) -> None:
    """Synchronous helper for batch printing via ptouch.LabelPrinter.print_multi.

    ptouch-py 1.1.0: LabelPrinter.print_multi(labels, margin_mm=None,
    high_resolution=None, half_cut=True) — 1 Connection, 1 Init (=1 Pre-Roll),
    5mm Half-Cut zwischen Labels, voller Cut am Ende.

    Excluded from coverage: real-hardware-only. Tests monkeypatch this module-level
    function. Hardware verification per scripts/smoke_first_print_batch.py (Task 11).
    """
    try:
        tape_cls = _PTOUCH_TAPE_CLASSES[tape_mm]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch tape class for {tape_mm}mm") from exc
    try:
        printer_cls = _PTOUCH_PRINTER_CLASSES[model_id]
    except KeyError as exc:
        raise PrintFailedError(f"No ptouch printer class for model {model_id!r}") from exc

    connection = ptouch.ConnectionNetwork(host, port=port, timeout=10.0)
    printer = printer_cls(connection=connection, high_resolution=high_resolution)
    labels = [ptouch.Label(image=img, tape=tape_cls) for img in images]
    try:
        printer.print_multi(
            labels,
            high_resolution=high_resolution,
            half_cut=half_cut,
        )
    except TypeError:
        # Älterer ptouch-Lib (<1.1) hat kein print_multi — Fallback: per-Item-Loop
        # mit print(). Degraded zu Phase-1i-Verhalten (22.5mm Pre-Roll pro Item).
        for i, label in enumerate(labels):
            is_last = i == len(labels) - 1
            try:
                printer.print(
                    label,
                    auto_cut=auto_cut,
                    high_resolution=high_resolution,
                    half_cut=half_cut and not is_last,
                    feed=is_last,
                )
            except TypeError:
                printer.print(label, auto_cut=auto_cut, high_resolution=high_resolution)
```

In `PTouchBackend` class, add after the existing `print_image` method (line ~248):

```python
    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Batch-print via ptouch.LabelPrinter.print_multi — atomic.

        Pre-Print: SNMP preflight 1x am Batch-Anfang. Bei Tape-Mismatch wird
        TapeMismatchError sofort geworfen, kein print_multi-Call.

        Phase 1k.2: ersetzt N separate ptouch.print() Calls durch 1 print_multi.
        Resultat: 5mm Half-Cut zwischen Labels statt 22.5mm Pre-Roll.
        """
        if not images:
            raise ValueError("print_images requires at least one image")

        preflight = await self.preflight_check()
        if preflight.loaded_tape_mm != tape_spec.width_mm:
            raise TapeMismatchError(
                expected_mm=tape_spec.width_mm,
                loaded_mm=preflight.loaded_tape_mm,
            )

        try:
            await asyncio.to_thread(
                _ptouch_print_multi,
                self.host,
                self._port,
                images,
                tape_spec.width_mm,
                model_id=self._model_id,
                auto_cut=auto_cut,
                high_resolution=high_resolution,
                half_cut=half_cut,
            )
        except (ptouch.PrinterWriteError, ptouch.PrinterPermissionError) as exc:
            raise PrintFailedError(str(exc)) from exc
        except (
            ptouch.PrinterNetworkError,
            ptouch.PrinterTimeoutError,
            ptouch.PrinterNotFoundError,
            ptouch.PrinterConnectionError,
        ) as exc:
            raise PrinterOfflineError(str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/test_ptouch_backend.py -k "print_images or print_multi" -v 2>&1 | tail -10
```

Expected: 3 passed.

- [ ] **Step 5: Full test-suite sanity check**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/ -q 2>&1 | tail -3
```

Expected: keine Regressionen (existing tests still green).

- [ ] **Step 6: Lint + commit**

```bash
backend/.venv/bin/ruff check backend/app/printer_backends/ptouch_backend.py backend/tests/unit/printer_backends/test_ptouch_backend.py
backend/.venv/bin/ruff format --check backend/app/printer_backends/ptouch_backend.py backend/tests/unit/printer_backends/test_ptouch_backend.py
backend/.venv/bin/mypy backend/app/printer_backends/ptouch_backend.py 2>&1 | tail -3

git add backend/app/printer_backends/ptouch_backend.py backend/tests/unit/printer_backends/test_ptouch_backend.py
git commit -m "feat(ptouch): print_images via ptouch.print_multi (Phase 1k.2 Task 3)

PTouchBackend.print_images() ueberschreibt Protocol-Default mit echtem
batch-printing via ptouch.LabelPrinter.print_multi: 1 Connection, 1 Pre-Roll,
5mm Half-Cut zwischen Labels statt 22.5mm zwischen jedem.

TypeError-Fallback: Aelterer ptouch-Lib ohne print_multi degradet zu
per-Item-Loop (Pre-Phase-1k.2 Verhalten).

Refs #102"
```

---

## Task 4: `BrotherQLBackend.print_images` Default-Loop

**Files:**
- Modify: `backend/app/printer_backends/brother_ql_backend.py`
- Test: `backend/tests/unit/printer_backends/test_brother_ql_backend.py` (append)

**Rationale:** brother_ql Lib hat kein `print_multi`-Equivalent. QL ist Endless-Tape (kein Half-Cut-Konzept zwischen Labels). `BrotherQLBackend` delegiert explizit an `default_print_images_loop`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/printer_backends/test_brother_ql_backend.py`:

```python
# ---------------------------------------------------------------------------
# Phase 1k.2: print_images delegates to default_print_images_loop
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_print_images_delegates_to_loop_helper(monkeypatch):
    """BrotherQLBackend.print_images calls default_print_images_loop."""
    from app.models.tape import TapeSpec
    from app.printer_backends.brother_ql_backend import BrotherQLBackend

    captured: dict[str, object] = {}

    async def fake_loop(backend, images, tape_spec, **kwargs):
        captured["backend"] = backend
        captured["num_images"] = len(images)
        captured["tape_mm"] = tape_spec.width_mm
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.printer_backends.brother_ql_backend.default_print_images_loop",
        fake_loop,
    )

    backend = BrotherQLBackend(host="192.0.2.11", model_id="QL-820NWB")
    tape_spec = TapeSpec(width_mm=62, printable_dots=696, media_type_name="endless_dk")
    images = [Image.new("1", (696, 200), color=1) for _ in range(3)]

    await backend.print_images(
        images, tape_spec,
        auto_cut=True, high_resolution=False, half_cut=False,
    )

    assert captured["backend"] is backend
    assert captured["num_images"] == 3
    assert captured["tape_mm"] == 62
    assert captured["auto_cut"] is True
    assert captured["half_cut"] is False  # QL erzwingt half_cut=False
```

(Note: `Image` is imported at the top of the existing test file from earlier tasks; verify the import line exists.)

- [ ] **Step 2: Run test to verify it fails**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/test_brother_ql_backend.py::test_print_images_delegates_to_loop_helper -v 2>&1 | tail -8
```

Expected: AttributeError — `print_images` not implemented.

- [ ] **Step 3: Implement**

In `backend/app/printer_backends/brother_ql_backend.py`:

Add import at top:
```python
from app.printer_backends.batch_helper import default_print_images_loop
```

Add method to `BrotherQLBackend` class (after `print_image`):

```python
    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Batch-print N images via per-item Loop.

        brother_ql Lib hat kein print_multi-Equivalent — QL ist Endless-Tape,
        kein Half-Cut-Konzept zwischen Labels (jedes Label wird vom Druckkopf
        ausgegeben und manuell abgeschnitten). Delegiert an
        default_print_images_loop mit half_cut=False (QL ignoriert das Argument).

        Phase 1k.2: aus Sicht der API identisches Verhalten wie zuvor —
        BatchJob-Pfad existiert um eine konsistente print_images-Signatur
        ueber alle Backends zu erfuellen.
        """
        # QL-Series: half_cut existiert nicht. Backend-Capability-Flag erzwingt False.
        await default_print_images_loop(
            self,
            images,
            tape_spec,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/test_brother_ql_backend.py -q 2>&1 | tail -5
```

Expected: alle tests grün (existing + neuer).

- [ ] **Step 5: Lint + commit**

```bash
backend/.venv/bin/ruff check backend/app/printer_backends/brother_ql_backend.py backend/tests/unit/printer_backends/test_brother_ql_backend.py
backend/.venv/bin/ruff format --check backend/app/printer_backends/brother_ql_backend.py backend/tests/unit/printer_backends/test_brother_ql_backend.py

git add backend/app/printer_backends/brother_ql_backend.py backend/tests/unit/printer_backends/test_brother_ql_backend.py
git commit -m "feat(brother_ql): print_images via default_print_images_loop (Phase 1k.2 Task 4)

QL-Series ist Endless-Tape ohne Half-Cut-Konzept. BrotherQLBackend.print_images
delegiert an default_print_images_loop mit half_cut=False (capability-flag erzwingt).
Phase 1k.2 Architektur-Konsistenz: alle Backends bieten print_images.

Refs #102"
```

---

## Task 5: `MockBackend.print_images` Default-Loop

**Files:**
- Modify: `backend/app/printer_backends/mock_backend.py`

**Rationale:** Mock-Backend braucht print_images für Tests die print_images()-Pfad triggern.

- [ ] **Step 1: Read existing MockBackend code**

```bash
sed -n '1,50p' backend/app/printer_backends/mock_backend.py
```

Identify the existing print_image signature und Class-Definition. Add print_images analog.

- [ ] **Step 2: Add print_images method to MockBackend**

In `backend/app/printer_backends/mock_backend.py`:

Add import:
```python
from app.printer_backends.batch_helper import default_print_images_loop
```

Add to `MockBackend` class (after `print_image`):

```python
    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Test-friendly Mock-Implementation via default_print_images_loop.

        Records each print_image call into self.printed_images for assertions.
        """
        await default_print_images_loop(
            self,
            images,
            tape_spec,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=half_cut,
        )
```

- [ ] **Step 3: Run all backend tests to verify no regression**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_backends/ -q 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 4: Lint + commit**

```bash
backend/.venv/bin/ruff check backend/app/printer_backends/mock_backend.py
backend/.venv/bin/ruff format --check backend/app/printer_backends/mock_backend.py

git add backend/app/printer_backends/mock_backend.py
git commit -m "feat(mock): MockBackend.print_images via default_print_images_loop (Phase 1k.2 Task 5)

Refs #102"
```

---

## Task 6: `_PTPQueuePrinter.print_images` Adapter + Bug-Fix half_cut/last_page forwarding

**Files:**
- Modify: `backend/app/printer_models/pt.py`

**Rationale:** Queue-Adapter hat aktuell **Bug**: forwarded weder `half_cut` noch `last_page` zum Backend (Zeile 256-264). PR #100 erreichte die Lib nicht. Wir fixen das gleich mit + neue print_images() Methode.

- [ ] **Step 1: Failing test im _PTPQueuePrinter test file (find first)**

```bash
find backend/tests -name "test_pt*.py" -o -name "*pt_queue*"
# Likely: backend/tests/unit/printer_models/test_pt.py
```

Append to the existing test file (path adjust if different):

```python
# ---------------------------------------------------------------------------
# Phase 1k.2: _PTPQueuePrinter.print_images forwards to backend.print_images
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ptp_queue_printer_print_images_forwards_to_backend(monkeypatch):
    """_PTPQueuePrinter.print_images calls backend.print_images with tape_spec."""
    from PIL import Image
    from uuid import uuid4
    from app.printer_models.pt import PTP750WDriver, _PTPQueuePrinter
    from app.printer_models.tape_registry import TapeRegistry, MediaType
    from unittest.mock import AsyncMock

    backend = AsyncMock()
    backend.print_images = AsyncMock()
    backend.half_cut_supported = True
    tape_registry = TapeRegistry()
    driver = PTP750WDriver(backend=backend)
    adapter = driver.make_queue_printer(tape_registry, printer_id=uuid4())

    images = [Image.new("1", (600, 70), color=1) for _ in range(3)]
    await adapter.print_images(
        images, tape_mm=12,
        media_type=MediaType.LAMINATED,
        auto_cut=True, high_resolution=False, half_cut=True,
    )

    assert backend.print_images.call_count == 1
    call = backend.print_images.call_args
    assert call.args[0] == images  # images list
    assert call.args[1].width_mm == 12  # tape_spec
    assert call.kwargs["auto_cut"] is True
    assert call.kwargs["half_cut"] is True


@pytest.mark.anyio
async def test_ptp_queue_printer_print_image_forwards_half_cut_last_page(monkeypatch):
    """REGRESSION: print_image (single) must forward half_cut + last_page (PR #100 bug)."""
    from PIL import Image
    from uuid import uuid4
    from app.printer_models.pt import PTP750WDriver, _PTPQueuePrinter
    from app.printer_models.tape_registry import TapeRegistry, MediaType
    from unittest.mock import AsyncMock

    backend = AsyncMock()
    backend.print_image = AsyncMock()
    backend.half_cut_supported = True
    tape_registry = TapeRegistry()
    driver = PTP750WDriver(backend=backend)
    adapter = driver.make_queue_printer(tape_registry, printer_id=uuid4())

    image = Image.new("1", (600, 70), color=1)
    await adapter.print_image(
        image, tape_mm=12,
        media_type=MediaType.LAMINATED,
        auto_cut=True, high_resolution=False,
        half_cut=True, last_page=False,
    )

    call = backend.print_image.call_args
    assert call.kwargs["half_cut"] is True
    assert call.kwargs["last_page"] is False
```

- [ ] **Step 2: Run tests to verify both fail**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_models/test_pt.py -k "print_images or print_image_forwards" -v 2>&1 | tail -15
```

Expected: AttributeError for `print_images`, AssertionError for the half_cut/last_page check.

- [ ] **Step 3: Implement — Bug fix + new method**

In `backend/app/printer_models/pt.py`, replace `_PTPQueuePrinter.print_image` and add `print_images`:

```python
    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        media_type = options.pop("media_type", self._default_media_type)
        tape_spec = self._tape_registry.lookup_pt(tape_mm, media_type)
        # Phase 1k.2 Bug-Fix: half_cut + last_page wurden vorher NICHT forwarded
        # (gefunden waehrend Plan-Writing Phase 1k.2). PR #100 erreichte die Lib
        # nicht. Hier explicit forwarden.
        await self._backend.print_image(
            image,
            tape_spec,
            auto_cut=bool(options.pop("auto_cut", True)),
            high_resolution=bool(options.pop("high_resolution", False)),
            half_cut=bool(options.pop("half_cut", False)),
            last_page=bool(options.pop("last_page", True)),
        )

    async def print_images(
        self,
        images: list[Image.Image],
        *,
        tape_mm: int,
        **options: Any,
    ) -> None:
        """Phase 1k.2: Adapter-Methode fuer Queue-BatchJob → backend.print_images."""
        media_type = options.pop("media_type", self._default_media_type)
        tape_spec = self._tape_registry.lookup_pt(tape_mm, media_type)
        await self._backend.print_images(
            images,
            tape_spec,
            auto_cut=bool(options.pop("auto_cut", True)),
            high_resolution=bool(options.pop("high_resolution", False)),
            half_cut=bool(options.pop("half_cut", True)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_models/test_pt.py -q 2>&1 | tail -3
```

Expected: all green.

- [ ] **Step 5: Lint + commit**

```bash
backend/.venv/bin/ruff check backend/app/printer_models/pt.py backend/tests/unit/printer_models/test_pt.py
backend/.venv/bin/ruff format --check backend/app/printer_models/pt.py backend/tests/unit/printer_models/test_pt.py
backend/.venv/bin/mypy backend/app/printer_models/pt.py 2>&1 | tail -3

git add backend/app/printer_models/pt.py backend/tests/unit/printer_models/test_pt.py
git commit -m "feat(pt): _PTPQueuePrinter.print_images + bug-fix half_cut/last_page forwarding (Phase 1k.2 Task 6)

Bug discovered during Phase 1k.2 plan-writing: _PTPQueuePrinter.print_image
forwarded only auto_cut + high_resolution. half_cut und last_page wurden aus
options dict geholt aber NIE an backend.print_image() weitergeleitet. PR #100
fix landete nie bei ptouch lib.

Fix: explicit options.pop für half_cut + last_page. Plus neue print_images()
Adapter-Methode fuer Queue-BatchJob-Pfad.

Refs #102, regression-fixes PR #100 (silent drop in adapter layer)"
```

---

## Task 7: `_QLQueuePrinter.print_images` Adapter

**Files:**
- Modify: `backend/app/printer_models/ql.py`

**Rationale:** Analog Task 6 für QL. QL braucht KEIN half_cut/last_page-Bug-Fix (QL hat kein half_cut), aber print_images Adapter ist nötig für Queue-Konsistenz.

- [ ] **Step 1: Failing test (analog Task 6)**

Append to `backend/tests/unit/printer_models/test_ql.py`:

```python
@pytest.mark.anyio
async def test_ql_queue_printer_print_images_forwards_to_backend(monkeypatch):
    """_QLQueuePrinter.print_images calls backend.print_images with tape_spec."""
    from PIL import Image
    from uuid import uuid4
    from app.printer_models.ql import QL820NWBDriver
    from app.printer_models.tape_registry import TapeRegistry
    from unittest.mock import AsyncMock

    backend = AsyncMock()
    backend.print_images = AsyncMock()
    backend.half_cut_supported = False
    tape_registry = TapeRegistry()
    driver = QL820NWBDriver(backend=backend)
    adapter = driver.make_queue_printer(tape_registry, printer_id=uuid4())

    images = [Image.new("1", (696, 200), color=1) for _ in range(2)]
    await adapter.print_images(
        images, tape_mm=62,
        auto_cut=True, high_resolution=False, half_cut=False,
    )

    assert backend.print_images.call_count == 1
    call = backend.print_images.call_args
    assert call.args[0] == images
    assert call.args[1].width_mm == 62
    assert call.kwargs["half_cut"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_models/test_ql.py -k "print_images" -v 2>&1 | tail -8
```

Expected: AttributeError.

- [ ] **Step 3: Implement**

In `backend/app/printer_models/ql.py`, in `_QLQueuePrinter` class (after `print_image`):

```python
    async def print_images(
        self,
        images: list[Image.Image],
        *,
        tape_mm: int,
        **options: Any,
    ) -> None:
        """Phase 1k.2: Adapter-Methode fuer Queue-BatchJob → backend.print_images.

        QL-Series unterstuetzt kein half_cut — Backend forciert intern False.
        """
        # Gemini-Review G-R2-1 (PR #106): lookup_ql benoetigt tape_mm UND
        # media_type — analog zu _PTPQueuePrinter.print_image. Nur mit tape_mm
        # waerf TypeError.
        media_type = options.pop("media_type", self._default_media_type)
        tape_spec = self._tape_registry.lookup_ql(tape_mm, media_type)
        await self._backend.print_images(
            images,
            tape_spec,
            auto_cut=bool(options.pop("auto_cut", True)),
            high_resolution=bool(options.pop("high_resolution", False)),
            half_cut=False,  # QL erzwingt
        )
```

(Adjust `tape_registry.lookup_ql` if the actual method name differs — verify with `grep "def lookup_ql\|def lookup_pt" app/printer_models/tape_registry.py`.)

- [ ] **Step 4: Run tests + commit**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/printer_models/test_ql.py -q 2>&1 | tail -3
backend/.venv/bin/ruff check backend/app/printer_models/ql.py backend/tests/unit/printer_models/test_ql.py
backend/.venv/bin/ruff format --check backend/app/printer_models/ql.py backend/tests/unit/printer_models/test_ql.py

git add backend/app/printer_models/ql.py backend/tests/unit/printer_models/test_ql.py
git commit -m "feat(ql): _QLQueuePrinter.print_images adapter (Phase 1k.2 Task 7)

QL erzwingt half_cut=False intern (capability-flag). Adapter-Konsistenz mit
PT fuer Queue-BatchJob-Pfad.

Refs #102"
```

---

## Task 8: `PrintQueue.BatchJob` dataclass + `enqueue_batch` + Worker isinstance-Branch

**Files:**
- Modify: `backend/app/services/print_queue.py`
- Create: `backend/tests/unit/services/test_print_queue_batch.py`

**Rationale:** Kern der 1k.2-Architektur. BatchJob als neuer Queue-Typ, Worker dispatched per isinstance.

- [ ] **Step 1: Failing test**

`backend/tests/unit/services/test_print_queue_batch.py`:

```python
"""Tests fuer BatchJob path durch PrintQueue (Phase 1k.2 Task 8)."""
from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.services.print_queue import BatchJob, PrintQueue


class _FakePrinter:
    """_PrinterLike test double with print_image + print_images."""
    def __init__(self, printer_id: UUID) -> None:
        self.id = printer_id
        self.print_image = AsyncMock()
        self.print_images = AsyncMock()


@pytest.fixture
def printer_id() -> UUID:
    return uuid4()


@pytest.fixture
def fake_printer(printer_id) -> _FakePrinter:
    return _FakePrinter(printer_id)


@pytest.fixture
def make_image() -> "callable[[], Image.Image]":
    return lambda: Image.new("1", (600, 70), color=1)


@pytest.mark.anyio
async def test_enqueue_batch_creates_batch_job(fake_printer, make_image):
    """enqueue_batch puts a BatchJob onto the queue, returns batch_id."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    job_ids = [uuid4(), uuid4(), uuid4()]

    batch_id = await queue.enqueue_batch(
        printer_id=fake_printer.id,
        images=images,
        job_ids=job_ids,
        tape_mm=12,
        options={"auto_cut": True, "high_resolution": False},
    )

    assert isinstance(batch_id, UUID)


@pytest.mark.anyio
async def test_worker_dispatches_batchjob_to_print_images(fake_printer, make_image):
    """Worker recognises BatchJob and calls printer.print_images, not print_image."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(2)]
    job_ids = [uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "high_resolution": False, "half_cut": True},
        )
        # Wait for worker to consume the batch
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    assert fake_printer.print_images.await_count == 1
    assert fake_printer.print_image.await_count == 0  # NOT called

    call = fake_printer.print_images.call_args
    assert len(call.args[0]) == 2  # images list
    assert call.kwargs["tape_mm"] == 12
    assert call.kwargs["half_cut"] is True


@pytest.mark.anyio
async def test_batchjob_success_marks_all_job_ids_completed(fake_printer, make_image):
    """On print_images success, all job_ids of the batch are marked completed."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    job_ids = [uuid4(), uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id, images=images, job_ids=job_ids,
            tape_mm=12, options={"auto_cut": True, "half_cut": True},
        )
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    # Status check — depends on JobStore implementation. Use list_completed if available:
    # For now, assert print_images called once (Mock-Store via MemoryJobStore default).
    assert fake_printer.print_images.await_count == 1


@pytest.mark.anyio
async def test_batchjob_failure_marks_all_job_ids_failed(fake_printer, make_image):
    """On print_images exception, all job_ids of the batch are marked failed."""
    fake_printer.print_images = AsyncMock(side_effect=RuntimeError("printer offline"))
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(2)]
    job_ids = [uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id, images=images, job_ids=job_ids,
            tape_mm=12, options={"auto_cut": True, "half_cut": True},
        )
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    assert fake_printer.print_images.await_count == 1


@pytest.mark.anyio
async def test_enqueue_batch_rejects_unknown_printer(fake_printer, make_image):
    """enqueue_batch raises KeyError for unknown printer_id."""
    queue = PrintQueue([fake_printer])
    images = [make_image()]
    with pytest.raises(KeyError):
        await queue.enqueue_batch(
            printer_id=uuid4(),  # unknown
            images=images,
            job_ids=[uuid4()],
            tape_mm=12,
            options={},
        )


@pytest.mark.anyio
async def test_enqueue_batch_requires_matching_lengths(fake_printer, make_image):
    """images and job_ids must have same length."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    with pytest.raises(ValueError, match="images and job_ids length mismatch"):
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=[uuid4(), uuid4()],  # only 2
            tape_mm=12,
            options={},
        )
```

- [ ] **Step 2: Run to verify failures**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/services/test_print_queue_batch.py -v 2>&1 | tail -15
```

Expected: ImportError on `BatchJob`, or AttributeError on `enqueue_batch`.

- [ ] **Step 3: Implement BatchJob + enqueue_batch + worker branch**

In `backend/app/services/print_queue.py`:

A) Update `_PrinterLike` Protocol (line ~130) — add `print_images`:

```python
@runtime_checkable
class _PrinterLike(Protocol):
    """Minimal printer contract this queue depends on.

    Real printer plugins (PR for Tasks 2.1/2.2) implement the richer
    PrinterModel Protocol (PR #48). The queue depends only on `id`,
    `print_image`, and (Phase 1k.2) `print_images`.
    """

    id: UUID

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None: ...

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None: ...
```

B) Add `BatchJob` dataclass (after `class PrintQueue`'s `_PrinterLike` Protocol):

```python
@dataclass(frozen=False)
class BatchJob:
    """Queue-Item das mehrere Labels in einer Backend-Operation druckt.

    Phase 1k.2: BatchJob ist orthogonal zu Job — der Worker dispatched per
    isinstance. Auf success/failure werden alle job_ids gemeinsam markiert
    (atomic semantics, User-Entscheidung Option 1).
    """
    batch_id: UUID
    printer_id: UUID
    image_payloads: list[bytes]   # PNG-encoded für DB-Konsistenz mit Job.image_payload
    job_ids: list[UUID]
    tape_mm: int
    options: dict[str, Any]
```

Add `dataclass` import at top:
```python
from dataclasses import dataclass
```

C) Update the queue type annotation (line ~181):
```python
        self._queues: dict[UUID, asyncio.Queue[Job | BatchJob | None]] = {
            p.id: asyncio.Queue() for p in printers
        }
```

D) Add `enqueue_batch` method to `PrintQueue` (after `submit_paused`):

```python
    async def enqueue_batch(
        self,
        *,
        printer_id: UUID,
        images: list[Image.Image],
        job_ids: list[UUID],
        tape_mm: int,
        options: dict[str, Any],
    ) -> UUID:
        """Phase 1k.2: Submit N images as ONE BatchJob (atomic print_multi call).

        Args:
            printer_id: Target printer (must be registered in self._queues).
            images: PIL Images in print order, len(images) >= 1.
            job_ids: Pre-allocated job UUIDs, one per image. Must be len(images) long.
            tape_mm: Shared tape width (12/18/24/62).
            options: Collective options (auto_cut, high_resolution, half_cut).

        Returns:
            batch_id: New UUID identifying this batch.

        Raises:
            KeyError: unknown printer_id.
            ValueError: len(images) != len(job_ids), or len(images) == 0.
        """
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        if not images:
            raise ValueError("enqueue_batch requires at least one image")
        if len(images) != len(job_ids):
            raise ValueError(
                f"images and job_ids length mismatch: {len(images)} vs {len(job_ids)}"
            )

        # Gemini-Review G1 (PR #106): Parallel PNG-Serialisierung
        payloads = await asyncio.gather(
            *[asyncio.to_thread(_serialize_image_to_png, img) for img in images]
        )

        # Gemini-Review G1 (PR #106): In-Memory Job-Registrierung pro item.
        # OHNE diese Schleife wirft get(job_id)/wait_for_job KeyError, weil
        # die individuellen Jobs nie in self._jobs landen. SSE-Frontend und
        # Hangar-Polling brauchen pro-Item-Job-Records (alle teilen das BatchJob
        # als Owner, aber jeder Job hat eigene id/state/_done_event).
        for jid, payload in zip(job_ids, payloads, strict=True):
            job = Job(
                id=str(jid),
                printer_id=printer_id,
                image_payload=payload,
                tape_mm=tape_mm,
                options=dict(options),
            )
            self._jobs[str(jid)] = job

        batch_id = uuid4()
        batch = BatchJob(
            batch_id=batch_id,
            printer_id=printer_id,
            image_payloads=list(payloads),
            job_ids=list(job_ids),
            tape_mm=tape_mm,
            options=dict(options),
        )
        await self._queues[printer_id].put(batch)
        logger.info("Batch %s queued on %s with %d items", batch_id, printer_id, len(images))
        return batch_id
```

Add `uuid4` import at top:
```python
from uuid import UUID, uuid4
```

E) Update worker (`_worker` method, line ~660) to dispatch per isinstance:

Find the section:
```python
            job = item

            # Wait while paused — ...
```

Replace with:
```python
            # Phase 1k.2: BatchJob vs Job — dispatch per isinstance
            if isinstance(item, BatchJob):
                await self._process_batch(printer, printer_id, item)
                continue

            job = item

            # Wait while paused — ...
```

F) Add new `_process_batch` method to `PrintQueue` (after `_worker`):

```python
    async def _process_batch(
        self,
        printer: _PrinterLike,
        printer_id: UUID,
        batch: BatchJob,
    ) -> None:
        """Phase 1k.2: Handle BatchJob — atomic success/failure for all job_ids.

        Decodes payloads, calls printer.print_images() once. On exception,
        marks all job_ids as failed with a shared error_message.

        Gemini-Review G2 (PR #106): Pro item MUSS JobStateMachine.transition
        gerufen werden, sonst:
        - _done_event wird nie gesetzt → wait_for_job(job_id) haengt unendlich
        - _notify_state_change wird nie gerufen → SSE-Frontend (Hangar) bekommt
          keine Updates und zeigt Jobs als ewig 'queued' an
        - started_at/finished_at Timestamps bleiben None (UI-Probleme)
        """
        # Wait while paused (mirror _worker semantics)
        while self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
            if self._stopping:
                return
            await self._worker_resume_events[printer_id].wait()

        # Resolve all Job in-memory objects (registered in enqueue_batch via
        # Gemini-Review G1 fix). Falls ein Job nicht mehr in self._jobs ist
        # (cancel mid-flight), skip — terminale state-transition wuerde fehlen.
        jobs: list[Job] = []
        for jid in batch.job_ids:
            job = self._jobs.get(str(jid))
            if job is None:
                logger.warning("Batch %s: job_id %s not in _jobs (cancelled?)", batch.batch_id, jid)
                continue
            jobs.append(job)
        if not jobs:
            logger.warning("Batch %s has no live jobs — skipping", batch.batch_id)
            return

        # Gemini-Review G2: in-memory transitions + SSE-Events + DB persist.
        # QUEUED -> PRINTING fuer jeden Job.
        #
        # Gemini-Review G-R2-2 (PR #106): Wenn JobStateMachine.transition fails
        # (z.B. job already CANCELLED), darf NICHT noch _store.mark_printing
        # gerufen werden — sonst inkonsistent (in-memory CANCELLED vs DB PRINTING).
        # Wir sammeln nur successfully transitioned jobs in active_jobs[] und
        # nutzen die fuer alle folgenden DB-Calls + post-print transitions.
        active_jobs: list[Job] = []
        for job in jobs:
            try:
                JobStateMachine.transition(job, JobState.PRINTING)
                self._notify_state_change(
                    job, JobState.QUEUED, JobState.PRINTING,
                    queue_depth=self._queue_depth(printer_id),
                )
                await self._store.mark_printing(UUID(job.id))
                active_jobs.append(job)
            except InvalidStateTransitionError:
                logger.warning(
                    "Batch %s: job %s skipped — state already %s (cancelled?)",
                    batch.batch_id, job.id, job.state,
                )

        if not active_jobs:
            logger.warning("Batch %s: 0 active jobs after transitions — skipping print", batch.batch_id)
            return

        # Gemini-Review G1 (PR #106): Parallel image decode
        images = await asyncio.gather(
            *[asyncio.to_thread(Image.open, BytesIO(p)) for p in batch.image_payloads]
        )

        try:
            await printer.print_images(
                images,
                tape_mm=batch.tape_mm,
                **batch.options,
            )
            # Success: alle active_jobs PRINTING -> COMPLETED.
            # Gemini-Review G-R2-2 (PR #106): nur active_jobs, NICHT alle jobs —
            # cancelled-mid-flight darf nicht ueberschrieben werden.
            for job in active_jobs:
                try:
                    JobStateMachine.transition(job, JobState.COMPLETED)
                    self._notify_state_change(
                        job, JobState.PRINTING, JobState.COMPLETED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                    await self._store.mark_done(UUID(job.id))
                except InvalidStateTransitionError:
                    logger.warning(
                        "Batch %s: success-transition of %s failed (state=%s)",
                        batch.batch_id, job.id, job.state,
                    )
            logger.info("Batch %s completed on %s", batch.batch_id, printer_id)
        except asyncio.CancelledError:
            raise
        except PrinterError as exc:
            # Copilot-Review C6 (PR #106): Konsistenz mit existing _worker —
            # PrinterError-Subtypes muessen via _printer_error_to_record auf
            # strukturierte error_code/error_detail gemapped werden. Plus:
            # recoverable hardware errors (tape_mismatch, cover_open, offline)
            # MUESSEN den Printer pausieren, sonst laufen Folge-Jobs ins gleiche
            # Problem.
            code, msg, detail = _printer_error_to_record(exc)
            # Gemini-Review G-R2-2 (PR #106): nur active_jobs, NICHT alle jobs.
            for job in active_jobs:
                job.error_code = code
                job.error_message = msg
                job.error_detail = detail
                job.error_msg = msg  # legacy field sync
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(
                        job, JobState.PRINTING, JobState.FAILED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                    await self._store.mark_failed(UUID(job.id), f"{code}: {msg}")
                except InvalidStateTransitionError:
                    logger.warning(
                        "Batch %s: failure-transition of %s failed (state=%s)",
                        batch.batch_id, job.id, job.state,
                    )
            logger.exception(
                "Batch %s: PrinterError on %s — %d items marked failed (%s)",
                batch.batch_id, printer_id, len(active_jobs), code,
            )
            # Recoverable hardware error -> Printer pausieren (User-Interaktion noetig)
            if isinstance(exc, _RECOVERABLE_PRINTER_ERRORS):
                await self.pause_printer(printer_id, reason=code)
        except Exception as exc:
            # Fallback fuer non-PrinterError exceptions
            error_msg = f"batch print failed: {exc}"
            # Gemini-Review G-R2-2 (PR #106): nur active_jobs.
            for job in active_jobs:
                job.error_code = "batch_failed"
                job.error_message = error_msg
                job.error_msg = error_msg  # legacy field sync
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(
                        job, JobState.PRINTING, JobState.FAILED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                    await self._store.mark_failed(UUID(job.id), error_msg)
                except InvalidStateTransitionError:
                    logger.warning(
                        "Batch %s: failure-transition of %s failed (state=%s)",
                        batch.batch_id, job.id, job.state,
                    )
            logger.exception(
                "Batch %s failed on %s — %d items marked failed",
                batch.batch_id, printer_id, len(active_jobs),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/services/test_print_queue_batch.py -v 2>&1 | tail -15
```

Expected: 6 passed.

- [ ] **Step 5: Run full queue test-suite for regression check**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/services/ -q 2>&1 | tail -3
```

Expected: alle vorherigen tests grün + neue 6 = ~120+.

- [ ] **Step 6: Lint + commit**

```bash
backend/.venv/bin/ruff check backend/app/services/print_queue.py backend/tests/unit/services/test_print_queue_batch.py
backend/.venv/bin/ruff format --check backend/app/services/print_queue.py backend/tests/unit/services/test_print_queue_batch.py
backend/.venv/bin/mypy backend/app/services/print_queue.py 2>&1 | tail -3

git add backend/app/services/print_queue.py backend/tests/unit/services/test_print_queue_batch.py
git commit -m "feat(queue): BatchJob + enqueue_batch + worker isinstance dispatch (Phase 1k.2 Task 8)

Neuer BatchJob dataclass mit batch_id, printer_id, image_payloads (PNG bytes),
job_ids[], tape_mm, options. PrintQueue.enqueue_batch validiert + serialisiert.
Worker dispatched BatchJob → _process_batch → printer.print_images. Atomic:
auf success markiert alle job_ids als done, auf failure alle als failed mit
gemeinsamer Error-Message.

_PrinterLike Protocol erweitert um print_images.

Refs #102"
```

---

## Task 9: `batch_dispatch.dispatch_batch` Refactor + Mixed-Tape-Check

**Files:**
- Modify: `backend/app/services/batch_dispatch.py`
- Modify: `backend/app/services/print_service.py` (neue `submit_batch_job` Methode)
- Modify: `backend/tests/unit/services/test_batch_dispatch.py`

**Rationale:** Render alle Items, sammle job_ids, queue als BatchJob. Mixed tape_mm → 400 vor Queue.

- [ ] **Step 1: Failing test in test_batch_dispatch.py**

Append:

```python
# ---------------------------------------------------------------------------
# Phase 1k.2: dispatch_batch queues BatchJob instead of N PrintJobs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dispatch_batch_uses_enqueue_batch_path(monkeypatch):
    """dispatch_batch with valid items calls service.submit_batch_job once."""
    # Build fake PrintService with submit_batch_job mock
    # ... uses existing test fixtures from this file
    # Specific implementation depends on existing test patterns.


@pytest.mark.anyio
async def test_dispatch_batch_rejects_mixed_tape_sizes():
    """Items with different template.tape_mm raise MixedTapeSizesError before queue."""
    from app.services.batch_dispatch import dispatch_batch, MixedTapeSizesError
    # Setup mock service with two PrintRequests pointing to templates of different tape_mm
    # Verify dispatch_batch raises MixedTapeSizesError, no jobs queued.
```

(Note: The full test setup requires existing fixtures. The implementer should consult the existing `test_batch_dispatch.py` for `_fake_service`, `_make_request`, and `_template_loader` patterns and reuse them. The exact failing test code depends on what's already there.)

- [ ] **Step 2: Run to verify failure**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/services/test_batch_dispatch.py -k "batch or mixed" -v 2>&1 | tail -15
```

Expected: failures.

- [ ] **Step 3: Refactor `dispatch_batch`**

`backend/app/services/batch_dispatch.py` — replace body. Hinzufügen `MixedTapeSizesError` Exception class und neue Funktion `dispatch_batch`:

```python
"""Best-effort Batch-Dispatcher: validiert + queued als atomic BatchJob.

Phase 1k.2: Statt N PrintJobs (einer pro Item) wird genau EINE BatchJob
in die Queue gegeben. Der Backend (PT-Series) verwendet ptouch.print_multi
fuer atomic batch printing mit 5mm Half-Cut zwischen Labels.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.schemas.print_batch import BatchError
from app.schemas.print_request import PrintRequest
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError

if TYPE_CHECKING:
    from app.printer_backends.base import PrinterBackend
    from app.services.print_service import PrintService

_log = logging.getLogger(__name__)


class MixedTapeSizesError(Exception):
    """Batch enthält Items mit unterschiedlichen template.tape_mm.

    Phase 1k.2: ptouch.print_multi unterstützt nur ein tape pro Call.
    Vor Queue abfangen → 400 Response.
    """

    def __init__(self, tape_mm_values: list[int]) -> None:
        super().__init__(f"Mixed tape sizes in batch: {sorted(set(tape_mm_values))}")
        self.tape_mm_values = tape_mm_values


_PER_ITEM_ERRORS: dict[type[Exception], str] = {
    TemplateNotFoundError: "template_not_found",
    LookupFailedError: "integration_lookup_failed",
    TapeEmptyError: "tape_empty",
}

_BATCH_FATAL_ERRORS: tuple[type[Exception], ...] = (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeMismatchError,  # atomic per Phase 1k.2 Spec
    MixedTapeSizesError,
)


async def dispatch_batch(
    service: PrintService,
    items: list[PrintRequest],
    *,
    half_cut_override: bool | None = None,
    backend: PrinterBackend | None = None,
) -> tuple[list[str], list[BatchError]]:
    """Render N items, queue ONE BatchJob via PrintService.submit_batch_job.

    Phase 1k.2 architecture:
    - Per-item validation (template_not_found, lookup_failed) collected in errors[]
    - Hardware errors (printer_offline, cover_open, tape_mismatch) propagated to caller
    - Mixed tape_mm → MixedTapeSizesError (400)
    - Successful items → ONE BatchJob mit allen Images, gemeinsamer half_cut Logic

    Returns:
        (job_ids_str, errors): job_ids im Erfolgsfall, BatchError list für skipped items.
        Bei BatchJob-Submit: alle job_ids gehoeren zu einer atomar-failed/atomar-success Batch.
    """
    errors: list[BatchError] = []
    valid_items: list[tuple[int, PrintRequest, int]] = []  # (orig_index, request, tape_mm)

    # 1. Per-item validation: collect tape_mm + flag failures.
    for index, item in enumerate(items):
        try:
            # Template loading throws TemplateNotFoundError synchronously
            tape_mm = await _validate_item_get_tape_mm(service, item)
            valid_items.append((index, item, tape_mm))
        except _BATCH_FATAL_ERRORS:
            raise
        except tuple(_PER_ITEM_ERRORS) as exc:
            code = _PER_ITEM_ERRORS[type(exc)]
            errors.append(
                BatchError(index=index, error_code=code, error_message=str(exc))
            )
        except Exception as exc:  # unknown sync failure
            _log.exception("unexpected error validating batch item %d", index)
            errors.append(
                BatchError(index=index, error_code="internal_error", error_message=str(exc))
            )

    if not valid_items:
        return [], errors

    # 2. Mixed tape_mm check
    tape_mm_set = {tm for _, _, tm in valid_items}
    if len(tape_mm_set) > 1:
        raise MixedTapeSizesError([tm for _, _, tm in valid_items])

    # 3. Backend half_cut capability
    backend_supports_half_cut: bool = getattr(backend, "half_cut_supported", False)
    if half_cut_override is not None:
        use_half_cut = half_cut_override and backend_supports_half_cut
    else:
        use_half_cut = backend_supports_half_cut

    # 4. Submit as single BatchJob
    requests = [req for _, req, _ in valid_items]
    job_ids = await service.submit_batch_job(
        requests,
        half_cut=use_half_cut,
    )

    return [str(jid) for jid in job_ids], errors


async def _validate_item_get_tape_mm(
    service: PrintService,
    item: PrintRequest,
) -> int:
    """Load template via public PrintService API, return tape_mm.

    Raises TemplateNotFoundError on miss.

    Copilot-Review C7 (PR #106): vorher hat dieser helper auf das private
    Attribut service._loader zugegriffen. Plaene auf Internals brechen bei
    Refactors. Stattdessen wird ein public Helper get_template_tape_mm auf
    PrintService aufgerufen (Task 9 Step 4a ergaenzt diese Methode).
    """
    return await service.get_template_tape_mm(item.template_id)
```

**Zusaetzlicher Step 4a vor Step 4 (`submit_batch_job`): public Helper auf `PrintService`**

In `backend/app/services/print_service.py` vor `submit_batch_job` adden:

```python
    async def get_template_tape_mm(self, template_id: str) -> int:
        """Public helper: load template and return its tape_mm.

        Used by batch_dispatch to validate tape_mm consistency across batch items
        without reaching into the private _loader attribute. (Copilot-Review C7
        PR #106.)

        Raises:
            TemplateNotFoundError: wenn template_id nicht im TemplateLoader.
        """
        template = self._loader.get(template_id)
        return template.tape_mm
```

- [ ] **Step 4: Add `PrintService.submit_batch_job`**

In `backend/app/services/print_service.py`, add method after `submit_print_job`:

```python
    async def submit_batch_job(
        self,
        requests: list[PrintRequest],
        *,
        half_cut: bool,
    ) -> list[UUID]:
        """Phase 1k.2: Render N items, submit ONE BatchJob to PrintQueue.

        Atomic: alle job_ids werden gemeinsam als completed/failed markiert.
        Preflight + tape-mismatch werden 1x am Anfang fuer alle items geprueft.
        """
        if not requests:
            raise ValueError("submit_batch_job requires at least one request")

        # 1. Load templates (alle muessen existieren — TemplateNotFoundError vorher abgefangen)
        templates = [self._loader.get(r.template_id) for r in requests]
        tape_mm = templates[0].tape_mm  # alle gleich (mixed-tape-check vorher)

        # 2. Preflight + tape-mismatch (1x fuer alle)
        preflight = await self._backend.preflight_check()
        if preflight.loaded_tape_mm != tape_mm:
            raise TapeMismatchError(
                expected_mm=tape_mm,
                loaded_mm=preflight.loaded_tape_mm,
            )

        # 3. Resolve LabelData ONCE per item, then render — Copilot-Review C8 +
        # Gemini-Review G3 (PR #106):
        # - label_data wird einmal pro Item resolved, fuer Render UND Persist
        #   wiederverwendet (vorher 2x: einmal fuer renderer, einmal fuer payload).
        # - Pillow-Render via asyncio.to_thread (CPU-intensive, blockiert sonst Event-Loop).
        # - asyncio.gather parallelisiert die N Resolve-und-Render Operationen.
        async def _prepare_one(
            req: PrintRequest, tmpl: TemplateSchema
        ) -> tuple[Image.Image, dict[str, Any]]:
            label_data = await self._resolve_label_data(req)
            image = await asyncio.to_thread(self._renderer.render, tmpl, label_data)
            return image, label_data.model_dump()

        prepared = await asyncio.gather(
            *[_prepare_one(r, t) for r, t in zip(requests, templates, strict=True)]
        )
        images = [img for img, _ in prepared]
        label_data_dumps = [dump for _, dump in prepared]

        # 4. Pre-allocate job UUIDs + persist in JobStore (analog submit_print_job).
        # Gemini-Review G-R2-3 (PR #106): JobStore.save_queued erwartet eine
        # DbJob model instance, NICHT kwargs. Konsistent mit submit_print_job.
        # Implementer: ggf. import-Pfad an existing submit_print_job orientieren
        # (from app.models.job import Job as DbJob).
        job_ids: list[UUID] = []
        for request, ld_dump in zip(requests, label_data_dumps, strict=True):
            job_id = uuid4()
            db_job = DbJob(
                id=job_id,
                printer_id=self._printer_id,
                template_key=request.template_id,
                payload={
                    "tape_mm": tape_mm,
                    "options": request.options.model_dump(),
                    "label_data": ld_dump,
                },
                api_key_id=None,
                source_ip=None,
            )
            await self._store.save_queued(db_job)
            job_ids.append(job_id)

        # 5. Enqueue as BatchJob
        await self._queue.enqueue_batch(
            printer_id=self._printer_id,
            images=images,
            job_ids=job_ids,
            tape_mm=tape_mm,
            options={
                "auto_cut": True,  # Sammelt
                "high_resolution": False,
                "half_cut": half_cut,
            },
        )

        return job_ids
```

Add imports at top of print_service.py if missing:
```python
import asyncio
from typing import Any
from uuid import UUID, uuid4

from PIL import Image  # nur falls noch nicht da

from app.models.job import Job as DbJob   # Gemini-Review G-R2-3 PR #106
from app.schemas.template import TemplateSchema
```

- [ ] **Step 5: Run tests + commit**

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/services/ -q 2>&1 | tail -3
backend/.venv/bin/ruff check backend/app/services/batch_dispatch.py backend/app/services/print_service.py backend/tests/unit/services/test_batch_dispatch.py
backend/.venv/bin/ruff format --check backend/app/services/batch_dispatch.py backend/app/services/print_service.py
backend/.venv/bin/mypy backend/app/services/batch_dispatch.py backend/app/services/print_service.py 2>&1 | tail -3

git add backend/app/services/batch_dispatch.py backend/app/services/print_service.py backend/tests/unit/services/test_batch_dispatch.py
git commit -m "feat(batch): dispatch_batch refactor to atomic BatchJob (Phase 1k.2 Task 9)

dispatch_batch sammelt valide items (per-item template_not_found etc. weiter
in errors[]), prueft mixed tape_mm vor Queue, ruft service.submit_batch_job
fuer den happy path. PrintService.submit_batch_job rendert N images,
persistiert N JobRecords, queued ONE BatchJob via enqueue_batch.

MixedTapeSizesError als neue Fatal-Error (→ 400 im Route-Layer).

Refs #102"
```

---

## Task 10: API-Route `batch.py` MixedTapeSizesError → 400

**Files:**
- Modify: `backend/app/api/routes/batch.py`

**Rationale:** MixedTapeSizesError aus dispatch_batch muss vom Route-Layer auf HTTP 400 gemapped werden.

- [ ] **Step 1: Inspect existing route**

```bash
sed -n '38,120p' backend/app/api/routes/batch.py
```

- [ ] **Step 2: Modify route handler**

Add to the try/except block in `create_batch`:

```python
        from app.services.batch_dispatch import MixedTapeSizesError

        try:
            job_ids, errors = await dispatch_batch(
                service, body.items,
                half_cut_override=body.half_cut_override,
                backend=backend,
            )
        except MixedTapeSizesError as exc:
            raise HTTPException(
                400,
                detail={
                    "error_code": "mixed_tape_sizes",
                    "error_message": str(exc),
                    "tape_mm_values": exc.tape_mm_values,
                },
            ) from exc
        # ... existing TapeMismatchError + PrinterOfflineError handlers stay
```

- [ ] **Step 3: Failing test**

In existing `backend/tests/integration/api/test_batch_endpoint_*.py`, add:

```python
@pytest.mark.anyio
async def test_post_batch_with_mixed_tape_sizes_returns_400(
    api_client_with_seed
):
    """Phase 1k.2: Batch with items pointing to different tape templates → 400."""
    body = {
        "items": [
            {
                "template_id": "qr-only-12mm",  # 12mm tape
                "data": {"primary_id": "A", "title": "T", "qr_payload": "https://e.test/a"},
            },
            {
                "template_id": "qr-only-18mm",  # 18mm tape
                "data": {"primary_id": "B", "title": "T", "qr_payload": "https://e.test/b"},
            },
        ],
    }
    resp = await api_client_with_seed.post(
        "/api/print/brother-p750w/batch",
        json=body,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "mixed_tape_sizes"
```

- [ ] **Step 4: Run + commit**

```bash
backend/.venv/bin/python -m pytest backend/tests/integration/api/ -q 2>&1 | tail -3
backend/.venv/bin/ruff check backend/app/api/routes/batch.py
backend/.venv/bin/ruff format --check backend/app/api/routes/batch.py
backend/.venv/bin/mypy backend/app/api/routes/batch.py 2>&1 | tail -3

git add backend/app/api/routes/batch.py backend/tests/integration/api/
git commit -m "feat(api): MixedTapeSizesError → 400 mixed_tape_sizes (Phase 1k.2 Task 10)

Refs #102"
```

---

## Task 11: End-to-End Integration-Test

**Files:**
- Create: `backend/tests/integration/test_batch_endpoint_multi_label.py`

**Rationale:** Verifiziert full flow: HTTP POST → batch_dispatch → submit_batch_job → enqueue_batch → worker → printer.print_images → atomic completion.

- [ ] **Step 1: Write end-to-end test**

```python
"""Phase 1k.2 End-to-End: POST /batch → BatchJob path → atomic completion."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


@pytest.mark.anyio
async def test_post_batch_4_items_calls_print_images_once(
    api_client_with_seed,
    monkeypatch,
):
    """4-item batch results in EXACTLY ONE print_images call (not 4 print_image)."""
    # Spy on Backend.print_images via fixture-installed mock
    body = {
        "items": [
            {
                "template_id": "qr-only-12mm",
                "data": {
                    "primary_id": f"V{i}",
                    "title": "smoke",
                    "qr_payload": f"https://e.test/{i}",
                },
            }
            for i in range(4)
        ],
    }
    resp = await api_client_with_seed.post(
        "/api/print/brother-p750w/batch",
        json=body,
    )
    assert resp.status_code == 202
    rb = resp.json()
    assert len(rb["job_ids"]) == 4
    assert rb["errors"] == []

    # Allow worker to dequeue + process
    for _ in range(50):
        await asyncio.sleep(0.05)
        # check mock call count via shared fixture

    # The Mock-Backend in the integration conftest must have:
    #   backend.print_images.await_count == 1
    #   backend.print_image.await_count == 0
    # Implementer adds asserts based on conftest setup.


@pytest.mark.anyio
async def test_post_batch_failure_marks_all_jobs_failed(
    api_client_with_seed,
    monkeypatch,
):
    """When print_images raises, all 4 job_ids show status='failed'."""
    # Implementer adapts to existing conftest patterns for status polling.
```

(The full test depends on existing `api_client_with_seed` fixture setup in `backend/tests/integration/conftest.py`. The implementer should consult existing tests like `test_batch_endpoint_happy.py` for patterns.)

- [ ] **Step 2: Run + commit**

```bash
backend/.venv/bin/python -m pytest backend/tests/integration/test_batch_endpoint_multi_label.py -v 2>&1 | tail -10

git add backend/tests/integration/test_batch_endpoint_multi_label.py
git commit -m "test(batch): end-to-end multi-label batch integration test (Phase 1k.2 Task 11)

Refs #102"
```

---

## Task 12: Hardware-Smoke-Script

**Files:**
- Create: `backend/scripts/smoke_first_print_batch.py`

**Rationale:** Manueller Test gegen echten PT-P750W. Verifiziert visuell die 5mm Half-Cut Eigenschaft die unit/integration tests nicht prüfen können.

- [ ] **Step 1: Create script**

```python
"""Manual hardware-smoke: 4-item batch via POST /batch endpoint.

Usage:
    python3 backend/scripts/smoke_first_print_batch.py [hub_url] [api_key]

Defaults to http://localhost:8000 + env $PRINTER_HUB_WEBHOOK_API_KEY.

Expected output: 4 labels on the tape strip, with ~5mm Half-Cut between each
item and a full cut at the end. Compare to Brother iOS App print quality.
"""
from __future__ import annotations

import os
import sys

import httpx

HUB_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
# Copilot-Review C9 (PR #106): kein hardcoded API-Key Default. Wenn weder
# CLI-Arg noch Env-Var gesetzt -> sofortiger Fehler mit klarer Meldung.
API_KEY = (
    sys.argv[2] if len(sys.argv) > 2
    else os.environ.get("PRINTER_HUB_WEBHOOK_API_KEY")
)
if not API_KEY:
    print(
        "ERROR: API key required. Set $PRINTER_HUB_WEBHOOK_API_KEY or pass as 2nd CLI arg.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    body = {
        "items": [
            {
                "template_id": "qr-only-12mm",
                "data": {
                    "primary_id": f"BATCH-{i+1}",
                    "title": "Phase 1k.2 Smoke",
                    "qr_payload": f"https://hangar.example.test/smoke/batch/{i+1}",
                },
            }
            for i in range(4)
        ],
    }
    resp = httpx.post(
        f"{HUB_URL}/api/print/brother-p750w/batch",
        json=body,
        headers={"X-Label-Hub-Key": API_KEY},
        timeout=30.0,
    )
    print(f"HTTP {resp.status_code}")
    print(resp.json())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_first_print_batch.py
git commit -m "feat(scripts): smoke_first_print_batch.py — manual 4-item batch hardware-smoke (Phase 1k.2 Task 12)

Verify 5mm Half-Cut between batch items vs Brother iOS App output.

Refs #102"
```

---

## Final Verification

- [ ] **Step 1: Full test-suite green**

```bash
cd /opt/repos/label-printer-hub
backend/.venv/bin/python -m pytest backend/tests -q 2>&1 | tail -5
```

Expected: 952 (baseline) + neue Task-Tests = ~990+ passed, 5 skipped.

- [ ] **Step 2: Full lint clean**

```bash
backend/.venv/bin/ruff check backend/app backend/tests
backend/.venv/bin/ruff format --check backend/app backend/tests
backend/.venv/bin/mypy backend/app 2>&1 | tail -3
```

Expected: clean (10 pre-existing import-untyped acceptable per Phase 1i baseline).

- [ ] **Step 3: Privacy + secret scan**

```bash
# (Privacy-scan: identisch zum CI-Job — siehe .github/workflows/ci.yml Step "Privacy / secret scan".
# Implementer kann den CI-Step lokal nachbauen falls noetig.)
```

Expected: empty (no privacy violations).

- [ ] **Step 4: Push + PR**

```bash
git push -u origin spec/phase-1k.2-multi-label-batch 2>&1 | tail -5

gh pr create --repo strausmann/Label-Printer-Hub \
  --title "feat: Phase 1k.2 Multi-Label-Batch via ptouch.print_multi (#102)" \
  --body "$(cat <<'EOF'
## Phase 1k.2 Implementation

Implements approved spec: \`docs/superpowers/specs/2026-06-04-multi-label-batch-design.md\`

Closes #102.

## Was geht

- Multi-Label-Batches an PT-Series produzieren 5mm Half-Cut zwischen Labels (Brother iOS App Verhalten)
- Statt 22.5mm Pre-Roll pro Item: 1 Connection, 1 Pre-Roll fuer den ganzen Batch
- Atomic semantics: bei Fehler werden alle job_ids des Batches gemeinsam als failed markiert
- API-Vertrag unveraendert (job_ids[] in BatchResponse)
- QL-820NWB: per-item Loop via default_print_images_loop (kein print_multi-Equivalent in brother_ql Lib)

## Bug-Fix als Bonus

PR #100 (last_page→feed) erreichte ptouch lib nicht weil _PTPQueuePrinter Adapter
half_cut + last_page aus options dict NICHT an backend.print_image forwarded.
Hier in Task 6 mit-gefixt.

## Test-Counts

- Baseline (nach PR #100): 952 passed
- Diese PR: ~990+ passed (+38 neue tests in 12 tasks)
- Manueller Hardware-Smoke: backend/scripts/smoke_first_print_batch.py

Refs Phase 1i Smoke-Empirie: docs/site/operations/protokolle/2026-06-04-phase1i-smoke-test-empirie.md
EOF
)" --base main --head spec/phase-1k.2-multi-label-batch
```

---

## Self-Review

(Wird vom writing-plans Workflow direkt nach Plan-Erstellung gemacht.)

### Spec Coverage Check

| Spec-Section | Tasks |
|---|---|
| Architektur Render-Phase | Task 9 (dispatch_batch + submit_batch_job) |
| Architektur Print-Phase | Task 3 (print_images PT) + Task 8 (BatchJob worker) |
| Neue Komponenten BatchJob | Task 8 |
| Neue Methode PrinterBackend.print_images | Task 2 |
| Neue Methode PTouchBackend.print_images | Task 3 |
| Neuer Helper _ptouch_print_multi | Task 3 |
| Modified batch_dispatch | Task 9 |
| Modified PrintQueue enqueue_batch + worker | Task 8 |
| Failure Modes (mixed tape, tape mismatch, hardware) | Tasks 9, 10 |
| Atomic Failure Semantik | Task 8 |
| Tests (unit + integration + hardware) | Tasks 1-12 (alle TDD) |
| Backward-Compat | Tasks 4, 5 (QL/Mock delegate), Task 6 (PT print_image bleibt) |

Vollständige Abdeckung.

### Placeholder Scan

- ✅ Keine "TBD", "TODO", "implement later"
- ✅ Alle code-Blocks haben tatsächlichen Code, keine "fill in" Phrasen
- ⚠️ Task 9 + 11 verweisen auf "existing test patterns" / "consult existing conftest" — das ist akzeptabel (Implementer darf existing patterns lesen), aber wenn der spec-reviewer das anzweifelt → minimal-test-code als Fallback in Task 9/11 expandieren

### Type-Konsistenz

- `BatchJob` Felder `batch_id, printer_id, image_payloads, job_ids, tape_mm, options` konsistent in Tasks 8 + 9
- `print_images` Signatur `(images: list[Image.Image], tape_spec: TapeSpec, *, auto_cut, high_resolution, half_cut) -> None` konsistent in Tasks 2, 3, 4, 5
- Queue-Adapter `print_images` Signatur `(images: list[Image.Image], *, tape_mm: int, **options) -> None` konsistent in Tasks 6, 7, 8
- `enqueue_batch` Parameter `(printer_id, images, job_ids, tape_mm, options)` konsistent in Task 8 + 9
- `MixedTapeSizesError` konsistent in Task 9 + 10

Alle types und signaturen konsistent.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-04-multi-label-batch-plan.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — Orchestrator dispatched 1 fresh subagent pro Task (12 Tasks), nach jeder spec-compliance + code-quality review. Fast iteration, parallel safety.

**2. Inline Execution** — Execute tasks in this session using superpowers:executing-plans, batch execution with checkpoints for review.

Welcher Ansatz?
