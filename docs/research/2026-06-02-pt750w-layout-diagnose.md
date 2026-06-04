# Phase 1i Task A — PT-P750W Layout-Diagnose

**Datum:** 2026-06-02
**Autor:** Implementer-Subagent (Phase 1i Sub-Task A)
**Methode:** Bitmap-Preview-Endpoint + statische Code-Analyse

---

## Befund

### Bitmap-Dimensionen (Rendered vs. Erwartet)

| Tape | Hub-Canvas (TAPE_HEIGHT_PX) | ptouch print_pins | Differenz | y_offset im _prepare_image |
|------|----------------------------|-------------------|-----------|---------------------------|
| 12mm | 106px | 70px | +36px | -18px (Crop!) |
| 18mm | 165px | 112px | +53px | -27px (Crop!) |
| 24mm | 256px | 128px | +128px | -64px (Crop!) |

Gemessene Bitmap aus `GET /api/templates/hangar-furniture-12mm/preview-png`:

- **Größe:** 284 × 106px (nach Trim-Crop auf der Längsachse)
- **Erwartete Druckhöhe (ptouch native):** 70px
- **Überlauf:** 36px (Hub rendert 51,4% zu viel)

### Element-Clipping bei hangar-furniture-12mm

| Element | Hub-Position | y im print_pins-Container | Status |
|---------|-------------|---------------------------|--------|
| QR (size=75) | x=5, y=5..80 | y=-13..62 | **QR-Kopf 13px ABGESCHNITTEN** |
| primary_id (font=20) | x=90, y=12 | y=-6 | **TEXT ABGESCHNITTEN** |
| title (font=14) | x=90, y=50 | y=32 | sichtbar |

---

## Hypothese H1: DPI-Mismatch (Hub 300 DPI / Brother 180 DPI) — **BESTÄTIGT, HAUPTURSACHE**

### Analyse

Der LabelRenderer in `app/services/label_renderer.py` dokumentiert (Zeile 9):

```
Coordinate system: top-left origin, pixels at 300 DPI (brother_ql native).
```

Das ist **falsch** für den PT-P750W. Der PT-P750W arbeitet mit:

- `RESOLUTION_DPI = 180` (Standardauflösung)
- `RESOLUTION_DPI_HIGH = 360` (High-Resolution-Modus)
- `PIN_CONFIGS[Tape12mm].print_pins = 70` (bei 180 DPI)

Die `TAPE_HEIGHT_PX`-Tabelle im Hub verwendet jedoch `300 DPI`:

```python
TAPE_HEIGHT_PX: Final[dict[int, int]] = {
    12: 106,  # 12mm × 300/25.4 ≈ 142px ... aber warum 106?
    18: 165,
    24: 256,
    62: 696,
}
```

### Woher kommt der Wert 106?

`12mm × 300 DPI / 25.4 mm/inch ≈ 142px` wäre "korrekt" bei 300 DPI. Der Wert 106 entspricht keiner sauberen DPI-Berechnung. Er liegt zwischen 180 DPI (85px) und 300 DPI (142px) und entspricht dem ptouch-Wert für HeatShrinkTube 17.7mm (`print_pins=106`). Möglicherweise wurde `TAPE_HEIGHT_PX[12]=106` von einem anderen Kontext (brother_ql-Library, die eine andere Geometrie hat) übernommen.

### Was macht ptouch._prepare_image?

```python
def _prepare_image(self, image, tape_config):
    container_image = Image.new("RGB", (image.width, config.print_pins), (255, 255, 255))
    y = (config.print_pins - image.height) // 2  # Zentrieren
    container_image.paste(image, (0, y))
```

Bei `image.height=106` und `print_pins=70`:

```
y = (70 - 106) // 2 = -18
```

PIL `paste()` mit negativem y-Offset schneidet die oberen 18 Zeilen stillschweigend ab. Das erklärt:
- **QR oben abgeschnitten** (QR-Top bei y=-13 → 13px geclippt)
- **primary_id-Text fehlt** (Text-Top bei y=-6 → vollständig geclippt)

