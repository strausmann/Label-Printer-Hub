# Phase 1i UUID-Continuity-Check (MA-2-Fix)

**Datum:** 2026-06-03
**Pre-Deploy-Status:** ✅ CONTINUITY BESTÄTIGT

## Existing DB-Row (label-printer-hub-backend Container auf hhdocker03)

| id (UUID) | slug | model | host | port |
|---|---|---|---|---|
| `c497ec0797585d7096b5f0cac97b71f7` | brother-p750w | pt-p750w | 172.16.50.212 | 9100 |

Lese-Befehl (SSH MCP auf hhdocker03 statt Dockhand exec — letzteres liefert nur execId ohne Output):

```bash
ssh hhdocker03 sqlite3 /docker/stacks/hangar-print-hub/data/hub/printer-hub.db \
  "SELECT id, slug, model, json_extract(connection, '\$.host') as host, json_extract(connection, '\$.port') as port FROM printers;"
```

## derive_printer_id (lokal berechnet)

```python
from app.services.printer_identity import derive_printer_id
derive_printer_id('pt-p750w', '172.16.50.212', 9100)
# -> c497ec07-9758-5d70-96b5-f0cac97b71f7  (Bindestriche nur Darstellung)
derive_printer_id('PT-P750W', '172.16.50.212', 9100)
# -> c497ec07-9758-5d70-96b5-f0cac97b71f7  (case-insensitive)
derive_printer_id('QL-820NWB', '172.16.51.213', 9100)
# -> 36365bdd-76c3-5bf3-875b-91aa30712816  (neu — keine bestehende Row)
```

## Continuity-Vergleich

| Drucker | Bestehende DB-UUID | derive_printer_id Ergebnis | Status |
|---------|-------------------|---------------------------|--------|
| PT-P750W | `c497ec07-9758-5d70-96b5-f0cac97b71f7` | `c497ec07-9758-5d70-96b5-f0cac97b71f7` | ✅ OK (identisch) |
| QL-820NWB | (existiert nicht) | `36365bdd-76c3-5bf3-875b-91aa30712816` | ✅ NEU (erwartet) |

## Befund

- `derive_printer_id` ist **case-insensitive** für den model-String — `pt-p750w` (DB) und `PT-P750W` (printers.yaml) liefern dieselbe UUID
- Deploy mit dem Phase-1i-Schema überschreibt die bestehende Row mit identischer UUID — alle PrintJobs/StatusBlocks bleiben verknüpft
- QL820 wird als zweite Row neu angelegt

## Folge für printers.yaml

```yaml
schema_version: 1
printers:
  - slug: brother-p750w
    name: "Brother PT-P750W"
    backend: ptouch
    model: PT-P750W           # auch lowercase 'pt-p750w' wäre OK
    host: 172.16.50.212
    port: 9100
    snmp:
      discover: true
      community: public
  - slug: brother-ql820
    name: "Brother QL-820NWB"
    backend: brother_ql
    model: QL-820NWB
    host: 172.16.51.213
    port: 9100
    snmp:
      discover: true
      community: public
```

Deploy darf erfolgen.
