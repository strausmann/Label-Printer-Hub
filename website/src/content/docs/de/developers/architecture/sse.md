---
title: Ereignisstrom und Reverse Proxys
description: "Der Strom /api/v1/events: warum ein Proxy ihn nicht puffern darf, Einstellungen für Traefik, Caddy, Nginx und Pangolin, wie du ihn prüfst und wie seine Frames aussehen."
sidebar:
  label: Ereignisstrom
---

Der Endpunkt `/api/v1/events` liefert Antworten als `text/event-stream`. Das Backend schickt ihn direkt an den Browser (ein Prozess, ADR 0015), also gelten diese Einstellungen für den Reverse Proxy vor dem Hub. Alle gängigen Reverse Proxys puffern Antworten von Haus aus – damit geht SSE kaputt, denn der Client bekommt nichts, bis der Puffer geleert oder die Verbindung geschlossen wird.

Das Backend setzt bei jeder SSE-Antwort `X-Accel-Buffering: no`. Proxys, die diesen Header beachten (Traefik v3, Nginx mit dem Modul `ngx_http_proxy`), leiten sofort weiter, ohne dass du etwas einstellen musst. Für Proxys, die ihn nicht beachten, brauchst du die Einstellungen weiter unten.

**Warum macht Puffern SSE kaputt?**
SSE ist eine lange laufende HTTP-Antwort. Jedes Ereignis ist ein kleines Stück, das sofort verschickt wird, wenn es passiert. Ein puffernder Proxy hält diese Stücke fest, bis sein Puffer voll ist oder die TCP-Verbindung zugeht – dann bekommt der Client entweder alle Ereignisse auf einmal oder gar nichts. Nur wenn das Puffern aus ist, reicht der Proxy jedes Stück gleich an den Client weiter, und nur so funktioniert SSE in Echtzeit.

**Warum spielt das Zeitlimit für Leerlauf eine Rolle?**
Das Backend schließt SSE-Verbindungen nach 300 Sekunden ohne Verkehr (einstellbar über `LABELYARD_SSE_IDLE_TIMEOUT_S`). Hat der Reverse Proxy für Verbindungen im Leerlauf ein kürzeres Lese-Zeitlimit, schließt er die Verbindung zuerst, und die EventSource des Browsers verbindet sich neu. Setz jedes Lese-Zeitlimit am Proxy auf mindestens `LABELYARD_SSE_IDLE_TIMEOUT_S + 60` Sekunden, damit es keine unnötigen Neuverbindungen gibt.

---

## Traefik v3

Traefik v3 beachtet `X-Accel-Buffering: no`, wenn `passHostHeader` an ist (die Vorgabe). Der Header, den das Backend setzt, reicht – Traefik braucht keine weiteren Einstellungen. Willst du es ausdrücklich haben, oder läuft bei dir Traefik v2, fügst du eine eigene Middleware hinzu:

```yaml
# In Docker-Compose-Labels oder einer statischen Middleware-Datei von Traefik
traefik.http.middlewares.sse-flush.headers.customResponseHeaders.X-Accel-Buffering=no
traefik.http.routers.labelyard-sse.rule=PathPrefix(`/api/v1/events`)
traefik.http.routers.labelyard-sse.middlewares=sse-flush@docker
```

Die Middleware `customResponseHeaders` setzt den Header auf der Antwort neu, sodass auch ältere Versionen von Traefik v2 die Bytes ungepuffert durchreichen.

---

## Caddy

```text
@sse path /api/v1/events*
handle @sse {
    reverse_proxy backend:8000 {
        flush_interval -1
    }
}
```

Mit `flush_interval -1` leert Caddy den Puffer bei jedem Schreiben. Mit der Vorgabe `flush_interval 0` wählt Caddy den Abstand selbst und puffert kleine SSE-Ereignisse womöglich. `examples/compose.caddy.yml` setzt `flush_interval -1` für die ganze Seite, damit ist der Ereignispfad abgedeckt.

---

## Nginx / nginx-proxy

```nginx
location /api/v1/events {
    proxy_pass http://backend:8000;
    proxy_buffering off;
    proxy_cache off;
    add_header X-Accel-Buffering no;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding on;
}
```

Die wichtigen Direktiven:

| Direktive | Wozu sie nötig ist |
|---|---|
| `proxy_buffering off` | schaltet den Antwortpuffer von Nginx ab; die Bytes gehen sofort durch |
| `proxy_cache off` | verhindert, dass das Cache-Modul die lange laufende Antwort abfängt |
| `proxy_http_version 1.1` | SSE braucht dauerhafte Verbindungen von HTTP/1.1; die Vorgabe `1.0` schließt nach jeder Antwort |
| `proxy_set_header Connection ''` | entfernt den Header `Connection: close`, den der Modus HTTP/1.0 setzt, und hält die Verbindung offen |
| `chunked_transfer_encoding on` | erlaubt Antworten in Stücken ohne bekannte `Content-Length` |

---

## Pangolin

Pangolin-Tunnel sitzen vor Traefik. Der Header `X-Accel-Buffering: no`, den das Backend setzt, kommt durch die Tunnelkette bis zum Browser. Über die Traefik-Einstellungen oben hinaus brauchst du für Pangolin nichts einzustellen.

Das Muster ist mit Gotify (ebenfalls SSE-basiert) hinter demselben Aufbau aus Pangolin und Traefik v3 erprobt. Der Header geht unverändert über den Weg Pangolin-Client Newt → Traefik → Browser.

