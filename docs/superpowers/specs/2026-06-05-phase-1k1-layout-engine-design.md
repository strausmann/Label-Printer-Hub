# Phase 1k.1 — Layout-Engine + TapeGeometry + ContentTypes (Design)

**Datum:** 2026-06-05
**Status:** Draft (zur User-Review)
**Tracking:** strausmann/Label-Printer-Hub#103 (Phase 1k.1 unter Umbrella #101)
**Vorgaenger-Spec:** docs/superpowers/specs/2026-05-17-phase-7e-template-layout-v2-design.md (subsumiert)
**Hardware-Baseline:** Phase 1i V4-Winner (docs/site/operations/protokolle/2026-06-04-phase1i-smoke-test-empirie.md)

## 1. Executive Summary

Phase 1k.1 ersetzt die 21 hartcodierten YAML-Templates (hangar/grocy/snipeit/spoolman/qr-only x 12/18/24mm + 6 Samla) durch eine semantische **Layout-Engine** mit zwei Achsen:

1. **TapeGeometry** — Tabelle mit allen 7 unterstuetzten Tape-Groessen (3.5/6/9/12/18/24/62mm) und ihren Render-Parametern (printable_px, qr_max, Font-Groessen)
2. **6 ContentTypes** — semantische Beschreibung was gerendert wird, **tape-unabhaengig** (qr_only, qr_one_line, qr_two_lines, text_one_line, text_two_lines, qr_with_listing)

**Tape-Unabhaengigkeit** ist der Kern-Wechsel: Hangar sendet `content_type: qr_two_lines` (ohne tape_mm), Hub liest `preflight.loaded_tape_mm` vom Drucker und rendert passend. Der bestehende `TapeMismatchError` wird damit obsolet — User wechselt physisch das Tape, das System rendert automatisch.

**Hard-Cut Migration:** Keine Legacy-Kompatibilitaet, keine Compat-Layer fuer alte `template_id`-Calls. Das System ist noch in Entwicklung, alle 21 YAMLs werden geloescht, alle Aufrufer auf die neue API umgestellt.

**Scope-Decomposition in 4 Sub-Phasen** (sequentiell mergebar):
- **1k.1a:** Hub Layout-Engine + neue API (Python)
- **1k.1b:** Hangar API-Migration (Go)
- **1k.1c:** Hangar Categories DB + CRUD-Editor + Live-Preview (Go)
- **1k.1d:** Hangar Navigation-Refactor (Administration-Submenu)

## 2. ContentTypes (semantische Render-Beschreibung)

Sechs Types decken alle bisherigen Use Cases ab. Jeder Type definiert WAS gerendert wird, nicht WIE — die TapeGeometry-Tabelle und der Renderer berechnen Pixel-Positionen automatisch.

| ContentType | Layout-Beschreibung | Genutzte LabelData-Felder | Original Templates (vorher) |
|-------------|---------------------|---------------------------|----------------------------|
| `qr_only` | QR fuellt volle Tape-Hoehe, kein Text | `qr_payload` | qr-only-12mm, qr-only-18mm, qr-only-24mm |
| `qr_one_line` | QR links + 1 Text-Zeile (XL, vertikal zentriert) | `qr_payload`, `primary_id` | (neu, war Sonderfall) |
| `qr_two_lines` | QR links + 2 Text-Zeilen (XL primary_id + L title) | `qr_payload`, `primary_id`, `title` | hangar-furniture-*, grocy-*, snipeit-*, spoolman-* |
| `text_one_line` | Voll-Breite Text XL, kein QR | `primary_id` | (neu) |
| `text_two_lines` | 2 Text-Zeilen XL + L, kein QR | `primary_id`, `title` | samla-stirntag-* (teilweise) |
| `qr_with_listing` | QR links + N Item-Zeilen (M-Groesse), Overflow zeigt "+N more" | `qr_payload`, `primary_id` (Header), `items: tuple[LabelDataItem,...]` | (neu, fuer Kallax-Regal-Uebersicht aus 7e-Spec) |

### Validation-Regeln

