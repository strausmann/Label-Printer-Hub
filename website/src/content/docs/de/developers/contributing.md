---
title: Mitmachen
description: Backend, Weboberfläche und diese Website einrichten und eine Änderung einreichen.
---

Beiträge sind willkommen, besonders Plugins für Druckermodelle. Die vollständigen Regeln stehen in [CONTRIBUTING.md](https://github.com/strausmann/labelyard/blob/main/CONTRIBUTING.md); diese Seite ist die Kurzfassung.

## Backend

```bash
gh repo fork strausmann/labelyard --clone
cd labelyard/backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Vor einem Pull Request führst du in `backend/` aus: `ruff check .`, `ruff format --check .`, `mypy app/` (strikt) und `pytest`. Die CI macht dasselbe, und alle vier sind harte Schranken.

## Wie Änderungen entstehen

- **Zuerst die Tests.** Schreib den fehlschlagenden Test, dann den Code.
- **Conventional Commits.** `feat:`, `fix:`, `docs:` und so weiter; semantic-release macht daraus die Versionen.
- **Die Druckwarteschlange ist Pflicht.** Nichts druckt an ihr vorbei.
- **Druckerspezifischer Code** bleibt in seinem Plugin unter `app/printer_models/`.

## Diese Website

Die Seite liegt in `website/` und wird mit Astro Starlight gebaut:

```bash
pnpm -C website install
pnpm -C website dev
```

Die Website wird auf Englisch und Deutsch gemeinsam gepflegt. Eine Änderung an einer Seite unter `website/src/content/docs/` ist erst fertig, wenn die englische und die deutsche Seite im selben Pull Request geändert werden. Die Prüfung `website / locale parity` schlägt fehl, wenn es eine Seite nur in einer Sprache gibt.

Der Build prüft jeden internen Link und Anker; ein kaputter lässt ihn scheitern. Die [Konfigurationsreferenz](/de/reference/configuration/) wird aus den Backend-Einstellungen erzeugt: Ändere die Beschreibungen in `website/src/config-descriptions.yml` und führ `website/scripts/gen-config-reference.py` aus.

## Marken

Brother, P-touch, PT-Series und QL-Series sind Marken der Brother Industries, Ltd. Nenn sie nur, um Kompatibilität zu beschreiben.
