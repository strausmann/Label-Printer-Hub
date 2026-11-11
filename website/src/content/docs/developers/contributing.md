---
title: Contributing
description: Set up the backend, the web UI and this website, and send a change.
---

Contributions are welcome, printer model plugins in particular. The full rules are in [CONTRIBUTING.md](https://github.com/strausmann/labelyard/blob/main/CONTRIBUTING.md); this page is the short version.

## Backend

```bash
gh repo fork strausmann/labelyard --clone
cd labelyard/backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Before a pull request, from `backend/`: `ruff check .`, `ruff format --check .`, `mypy app/` (strict) and `pytest`. CI runs the same, and all four are hard gates.

## How changes are made

- **Tests first.** Write the failing test, then the code.
- **Conventional Commits.** `feat:`, `fix:`, `docs:` and so on; releases are made from them by semantic-release.
- **The print queue is mandatory.** Nothing prints past it.
- **Printer-specific code** stays in its plugin under `app/printer_models/`.

## This website

The site lives in `website/` and is built with Astro Starlight:

```bash
pnpm -C website install
pnpm -C website dev
```

The website is maintained in English and German together. A change to any page under `website/src/content/docs/` is complete only when the English and the German page change in the same pull request. The `website / locale parity` check fails when a page exists in one language only.

The build checks every internal link and anchor; a broken one fails it. The [configuration reference](/reference/configuration/) is generated from the backend settings: edit the descriptions in `website/src/config-descriptions.yml` and run `website/scripts/gen-config-reference.py`.

## Trademarks

Brother, P-touch, PT-Series and QL-Series are trademarks of Brother Industries, Ltd. Name them only to describe compatibility.
