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

## Labelyard erweitern

- **Druckermodelle** sind Plugins in `backend/app/printer_models/`; eine Datei je Serie hält modellspezifischen Code aus dem Rest heraus.
- **Integrationen** sind Python-Pakete, die sich über den Entry Point `label_hub.integrations` anmelden. Ein Plugin bietet ein `lookup(identifier)`, das die Etikettendaten zurückgibt; die mitgelieferten Plugins für Snipe-IT, Grocy und Spoolman sind die Vorbilder. Plugins von Dritten installierst du mit `pip` neben dem Hub, ohne dieses Repository zu ändern.

Wie du eine Entwicklungsumgebung einrichtest und eine Änderung einreichst: [Mitmachen](/de/developers/contributing/).
