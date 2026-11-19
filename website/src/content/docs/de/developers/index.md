---
title: Entwickeln
description: Auf der API von Labelyard aufbauen, es mit Plugins erweitern und die API-Referenz finden.
sidebar:
  label: Überblick
---

Labelyard ist ein FastAPI-Backend (Python 3.12, SQLite, asyncio), das auch eine Weboberfläche in React und TypeScript ausliefert, in einem Container. Alles, was die Weboberfläche tut, läuft über dieselbe versionierte REST-API, die auch dein eigener Code nutzen kann.

## Die API

- **Versionierte Pfade.** Jede Route liegt unter `/api/v1/`. Nur die Prüfpfade `/healthz` und `/readiness` liegen außerhalb.
- **Anmeldung.** Schick einen API-Schlüssel in `X-Label-Hub-Key` (siehe [API-Schlüssel](/de/admin/api-keys/)); Webhooks nutzen `X-API-Key`.
- **Live-Ereignisse.** `/api/v1/events` liefert Server-Sent Events zu Änderungen an Druckern und Aufträgen.
- **Der Vertrag.** Das OpenAPI-Dokument wird aus dem Code erzeugt, von jedem laufenden Hub unter `/openapi.json` ausgeliefert und dort unter `/docs` zum Blättern angeboten. Die [API-Referenz](/de/developers/api/) auf dieser Seite wird beim Bauen aus demselben Dokument erzeugt.

Die API-Referenz ist die einzige Stelle dieser Seite, die nicht vollständig auf Deutsch vorliegt: Navigation und Rahmen sind deutsch, aber die Beschreibungen der Operationen kommen aus dem englischen OpenAPI-Dokument, und die Abschnittsüberschriften des Plugins (Parameters, Responses, Request Body) sind fest auf Englisch.

Fehler tragen einen maschinenlesbaren `error_code`, zum Beispiel `tape_empty`, `printer_offline` oder `content_type_data_mismatch`, damit ein Client auf die Ursache reagieren kann statt auf den Statuscode.

**Fehlerantworten der Druckrouten.** Jede Route, die ein Etikett druckt oder zeichnet, beantwortet einen bekannten Drucker- oder Darstellungsfehler mit demselben Status und Code: 409 für den Drucker oder das Band (`printer_disabled`, `printer_cover_open`, `printer_error` für jeden anderen Fehlerzustand, den der Drucker meldet, `no_tape_loaded`, `tape_empty`, `tape_mismatch`, `media_type_mismatch` für eine Rolle mit gestanzten Einzeletiketten, `unsupported_tape`), 422 für die Etikettendaten (`content_type_data_mismatch`, `qr_payload_too_long`, `tape_label_too_long` für ein Etikett, das länger ist, als sein Band erlaubt, `integration_unknown_app`), 502 für eine gescheiterte Abfrage (`integration_lookup_failed`) und 503 für einen nicht erreichbaren Drucker (`printer_offline`, `snmp_query_failed`). Die Form der Antwort ist die der jeweiligen Route und steht bei ihren Antworten in der [API-Referenz](/de/developers/api/); eine Problem-Antwort schreibt den Code mit `-` (`unsupported-tape`) und trägt die Einzelheiten in `extensions`. Der Testdruck beantwortet einen nicht erreichbaren Drucker mit 409 `printer-offline`.

## Labelyard erweitern

- **Druckermodelle** sind Plugins in `backend/app/printer_models/`; eine Datei je Serie hält modellspezifischen Code aus dem Rest heraus.
- **Integrationen** sind Python-Pakete, die sich über den Entry Point `label_hub.integrations` anmelden. Ein Plugin bietet ein `lookup(identifier)`, das die Etikettendaten zurückgibt; die mitgelieferten Plugins für Snipe-IT, Grocy und Spoolman sind die Vorbilder. Plugins von Dritten installierst du mit `pip` neben dem Hub, ohne dieses Repository zu ändern.

Wie du eine Entwicklungsumgebung einrichtest und eine Änderung einreichst: [Mitmachen](/de/developers/contributing/).
