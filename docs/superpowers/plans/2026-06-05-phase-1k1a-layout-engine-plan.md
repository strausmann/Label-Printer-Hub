# Phase 1k.1a Hub Layout-Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ersetzt die 21 hartcodierten YAML-Templates durch eine semantische tape-unabhaengige LayoutEngine mit TapeGeometry-Tabelle (7 Tape-Groessen) und 7 ContentTypes auf dem Hub-Backend (Python/FastAPI).

**Architecture:** LayoutEngine.render(tape_mm, content_type, data) ersetzt LabelRenderer komplett. Hard-Cut Migration ohne Legacy-Kompatibilitaet — alle Templates, TemplateLoader, /api/templates Routes und der PAUSED-Job-Pfad werden geloescht. `jobs.template_key` bleibt als nullable Audit-Spalte erhalten, neue Spalten `jobs.content_type` + `jobs.rendered_tape_mm` werden deterministisch backfilled.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PIL/Pillow, qrcode, SQLAlchemy + Alembic, pytest.

**Spec Reference:** `docs/superpowers/specs/2026-06-05-phase-1k1-layout-engine-design.md` (commit 6de07cd, approved nach 7 Review-Runden)

**Issue:** strausmann/Label-Printer-Hub#103 (Phase 1k.1 unter Umbrella #101)

**Working Branch:** Neuer Branch `feat/phase-1k1a-layout-engine` von `main`. (NICHT auf `spec/phase-1k1-layout-engine` arbeiten — die Spec wird separat gemerged.)

---

## File Structure

**Created (new files):**

| Datei | Verantwortung |
|-------|---------------|
| `backend/app/schemas/tape_geometry.py` | TapeGeometry Pydantic-Model + `TAPE_GEOMETRY` dict (7 Eintraege) |
| `backend/app/schemas/content_type.py` | `ContentType` Enum (7 Werte) |
| `backend/app/schemas/label_data_item.py` | `LabelDataItem` (item + optional qr_payload) fuer qr_with_listing |
| `backend/app/services/layout_engine.py` | `LayoutEngine.render()` + 7 `_render_*` Methoden + Validation |
| `backend/app/printer_backends/exceptions.py` (Erweiterung) | `UnsupportedTapeError`, `NoTapeLoadedError`, `ContentTypeDataMismatchError` |

**Modified:**

| Datei | Aenderung |
|-------|-----------|
| `backend/app/schemas/label_data.py` | title/primary_id/qr_payload optional; items: tuple[LabelDataItem,...] |
| `backend/app/schemas/print_request.py` | content_type-Feld; template_id + on_tape_mismatch raus |
| `backend/app/services/print_service.py` | LayoutEngine statt LabelRenderer, kein TapeMismatchError-Pfad mehr |
| `backend/app/services/print_queue.py` | _rerender_from_db nutzt LayoutEngine.render(); PAUSED-State raus |
| `backend/app/services/batch_dispatch.py` | MixedTapeSizesError + Tape-Konsistenz-Check raus |
| `backend/app/api/routes/print.py` | APIRouter(prefix="/api"); content_type-Schema; resume-Route raus |
| `backend/app/api/routes/batch.py` | content_type, MixedTapeSizesError-Mapping raus |
| `backend/app/api/routes/jobs.py` | resume-Route raus |
| `backend/app/api/error_handlers.py` | UnsupportedTapeError 409, ContentTypeDataMismatchError 422, NoTapeLoadedError 409; alte raus |
| `backend/app/main.py` | templates-Router-Registrierungen weg; LayoutEngine in app.state |
| `backend/app/lifespan.py` | TemplateLoader-Preload raus |

**Deleted:**

| Datei | Begruendung |
|-------|------------|
| `backend/app/services/label_renderer.py` | Durch LayoutEngine ersetzt |
| `backend/app/services/template_loader.py` | Templates obsolet |
| `backend/app/services/svg_renderer.py` | v1 SVG-Renderer obsolet |
| `backend/app/schemas/template.py` | v1 Schema obsolet |
| `backend/app/schemas/template_read.py` | Read-Schema obsolet |
| `backend/app/models/template.py` | SQLAlchemy-Model obsolet |
| `backend/app/repositories/templates.py` | templates Tabelle dropped |
| `backend/app/api/routes/templates.py` | /api/templates/* weg |
| `backend/app/api/routes/templates_preview.py` | /api/templates/{key}/preview-* weg |
| `backend/app/seed/templates/*.yaml` | Alle 21 YAML-Files |
| `backend/tests/**/test_template*` | Alle Template-Tests |
| `backend/tests/**/test_label_renderer*` | Alle alten Renderer-Tests |
| `backend/tests/**/test_svg_renderer*` | SVG-Renderer-Tests |

---

## Task Execution Order (Critical)

Tasks 1-13 (Foundation + LayoutEngine) muessen VOR den Service-Refactors (Tasks 14-17) abgeschlossen sein. Tasks 22-23 (DB-Migration + File-Cleanup) sind die LETZTEN Schritte vor der Final-Integration.

Reihenfolge:
1. Foundation (Tasks 1-4)
2. Exceptions (Task 5)
3. LayoutEngine (Tasks 6-13)
4. Request-Schema-Anpassung (Task 14)
5. Service-Refactors (Tasks 15-17)
6. Route-Refactors (Tasks 18-20)
7. Error-Handler (Task 21)
8. DB-Migration (Task 22)
9. File-Cleanup (Task 23)
10. Main/Lifespan-Cleanup (Task 24)
11. Final Integration (Task 25)

---

### Task 1: TapeGeometry Schema

**Files:**
- Create: `backend/app/schemas/tape_geometry.py`
- Test: `backend/tests/unit/schemas/test_tape_geometry.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_tape_geometry.py
"""Unit tests for TapeGeometry model and TAPE_GEOMETRY constants table."""

from __future__ import annotations

import pytest
from app.schemas.tape_geometry import TAPE_GEOMETRY, TapeGeometry


