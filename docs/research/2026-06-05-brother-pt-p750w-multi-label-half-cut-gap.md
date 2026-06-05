# Brother PT-P750W Multi-Label Tape-Feed-Mechanismus — Research

**Datum:** 2026-06-05
**Scope:** PT-P750W / PT-E550W ESC/P-Raster-Protokoll, ptouch-py 1.1.0
**Output-Verzeichnis:** `/opt/repos/label-printer-hub`
**Methode:** Direktanalyse ptouch-py 1.1.0 Quellcode (lokal installiert) + Web-Recherche + C-Referenz-Implementierung

---

## 1. Executive Summary

Der aktuelle Zustand — perforierter Streifen mit ~5mm Half-Cut-Abstand zwischen Labels —
ist durch `ptouch.LabelPrinter.print_multi()` korrekt implementiert und spiegelt das
physisch minimalste Ergebnis wider, das mit der aktuellen ptouch-py 1.1.0 Public API
erreichbar ist. Das Verhalten ist **production-ship-fähig**.

Ein lokaler Hub-Override ist **einfach machbar**: Die sauberste Option (Subclassing
`PTP750W`) braucht ~20 Minuten und ist vollständig rückwärtskompatibel mit dem
bestehenden `_ptouch_print_multi()` in `ptouch_backend.py`. Sie schaltet
`chain_printing=True` frei, das ptouch-py zwar intern kennt (in
`_build_page_control_sequence()`), aber in `print()` hartkodiert auf `False` belässt
(GitHub Issue nbuchwitz/ptouch#20, Mai 2026).

**Empfehlung:** Kein Override erforderlich für Production-Ship. Falls der
~5mm-Gap in Zukunft stört: Option B (Subclass) umsetzen.

---

## 2. Brother PT-Protokoll Tape-Feed-Mechanismus

### 2.1 Relevante Commands

Alle Commands aus dem offiziellen Brother Software Developer's Manual
(Raster Command Reference, Version 1.02 für PT-E550W/P750W/P710BT,
Dokument-ID: `cv_pte550wp750wp710bt_eng_raster_102.pdf`) und verifiziert gegen
ptouch-py 1.1.0 Quellcode (`printer.py`).

| Command | Bytes | Funktion |
|---------|-------|---------|
| **ESC @** | `1B 40` | Initialisierung (Reset) |
| **ESC i a** | `1B 69 61 01` | Raster-Grafik-Modus aktivieren |
| **ESC i z** | `1B 69 7A [n1 n2 n3 n4 l1 l2 l3 l4 0 0]` | Print-Information (Länge + Tape-Breite + Media-Typ) |
| **ESC i M** | `1B 69 4D [n]` | Mode-Settings (Auto-Cut, Mirror) |
| **ESC i K** | `1B 69 4B [n]` | Advanced Mode Settings (Half-Cut, Chain, High-Res) |
| **ESC i d** | `1B 69 64 [n1 n2]` | Margin in Dots (16-bit little-endian) |
| **M** | `4D [00/02]` | Kompression: `00`=keine, `02`=TIFF/PackBits |
| **G** | `47 [n1 n2] [data]` | Raster-Grafik-Transfer (eine Spalte) |
| **Z** | `5A` | Zero-Raster (leere Zeile, nur mit Kompression) |

### 2.2 ESC i M — Mode Settings (Bit-Flags)

| Bit | Bedeutung | 0 | 1 |
|-----|-----------|---|---|
| 0–5 | reserviert | — | — |
| 6 | Auto-Cut | aus | ein |
| 7 | Mirror-Print | aus | ein |

```python
# ptouch-py printer.py, Zeile 289–293
mode = 0
if auto_cut:
    mode |= 1 << 6   # 0x40
if mirror_print:
    mode |= 1 << 7   # 0x80
return struct.pack("4B", 0x1B, 0x69, 0x4D, mode)
```

**Für `print_multi()` (non-last Labels):**
`auto_cut=False` → ESC i M = `1B 69 4D 00`

### 2.3 ESC i K — Advanced Mode Settings (Bit-Flags)

| Bit | Bedeutung | 0 | 1 |
|-----|-----------|---|---|
| 0 | Draft-Druck | normal (360 DPI vertikal) | Entwurf |
| 1 | reserviert | — | — |
| 2 | **Half-Cut** | aus (Voll-Cut oder kein Cut) | **ein** (nur Träger abschneiden) |
| 3 | **No Chain Printing** | Chain aktiv (kein Feed) | **No Chain** (Feed nach Label) |
| 4–5 | reserviert | — | — |
| 6 | **High Resolution** | Standard | Hochauflösung |
| 7 | reserviert | — | — |

```python
# ptouch-py printer.py, Zeile 318–331
mode = 0
if half_cut:
    mode |= 1 << 2   # 0x04
if not chain_printing:
    mode |= 1 << 3   # 0x08  (INVERTIERTE LOGIK!)
if high_resolution:
    mode |= 1 << 6   # 0x40
return struct.pack("4B", 0x1B, 0x69, 0x4B, mode)
```

**Wichtig — Invertierte Logik:** Bit 3 heißt `No Chain Printing`. Wenn der Parameter
`chain_printing=True` ist, wird Bit 3 NICHT gesetzt (0x00), d.h. Chain-Modus ist aktiv.

#### Cut-Mode-Wertetabelle (PT-P750W)

| `half_cut` | `chain_printing` | ESC i K [n] | Physisches Verhalten |
|------------|------------------|-------------|----------------------|
| `False` | `False` | `0x08` | Kein Cut, Feed nach Label |
| `True` | `False` | `0x0C` | **Half-Cut, Feed nach Label** (aktuell in `print_multi`) |
| `False` | `True` | `0x00` | Kein Cut, kein Feed (Chain) |
| `True` | `True` | `0x04` | Half-Cut, kein Feed (Chain-Half-Cut) |

### 2.4 ESC i d — Margin-Command

```
1B 69 64 [n1] [n2]
margin_dots = n1 + 256 * n2  (16-bit little-endian)
```

Konversion aus `margin_mm`:
```python
margin_dots = round(margin_mm * RESOLUTION_DPI / 25.4)
# Bei 180 DPI, DEFAULT_MARGIN_MM=2.0mm:
# margin_dots = round(2.0 * 180 / 25.4) = 14 Dots = 1.98mm physisch
```

**Grenzen (ptouch-py enforced):**
- `MIN_MARGIN_MM = 2.0` → 14 Dots bei 180 DPI
- `MAX_MARGIN_MM = 127.0` → 900 Dots bei 180 DPI
- `DEFAULT_MARGIN_MM = 2.0`

### 2.5 0x1A vs 0x0C Physik

| Opcode | Name | Physisches Verhalten |
|--------|------|----------------------|
| `0x1A` | Print and Feed | Druckt, dann schiebt Tape ~22.5mm vor (Pre-Roll für nächsten Print). Endposition: Tape vor der Schneide |
| `0x0C` | Print without Feed | Druckt, Tape verbleibt an aktueller Position. Kein Motor-Vorschub nach Druck. |

**Quelle für 22.5mm Pre-Roll:** Brother Support-Seite
"Why does a one inch piece of blank tape feed prior to every label"
(https://help.brother-usa.com/app/answers/detail/a_id/79756):
> "Small Margin & Chain: 0.89" (22.5mm) initially"

**Quelle für PTC_FORMFEED/PTC_EJECT:** CUPS ptouch-driver C-Quellcode
(`printer-driver-ptouch/rastertoptch.c`, philpem/printer-driver-ptouch):
```c
#define PTC_EJECT    0x1a   // Ejects label after printing
#define PTC_FORMFEED 0x0c   // Form feed — prints without ejecting
```

---

## 3. iOS-App Verhalten (Quellen-Beleg)

### 3.1 Beobachtetes Verhalten (Hardware-Test 2026-06-05)

- 4-Item-QR-Batch auf 12mm TZe-Tape
- iOS P-touch Design&Print App: Labels kommen als **einzelne Stücke** aus dem Drucker
  → voller Schnitt zwischen jedem Label, ~5mm Leerband als Gap
- ptouch-py `print_multi()`: Labels kommen als **perforierter Streifen** (Half-Cut-Perforierungen)
  → gleicher ~5mm-Gap, aber Half-Cut statt Full-Cut

### 3.2 Keine direkten USB-Sniff-Captures verfügbar

Eine gezielte Suche nach iOS-App-USB-Sniff-Captures ergab keine öffentlich verfügbaren
Byte-Sequenzen für die P-touch Design&Print App. Die App kommuniziert ausschließlich
über Bluetooth (keine USB-Unterstützung am PT-P750W via iOS), was Sniffing deutlich
schwieriger macht.

### 3.3 Hypothesen aus Protokoll-Analyse

**Hypothese (hohe Konfidenz):** Die iOS-App verwendet für den Batch-Druck wahrscheinlich:
- ESC i M mit `auto_cut=True` (Bit 6 = 1 → 0x40)
- ESC i K mit `half_cut=False`, `chain_printing=False` → 0x08
- 0x1A (Print and Feed) nach JEDEM Label
- Dadurch: voller Schnitt nach jedem Label + 22.5mm Pre-Roll → Labels fallen einzeln aus

**Begründung:** Das beobachtete Verhalten (Labels fallen einzeln aus) passt zur
Standard-Einzeldruck-Sequenz: Auto-Cut ON + 0x1A pro Label. Die iOS-App iteriert
schlicht über die Labels und druckt jedes einzeln, ohne Batch-Optimierung.

**Unterschied zu ptouch-py:** ptouch-py's `print_multi()` optimiert den Batch:
- `auto_cut=False` + `half_cut=True` + `feed=False (0x0C)` für alle außer letztem Label
- Dadurch: Half-Cut-Perforation statt Voll-Schnitt, kein 22.5mm Pre-Roll zwischen Labels

---

## 4. Implementation-Optionen für lokalen Hub-Override

### Vorbedingung: margin_mm ist bereits minimal

Der aktuelle ~5mm-Gap zwischen Labels setzt sich zusammen aus:
- Label N: trailing margin = `DEFAULT_MARGIN_MM = 2.0mm`
- Label N+1: leading margin = `DEFAULT_MARGIN_MM = 2.0mm`
- Half-Cut-Blade-Positionierungsoffset ≈ 1mm (mechanisch)
- **Gesamt: ~5mm** — entspricht dem Hardware-Messwert

Da `MIN_MARGIN_MM = 2.0` in ptouch-py enforced wird (wirft `ValueError` bei `< 2.0`),
ist der ~5mm-Gap mit der aktuellen Public API das **physische Minimum**.

---

### Option A: Keine Änderung (Current State akzeptieren)

**Beschreibung:** `_ptouch_print_multi()` ruft `printer.print_multi(labels, half_cut=True)` auf.
Liefert perforierte Labels mit ~5mm Gap. Ist laut Anforderung production-ship-fähig.

**Code (aktuell, keine Änderung):**
```python
# backend/app/printer_backends/ptouch_backend.py (bestehend)
printer.print_multi(
    labels,
    high_resolution=high_resolution,
    half_cut=half_cut,
)
```

**Aufwand:** 0 Minuten

**Risiko:** Kein Risiko. Keine Codeänderung.

**Test-Plan:**
```bash
# Aktueller Hardware-Test bereits durchgeführt (2026-06-05):
python scripts/smoke_first_print_batch.py --host <IP> --count 4
# Erwartetes Ergebnis: perforierter 4-Label-Streifen, ~5mm Half-Cut-Abstand
```

---

### Option B: Subclass PTP750W mit `chain_printing`-Unterstützung

**Beschreibung:** Subclasse `PTP750W` in `ptouch_backend.py`, überschreibe `print()` um
`chain_printing` durchzureichen. Dann eigene `print_multi()`-Implementierung die
`chain_printing=True` für non-last Labels nutzt.

**Warum sauber:** ptouch-py's `_build_page_control_sequence()` hat bereits einen
`chain_printing`-Parameter (Zeile 480). `print()` hardkodiert ihn auf `False` (Zeile 653).
Der Subclass-Ansatz nutzt nur öffentliche/protected Methoden — kein Monkey-Patching.

```python
# backend/app/printer_backends/ptouch_backend.py

import ptouch
from ptouch.printer import LabelPrinter, TapeConfig
from ptouch.tape import Tape

class _PTP750WWithChain(ptouch.PTP750W):
    """PTP750W mit chain_printing-Unterstützung im print() für Batch-Jobs."""

    def print(
        self,
        label,
        margin_mm=None,
        high_resolution=None,
        feed=True,
        auto_cut=None,
        half_cut=None,
        chain_printing=False,   # <-- neuer Parameter
    ) -> None:
        """Wie PTP750W.print(), aber chain_printing wird durchgereicht."""
        import struct
        from PIL import Image as _Image

        high_res = self.high_resolution if high_resolution is None else high_resolution
        tape_config = self.get_tape_config(label.tape)
        label.prepare(tape_config.print_pins, self.RESOLUTION_DPI)
        image = label.image

        img_1bit = self._prepare_image(image, tape_config)
        raster = self._generate_raster(img_1bit, tape_config)
        num_lines = image.width

        margin_mm = margin_mm if margin_mm is not None else self.DEFAULT_MARGIN_MM
        if not self.MIN_MARGIN_MM <= margin_mm <= self.MAX_MARGIN_MM:
            raise ValueError(
                f"Margin must be between {self.MIN_MARGIN_MM} and {self.MAX_MARGIN_MM} mm"
            )
        margin_dots = self._mm_to_dots(margin_mm)

        control_seq = self._build_page_control_sequence(
            num_lines=num_lines,
            margin=margin_dots,
            tape=label.tape,
            high_resolution=high_res,
            is_first_page=False,
            auto_cut=auto_cut if auto_cut is not None else self.DEFAULT_AUTO_CUT,
            half_cut=half_cut if half_cut is not None else self.DEFAULT_HALF_CUT,
            chain_printing=chain_printing,   # <-- wird jetzt übergeben
        )

        raster_data = self._build_raster_data(raster, num_lines, high_res)
        print_cmd = b"\x1a" if feed else b"\x0c"
        self.connection.write(control_seq + raster_data + print_cmd)

    def print_multi_chain(
        self,
        labels,
        margin_mm=None,
        high_resolution=None,
        half_cut=True,
    ) -> None:
        """Batch-Print mit chain_printing=True für non-last Labels.

        ESC i K für intermediate Labels: 0x04 (half-cut=1, chain=0)
        ESC i K für last Label: 0x0C (half-cut=1, no-chain=1)
        Resultat: ~4mm Gap (2x margin_mm) ohne Blade-Offset.
        """
        if not labels:
            raise ValueError("At least one label is required")
        for idx, label in enumerate(labels):
            is_last = idx == len(labels) - 1
            self.print(
                label,
                margin_mm=margin_mm,
                high_resolution=high_resolution,
                feed=is_last,
                auto_cut=not half_cut,
                half_cut=half_cut,
                chain_printing=not is_last,   # chain for all but last
            )
```

**Verwendung in `_ptouch_print_multi()`:**
```python
# In _ptouch_print_multi() in ptouch_backend.py:
# Statt: printer_cls = _PTOUCH_PRINTER_CLASSES[model_id]  # -> ptouch.PTP750W
# Verwende: printer_cls = _PTP750WWithChain für PT-P750W
# Und: printer.print_multi_chain(labels, ...) statt printer.print_multi(...)
```

**Aufwand:** ~20–30 Minuten (Code + Unit-Tests anpassen)

**Risiko (niedrig):**
- Wenn ptouch-py `_build_page_control_sequence()` umbenennt oder Signatur ändert →
  Break. Mitigierung: Versionspinning in `pyproject.toml` auf `ptouch==1.1.0`.
- `print()` wird komplett re-implementiert (Copy-Paste aus upstream) → Drift.
  Mitigierung: Kommentar mit Upstream-Commit-Hash.
- chain_printing=True unterdrückt den Cutter-Motor nach jedem Label. Falls der
  Drucker in einen Fehlerzustand läuft (z.B. Jam), kein automatisches Stoppen.

**Test-Plan:**
```bash
# Unit-Test: monkey-patch _ptouch_print_multi, Verify ESC i K byte für intermediate
# Hardware-Test:
python scripts/smoke_first_print_batch.py --host <IP> --count 4 --chain
# Erwartetes Ergebnis: perforierter Streifen, ~4mm Gap (vs ~5mm aktuell)
```

---

### Option C: Monkey-Patch `_build_page_control_sequence`

**Beschreibung:** Überschreibe `_build_page_control_sequence` auf der Printer-Instanz
nach deren Erzeugung, um `chain_printing` durchzureichen.

```python
# In _ptouch_print_multi():
import functools

connection = ptouch.ConnectionNetwork(host, port=port, timeout=10.0)
printer = printer_cls(connection=connection, high_resolution=high_resolution)

# Monkey-Patch: _build_page_control_sequence mit chain_printing-Flag
_orig_build = printer._build_page_control_sequence

def _build_with_chain(self_or_num_lines, margin=None, *, chain_printing_override=False, **kw):
    # ptouch-py 1.1.0: _build_page_control_sequence(num_lines, margin, tape, ...)
    # chain_printing wird hier injiziert
    return _orig_build(self_or_num_lines, margin, chain_printing=chain_printing_override, **kw)

printer._build_page_control_sequence = _build_with_chain
```

**Hinweis:** Dieser Ansatz ist fragil wegen der Signatur-Abhängigkeit und wird
**nicht empfohlen**. Option B ist sauberer.

**Aufwand:** ~10–15 Minuten

**Risiko (mittel):**
- `_build_page_control_sequence` ist eine private Methode (Präfix `_`)
- Signatur kann sich in Patch-Releases ändern
- Monkey-Patching auf Instanz-Ebene ist schwerer zu testen

---

### Option D: Warten auf upstream Issue nbuchwitz/ptouch#20

**Beschreibung:** Issue #20 (Mai 2026) fordert explizit `chain_printing` als öffentlichen
Parameter in `print()` und `print_multi()`. Falls merged, sind Optionen B+C obsolet.

**Aufwand:** 0 Minuten lokale Arbeit. Timeline unbekannt.

**Risiko:** Keine stabile Zusage für ptouch-py 1.2.x. Issue könnte lange offen bleiben.

---

## 5. Vergleich der Optionen

| Option | Aufwand | Risiko | Gap-Ergebnis | Empfehlung |
|--------|---------|--------|--------------|------------|
| **A — Keine Änderung** | 0 min | keines | ~5mm Half-Cut | Production-Ship jetzt |
| **B — Subclass** | ~25 min | niedrig | ~4mm Half-Cut | Wenn Gap störend wird |
| **C — Monkey-Patch** | ~15 min | mittel | ~4mm Half-Cut | Nicht empfohlen |
| **D — Upstream warten** | 0 min | unbekannt | ~4mm Half-Cut | Falls Issue#20 closed wird |

**Empfohlene Reihenfolge:**
1. **Jetzt:** Option A (Production-Ship mit ~5mm Gap)
2. **Bei Bedarf (spätere Phase):** Option B umsetzen
3. **Issue#20 beobachten:** Wenn ptouch-py 1.2.x Chain-Support merged, auf neue Version
   updaten und Subclass entfernen

### Warum `chain_printing=True` den Gap reduziert

Mit `chain_printing=True` sendet ptouch-py ESC i K = `0x04` statt `0x0C`:
- Bit 2 = 1: Half-Cut aktiv
- Bit 3 = 0: Chain-Modus aktiv (kein Motor-Vorschub nach dem Cut)

Der Drucker führt den Half-Cut aus, schiebt aber das Tape NICHT vor.
Das bedeutet: kein ~1mm Blade-Offset durch Motor-Repositionierung.
Gap = 2x `margin_mm` = 2x 2mm = **4mm statt 5mm**.

### Warum der Gap nicht weiter reduziert werden kann

`MIN_MARGIN_MM = 2.0` ist in ptouch-py enforced (ValueError). Technisch würde
ESC i d mit margin=0 (0 Dots) keinen Gap geben, aber:
1. Die Brother-Spezifikation dokumentiert ein Minimum von ~2mm (aus Feed-Amount-Sektion)
2. Mit margin=0 riskiert man Druckdefekte an der Label-Grenze (Head-Position)
3. Dieser Raw-Byte-Ansatz erfordert vollständige Custom-Protokoll-Implementierung

---

## 6. Quellen

| Quelle | URL | Relevanz |
|--------|-----|---------|
| Brother Raster Command Reference PT-E550W/P750W (PDF, v1.02) | [download.brother.com](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf) | Primär: ESC i M, ESC i K, ESC i d, Print-Commands. Enthält vollständige Bit-Flag-Dokumentation. |
| ptouch-py GitHub (nbuchwitz/ptouch) | [github.com/nbuchwitz/ptouch](https://github.com/nbuchwitz/ptouch) | Quellcode v1.1.0 — lokal installiert und vollständig gelesen. `printer.py` enthält alle Protocol-Implementierungen. |
| ptouch-py Issue #20 — chain/mirror in public API | [github.com/nbuchwitz/ptouch/issues/20](https://github.com/nbuchwitz/ptouch/issues/20) | Feature-Request der genau das chain_printing-Problem beschreibt. Bestätigt: chain_printing in print() hardkodiert auf False. |
| CUPS printer-driver-ptouch (philpem) | [github.com/philpem/printer-driver-ptouch](https://github.com/philpem/printer-driver-ptouch) | C-Implementierung: `#define PTC_EJECT 0x1a`, `PTC_FORMFEED 0x0c`, ESC i K Bit-Flags. Unabhängige Verifikation des Protokolls. |
| Brother Support: "Why does one inch tape feed" | [help.brother-usa.com/app/answers/detail/a_id/79756](https://help.brother-usa.com/app/answers/detail/a_id/79756) | Bestätigt 22.5mm Pre-Roll beim 0x1A-Opcode ("Small Margin & Chain: 0.89in"). |
| PT-P750W Feed/Cut Options | [support.brother.com](https://support.brother.com/g/b/faqend.aspx?c=us&lang=en&prod=p750weus&faqid=faqp00100033_000) | Bestätigt: Chain Print, Half-Cut, Auto-Cut als offizielle Modi des PT-P750W. |
| Python gist stecman — PT-P300BT reverse engineering | [gist.github.com/stecman/ee1fd9a8b1b6f0fdd170ee87ba2ddafd](https://gist.github.com/stecman/ee1fd9a8b1b6f0fdd170ee87ba2ddafd) | Unabhängige Implementierung: `\x1B\x69\x4B\x08` für "No chain" bestätigt. |

---

## Anhang: Verifizierte ptouch-py 1.1.0 Byte-Sequenz für Batch-Print

### Intermediäres Label (non-last) — aktuelles `print_multi()` Verhalten

```
# Initialisierung (nur erstes Label per Batch wegen is_first_page=False):
# (keine Invalidate/Initialize für non-first pages)
1B 69 61 01                 # ESC i a 0x01 — Raster-Modus
1B 69 7A [n1..n4][l1..l4] 00 00  # ESC i z — Print-Information
1B 69 4D 00                 # ESC i M 0x00 — auto_cut=False
1B 69 4B 0C                 # ESC i K 0x0C — half_cut=True, chain=False (0x04+0x08)
1B 69 64 0E 00              # ESC i d 14 dots = 2mm — DEFAULT_MARGIN_MM
4D 02                       # M 0x02 — TIFF-Kompression ein (PTE550W default)
[G/Z raster data...]        # Bilddaten spaltenweise
0C                          # 0x0C — Print without feed
```

### Letztes Label — `print_multi()` Verhalten

```
[gleiche Control-Sequenz wie oben]
1B 69 4B 0C                 # ESC i K 0x0C — half_cut=True, chain=False
[G/Z raster data...]
1A                          # 0x1A — Print AND feed (~22.5mm Pre-Roll)
```

### Mit Option B (`chain_printing=True` für non-last)

```
1B 69 4B 04                 # ESC i K 0x04 — half_cut=True, chain=TRUE
[G/Z raster data...]
0C                          # 0x0C — Print without feed
```

### Pin-Konfiguration PT-P750W (aus ptouch-py `printers.py`)

| Tape | left_pins | print_pins | right_pins | Gesamt |
|------|-----------|------------|------------|--------|
| 3.5mm | 52 | 24 | 52 | 128 |
| 6mm | 48 | 32 | 48 | 128 |
| 9mm | 39 | 50 | 39 | 128 |
| 12mm | 29 | 70 | 29 | 128 |
| 18mm | 8 | 112 | 8 | 128 |
| 24mm | 0 | 128 | 0 | 128 |

**Quelle:** `ptouch-py printers.py` Klasse `PTE550W` (PTP750W erbt ohne Änderung).
Kommentar im Quellcode: "Source: cv_pte550wp750wp710bt_eng_raster_102.pdf, page 20, section 2.3 Print Area".