---

## Hypothese H2: TAPE_HEIGHT_PX falsch (mehr als druckbare Höhe) — **BESTÄTIGT, BEGLEITEND**

Die Template-YAML `hangar-furniture-12mm.yaml` enthält bereits den Hinweis:

```yaml
# 180 DPI: 12mm ≈ 85 px Höhe.
```

Der Kommentar ist korrekt. Der tatsächliche ptouch `print_pins`-Wert für 12mm bei 180 DPI ist **70px** (nicht 85px — 85 wäre 12mm × 180/25.4). Die 70 Pins sind die *physisch bedruckbaren Pins* des PT-P750W für 12mm Tape, die kleiner sind als die geometrisch berechnete Tapehöhe.

**Fazit:** `TAPE_HEIGHT_PX[12] = 106` ist um den Faktor `106/70 = 1.51` zu groß.

---

## Hypothese H3: ptouch_backend rotiert/skaliert falsch — **NICHT URSACHE**

`ptouch.LabelPrinter._prepare_image` zentriert das Bild vertikal und konvertiert zu 1-Bit. Es gibt keine Rotation und keine DPI-Skalierung in der Library — die Library übernimmt das Bild 1:1 in der gegebenen Auflösung und passt es in den `print_pins`-Container. Die Clipping-Ursache liegt also vollständig im Hub (falsche Canvas-Größe), nicht im ptouch-Backend.

---

## Hypothese H4: Hangar sendet primary_id leer — **UNERHEBLICH**

Auch wenn Hangar `primary_id` korrekt sendet, ist der Text-y-Wert im ptouch-Container negativ → geclippt. Das Problem existiert unabhängig vom gesendeten Wert.

---

## Fix-Empfehlung

### Option A (Empfohlen): TAPE_HEIGHT_PX auf ptouch print_pins anpassen + Templates neu layouten

```python
# app/services/label_renderer.py
TAPE_HEIGHT_PX: Final[dict[int, int]] = {
    12: 70,   # ptouch PTP750W print_pins für Tape12mm
    18: 112,  # ptouch PTP750W print_pins für Tape18mm
    24: 128,  # ptouch PTP750W print_pins für Tape24mm
    62: 696,  # QL endless — unverändert (kein PT-P750W)
}
```

Alle 15 Seed-Templates müssen ihre Element-Koordinaten an den kleineren Canvas (70px / 112px / 128px) anpassen.

### Option B: Render-Skalierung in LabelRenderer

Nach dem Rendern auf dem aktuellen Canvas das Bild auf `print_pins` skalieren:

```python
img = img.resize((img.width, print_pins), Image.LANCZOS)
```

**Nachteil:** Bilder werden bei Downscale unscharf. Texte und QR-Codes verlieren Lesbarkeit.

### Empfehlung

**Option A** ist die saubere Lösung. Template-Koordinaten sind semantisch auf die physische Druckfläche abzustimmen, nicht auf eine imaginäre 300 DPI Abstraktion. Die ptouch `print_pins`-Werte sind die Ground Truth.

---

## Auswirkung auf Sub-Task B (Task 10): Betroffene Templates

Alle 15 Seed-Templates sind betroffen. Elementweise Clipping-Analyse:

### 12mm Templates (Hub 106px → Printer 70px, y_offset=-18)

| Template | Element | Hub-y | Printer-y | Status |
|----------|---------|-------|-----------|--------|
| hangar-furniture-12mm | QR (size=75) | 5..80 | -13..62 | **QR-Kopf CLIP** |
| hangar-furniture-12mm | primary_id | 12 | -6 | **TEXT CLIP** |
| hangar-furniture-12mm | title | 50 | 32 | ok |
| grocy-12mm | QR (size=80) | 13..93 | -5..75 | **QR-Kopf CLIP** |
| grocy-12mm | primary_id | 18 | 0 | ok (Grenzfall) |
| grocy-12mm | title | 60 | 42 | ok |
| snipeit-12mm | QR (size=80) | 13..93 | -5..75 | **QR-Kopf CLIP** |
| snipeit-12mm | primary_id | 18 | 0 | ok (Grenzfall) |
| snipeit-12mm | title | 60 | 42 | ok |
| spoolman-12mm | QR (size=80) | 13..93 | -5..75 | **QR-Kopf CLIP** |
| spoolman-12mm | primary_id | 18 | 0 | ok (Grenzfall) |
| spoolman-12mm | title | 60 | 42 | ok |
| qr-only-12mm | QR (size=80) | 13..93 | -5..75 | **QR-Kopf CLIP** |

