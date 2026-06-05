# Phase 1k.1 — Layout-Engine + TapeGeometry + ContentTypes (Design)

**Datum:** 2026-06-05
**Status:** Draft (zur User-Review)
**Tracking:** strausmann/Label-Printer-Hub#103 (Phase 1k.1 unter Umbrella #101)
**Vorgaenger-Spec:** docs/superpowers/specs/2026-05-17-phase-7e-template-layout-v2-design.md (subsumiert)
**Hardware-Baseline:** Phase 1i V4-Winner — empirisch validiert auf PT-P750W mit 12mm TZe-Tape. Pixel-Werte (QR x=2 y=2 max_size=66, text_start_x=72, font_xl=22, font_l=18) dokumentiert im Issue-Kommentar zu Issue #103. Das originale Smoke-Test-Protokoll liegt im privaten `homelab-management` Repo (kein OS-Pfad in diesem Repo).

## 1. Executive Summary

Phase 1k.1 ersetzt die 21 hartcodierten YAML-Templates (hangar/grocy/snipeit/spoolman/qr-only x 12/18/24mm + 6 Samla) durch eine semantische **Layout-Engine** mit zwei Achsen:

1. **TapeGeometry** — Tabelle mit **initialem Scope** von 7 Tape-Groessen (**4**/6/9/12/18/24/62mm — `int`, kleinste PT-TZe ist **4mm** (24 Print-Pins) — nicht 3.5mm wie in fruehen Drafts) und ihren Render-Parametern (printable_px, qr_max, Font-Groessen). Die bestehende `TapeRegistry` kennt zusaetzliche QL-DK-Breiten (29/38/50/54mm) — Layout-Engine in 1k.1 deckt diese **bewusst noch nicht** ab; entsprechende Print-Requests fuehren zu `UnsupportedTapeError`. Erweiterung der Tabelle ist Constants-Aenderung (kein Code-Refactor) und kann als Folge-Phase ergaenzt werden.
2. **7 ContentTypes** — semantische Beschreibung was gerendert wird, **tape-unabhaengig** (qr_only, qr_one_line, qr_two_lines, **qr_three_lines** fuer 3-Zeilen-Layouts mit secondary, text_one_line, text_two_lines, qr_with_listing)

**Tape-Unabhaengigkeit** ist der Kern-Wechsel: Hangar sendet `content_type: qr_two_lines` (ohne tape_mm), Hub liest `preflight.loaded_tape_mm` vom Drucker und rendert passend. Der bestehende `TapeMismatchError` wird damit obsolet — User wechselt physisch das Tape, das System rendert automatisch.

**Hard-Cut Migration:** Keine Legacy-Kompatibilitaet, keine Compat-Layer fuer alte `template_id`-Calls. Das System ist noch in Entwicklung, alle 21 YAMLs werden geloescht, alle Aufrufer auf die neue API umgestellt.

**Scope-Decomposition in 4 Sub-Phasen** (sequentiell mergebar):
- **1k.1a:** Hub Layout-Engine + neue API (Python)
- **1k.1b:** Hangar API-Migration (Go)
- **1k.1c:** Hangar Categories DB + CRUD-Editor + Live-Preview (Go)
- **1k.1d:** Hangar Navigation-Refactor (Administration-Submenu)

## 2. ContentTypes (semantische Render-Beschreibung)

Sieben Types decken alle bisherigen Use Cases ab. Jeder Type definiert WAS gerendert wird, nicht WIE — die TapeGeometry-Tabelle und der Renderer berechnen Pixel-Positionen automatisch.

| ContentType | Layout-Beschreibung | Genutzte LabelData-Felder | Original Templates (vorher) |
|-------------|---------------------|---------------------------|----------------------------|
| `qr_only` | QR fuellt volle Tape-Hoehe, kein Text | `qr_payload` | qr-only-12mm, qr-only-18mm, qr-only-24mm |
| `qr_one_line` | QR links + 1 Text-Zeile (XL, vertikal zentriert) | `qr_payload`, `primary_id` | (neu, war Sonderfall) |
| `qr_two_lines` | QR links + 2 Text-Zeilen (XL primary_id + L title) | `qr_payload`, `primary_id`, `title` | hangar-furniture-12mm, grocy-12mm, snipeit-12mm, spoolman-12mm, samla-stirntag-12mm, samla-stirntag-24mm, samla-stirntag-62mm, samla-deckel-12mm, samla-deckel-24mm, samla-deckel-62mm |
| `qr_three_lines` | QR links + 3 Text-Zeilen (XL primary_id + L title + S secondary[0]) | `qr_payload`, `primary_id`, `title`, `secondary` | hangar-furniture-18mm, hangar-furniture-24mm, grocy-18mm, grocy-24mm, snipeit-18mm, snipeit-24mm, spoolman-18mm, spoolman-24mm |
| `text_one_line` | Voll-Breite Text XL, kein QR | `primary_id` | (neu, kein altes Template) |
| `text_two_lines` | 2 Text-Zeilen XL + L, kein QR | `primary_id`, `title` | (neu, kein altes Template) |
| `qr_with_listing` | QR links + N Item-Zeilen (M-Groesse), Overflow zeigt "+N more" | `qr_payload`, `primary_id` (Header), `items: tuple[LabelDataItem,...]` | (neu, fuer Kallax-Regal-Uebersicht aus 7e-Spec) |

**User-Designentscheidung:** Samla-Boxen bekommen unabhaengig von der Anbringungsart (Stirn / Front / Deckel) das gleiche Label-Layout `qr_two_lines`. Die 6 Original-Templates `samla-stirntag-12/24/62mm` + `samla-deckel-12/24/62mm` werden durch eine einzige Hangar-Category "Samla" mit `content_type: qr_two_lines` ersetzt.

### Validation-Regeln

**Schema-Anpassung erforderlich:** Im bestehenden Backend sind `LabelData.title`, `LabelData.primary_id` und `LabelData.qr_payload` als required Pydantic-Felder modelliert. Mit 7 ContentTypes die jeweils nur einen Teil der Felder benoetigen (z.B. `qr_only` nur qr_payload, `text_one_line` nur primary_id), wuerde Pydantic-Validation bereits 422 werfen bevor die Engine-Validation greift.

