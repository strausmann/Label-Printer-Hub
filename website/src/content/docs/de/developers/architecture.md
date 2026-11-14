---
title: Architektur
description: "Wie Labelyard gebaut ist: ein Prozess, die Bausteine von Backend und Weboberfläche, die Datenflüsse, die Warteschlange und der Ereignisstrom."
sidebar:
  label: Architektur
---

Der Überblick im Großen. Das **Warum** hinter jeder Entscheidung steht in den [Entscheidungsdokumenten](https://github.com/strausmann/labelyard/tree/main/docs/decisions).

## Im Überblick

```
┌──────────────────────┐  HTTP/JSON  ┌──────────────────────────────┐  TCP/9100  ┌──────────┐
│  Browser / PWA       │ ──────────► │ Hub (ein Python-Prozess)     │ ─────────► │ Drucker  │
│  React + TypeScript  │   + SSE     │ FastAPI, asyncio             │            │ Brother  │
│  Service Worker      │ ◄────────── │ liefert API, /api/v1/events  │ ◄───────── │ PT / QL  │
│  Scannen per Kamera  │             │ und die gebaute Oberfläche   │  passiver  └──────────┘
└──────────────────────┘             │ Warteschlange + Zustände     │  Status
                                     │ SQLite, EventBus             │  UDP/161 SNMP
                                     └──────────────────────────────┘
```

Ein Container (ADR [0015](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0015-single-process-deployment.md), löst ADR [0001](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0001-two-container-architecture.md) ab):
- `labelyard` – Python/FastAPI; spricht mit den Druckern, führt die Warteschlange, bietet die JSON-API, den JSON-Ereignisstrom und die statische Weboberfläche (mit `index.html` als Rückfall für die Routen im Browser)

Die Weboberfläche wird beim Bau des Images aus `frontend/` gebaut (mehrstufiges Dockerfile, Build-Kontext ist die Wurzel des Repositorys) und ins Image kopiert; es gibt keinen eigenen Prozess und kein eigenes Image für das Frontend. Der Reverse Proxy des Betreibers (Traefik / Pangolin / Caddy / ohne Proxy – siehe [Reverse Proxy](/de/install/reverse-proxy/) und [`examples/`](https://github.com/strausmann/labelyard/tree/main/examples)) zeigt direkt auf den Hub auf Port 8000. Drucker, Integrationen und Schlüssel verwaltest du in der Oberfläche, sie liegen in der Datenbank (ADR [0017](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0017-settings-in-database-env-locks-encrypted-secrets.md)); Geheimnisse sind mit `LABELYARD_SECRET_KEY` verschlüsselt.

## Die Bausteine

### Backend ([ADR 0002](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0002-python-fastapi-backend.md))

```
backend/app/
├── main.py                       # FastAPI-App und Lebenszyklus
├── cli.py                        # Befehl labelyard (admin create-key, ...)
├── config.py                     # Einstellungen aus der Umgebung
├── api/
│   ├── routes/                   # ein Router je Ressource (print, jobs, printers, sheets, webhooks, events, ...)
│   └── dependencies/             # Anmeldung, Ratenlimits, Webhook-Schlüssel
├── auth/                         # API-Schlüssel, Sitzungen, CSRF
├── printer_models/               # ein Plugin je Modellfamilie (ADR 0004)
│   ├── base.py                   # Protokoll PrinterModel
│   ├── pt.py                     # Treiber der Brother-PT-Serie
│   ├── ql.py                     # Treiber der Brother-QL-Serie
│   └── registry.py               # ModelRegistry: Entry Points, Suche nach PJL-Zeichenkette / SNMP-Wert
├── printer_backends/             # wie die Bytes zum Drucker kommen (ADR 0020)
│   ├── base.py                   # Schnittstelle der Backends
│   ├── ptouch_backend.py         # PT-Serie über TCP/9100
│   ├── brother_ql_backend.py     # QL-Serie über TCP/9100
│   ├── mock_backend.py           # Schein-Drucker für Tests und die Smoke-Compose-Datei
│   └── ipp/                      # eigener IPP-Client für Seitendrucker
├── services/
│   ├── layout_engine.py          # zeichnet ein Etikett aus LabelData und einem Inhaltstyp
│   ├── print_service.py          # Vorprüfung, Nachschlagen, Zeichnen, Speichern, Einreihen
│   ├── print_queue.py            # asyncio-Warteschlange + Worker je Drucker (ADR 0005)
│   ├── page_job_runner.py        # Seitenaufträge auf IPP-Druckern, abgerechnet nach dem, was der Drucker meldet
│   ├── printer_runtime.py        # der eine Codepfad, der einen Drucker in den laufenden Hub einhängt (ADR 0024)
│   ├── hardware_identity.py      # Identität eines Druckers aus seiner Seriennummer (ADR 0024)
│   ├── status_block.py           # liest den 32-Byte-Statusblock von Brother
│   ├── status_freshness.py       # wie alt ein zwischengespeicherter Status sein darf, bevor er als unbekannt gilt
│   ├── roll_tracker.py           # erkennt den Wechsel der Rolle (Bandkassette)
│   ├── tape_registry.py          # Nachschlagetabelle der Brother-Bänder
│   ├── event_bus.py              # Publish/Subscribe im Speicher für SSE (ADR 0009)
│   └── producers/                # speisen den Event-Bus (Warteschlange, Statusabfrage, Bandwechsel, IPP-Status)
├── integrations/
│   ├── base.py                   # Protokoll IntegrationPlugin
│   ├── registry.py               # IntegrationRegistry: Entry Points
│   ├── snipeit/plugin.py
│   ├── spoolman/plugin.py
│   └── grocy/plugin.py
├── sheets/                       # Bogentypen, Planer, Reservierungen (ADR 0023)
├── calibration/                  # Kalibrierung der Seitendrucker (Anpassung, Modell, Dienst)
├── page_render/                  # PDF-Seiten für Seitendrucker
├── settings_store/               # Einstellungen in der Datenbank; die Umgebung sperrt Felder (ADR 0017)
├── models/                       # SQLModel-Persistenz (Aufträge, Drucker, Rollen, Bögen, ...)
├── repositories/                 # Datenbankzugriff
├── schemas/                      # Modelle für Anfragen und Antworten
├── db/                           # Engine, Sitzung, Lebenszyklus
└── seed/                         # Bogentypen, die beim Start geladen werden
```

### Weboberfläche ([ADR 0016](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0016-react-typescript-web-ui.md), löst [0003](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0003-go-tailwind-htmx-pwa-frontend.md) ab)

```
frontend/
├── src/
│   ├── app/                 # Router, Sitzung, Query-Client, Hinweis auf neue Versionen
│   ├── api/                 # Client, Ereignisstrom, Typen aus dem OpenAPI-Vertrag erzeugt (ADR 0011)
│   ├── features/            # Übersicht, Drucker, Aufträge, Integrationen, Nachschlagen, Scannen, Suche, Einstellungen
│   ├── shell/, pages/       # App-Rahmen (Seitenleiste / Tab-Leiste) und Seitenrahmen
│   ├── design/              # Design-Tokens (Spec 5.2)
│   └── i18n/                # Meldungskataloge (Englisch als Standard)
├── public/                  # PWA-Symbole, Manifest
└── e2e/                     # Playwright-Tests gegen das echte Backend (Schein-Drucker)
```

Browser melden sich mit einem API-Schlüssel (oder über SSO am Proxy) an und bekommen ein Sitzungs-Cookie mit CSRF-Schutz ([ADR 0019](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0019-proxy-headers-need-trust-token.md) für die Vertrauensregeln, und [Benutzer und SSO](/de/admin/users-and-sso/)).

## Datenflüsse

### Pull-Modus – jemand scannt in der Oberfläche einen Barcode

1. Jemand öffnet `https://labelyard.example.com/` (ausgeliefert vom Hub)
2. Öffnet einen Eintrag: sucht ihn in Snipe-IT, Grocy oder Spoolman, scannt seinen Barcode oder folgt einem Etikett-Link (`/asset/<id>`) → die Oberfläche ruft `GET /api/v1/lookup/snipeit/<id>` auf
3. Das Backend holt die Daten des Assets aus Snipe-IT und gibt `LabelData` zurück
4. Der Druckdialog zeigt eine Vorschau, die das Backend zeichnet; die Person wählt Drucker, Gestaltung und Anzahl
5. Sie klickt **Drucken** → `POST /api/v1/print` → das Backend reiht den Auftrag ein und antwortet `202` + `job_id`
6. Die Oberfläche hält für den ganzen Tab schon eine SSE-Verbindung zu `/api/v1/events`
7. Der Worker der Warteschlange im Backend nimmt den Auftrag, öffnet TCP/9100 zum Drucker und schickt die Rasterdaten
8. Das Backend legt die Ereignisse `job` und `status` auf den EventBus → SSE (JSON-Frames) → die Oberfläche aktualisiert ihre Daten an Ort und Stelle
9. Der Auftrag ist fertig; sein Zustand auf der Seite ändert sich durch das SSE-Ereignis. Der Hub schickt keine Benachrichtigung im Browser (eine Benachrichtigungszentrale ist in [#255](https://github.com/strausmann/labelyard/issues/255) geplant)

### Push-Modus – Webhooks von Spoolman und Grocy

Der Hub nimmt Webhooks für Spulen aus Spoolman (`POST /api/v1/webhook/spoolman`) und Produkte aus Grocy (`POST /api/v1/webhook/grocy`) an. Grocy schickt sie selbst, wenn in seiner `data/config.php` `FEATURE_FLAG_LABEL_PRINTING=true` gesetzt ist; bei Spoolman ruft das, was auf das Spulen-Ereignis reagiert (zum Beispiel ein Automatisierungswerkzeug), die Route auf. Snipe-IT hat keine Webhook-Route und arbeitet nur im Pull-Modus über die Oberfläche des Hubs. [Erste Schritte](/de/install/getting-started/#5-webhooks-drucken-wenn-etwas-passiert) und [Webhooks](/de/integrations/webhooks/) nennen die Inhalte.

1. Grocy schickt an `https://labelyard.example.com/api/v1/webhook/grocy` (ein Ereignis aus Spoolman geht an `/api/v1/webhook/spoolman`)
2. Der Reverse Proxy leitet die Webhook-Unterroute **ohne SSO** an den Hub
3. Das Backend prüft `X-API-Key` und das Ratenlimit je Schlüssel (`LABELYARD_WEBHOOK_LIMIT_PER_MINUTE`, Standard 120) und gibt dann ein Etikett `qr_two_lines` für die Spule oder das Produkt über den Druckdienst an den ersten eingeschalteten Banddrucker, auf demselben Weg wie `POST /api/v1/print`: Vorprüfung, Nachschlagen, Zeichnen, Speichern, Einreihen. Fehler am Drucker und beim Nachschlagen beantwortet er wie die Druck-Route mit 409/422/502/503, eine unbekannte Spule oder ein unbekanntes Produkt mit 404 `app-lookup-not-found` und eine nicht eingerichtete Integration mit 503 `integration_not_configured` (beide im Format eines Problem-Details); eingereiht wird dann nichts. Es wird ein Etikett gedruckt; `quantity` wird angenommen, aber nicht gedruckt ([#284](https://github.com/strausmann/labelyard/issues/284))
4. Die Antwort ist `202` mit der Nummer des Auftrags; der Aufrufer wartet nicht auf das Ende des Drucks (Webhook-Aufträge haben keinen Besitzer, deshalb sehen sie nur Admins und SSO-Aufrufer)
5. Das Backend druckt; jeder offene SSE-Strom sieht die Zustandswechsel live

### Status je Phase ([ADR 0006](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0006-status-sources-by-phase.md))

| Frage | Quelle |
|---|---|
| Banddrucker: Status, Bandbreite, Seitenzähler | SNMP, abgefragt von `StatusProbeProducer` (standardmäßig alle 30 s). `ESC i S` auf TCP/9100 bekommt bei den Familien PT und QL über das Netz keine Antwort |
| Banddrucker: Hat die Rolle gewechselt? | `roll_tracker` vergleicht die Abfrage mit dem gespeicherten Datensatz der Rolle; der Drucker meldet keine Bandfarbe, deshalb fragt der Hub beim Rollenwechsel nach |
| Seitendrucker (IPP): Status und Verbrauchsmaterial | `IppStatusProducer`, abgefragt mit Rückzug nach Fehlschlägen |
| Ist der zwischengespeicherte Status noch gut? | `status_freshness`: Älter als 90 s oder drei Abfrageintervalle (das Längere zählt) erscheint er als unbekannt |

## Warteschlange ([ADR 0005](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0005-print-queue-is-mandatory.md))

- Eine `asyncio.Queue` und eine Worker-Koroutine **je Drucker**
- In SQLite gespeichert (Aufträge überstehen einen Neustart des Hubs)
- Zustände: `queued | paused | printing | completed | failed | cancelled`
- Abbrechen mitten im Druck geht bei Banddruckern **nicht** (die Brother-Spezifikation verbietet Befehle während des Drucks). IPP-Seitendrucker können einen laufenden Auftrag abbrechen (`Cancel-Job`, [ADR 0020](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0020-backend-kinds-ipp-page-printers.md))
- Seitenaufträge (IPP-Drucker) verfolgt der Hub am Drucker bis zu einem Endzustand und rechnet sie nach einem Neustart nach dem ab, was der Drucker meldet; Bandaufträge in `printing` werden zu `failed_restart`
- Aktionen: Pause/Fortsetzen/Abbrechen/Wiederholen/Priorität bei Aufträgen; Pause/Fortsetzen/Leeren beim Worker eines Druckers

## API-Vertrag ([ADR 0011](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0011-openapi-as-api-contract.md))

Die OpenAPI-3.1-Spezifikation des Backends ist maßgeblich:

| Pfad | Für wen |
|---|---|
| `GET /openapi.json` | Werkzeuge (Codegenerierung, Postman, Vertragstests) |
| `GET /docs` | Interaktive API-Referenz (Scalar, vom Hub ausgeliefert, ohne CDN) |

Die API-Typen der Weboberfläche werden aus dem OpenAPI-Dokument des Backends erzeugt (`pnpm gen:api`), und die CI schlägt fehl, wenn der erzeugte Client nicht mehr zum Vertrag passt.

## Releases ([ADR 0008](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0008-conventional-commits-and-semantic-release.md))

- Conventional Commits bestimmen über semantic-release die Versionssprünge
- Push nach `main` → Release-Pipeline: Tag → GitHub-Release → Docker-Image auf GHCR + Docker Hub
- Tag-Schema ([ADR 0007](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0007-docker-image-tag-scheme.md)): Jedes stabile Release veröffentlicht `1.0.0`, `1.0`, `1` und `latest` – Vorabversionen bekommen nur die volle Version
- Mehrere Architekturen: `linux/amd64` + `linux/arm64`

## SSE-EventBus

Das Backend bietet `GET /api/v1/events[?printer_id=<uuid>]` als Strom von Server-Sent Events mit JSON-Frames. Das Singleton `EventBus` (auf `app.state.event_bus`) verteilt die `BusEvent`-Instanzen der Producer an alle verbundenen Abonnenten:

| Producer | Kanal | Ereignistyp |
|---|---|---|
| `PrintQueueProducer` | `printer:{id}:queue` | `job.state_changed` |
| `StatusProbeProducer` | `printer:{id}:state` | `printer.status` |
| `TapeChangeProducer` | `printer:{id}:tape` | `printer.tape_changed` |
| Admin-API für Drucker | `hub` | `hub.printers_changed` |

Der Strom beginnt mit einem Schnappschuss je sichtbarem Drucker, meldet sich an wie jede `read`-Route und endet mit `auth.expired`, sobald die Zugangsdaten nicht mehr gelten. Das Format der Frames und die Flush-Einstellungen für Traefik, Caddy, Nginx und Pangolin: [Ereignisstrom und Reverse Proxys](/de/developers/architecture/sse/). Den früheren Strom mit HTML-Fragmenten `/api/events` (für HTMX) gibt es nicht mehr.

## Was der Reverse Proxy leisten muss

Der Hub lauscht in seinem Container auf Port `8000` und liefert dort Oberfläche und API aus. SSE verlangt, dass der Reverse Proxy Antworten nicht puffert (siehe [Ereignisstrom und Reverse Proxys](/de/developers/architecture/sse/) für Traefik/Caddy/Nginx/Pangolin und [`examples/`](https://github.com/strausmann/labelyard/tree/main/examples) für vollständige Compose-Beispiele).

Für Pangolin gilt das **Muster mit zwei Ressourcen**:

1. Hauptoberfläche: durch SSO geschützt, ganze Domain; die Ressource setzt den Header mit dem Vertrauens-Token, den der Hub verlangt (`LABELYARD_SSO_TRUST_TOKEN`)
2. Webhook-Unterroute (`/api/v1/webhook/`): ohne SSO, geschützt durch `LABELYARD_WEBHOOK_API_KEY`

## Wo was liegt

| Du suchst | Ort |
|---|---|
| Warum etwas so entschieden wurde | [Entscheidungsdokumente](https://github.com/strausmann/labelyard/tree/main/docs/decisions) |
| Wie man den Hub betreibt | [Erste Schritte](/de/install/getting-started/) |
| Wie man ein Druckermodell oder ein Nachschlage-Plugin ergänzt | [Plugins schreiben](/de/developers/plugin-authoring/) |
| API-Referenz | [API-Referenz](/de/developers/api/), und `/docs` auf einem laufenden Hub |
| Recherche-Notizen (Druckerprotokolle, IPP-Kompatibilität) | [Recherche-Notizen](https://github.com/strausmann/labelyard/tree/main/docs/research) |
| Datenschutz und Marken | [Richtlinien](https://github.com/strausmann/labelyard/tree/main/docs/policies) |
| Beispiel-Installationen | [`examples/`](https://github.com/strausmann/labelyard/tree/main/examples) |
