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
2. Leg einen Schlüssel an, mit einem Namen, der sagt, wer ihn nutzt, und einem Bereich. Das Formular setzt weder eine Druckerliste noch ein Ratenlimit; setze `allowed_printer_ids` (nicht bei `admin`) und `rate_limit_per_minute` über die API, mit `POST /api/v1/admin/api-keys` oder `PATCH /api/v1/admin/api-keys/{id}`.
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

## Schlüssel in einer Adresse

Eine Route nimmt einen Schlüssel in der Adresse statt im Header an: Grocys Etikettendrucker-Webhook, `POST /api/v1/webhook/grocy/label?token=<schlüssel>`, weil Grocy keine Header schicken kann ([ADR 0027](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0027-url-token-for-the-grocy-label-webhook.md)). Alle anderen Routen ignorieren einen Parameter `token`.

Einen Schlüssel in einer Adresse sieht mehr als nur der Hub. Grocy schreibt die Adresse in sein eigenes Protokoll. Außerdem zeigt Grocy sie dem Grocy-Nutzer, wenn der Hub ein Etikett ablehnt oder nicht innerhalb von 2 Sekunden antwortet. Auch Proxys protokollieren sie oft. Der Hub verbirgt den Wert in seinen eigenen Protokollen. Deshalb:

- Dort geht nur ein `print`-Schlüssel. Ein `read`-Schlüssel antwortet mit `403` und `insufficient_scope`, ein `admin`-Schlüssel mit `403` und `token_scope_too_wide`.
- Leg einen Schlüssel nur für Grocy an und beschränke ihn auf die Drucker von Grocys Etiketten. Ein Etikett, das einem anderen Drucker zugeordnet ist, antwortet dann mit `403` und `printer_not_allowed`.
- Wurde die Adresse gesehen, wo sie nicht hingehört, widerruf den Schlüssel und leg einen neuen an.

## Ratenlimits

Standard sind 60 Anfragen pro Minute und Schlüssel, einstellbar von 1 bis 10.000. Darüber antwortet der Hub mit `429`, einem Header `Retry-After` und dem Fehlercode `rate_limit_exceeded`.

## Bögen

Bögen sind gemeinsames, greifbares Material: Die Routen für Bögen sind nicht durch die Drucker eines Schlüssels beschränkt, und jeder Schlüssel sieht jeden Bogen.

| Route | Bereich |
|---|---|
| `GET /api/v1/sheets`, `/sheets/{code}`, `/sheets/next-code`, `/sheet-cells` | `read` |
| `POST /api/v1/sheets` (anlegen), `/sheets/{code}/cells/mark`, `/cells/unmark`, `/cells/resolve` | `print` |
| `POST /api/v1/sheets/{code}/discard` | `admin` |

Einen Bogen zu verwerfen braucht seit 1.5.x `admin`; vorher konnte das ein `print`-Schlüssel. Ein verworfener Bogen lässt sich nicht zurückholen, und sein Code wird nie wieder vergeben – ein Schlüssel, der nur Etiketten druckt, soll also keinen Bogen ausmustern. Ein `print`-Schlüssel bekommt `403` mit `insufficient_scope`. Zellen markieren und klären bleibt bei `print`, auch für Schlüssel, die auf einige Drucker beschränkt sind.

## Stapel, Vorschauen und Zeichnen

Bandstapel (`POST /api/v1/print/{printer}/batch`) sind je Drucker und je Schlüssel begrenzt:

| Grenze | Standard | Einstellung |
|---|---|---|
| Banddurchläufe, die ein Drucker eingereiht hat oder druckt | 5 (mindestens 5) | `LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER` |
| Banddurchläufe eines Schlüssels über alle Drucker, angehaltene mitgezählt | 20 | `LABELYARD_MAX_QUEUED_RUNS_PER_KEY` |
| Angehaltene Durchläufe je Drucker (gestoppt oder wartend auf `/continue`) | 5 | fest |
| Angehaltene Durchläufe eines Schlüssels auf einem Drucker | 2 | fest |