**Loesung:** In Phase 1k.1a werden die Felder im `LabelData`-Basismodell **optional** gemacht (`str | None = None`). Die ContentType-spezifischen Pflichtfeld-Checks passieren **zentral in `LayoutEngine._validate_data(content_type, data)`** als ContentTypeDataMismatchError (422). `source_app` bleibt das einzige zwingend gesetzte Feld auf Datenebene.

Pflichtfeld-Matrix (gepueft in `_validate_data`):

| ContentType | qr_payload | primary_id | title | secondary | items | source_app |
|-------------|-----------|------------|-------|-----------|-------|------------|
| `qr_only` | erforderlich | — | — | — | — | erforderlich |
| `qr_one_line` | erforderlich | erforderlich | — | — | — | erforderlich |
| `qr_two_lines` | erforderlich | erforderlich | erforderlich | — | — | erforderlich |
| `qr_three_lines` | erforderlich | erforderlich | erforderlich | mind. 1 Eintrag | — | erforderlich |
| `text_one_line` | — | erforderlich | — | — | — | erforderlich |
| `text_two_lines` | — | erforderlich | erforderlich | — | — | erforderlich |
| `qr_with_listing` | erforderlich | erforderlich (Header) | — | — | mind. 1 Item | erforderlich |

Bei Verstoss: `ContentTypeDataMismatchError(content_type, missing_fields)` -> 422. Felder die nicht erforderlich sind, werden beim Rendern ignoriert (nicht abgelehnt).

## 3. TapeGeometry (alle 7 Tape-Groessen)

Pixel-Werte aus Brother Pin-Konfiguration (PT-Serie 180 DPI, QL 300 DPI). Die 12mm-Zeile ist empirisch validiert (Phase 1i V4-Winner). Die anderen Zeilen sind via Pixel-Ratio extrapoliert und werden nach Implementation per Smoke-Test validiert.

**Wichtig:** `tape_mm` ist konsistent mit dem bestehenden Backend (`TapeSpec.width_mm: int`, SNMP-Parsing `int`) als **Integer** modelliert. Die kleinste PT-TZe-Tape-Groesse ist **4mm** (24 Print-Pins), nicht 3.5mm.

`qr_max_px` folgt der allgemeinen Formel `printable_px - 2 * qr_padding_px` — damit ist die Geometrie pro Eintrag konsistent und nicht abhaengig von einem hardgecodeten Padding.

`text_start_x` ist die **absolute Pixel-X-Position** ab dem linken Tape-Rand. Sie liegt logisch hinter dem QR-Block plus einem Gap von `2 * qr_padding_px` (symmetrisches Padding: einmal vor dem QR, das QR selbst, dann noch einmal das Padding als Trenn-Gap zum Text). Damit gilt die Formel `text_start_x = qr_padding_px + qr_max_px + 2 * qr_padding_px = printable_px + qr_padding_px`. Bei reinen Text-ContentTypes ohne QR (text_one_line, text_two_lines) wird `text_start_x` ignoriert — Text rendert ab `qr_padding_px` links.

```python
# backend/app/schemas/tape_geometry.py

from pydantic import BaseModel, ConfigDict, Field


class TapeGeometry(BaseModel):
    """Render-Parameter pro Tape-Groesse (alle Werte in Pixel)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    printable_px: int = Field(gt=0)            # Brother Pin-Count fuer die Tape-Groesse
    qr_max_px: int = Field(gt=0)               # printable_px - 2 * qr_padding_px (Quadrat fuer QR)
    qr_padding_px: int = Field(ge=0)           # Padding um den QR-Code (auch Gap zur ersten Text-Zeile)
    text_start_x: int = Field(ge=0)            # Absolute X-Position wo Text nach QR beginnt
    line_spacing_px: int = Field(ge=0)         # Vertikaler Abstand zwischen Text-Zeilen
    font_xl: int = Field(gt=0)                 # primary_id Groesse
    font_l: int = Field(gt=0)                  # title Groesse
    font_m: int = Field(gt=0)                  # listing item Groesse
    font_s: int = Field(gt=0)                  # secondary Groesse


# tape_mm als int — konsistent mit TapeSpec.width_mm und SNMP-Parsing
TAPE_GEOMETRY: dict[int, TapeGeometry] = {
    4:   TapeGeometry(printable_px=24,  qr_max_px=20,  qr_padding_px=2, text_start_x=26,  line_spacing_px=1,  font_xl=8,   font_l=7,  font_m=6,  font_s=5),
    6:   TapeGeometry(printable_px=32,  qr_max_px=28,  qr_padding_px=2, text_start_x=34,  line_spacing_px=2,  font_xl=10,  font_l=9,  font_m=7,  font_s=6),
    9:   TapeGeometry(printable_px=50,  qr_max_px=46,  qr_padding_px=2, text_start_x=52,  line_spacing_px=3,  font_xl=14,  font_l=12, font_m=10, font_s=8),
    12:  TapeGeometry(printable_px=70,  qr_max_px=66,  qr_padding_px=2, text_start_x=72,  line_spacing_px=4,  font_xl=22,  font_l=18, font_m=14, font_s=10),  # V4-Winner
    18:  TapeGeometry(printable_px=112, qr_max_px=108, qr_padding_px=2, text_start_x=114, line_spacing_px=6,  font_xl=32,  font_l=26, font_m=20, font_s=14),
    24:  TapeGeometry(printable_px=128, qr_max_px=124, qr_padding_px=2, text_start_x=130, line_spacing_px=8,  font_xl=36,  font_l=30, font_m=24, font_s=18),
    62:  TapeGeometry(printable_px=696, qr_max_px=688, qr_padding_px=4, text_start_x=700, line_spacing_px=20, font_xl=120, font_l=96, font_m=72, font_s=48),  # QL 300 DPI
}
```

### Empirische Validierung post-Deploy

