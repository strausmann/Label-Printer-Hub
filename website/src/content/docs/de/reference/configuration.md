---
title: Konfiguration
description: Jede LABELYARD_-Umgebungsvariable, ihr Standardwert und was sie bewirkt.
---

<!-- Diese Seite wird von `website/scripts/gen-config-reference.py` aus den Backend-Einstellungen erzeugt; ändere die Beschreibungen in `website/src/config-descriptions.yml`, nicht hier. -->

Jede Einstellung ist eine Umgebungsvariable mit dem Präfix `LABELYARD_`. Die Namen früherer Versionen werden mindestens bis 2.0.0 weiter gelesen, und eine `LABELYARD_`-Variable gewinnt immer; ein leerer Wert gilt bei beiden Präfixen als nicht gesetzt. Details findest du unter [Aktualisieren](/de/admin/upgrades/).

Drucker haben keine Variablen: Du legst sie in der Weboberfläche unter Einstellungen > Drucker an.

## Pflichtangaben

### `LABELYARD_SECRET_KEY`

**Pflicht**

Hauptschlüssel für die in der Datenbank gespeicherten Geheimnisse: base64url-Text aus genau 32 Bytes. Erzeuge ihn mit `openssl rand -base64 32 | tr '+/' '-_'` und bewahre ihn auf, ohne ihn lassen sich gespeicherte Geheimnisse nicht mehr lesen.

Geheim: wird nie protokolliert oder angezeigt.

### `LABELYARD_PUBLIC_URL`

**Pflicht**

Jede `http(s)`-Adresse, auch eine lokale. Trag die Adresse ein, unter der die Weboberfläche geöffnet wird. Bei `https` sind die Sitzungs-Cookies `Secure` und tragen das Präfix `__Host-`; außerdem ist sie der erlaubte `Origin` für ändernde Anfragen.

In der Weboberfläche nur sichtbar; der Wert kommt immer aus der Umgebung.

## Optional

### `LABELYARD_DATABASE_URL`

Standard: `sqlite+aiosqlite:////data/printer-hub.db`

Datenbankverbindung. Der Standard legt die SQLite-Datei im Volume `/data` ab; bestehende Installationen finden ihre Daten weiter unter diesem Namen.

### `LABELYARD_BOOTSTRAP_ADMIN_KEY`

Standard: leer

Einmalschlüssel (mindestens 32 Zeichen), mit dem du dich anmeldest, solange es noch keinen Admin-Schlüssel gibt, um den ersten anzulegen. Leer schaltet ihn ab; sobald ein aktiver Admin-Schlüssel existiert, wird er abgelehnt.

Geheim: wird nie protokolliert oder angezeigt.

### `LABELYARD_WEB_DIST_DIR`

Standard: `/opt/app/web`

Verzeichnis der gebauten Weboberfläche, die das Backend ausliefert. Das Image setzt es; ändere es nur für einen eigenen Build.

### `LABELYARD_PAPERLESS_URL`

Standard: leer

Basisadresse von Paperless-ngx für den Verbindungstest unter Einstellungen > Integrationen.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_PAPERLESS_TOKEN`

Standard: leer

API-Token von Paperless-ngx.

Geheim: wird nie protokolliert oder angezeigt.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_PAPERLESS_TIMEOUT`

Standard: `5.0`

Sekunden, die auf Paperless-ngx gewartet wird.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_WEBHOOK_API_KEY`

Standard: leer

Gemeinsamer Schlüssel für die eingehenden Webhooks von Spoolman und Grocy, gesendet im Header `X-API-Key`. Mindestens 32 Zeichen (`openssl rand -hex 32`). Leer beantwortet jeden Webhook-Aufruf mit 503.

Geheim: wird nie protokolliert oder angezeigt.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_SNIPEIT_URL`

Standard: leer

Basisadresse von Snipe-IT.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_SNIPEIT_API_KEY`

Standard: leer

API-Token von Snipe-IT (Bearer).

Geheim: wird nie protokolliert oder angezeigt.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_SNIPEIT_TIMEOUT`

Standard: `5.0`

Sekunden, die auf Snipe-IT gewartet wird.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_GROCY_URL`

Standard: leer

Basisadresse von Grocy.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_GROCY_API_KEY`

