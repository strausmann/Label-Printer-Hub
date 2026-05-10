# 0006 — Status sources by phase (ESC i S / passive notifications / SNMP)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

Brother label printers expose three status-discovery channels:

1. **TCP/9100 `ESC i S`** request → printer replies with a 32-byte status block (full info: tape width, type, errors, phase, colours)
2. **TCP/9100 automatic notifications** — during a print job, the printer pushes status blocks unprompted (phase changes, completion, errors)
3. **SNMP v2c** (community `public` by default) — exposes printer-MIB OIDs (Display LCD text, page counter, alerts, serial number)

These channels have different costs and different availability windows:
- `ESC i S` opens a TCP connection — heavyweight; **forbidden during an active print**
- Passive TCP read works only while a print is in flight (Brother sends updates spontaneously)
- SNMP is the only channel that works at any time, including during a print, on a separate UDP/161 socket

Choosing the wrong source for a given moment leads to wasted connections, missed events, or even deadlocks (e.g. opening a TCP connection while a print is running). The Brother Raster Command Reference v1.02 explicitly forbids sending commands during printing.

## Decision

The hub uses different sources for different phases:

| Phase | Source | Why |
|---|---|---|
| **Pre-print check** | TCP/9100 `ESC i S` | Most complete data: tape width/type, error flags, colours, model code |
| **Active print monitoring** | Passive read of the open TCP connection | Brother pushes status changes automatically; we already hold the socket |
| **Idle / dashboard polling (every 30 s)** | SNMP Display-OID `1.3.6.1.2.1.43.16.5.1.2.1.1` + Page-Counter `1.3.6.1.2.1.43.10.2.1.4.1.1` | Lightweight; doesn't open TCP; safe to call any time |
| **Wake-from-sleep detection** | SNMP polled at 1 s for up to 30 s | PT-Series enters sleep after ~5 min idle and needs ping to wake |
| **Tape change detection** | Periodic comparison of SNMP-reported state vs last cached `ESC i S` block; on change, trigger fresh `ESC i S` for full details | Combines cheap polling with deep-inspect on change |

The `StatusBlockParser` (32-byte spec layout) is the canonical decoder; SNMP responses are mapped into the same `StatusBlock` dataclass for unified handling.

The full status-block schema, error bitmaps, tape codes and colour tables are documented in [`../research/2026-05-10-brother-pt-raster-extract.md`](../research/2026-05-10-brother-pt-raster-extract.md) (to be migrated from the maintainer's mono-repo).

## Options considered

### Option A — Phase-specific sources (chosen)
- Pros: respects Brother spec constraints; minimum overhead per phase; never deadlocks the printer
- Cons: more code to keep straight; need to document clearly so contributors don't bypass

### Option B — SNMP-only for everything
- Pros: simplest; one channel
- Cons: SNMP doesn't expose all fields the 32-byte status block has (tape colour, text colour, error info 2 sub-bits); slower change detection; no active-print fidelity

### Option C — TCP `ESC i S` polled every N seconds
- Pros: rich data
- Cons: forbidden during print; wastes printer cycles on idle when SNMP is enough

## Consequences

- `StatusProbe` class in `backend/app/services/status_probe.py` exposes a single async API; internally chooses source by hub state
- Idle polling is rate-limited to 30 s default (configurable) to avoid hammering the printer's CPU
- Wake-from-sleep loop bounded at 30 s timeout; failure surfaces as `printer_offline` event
- `EventBus` receives a `tape_changed` event when the cached state diverges from a fresh `ESC i S` read
- Documentation must clearly mark which methods are safe during a print and which aren't (see `docs/architecture.md`)

## References

- Brother Raster Command Reference v1.02, sections 1 ("Printing using raster commands"), 4 ("Printing command details" → `ESC i S`), and 5 ("Flow charts")
- Brother Enterprise OID 2435 — verified against PT-P750W and QL-820NWBc
- Issue [#14](https://github.com/strausmann/label-printer-hub/issues/14) — SSE EventBus
- Related: ADR 0004 (plugin architecture surfaces these methods), ADR 0005 (queue worker uses passive monitoring during print)