| Regel | Geprueft |
|-------|----------|
| `qr_*` ContentType benoetigt `qr_payload` in data | 422 wenn fehlt |
| `text_*` ContentType ignoriert `qr_payload` (kein Fehler, nur unused) | — |
| `qr_with_listing` benoetigt `items: tuple[LabelDataItem,...]` mit mindestens 1 Item | 422 wenn fehlt/leer |
| `text_one_line` und `qr_one_line` benoetigen `primary_id` | 422 wenn fehlt |
| `*_two_lines` benoetigt `primary_id` UND `title` | 422 wenn eines fehlt |

## 3. TapeGeometry (alle 7 Tape-Groessen)

Pixel-Werte aus Brother Pin-Konfiguration (PT-Serie 180 DPI, QL 300 DPI). Die 12mm-Zeile ist empirisch validiert (Phase 1i V4-Winner). Die anderen Zeilen sind via Pixel-Ratio extrapoliert und werden nach Implementation per Smoke-Test validiert.

```python
# backend/app/schemas/tape_geometry.py

from pydantic import BaseModel, ConfigDict


class TapeGeometry(BaseModel):
    """Render-Parameter pro Tape-Groesse (alle Werte in Pixel)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    printable_px: int        # Brother Pin-Count fuer die Tape-Groesse
    qr_max_px: int           # printable_px - 4 (2px Padding pro Seite)
    qr_padding_px: int       # Padding um den QR-Code
    text_start_x: int        # X-Position wo Text nach QR beginnt
    line_spacing_px: int     # Vertikaler Abstand zwischen Text-Zeilen
    font_xl: int             # primary_id Groesse
    font_l: int              # title Groesse
    font_m: int              # listing item Groesse
    font_s: int              # secondary Groesse (reserviert)


TAPE_GEOMETRY: dict[float, TapeGeometry] = {
    3.5: TapeGeometry(printable_px=24,  qr_max_px=20,  qr_padding_px=2, text_start_x=26,  line_spacing_px=1, font_xl=8,   font_l=7,  font_m=6,  font_s=5),
    6:   TapeGeometry(printable_px=32,  qr_max_px=28,  qr_padding_px=2, text_start_x=34,  line_spacing_px=2, font_xl=10,  font_l=9,  font_m=7,  font_s=6),
    9:   TapeGeometry(printable_px=50,  qr_max_px=46,  qr_padding_px=2, text_start_x=52,  line_spacing_px=3, font_xl=14,  font_l=12, font_m=10, font_s=8),
    12:  TapeGeometry(printable_px=70,  qr_max_px=66,  qr_padding_px=2, text_start_x=72,  line_spacing_px=4, font_xl=22,  font_l=18, font_m=14, font_s=10),  # V4-Winner
    18:  TapeGeometry(printable_px=112, qr_max_px=108, qr_padding_px=2, text_start_x=114, line_spacing_px=6, font_xl=32,  font_l=26, font_m=20, font_s=14),
    24:  TapeGeometry(printable_px=128, qr_max_px=124, qr_padding_px=2, text_start_x=130, line_spacing_px=8, font_xl=36,  font_l=30, font_m=24, font_s=18),
    62:  TapeGeometry(printable_px=696, qr_max_px=672, qr_padding_px=4, text_start_x=680, line_spacing_px=20, font_xl=120, font_l=96, font_m=72, font_s=48),  # QL 300 DPI
}
```

### Empirische Validierung post-Deploy

12mm-Werte aus Phase 1i V4-Winner sind scan-verifiziert.
3.5/6/9/18/24/62mm wurden via Pixel-Ratio extrapoliert (`new_value = 12mm_value * new_printable_px / 70`). Smoke-Test als Follow-up-Issue: jede Tape-Groesse einmal mit `qr_two_lines` drucken, Lesbarkeit pruefen, ggf. Werte korrigieren. User hat 24mm-Tapes und QL-Rollen verfuegbar.

## 4. Layout-Engine API