**12mm Fix-Schema:** Canvas von 106px auf 70px reduzieren. QR-Size auf max ~58px (bei y=5: 5+58=63 < 70). Text-Font-Größen entsprechend anpassen.

### 18mm Templates (Hub 165px → Printer 112px, y_offset=-27)

| Template | Element | Hub-y | Printer-y | Status |
|----------|---------|-------|-----------|--------|
| hangar-furniture-18mm | QR (size=110) | 8..118 | -19..91 | **QR-Kopf CLIP** |
| hangar-furniture-18mm | primary_id | 18 | -9 | **TEXT CLIP** |
| hangar-furniture-18mm | title | 75 | 48 | ok |
| grocy-18mm | QR (size=140) | 13..153 | -14..126 | **QR-Kopf + Bottom CLIP** |
| grocy-18mm | primary_id | 20 | -7 | **TEXT CLIP** |
| snipeit-18mm | QR (size=140) | 13..153 | -14..126 | **QR-Kopf + Bottom CLIP** |
| snipeit-18mm | primary_id | 20 | -7 | **TEXT CLIP** |
| spoolman-18mm | QR (size=140) | 13..153 | -14..126 | **QR-Kopf + Bottom CLIP** |
| spoolman-18mm | primary_id | 20 | -7 | **TEXT CLIP** |
| qr-only-18mm | QR (size=140) | 13..153 | -14..126 | **QR beidseitig CLIP** |

### 24mm Templates (Hub 256px → Printer 128px, y_offset=-64)

| Template | Element | Hub-y | Printer-y | Status |
|----------|---------|-------|-----------|--------|
| hangar-furniture-24mm | QR (size=150) | 10..160 | -54..96 | **QR-Kopf CLIP** |
| hangar-furniture-24mm | primary_id | 20 | -44 | **TEXT CLIP** |
| hangar-furniture-24mm | title | 100 | 36 | ok |
| grocy-24mm | QR (size=230) | 13..243 | -51..179 | **beidseitig CLIP** |
| grocy-24mm | primary_id | 20 | -44 | **TEXT CLIP** |
| snipeit-24mm | QR (size=230) | 13..243 | -51..179 | **beidseitig CLIP** |
| snipeit-24mm | primary_id | 20 | -44 | **TEXT CLIP** |
| spoolman-24mm | QR (size=230) | 13..243 | -51..179 | **beidseitig CLIP** |
| spoolman-24mm | primary_id | 20 | -44 | **TEXT CLIP** |
| qr-only-24mm | QR (size=230) | 13..243 | -51..179 | **beidseitig CLIP** |

**Zusammenfassung Sub-Task B:** Alle 15 Templates müssen angepasst werden. In Sub-Task B werden neue Koordinaten für alle Tape-Größen berechnet und die YAML-Dateien sowie `TAPE_HEIGHT_PX` aktualisiert.

---

## Referenzen

| Dokument | Pfad |
|----------|------|
| LabelRenderer | `backend/app/services/label_renderer.py` |
| TAPE_HEIGHT_PX | `backend/app/services/label_renderer.py:28` |
| ptouch PIN_CONFIGS | ptouch-Library `PTP750W.PIN_CONFIGS` |
| _prepare_image | ptouch-Library `LabelPrinter._prepare_image` |
| hangar-furniture-12mm.yaml | `backend/app/seed/templates/hangar-furniture-12mm.yaml` |
| Preview-Endpoint | `backend/app/api/routes/templates_preview.py` |
| Phase 1i Plan | Plan-Dokument Phase 1i |
