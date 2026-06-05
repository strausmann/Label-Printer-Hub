# Phase 1k.2: Multi-Label-Batch via `ptouch.print_multi()` — Design Spec

**Datum:** 2026-06-04
**Issue:** [#102 Phase 1k.2 Multi-Label-Batch](https://github.com/strausmann/Label-Printer-Hub/issues/102)
**Parent:** [#101 Phase 1k Umbrella](https://github.com/strausmann/Label-Printer-Hub/issues/101)
**Status:** Approved (User-Bestätigung in Brainstorming-Session 2026-06-04)
**Naechstes Skill:** `superpowers:writing-plans`

## Hintergrund

Phase 1i Smoke-Test (2026-06-04) deckte einen Live-Bug auf: Multi-Label-Batches drucken 22.5mm leeres Tape zwischen jedem Label statt der 5mm Half-Cut die Brother iOS App produziert. Root cause:

`batch_dispatch.dispatch_batch()` erstellt N separate `PrintJob`s. Jeder wird vom Queue-Worker als eigener `ptouch.LabelPrinter.print()` Call ausgeführt. Jeder Call öffnet eine eigene Connection, sendet eine eigene Init-Sequence (die ein 22.5mm Pre-Roll triggert) und schliesst danach. `feed=False` (in PR #100 nachgereicht) unterdrückt nur den End-Feed des aktuellen Calls — der nächste Call macht trotzdem volle Init.

**Entscheidende Entdeckung:** `ptouch-py 1.1.0` hat bereits eine `LabelPrinter.print_multi(labels: list[Label], half_cut: bool=True)` Methode die mehrere Labels in EINER Connection mit korrekten 5mm Half-Cuts zwischen Items abarbeitet. Wir müssen sie nur aufrufen.

## Ziel

Multi-Label-Batches an PT-Series Drucker produzieren das gleiche Tape-Verhalten wie die Brother iOS App:

- **Erstes Label:** 22.5mm Pre-Roll am Anfang (einmalig pro Batch)
- **Zwischen Labels:** ~5mm Half-Cut (taktile Trennung, kein leeres Tape)
- **Letztes Label:** voller Cut zur Trennung vom nächsten Batch

API-Vertrag (`POST /api/print/{slug}/batch` → 202 + `batch_id` + `job_ids[]`) bleibt unverändert. Hangar braucht keine Anpassung.

## Scope

### In Scope

- PT-P750W Multi-Label-Batches via `print_multi()` (PTouchBackend)
- Neue `PrinterBackend.print_images()` Protocol-Methode mit Default-Loop-Impl
- Neuer `PrintQueue.BatchJob` Typ
- Atomic Failure-Semantik (Option 1 — User-Entscheidung): bei Fehler werden alle Job-IDs gemeinsam als failed markiert
- Single-Item-Batches funktionieren weiter (`print_multi` mit 1 Element ist äquivalent zu `print`)
- Tape-Mismatch-Check (existing `print_service.py:92`) 1x am Batch-Anfang
- Tests: unit + integration + manueller Hardware-Smoke

### Out of Scope

- **QL-820NWB Batching** — `brother_ql` Lib hat kein `print_multi` Equivalent. QL ist Endless-Tape (kein Half-Cut zwischen Labels). `BrotherQLBackend` erbt Default-Loop-Impl der Base-Class. Status quo bleibt.
- **Layout-Engine** — separater Scope ([#103 Phase 1k.1](https://github.com/strausmann/Label-Printer-Hub/issues/103))
- **Auto-Scale Tape-Mismatch** — kommt mit 1k.1 ([#103 Kommentar 4624051365](https://github.com/strausmann/Label-Printer-Hub/issues/103#issuecomment-4624051365))
- **Online Template-Editor** — separater Scope ([#104 Phase 1k.3](https://github.com/strausmann/Label-Printer-Hub/issues/104))
- **API-Migration zu batch-only-Semantik (Option 2)** — verworfen. Per-item job_ids bleiben Teil des Contracts.
- **Per-Drucker konfigurierbare Semantik (Option 3)** — verworfen. Atomic für PT, Loop für QL ist Backend-Implementation-Detail, nicht API-Verhalten.

## Architektur

### Render-Phase (synchron in `batch_dispatch`)

```
HTTP Request POST /api/print/brother-p750w/batch
{items: [V1, V2, V3, V4]}
        |
        v
batch.py route handler (unveraendert)
- Resolve printer by slug
- ACL-Check (auth.has_print scope)
- backend_router.get(slug) -> PTouchBackend instance
        |
        v
batch_dispatch.dispatch_batch(items, backend) (refactored)
- fuer jedes Item:
    - TemplateLoader.get(template_id)
    - LabelRenderer.render(template, data) -> Image[i]
    - JobRecord(job_id=uuid(), status="queued") in DB
- collect images[] + per-item PrintOptions[]
- preflight = await backend.preflight_check() (1x am Batch-Anfang)
- check: alle items haben gleichen template.tape_mm -> sonst 400 mixed_tape_sizes
- check: preflight.loaded_tape_mm == template.tape_mm -> sonst tape_mismatch
- enqueue: PrintQueue.enqueue_batch(
    BatchJob(
      images=[Image1, Image2, Image3, Image4],
      options=[Options1, ..., Options4],
      job_ids=[j1, j2, j3, j4],
      batch_id=abc,
      backend_slug="brother-p750w",
    )
  )
        |
        v
HTTP Response 202 (unveraendert)
{batch_id: abc, job_ids: [j1, j2, j3, j4], errors: []}
```

### Print-Phase (asynchron im Queue-Worker)

```
PrintQueue worker.run()
        |
        v
Dequeue next item — check Union-Type:
- PrintJob (single item, existierender Pfad) -> backend.print_image(image, options)
- BatchJob (neu) -> backend.print_images(images[], options[])
        |
        v
PTouchBackend.print_images(images, options) (neu)
- Convert each PIL Image -> ptouch.label.Label
- Determine collective options (half_cut=True zwischen Items, auto_cut=True am Ende)
- await asyncio.to_thread(
    _ptouch_print_multi,
    labels=[label1, label2, label3, label4],
    model_id="PT-P750W",
    half_cut=True,
    high_resolution=...,
  )
        |
        v
_ptouch_print_multi(labels, model_id, ...) (neu, module-level fuer Test-Mocks)
- LabelPrinter = _PTOUCH_PRINTER_CLASSES[model_id]
- printer = LabelPrinter(connection)
- printer.print_multi(labels, half_cut=half_cut, high_resolution=high_resolution)
  -> ptouch Lib: 1 Connection, 1 Pre-Roll, 5mm Half-Cut zwischen Labels, voller Cut am Ende
        |
        v
On success -> loop job_ids: JobRecord[i].status = "completed"
On failure -> loop job_ids: JobRecord[i].status = "failed", error_message gemeinsam
        |
        v
SSE Event Bus -> Hangar pollt /api/jobs/{j1..j4} -> bekommt finalen Status
```

## Komponenten-Änderungen

### Neue Komponenten

| Komponente | Datei | Verantwortlichkeit |
|---|---|---|
| `BatchJob` (dataclass) | `app/services/print_queue.py` | Queue-Item mit `images: list[Image]`, `options: list[PrintOptions]`, `job_ids: list[UUID]`, `batch_id: UUID`, `backend_slug: str` |
| `PrinterBackend.print_images(images, options)` | `app/printer_backends/base.py` (Protocol) | Neue Default-Methode mit Loop-Impl. Backend kann überschreiben. |
| `PTouchBackend.print_images()` | `app/printer_backends/ptouch_backend.py` | Konvertiert Images -> Labels, ruft `_ptouch_print_multi` |
| `_ptouch_print_multi(labels, model_id, ...)` | gleich | Module-level helper analog zu `_ptouch_print`. Test-Monkeypatchability. |

### Modifizierte Komponenten

| Komponente | Datei | Änderung |
|---|---|---|
| `batch_dispatch.dispatch_batch()` | `app/services/batch_dispatch.py` | Statt N `enqueue_job()` jetzt 1 `enqueue_batch()`. Mixed-tape-Check vor Queue. |
| `PrintQueue.enqueue_batch()` | `app/services/print_queue.py` | Neue Methode, akzeptiert `BatchJob` |
| `PrintQueue` Worker-Loop | gleich | `isinstance(item, BatchJob)` Branch der `backend.print_images()` aufruft |

### Unveränderte Komponenten

- API-Endpoint `POST /api/print/{slug}/batch`
- `BatchRequest` / `BatchResponse` Pydantic-Schemas
- `JobRecord` DB-Modell (1 Row pro Item bleibt)
- `PrintService.enqueue_job()` (für True-Single-Calls weiterhin genutzt, z.B. `POST /api/print/{slug}` ohne batch)
- `BrotherQLBackend` (erbt Default-Loop-Impl, QL bleibt per-item)
- Hangar-Code (Frontend, Routes, Templates)

## Datenmodell

### `BatchJob`

```python
@dataclass(frozen=True)
class BatchJob:
    """Queue-Item das mehrere Labels in einer Backend-Operation druckt."""
    batch_id: UUID
    backend_slug: str               # zur Validierung dass Backend-Router noch übereinstimmt
    images: list[Image]             # bereits gerenderte PIL Images
    options: list[PrintOptions]     # per-item (copies, auto_cut etc.)
    job_ids: list[UUID]             # tracking — 1 zu 1 mit images/options
    tape_mm: int                    # einheitlich, vor Queue validiert
```

### `PrinterBackend` Protocol

```python
class PrinterBackend(Protocol):
    backend_id: str
    half_cut_supported: bool

    async def preflight_check(self, ...) -> PreflightStatus: ...
    async def print_image(self, image, tape_spec, *, ...) -> None: ...

    # NEU — Default-Impl in Base, Backend überschreibt für native batching
    async def print_images(
        self,
        images: list[Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,    # Standard: Half-Cut zwischen Batch-Items
    ) -> None:
        """Print N images as a batch — semantics depend on backend impl.

        PT-Series via ptouch.print_multi: ATOMIC (success or all-fail at hardware level).
        Default per-item loop (QL/Mock): best-effort per item — items 0..N-1 may already
        be printed when item N fails. Job-state handling MUST treat partial-success
        explicitly (see plan Task 8 _process_batch error handler).
        """
        # (Copilot-Review C1 PR #106): Default-Impl als FREIE Funktion in
        # batch_helper.py, NICHT als Protocol-default — Python typing.Protocol
        # method bodies werden nicht von conforming classes geerbt. Backends
        # die nicht ueberschreiben rufen explicit default_print_images_loop auf.
        ...  # siehe app.printer_backends.batch_helper.default_print_images_loop
```

`PTouchBackend.print_images()` überschreibt mit echtem `ptouch.print_multi` (atomic).

`BrotherQLBackend` und `MockBackend` haben eigene `print_images` Methoden die explicit `default_print_images_loop(self, ...)` aus `app.printer_backends.batch_helper` aufrufen — Python Protocols haben keine vererbten Default-Methoden, daher MUSS jeder Backend die Methode haben.

## Failure Modes

| Failure | Wo erkannt | API-Response | Job-Status |
|---|---|---|---|
| Mixed `tape_mm` im Batch | `batch_dispatch` (vor Queue) | 400 `mixed_tape_sizes` | keine Jobs erstellt |
| Template not found | `batch_dispatch` (vor Queue) | per-item `errors[i].error_code=template_not_found` | per-item `failed` |
| Tape-Mismatch (loaded != template.tape_mm) | `batch_dispatch` (Preflight) | 409 `tape_mismatch` (oder queued, je `on_tape_mismatch`) | alle Jobs als `failed`/`paused` |
| Printer offline | `preflight_check` | 503 `printer_offline` | keine Jobs erstellt |
| Hardware-Fehler mid-print_multi | `_ptouch_print_multi` Exception | — (Worker setzt) | **alle Jobs als `failed`** `batch_failed` mit gemeinsamer Message |
| Single-Item-Batch (len(items)=1) | — | normales 202 | normaler print_multi mit 1 Element |

### Atomic Failure (Option 1)

`ptouch.LabelPrinter.print_multi()` ist atomar. Bei Exception kennt die Lib nicht welches Item gescheitert ist:

```python
try:
    await asyncio.to_thread(_ptouch_print_multi, labels=..., ...)
    for job_id in batch.job_ids:
        await job_repo.mark_completed(job_id)
except PtouchError as exc:
    error_msg = f"batch print_multi failed: {exc}"
    for job_id in batch.job_ids:
        await job_repo.mark_failed(
            job_id,
            error_code="batch_failed",
            error_message=error_msg,
        )
```

**Hangar-Sicht (1k.2-Scope):** Wenn ein Item-Job-Status `failed` zeigt, weiß Hangar zunächst nicht ob NUR dieses Item gescheitert ist oder der ganze Batch — sie sehen alle vier als failed. Das ist **akzeptabel für 1k.2** weil Hangar-Code unverändert bleibt und die UI bereits "alle 4 sind rot" anzeigt.

**Optionale Erweiterung (Phase 1k.2-Followup oder Phase 1l, OUT OF 1k.2 SCOPE):** Job-Record könnte ein zusätzliches Feld `batch_failure_mode: atomic | individual` bekommen, plus Hangar-UI-Anpassung "Batch failed — 4 items affected". Das ist **kein 1k.2-Scope** (würde Hangar-Änderung erfordern, was 1k.2 explizit ausschließt — siehe "Backward-Compatibility"). (Copilot-Review C2 PR #106 — Scope-Konflikt aufgelöst durch Verschiebung in Followup.)

## Test-Strategie

| Layer | Test |
|---|---|
| `_ptouch_print_multi()` unit | Monkeypatch `LabelPrinter.print_multi`, verify labels-Array + half_cut + high_resolution forwarded korrekt |
| `PTouchBackend.print_images()` unit | Mock `_ptouch_print_multi`, verify Image-zu-Label-Konvertierung + collective options |
| `PrintQueue.BatchJob` worker | Submit BatchJob, verify worker ruft `backend.print_images()` (nicht `print_image()`), verify alle job_ids als completed/failed markiert |
| `batch_dispatch.dispatch_batch()` | Submit Batch mit gemischten tape_mm -> 400 vor Queue; mit gleichen tape_mm -> BatchJob in Queue |
| Integration | Echte `POST /api/print/.../batch` mit 4 Items, mock backend, verify atomic behavior |
| Mixed-Backend | Batch an QL-Drucker (`brother_ql`) -> `BrotherQLBackend.print_images()` Default-Loop, verify pro-item Verhalten unverändert |
| Hardware-Smoke (manuell) | Echter PT-P750W, 4 Labels in Batch, optisch verifizieren: 5mm Half-Cut zwischen, voller Cut am Ende |

## Backward-Compatibility

- API-Endpoints: unverändert (`POST /api/print/{slug}/batch`, `POST /api/print/{slug}` single)
- `BatchRequest`/`BatchResponse` Schemas: unverändert
- Single-Item-Batches: `print_multi` mit 1 Element funktioniert — keine Sonderfall-Logik nötig
- Mixed Batches mit existing `on_tape_mismatch=queue`: bleibt erhalten — Worker beim Dequeue prüft, ggf. pausiert Job
- QL-Backend: erbt Default-Loop-Impl in `PrinterBackend` Base-Class — identisches Verhalten wie heute
- Hangar: KEINE Änderung am Frontend-Code

## Akzeptanzkriterien

- [ ] PT-P750W druckt 4 Items in einem Batch mit **5mm Half-Cut zwischen Labels**
- [ ] Letztes Item bekommt vollen Cut (Trennung von nächster Batch-Session)
- [ ] API-Response unverändert (`job_ids[]` vorhanden, alle UUIDs verschieden)
- [ ] Bei Hardware-Fehler: alle Jobs des Batches als failed mit gemeinsamer `batch_failed` Error-Message
- [ ] Single-Item-Batches funktionieren weiter (print_multi mit 1 Element)
- [ ] QL-820NWB Batches funktionieren weiter (Default-Loop-Impl, kein Verhalten-Change)
- [ ] Mixed tape_mm im Batch -> 400 `mixed_tape_sizes` vor Queue, keine Jobs erstellt
- [ ] Tests: unit + integration + manueller Hardware-Smoke alle grün
- [ ] Bestehende Hangar-Integration funktioniert ohne Code-Change

## Offene Fragen (für writing-plans)

- Konkrete Stelle der Image-zu-Label Konvertierung — direkt in `PTouchBackend.print_images()` oder in `_ptouch_print_multi`? (Beide möglich; je nach Test-Mocking-Strategie)
- `batch_failure_mode` Field in JobRecord — DB-Migration oder JSON-Spalte erweitern?
- SSE Event-Bus: Senden wir 1 Event pro Batch (batch_completed) oder N Events (per-item)? Aktuell: per-job — beibehalten für Backward-Compat.

## Referenzen

(Copilot-Review C3 PR #106: Privacy-Konformität — keine `*.strausmann.*` Links. Phase 1i Smoke-Empirie ist im privaten Repo `homelab-management`, nicht in diesem OS-Repo gemirrort.)

- Phase 1i Smoke-Test Empirie: internes Repo `homelab-management`, Pfad `docs/site/operations/protokolle/2026-06-04-phase1i-smoke-test-empirie.md` — Kurzfassung: PT-P750W druckt 22.5mm leeres Tape zwischen Multi-Label-Batches statt 5mm Half-Cut (Brother iOS App Verhalten). Empirisch verifiziert über 2 Smoke-Test-Iterationen (V1-V4 4-Varianten-Test) am 2026-06-04.
- Hub PR #100 (last_page → feed groundwork): [https://github.com/strausmann/Label-Printer-Hub/pull/100](https://github.com/strausmann/Label-Printer-Hub/pull/100)
- ptouch-py 1.1.0 `print_multi` Signatur: verifiziert in Container `docker exec label-printer-hub-backend python3 -c "import ptouch.printer; import inspect; print(inspect.signature(ptouch.printer.LabelPrinter.print_multi))"`
- Issue #102 (1k.2): [https://github.com/strausmann/Label-Printer-Hub/issues/102](https://github.com/strausmann/Label-Printer-Hub/issues/102)
- Issue #103 (1k.1 Auto-Scale Insight): [https://github.com/strausmann/Label-Printer-Hub/issues/103#issuecomment-4624051365](https://github.com/strausmann/Label-Printer-Hub/issues/103#issuecomment-4624051365)
- A-Diagnose PT-P750W Layout: `docs/research/2026-06-02-pt750w-layout-diagnose.md` (im Hub-Repo selbst)
