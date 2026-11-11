# 0024 — Printers are wired at runtime through one code path and identified by hardware

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** maintainer
- **Related:** [0005](0005-print-queue-is-mandatory.md) (print queue), [0006](0006-status-sources-by-phase.md) (status sources), [0020](0020-backend-kinds-ipp-page-printers.md) (IPP page printers), [0023](0023-sheet-archive.md) (calibration, D17)

## Context

Up to 1.4.x the hub wired printers once, in the startup lifespan. A printer added, changed or disabled in the admin UI was stored, but its status polling, queue worker and print service only followed after a restart (#224). Two code paths (startup and "something changed") would have drifted apart.

A printer is stored by its network address. Calibration (D17) belongs to a printer and tray, so it describes a physical device. When a device behind the same address is swapped, for example a replaced office printer that gets the old IP, the stored calibration is silently applied to a different machine, and sheet cells land in the wrong place (#231).

## Decision

**Every printer is wired through one runtime component, at startup and on every admin change; and each printer carries the hardware identity of the device seen behind its address, so that a swap holds sheet jobs until a person decides.**

- **One wiring path.** `PrinterRuntime` (`backend/app/services/printer_runtime.py`) owns `attach`, `detach` and `reconcile`. The lifespan attaches every enabled printer; an admin create, update or disable calls `reconcile`. A printer wired at runtime is wired exactly like one wired at startup: tape printers get their router entry, print service, queue printer and (with SNMP discovery) status and tape-change producers; IPP printers get their page client, state, queue printer and status producer.
- **Re-wire only on what wiring depends on.** `wiring_key` lists the fields the wiring is built from (enabled, backend, connection, model, SNMP settings, IPP trays, IPP timeout). Equal keys need no re-wire; name, label, cut and layout defaults are handed over without one.
- **Ordering.** One lock per printer id serializes attach, detach and reconcile. A producer stops before its printer leaves the queue. Producers start only after the runtime starts, so startup never waits for a probe.
- **Hardware identity.** After each successful probe the status producer reports every identity candidate it saw. The strongest stored kind wins: SNMP serial number, then IPP `printer-uuid`, then MAC address. Comparison is always on the stored kind, and a probe that reports nothing of that kind never counts as a mismatch.
- **A different device holds sheet jobs.** A reading that differs is recorded beside the stored identity, never over it, and starts a mismatch. While the mismatch lasts the queue holds that printer's sheet and calibration pages (not the test page, which is how an operator checks the printer) and the UI shows the swap. An admin resolves it with `same_device` (calibration stays) or `replaced` (calibration is deleted). The hold is re-read from the database on every change, fails closed (a read that fails may set a hold, never release one) and is restored after a restart.
- **Identity values are inventory data for admins.** They appear only in admin views; they are never logged and never sent in events. The SSE event carries only the flag and its start time.

## Options considered

### Option A — one runtime component for startup and changes (picked)
- Pros: one path, so runtime and startup wiring cannot drift; changes take effect without a restart.
- Cons: concurrency (add during recovery, remove during add) has to be handled explicitly; done with the per-printer lock and the producer-before-queue order.

### Option B — keep startup wiring and require a restart after printer changes
- Pros: no runtime concurrency.
- Cons: a stored printer that does nothing until a restart; the cause of #224.

### Option C — identify printers by address only, warn on a model change
- Pros: no identity storage.
- Cons: a swap to the same model goes unnoticed, which is the case that ruins sheets.

## Consequences

- Printer changes in the admin UI take effect immediately, including status polling and disable.
- Sheet and calibration pages on a printer whose device changed wait until an admin resolves the swap; tape jobs and the test page are not held.
- Printers that report no identity at all (no SNMP serial, IPP UUID or MAC) are not protected against swaps.
- Follow-ups are tracked in #263 (for example the orphan worker after a failed IPP attach, R17-4).

## References

- Issues: #224, #231, #252
- Code: `backend/app/services/printer_runtime.py`, `backend/app/services/hardware_identity.py`
