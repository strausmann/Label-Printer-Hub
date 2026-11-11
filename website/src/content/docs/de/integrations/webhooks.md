---
title: Webhooks
description: Spoolman und Grocy ein Etikett drucken lassen, wenn sich etwas ändert, mit einem gemeinsamen Webhook-Schlüssel.
---

Zwei Endpunkte nehmen Ereignisse an und drucken daraufhin ein Etikett.

`POST /api/v1/webhook/spoolman` druckt das Etikett der Spule. `quantity` ist das restliche Filament in Gramm und optional:

```json
{ "spool_id": "17", "type": "updated", "quantity": 640 }
```

`POST /api/v1/webhook/grocy` druckt das Etikett des Produkts. `quantity` ist optional:

```json
{ "product_id": "42", "type": "stock_added", "quantity": 2 }
```

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

## Hinter einem Proxy mit SSO

Die Apps, die Webhooks schicken, können sich nicht an einem SSO-Proxy anmelden. Leite `/api/v1/webhook/` daran vorbei: Das Traefik-Beispiel hat für den Pfad einen eigenen Router, das Pangolin-Beispiel eine zweite Ressource ohne Anmeldung (siehe [Reverse Proxy](/de/install/reverse-proxy/)). Der Webhook-Schlüssel schützt die Endpunkte weiterhin.
