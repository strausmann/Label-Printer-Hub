# Brother SNMP OIDs used by First-Print

`pysnmp>=6.2` (asyncio API in `pysnmp.hlapi.v3arch.asyncio`).

## Discovery

| OID | Returns | Used for |
|---|---|---|
| `1.3.6.1.4.1.2435.2.3.9.1.1.7.0` | PJL identification string: `MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;` | Lifespan startup → `ModelRegistry.find_by_pjl(...)` |

## Live status during print (Host-Resources Printer MIB, RFC 1213)

| OID | Returns | Mapping |
|---|---|---|
| `1.3.6.1.2.1.25.3.5.1.1.1` (`hrPrinterStatus`) | Integer: 1=other, 2=unknown, 3=idle, 4=printing, 5=warmup | string in `LiveStatus.hr_printer_status` |
| `1.3.6.1.2.1.25.3.5.1.2.1` (`hrPrinterDetectedErrorState`) | OCTET STRING of bytes; bits select errors | list of bit names in `LiveStatus.error_flags` |

### `hrPrinterDetectedErrorState` bit map (byte 0, MSB first)

| Bit | Name | Notes |
|---|---|---|
| 0 | lowPaper | not used by PT-Series |
| 1 | noPaper | maps to tape empty/end |
| 2 | lowToner | not applicable |
| 3 | noToner | not applicable |
| 4 | doorOpen | cover open |
| 5 | jammed | media jam |
| 6 | offline | printer reports offline |
| 7 | serviceRequested | hard fault, contact service |

Byte 1: inputTrayMissing, outputTrayMissing, markerSupplyMissing, outputFull, inputTrayEmpty, overduePreventMaint — none relevant for PT-Series tape devices in First-Print.

## Authentication

SNMPv2c, community read-only. Default community is `public`; configurable via `printer_snmp_community` setting. The PT-P750W is on the LAN/Tailscale, not on the open internet, so v2c is sufficient.

## Why this and not ESC i S

| Job | ESC i S (TCP/9100) | SNMP (UDP/161) |
|---|---|---|
| Pre-print tape match | direct (byte 10) | needs string parsing |
| Discovery (PJL) | not available | **only path** |
| During-print status | blocked by ptouch's TCP session | **runs in parallel** |