12mm-Werte aus Phase 1i V4-Winner sind scan-verifiziert (siehe Issue #103 Issue-Kommentar fuer Detailwerte).

**Extrapolations-Methodologie fuer 4/6/9/18/24/62mm:**
1. **Font-Groessen** (`font_xl`, `font_l`, `font_m`, `font_s`): via Pixel-Ratio `new_value = round(12mm_value * new_printable_px / 70)`, dann auf sinnvolle Lesbarkeit-Grenzen geclamped (Minimum 5px fuer 4mm).
2. **`qr_padding_px`**: bewusst konstant bei `2` fuer 4-24mm Tape; auf `4` erhoeht fuer 62mm (hoehere DPI, mehr Platz). Kein lineares Scaling.
3. **`line_spacing_px`**: via Ratio extrapoliert, dann auf Ganzzahl-Werte gerundet.
4. **`text_start_x`**: deterministisch berechnet als `printable_px + qr_padding_px` (folgt der Formel aus dem Header-Block dieser Sektion).
5. **`qr_max_px`**: deterministisch berechnet als `printable_px - 2 * qr_padding_px`.

Smoke-Test als Follow-up-Issue: jede Tape-Groesse einmal mit `qr_two_lines` drucken, Lesbarkeit pruefen, ggf. Werte korrigieren. User hat 24mm-Tapes und QL-Rollen verfuegbar.

## 4. Layout-Engine API

```python
# backend/app/services/layout_engine.py

from PIL import Image
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY


class LayoutEngine:
    """Rendert Labels semantisch pro Tape-Groesse + ContentType.

    Ersetzt LabelRenderer komplett. Keine Templates mehr — Engine kennt
    alle Kombinationen von TapeGeometry x ContentType.
    """

    def render(
        self,
        tape_mm: int,
        content_type: ContentType,
        data: LabelData,
    ) -> Image.Image:
        """Render-Pfad: tape_mm + content_type + data -> PIL Image.

        Raises UnsupportedTapeError wenn tape_mm nicht in TAPE_GEOMETRY.
        Raises ContentTypeDataMismatchError wenn data Pflichtfelder fehlen.
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
```

Jede `_render_*`-Methode ist klein (<30 Zeilen), nutzt nur `geometry` + `data`, und gibt ein PIL-Image zurueck dessen Hoehe `geometry.printable_px` entspricht. Die Breite wird durch Inhalt und Whitespace-Trim bestimmt (analog Phase 1i LabelRenderer-Verhalten).

Fuer `qr_three_lines`: rendert `primary_id` (XL, oben), `title` (L, mittig), und den ersten Eintrag von `secondary` (S, unten). Weitere `secondary`-Eintraege werden ignoriert — falls Use Cases mit 2+ secondary-Zeilen aufkommen, wird ein separater ContentType `qr_with_listing` oder eine zukuenftige `qr_four_lines`-Variante erstellt.

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
+-- content_type.py         # ContentType Enum (7 Werte)
backend/app/services/
+-- layout_engine.py        # LayoutEngine.render() + 7 _render_*-Methoden
backend/tests/unit/services/
+-- test_layout_engine.py   # Unit-Tests pro ContentType x Tape-Groesse
```

### Modifizierte Files (vervollstaendigt nach ops-agent + Copilot Review)

```
backend/app/schemas/
*-- label_data.py           # + items: tuple[LabelDataItem, ...] = () und ggf. secondary-Validation
+-- label_data_item.py      # NEU — LabelDataItem(item: str, qr_payload: str | None = None)
backend/app/services/
*-- print_service.py        # submit_job: render via LayoutEngine (statt LabelRenderer); TapeMismatchError-Pfad raus
*-- print_queue.py          # _process_job: nutzt content_type statt template
                            # KRITISCH: _rerender_from_db Recovery-Pfad migrieren —
                            # statt TemplateLoader+LabelRenderer jetzt LayoutEngine.render() mit
                            # gespeicherten content_type + rendered_tape_mm + data Snapshot
*-- batch_dispatch.py       # MixedTapeSizesError loeschen (in 1k.2 eingefuehrt, jetzt obsolet);
                            # Tape-Konsistenz-Check raus, alle Items rendern auf loaded_tape_mm
backend/app/services/
*-- svg_renderer.py         # SVG-Pfad analog LayoutEngine — render(tape_mm, content_type, data) -> SVG;
                            # falls SVG-Output noch genutzt wird (Preview-Endpoint, Tests)
backend/app/api/routes/
*-- print.py                # Request-Schema: content_type: ContentType, kein template_id mehr;
                            # on_tape_mismatch-Feld geloescht (Pfad obsolet, siehe unten)
*-- batch.py                # items[].content_type statt items[].template_id;
                            # MixedTapeSizesError 400-Mapping geloescht
*-- jobs.py                 # POST /jobs/{job_id}/resume Route loeschen (PAUSED-Pfad obsolet);
                            # Job-Schema content_type + rendered_tape_mm zurueckgeben
backend/app/exceptions/
*-- error_handlers.py       # TapeMismatchError + MixedTapeSizesError Handler entfernen;
                            # UnsupportedTapeError + NoTapeLoadedError + ContentTypeDataMismatchError registrieren
backend/app/main.py         # Router-Registrierungen: /api/templates Router entfernen;
                            # imports von TemplateLoader entfernen
backend/app/lifespan.py     # Template-Seed-Load beim Startup entfernen;
                            # falls TemplateLoader.preload() aufgerufen wird, weg
```

### Geloeschte Files

```
backend/app/services/label_renderer.py       # ersetzt durch LayoutEngine
backend/app/services/template_loader.py      # Templates obsolet
backend/app/schemas/template.py              # v1 Schema obsolet
backend/app/schemas/template_read.py         # Read-Schema obsolet (kein API mehr)
backend/app/models/template.py               # SQLAlchemy-Model obsolet
backend/app/repositories/templates.py        # Repository obsolet (templates Tabelle dropped)
backend/app/api/routes/templates.py          # /api/templates/* komplett weg
backend/app/api/routes/templates_preview.py  # /api/templates/{key}/preview-* weg
backend/app/seed/templates/*.yaml            # alle 21 YAML-Files
backend/tests/**/test_template*              # alle Template-Tests
backend/tests/**/test_label_renderer*        # alle alten Renderer-Tests
backend/tests/**/test_svg_renderer*          # SVG-Renderer-Tests gegen v1 Schema
```

### Obsolete Konzepte (komplette Pfade entfernen)

| Konzept | Bisheriger Code-Pfad | Was passiert |
|---------|---------------------|--------------|
| `TapeMismatchError` | `print_service.py:94`, `:235`, `error_handlers.py` | Klasse + Handler geloescht — Engine rendert immer auf `loaded_tape_mm` |
| `on_tape_mismatch=queue\|fail` PrintRequest-Feld | `routes/print.py`, `routes/batch.py` | Feld geloescht — alle Requests verhalten sich wie "auto-scale" |
| PAUSED-Job State | `print_queue.py`, `JobStateMachine` | State + Transitions geloescht — Jobs sind QUEUED/PRINTING/COMPLETED/FAILED/**CANCELLED** (CANCELLED-State BLEIBT erhalten — wird durch Cancel-Operation gesetzt, unabhaengig vom PAUSED-Pfad) |
| `POST /jobs/{job_id}/resume` Route | `routes/jobs.py:230` UND `routes/print.py` (separater Endpoint im on_tape_mismatch-PAUSED-Workflow) | Beide Routes geloescht — Resume war nur fuer PAUSED-Jobs noetig |
| `MixedTapeSizesError` | `batch_dispatch.py`, `routes/batch.py:60+` | Klasse + 400-Mapping geloescht — Batches mit gemischten ContentTypes rendern alle auf gleiche `loaded_tape_mm` |

### Neue/geanderte Routes

| Route | Methode | Aenderung |
|-------|---------|-----------|
| `/api/print/{slug}` | POST | Request hat `content_type: ContentType`, `data: LabelData`, `options: PrintOptions` — `template_id` und `on_tape_mismatch` Felder geloescht |
| `/api/print/{slug}/batch` | POST | items[] mit `content_type`, kein `template_id`, kein `on_tape_mismatch` |
| `/api/render/preview` | **POST** | **POST mit JSON-Body** `{content_type, tape_mm, data, format: "png"\|"svg"}`. GET ist ungeeignet weil `qr_with_listing` mit `items: tuple[LabelDataItem,...]` URL-Length-Limits sprengt (proxy/browser caching/escaping-Issues) |
| `/api/templates/*` | alle | komplett geloescht (Route-File weg) |
| `/api/templates/{key}/preview-png` | GET | geloescht |
| `/api/templates/{key}/preview-svg` | GET | geloescht |
| `/api/jobs/{job_id}/resume` | POST | geloescht (PAUSED-State obsolet) |

### DB-Migration (Alembic)

**Korrektur aus ops-agent Review:** Die bestehende Spalte heisst `template_key` (nicht `template_id`). Das `drop_column("template_id")` Beispiel war falsch.

**Korrektur aus Gemini Review:** SQLite unterstuetzt `drop_column` nicht direkt — `op.batch_alter_table` ist Pflicht.

**Korrektur aus Copilot Review CP-9:** Statt `content_type=NULL` zu lassen, backfillen wir deterministisch aus dem strukturierten `template_key`.

**Designentscheidung aus Copilot Review R3-4:** Die Spalte `jobs.template_key` BLEIBT als Audit-/Debug-Information erhalten. Sie ist im bestehenden Backend als "snapshot string — survives template deletion" dokumentiert, wird in `JobRead` API ausgegeben und enthaelt auch Nicht-Seed-Keys wie `spoolman/<id>` oder `grocy/<id>`. Nur die `templates` Tabelle wird gedroppt (keine Templates mehr). `template_key` wird ueber das Schema-Update nullable (neue Jobs ab 1k.1a haben `template_key=NULL`, aber `content_type` + `rendered_tape_mm` gesetzt).

Neue Migration `XXXX_drop_templates_table_and_add_content_columns.py`:
```python
def upgrade() -> None:
    # 1) Neue Spalten in jobs hinzufuegen — content_type + rendered_tape_mm
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("content_type", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("rendered_tape_mm", sa.Integer, nullable=True))
        # 2) template_key: NOT NULL Constraint entfernen (neue Jobs setzen es nicht
        #    mehr, alte Jobs behalten ihren Wert als Audit-Trail)
        batch_op.alter_column("template_key", nullable=True)

    # 3) Deterministisches Backfill basierend auf bekanntem Seed-Template-Schema.
    #    HINWEIS: template_key kann auch nicht-Seed-Werte enthalten (z.B. Webhook-
    #    Erzeugte Jobs wie "spoolman/<id>" oder "grocy/<id>"). Diese matchen keinen
    #    der CASE-Patterns und behalten content_type=NULL. Das Frontend zeigt
    #    template_key zusaetzlich an, sodass die historische Information sichtbar
    #    bleibt.
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE jobs SET
            content_type = CASE
                WHEN template_key LIKE 'qr-only-%'             THEN 'qr_only'
                WHEN template_key LIKE 'samla-%'               THEN 'qr_two_lines'
                WHEN template_key IN ('hangar-furniture-12mm', 'grocy-12mm',
                                       'snipeit-12mm', 'spoolman-12mm')
                                                                THEN 'qr_two_lines'
                WHEN template_key IN ('hangar-furniture-18mm', 'hangar-furniture-24mm',
                                       'grocy-18mm', 'grocy-24mm',
                                       'snipeit-18mm', 'snipeit-24mm',
                                       'spoolman-18mm', 'spoolman-24mm')
                                                                THEN 'qr_three_lines'
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

    # 4) templates Tabelle entfernen — nicht mehr genutzt nach Hard-Cut.
    #    template_key bleibt als Snapshot-Spalte in jobs erhalten.
    op.drop_table("templates")


def downgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String, unique=True),
        # ... ursprueengliche Spalten
    )
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("template_key", nullable=False)  # zurueck zu NOT NULL
        batch_op.drop_column("content_type")
        batch_op.drop_column("rendered_tape_mm")
```

**JobRead API-Schema** (nach 1k.1a):
- `content_type: ContentType | None` — fuer neue Jobs gesetzt; fuer historische Jobs aus Backfill bestimmt; NULL nur fuer non-matching template_keys
- `rendered_tape_mm: int | None` — analog
- `template_key: str | None` — Audit-Snapshot, NULL fuer neue Jobs, gesetzt fuer historische Jobs

Frontend zeigt fuer historische Jobs zusaetzlich den `template_key` als Hint (z.B. tooltip "Original template: spoolman/abc-123"), damit die Provenance erkennbar bleibt.

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
| `cmd/hangar/main.go:768` | Preview-Proxy umgebaut: `/admin/print/preview/{template_id}` -> `POST /admin/print/preview` mit JSON-Body `{content_type, tape_mm, data, format}`. Forward auf Hub `POST /api/render/preview` (Body durchreichen). GET-Variante mit Query-String wuerde URL-Length-Limits sprengen bei `qr_with_listing`. |
| `internal/hub/example-layouts.yaml` | Komplett neu geschrieben (siehe unten); wird in Phase 1k.1c durch Go-Defaults abgeloest |
| `internal/templates/print_form.templ` | Template-Picker raus (er war eh nur einer pro Category) |
| `cmd/hangar/main_test.go` + `internal/generator/print_test.go` | Tests auf neue Felder umgestellt |

### Neue example-layouts.yaml (Uebergangs-Loesung)

User-Entscheidung: Samla-Boxen bekommen unabhaengig von der Anbringung (Stirn/Front/Deckel) das gleiche Label-Layout. **Eine Category "Samla"** statt drei separate.

**Wichtig:** Die YAML-Datei ist eine Zwischen-Loesung fuer Phase 1k.1b. Phase 1k.1c migriert die Categories vollstaendig in die DB mit **in Go-Code definierten Defaults** (siehe Sektion 7). Nach Phase 1k.1c gibt es keinen YAML-Pfad mehr — `HUB_LAYOUTS_PATH` Environment-Variable wird deprecated und in einer Folge-Phase entfernt.

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
  Samla:                                  # UNIFIED: alle Samla-Varianten (Stirn/Front/Deckel)
    printer_slug: brother-ql820
    content_type: qr_two_lines
    quantity_default: 1
```

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
POST   /admin/print/categories/preview            # HTMX-Endpoint mit JSON-Body, forwarded an Hub
                                                  # Body: {content_type, tape_mm, data, format}
                                                  # Consistent mit Hub-Endpoint (POST wegen URL-Length
                                                  # bei qr_with_listing items)
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
1. `content_type` Dropdown (qr_only / qr_one_line / qr_two_lines / **qr_three_lines** / text_one_line / text_two_lines / qr_with_listing — alle 7 Werte)
2. Optionale Sample-Daten (primary_id, title, secondary, items) — defaults aus ContentType-Definition

HTMX-Trigger: `change`-Event auf Form-Felder -> `POST /admin/print/categories/preview` mit JSON-Body -> Hub `POST /api/render/preview` -> SVG zurueck -> in Preview-Pane.

Preview-Pane zeigt 3 SVGs side-by-side: 12mm, 18mm, 24mm (oder 62mm wenn QL-Drucker). Per Tab oder Stack-Layout je nach Viewport.

### Initial-Seeding via Go-Defaults (kein YAML mehr)

**User-Designentscheidung:** Hangar shipped mit eingebauten Default-Categories direkt im Go-Code. Die `HUB_LAYOUTS_PATH` Env-Variable und `hub-layouts.yaml` wird obsolet.

```go
// internal/category/defaults.go
package category

// DefaultCategories: Initial-Set fuer frische Installationen.
// Diese werden beim ersten Start in die DB geschrieben (wenn Tabelle leer ist).
// Nach erfolgreicher Initialisierung der Datenbank werden zuerst die Moebel-Typen
// initialisiert, danach diese Categories.
var DefaultCategories = []Category{
    {Name: "Kallax-Fach",            PrinterSlug: "brother-p750w", ContentType: "qr_two_lines",     QuantityDefault: 1, SortOrder: 10},
    {Name: "Kallax-Regal",           PrinterSlug: "brother-p750w", ContentType: "qr_with_listing", QuantityDefault: 1, SortOrder: 20},
    {Name: "Alex-Schublade",         PrinterSlug: "brother-p750w", ContentType: "qr_two_lines",     QuantityDefault: 1, SortOrder: 30},
    {Name: "Schreibtisch-Schublade", PrinterSlug: "brother-p750w", ContentType: "qr_two_lines",     QuantityDefault: 1, SortOrder: 40},
    {Name: "Billy-Ebene AK",         PrinterSlug: "brother-p750w", ContentType: "qr_two_lines",     QuantityDefault: 1, SortOrder: 50},
    {Name: "Billy-Ebene VK",         PrinterSlug: "brother-p750w", ContentType: "qr_two_lines",     QuantityDefault: 1, SortOrder: 60},
    {Name: "Samla",                  PrinterSlug: "brother-ql820", ContentType: "qr_two_lines",     QuantityDefault: 1, SortOrder: 70},
}
```

**Seed-Reihenfolge beim ersten Start:**
1. DB-Schema initialisieren (GORM auto-migrate)
2. Moebel-Typen (bestehend, aus `internal/catalog/`) initialisieren falls leer
3. **`DefaultCategories` in `print_categories` schreiben falls Tabelle leer**
4. Log: `"Seeded N default print categories"`

Nach Initial-Seed: User aendert Categories ueber Admin-UI (1k.1c CRUD-Editor). Default-Set ist nur bei frischer DB relevant; bestehende DBs werden nicht ueberschrieben.

**YAML-Konfig-Pfad (`HUB_LAYOUTS_PATH` / `example-layouts.yaml`):**
- Wird in Phase 1k.1c **als deprecated markiert** im Code (Log-Warning beim Start: "HUB_LAYOUTS_PATH is deprecated and ignored. Use Admin-UI to manage categories.")
- In einer Folge-Phase (kein Issue noetig, kleiner Cleanup): YAML-Lese-Code und Env-Variable komplett entfernen
- Test-Files unter `internal/hub/` die YAML laden: in 1k.1c geloescht oder auf Go-Defaults umgestellt

### Tests

| Test-Layer | Coverage |
|-----------|----------|
| Unit | CategoryService CRUD, Validation, sort_order-Reorder, Default-Seed-Idempotency |
| Integration | HTTP-Routes mit auth-required Middleware, CSRF |
| HTMX-Integration | Preview-Endpoint (POST mit JSON-Body) liefert valide SVG-Response |
| Initial-Seed | Bei leerer DB: nach DB-Init existieren genau N Categories aus DefaultCategories. Bei bestehender DB: keine Aenderung |

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

- [ ] `TapeGeometry` (Pydantic mit `Field(gt=0)/Field(ge=0)` Constraints) + `TAPE_GEOMETRY: dict[int, TapeGeometry]` fuer 7 Tape-Groessen (4/6/9/12/18/24/62mm)
- [ ] `ContentType` Enum mit 7 Werten (qr_only, qr_one_line, qr_two_lines, qr_three_lines, text_one_line, text_two_lines, qr_with_listing)
- [ ] `LayoutEngine.render(tape_mm: int, content_type, data)` implementiert alle 7 ContentTypes
- [ ] `LabelData` Schema-Anpassung: `title`, `primary_id`, `qr_payload` werden auf optional gesetzt (`str | None = None`); ContentType-spezifische Pflichtfeld-Validation zentral in `LayoutEngine._validate_data()`; nur `source_app` bleibt zwingend gesetzt
- [ ] `LabelData.items` Erweiterung + `LabelDataItem`-Klasse
- [ ] Routes `/api/print/*` umgebaut auf `content_type`; `template_id` und `on_tape_mismatch` Felder entfernt
- [ ] `/api/render/preview` umgebaut auf **POST mit JSON-Body** `{content_type, tape_mm, data, format}`
- [ ] Routes `/api/templates/*` komplett entfernt
- [ ] `POST /api/jobs/{job_id}/resume` entfernt (PAUSED-State obsolet)
- [ ] Alle 21 YAML-Templates geloescht
- [ ] `LabelRenderer`, `TemplateLoader`, `template.py` Schema geloescht
- [ ] **`print_queue.py._rerender_from_db`** Recovery-Pfad migriert: nutzt jetzt `LayoutEngine.render(rendered_tape_mm, content_type, data)` statt TemplateLoader+LabelRenderer (KRITISCH — sonst sind alle bestehenden Recovery-Operationen broken)
- [ ] `batch_dispatch.py` `MixedTapeSizesError` + Tape-Konsistenz-Check entfernt
- [ ] `error_handlers.py` alte Errors (TapeMismatchError, MixedTapeSizesError) entfernt; neue (UnsupportedTapeError, NoTapeLoadedError, ContentTypeDataMismatchError) registriert
- [ ] `main.py` Router-Registrierungen + Imports aufgeraeumt (kein TemplateLoader mehr)
- [ ] `lifespan.py` Template-Preload entfernt
- [ ] `svg_renderer.py` analog migriert oder geloescht (je nach SVG-Use)
- [ ] Alembic-Migration: `templates` Tabelle drop + `jobs.content_type` + `jobs.rendered_tape_mm` add via `op.batch_alter_table` (SQLite-kompatibel) mit deterministischem Backfill aus `template_key`. `jobs.template_key` BLEIBT als nullable Audit-Spalte erhalten (snapshot survives template deletion, sichtbar in JobRead API)
- [ ] Tests gruen, Coverage >=90% auf neuen Modulen
- [ ] Smoke-Test: 12mm V4-Baseline visuell identisch
- [ ] Refs #103, Closes #81 (7e-Spec subsumiert)

### Phase 1k.1b

- [ ] `LayoutMapping` struct: `TemplateID` -> `ContentType`
- [ ] `PrintRequest` struct: `template_id` -> `content_type`
- [ ] `example-layouts.yaml` als Uebergangs-Loesung umgeschrieben (7 ContentTypes inkl. qr_three_lines + `Kallax-Regal` + unified "Samla") — wird in 1k.1c durch Go-Defaults abgeloest
- [ ] Preview-Proxy-Route umgebaut: `POST /admin/print/preview` mit JSON-Body, forward auf Hub `POST /api/render/preview`
- [ ] `print_form.templ` Template-Picker entfernt
- [ ] Tests gruen
- [ ] Smoke: Kallax-Fach-Print identisch zu pre-Migration
- [ ] Refs #103

### Phase 1k.1c

- [ ] DB-Schema `print_categories` + GORM-Model
- [ ] `CategoryService` mit CRUD-API
- [ ] Routes `/admin/print/categories/*` mit Auth-Middleware
- [ ] Templates: List, Add, Edit, Preview-Pane (Dropdown enthaelt alle **7 ContentTypes inkl. qr_three_lines**)
- [ ] HTMX Live-Preview-Endpoint **POST mit JSON-Body** mit Hub-Forwarding (statt GET, konsistent mit Hub-Endpoint)
- [ ] **`internal/category/defaults.go`** mit `DefaultCategories` Slice (Go-Code, KEIN YAML)
- [ ] Initial-Seed-Logik beim ersten Start: nach DB-Init und Moebel-Typen-Seed → schreibt `DefaultCategories` in `print_categories` wenn Tabelle leer
- [ ] **`HUB_LAYOUTS_PATH` Env-Variable + YAML-Lese-Code deprecated** mit Warning-Log; YAML-File wird ignoriert
- [ ] `internal/hub/example-layouts.yaml` und zugehoeriger YAML-Loader-Code entweder geloescht oder als deprecated markiert
- [ ] Tests: Service-Unit + HTTP-Integration + HTMX-Integration + Initial-Seed-Idempotency
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

**ContentType-Auswahl:** 7 Types decken alle bisherigen 21 Templates ab plus Kallax-Aggregation aus 7e plus 3-Zeilen-Layouts (qr_three_lines fuer grocy/snipeit/spoolman 18/24mm + hangar-furniture 18/24mm). Validation-Regeln sind explizit, source_app als bestehendes Pflichtfeld erwaehnt.

**Samla-Unifikation:** Auf User-Wunsch werden alle 6 Samla-Templates (Stirntag/Deckel x 12/24/62mm) auf eine einzige Hangar-Category "Samla" mit `content_type: qr_two_lines` reduziert.

**Tape-Independence:** Eliminiert TapeMismatchError aus Print-Pfad. Edge-Case "unsupported tape_mm" wird durch defensiv eingebaute Errors gefangen (sollte mit 7 Groessen praktisch nicht auftreten).

**Migration:** DB-Migrationen nutzen `op.batch_alter_table` fuer SQLite-Kompatibilitaet. `jobs.content_type` wird beim Migrations-Run deterministisch aus `template_key` backfilled (kein Daten-Verlust fuer Historie). Hangar-YAML wird zur Seed-Quelle.

**Konsistenz mit Backend-Typen:** `tape_mm` als `int` durchgehend — kein `float`. Stimmt mit `TapeSpec.width_mm` und SNMP-Parsing ueberein.

**Out-of-Scope-Liste:** alle bekannten Versuchungen explizit ausgeschlossen (Multi-Printer-Model, WYSIWYG, Custom-Types, etc.).

---

### Review-Round 1 (PR #108 Findings adressiert)

Diese Spec wurde nach der ersten Review-Runde durch ops-agent, Gemini Code Assist und GitHub Copilot ueberarbeitet. Adressierte Findings:

**CRITICAL (8/8 adressiert):**
- C1 (ops-agent) — Hard-Cut-Liste in Sektion 5 vervollstaendigt: svg_renderer, templates_preview, batch_dispatch, main, lifespan, error_handlers + KRITISCH print_queue._rerender_from_db Recovery-Pfad explizit benannt
- C2 (ops-agent) — Alembic: `template_id` -> `template_key` korrigiert
- C3 (ops-agent) — Obsolete Konzepte Tabelle in Sektion 5 ergaenzt: TapeMismatchError, on_tape_mismatch, PAUSED-State, /jobs/{id}/resume, MixedTapeSizesError
- C4 (Copilot) — `tape_mm: int` durchgehend, `dict[int, TapeGeometry]`, 4mm statt 3.5mm (PT-TZe-Minimum)
- C5 (Copilot) — `qr_three_lines` als 7. ContentType fuer grocy/snipeit/spoolman 18/24mm + hangar-furniture 18/24mm
- C6 (Copilot) — `samla-stirntag-*` Mapping in Sektion 2 korrigiert zu `qr_two_lines` (haben QR); zusaetzlich User-Wunsch: Samla unified
- C7 (Copilot) — 62mm Werte korrigiert: `qr_max_px=688` (war 672) mit `qr_padding_px=4`
- C8 (Copilot) — Phase-1i-Smoke-Empirie-Pfad bleibt im Issue-Kommentar #103 erreichbar; im Spec wird darauf statt auf einen nicht-OS-Pfad verwiesen

**MEDIUM (7/7 adressiert):**
- M1 (Gemini) — Pydantic `Field(gt=0)/Field(ge=0)` Constraints in TapeGeometry
- M2 (Gemini) — `op.batch_alter_table` fuer SQLite-Kompatibilitaet
- M3 (Copilot) — `qr_max_px` Formel als `printable_px - 2 * qr_padding_px` im Sektion-3-Header beschrieben
- M4 (Copilot + ops-agent) — Preview-Endpoint von GET auf POST mit JSON-Body
- M5 (Copilot) — Deterministisches Backfill aus `template_key` in Migration
- M6 (ops-agent) — `text_start_x` als absolute X-Position erklaert
- M7 (ops-agent) — `source_app` Pflichtfeld in LabelData explizit in Validation-Regeln erwaehnt

LOW-Findings (3) und PRAISE (5) sind im PR-Kommentar archiviert.

### Review-Round 2 (PR #108 Findings adressiert) + User-Designentscheidung

Nach Round-1-Push hat Copilot eine zweite Review (commit 2545467) durchgefuehrt und 7 weitere Inkonsistenzen gefunden. Zusaetzlich kam eine User-Designentscheidung zum Initial-Seeding hinzu.

**Round-2 CRITICAL/MEDIUM (7/7 adressiert):**

- R2-1 (Copilot) — Sektion 5 File-Liste-Kommentare: "ContentType Enum (6 Werte)" + "6 _render_* Methoden" -> "7 Werte" / "7 _render_* Methoden"
- R2-2 (Copilot) — Sektion 7 1k.1c Dropdown-Liste: `qr_three_lines` als 4. Eintrag ergaenzt (war ausgelassen)
- R2-3 (Copilot) — Sektion 3 `text_start_x` Formel korrekt: Gap zur Text-Spalte ist `2 * qr_padding_px` (symmetrisches Padding um QR); Beispiel: 12mm = `qr_padding_px(2) + qr_max_px(66) + 2*qr_padding_px(4) = 72`; 62mm korrigiert auf `printable_px(696) + qr_padding_px(4) = 700` (war 696 — die Formel-Anwendung fehlte)
- R2-4 (Copilot) — Sektion 6 1k.1b Preview-Proxy: `cmd/hangar/main.go:768` jetzt `POST /admin/print/preview` mit JSON-Body statt Query-String, konsistent zur Hub-API
- R2-5 (Copilot) — Sektion 7 1k.1c Categories-Preview-Route: `POST /admin/print/categories/preview` mit JSON-Body
- R2-6 (Copilot) — Sektion 5 Alembic-Migration: `template_key` ist im aktuellen Schema NOT NULL und kann Nicht-Seed-Werte enthalten (z.B. Webhook-Erzeugte Jobs `spoolman/<id>`, `grocy/<id>`). Migration-Hinweis explizit ergaenzt — solche Eintraege bekommen `content_type=NULL` und werden im Frontend als "(legacy)" markiert
- R2-7 (Copilot) — Sektion 5 Obsolete-Konzepte-Tabelle: `POST /jobs/{job_id}/resume` existiert auch separat in `routes/print.py` (on_tape_mismatch=queue / PAUSED-Workflow) — beide Routes geloescht

**User-Designentscheidung (Round 2):**

Initial-Seeding der Hangar-Categories erfolgt ueber **Go-Code Defaults** (`DefaultCategories` Slice in `internal/category/defaults.go`), NICHT mehr ueber YAML. Reihenfolge beim ersten Start: DB-Init -> Moebel-Typen-Seed -> `DefaultCategories`-Seed. `HUB_LAYOUTS_PATH` und `hub-layouts.yaml` werden in 1k.1c deprecated und ignoriert. Ziel: YAML-freie Konfiguration, Categories sind ausschliesslich ueber Admin-UI editierbar.

Sektion 6 (1k.1b) markiert die YAML-Datei explizit als Uebergangs-Loesung. Sektion 7 (1k.1c) definiert `DefaultCategories` als Source-of-Truth fuer den frischen Start. Out-of-Scope-Sektion ergaenzt: vollstaendiges Entfernen des YAML-Lese-Codes ist in einer Folge-Phase nach 1k.1c (kein eigenes Issue noetig).

### Review-Round 3 (PR #108 Findings adressiert)

Nach Round-2-Push hat Copilot eine dritte Review (commit 9c877cb) durchgefuehrt und 4 weitere Findings gemeldet — davon 1 Designentscheidung (template_key behalten) und 3 Klarstellungen.

**Round-3 (4/4 adressiert):**

- R3-1 (Copilot) — PR-Beschreibung war veraltet (6 ContentTypes / 3.5mm). PR-Body wird parallel aktualisiert; in der Spec selbst hat sich nichts geaendert (Source of Truth war immer Spec, nicht PR-Body)
- R3-2 (Copilot) — Executive Summary explizit "4mm (nicht 3.5mm)" geschrieben um die historische Verwechslung zu adressieren
- R3-3 (Copilot) — Mapping-Tabelle in Sektion 2: `hangar-furniture-*-12mm` Wildcard war irrefuehrend (keine Wildcards im Repo). Aufgeloest in konkrete Eintraege `hangar-furniture-12mm` etc.
- R3-4 (Copilot, DESIGN-ENTSCHEIDUNG) — `jobs.template_key` Spalte wird NICHT gedroppt. Sie bleibt als nullable Audit-/Debug-Snapshot erhalten (Webhook-Keys wie `spoolman/<id>` waeren sonst nicht mehr rekonstruierbar; "survives template deletion" Eigenschaft bleibt erhalten). Migration NOT NULL -> nullable; neue Jobs setzen template_key=NULL aber content_type+rendered_tape_mm. Frontend zeigt template_key zusaetzlich als Provenance-Hint fuer historische Jobs

### Review-Round 4 (PR #108 Findings adressiert)

Nach Round-3-Push hat Copilot eine vierte Review (commit b10552a) durchgefuehrt und 4 weitere Klarstellungen gemeldet.

**Round-4 (4/4 adressiert):**

- R4-1 (Copilot) — Validation-Regeln Pre-Condition: bestehendes `LabelData` hat `title/primary_id/qr_payload` als required. Spec ergaenzt um expliziten Schema-Anpassungs-Schritt: Felder werden auf `str | None = None` umgestellt, ContentType-Validation passiert zentral in `LayoutEngine._validate_data()`. Pflichtfeld-Matrix als Tabelle in Sektion 2 ergaenzt
- R4-2 (Copilot) — Extrapolations-Methodologie pro Feld erklaert: Pixel-Ratio + Clamping fuer Fonts, konstantes qr_padding_px bei 2 (62mm: 4), deterministische Formeln fuer text_start_x und qr_max_px. Damit ist die Tabelle nachvollziehbar pflegbar
- R4-3 (Copilot) — Executive Summary explizit: "initiale Scope" von 7 Groessen; bestehende `TapeRegistry` kennt weitere QL-DK-Breiten (29/38/50/54mm) die in 1k.1 bewusst noch nicht abgedeckt sind -> `UnsupportedTapeError`; Erweiterung in Folge-Phase moeglich
- R4-4 (Copilot) — Import-Konvention angepasst: `from PIL.Image import Image` -> `from PIL import Image`, Return-Type `Image.Image` (konsistent mit Repo-Konvention)

### Review-Round 5 (PR #108 Findings adressiert)

Nach Round-4-Push hat Copilot eine fuenfte Review (commit c37d494) durchgefuehrt und 4 weitere Klarstellungen gemeldet — alle finishing touches.

**Round-5 (4/4 adressiert):**

- R5-1 (Copilot) — Geloeschte-Files-Liste vervollstaendigt: `backend/app/models/template.py` (SQLAlchemy-Model), `backend/app/repositories/templates.py` (Repository), `backend/app/schemas/template_read.py` (Read-Schema) wurden ergaenzt
- R5-2 (Copilot) — Obsolete-Konzepte-Tabelle: PAUSED-State-Entfernung impliziert NICHT CANCELLED-State-Entfernung. Klarstellung in der Tabelle: Jobs nach 1k.1a sind QUEUED/PRINTING/COMPLETED/FAILED/**CANCELLED** — der CANCELLED-State bleibt erhalten (durch Cancel-Operation gesetzt, unabhaengig vom PAUSED-Pfad)
- R5-3 (Copilot) — PR-Body weiterhin "6 ContentTypes" / "3.5mm" — Update aus Round 3 ist nicht persistiert (GraphQL-Warnung). Body wird via gh API erneut gesetzt
- R5-4 (Copilot) — Hardware-Baseline-Referenz im Spec-Header zeigte auf nicht existierenden Pfad `docs/site/operations/protokolle/...`. Korrigiert: Verweis auf Issue #103 Kommentar (oeffentlich verfuegbar) + Hinweis dass Original-Protokoll im privaten `homelab-management` Repo liegt
