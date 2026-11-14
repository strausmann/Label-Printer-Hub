---
title: API-Schlüssel
description: Einen Schlüssel je Aufrufer anlegen, Bereich und Drucker wählen und wieder hineinkommen, wenn alle Admin-Schlüssel verloren sind.
---

Alles, was kein Browser hinter einem SSO-Proxy ist, meldet sich mit einem API-Schlüssel an: die Weboberfläche, Skripte, andere Apps. Schick ihn im Header `X-Label-Hub-Key`. Der Header-Name und das Präfix `lh_` der Schlüssel stammen noch vom früheren Projektnamen und bleiben, damit bestehende Clients weiter funktionieren.

## Bereiche

| Bereich | Erlaubt | Wofür |
|---|---|---|
| `read` | Nur lesen | Überwachung, Statusseiten |
| `print` | Lesen und drucken | Apps und Skripte, die drucken |
| `admin` | Alles, auch Einstellungen und Schlüssel | Menschen, die den Hub verwalten |

Jeder Bereich schließt die darüber ein. Ein `read`- oder `print`-Schlüssel lässt sich außerdem auf einzelne Drucker beschränken; eine leere Liste erlaubt alle. Ein Schlüssel mit dem Bereich `admin` wirkt immer auf jeden Drucker und lässt sich deshalb nicht beschränken: Eine Druckerliste an einem Admin-Schlüssel lehnt der Hub mit `422` und `admin_key_not_restrictable` ab.

## Einen Schlüssel anlegen

1. Melde dich mit einem Admin-Schlüssel an und öffne **Einstellungen > Zugang und Schlüssel**.
2. Leg einen Schlüssel an, mit einem Namen, der sagt, wer ihn nutzt, mit Bereich, Druckern (nicht bei `admin`) und Ratenlimit.
3. Kopier den Schlüssel. Er wird **einmal** angezeigt; der Hub speichert nur einen bcrypt-Hash davon.

Leg einen Schlüssel je Aufrufer an, damit du einen widerrufen kannst, ohne die anderen anzufassen.

## Einen Schlüssel benutzen

```bash
curl -H "X-Label-Hub-Key: lh_..." https://labelyard.example.com/api/v1/printers

curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_two_lines",
       "data": {"title": "Asset 123", "primary_id": "ASSET-123",
                "qr_payload": "https://snipe.example.com/hardware/123"}}'
```

Anfragen, die sich mit einem Schlüssel im Header anmelden, laufen nicht durch die CSRF-Prüfung; die schützt nur Browsersitzungen.

## Ratenlimits

Standard sind 60 Anfragen pro Minute und Schlüssel, einstellbar von 1 bis 10.000. Darüber antwortet der Hub mit `429`, einem Header `Retry-After` und dem Fehlercode `rate_limit_exceeded`.

## Erster Schlüssel und Notzugang

Eine frische Installation hat keinen Schlüssel; die [Installation](/de/install/) zeigt die zwei Wege zum ersten. Sind alle Admin-Schlüssel verloren, legst du im Container einen neuen an. Er wird einmal ausgegeben:

```bash
docker compose exec labelyard labelyard admin create-key --scope admin --name recovery
```

Wer Befehle im Container ausführen kann, hat den Hub ohnehin in der Hand, deshalb öffnet das keinen neuen Weg hinein. Widerruf danach die verlorenen Schlüssel. Wenn du einen Schlüssel widerrufst, enden auch alle Browsersitzungen, die sich damit angemeldet haben.