```python
# backend/app/services/layout_engine.py

from PIL.Image import Image
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData


class LayoutEngine:
    """Rendert Labels semantisch pro Tape-Groesse + ContentType.

    Ersetzt LabelRenderer komplett. Keine Templates mehr — Engine kennt
    alle Kombinationen von TapeGeometry x ContentType.
    """

    def render(
        self,
        tape_mm: float,
        content_type: ContentType,
        data: LabelData,
    ) -> Image:
        """Render-Pfad: tape_mm + content_type + data -> PIL Image."""
        geometry = self._lookup_geometry(tape_mm)
        self._validate_data(content_type, data)

        match content_type:
            case ContentType.QR_ONLY:
                return self._render_qr_only(geometry, data)
            case ContentType.QR_ONE_LINE:
                return self._render_qr_one_line(geometry, data)
            case ContentType.QR_TWO_LINES:
                return self._render_qr_two_lines(geometry, data)
            case ContentType.TEXT_ONE_LINE:
                return self._render_text_one_line(geometry, data)
            case ContentType.TEXT_TWO_LINES:
                return self._render_text_two_lines(geometry, data)
            case ContentType.QR_WITH_LISTING:
                return self._render_qr_with_listing(geometry, data)
```

Jede `_render_*`-Methode ist klein (<30 Zeilen), nutzt nur `geometry` + `data`, und gibt ein PIL-Image zurueck dessen Hoehe `geometry.printable_px` entspricht. Die Breite wird durch Inhalt und Whitespace-Trim bestimmt (analog Phase 1i LabelRenderer-Verhalten).

### Errors

| Error | HTTP | Zweck |
|-------|------|-------|
| `UnsupportedTapeError(tape_mm)` | 422 | tape_mm nicht in TAPE_GEOMETRY (defensive — tritt mit 7 Groessen nicht praktisch auf) |
| `ContentTypeDataMismatchError(content_type, missing_fields)` | 422 | data fehlen Pflichtfelder fuer den ContentType |
| `NoTapeLoadedError()` | 409 | preflight.loaded_tape_mm == None (Tape physisch nicht eingelegt) |

`TapeMismatchError` wird ersatzlos geloescht (nicht mehr im Render-Pfad geworfen).

## 5. Phase 1k.1a — Hub Layout-Engine (Backend)

### Neue Files

```
backend/app/schemas/
+-- tape_geometry.py        # TapeGeometry Pydantic-Model + TAPE_GEOMETRY dict
+-- content_type.py         # ContentType Enum (6 Werte)
backend/app/services/
+-- layout_engine.py        # LayoutEngine.render() + 6 _render_*-Methoden
backend/tests/unit/services/
+-- test_layout_engine.py   # Unit-Tests pro ContentType x Tape-Groesse
```

### Modifizierte Files

```
backend/app/schemas/
*-- label_data.py           # + items: tuple[LabelDataItem, ...] = ()
+-- label_data_item.py      # NEU — LabelDataItem(item: str, qr_payload: str | None = None)
backend/app/services/
*-- print_service.py        # submit_job: render via LayoutEngine (statt LabelRenderer)
*-- print_queue.py          # _process_job: nutzt content_type statt template
backend/app/api/routes/
*-- print.py                # Request-Schema: content_type: ContentType, kein template_id mehr
*-- batch.py                # Gleicher Pattern: items[].content_type statt items[].template_id
backend/app/api/exceptions/  # neue Errors registriert
```

### Geloeschte Files

```
backend/app/services/label_renderer.py
backend/app/services/template_loader.py
backend/app/schemas/template.py
backend/app/api/routes/templates.py          # /api/templates/* komplett weg
backend/app/api/routes/templates_preview.py  # /api/templates/{key}/preview-* weg
backend/app/seed/templates/*.yaml            # alle 21 YAML-Files
backend/tests/**/test_template*              # alle Template-Tests
backend/tests/**/test_label_renderer*        # alle alten Renderer-Tests
```

### Neue/geanderte Routes

| Route | Methode | Aenderung |
|-------|---------|-----------|
| `/api/print/{slug}` | POST | Request hat `content_type: str` (Enum), `data: LabelData`, `options: PrintOptions` — `template_id` Feld geloescht |
| `/api/print/{slug}/batch` | POST | items[] mit `content_type`, kein `template_id` |
| `/api/render/preview` | GET | Query: `?content_type=qr_two_lines&tape_mm=18&data_json={...}` |
| `/api/templates/*` | alle | komplett geloescht (Route-File weg) |
| `/api/templates/{key}/preview-png` | GET | geloescht |
| `/api/templates/{key}/preview-svg` | GET | geloescht |

