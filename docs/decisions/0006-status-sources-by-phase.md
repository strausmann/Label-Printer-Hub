<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# 0006 — Status sources by phase (ESC i S / passive notifications / SNMP)

- **Status:** Accepted (amended 2026-11-10 and 2026-11-17, see the amendments at the end)
- **Amended by:** [0030](0030-confirmed-tape-prints.md) — after sending, the hub waits for the printer's confirmation (IPP job state or the SNMP label counter) instead of one SNMP read; the row "After sending" and the paragraph on an unread status in the 2026-11-17 amendment are history
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

## Phase-0 hardware notes — PT vs QL behaviour differs

Empirical testing during Phase 0 (2026-05-10) revealed an important difference between the two model families:

| Behaviour | PT-Series (PT-P750W) | QL-Series (QL-820NWB) |
|---|---|---|
| `ESC i S` standalone over TCP/9100 | ✅ Returns 32-byte status block | ❌ Returns nothing (no response) |
| `ESC i S` after Invalidate + Initialize + `ESC i a 01` | ✅ Returns | ❌ Returns nothing |
| `ESC i S` embedded in a print-job stream | ✅ Works | ✅ Works (per `brother_ql` library) |
| SNMP Display-OID, Page-Counter, Brother Enterprise OIDs | ✅ Works | ✅ Works (identical OID map) |
| Automatic status notifications during print | ✅ Sent unprompted | ✅ Sent unprompted |

**Implication:** the `PT-Series` plugin can perform a pre-print status probe via `ESC i S` over TCP/9100 directly. The `QL-Series` plugin must instead use SNMP for pre-print check (since standalone `ESC i S` returns nothing). Status during an active print works the same way for both (passive read of automatic notifications).

This is **plugin-encapsulated** behaviour — the public `PrinterModel.query_status()` API is identical; the implementation differs internally. See [ADR 0004](0004-plugin-architecture-for-printer-models.md).

If a future QL firmware version starts answering standalone `ESC i S` (or a contributor finds the magic command sequence we're missing), the QL plugin can be updated without affecting the rest of the system.

## References

- Brother Raster Command Reference v1.02, sections 1 ("Printing using raster commands"), 4 ("Printing command details" → `ESC i S`), and 5 ("Flow charts")
- Brother Enterprise OID 2435 — verified against PT-P750W and QL-820NWBc
- Issue [#14](https://github.com/strausmann/label-printer-hub/issues/14) — SSE EventBus
- Related: ADR 0004 (plugin architecture surfaces these methods), ADR 0005 (queue worker uses passive monitoring during print)

## Amendment — 2026-11-10 (#252)

A live read-only spike (#229) on a PT-P750W and a QL-820NWB found that `ESC i S` on TCP/9100 gets no answer within 8 seconds over the network, with or without the invalidate and initialise prefix. Network status therefore comes from SNMP; `ESC i S` is not a usable status source over TCP/9100 for these families. SNMP reports the tape width but no tape colour (the media colour entry holds a generic value, not a tape colour), so both families ask the person when the roll changes. The spike results (commands, answers, the SNMP entries read) are recorded in issue [#229](https://github.com/strausmann/Label-Printer-Hub/issues/229) and in the ledger of the 1.5.0 plan, Revision 3 ([Task 0 row](../superpowers/plans/2026-11-09-api-v1-live-printers-manifest.md#ledger)). The `ESC i S` rows in the tables above describe the original plan, not what the hub does today; the decision text is left as written.

## Amendment — 2026-11-17 (#389): the status right before and right after sending

Neither print library reads anything back over the network: `brother_ql` returns `outcome: "sent"` right after writing on its `network` backend ("The network backend doesn't support readback"), and `ptouch` only writes. A tape print therefore has two more SNMP reads around the send, both on UDP/161, never on the print connection:

| Phase | Source | What it decides |
|---|---|---|
| **Submit** | SNMP preflight (`preflight_check`) | the loaded tape width the label is drawn for; `payload.loaded_roll` is recorded |
| **Right before sending** (both backends, once per send call; a batch call is checked once) | SNMP preflight | refuses, nothing sent: any blocking error bit (`noPaper` → `tape_empty`, `doorOpen` → `printer_cover_open`, every other bit of `post_send.HARD_ERROR_FLAGS` → `printer_error`), no tape (`no_tape_loaded`), a different width (`tape_mismatch`), a die-cut roll on a QL (`media_type_mismatch`); the read is kept for the job record (`loaded_roll` of the roll it was sent to) |
| **After sending** (`check_after_send`, single jobs and after each group of a tape run) | one SNMP read, `POST_SEND_SETTLE_S` (1 s) after the send | fails the job only on blocking bits that are **new** compared with the read before sending; a bit that was there before refused up front, so a sticky bit never yields a printed-but-failed label |

When the status cannot be read after sending, a **single job** stays `done` (the label was sent; a warning is logged). A **tape run** keeps its #277 behaviour: the group's outcome is `outcome_unknown` and the run stops. The two differ on purpose: a run cannot continue blind, a single label must not be reported as failed when nothing says it failed.

Not verified on hardware: which bit a QL-820NWB sets after it refuses a job ("wrong roll type"), and whether it is visible one second after the send. SNMP has no media type code, only the media text (`prtInputMediaName`); whether a QL names a die-cut roll with a label length is unverified too, and an unrecognised text is never refused. Each roll change is logged at INFO with the reported text and the kind read from it, so a refused print can be traced.