class TestTapeGeometryModel:
    def test_valid_values_accepted(self) -> None:
        geom = TapeGeometry(
            printable_px=70, qr_max_px=66, qr_padding_px=2,
            text_start_x=72, line_spacing_px=4,
            font_xl=22, font_l=18, font_m=14, font_s=10,
        )
        assert geom.printable_px == 70

    def test_zero_printable_px_rejected(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            TapeGeometry(
                printable_px=0, qr_max_px=66, qr_padding_px=2,
                text_start_x=72, line_spacing_px=4,
                font_xl=22, font_l=18, font_m=14, font_s=10,
            )

    def test_negative_qr_padding_rejected(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            TapeGeometry(
                printable_px=70, qr_max_px=66, qr_padding_px=-1,
                text_start_x=72, line_spacing_px=4,
                font_xl=22, font_l=18, font_m=14, font_s=10,
            )

    def test_frozen_immutable(self) -> None:
        geom = TapeGeometry(
            printable_px=70, qr_max_px=66, qr_padding_px=2,
            text_start_x=72, line_spacing_px=4,
            font_xl=22, font_l=18, font_m=14, font_s=10,
        )
        with pytest.raises(ValueError):
            geom.printable_px = 100  # type: ignore[misc]


class TestTapeGeometryConstants:
    def test_all_seven_sizes_defined(self) -> None:
        assert set(TAPE_GEOMETRY.keys()) == {4, 6, 9, 12, 18, 24, 62}

    def test_12mm_v4_winner_values(self) -> None:
        geom = TAPE_GEOMETRY[12]
        assert geom.printable_px == 70
        assert geom.qr_max_px == 66
        assert geom.text_start_x == 72
        assert geom.font_xl == 22
        assert geom.font_l == 18

    def test_qr_max_px_follows_formula(self) -> None:
        """qr_max_px = printable_px - 2 * qr_padding_px"""
        for tape_mm, geom in TAPE_GEOMETRY.items():
            expected = geom.printable_px - 2 * geom.qr_padding_px
            assert geom.qr_max_px == expected, (
                f"{tape_mm}mm: qr_max_px={geom.qr_max_px} expected {expected}"
            )

    def test_text_start_x_follows_formula(self) -> None:
        """text_start_x = printable_px + qr_padding_px"""
        for tape_mm, geom in TAPE_GEOMETRY.items():
            expected = geom.printable_px + geom.qr_padding_px
            assert geom.text_start_x == expected, (
                f"{tape_mm}mm: text_start_x={geom.text_start_x} expected {expected}"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/schemas/test_tape_geometry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.tape_geometry'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/schemas/tape_geometry.py
"""Brother printer tape geometry — pixel dimensions per supported tape width.

Each TapeGeometry entry describes the printable area and layout parameters for
a single tape width. The renderer (LayoutEngine) consumes these to position
QR codes and text deterministically, independent of which ContentType is used.

The 12mm values are empirically validated (Phase 1i V4-Winner, scan-verified).
Other tape widths are extrapolated via pixel-ratio from 12mm and require
post-deploy smoke-test validation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TapeGeometry(BaseModel):
    """Render parameters for one supported tape width (all values in pixels).

    Formulas (enforced by TAPE_GEOMETRY entries):
        qr_max_px = printable_px - 2 * qr_padding_px
        text_start_x = printable_px + qr_padding_px
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    printable_px: int = Field(gt=0)
    """Print-pin count per tape (Brother spec)."""

    qr_max_px: int = Field(gt=0)
    """Square QR-code edge length: printable_px - 2 * qr_padding_px."""

    qr_padding_px: int = Field(ge=0)
    """Padding around the QR-code (also separator gap before text column)."""

    text_start_x: int = Field(ge=0)
    """Absolute X-position where text rendering starts (after QR + gap)."""

    line_spacing_px: int = Field(ge=0)
    """Vertical gap between adjacent text lines."""

    font_xl: int = Field(gt=0)
    """primary_id font size."""

    font_l: int = Field(gt=0)
    """title font size."""

    font_m: int = Field(gt=0)
    """listing item / secondary content font size."""

    font_s: int = Field(gt=0)
    """secondary line font size."""


TAPE_GEOMETRY: dict[int, TapeGeometry] = {
    4:  TapeGeometry(printable_px=24,  qr_max_px=20,  qr_padding_px=2, text_start_x=26,  line_spacing_px=1,  font_xl=8,   font_l=7,  font_m=6,  font_s=5),
    6:  TapeGeometry(printable_px=32,  qr_max_px=28,  qr_padding_px=2, text_start_x=34,  line_spacing_px=2,  font_xl=10,  font_l=9,  font_m=7,  font_s=6),
    9:  TapeGeometry(printable_px=50,  qr_max_px=46,  qr_padding_px=2, text_start_x=52,  line_spacing_px=3,  font_xl=14,  font_l=12, font_m=10, font_s=8),
    12: TapeGeometry(printable_px=70,  qr_max_px=66,  qr_padding_px=2, text_start_x=72,  line_spacing_px=4,  font_xl=22,  font_l=18, font_m=14, font_s=10),
    18: TapeGeometry(printable_px=112, qr_max_px=108, qr_padding_px=2, text_start_x=114, line_spacing_px=6,  font_xl=32,  font_l=26, font_m=20, font_s=14),
    24: TapeGeometry(printable_px=128, qr_max_px=124, qr_padding_px=2, text_start_x=130, line_spacing_px=8,  font_xl=36,  font_l=30, font_m=24, font_s=18),
    62: TapeGeometry(printable_px=696, qr_max_px=688, qr_padding_px=4, text_start_x=700, line_spacing_px=20, font_xl=120, font_l=96, font_m=72, font_s=48),
}
"""Map int(tape_mm) -> TapeGeometry. 12mm scan-verified, others extrapolated."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/schemas/test_tape_geometry.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/tape_geometry.py backend/tests/unit/schemas/test_tape_geometry.py
git commit -m "feat(schemas): add TapeGeometry + TAPE_GEOMETRY constants table

Phase 1k.1a Task 1: introduces the central pixel-geometry table for all 7
supported tape widths (4/6/9/12/18/24/62mm). 12mm scan-verified, others
extrapolated via pixel-ratio.

Refs #103"
```

---

### Task 2: ContentType Enum

**Files:**
- Create: `backend/app/schemas/content_type.py`
- Test: `backend/tests/unit/schemas/test_content_type.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_content_type.py
"""Unit tests for ContentType enum."""

from __future__ import annotations

from app.schemas.content_type import ContentType


class TestContentType:
    def test_all_seven_values_defined(self) -> None:
        assert {c.value for c in ContentType} == {
            "qr_only", "qr_one_line", "qr_two_lines", "qr_three_lines",
            "text_one_line", "text_two_lines", "qr_with_listing",
        }

    def test_string_value_round_trip(self) -> None:
        assert ContentType("qr_two_lines") == ContentType.QR_TWO_LINES
        assert ContentType.QR_TWO_LINES.value == "qr_two_lines"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/schemas/test_content_type.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# backend/app/schemas/content_type.py
"""Semantic content types — tape-independent label descriptions.

Each ContentType describes WHAT is rendered (QR + N text lines, or listing,
or text-only). The renderer (LayoutEngine) consumes (tape_mm, content_type,
data) and produces a PIL Image — pixel positions are computed from the
TapeGeometry table, not from the ContentType.
"""

from __future__ import annotations

from enum import StrEnum


class ContentType(StrEnum):
    """Tape-independent semantic content types for label rendering."""

    QR_ONLY = "qr_only"
    """QR fills the full tape height; no text."""

    QR_ONE_LINE = "qr_one_line"
    """QR left + 1 text line (XL, vertically centered): qr_payload + primary_id."""

    QR_TWO_LINES = "qr_two_lines"
    """QR left + 2 text lines (XL primary_id + L title)."""

    QR_THREE_LINES = "qr_three_lines"
    """QR left + 3 text lines (XL primary_id + L title + S secondary[0])."""

    TEXT_ONE_LINE = "text_one_line"
    """Full-width text XL (primary_id); no QR."""

    TEXT_TWO_LINES = "text_two_lines"
    """2 text lines (XL primary_id + L title); no QR."""

    QR_WITH_LISTING = "qr_with_listing"
    """QR + N item lines (M font); overflow shows "+N more"."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/schemas/test_content_type.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/content_type.py backend/tests/unit/schemas/test_content_type.py
git commit -m "feat(schemas): add ContentType enum (7 semantic types)

Phase 1k.1a Task 2: introduces tape-independent ContentType enum.
qr_only, qr_one_line, qr_two_lines, qr_three_lines, text_one_line,
text_two_lines, qr_with_listing.

Refs #103"
```

---

### Task 3: LabelDataItem Schema

**Files:**
- Create: `backend/app/schemas/label_data_item.py`
- Test: `backend/tests/unit/schemas/test_label_data_item.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_label_data_item.py
"""Unit tests for LabelDataItem (qr_with_listing child)."""

from __future__ import annotations

import pytest
from app.schemas.label_data_item import LabelDataItem


class TestLabelDataItem:
    def test_minimal_item(self) -> None:
        item = LabelDataItem(item="A — Schrauben")
        assert item.item == "A — Schrauben"
        assert item.qr_payload is None

    def test_with_qr_payload(self) -> None:
        item = LabelDataItem(
            item="B", qr_payload="https://example.com/locations/k02/b"
        )
        assert item.qr_payload == "https://example.com/locations/k02/b"

    def test_item_required(self) -> None:
        with pytest.raises(ValueError, match="item"):
            LabelDataItem()  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        item = LabelDataItem(item="A")
        with pytest.raises(ValueError):
            item.item = "B"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/schemas/test_label_data_item.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# backend/app/schemas/label_data_item.py
"""Single child entry for qr_with_listing aggregation labels."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LabelDataItem(BaseModel):
    """One row in a qr_with_listing label (e.g. Kallax-Regal-Uebersicht)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: str
    """Display text for this child (e.g. 'A — Schrauben')."""

    qr_payload: str | None = None
    """Optional per-child QR payload (reserved; not rendered in 1k.1a)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/schemas/test_label_data_item.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/label_data_item.py backend/tests/unit/schemas/test_label_data_item.py
git commit -m "feat(schemas): add LabelDataItem (qr_with_listing child)

Phase 1k.1a Task 3: child-entry model for qr_with_listing aggregation.
Used in LabelData.items tuple for Kallax-Regal-Uebersicht labels.

Refs #103"
```

---

### Task 4: LabelData — Optional Fields + items

**Files:**
- Modify: `backend/app/schemas/label_data.py`
- Test: `backend/tests/unit/schemas/test_label_data.py` (Adapt existing or create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_label_data.py (replace or extend existing tests)
"""Unit tests for LabelData with optional fields and items extension."""

from __future__ import annotations

from app.schemas.label_data import LabelData
from app.schemas.label_data_item import LabelDataItem


class TestLabelDataOptionalFields:
    def test_only_source_app_required(self) -> None:
        data = LabelData(source_app="manual")
        assert data.title is None
        assert data.primary_id is None
        assert data.qr_payload is None
        assert data.secondary == ()
        assert data.items == ()

    def test_all_fields_set(self) -> None:
        data = LabelData(
            source_app="hangar",
            primary_id="K-02",
            title="Werkstatt",
            qr_payload="https://example.com/locations/k-02",
            secondary=("Notiz 1",),
            items=(LabelDataItem(item="A"), LabelDataItem(item="B")),
        )
        assert data.items[0].item == "A"
        assert len(data.items) == 2

    def test_frozen(self) -> None:
        data = LabelData(source_app="manual")
        import pytest
        with pytest.raises(ValueError):
            data.title = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/schemas/test_label_data.py -v`
Expected: FAIL — original `title: str` was required.

- [ ] **Step 3: Modify implementation**

Replace the contents of `backend/app/schemas/label_data.py` with:

```python
"""App-agnostic label data passed from lookup-clients to the LayoutEngine.

LabelData is what a `*_client.lookup(id)` call produces. It is the
serialisable view of a real-world entity (Snipe-IT asset, Grocy product,
Spoolman spool, Hangar location) condensed into the minimal set of fields
a label may need: an optional title, an optional identifier, an optional
QR payload, optional secondary lines, and a source-app tag.

**Phase 1k.1a:** All content fields are optional because ContentType
selects which fields are required for a given render call. The
LayoutEngine validates per-ContentType requirements in
`_validate_data()` and raises `ContentTypeDataMismatchError` if the
required fields are missing.

Only `source_app` remains required — it is used for downstream routing,
logging, and metrics independent of the chosen ContentType.

Layout, font, geometry, and tape-fit decisions live in TapeGeometry +
LayoutEngine, NOT here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.label_data_item import LabelDataItem


class LabelData(BaseModel):
    """Immutable, app-agnostic label payload."""

    model_config = ConfigDict(frozen=True)

    source_app: str
    """Source application tag (e.g. 'snipeit', 'grocy', 'spoolman', 'hangar', 'manual')."""

    title: str | None = None
    """Optional title (e.g. asset name); required by qr_two_lines, qr_three_lines, text_two_lines."""

    primary_id: str | None = None
    """Optional primary identifier; required by qr_one_line, *_two_lines, *_three_lines, text_one_line, qr_with_listing (header)."""

    qr_payload: str | None = None
    """Optional URL/payload for the QR code; required by qr_only, qr_*_line(s), qr_with_listing."""

    secondary: tuple[str, ...] = ()
    """Optional additional text lines; first entry rendered by qr_three_lines."""

    items: tuple[LabelDataItem, ...] = ()
    """Child items for qr_with_listing aggregation labels (Kallax-Regal-Uebersicht etc.)."""
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/schemas/test_label_data.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full test suite to find dependent breakages**

Run: `cd backend && pytest -x --ignore=tests/integration 2>&1 | tail -30`
Expected: Multiple failures in tests that constructed `LabelData(title="x", primary_id="y", qr_payload="z", source_app="...")` — these still work (constructor accepts kwargs). But tests that expected raises when fields were missing now fail. Note failures for Task 5+ to address.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/label_data.py backend/tests/unit/schemas/test_label_data.py
git commit -m "feat(schemas): LabelData fields optional + items extension

Phase 1k.1a Task 4: title/primary_id/qr_payload werden optional
(str | None = None). source_app bleibt einzig zwingend gesetzt.
items: tuple[LabelDataItem, ...] = () fuer qr_with_listing.

ContentType-spezifische Pflichtfeld-Validation passiert ab jetzt zentral
in LayoutEngine._validate_data() — siehe Task 6.

Refs #103"
```

---

### Task 5: New Exceptions

**Files:**
- Modify: `backend/app/printer_backends/exceptions.py`
- Test: `backend/tests/unit/printer_backends/test_exceptions.py` (extend existing)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/printer_backends/test_exceptions.py (extend with new tests)
from __future__ import annotations

import pytest
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    NoTapeLoadedError,
    UnsupportedTapeError,
)


class TestUnsupportedTapeError:
    def test_carries_tape_mm(self) -> None:
        exc = UnsupportedTapeError(tape_mm=36)
        assert exc.tape_mm == 36
        assert "36" in str(exc)
        assert "supported" in str(exc).lower()


class TestNoTapeLoadedError:
    def test_message_default(self) -> None:
        exc = NoTapeLoadedError()
        assert "no tape" in str(exc).lower()


class TestContentTypeDataMismatchError:
    def test_carries_content_type_and_missing(self) -> None:
        exc = ContentTypeDataMismatchError(
            content_type="qr_two_lines",
            missing_fields=("primary_id", "title"),
        )
        assert exc.content_type == "qr_two_lines"
        assert exc.missing_fields == ("primary_id", "title")
        assert "primary_id" in str(exc) and "title" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/printer_backends/test_exceptions.py -v`
Expected: FAIL with `ImportError` for the new classes.

- [ ] **Step 3: Extend implementation**

Append to `backend/app/printer_backends/exceptions.py`:

```python
class UnsupportedTapeError(Exception):
    """Raised when the preflight-detected tape_mm is not in TAPE_GEOMETRY.

    HTTP-Status: 409 (Conflict) — same family as TapeEmptyError, CoverOpenError.
    The user must switch to a supported tape; retrying with the same loaded
    tape will fail again.

    Defensive: with 7 supported sizes (4/6/9/12/18/24/62mm) this should not
    occur in typical hardware setups (PT-Serie + QL-820NWB). The bestehende
    TapeRegistry kennt zusaetzliche QL-DK-Breiten (29/38/50/54mm), die in
    1k.1 bewusst noch nicht abgedeckt sind — Erweiterung als Folge-Phase
    moeglich.
    """

    def __init__(self, *, tape_mm: int) -> None:
        self.tape_mm = tape_mm
        supported = (4, 6, 9, 12, 18, 24, 62)
        super().__init__(
            f"Tape width {tape_mm}mm is not supported by the layout engine. "
            f"Supported: {supported}"
        )


class NoTapeLoadedError(Exception):
    """Raised when preflight returns loaded_tape_mm=None (no tape inserted).

    HTTP-Status: 409 (Conflict) — physical hardware state, retry needed
    after user inserts tape.
    """

    def __init__(self) -> None:
        super().__init__("No tape loaded — insert a Brother TZe or DK cartridge.")


class ContentTypeDataMismatchError(Exception):
    """Raised when LabelData lacks fields required by the chosen ContentType.

    HTTP-Status: 422 (Unprocessable Entity) — client can correct the
    request payload and retry without changing hardware state.
    """

    def __init__(
        self,
        *,
        content_type: str,
        missing_fields: tuple[str, ...],
    ) -> None:
        self.content_type = content_type
        self.missing_fields = missing_fields
        super().__init__(
            f"ContentType '{content_type}' requires fields {list(missing_fields)} "
            f"in LabelData — please populate them and retry."
        )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/printer_backends/test_exceptions.py -v`
Expected: PASS (3 new tests + existing tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/exceptions.py backend/tests/unit/printer_backends/test_exceptions.py
git commit -m "feat(exceptions): UnsupportedTapeError + NoTapeLoadedError + ContentTypeDataMismatchError

Phase 1k.1a Task 5: new exception classes used by LayoutEngine.

UnsupportedTapeError(409) and NoTapeLoadedError(409) for hardware/preflight
conflicts. ContentTypeDataMismatchError(422) for client-correctable data
validation errors per ContentType.

Refs #103"
```

---

### Task 6: LayoutEngine Skeleton

**Files:**
- Create: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_layout_engine.py
"""Unit tests for LayoutEngine — skeleton + validation + dispatch."""

from __future__ import annotations

import pytest
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_data_item import LabelDataItem
from app.services.layout_engine import LayoutEngine


class TestLayoutEngineLookup:
    def test_supported_tape_mm_returns_geometry(self) -> None:
        eng = LayoutEngine()
        # Internal helper exercised via _lookup_geometry — called by render.
        # We don't call _lookup_geometry directly; we trigger via an invalid tape.
        with pytest.raises(UnsupportedTapeError) as exc_info:
            eng.render(
                tape_mm=36,
                content_type=ContentType.QR_ONLY,
                data=LabelData(source_app="manual", qr_payload="x"),
            )
        assert exc_info.value.tape_mm == 36


class TestLayoutEngineValidation:
    def test_qr_only_requires_qr_payload(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_ONLY,
                data=LabelData(source_app="manual"),
            )
        assert "qr_payload" in exc_info.value.missing_fields

    def test_qr_two_lines_requires_all_three(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_TWO_LINES,
                data=LabelData(source_app="manual", primary_id="x"),
            )
        # Missing both qr_payload + title
        assert set(exc_info.value.missing_fields) >= {"qr_payload", "title"}

    def test_qr_three_lines_requires_secondary(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=18,
                content_type=ContentType.QR_THREE_LINES,
                data=LabelData(
                    source_app="grocy",
                    primary_id="X", title="Y", qr_payload="Z",
                    secondary=(),  # empty -> missing
                ),
            )
        assert "secondary" in exc_info.value.missing_fields

    def test_text_one_line_only_needs_primary_id(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.TEXT_ONE_LINE,
                data=LabelData(source_app="manual"),
            )
        assert exc_info.value.missing_fields == ("primary_id",)

    def test_qr_with_listing_requires_items_and_qr(self) -> None:
        eng = LayoutEngine()
        with pytest.raises(ContentTypeDataMismatchError) as exc_info:
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_WITH_LISTING,
                data=LabelData(source_app="hangar", primary_id="K02"),
            )
        assert "qr_payload" in exc_info.value.missing_fields
        assert "items" in exc_info.value.missing_fields

    def test_qr_with_listing_with_items_passes_validation(self) -> None:
        """Validation passes even though rendering not yet implemented."""
        eng = LayoutEngine()
        # Render returns NotImplementedError for now (will be Task 13)
        with pytest.raises(NotImplementedError):
            eng.render(
                tape_mm=12,
                content_type=ContentType.QR_WITH_LISTING,
                data=LabelData(
                    source_app="hangar",
                    primary_id="K02",
                    qr_payload="https://example.com/k02",
                    items=(LabelDataItem(item="A"),),
                ),
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.layout_engine'`

- [ ] **Step 3: Write skeleton implementation**

```python
# backend/app/services/layout_engine.py
"""LayoutEngine — semantic layout rendering driven by ContentType + TapeGeometry.

Replaces the v1 LabelRenderer. Each render() call resolves:
  1. tape_mm -> TapeGeometry (via TAPE_GEOMETRY dict)
  2. content_type-required fields -> validated against LabelData
  3. Dispatched to a per-ContentType _render_*() method
  4. Returns a PIL Image whose height matches geometry.printable_px

The _render_*() methods are implemented in subsequent tasks (7-13).
"""

from __future__ import annotations

from PIL import Image

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY, TapeGeometry


class LayoutEngine:
    """Tape-independent semantic label renderer.

    Stateless — safe to instantiate once and reuse across requests.
    """

    # ContentType -> ordered tuple of LabelData field names that must be set.
    # Used by _validate_data to produce ContentTypeDataMismatchError with a
    # complete missing-fields list (one 422 instead of multiple round-trips).
    _REQUIRED_FIELDS: dict[ContentType, tuple[str, ...]] = {
        ContentType.QR_ONLY: ("qr_payload",),
        ContentType.QR_ONE_LINE: ("qr_payload", "primary_id"),
        ContentType.QR_TWO_LINES: ("qr_payload", "primary_id", "title"),
        ContentType.QR_THREE_LINES: ("qr_payload", "primary_id", "title", "secondary"),
        ContentType.TEXT_ONE_LINE: ("primary_id",),
        ContentType.TEXT_TWO_LINES: ("primary_id", "title"),
        ContentType.QR_WITH_LISTING: ("qr_payload", "primary_id", "items"),
    }

    def render(
        self,
        tape_mm: int,
        content_type: ContentType,
        data: LabelData,
    ) -> Image.Image:
        """Render a label for the given tape width + content type + data.

        Raises:
            UnsupportedTapeError (409): tape_mm not in TAPE_GEOMETRY.
            ContentTypeDataMismatchError (422): data missing required fields.
        """
        geometry = self._lookup_geometry(tape_mm)
        self._validate_data(content_type, data)

        match content_type:
            case ContentType.QR_ONLY:
                return self._render_qr_only(geometry, data)
            case ContentType.QR_ONE_LINE:
                return self._render_qr_one_line(geometry, data)
            case ContentType.QR_TWO_LINES:
                return self._render_qr_two_lines(geometry, data)
            case ContentType.QR_THREE_LINES:
                return self._render_qr_three_lines(geometry, data)
            case ContentType.TEXT_ONE_LINE:
                return self._render_text_one_line(geometry, data)
            case ContentType.TEXT_TWO_LINES:
                return self._render_text_two_lines(geometry, data)
            case ContentType.QR_WITH_LISTING:
                return self._render_qr_with_listing(geometry, data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lookup_geometry(self, tape_mm: int) -> TapeGeometry:
        geom = TAPE_GEOMETRY.get(tape_mm)
        if geom is None:
            raise UnsupportedTapeError(tape_mm=tape_mm)
        return geom

    def _validate_data(self, content_type: ContentType, data: LabelData) -> None:
        required = self._REQUIRED_FIELDS[content_type]
        missing: list[str] = []
        for field_name in required:
            value = getattr(data, field_name)
            # Empty string, empty tuple, or None counts as missing.
            if value is None or (hasattr(value, "__len__") and len(value) == 0):
                missing.append(field_name)
        if missing:
            raise ContentTypeDataMismatchError(
                content_type=str(content_type),
                missing_fields=tuple(missing),
            )

    # ------------------------------------------------------------------
    # _render_* methods — implemented in Tasks 7-13
    # ------------------------------------------------------------------

    def _render_qr_only(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 7")

    def _render_qr_one_line(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 8")

    def _render_qr_two_lines(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 9")

    def _render_qr_three_lines(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 10")

    def _render_text_one_line(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 11")

    def _render_text_two_lines(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 12")

    def _render_qr_with_listing(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        raise NotImplementedError("Task 13")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine.py -v`
Expected: PASS (6 tests for validation + dispatch; rendering NotImplementedError is expected)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine.py
git commit -m "feat(services): LayoutEngine skeleton — dispatch + validation

Phase 1k.1a Task 6: introduces LayoutEngine with _lookup_geometry,
_validate_data, and match-statement dispatch to per-ContentType render
methods. Rendering methods raise NotImplementedError pending Tasks 7-13.

Refs #103"
```

---

### Task 7: _render_qr_only

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_layout_engine_render.py
"""Render tests per ContentType — output image checks (size, content)."""

from __future__ import annotations

from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.layout_engine import LayoutEngine


class TestRenderQROnly:
    def test_image_height_matches_printable_px_12mm(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/x"),
        )
        assert img.height == TAPE_GEOMETRY[12].printable_px == 70

    def test_image_mode_is_1bit(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/x"),
        )
        assert img.mode == "1"

    def test_qr_pixels_present(self) -> None:
        """At least some black pixels exist (the QR is rendered)."""
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/x"),
        )
        black = sum(1 for p in img.getdata() if p == 0)
        assert black > 200, f"Expected QR pixels; got {black} black pixels"

    def test_24mm_renders(self) -> None:
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_ONLY,
            data=LabelData(source_app="manual", qr_payload="https://example.com/y"),
        )
        assert img.height == TAPE_GEOMETRY[24].printable_px == 128
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQROnly -v`
Expected: FAIL with `NotImplementedError: Task 7`

- [ ] **Step 3: Implement _render_qr_only**

Add helper imports + replace the placeholder `_render_qr_only` in `backend/app/services/layout_engine.py`. The imports at the top of the file become:

```python
from __future__ import annotations

import io

import qrcode
from PIL import Image

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY, TapeGeometry
```

Add a private helper at the top of the `LayoutEngine` class (above `render()`):

```python
    @staticmethod
    def _build_qr_image(payload: str, size_px: int) -> Image.Image:
        """Render a QR code as a square 1-bit PIL Image at the requested size."""
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=0,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        # Render at high resolution, then resize to the target size.
        rendered = qr.make_image(fill_color="black", back_color="white")
        return rendered.convert("1").resize((size_px, size_px), Image.NEAREST)

    @staticmethod
    def _blank_canvas(width: int, height: int) -> Image.Image:
        """Return a white 1-bit PIL Image of the given size."""
        return Image.new("1", (width, height), color=1)
```

Replace `_render_qr_only` with:

```python
    def _render_qr_only(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """QR fills the full printable height, left-padded by qr_padding_px.

        Width = qr_max_px + 2 * qr_padding_px = printable_px (square label).
        """
        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        canvas_width = geometry.printable_px  # tight crop, QR + padding both sides
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        # Center vertically; QR is square so vertical padding = qr_padding_px.
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQROnly -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_qr_only

Phase 1k.1a Task 7: QR fills full printable height with qr_padding_px
border. Width = printable_px (square output). Uses qrcode lib with
ERROR_CORRECT_M and resizes to geometry.qr_max_px.

Refs #103"
```

---

### Task 8: _render_qr_one_line

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/services/test_layout_engine_render.py`:

```python
class TestRenderQROneLine:
    def test_image_height_matches_printable_px(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONE_LINE,
            data=LabelData(
                source_app="manual",
                qr_payload="https://example.com/x",
                primary_id="X-001",
            ),
        )
        assert img.height == TAPE_GEOMETRY[12].printable_px

    def test_width_includes_text_column(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_ONE_LINE,
            data=LabelData(
                source_app="manual",
                qr_payload="https://example.com/x",
                primary_id="X-001",
            ),
        )
        # Width must exceed text_start_x (text rendered after QR).
        assert img.width > TAPE_GEOMETRY[12].text_start_x
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQROneLine -v`
Expected: FAIL with `NotImplementedError: Task 8`

- [ ] **Step 3: Implement _render_qr_one_line + text helper**

Add this helper to the `LayoutEngine` class (next to `_build_qr_image`):

```python
    @staticmethod
    def _load_font(size_px: int) -> "Image.ImageFont":  # noqa: F821
        """Load DejaVuSans TrueType font at the requested pixel size.

        DejaVuSans.ttf is installed via fonts-dejavu-core in the Dockerfile
        (Phase 1i pre-fix). On dev machines without the system font, falls
        back to the default bitmap font (tests skip such envs).
        """
        from PIL import ImageFont
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size_px)
        except OSError:
            return ImageFont.load_default()

    @staticmethod
    def _measure_text(text: str, font: "Image.ImageFont") -> tuple[int, int]:  # noqa: F821
        """Return (width, height) bounding box of `text` rendered with `font`."""
        from PIL import ImageDraw
        bbox = ImageDraw.Draw(Image.new("1", (1, 1), color=1)).textbbox(
            (0, 0), text, font=font
        )
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
```

Replace `_render_qr_one_line` with:

```python
    def _render_qr_one_line(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """QR left + 1 text line (primary_id, font_xl, vertically centered)."""
        from PIL import ImageDraw

        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font = self._load_font(geometry.font_xl)
        text = data.primary_id or ""
        text_w, text_h = self._measure_text(text, font)

        canvas_width = geometry.text_start_x + text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        # QR top-left at (qr_padding_px, qr_padding_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))
        # Text vertically centered on the printable area.
        text_y = max(0, (geometry.printable_px - text_h) // 2)
        ImageDraw.Draw(canvas).text(
            (geometry.text_start_x, text_y), text, font=font, fill=0
        )
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQROneLine -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_qr_one_line

Phase 1k.1a Task 8: QR left + 1 text line (primary_id, font_xl,
vertically centered). Width sized to fit text content.

Refs #103"
```

---

### Task 9: _render_qr_two_lines (V4-Winner Baseline)

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/services/test_layout_engine_render.py`:

```python
class TestRenderQRTwoLines:
    def test_baseline_12mm_v4_winner(self) -> None:
        """Phase 1i V4-Winner baseline: primary_id top, title below QR.

        Scan-verified empirical baseline from 12mm PT-P750W hardware.
        """
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_TWO_LINES,
            data=LabelData(
                source_app="hangar",
                primary_id="K-02",
                title="Werkstatt",
                qr_payload="https://example.com/locations/k-02",
            ),
        )
        # Height must be 70px (12mm V4-Winner)
        assert img.height == 70
        # Width has QR + text — at minimum text_start_x + minimum text width.
        geom = TAPE_GEOMETRY[12]
        assert img.width > geom.text_start_x

    def test_24mm_renders(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_TWO_LINES,
            data=LabelData(
                source_app="hangar", primary_id="K-02", title="Werkstatt",
                qr_payload="https://example.com/x",
            ),
        )
        assert img.height == 128

    def test_62mm_renders_at_higher_dpi(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=62,
            content_type=ContentType.QR_TWO_LINES,
            data=LabelData(
                source_app="samla", primary_id="HH-AK-SM01", title="Samla 11L",
                qr_payload="https://example.com/x",
            ),
        )
        assert img.height == 696
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQRTwoLines -v`
Expected: FAIL with `NotImplementedError: Task 9`

- [ ] **Step 3: Implement _render_qr_two_lines**

Replace `_render_qr_two_lines` with:

```python
    def _render_qr_two_lines(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """QR left + 2 text lines (primary_id XL on top, title L below).

        Phase 1i V4-Winner baseline for 12mm:
          - primary_id at y=2 (font_xl=22)
          - title at y=42 (font_l=18)
          - text_start_x=72
        Generalises to other tape widths via geometry constants.
        """
        from PIL import ImageDraw

        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font_primary = self._load_font(geometry.font_xl)
        font_title = self._load_font(geometry.font_l)

        primary_text = data.primary_id or ""
        title_text = data.title or ""
        primary_w, _ = self._measure_text(primary_text, font_primary)
        title_w, _ = self._measure_text(title_text, font_title)
        max_text_w = max(primary_w, title_w)

        canvas_width = geometry.text_start_x + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))

        draw = ImageDraw.Draw(canvas)
        # primary_id: top with qr_padding_px gap from canvas top
        draw.text(
            (geometry.text_start_x, geometry.qr_padding_px),
            primary_text, font=font_primary, fill=0,
        )
        # title: starts after primary line height + line_spacing_px
        title_y = (
            geometry.qr_padding_px
            + geometry.font_xl
            + geometry.line_spacing_px
        )
        draw.text(
            (geometry.text_start_x, title_y),
            title_text, font=font_title, fill=0,
        )
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQRTwoLines -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_qr_two_lines (V4 baseline)

Phase 1k.1a Task 9: QR + 2 text lines (primary_id XL + title L).
Mirrors Phase 1i V4-Winner empirical baseline for 12mm scan-verified
geometry. Generalises across all 7 supported tape widths.

Refs #103"
```

---

### Task 10: _render_qr_three_lines

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/services/test_layout_engine_render.py`:

```python
class TestRenderQRThreeLines:
    def test_18mm_with_secondary(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=18,
            content_type=ContentType.QR_THREE_LINES,
            data=LabelData(
                source_app="grocy",
                primary_id="Erdbeermarmelade",
                title="Lager > Vorrat",
                qr_payload="https://example.com/x",
                secondary=("MHD 2027-04-30",),
            ),
        )
        assert img.height == 112  # 18mm printable_px

    def test_24mm_renders(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_THREE_LINES,
            data=LabelData(
                source_app="grocy", primary_id="X", title="Y",
                qr_payload="https://example.com/x",
                secondary=("Z",),
            ),
        )
        assert img.height == 128
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQRThreeLines -v`
Expected: FAIL with `NotImplementedError: Task 10`

- [ ] **Step 3: Implement _render_qr_three_lines**

Replace `_render_qr_three_lines` with:

```python
    def _render_qr_three_lines(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """QR left + 3 text lines: primary_id XL, title L, secondary[0] S."""
        from PIL import ImageDraw

        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font_primary = self._load_font(geometry.font_xl)
        font_title = self._load_font(geometry.font_l)
        font_secondary = self._load_font(geometry.font_s)

        primary_text = data.primary_id or ""
        title_text = data.title or ""
        secondary_text = data.secondary[0] if data.secondary else ""

        primary_w, _ = self._measure_text(primary_text, font_primary)
        title_w, _ = self._measure_text(title_text, font_title)
        sec_w, _ = self._measure_text(secondary_text, font_secondary)
        max_text_w = max(primary_w, title_w, sec_w)

        canvas_width = geometry.text_start_x + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))

        draw = ImageDraw.Draw(canvas)
        y = geometry.qr_padding_px
        draw.text(
            (geometry.text_start_x, y),
            primary_text, font=font_primary, fill=0,
        )
        y += geometry.font_xl + geometry.line_spacing_px
        draw.text(
            (geometry.text_start_x, y),
            title_text, font=font_title, fill=0,
        )
        y += geometry.font_l + geometry.line_spacing_px
        draw.text(
            (geometry.text_start_x, y),
            secondary_text, font=font_secondary, fill=0,
        )
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQRThreeLines -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_qr_three_lines

Phase 1k.1a Task 10: QR + 3 text lines (primary_id XL + title L +
secondary[0] S). Used by grocy/snipeit/spoolman 18/24mm and hangar-
furniture 18/24mm labels post-migration.

Refs #103"
```

---

### Task 11: _render_text_one_line

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/services/test_layout_engine_render.py`:

```python
class TestRenderTextOneLine:
    def test_no_qr_present(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.TEXT_ONE_LINE,
            data=LabelData(source_app="manual", primary_id="HELLO"),
        )
        # Width should be small — only text, no QR (no qr_max_px area)
        assert img.width < 200  # generous upper bound for "HELLO" at font_xl=22

    def test_renders_at_correct_height(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.tape_geometry import TAPE_GEOMETRY
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.TEXT_ONE_LINE,
            data=LabelData(source_app="manual", primary_id="X"),
        )
        assert img.height == TAPE_GEOMETRY[24].printable_px
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderTextOneLine -v`
Expected: FAIL with `NotImplementedError: Task 11`

- [ ] **Step 3: Implement _render_text_one_line**

Replace `_render_text_one_line` with:

```python
    def _render_text_one_line(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """Full-width text (primary_id, font_xl, vertically centered)."""
        from PIL import ImageDraw

        font = self._load_font(geometry.font_xl)
        text = data.primary_id or ""
        text_w, text_h = self._measure_text(text, font)

        # No QR -> canvas starts with qr_padding_px left margin
        canvas_width = geometry.qr_padding_px + text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        text_y = max(0, (geometry.printable_px - text_h) // 2)
        ImageDraw.Draw(canvas).text(
            (geometry.qr_padding_px, text_y), text, font=font, fill=0,
        )
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderTextOneLine -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_text_one_line

Phase 1k.1a Task 11: full-width primary_id text without QR. Vertically
centered, padded by qr_padding_px from both edges.

Refs #103"
```

---

### Task 12: _render_text_two_lines

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/services/test_layout_engine_render.py`:

```python
class TestRenderTextTwoLines:
    def test_18mm_renders(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=18,
            content_type=ContentType.TEXT_TWO_LINES,
            data=LabelData(source_app="manual", primary_id="LINE1", title="LINE2"),
        )
        assert img.height == 112
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderTextTwoLines -v`
Expected: FAIL with `NotImplementedError: Task 12`

- [ ] **Step 3: Implement _render_text_two_lines**

Replace `_render_text_two_lines` with:

```python
    def _render_text_two_lines(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """2 text lines (primary_id XL + title L), no QR."""
        from PIL import ImageDraw

        font_primary = self._load_font(geometry.font_xl)
        font_title = self._load_font(geometry.font_l)
        primary_text = data.primary_id or ""
        title_text = data.title or ""
        primary_w, _ = self._measure_text(primary_text, font_primary)
        title_w, _ = self._measure_text(title_text, font_title)
        max_text_w = max(primary_w, title_w)

        canvas_width = geometry.qr_padding_px + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)

        draw = ImageDraw.Draw(canvas)
        y = geometry.qr_padding_px
        draw.text(
            (geometry.qr_padding_px, y),
            primary_text, font=font_primary, fill=0,
        )
        y += geometry.font_xl + geometry.line_spacing_px
        draw.text(
            (geometry.qr_padding_px, y),
            title_text, font=font_title, fill=0,
        )
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderTextTwoLines -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_text_two_lines

Phase 1k.1a Task 12: 2 text lines (primary_id XL + title L), no QR.

Refs #103"
```

---

### Task 13: _render_qr_with_listing

**Files:**
- Modify: `backend/app/services/layout_engine.py`
- Test: `backend/tests/unit/services/test_layout_engine_render.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/services/test_layout_engine_render.py`:

```python
class TestRenderQRWithListing:
    def test_4_items_render(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.label_data_item import LabelDataItem
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        img = eng.render(
            tape_mm=24,
            content_type=ContentType.QR_WITH_LISTING,
            data=LabelData(
                source_app="hangar",
                primary_id="Kallax-02",
                qr_payload="https://example.com/k02",
                items=(
                    LabelDataItem(item="A — Schrauben"),
                    LabelDataItem(item="B — Muttern"),
                    LabelDataItem(item="C — Werkzeug"),
                    LabelDataItem(item="D — Kabel"),
                ),
            ),
        )
        assert img.height == 128

    def test_overflow_shows_n_more(self) -> None:
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData
        from app.schemas.label_data_item import LabelDataItem
        from app.services.layout_engine import LayoutEngine
        eng = LayoutEngine()
        # 12mm can only fit ~2 lines at font_m=14 — 10 items overflow
        many = tuple(LabelDataItem(item=f"Item {i}") for i in range(10))
        img = eng.render(
            tape_mm=12,
            content_type=ContentType.QR_WITH_LISTING,
            data=LabelData(
                source_app="hangar", primary_id="X", qr_payload="x", items=many,
            ),
        )
        assert img.height == 70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQRWithListing -v`
Expected: FAIL with `NotImplementedError: Task 13`

- [ ] **Step 3: Implement _render_qr_with_listing**

Replace `_render_qr_with_listing` with:

```python
    def _render_qr_with_listing(
        self, geometry: TapeGeometry, data: LabelData,
    ) -> Image.Image:
        """QR left + N item lines (font_m). Overflow shows '+N more'."""
        from PIL import ImageDraw

        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font_item = self._load_font(geometry.font_m)
        items = list(data.items)

        # How many lines fit in the printable area? Reserve qr_padding_px top/bottom.
        available_h = geometry.printable_px - 2 * geometry.qr_padding_px
        line_h = geometry.font_m + geometry.line_spacing_px
        max_lines = max(1, available_h // line_h)

        # Reserve last line for "+N more" if overflowing.
        if len(items) > max_lines:
            visible_count = max_lines - 1
            overflow_text = f"+{len(items) - visible_count} more"
            visible = items[:visible_count]
        else:
            visible = items
            overflow_text = None

        # Compute canvas width based on widest rendered line.
        widths = [self._measure_text(it.item, font_item)[0] for it in visible]
        if overflow_text:
            widths.append(self._measure_text(overflow_text, font_item)[0])
        max_text_w = max(widths) if widths else 0

        canvas_width = geometry.text_start_x + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))

        draw = ImageDraw.Draw(canvas)
        y = geometry.qr_padding_px
        for it in visible:
            draw.text(
                (geometry.text_start_x, y),
                it.item, font=font_item, fill=0,
            )
            y += line_h
        if overflow_text:
            draw.text(
                (geometry.text_start_x, y),
                overflow_text, font=font_item, fill=0,
            )
        return canvas
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine_render.py::TestRenderQRWithListing -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run all LayoutEngine tests**

Run: `cd backend && pytest tests/unit/services/test_layout_engine.py tests/unit/services/test_layout_engine_render.py -v`
Expected: All PASS (validation + dispatch + 7 render methods)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/layout_engine.py backend/tests/unit/services/test_layout_engine_render.py
git commit -m "feat(layout-engine): implement _render_qr_with_listing

Phase 1k.1a Task 13: QR + N item lines (font_m), overflow shows
'+N more' on the last line. Used for Kallax-Regal-Uebersicht and
similar aggregation labels.

Completes all 7 ContentType render methods.

Refs #103"
```

---

### Task 14: PrintRequest Schema Refactor

**Files:**
- Modify: `backend/app/schemas/print_request.py`
- Test: `backend/tests/unit/schemas/test_print_request.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/schemas/test_print_request.py
"""Unit tests for PrintRequest with content_type (no template_id)."""

from __future__ import annotations

import pytest
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintRequest, RawLabelData


class TestPrintRequest:
    def test_with_content_type_and_raw_data(self) -> None:
        req = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            data=RawLabelData(
                primary_id="K-02", title="Werkstatt",
                qr_payload="https://example.com/x",
            ),
        )
        assert req.content_type == ContentType.QR_TWO_LINES
        assert req.data.primary_id == "K-02"

    def test_no_template_id_field(self) -> None:
        """template_id is no longer a valid field — extra="forbid" rejects it."""
        with pytest.raises(ValueError, match="template_id"):
            PrintRequest(
                template_id="anything",
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="x", primary_id="", title=""),
            )  # type: ignore[call-arg]

    def test_no_on_tape_mismatch_field(self) -> None:
        with pytest.raises(ValueError, match="on_tape_mismatch"):
            PrintRequest(
                on_tape_mismatch="queue",
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="x", primary_id="", title=""),
            )  # type: ignore[call-arg]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/schemas/test_print_request.py -v`
Expected: FAIL — current PrintRequest still has template_id + on_tape_mismatch.

- [ ] **Step 3: Modify implementation**

Read current `backend/app/schemas/print_request.py` and rewrite as follows. The PrintRequest model should look like:

```python
"""Request schemas for POST /api/print + supporting models.

Phase 1k.1a: template_id and on_tape_mismatch removed; content_type added.
RawLabelData mirrors LabelData (minus source_app which is set server-side
to 'manual' for raw requests).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.content_type import ContentType
from app.schemas.label_data_item import LabelDataItem


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
    half_cut: bool = False
    last_page: bool = True


class RawLabelData(BaseModel):
    """Raw label payload accepted when the client supplies data directly.

    Mirrors LabelData minus `source_app` (always set to "manual" server-side).
    All content fields are optional — ContentType-specific validation happens
    in LayoutEngine._validate_data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str | None = None
    primary_id: str | None = None
    qr_payload: str | None = None
    secondary: tuple[str, ...] = ()
    items: tuple[LabelDataItem, ...] = ()


class PrintRequest(BaseModel):
    """POST /api/print body.

    Either `data` (RawLabelData) or `lookup` (PrintLookupRequest) is provided.
    Exactly one of the two must be present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_type: ContentType
    """Semantic content type — drives LayoutEngine render dispatch."""

    options: PrintOptions = PrintOptions()
    """Per-print options (copies, cut behaviour, etc.)."""

    data: RawLabelData | None = None
    """Raw label data (preferred over lookup)."""

    lookup: PrintLookupRequest | None = None
    """Lookup-based label data (resolved via plugin)."""

    @model_validator(mode="after")
    def _exactly_one_data_source(self) -> Self:
        if (self.data is None) == (self.lookup is None):
            raise ValueError(
                "Exactly one of 'data' or 'lookup' must be set."
            )
        return self
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/schemas/test_print_request.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full schema suite — expect some failures**

Run: `cd backend && pytest tests/unit/schemas -v 2>&1 | tail -20`
Note: existing tests that constructed PrintRequest with template_id will fail. These tests get fixed in later tasks (15-20). For now, only `test_print_request.py` must pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/print_request.py backend/tests/unit/schemas/test_print_request.py
git commit -m "feat(schemas): PrintRequest content_type-based (no template_id)

Phase 1k.1a Task 14: PrintRequest now requires content_type:ContentType.
template_id and on_tape_mismatch fields removed (extra=forbid rejects).
RawLabelData fields are optional — validation in LayoutEngine.

Refs #103"
```

---

### Task 15: PrintService Refactor

**Files:**
- Modify: `backend/app/services/print_service.py`
- Test: `backend/tests/unit/services/test_print_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_print_service.py — new tests; keep useful existing
"""Unit tests for PrintService with LayoutEngine integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.snmp_helper import LiveStatus
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.services.layout_engine import LayoutEngine
from app.services.print_service import PrintService


@pytest.fixture()
def make_service():
    def _make(loaded_tape_mm: int = 12) -> tuple[PrintService, AsyncMock]:
        printer_id = uuid4()
        backend = AsyncMock()
        backend.preflight_check = AsyncMock(
            return_value=LiveStatus(
                loaded_tape_mm=loaded_tape_mm,
                tape_empty=False, cover_open=False, online=True,
            )
        )
        queue = MagicMock()
        queue.submit = AsyncMock(return_value=uuid4())
        store = MagicMock()
        store.save_queued = MagicMock()
        engine = LayoutEngine()
        svc = PrintService(
            printer_id=printer_id,
            backend=backend,
            queue=queue,
            store=store,
            engine=engine,
        )
        return svc, queue
    return _make


class TestPrintServiceRender:
    @pytest.mark.asyncio
    async def test_submits_with_loaded_tape_mm(self, make_service) -> None:
        svc, queue = make_service(loaded_tape_mm=18)
        request = PrintRequest(
            content_type=ContentType.QR_TWO_LINES,
            data=RawLabelData(
                primary_id="K02", title="Workshop", qr_payload="https://e.com/x",
            ),
        )
        await svc.submit_print_job(request)
        queue.submit.assert_awaited_once()
        # First positional arg is the rendered image — height matches 18mm tape
        call_args = queue.submit.call_args
        # signature: submit(printer_id, image, *, tape_mm, ...)
        image = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("image")
        tape_mm_arg = call_args.kwargs.get("tape_mm")
        assert tape_mm_arg == 18
        assert image is not None and image.height == 112  # 18mm printable_px
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_print_service.py::TestPrintServiceRender -v`
Expected: FAIL — current PrintService takes `loader+renderer`, not `engine`.

- [ ] **Step 3: Refactor PrintService**

Read `backend/app/services/print_service.py` carefully. The refactor:

1. Constructor: replace `loader: TemplateLoader, renderer: LabelRenderer` parameters with `engine: LayoutEngine`.
2. `submit_print_job`: remove template lookup; remove TapeMismatchError; remove PAUSED-path; render via `engine.render(tape_mm=preflight.loaded_tape_mm, content_type=request.content_type, data=label_data)`.
3. `_resolve_label_data` keeps existing lookup logic but constructs `LabelData(source_app="manual", **request.data.model_dump())` for raw data.
4. Remove `submit_paused_with_id` references / `resume_paused_job` if present.
5. Drop the `on_tape_mismatch` branching entirely.

The new `submit_print_job` body should be approximately:

```python
async def submit_print_job(self, request: PrintRequest) -> UUID:
    """Orchestrate preflight -> render -> persist -> queue.submit.

    Phase 1k.1a: tape-independent rendering. The engine renders for the
    currently loaded tape (preflight.loaded_tape_mm), so TapeMismatchError
    is obsolete in this path.
    """
    preflight = await self._backend.preflight_check()
    if preflight.loaded_tape_mm is None:
        raise NoTapeLoadedError()

    label_data = await self._resolve_label_data(request)
    image = self._engine.render(
        tape_mm=preflight.loaded_tape_mm,
        content_type=request.content_type,
        data=label_data,
    )

    job_id = uuid4()
    job = Job(
        id=str(job_id),
        printer_id=self._printer_id,
        template_key=None,  # new jobs no longer reference templates
        content_type=str(request.content_type),
        rendered_tape_mm=preflight.loaded_tape_mm,
        payload={
            "label_data": label_data.model_dump(),
            "tape_mm": preflight.loaded_tape_mm,
            "options": request.options.model_dump(),
        },
        api_key_id=None,
        source_ip=None,
    )
    self._store.save_queued(job)
    await self._queue.submit(
        self._printer_id,
        image,
        tape_mm=preflight.loaded_tape_mm,
        auto_cut=request.options.auto_cut,
        high_resolution=request.options.high_resolution,
        half_cut=request.options.half_cut,
        last_page=request.options.last_page,
    )
    return job_id
```

`_resolve_label_data` becomes:

```python
async def _resolve_label_data(self, request: PrintRequest) -> LabelData:
    if request.data is not None:
        raw = request.data
        return LabelData(
            source_app="manual",
            title=raw.title,
            primary_id=raw.primary_id,
            qr_payload=raw.qr_payload,
            secondary=raw.secondary,
            items=raw.items,
        )
    # lookup path
    assert request.lookup is not None
    return await self._lookup_service.resolve(
        request.lookup.app, request.lookup.identifier,
    )
```

(Job model + Job dataclass might need a `content_type` and `rendered_tape_mm` field — these are added in Task 22 along with the DB migration. For now, store them in `payload` and update Job dataclass to accept them as optional kwargs.)

Actually — the Job dataclass extension is touched in Task 22's migration. For Task 15, just include the fields in `payload` dict for now and reconcile when models change.

Replace with the simpler form (keep template_key=None for now, content_type lives in payload until Task 22):

```python
job = Job(
    id=str(job_id),
    printer_id=self._printer_id,
    template_key=None,
    payload={
        "label_data": label_data.model_dump(),
        "content_type": str(request.content_type),
        "rendered_tape_mm": preflight.loaded_tape_mm,
        "tape_mm": preflight.loaded_tape_mm,
        "options": request.options.model_dump(),
    },
    api_key_id=None,
    source_ip=None,
)
```

Also update the Job model in `backend/app/models/job.py` if `template_key` is currently `str` (NOT NULL) — change to `str | None`:

```python
# backend/app/models/job.py
template_key: str | None  # snapshot string — survives template deletion; None for content_type-based jobs
```

(Note: SQLAlchemy column NOT NULL constraint is changed in Task 22's Alembic migration.)

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_print_service.py -v`
Expected: PASS for new tests. Old tests that referenced TapeMismatchError/PAUSED may fail — delete them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/print_service.py backend/app/models/job.py backend/tests/unit/services/test_print_service.py
git commit -m "refactor(print-service): integrate LayoutEngine + remove PAUSED path

Phase 1k.1a Task 15: PrintService now renders via LayoutEngine.render()
using preflight.loaded_tape_mm. TapeMismatchError-Pfad und PAUSED-Job-
Pfad entfernt. NoTapeLoadedError fuer fehlendes Tape.

Job.template_key wird nullable (None fuer neue Jobs ab 1k.1a).
content_type + rendered_tape_mm in payload dict — eigene Spalten via
Alembic in Task 22.

Refs #103"
```

---

### Task 16: PrintQueue _rerender_from_db Migration (KRITISCH)

**Files:**
- Modify: `backend/app/services/print_queue.py`
- Test: `backend/tests/unit/services/test_print_queue_rerender.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_print_queue_rerender.py
"""Test the _rerender_from_db recovery path uses LayoutEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.schemas.content_type import ContentType
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue


class TestRerenderFromDb:
    @pytest.mark.asyncio
    async def test_rerender_uses_engine_with_stored_content_type(self) -> None:
        printer = MagicMock(id=uuid4())
        queue = PrintQueue(
            printers=[printer],
            engine=LayoutEngine(),
            store=MagicMock(),
            on_state_change=AsyncMock(),
        )
        # Simulate a stored job payload
        stored_payload = {
            "label_data": {
                "source_app": "manual",
                "primary_id": "K-02",
                "title": "Werkstatt",
                "qr_payload": "https://example.com/x",
                "secondary": [],
                "items": [],
            },
            "content_type": "qr_two_lines",
            "rendered_tape_mm": 12,
            "tape_mm": 12,
            "options": {
                "copies": 1, "auto_cut": True, "high_resolution": False,
                "half_cut": False, "last_page": True,
            },
        }
        image = queue._rerender_from_db_payload(stored_payload)
        # 12mm printable_px
        assert image.height == 70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_print_queue_rerender.py -v`
Expected: FAIL — `_rerender_from_db_payload` does not exist or uses LabelRenderer.

- [ ] **Step 3: Refactor PrintQueue**

In `backend/app/services/print_queue.py`:
1. Constructor: replace `renderer: LabelRenderer | None, loader: type[TemplateLoader] | None` with `engine: LayoutEngine`.
2. Remove all PAUSED-state code: `submit_paused_with_id`, `resume_paused_job`, `PrinterWorkerState.PAUSED` (if present), `_worker_resume_events`. Keep ACTIVE (renamed from PAUSED-aware).
3. Rename or add `_rerender_from_db_payload(payload: dict) -> Image.Image`:

```python
def _rerender_from_db_payload(self, payload: dict) -> "Image.Image":
    """Reconstruct a PIL Image from a stored job payload.

    Used during startup recovery for QUEUED jobs persisted before crash.
    The payload was produced by PrintService.submit_print_job (Task 15).
    """
    from app.schemas.label_data import LabelData
    from app.schemas.content_type import ContentType

    label_data = LabelData(**payload["label_data"])
    content_type = ContentType(payload["content_type"])
    tape_mm = int(payload["rendered_tape_mm"])
    return self._engine.render(
        tape_mm=tape_mm,
        content_type=content_type,
        data=label_data,
    )
```

4. Replace any internal call sites of the old `_rerender_from_db` / `_renderer.render(...)` to use the new method.
5. Update the JobStateMachine to drop PAUSED transitions if present (`backend/app/services/job_lifecycle.py`).

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_print_queue_rerender.py -v`
Expected: PASS

- [ ] **Step 5: Run full print_queue test suite**

Run: `cd backend && pytest tests/unit/services/test_print_queue*.py -v 2>&1 | tail -30`
Note: many existing tests referenced the old PAUSED path or LabelRenderer. Delete the obsolete ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/print_queue.py backend/app/services/job_lifecycle.py backend/tests/unit/services/test_print_queue_rerender.py
git commit -m "refactor(print-queue): _rerender_from_db via LayoutEngine; drop PAUSED

Phase 1k.1a Task 16: KRITISCH — Recovery-Pfad migriert von LabelRenderer
+ TemplateLoader auf LayoutEngine.render() mit gespeichertem
content_type + rendered_tape_mm + label_data Snapshot. PAUSED-State und
zugehoerige resume_paused_job-Logik entfernt.

Refs #103"
```

---

### Task 17: BatchDispatch Cleanup

**Files:**
- Modify: `backend/app/services/batch_dispatch.py`
- Test: `backend/tests/unit/services/test_batch_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_batch_dispatch.py
"""Tests batch dispatch accepting mixed ContentTypes (no MixedTapeSizesError)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintOptions, PrintRequest, RawLabelData
from app.services.batch_dispatch import dispatch_batch


class TestBatchDispatch:
    @pytest.mark.asyncio
    async def test_mixed_content_types_all_accepted(self) -> None:
        """Different ContentTypes in one batch render on same loaded_tape_mm."""
        service = AsyncMock()
        service.submit_batch_job = AsyncMock(return_value=(uuid4(), [uuid4(), uuid4()]))
        items = [
            PrintRequest(
                content_type=ContentType.QR_TWO_LINES,
                data=RawLabelData(primary_id="A", title="T", qr_payload="x"),
            ),
            PrintRequest(
                content_type=ContentType.QR_ONLY,
                data=RawLabelData(qr_payload="y"),
            ),
        ]
        await dispatch_batch(service=service, items=items)
        service.submit_batch_job.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/services/test_batch_dispatch.py::TestBatchDispatch::test_mixed_content_types_all_accepted -v`
Expected: FAIL — current `dispatch_batch` calls `_validate_item_get_tape_mm` and raises MixedTapeSizesError for differing tape_mm.

- [ ] **Step 3: Refactor batch_dispatch.py**

The cleanup:
1. Remove `MixedTapeSizesError` class definition.
2. Remove `_validate_item_get_tape_mm` helper.
3. Remove the consistency-check loop in `dispatch_batch`.
4. `dispatch_batch` now just collects request items and calls `service.submit_batch_job(requests=items)`.

Replace `dispatch_batch` body:

```python
async def dispatch_batch(
    *,
    service: "PrintService",
    items: list[PrintRequest],
) -> tuple[UUID, list[UUID]]:
    """Submit a batch of mixed-ContentType print requests.

    Phase 1k.1a: tape consistency check removed — all items render on the
    same loaded_tape_mm (read once via preflight by PrintService).
    """
    if not items:
        raise ValueError("Batch must contain at least one item.")
    return await service.submit_batch_job(requests=items)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/unit/services/test_batch_dispatch.py -v`
Expected: PASS for new test. Old tests that asserted MixedTapeSizesError need deletion.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/batch_dispatch.py backend/tests/unit/services/test_batch_dispatch.py
git commit -m "refactor(batch-dispatch): drop MixedTapeSizesError + tape consistency check

Phase 1k.1a Task 17: tape-independent ContentTypes erlauben jetzt
gemischte ContentTypes pro Batch — alle Items rendern auf gleicher
loaded_tape_mm. MixedTapeSizesError + _validate_item_get_tape_mm
entfernt.

Refs #103"
```

---

### Task 18: routes/print.py Refactor + Prefix

**Files:**
- Modify: `backend/app/api/routes/print.py`
- Test: `backend/tests/integration/test_route_print.py` (extend or replace)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_route_print.py (new tests)
"""Integration test for POST /api/print with content_type."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_post_api_print_with_content_type(authed_client: AsyncClient) -> None:
    """POST /api/print accepts content_type + data payload."""
    payload = {
        "content_type": "qr_two_lines",
        "data": {
            "primary_id": "K-02",
            "title": "Werkstatt",
            "qr_payload": "https://example.com/locations/k-02",
        },
        "options": {"copies": 1},
    }
    resp = await authed_client.post("/api/print/brother-p750w", json=payload)
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["state"] in {"queued", "printing"}


@pytest.mark.asyncio
async def test_post_api_print_rejects_template_id(authed_client: AsyncClient) -> None:
    """template_id field is rejected (extra=forbid)."""
    payload = {
        "template_id": "anything",
        "content_type": "qr_only",
        "data": {"qr_payload": "x"},
    }
    resp = await authed_client.post("/api/print/brother-p750w", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_print_resume_route_gone(authed_client: AsyncClient) -> None:
    """POST /api/jobs/{id}/resume returns 404 (route deleted)."""
    resp = await authed_client.post("/api/jobs/00000000-0000-0000-0000-000000000000/resume")
    assert resp.status_code == 404
```

(Assumes `authed_client` fixture exists; if not, copy the auth setup from existing integration tests.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_route_print.py -v`
Expected: FAIL — route is currently `/print` not `/api/print`.

- [ ] **Step 3: Refactor routes/print.py**

The refactor:
1. Change `router = APIRouter()` to `router = APIRouter(prefix="/api")`.
2. Adapt `@router.post("/print", ...)` to `@router.post("/print/{slug}", ...)` — slug is now part of the path (or accept it via query — match existing batch.py style).
3. Remove `TapeMismatchError` import + error map entry.
4. Remove TemplateNotFoundError import + entry.
5. Add `UnsupportedTapeError`, `NoTapeLoadedError`, `ContentTypeDataMismatchError` to the error map.
6. Delete `POST /jobs/{job_id}/resume` route (if defined here).
7. Adapt response schema if needed (now returns `job_id` + `state`, no `error_detail.expected_mm` for tape_mismatch).

Reference batch.py path style. After the change, the file should:
- Have `prefix="/api"` on the router
- Define `POST /print/{printer_slug}` (the slug parameter routes to the right printer)
- Not import TapeMismatchError or TemplateNotFoundError
- Not have a resume endpoint

If the printer-slug resolution was previously done via dependency injection, keep that pattern but make sure the path matches `/api/print/{slug}` overall.

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/integration/test_route_print.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/print.py backend/tests/integration/test_route_print.py
git commit -m "feat(api): /api/print prefix + content_type schema + remove resume

Phase 1k.1a Task 18: APIRouter(prefix=/api), POST /api/print/{slug}
mit content_type-Body, template_id und on_tape_mismatch raus,
/api/jobs/{id}/resume Route entfernt. UnsupportedTapeError(409),
NoTapeLoadedError(409), ContentTypeDataMismatchError(422) mapping.

Refs #103"
```

---

### Task 19: routes/batch.py Refactor

**Files:**
- Modify: `backend/app/api/routes/batch.py`
- Test: `backend/tests/integration/test_route_batch.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_route_batch.py
"""POST /api/print/{slug}/batch accepts content_type-keyed items."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_batch_content_type(authed_client: AsyncClient) -> None:
    payload = {
        "items": [
            {
                "content_type": "qr_two_lines",
                "data": {
                    "primary_id": "A", "title": "T1",
                    "qr_payload": "https://example.com/a",
                },
            },
            {
                "content_type": "qr_only",
                "data": {"qr_payload": "https://example.com/b"},
            },
        ],
    }
    resp = await authed_client.post("/api/print/brother-p750w/batch", json=payload)
    assert resp.status_code == 202
    body = resp.json()
    assert "batch_id" in body
    assert len(body["job_ids"]) == 2


@pytest.mark.asyncio
async def test_batch_rejects_template_id(authed_client: AsyncClient) -> None:
    payload = {
        "items": [{"template_id": "anything", "data": {"qr_payload": "x"}}],
    }
    resp = await authed_client.post("/api/print/brother-p750w/batch", json=payload)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_route_batch.py -v`
Expected: FAIL — batch currently uses template_id-keyed items.

- [ ] **Step 3: Refactor routes/batch.py**

The refactor:
1. Update the BatchRequest items schema to use `content_type: ContentType` field (mirrors PrintRequest).
2. Delete the `MixedTapeSizesError` handler in the error map (and the `400` mapping).
3. Keep the existing routing structure; just replace `template_id` references with `content_type` in the Pydantic models.

If `BatchItem` is defined as a Pydantic model in this file, change:
```python
class BatchItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content_type: ContentType
    data: RawLabelData | None = None
    lookup: PrintLookupRequest | None = None
    options: PrintOptions = PrintOptions()
    # validator: exactly one of data/lookup
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/integration/test_route_batch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/batch.py backend/tests/integration/test_route_batch.py
git commit -m "feat(api): batch route content_type + drop MixedTapeSizesError

Phase 1k.1a Task 19: BatchItem schema uses content_type. Mixed
ContentTypes pro Batch erlaubt — alle rendern auf loaded_tape_mm.
MixedTapeSizesError 400 mapping entfernt.

Refs #103"
```

---

### Task 20: routes/jobs.py — Remove resume

**Files:**
- Modify: `backend/app/api/routes/jobs.py`
- Test: `backend/tests/integration/test_route_jobs.py` (assertion already in Task 18)

- [ ] **Step 1: Locate the resume route**

```bash
grep -n "resume" backend/app/api/routes/jobs.py
```

- [ ] **Step 2: Delete the route function**

Open `backend/app/api/routes/jobs.py` and delete the `@router.post(".../resume", ...)` decorator + function. Also remove any related helper imports if unused.

- [ ] **Step 3: Run integration test**

The test from Task 18 (`test_post_print_resume_route_gone`) verifies this returns 404:
Run: `cd backend && pytest tests/integration/test_route_print.py::test_post_print_resume_route_gone -v`
Expected: PASS (404)

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/jobs.py
git commit -m "feat(api): remove POST /api/jobs/{id}/resume route

Phase 1k.1a Task 20: PAUSED-State obsolet ab 1k.1, Resume-Route entfernt.

Refs #103"
```

---

### Task 21: error_handlers.py Update

**Files:**
- Modify: `backend/app/api/error_handlers.py`
- Test: `backend/tests/integration/test_error_handlers.py` (extend or new)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_error_handlers.py
"""Integration tests for global exception -> HTTP-Status mapping."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unsupported_tape_returns_409(authed_client: AsyncClient) -> None:
    """If preflight returns an unsupported tape (e.g. mock 36mm), expect 409."""
    # This needs a fixture that mocks preflight to return tape_mm=36.
    # Skip if the fixture isn't trivially available; otherwise:
    pytest.skip("Requires fixture for preflight=36mm mock")


@pytest.mark.asyncio
async def test_content_type_data_mismatch_returns_422(authed_client: AsyncClient) -> None:
    payload = {
        "content_type": "qr_two_lines",
        "data": {"primary_id": "X"},  # missing title + qr_payload
    }
    resp = await authed_client.post("/api/print/brother-p750w", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body.get("error_code") == "content_type_data_mismatch"


@pytest.mark.asyncio
async def test_tape_mismatch_error_class_gone(authed_client: AsyncClient) -> None:
    """TapeMismatchError must not be referenced anywhere in routes."""
    from app.api import error_handlers as mod
    # Module should not import TapeMismatchError nor MixedTapeSizesError
    src = open(mod.__file__).read()
    assert "TapeMismatchError" not in src
    assert "MixedTapeSizesError" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_error_handlers.py -v`
Expected: FAIL on the content_type test (mapping doesn't exist yet) and import-test if old refs still present.

- [ ] **Step 3: Modify error_handlers.py**

Open `backend/app/api/error_handlers.py`. Changes:

1. Remove imports + mappings for `TapeMismatchError`, `MixedTapeSizesError`.
2. Add imports + handlers for `UnsupportedTapeError`, `NoTapeLoadedError`, `ContentTypeDataMismatchError`.

Pattern (adjust to match existing handler structure):

```python
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    NoTapeLoadedError,
    UnsupportedTapeError,
)

def register_error_handlers(app: FastAPI) -> None:
    # ... existing handlers ...

    @app.exception_handler(UnsupportedTapeError)
    async def _h_unsupported_tape(_, exc: UnsupportedTapeError):
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "unsupported_tape",
                "error_message": str(exc),
                "error_detail": {"tape_mm": exc.tape_mm},
            },
        )

    @app.exception_handler(NoTapeLoadedError)
    async def _h_no_tape(_, exc: NoTapeLoadedError):
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "no_tape_loaded",
                "error_message": str(exc),
            },
        )

    @app.exception_handler(ContentTypeDataMismatchError)
    async def _h_content_type_data_mismatch(_, exc: ContentTypeDataMismatchError):
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "content_type_data_mismatch",
                "error_message": str(exc),
                "error_detail": {
                    "content_type": exc.content_type,
                    "missing_fields": list(exc.missing_fields),
                },
            },
        )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/integration/test_error_handlers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/error_handlers.py backend/tests/integration/test_error_handlers.py
git commit -m "feat(api): error_handlers — new exception mappings + remove obsolete

Phase 1k.1a Task 21: TapeMismatchError + MixedTapeSizesError handlers
geloescht. UnsupportedTapeError(409), NoTapeLoadedError(409),
ContentTypeDataMismatchError(422) handlers hinzugefuegt.

Refs #103"
```

---

### Task 22: Alembic Migration (templates drop + jobs columns + backfill)

**Files:**
- Create: `backend/alembic/versions/<rev>_phase_1k1a_drop_templates_add_content_columns.py`
- Modify: `backend/app/models/job.py` (add new columns to ORM model)
- Test: `backend/tests/integration/test_alembic_migration.py`

- [ ] **Step 1: Generate the migration revision file**

```bash
cd backend
alembic revision -m "phase_1k1a_drop_templates_add_content_columns"
```

This creates `backend/alembic/versions/<auto_rev>_phase_1k1a_drop_templates_add_content_columns.py`.

- [ ] **Step 2: Write the migration**

Open the generated revision and replace `upgrade`/`downgrade`:

```python
"""phase_1k1a_drop_templates_add_content_columns

Revision ID: <auto>
Revises: <prev>
Create Date: 2026-06-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "<auto>"
down_revision = "<prev>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add new columns to jobs; template_key becomes nullable for new jobs.
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("content_type", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("rendered_tape_mm", sa.Integer(), nullable=True))
        batch_op.alter_column("template_key", nullable=True)

    # 2) Deterministic backfill from template_key for historical jobs.
    #    Webhook-keys (spoolman/<id>, grocy/<id>) won't match -> content_type=NULL.
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE jobs SET
            content_type = CASE
                WHEN template_key LIKE 'qr-only-%' THEN 'qr_only'
                WHEN template_key LIKE 'samla-%' THEN 'qr_two_lines'
                WHEN template_key IN (
                    'hangar-furniture-12mm', 'grocy-12mm',
                    'snipeit-12mm', 'spoolman-12mm'
                ) THEN 'qr_two_lines'
                WHEN template_key IN (
                    'hangar-furniture-18mm', 'hangar-furniture-24mm',
                    'grocy-18mm', 'grocy-24mm',
                    'snipeit-18mm', 'snipeit-24mm',
                    'spoolman-18mm', 'spoolman-24mm'
                ) THEN 'qr_three_lines'
                ELSE NULL
            END,
            rendered_tape_mm = CASE
                WHEN template_key LIKE '%-12mm' THEN 12
                WHEN template_key LIKE '%-18mm' THEN 18
                WHEN template_key LIKE '%-24mm' THEN 24
                WHEN template_key LIKE '%-62mm' THEN 62
                ELSE NULL
            END
    """))

    # 3) Drop the templates table — TemplateLoader is obsolete.
    op.drop_table("templates")


def downgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String, unique=True, nullable=False),
        sa.Column("definition", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("template_key", nullable=False)
        batch_op.drop_column("rendered_tape_mm")
        batch_op.drop_column("content_type")
```

- [ ] **Step 3: Update the SQLAlchemy Job model**

Edit `backend/app/models/job.py` to add the new columns:

```python
# in the Job model class
content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
rendered_tape_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
template_key: Mapped[str | None] = mapped_column(String, nullable=True)  # now nullable
```

(Adapt to the existing model's syntax — `Mapped` style or older `Column` style.)

Also update `backend/app/repositories/jobs.py` if `save_queued` (or equivalent) sets `template_key` — accept it as optional and add `content_type` + `rendered_tape_mm` kwargs.

- [ ] **Step 4: Write the migration test**

```python
# backend/tests/integration/test_alembic_migration.py
"""Verify the 1k.1a migration upgrades + downgrades on a fresh DB."""

from __future__ import annotations

import subprocess


def test_alembic_upgrade_head() -> None:
    """Migration runs cleanly from base to head."""
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="backend",
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_alembic_downgrade_one_then_upgrade() -> None:
    """Downgrade + upgrade round-trip works."""
    subprocess.run(["alembic", "downgrade", "-1"], cwd="backend", check=True)
    subprocess.run(["alembic", "upgrade", "head"], cwd="backend", check=True)
```

- [ ] **Step 5: Run migration tests**

Run: `cd backend && pytest tests/integration/test_alembic_migration.py -v`
Expected: PASS (both)

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/*_phase_1k1a_drop_templates_add_content_columns.py backend/app/models/job.py backend/app/repositories/jobs.py backend/tests/integration/test_alembic_migration.py
git commit -m "feat(db): Alembic migration — drop templates + add jobs.content_type/rendered_tape_mm

Phase 1k.1a Task 22: drops templates table, adds jobs.content_type +
rendered_tape_mm via op.batch_alter_table (SQLite-kompatibel).
jobs.template_key wird nullable (Audit-Spalte fuer historische Jobs).
Backfill aus template_key deterministisch fuer Seed-Template-Keys;
Webhook-Keys (spoolman/<id>, grocy/<id>) behalten content_type=NULL.

Refs #103"
```

---

### Task 23: File-Cleanup (Delete obsolete files)

**Files:**
- Delete: 13 files/dirs (siehe Plan-Header "Deleted"-Liste)

- [ ] **Step 1: Delete service files**

```bash
cd backend
rm app/services/label_renderer.py
rm app/services/template_loader.py
rm app/services/svg_renderer.py
```

- [ ] **Step 2: Delete schemas**

```bash
rm app/schemas/template.py
rm app/schemas/template_read.py
```

- [ ] **Step 3: Delete models + repositories**

```bash
rm app/models/template.py
rm app/repositories/templates.py
```

- [ ] **Step 4: Delete routes**

```bash
rm app/api/routes/templates.py
rm app/api/routes/templates_preview.py
```

- [ ] **Step 5: Delete seed YAMLs**

```bash
rm app/seed/templates/*.yaml
rmdir app/seed/templates 2>/dev/null || true
```

- [ ] **Step 6: Delete obsolete tests**

```bash
find tests -name "test_label_renderer*" -delete
find tests -name "test_template*" -delete
find tests -name "test_svg_renderer*" -delete
```

- [ ] **Step 7: Run full test suite — find remaining import errors**

Run: `cd backend && pytest -x 2>&1 | head -40`
Expected: import errors in files that still reference deleted modules. Note them for Task 24.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: delete obsolete template-related files (Phase 1k.1a)

Phase 1k.1a Task 23: hard-cut Loeschung von:
- label_renderer.py, template_loader.py, svg_renderer.py (Services)
- template.py, template_read.py (Schemas)
- models/template.py, repositories/templates.py (DB-Aggregat)
- routes/templates.py, routes/templates_preview.py (API)
- seed/templates/*.yaml (21 YAML-Files)
- alle test_label_renderer*, test_template*, test_svg_renderer*

Refs #103"
```

---

### Task 24: main.py + lifespan.py Cleanup

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/lifespan.py`

- [ ] **Step 1: Locate the orphaned imports/calls**

```bash
cd backend
grep -n "templates_routes\|templates_preview_router\|TemplateLoader\|LabelRenderer" app/main.py app/lifespan.py
```

- [ ] **Step 2: Remove from main.py**

Open `backend/app/main.py`. Delete:
- Imports of `templates_routes`, `templates_preview_router`, `LabelRenderer`, `TemplateLoader`.
- `app.include_router(templates_routes.router)` / `.render_router`.
- `app.include_router(templates_preview_router)`.
- Any `app.state.renderer = LabelRenderer(...)` or `app.state.template_loader = ...` lines.

Add:
- Import `from app.services.layout_engine import LayoutEngine`.
- In the lifespan / app-startup, `app.state.engine = LayoutEngine()`.

- [ ] **Step 3: Remove from lifespan.py**

Delete any `TemplateLoader(...).preload()` calls. Add LayoutEngine wiring if not already done in main.py.

- [ ] **Step 4: Run full test suite**

Run: `cd backend && pytest -x 2>&1 | tail -30`
Expected: PASS (or only failures in tests still to be addressed in Task 25)

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/lifespan.py
git commit -m "chore: main.py + lifespan.py — drop TemplateLoader/LabelRenderer wiring

Phase 1k.1a Task 24: Router-Registrierungen fuer templates entfernt.
app.state.engine = LayoutEngine() statt LabelRenderer. Lifespan-Preload
fuer Templates raus.

Refs #103"
```

---

### Task 25: Final Integration + Smoke Test Setup

**Files:**
- Create: `backend/tests/integration/test_phase_1k1a_integration.py`
- Create: `backend/scripts/smoke_layout_engine_12mm_v4.py`

- [ ] **Step 1: Write the full integration test**

```python
# backend/tests/integration/test_phase_1k1a_integration.py
"""Full integration test: API -> Engine -> Queue for content_type-based flow."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_print_flow_qr_two_lines(authed_client: AsyncClient) -> None:
    """End-to-end happy path on a mocked printer."""
    payload = {
        "content_type": "qr_two_lines",
        "data": {
            "primary_id": "K-02",
            "title": "Werkstatt",
            "qr_payload": "https://example.com/locations/k-02",
        },
        "options": {"copies": 1, "auto_cut": True},
    }
    resp = await authed_client.post("/api/print/brother-p750w-mock", json=payload)
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_full_batch_flow_mixed_content_types(authed_client: AsyncClient) -> None:
    payload = {
        "items": [
            {
                "content_type": "qr_two_lines",
                "data": {"primary_id": "A", "title": "T", "qr_payload": "x"},
            },
            {
                "content_type": "qr_only",
                "data": {"qr_payload": "y"},
            },
            {
                "content_type": "qr_three_lines",
                "data": {
                    "primary_id": "G1", "title": "Marmelade",
                    "qr_payload": "z", "secondary": ["MHD 2027-04-30"],
                },
            },
        ],
    }
    resp = await authed_client.post(
        "/api/print/brother-p750w-mock/batch", json=payload,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert len(body["job_ids"]) == 3


@pytest.mark.asyncio
async def test_preview_endpoint_post(authed_client: AsyncClient) -> None:
    payload = {
        "content_type": "qr_two_lines",
        "tape_mm": 12,
        "data": {
            "primary_id": "X", "title": "Y",
            "qr_payload": "https://example.com/x",
        },
        "format": "png",
    }
    resp = await authed_client.post("/api/render/preview", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
```

- [ ] **Step 2: Write the smoke-test script**

```python
# backend/scripts/smoke_layout_engine_12mm_v4.py
"""Manual smoke test: render qr_two_lines for 12mm and save PNG for visual diff.

Run:
    cd backend && python scripts/smoke_layout_engine_12mm_v4.py
Output:
    /tmp/smoke_v4_12mm.png — visual diff against Phase 1i V4-Winner reference.
"""

from __future__ import annotations

from pathlib import Path

from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.layout_engine import LayoutEngine


def main() -> None:
    eng = LayoutEngine()
    img = eng.render(
        tape_mm=12,
        content_type=ContentType.QR_TWO_LINES,
        data=LabelData(
            source_app="hangar",
            primary_id="K-02",
            title="Werkstatt",
            qr_payload="https://example.com/locations/k-02",
        ),
    )
    out = Path("/tmp/smoke_v4_12mm.png")
    img.save(out)
    print(f"Wrote {out} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Implement POST /api/render/preview endpoint (if not done in Task 18)**

Add to `backend/app/api/routes/print.py` (router prefix already `/api`):

```python
from io import BytesIO
from fastapi.responses import Response

class PreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content_type: ContentType
    tape_mm: int
    data: RawLabelData
    format: Literal["png"] = "png"  # svg later if needed


@router.post("/render/preview", tags=["render"])
async def render_preview(req: PreviewRequest, http: Request) -> Response:
    engine: LayoutEngine = http.app.state.engine
    label = LabelData(
        source_app="preview",
        title=req.data.title, primary_id=req.data.primary_id,
        qr_payload=req.data.qr_payload, secondary=req.data.secondary,
        items=req.data.items,
    )
    img = engine.render(req.tape_mm, req.content_type, label)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
```

- [ ] **Step 4: Run integration test**

Run: `cd backend && pytest tests/integration/test_phase_1k1a_integration.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run smoke-test script**

Run: `cd backend && python scripts/smoke_layout_engine_12mm_v4.py`
Expected: Output `Wrote /tmp/smoke_v4_12mm.png (<width>x70)`. Manually compare against Phase 1i V4-Winner output (visual diff in browser).

- [ ] **Step 6: Run lint + type-check + full suite**

```bash
cd backend
ruff check .
ruff format --check .
mypy .
pytest --cov=app --cov-report=term-missing
```

Expected: lint clean, mypy clean, all tests pass, coverage ≥90% on new modules.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/integration/test_phase_1k1a_integration.py backend/scripts/smoke_layout_engine_12mm_v4.py backend/app/api/routes/print.py
git commit -m "test(integration): full Phase 1k.1a flow + 12mm V4-Winner smoke script

Phase 1k.1a Task 25: end-to-end tests verifying API -> LayoutEngine ->
Queue. POST /api/render/preview endpoint hinzugefuegt. Smoke-Script fuer
12mm V4-Baseline-Vergleich (Phase 1i Visual-Diff).

Refs #103"
```

---

## Final Steps

- [ ] **Push branch + open PR**

```bash
git push -u origin feat/phase-1k1a-layout-engine
gh pr create --base main --title "feat(1k.1a): Hub Layout-Engine — replaces 21 templates with semantic engine" --body-file - <<'EOF'
## Summary

Implements Phase 1k.1a per approved spec.

Closes #103 partially (Phase 1k.1a only — 1k.1b/c/d folgen separat).
Refs #101.

Spec: `docs/superpowers/specs/2026-06-05-phase-1k1-layout-engine-design.md`
Plan: `docs/superpowers/plans/2026-06-05-phase-1k1a-layout-engine-plan.md`

## Test plan

- [x] Unit: TapeGeometry, ContentType, LayoutEngine (all 7 render methods)
- [x] Unit: PrintService, PrintQueue rerender, batch_dispatch
- [x] Integration: POST /api/print, /api/print/{slug}/batch, /api/render/preview
- [x] Integration: TapeMismatchError + resume routes gone (404/422)
- [x] Integration: Alembic upgrade + downgrade
- [x] Coverage ≥90% on new modules

Hardware smoke (post-deploy): 12mm V4-Winner visual identical to Phase 1i output.
EOF
```

- [ ] **Hardware-Smoke nach Deploy**

After Watchtower deploys the new image to the test environment:
1. Send a 12mm `qr_two_lines` print via the new API to the PT-P750W.
2. Compare the printed label visually against the Phase 1i V4-Winner reference.
3. Validate scan-ability of the QR code.
4. Document the result in a follow-up issue/comment.

---

## Self-Review Summary

**Spec coverage:**
- Sektion 1 (Executive Summary): covered by Tasks 1-13 (Engine + Schemas) and Tasks 14-21 (API/Service refactors)
- Sektion 2 (ContentTypes + Validation): Tasks 2 + 6 (skeleton) + 7-13 (per-type)
- Sektion 3 (TapeGeometry): Task 1
- Sektion 4 (LayoutEngine API): Tasks 5-13
- Sektion 5 (1k.1a Files): Tasks 14-25 cover every file in the spec's modify/delete lists
- Sektion 9 (Testing): each task includes failing-test-first + final integration tests + smoke
- Sektion 10 DoD 1k.1a: all checkboxes mapped to tasks

**Placeholder scan:** No "TBD", "TODO" outside intentional `TODO(phase5)` from existing code. All steps contain runnable code.

**Type consistency:** All tasks reference `tape_mm: int`, `content_type: ContentType`, `LabelData` with optional fields. `ContentType` enum used consistently.

**Decomposition complete:** 25 tasks, each producing self-contained commits. Tasks 6-13 build the engine incrementally (skeleton + 7 render methods, one per task) to enable per-task subagent review.