Standard: leer

API-Schlüssel von Grocy.

Geheim: wird nie protokolliert oder angezeigt.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_GROCY_TIMEOUT`

Standard: `5.0`

Sekunden, die auf Grocy gewartet wird.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_SPOOLMAN_URL`

Standard: leer

Basisadresse von Spoolman. Spoolman braucht keinen Schlüssel.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_SPOOLMAN_TIMEOUT`

Standard: `5.0`

Sekunden, die auf Spoolman gewartet wird.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.

### `LABELYARD_SERVER_PORT`

Standard: `8090`

Derzeit ohne Wirkung: Die Anwendung liest sie nicht. Im Container kommt der Port aus der Variablen `PORT` (Standard `8000`), die der Startbefehl als `--port` an uvicorn übergibt.

### `LABELYARD_LOG_LEVEL`

Standard: `INFO`

Einer der Werte `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Jeder andere Wert bricht den Start mit einem Fehler ab.

### `LABELYARD_SIGN_IN_LIMIT_PER_MINUTE`

Standard: `10`

Anmeldeversuche im Browser pro Minute und Client-Adresse. Hinter einem Proxy teilen sich alle Clients dessen Adresse, solange der Proxy nicht als vertrauenswürdig eingetragen ist (`FORWARDED_ALLOW_IPS`).

### `LABELYARD_SSE_QUEUE_SIZE`

Standard: `32`

Gepufferte Ereignisse je Abonnent der Live-Aktualisierung; ist der Puffer voll, fällt das älteste weg.

### `LABELYARD_SSE_IDLE_TIMEOUT_S`

Standard: `300.0`

Sekunden ohne Aktivität, nach denen der Server eine Live-Verbindung schließt.

### `LABELYARD_SSE_MAX_SUBSCRIBERS`

Standard: `100`

Gleichzeitige Live-Verbindungen je Drucker; weitere werden mit 429 beantwortet.

### `LABELYARD_SSE_HEARTBEAT_S`

Standard: `30.0`

Sekunden zwischen Keep-alive-Rahmen, wenn keine Ereignisse fließen.

### `LABELYARD_SSE_PROBE_INTERVAL_S`

Standard: `30.0`

Sekunden zwischen zwei Statusabfragen (SNMP) je Drucker.

### `LABELYARD_TRUST_LEGACY_PANGOLIN_USER`

Standard: `False`

Schaltet den alten Header `X-Pangolin-User` ohne Vertrauens-Token frei. Standardmäßig aus; er erzeugt nie eine Browsersitzung.

### `LABELYARD_TRUST_PANGOLIN_BASIC_BYPASS`

Standard: `False`

Schaltet die Basic-Umgehung von Pangolin (`Authorization: Basic`) frei. Standardmäßig aus; ändernde Anfragen damit brauchen einen `Origin`, der der öffentlichen Adresse entspricht.

### `LABELYARD_PANGOLIN_BYPASS_SCOPE_DOWNGRADE`

Standard: `False`

Beschränkt die Basic-Umgehung, falls sie überhaupt aktiv ist, auf den Bereich `read`.

### `LABELYARD_SSO_USER_HEADER`

Standard: `Remote-User`

Header, in dem der SSO-Proxy den angemeldeten Benutzer mitschickt.

### `LABELYARD_SSO_TRUST_HEADER`

Standard: `X-Pangolin-Token`

Header, in dem der SSO-Proxy das Vertrauens-Token mitschickt.

### `LABELYARD_SSO_TRUST_TOKEN`

Standard: leer

Gemeinsames Geheimnis, das der Proxy im Vertrauens-Header schickt. Nur damit zählt der Benutzer-Header, sodass sich kein Nachbarcontainer als Benutzer ausgeben kann. Leer schaltet die Anmeldung über den Proxy ab.

### `LABELYARD_JOB_RETENTION_DAYS`

Standard: `30`

Tage, nach denen abgeschlossene Aufträge (fertig, fehlgeschlagen, abgebrochen) gelöscht werden.

Auch in der Weboberfläche einstellbar; ein hier gesetzter Wert gewinnt und sperrt das Feld dort.