### DB-Migration (Alembic)

Neue Migration `XXXX_drop_templates_table.py`:
```python
def upgrade() -> None:
    op.drop_table("templates")

def downgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String, unique=True),
        # ... ursprueengliche Spalten
    )
```

Print-Jobs-Historie: bestehende `jobs.template_id`-Spalte wird ersetzt durch `jobs.content_type` + `jobs.rendered_tape_mm`. Migration:
```python
def upgrade() -> None:
    op.add_column("jobs", sa.Column("content_type", sa.String(32)))
    op.add_column("jobs", sa.Column("rendered_tape_mm", sa.Float))
    op.drop_column("jobs", "template_id")
```

Existierende Jobs-Eintraege bekommen content_type=NULL — fuer Historie tolerierbar (Frontend zeigt "(legacy)" wenn NULL).

### Pflicht-Smoke-Test nach Implementation

12mm-Rendering muss visuell identisch zum Phase 1i V4-Winner Output sein. Konkreter Test:
- Vorher: `LabelRenderer().render(template="hangar-furniture-12mm", data={primary_id="K-02", title="Werkstatt", qr_payload="..."})` -> Image A
- Nachher: `LayoutEngine().render(tape_mm=12, content_type=QR_TWO_LINES, data=...)` -> Image B
- A == B per Pixel-Hash-Vergleich, oder A und B visuell nicht unterscheidbar (manuell ueber Browser-Diff)

## 6. Phase 1k.1b — Hangar API-Migration

### Aenderungen pro File

| File | Aenderung |
|------|-----------|
| `internal/hub/layouts.go` | Struct `LayoutMapping`: `TemplateID string` -> `ContentType string`. YAML-Tag `template_id` -> `content_type`. |
| `internal/hub/client.go` | `PrintRequest` struct: `template_id` Feld entfernen, `content_type` hinzufuegen. JSON-Marshaling angepasst. |
| `internal/generator/print_p750w.go` | PrintRequest-Bau: `TemplateID: m.TemplateID` -> `ContentType: m.ContentType` |
| `cmd/hangar/main.go:768` | Preview-Proxy: `/admin/print/preview/{template_id}` -> `/admin/print/preview?content_type=...&tape_mm=...`. Forward auf Hub `/api/render/preview` mit Query-String. |
| `internal/hub/example-layouts.yaml` | Komplett neu geschrieben (siehe unten) |
| `internal/templates/print_form.templ` | Template-Picker raus (er war eh nur einer pro Category) |
| `cmd/hangar/main_test.go` + `internal/generator/print_test.go` | Tests auf neue Felder umgestellt |

### Neue example-layouts.yaml

```yaml
# Phase 1k.1b: ContentType statt template_id, eine Zeile pro Moebeltyp
# (vorher: 3 Zeilen wenn 12/18/24mm-Varianten existierten)

printers:
  brother-p750w: "11111111-1111-1111-1111-111111111111"
  brother-ql820: "22222222-2222-2222-2222-222222222222"

categories:
  Kallax-Fach:
    printer_slug: brother-p750w
    content_type: qr_two_lines
    quantity_default: 1
  Kallax-Regal:                          # NEU — Aggregations-Use-Case
    printer_slug: brother-p750w
    content_type: qr_with_listing
    quantity_default: 1
  Alex-Schublade:
    printer_slug: brother-p750w
    content_type: qr_two_lines
  Schreibtisch-Schublade:
    printer_slug: brother-p750w
    content_type: qr_two_lines
  "Billy-Ebene AK":
    printer_slug: brother-p750w
    content_type: qr_two_lines
  "Billy-Ebene VK":
    printer_slug: brother-p750w
    content_type: qr_two_lines
  Samla-Stirntag:
    printer_slug: brother-ql820
    content_type: text_two_lines        # Samla ohne QR (Aufdruck am Karton)
  Samla-Deckel:
    printer_slug: brother-ql820
    content_type: qr_two_lines
```

Die Eintraege werden hier noch aus YAML gelesen. Phase 1k.1c migriert dann auf DB-Tabelle (yaml dient ab da nur noch als Initial-Seed).

