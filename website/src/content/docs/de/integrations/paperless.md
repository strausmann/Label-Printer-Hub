---
title: Paperless-ngx
description: Etiketten für Dokumente in Paperless-ngx über die API von Labelyard drucken.
---

Für Paperless-ngx hat Labelyard kein Such-Plugin. Etiketten für Dokumente, etwa Etiketten mit der Archivseriennummer (ASN), druckst du über die API des Hubs.

## Einrichtung

1. Leg in Labelyard dafür einen API-Schlüssel mit dem Bereich `print` an (siehe [API-Schlüssel](/de/admin/api-keys/)).
2. Optional: Trag unter **Einstellungen > Integrationen > Paperless** die Adresse von Paperless und ein API-Token ein und teste die Verbindung. Oder setz `LABELYARD_PAPERLESS_URL` und `LABELYARD_PAPERLESS_TOKEN`.

## Ein Etikett drucken

Text und QR-Inhalt schickst du selbst in `data`:

```bash
curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_one_line",
       "data": {"title": "ASN 000123", "primary_id": "ASN000123",
                "qr_payload": "ASN000123"}}'
```

Die Antwort enthält die Auftrags-ID; wie du ihr folgst, zeigt die [Druckwarteschlange](/de/using/queue/). Für viele Etiketten auf einmal auf einen Bogen siehe die Bogen-Endpunkte in der [API-Referenz](/de/developers/api/).
