---
title: Webhooks
description: Spoolman und Grocy ein Etikett drucken lassen, wenn sich etwas ändert, mit einem gemeinsamen Webhook-Schlüssel.
---

Zwei Endpunkte nehmen Ereignisse an und drucken daraufhin ein Etikett. Ein dritter druckt [Grocys eigene Etiketten](#grocys-etikettendrucker-funktion).

`POST /api/v1/webhook/spoolman` druckt das Etikett der Spule. `quantity` ist das restliche Filament in Gramm und optional:

```json
{ "spool_id": "17", "type": "updated", "quantity": 640 }
```

`POST /api/v1/webhook/grocy` druckt das Etikett des Produkts. `quantity` ist optional:

```json
{ "product_id": "42", "type": "stock_added", "quantity": 2 }
```

## Die Menge auf dem Etikett

Eine `quantity` im gültigen Bereich wird als dritte Zeile des Etiketts gedruckt, in der Sprache, die unter **Einstellungen > Allgemein** gewählt ist, nicht in der Sprache des Absenders. Ohne `quantity` oder mit einer außerhalb des Bereichs behält das Etikett seine zwei Zeilen. Sie ist nie eine Anzahl Kopien: Pro Ereignis wird ein Etikett gedruckt.

| Quelle | `quantity` | Englisch | Deutsch |
|---|---|---|---|
| Spoolman | 0 bis 1000000, kaufmännisch auf ganze Gramm gerundet | `851g remaining` | `851 g übrig` |
| Grocy | -1000000 bis 1000000, kaufmännisch auf zwei Nachkommastellen gerundet, mit Vorzeichen | `Stock change: +2` | `Bestandsänderung: +2` (mit Dezimalkomma: `-1,5`) |

Eine dritte Sprache fällt auf Englisch zurück.

Jeder Aufruf antwortet mit `202` und der ID des neuen Auftrags, der an den ersten eingeschalteten Banddrucker geht. Die Etikettendaten kommen vom Plugin für [Spoolman](/de/integrations/spoolman/) oder [Grocy](/de/integrations/grocy/), die Integration muss also verbunden sein.

## Der Webhook-Schlüssel

Webhooks nutzen keine API-Schlüssel. Sie teilen sich ein Geheimnis, das im Header `X-API-Key` mitkommt:

```bash
openssl rand -hex 32   # mindestens 32 Zeichen
```

Setz es als `LABELYARD_WEBHOOK_API_KEY` (oder unter Einstellungen > Zugang und Schlüssel) und trag denselben Wert in der sendenden App ein.

| Antwort | Bedeutung |
|---|---|
| `202` | Angenommen; der Auftrag ist eingereiht |
| `401` | Der Header `X-API-Key` fehlt oder ist falsch |
| `422` | Ein Pflichtfeld im Inhalt fehlt |
| `502` | Das Plugin konnte den Eintrag in seiner App nicht nachschlagen |
| `503` | Kein Webhook-Schlüssel gesetzt oder kein Banddrucker eingeschaltet |

## Grocys Etikettendrucker-Funktion

`POST /api/v1/webhook/grocy/label` ist die Adresse, die Grocys eigene Etikettendrucker-Funktion aufruft (`LABEL_PRINTER_WEBHOOK`); richte sie ein wie unter [Grocys eigene Etiketten drucken](/de/integrations/grocy/#grocys-eigene-etiketten-drucken) beschrieben. Anders als die beiden Endpunkte oben nutzt sie nicht den Webhook-Schlüssel. Grocy schickt keine Header, deshalb steht ein API-Schlüssel mit dem Bereich `print` im Parameter `token` der Adresse (siehe [Schlüssel in einer Adresse](/de/admin/api-keys/#schlüssel-in-einer-adresse)). Der Header `X-Label-Hub-Key` geht auch und gewinnt, wenn beides kommt.

Drucker und Layout kommen aus der Zuordnung der Etikettenart unter **Einstellungen > Integrationen**. Der Hub antwortet vor dem Druck, innerhalb von zwei Sekunden. Grocy wartet nicht länger und zeigt seinem Nutzer die Adresse samt Schlüssel, wenn die Antwort ein Fehler ist oder zu spät kommt.

| Antwort | Bedeutung |
|---|---|
| `202` | Angenommen, mit der ID des Auftrags. Ein Etikett, das der Hub nicht lesen kann (`grocy_label_invalid`) oder dessen Namensfeld nicht zu seiner Art passt (`grocy_label_mismatch`), antwortet ebenfalls mit `202`, mit einem fehlgeschlagenen Auftrag |
| `401` | `invalid_token`: Der Schlüssel fehlt, ist unbekannt, ausgeschaltet oder abgelaufen |
| `403` | `insufficient_scope` (ein `read`-Schlüssel), `token_scope_too_wide` (ein `admin`-Schlüssel) oder `printer_not_allowed` (der Schlüssel darf den Drucker des Etiketts nicht nutzen) |
| `413` | `body_too_large`: Der Inhalt ist größer als 1 MiB |
| `415` | `json_required`: Setz in Grocy `LABEL_PRINTER_HOOK_JSON` auf `true` |
| `429` | `rate_limit_exceeded`: das Limit des Schlüssels pro Minute, mit `Retry-After` |
| `503` | `grocy_label_disabled` (in den Einstellungen ausgeschaltet), `grocy_label_printer_unavailable` (der zugeordnete Drucker ist unbekannt, ausgeschaltet oder ein Seitendrucker) oder kein Banddrucker eingeschaltet |

Scheitert der Drucker nach der Antwort (keine Verbindung, kein Band), wird der Auftrag mit demselben Code als fehlgeschlagen markiert, den `POST /api/v1/print` antworten würde. Keine Antwort nennt einen Drucker.

## Hinter einem Proxy mit SSO

Die Apps, die Webhooks schicken, können sich nicht an einem SSO-Proxy anmelden. Leite `/api/v1/webhook/` daran vorbei: Das Traefik-Beispiel hat für den Pfad einen eigenen Router, das Pangolin-Beispiel eine zweite Ressource ohne Anmeldung (siehe [Reverse Proxy](/de/install/reverse-proxy/)). Der Webhook-Schlüssel schützt die Endpunkte weiterhin.
