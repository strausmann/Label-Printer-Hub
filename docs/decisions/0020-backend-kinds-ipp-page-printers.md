<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0020 — Page printers are a backend kind (IPP) with the hub's own client

- **Status:** Accepted
- **Accepted:** 2026-11-10 (#252) — shipped in 1.2.0–1.4.0
- **Amended:** 2026-11-09 (#226) — every API route now lives under `/api/v1/`; the paths quoted below are the original ones, the decision is unchanged
- **Date:** 2026-11-06
- **Deciders:** maintainer
- **Amends:** ADR-0004 (does not supersede it), and narrows ADR-0005's cancel rule to raw streams
- **Decision label:** D18

## Context

The sheet archive (spec `docs/superpowers/specs/2026-11-05-sheet-archive-design.md`, sections 11 and 20) prints label sheets (A4 / Letter die-cut sheets) on ordinary office page printers. Until now every printer the hub drives is a Brother raster device: tape or die-cut labels, a TCP/9100 byte stream, a model identified by its SNMP PJL string. ADR 0004 makes each such model family a `PrinterModel` plugin chosen through that PJL string.

Page printers do not fit that shape. They are many vendors and models; they speak IPP (RFC 8010/8011), which describes the printer's own capabilities (formats, media, trays, margins, state); they take whole documents, not raster lines; and they keep their own job queue that IPP can query and cancel. A plugin per page-printer model would be pointless — the protocol is model-agnostic — and the PJL identification of ADR 0004 does not exist for them.

ADR 0005 forbids cancelling a job once it is printing, because a TCP/9100 stream has no way to stop the device mid-label. IPP defines Cancel-Job.

## Decision

We add printer families beyond the Brother raster protocol as **backend kinds**, and the first one is `ipp`: a page printer reached by an IPP URI, driven by the hub's own small IPP client over `httpx`, sent **PDF only**, configured in the web UI.

- **Backend kind, not model plugin.** `printers.backend` accepts `ipp`. An `ipp` printer has no `PrinterModel` plugin, no SNMP discovery and no cut defaults; `model` is informational and filled from `printer-make-and-model`. The `PrinterModel` protocol of ADR 0004 stays the extension point for raster families that are identified by PJL. `ipp` rows never enter the tape wiring (backend router, model resolution, SNMP producers); tape routes answer `409 media_kind_mismatch` for them.
- **Own client.** `app/printer_backends/ipp/` encodes and decodes the binary IPP message and runs Get-Printer-Attributes, Print-Job, Get-Job-Attributes, Get-Jobs, Cancel-Job (and Validate-Job). It reuses the hub's HTTP stack, bounds every exchange (1 MB response cap, timeouts, no redirects, no proxy from the environment) and carries no new dependency.
- **PDF only.** The hub renders every page itself and sends `application/pdf`. A printer that does not list PDF in `document-format-supported` cannot be saved (`409 ipp_pdf_unsupported`, OC-18).
- **Cancel-Job is allowed for IPP.** ADR 0005's "no mid-print cancel" is about TCP/9100 streams. For an `ipp` printer the hub may cancel a job the printer already holds; the queue tracks the cancel to its final state.
- **Configuration in the UI** (D6). The admin enters the URI (`ipp`, `ipps`, `http`, `https`; no user info, no fragment), TLS verification (on by default, may be switched off for self-signed certificates, OC-17) and trays. `POST /api/v1/admin/printers/ipp/probe` (admin only) reads the printer live and returns a bounded summary. It sits on the existing admin printers router, so it follows that router's `/api/v1/admin/printers` prefix rather than the spec's `/api/admin/printers/ipp/probe`. Saving probes the printer too; nothing is saved when it is unreachable, lacks PDF, or does not report a configured tray.

## Options considered

### Option A — backend kind `ipp` with an own client over httpx (chosen)
- Pros: one HTTP stack; small, fully specified wire format; every limit is ours to set; testable with synthetic fixtures and a fake printer; no model-specific code.
- Cons: the hub owns an IPP codec (mitigated by an interoperability spike against CUPS' `ippeveprinter`/`ipptool`, [research note](../research/2026-11-05-ipp-client-interop.md)).

### Option B — `pyipp`
- Pros: existing library.
- Cons: built on `aiohttp` (a second HTTP client stack), designed for status reading, more dependencies.

### Option C — CUPS / `pycups`
- Pros: mature driver stack.
- Cons: needs CUPS in the image or on the host, and adds the driver layer the issue rules out.

### Option D — a `PrinterModel` plugin per page printer
- Pros: no new concept.
- Cons: the protocol is model-agnostic, PJL identification does not exist for these printers, and every new model would need a plugin for nothing.

## Consequences

- `printers.backend` has three values; code that wires tape printers filters `ipp` rows out (`app/main.py`), and the tape batch route refuses them.
- New tables `printer_trays` and `printer_calibrations` (migration `20261105b1`). Trays are replaced as a whole when the admin saves them.
- The IPP URI is connection detail: `GET /api/printers` and `GET /api/printers/{id}` show it to admin callers only; other callers see `{"tls_verify": …}` (spec 14, 18).
- The probe is an SSRF surface by nature (the hub connects where an admin says). It is admin only, limited to the four schemes without user info, bounded by the client's limits, and its errors never repeat the URI or the printer's answer beyond the IPP status name.
- IPP authentication is out of scope (OC-2); the hub stores no printer secrets.
- Follow-ups in the same plan: status polling for page printers, page jobs in the queue with tracking, cancel and restart recovery, manual calibration, the capabilities endpoint.

## References

- Spec: `docs/superpowers/specs/2026-11-05-sheet-archive-design.md` (sections 4, 7.1, 11, 14, 18, 20)
- Related ADRs: [0004](0004-plugin-architecture-for-printer-models.md) (amended), [0005](0005-print-queue-is-mandatory.md) (cancel rule narrowed to raw streams), [0011](0011-openapi-as-api-contract.md)
- RFC 8010, RFC 8011 (IPP/1.1), PWG 5100.7 (`media-col`)
