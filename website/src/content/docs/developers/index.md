---
title: Developers
description: Build on the Labelyard API, extend it with plugins, and find the API reference.
sidebar:
  label: Overview
---

Labelyard is a FastAPI backend (Python 3.12, SQLite, asyncio) that also serves a React and TypeScript web UI, in one container. Everything the web UI does goes through the same versioned REST API that your own code can use.

## The API

- **Versioned paths.** Every route lives under `/api/v1/`. The probes `/healthz` and `/readiness` stay outside.
- **Authentication.** Send an API key in `X-Label-Hub-Key` (see [API keys](/admin/api-keys/)); webhooks use `X-API-Key`.
- **Live events.** `/api/v1/events` streams Server-Sent Events for printer and job changes.
- **The contract.** The OpenAPI document is generated from the code, served by every running hub at `/openapi.json`, and browsable there at `/docs`. The [API reference](/developers/api/) on this site is rendered from the same document at build time.

Errors carry a machine-readable `error_code`, for example `tape_empty`, `printer_offline` or `content_type_data_mismatch`, so a client can react to the cause rather than to the status code.

## Extending Labelyard

- **Printer models** are plugins in `backend/app/printer_models/`; one file per series keeps model-specific code out of the rest.
- **Integrations** are Python packages registered through the `label_hub.integrations` entry point. A plugin implements a `lookup(identifier)` that returns the label data; the bundled Snipe-IT, Grocy and Spoolman plugins are the examples. Third-party plugins install with `pip` next to the hub, without a change to this repository.

How to set up a development environment and send a change: [contributing](/developers/contributing/).