Eine Browser-Sitzung, die mit einem Schlüssel angemeldet ist, zählt für diese Grenzen als dieser Schlüssel. Über einer Grenze für eingereihte Durchläufe antwortet der Stapel mit `429` und dem Fehlercode `too-many-queued-runs`. Der dritte angehaltene Durchlauf eines Schlüssels auf einem Drucker verwirft den ältesten angehaltenen Durchlauf genau dieses Schlüssels (`run_discarded_limit`), nie den eines anderen. Solange die fünf angehaltenen Plätze eines Druckers belegt sind, lehnt der Hub einen Stapel mit mehr als 50 Etiketten von einem Schlüssel, der dort keinen angehaltenen Durchlauf hat, mit `429` ab; kleinere Stapel nimmt er immer an.

Nur der Schlüssel, der einen Stapel abgeschickt hat, darf seinen Durchlauf mit `continue` fortsetzen, mit `reprint` neu drucken oder mit `discard` verwerfen, und `GET /api/v1/batches/runs/held` zeigt einem Schlüssel nur seine eigenen Durchläufe. Für jeden anderen Schlüssel antwortet der Stapel mit `404`, auch bei `GET /api/v1/batches/{id}`. SSO-Benutzer und Admin-Schlüssel sehen alle Durchläufe und dürfen mit allen arbeiten. Alle Aufrufer ohne Schlüssel (SSO-Benutzer) zählen für die Grenzen der angehaltenen Durchläufe als **ein** Schlüssel: Der angehaltene Durchlauf eines SSO-Benutzers lässt jeden SSO-Benutzer durch die Prüfung der Plätze, und ein weiterer angehaltener Durchlauf eines SSO-Benutzers kann den ältesten eines anderen verwerfen.

Eine Bogenvorschau (`POST /api/v1/print/{printer}/sheet/preview`) läuft je Schlüssel einmal zur selben Zeit; eine zweite antwortet mit `429` `too-many-previews`. Bei Vorschauen unterscheidet der Hub Aufrufer ohne Schlüssel nach Quelle, Benutzer und Adresse.

Der Hub zeichnet höchstens zwei Seiten zugleich, Bogenvorschauen und Seitenaufträge zusammen. Braucht eine Seite länger als `LABELYARD_RENDER_TIMEOUT_S` (Standard 60 Sekunden), endet die Vorschau mit `504` `render-timeout`, und ein Seitenauftrag scheitert mit `render_timeout`. Ihr Zeichen-Thread lässt sich nicht anhalten und behält seinen Platz, bis er endet; ab dem Zeitlimit gilt er als festgefahren, auch wenn sein Aufrufer längst weg ist.

Jeder Besitzer belegt höchstens einen der zwei Plätze zugleich, laufend oder festgefahren: jeder API-Schlüssel für sich (eine mit einem Schlüssel angemeldete Browser-Sitzung zählt als dieser Schlüssel), und alle Aufrufer ohne Schlüssel (SSO-Benutzer, die eigenen Seitenaufträge des Hubs) zusammen als eine Gruppe. Eine zweite Zeichnung desselben Besitzers wartet, höchstens bis zum Zeitlimit, und scheitert dann wie bei vollem Hub. Hat ein Schlüssel eine festgefahrene Zeichnung, antwortet seine nächste Vorschau sofort mit `429` `too-many-previews`, und sein nächster Seitenauftrag scheitert sofort mit `render_timeout`. Hat die Gruppe ohne Schlüssel eine festgefahrene Zeichnung, antwortet eine Vorschau ohne Schlüssel sofort mit `503` `render-unavailable`, und ein Seitenauftrag ohne Schlüssel scheitert sofort mit `render_unavailable`. Sind alle Plätze festgefahren, bekommt jeder Aufrufer diese Antwort.

Das bewusst getragene Restrisiko: Eine Partei allein kann nicht beide Plätze blockieren, zwei verschiedene Besitzer zusammen schon (zwei Schlüssel, oder ein Schlüssel und ein SSO-Benutzer). Schlüssel vergibt ein Admin; widerruf so einen Schlüssel. Das beendet seine weiteren Anfragen, den festgefahrenen Platz gibt aber erst das Ende des Threads oder ein Neustart des Hubs frei. Die Aufrufer ohne Schlüssel teilen sich ihren Platz; eine festgefahrene Zeichnung eines SSO-Benutzers weist deshalb jeden SSO-Benutzer ab, bis sie endet oder der Hub neu startet.