### Smoke-Test

`Kallax-Fach`-Print ueber neue Hangar-API muss visuell identisch zum pre-Migration-Print sein. Hardware-Validierung mit PT-P750W + 12mm-Tape.

## 7. Phase 1k.1c — Hangar Categories DB + CRUD-Editor

### DB-Schema (SQLite, GORM auto-migrate oder SQL-Migration)

```sql
CREATE TABLE print_categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,        -- "Kallax-Fach"
    content_type    TEXT NOT NULL,                -- "qr_two_lines"
    printer_slug    TEXT NOT NULL,                -- "brother-p750w"
    quantity_default INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL
);
CREATE INDEX idx_print_categories_sort ON print_categories(sort_order);
```

### Neuer Service

```
internal/category/
+-- service.go          # CategoryService: List, Get, Create, Update, Delete, Reorder
+-- model.go            # Category struct (GORM)
+-- service_test.go     # Unit-Tests
```

### Neue Routes

```
GET    /admin/print/categories                    # Liste mit Live-Preview pro Eintrag
GET    /admin/print/categories/new                # Add-Form
POST   /admin/print/categories                    # Create
GET    /admin/print/categories/{id}/edit          # Edit-Form mit Live-Preview
PUT    /admin/print/categories/{id}               # Update
DELETE /admin/print/categories/{id}               # Delete
POST   /admin/print/categories/reorder            # Drag-and-Drop neu sortieren
GET    /admin/print/categories/preview            # HTMX-Endpoint: liefert SVG aus Hub
                                                  # Query: ?content_type=...&tape_mm=...&primary_id=...&title=...
```

### Templates

```
internal/templates/
+-- admin_print_categories_list.templ     # Liste mit Mini-Preview pro Eintrag
+-- admin_print_categories_form.templ     # Add/Edit-Form mit Live-Preview-Pane
+-- components/category_preview_pane.templ # HTMX-Target fuer Live-Preview-Refresh
```

### Live-Preview-Verhalten

User waehlt im Add/Edit-Form:
1. `content_type` Dropdown (qr_only/qr_one_line/qr_two_lines/text_one_line/text_two_lines/qr_with_listing)
2. Optionale Sample-Daten (primary_id, title, items) — defaults aus ContentType-Definition

HTMX-Trigger: `change`-Event auf Form-Felder -> `GET /admin/print/categories/preview?content_type=...&tape_mm=12` -> Hub `/api/render/preview` -> SVG zurueck -> in Preview-Pane.

Preview-Pane zeigt 3 SVGs side-by-side: 12mm, 18mm, 24mm (oder 62mm wenn QL-Drucker). Per Tab oder Stack-Layout je nach Viewport.

### YAML-Seed-Import

Beim ersten Start (wenn Tabelle leer):
1. Lese `HUB_LAYOUTS_PATH` (z.B. /etc/hangar/hub-layouts.yaml)
2. Iteriere `categories` und schreibe in DB
3. Log: "Imported N categories from hub-layouts.yaml"

YAML-File bleibt erhalten (read-only Source), aber Service liest ab jetzt aus DB. Manueller Re-Import via Admin-Action "Seed neu einlesen".

### Tests

| Test-Layer | Coverage |
|-----------|----------|
| Unit | CategoryService CRUD, Validation, sort_order-Reorder |
| Integration | HTTP-Routes mit auth-required Middleware, CSRF |
| HTMX-Integration | Preview-Endpoint liefert valide SVG-Response |
| Migration | Seed-Import aus example-layouts.yaml erzeugt korrekte DB-Eintraege |

## 8. Phase 1k.1d — Hangar Navigation-Refactor

### Aktuelle Navigation (flach)

```
Katalog | Meine Items | Admin (Catalog) | Drucken | Benutzer | Status (debug)
```

### Neue Navigation (hierarchisch)

```
Katalog (top)
Meine Items (top, SSO)
Drucken (top, haeufige User-Aktion)
Administration ▾ (top, mit Untermenue)
   |-- Katalog-Typen      (vorher "Admin")
   |-- Print-Categories   (NEU aus 1k.1c)
   |-- Benutzer
   |-- Einstellungen      (NEU — Hub-Layouts-Resync, Resolver-Config, SSO-Status)
   '-- Debugging ▾
       |-- Status
       '-- Stats
```