SSE funktioniert ohne zusätzliche Pangolin-Einstellungen, solange die Antwort `X-Accel-Buffering: no` trägt. Setz das Zeitlimit für Leerlauf in Pangolin höher als `LABELYARD_SSE_IDLE_TIMEOUT_S`.

---

## Prüfen

Prüf nach dem Einrichten, ob SSE durchgehend funktioniert:

```bash
# Ersetze <host> durch die Adresse des Hubs; jeder API-Schlüssel mit read-Bereich geht
# (der Schlüssel kommt aus der Umgebung und wird nie auf der Kommandozeile getippt).
curl -N -H "Accept: text/event-stream" -K - <<EOF2
header = "X-Label-Hub-Key: $HUB_API_KEY"
url = "https://<host>/api/v1/events"
EOF2
# Du solltest ": connected" sehen, einen Schnappschuss je Drucker, danach alle 30 Sekunden
# Kommentarzeilen ": keepalive".
```

Kehrt die Verbindung sofort ohne Ausgabe zurück oder kommt die Ausgabe erst nach langer Verzögerung, puffert der Proxy. Prüf den Header `X-Accel-Buffering` in der Antwort:

```bash
curl -s -D - -o /dev/null -m 3 -K - <<EOF2 | grep -i buffering
header = "X-Label-Hub-Key: $HUB_API_KEY"
url = "https://<host>/api/v1/events"
EOF2
# Erwartet: X-Accel-Buffering: no
```

Fehlt der Header, prüf, ob der Container des Backends erreichbar ist und ob der Proxy die Header der Antwort weiterreicht.

---

## Der Strom der Weboberfläche: `GET /api/v1/events`

Die Weboberfläche öffnet **eine** `EventSource` auf `/api/v1/events` (optional `?printer_id=<uuid>`). Sie meldet sich an wie jede `read`-Route, das Sitzungs-Cookie eines angemeldeten Browsers reicht also. Die Proxy-Einstellungen oben gelten unverändert.

| Frame | Bedeutung |
|-------|---------|
| `: connected` | die Abonnements stehen |
| `id: 0` + Schnappschuss-Ereignisse | aktueller Zustand je sichtbarem Drucker (`printer.status`, `printer.tape_changed`, aktive `job.state_changed`) |
| `id: N` / `event: <type>` / `data: <json>` | Live-Ereignis; `N` zählt je Kanal |
| `: keepalive` | alle `LABELYARD_SSE_HEARTBEAT_S` Sekunden |
| `event: auth.expired` | Sitzung oder Schlüssel gilt nicht mehr (oder seine Druckerbeschränkung hat sich geändert); der Strom schließt sich |

`data` ist immer `{"channel": str, "printer_id": str | null, "type": str, "ts": ISO-8601, "data": {...}}`.

Der Strom abonniert den Kanal `hub`, den Kanal `sheets` und `printer:{id}:{queue,state,tape}` jedes eingeschalteten Druckers, den die Zugangsdaten sehen dürfen. Drucker außerhalb von `allowed_printer_ids` werden nie abonniert. Ohne Filter `printer_id` kommen Drucker, die später angelegt oder eingeschaltet werden, laufend dazu.

`sheet.updated` (Kanal `sheets`) wird nach jeder gespeicherten Änderung an den Zellen eines Bogens veröffentlicht: eine Reservierung, eine Freigabe, das Ergebnis eines Seitenauftrags (`used`, `unconfirmed` oder freigegeben), der Durchlauf beim Start, der regelmäßige Durchlauf der Reservierungen (Zellen von Aufträgen, deren Ergebnis verloren ging), das Klären unbestätigter Zellen und eine Bearbeitung von Hand. Sein `data` ist `{"code": str, "free": int, "total": int, "changed": [int], "state": str}`; `changed` nennt die betroffenen Zellennummern, `state` den Zustand des Bogens. Bögen haben keine Druckerbeschränkung (OC-11), deshalb bekommt jeder Strom diesen Kanal, unabhängig von `allowed_printer_ids` und einem Filter `printer_id`. Ein Client reagiert darauf, indem er den Bogen neu liest.

`run.state_changed` (Kanal `printer:{id}:queue`) wird veröffentlicht, wenn ein Banddurchlauf (#277) in die Liste der angehaltenen Durchläufe kommt oder sie verlässt – das sagt einem Client kein Auftragsereignis: Er beginnt auf eine Bestätigung zu warten, hält an, wird bestätigt, neu gedruckt oder verworfen. Sein `data` ist `{"run_id": str, "printer_id": str, "state": str}`; `state` ist der Zustand des Durchlaufs (`awaiting_confirmation`, `stopped`, `printing`) oder `discarded` / `finished`, sobald er weg ist. Es wird verschickt, nachdem der Zustand gesetzt ist, sodass ein Client, der den Durchlauf daraufhin liest, ihn auch sieht. Es trägt keinen Inhalt eines Etiketts. Ein Client reagiert darauf, indem er die angehaltenen Durchläufe neu liest.

`hub.printers_changed` (Kanal `hub`) veröffentlicht die Admin-API für Drucker mit `{"printer_id": str, "change": "created" | "updated" | "disabled" | "enabled"}`.

Bei jedem Herzschlag prüft der Strom seine Zugangsdaten in einer kurzen Datenbanksitzung neu (eine dauerhafte hält er nicht). Die Obergrenze `LABELYARD_SSE_MAX_SUBSCRIBERS` gilt für die Zahl offener Ereignisströme; einer mehr bekommt `429`. Wiederholung über `Last-Event-ID` gibt es nicht: Nach einer Neuverbindung bekommt der Client einen frischen Schnappschuss.