`GET /readiness` zeigt festgefahrene Zeichnungen in der Prüfung `render_slots`, die fehlschlägt, wenn alle Plätze festgefahren sind. `/healthz` zeigt das nicht, dann startest du den Hub von Hand neu. Plätze und Zähler leben im Prozess des Hubs; das Image startet einen Prozess. Startest du das Backend mit mehreren Worker-Prozessen (zum Beispiel `uvicorn --workers 2`), hat jeder seine eigenen zwei Plätze und Zähler, und ein Schlüssel kann in jedem einen Platz belegen.

## Aufträge gehören dem Schlüssel, der sie abgeschickt hat

Jeder Auftrag merkt sich den API-Schlüssel, der ihn abgeschickt hat (Bandetiketten, Stapel, Bögen, Seitenaufträge, Testdrucke und Wiederholungen), auch wenn er aus einer Browser-Sitzung kam, die mit diesem Schlüssel angemeldet ist. Ein Schlüssel ohne `admin` sieht nur seine eigenen Aufträge und arbeitet nur mit ihnen, genauso eine damit angemeldete Browser-Sitzung: Die Anmeldung erweitert nicht, was ein Schlüssel sehen darf.

- `GET /api/v1/jobs` listet nur die Aufträge, die der Schlüssel abgeschickt hat.
- `GET /api/v1/jobs/{id}`, `POST …/cancel`, `…/retry`, `…/pause` und `…/resume` antworten bei einem Auftrag eines anderen Schlüssels mit `404`, mit demselben Inhalt wie bei einem Auftrag, den es nicht gibt.
- `GET /api/v1/printers/{id}/queue` listet nur die eigenen aktiven Aufträge des Schlüssels, und `POST /api/v1/printers/{id}/queue/clear` bricht nur seine eigenen eingereihten Aufträge ab; die Aufträge anderer Schlüssel und von Browser- oder SSO-Benutzern bleiben eingereiht.
- `GET /api/v1/batches/{id}` antwortet bei einem Stapel eines anderen Schlüssels mit `404`.
- Der Ereignisstrom `GET /api/v1/events` liefert `job.state_changed` und `run.state_changed` nur für die eigenen Aufträge und Banddurchläufe des Schlüssels, live und im Schnappschuss. Drucker-Ereignisse (`printer.status`, `printer.tape_changed`, …) erreichen weiter jeden Schlüssel des Druckers, und `queue_depth` zählt weiter die ganze Warteschlange des Druckers.

Ein Auftrag ohne Besitzerschlüssel gehört keinem API-Schlüssel, ein einfacher Schlüssel bekommt für ihn also `404`. Das sind alle Aufträge von SSO-Benutzern, alle Webhook-Aufträge (der Webhook-Schlüssel ist kein API-Schlüssel) und alle Bandaufträge, die 1.5.0 oder älter gespeichert hat – diese Versionen haben Bandetiketten, -stapel und -wiederholungen ohne ihren Schlüssel gespeichert. Ein Auftrag, den der Hub nach einem Neustart wiederherstellt, behält den Schlüssel, mit dem er gespeichert wurde.

SSO-Benutzer, Admin-Schlüssel und mit einem Admin-Schlüssel angemeldete Browser-Sitzungen sehen jeden Auftrag ihrer Drucker und dürfen mit jedem arbeiten. Haben sich mehrere Clients die Aufträge eines Druckers über verschiedene Schlüssel geteilt, gib dem Client, der alle sehen muss, einen Admin-Schlüssel, oder lass jeden Client seine eigenen Aufträge verfolgen.

## Erster Schlüssel und Notzugang

Eine frische Installation hat keinen Schlüssel; die [Installation](/de/install/) zeigt die zwei Wege zum ersten. Sind alle Admin-Schlüssel verloren, legst du im Container einen neuen an. Er wird einmal ausgegeben:

```bash
docker compose exec labelyard labelyard admin create-key --scope admin --name recovery
```

Wer Befehle im Container ausführen kann, hat den Hub ohnehin in der Hand, deshalb öffnet das keinen neuen Weg hinein. Widerruf danach die verlorenen Schlüssel. Wenn du einen Schlüssel widerrufst, enden auch alle Browsersitzungen, die sich damit angemeldet haben.