### Permission-Gating

| Top-Level-Item | Sichtbar wenn |
|----------------|---------------|
| Katalog | immer |
| Meine Items | User.Source == "sso" |
| Drucken | CanAccessCatalogAdmin (unveraendert) |
| Administration | HasAnyAdminAccess(ctx) — neue Helper-Funktion |

```go
// internal/auth/permissions.go
func HasAnyAdminAccess(ctx context.Context) bool {
    return CanAccessCatalogAdmin(ctx) ||
           CanAccessUsersAdmin(ctx) ||
           CanAccessDebug(ctx)
}
```

Submenu-Items folgen ihren eigenen Permission-Checks (z.B. "Benutzer" nur sichtbar wenn `CanAccessUsersAdmin`).

### UI-Implementation

**Desktop (`md:` und groesser):**
- Click-Dropdown unter "Administration" — nutzt vanilla JS oder Alpine.js
- Active-State: aktueller Pfad wird im Submenu hervorgehoben (gelbes Border)

**Mobile (Hamburger-Drawer):**
- Administration als `<details>` Element — nativer Browser-Toggle, kein JS noetig
- Submenu eingerueckt, kollabierbar

### Files

```
internal/templates/
*-- layout.templ                       # nav-section + mobile-drawer Restructure
+-- components/admin_dropdown.templ    # NEU — wiederverwendbar
web/static/js/
+-- admin-dropdown.js                  # Click-outside-handler, ESC-close
internal/auth/
*-- permissions.go                     # + HasAnyAdminAccess(ctx)
```

### Tests

Snapshot-Test der gerenderten layout.templ:
- mit User ohne Admin-Rolle: "Administration" Top-Level fehlt
- mit User mit nur CatalogAdmin: "Administration" sichtbar, nur "Katalog-Typen" + "Drucken" im Submenu
- mit Voll-Admin: alle Submenu-Items sichtbar

## 9. Testing-Strategie (alle Phasen)

| Phase | Test-Layer | Coverage-Ziel |
|-------|-----------|---------------|
| 1k.1a Hub | Unit (TapeGeometry x ContentType x Validation) + Integration (Print-Endpoint Roundtrip) | 90%+ |
| 1k.1b Hangar API | Unit (Layouts-Parsing, Client-Request-Bau) + Integration (Hangar -> Mock-Hub) | 85%+ |
| 1k.1c Hangar Categories | Unit (Service-CRUD) + Integration (HTTP-Routes mit Auth) + HTMX (Preview-Endpoint) | 85%+ |
| 1k.1d Navigation | Snapshot (rendered HTML) + Permission-Tests | n/a (templ-Snapshots) |

### Hardware-Smoke nach allen 4 Phasen

| Test | Drucker | Tape |
|------|---------|------|
| 12mm V4-Baseline (Regression) | PT-P750W | 12mm TZe |
| 24mm Smoke (neu validiert) | PT-P750W | 24mm TZe |
| 62mm Endlos | QL-820NWB | 62mm DK |
| `qr_with_listing` mit 4 Items | PT-P750W | 24mm TZe |

## 10. Definition of Done (pro Sub-Phase)

### Phase 1k.1a

- [ ] `TapeGeometry` + `TAPE_GEOMETRY` dict fuer 7 Tape-Groessen
- [ ] `ContentType` Enum mit 6 Werten
- [ ] `LayoutEngine.render()` implementiert alle 6 ContentTypes
- [ ] `LabelData.items` Erweiterung + `LabelDataItem`-Klasse
- [ ] Routes `/api/print/*` umgebaut auf `content_type`
- [ ] `/api/render/preview` umgebaut auf Query-Params
- [ ] Routes `/api/templates/*` komplett entfernt
- [ ] Alle 21 YAML-Templates geloescht
- [ ] `LabelRenderer`, `TemplateLoader`, `template.py` Schema geloescht
- [ ] Alembic-Migration: `templates` Tabelle drop + `jobs.content_type` add
- [ ] Tests gruen, Coverage >=90% auf neuen Modulen
- [ ] Smoke-Test: 12mm V4-Baseline visuell identisch
- [ ] Refs #103, Closes #81 (7e-Spec subsumiert)

### Phase 1k.1b

- [ ] `LayoutMapping` struct: `TemplateID` -> `ContentType`
- [ ] `PrintRequest` struct: `template_id` -> `content_type`
- [ ] `example-layouts.yaml` mit 6 ContentTypes + `Kallax-Regal` neu
- [ ] Preview-Proxy-Route umgebaut
- [ ] `print_form.templ` Template-Picker entfernt
- [ ] Tests gruen
- [ ] Smoke: Kallax-Fach-Print identisch zu pre-Migration
- [ ] Refs #103

### Phase 1k.1c

- [ ] DB-Schema `print_categories` + GORM-Model
- [ ] `CategoryService` mit CRUD-API
- [ ] Routes `/admin/print/categories/*` mit Auth-Middleware
- [ ] Templates: List, Add, Edit, Preview-Pane
- [ ] HTMX Live-Preview-Endpoint mit Hub-Forwarding
- [ ] YAML-Seed-Import beim ersten Start
- [ ] Tests: Service-Unit + HTTP-Integration + HTMX-Integration
- [ ] Smoke: neue Category anlegen, Preview sehen, Test-Print starten
- [ ] Refs #103

### Phase 1k.1d

- [ ] `HasAnyAdminAccess` Helper in `internal/auth/permissions.go`
- [ ] `layout.templ` Nav umgebaut auf hierarchische Struktur
- [ ] `admin_dropdown.templ` Komponente
- [ ] `admin-dropdown.js` Click-outside + ESC-close
- [ ] Mobile-Drawer: `<details>`-basierte Admin-Section
- [ ] Snapshot-Tests fuer Permission-Varianten
- [ ] Smoke: manuelles Navigieren Mobile + Desktop
- [ ] Refs #103

## 11. Out-of-Scope

- **Multi-Printer-Model Layouts** (PT-180-DPI vs QL-300-DPI) — TapeGeometry abstrahiert das ueber tape_mm-Aufloesung; pro-Modell-Varianten sind ein zukuenftiger Constants-Table-Erweiterung
- **Image-Elemente** (Logos, Photos) — Engine rendert Text + QR, Image-Elemente bleiben deferred
- **WYSIWYG-Editor fuer ContentType-Layouts** — Phase 1k.3 (Issue #104)
- **Per-User-Custom-ContentTypes** — Phase 1k.3
- **36mm-Tape-Support** — Constants-Table-Erweiterung sobald Hardware
- **TapeMismatchError-Detection** im Hangar-Frontend (z.B. Warnung vor Print) — Phase 1k.1c koennte dies optional aufnehmen wenn Hardware-Drucker fehlende Tape-Erkennung melden

## 12. Self-Review

**Privacy-Check:** Spec nutzt RFC 5737-Placeholder (example.com), keine echten IPs/Hostnames, keine echten Namen.

**Hard-Cut-Rationale:** User bestaetigt: System in Entwicklung, keine Legacy-Kompatibilitaet noetig. Saubere Loeschung aller alten Templates und Renderer ist einfacher als Compat-Layer.

**Scope-Aufteilung:** 4 Sub-Phasen mit klaren Abhaengigkeiten (a -> b -> c, d nach c). Jede Phase einzeln deploy-bar und reversibel.

**ContentType-Auswahl:** 6 Types decken alle bisherigen 21 Templates ab plus Kallax-Aggregation aus 7e. Validation-Regeln sind explizit.

**Tape-Independence:** Eliminiert TapeMismatchError aus Print-Pfad. Edge-Case "unsupported tape_mm" wird durch defensiv eingebaute Errors gefangen (sollte mit 7 Groessen praktisch nicht auftreten).

**Migration:** DB-Migrationen sind klar, jobs.content_type-Spalte ist nullable fuer Historie. Hangar-YAML wird zur Seed-Quelle.

**Out-of-Scope-Liste:** alle bekannten Versuchungen explizit ausgeschlossen (Multi-Printer-Model, WYSIWYG, Custom-Types, etc.).
