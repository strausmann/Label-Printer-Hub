---
title: Erste Schritte
description: Von null zum gedruckten Etikett – Hub starten, anmelden, Drucker anlegen, drucken, die Web-App aufs Handy holen und Webhooks anbinden.
---

Diese Seite bringt dich von null zum gedruckten Etikett: Hub starten, anmelden, Drucker anlegen, drucken, die Web-App auf dem Handy installieren und Spoolman oder Grocy anbinden.

## 1. Den Hub starten

Der Hub ist ein einziger Container. Such dir in [`examples/`](https://github.com/strausmann/labelyard/tree/main/examples) die Compose-Datei aus, die zu deinem Aufbau passt (ohne Proxy, Traefik, Pangolin, Caddy; [Docker Compose](/de/install/) und [Reverse Proxy](/de/install/reverse-proxy/) erklären die Varianten), und kopiere sie zusammen mit `.env.example`.

```bash
git clone https://github.com/strausmann/labelyard.git
cd labelyard/examples
cp .env.example .env
```

Setz in `.env` mindestens diese zwei Werte:

| Variable | Wert |
|---|---|
| `LABELYARD_SECRET_KEY` | verschlüsselt die Geheimnisse in der Datenbank; erzeugen mit `openssl rand -base64 32 \| tr '+/' '-_'` |
| `LABELYARD_PUBLIC_URL` | die Adresse, unter der du den Hub öffnest, zum Beispiel `http://localhost:8000` oder `https://labelyard.example.com` |

Heb den geheimen Schlüssel gut auf: Ohne ihn lassen sich die gespeicherten Geheimnisse nicht mehr entschlüsseln.

```bash
docker compose -f compose.standalone.yml up -d
curl http://localhost:8000/healthz
curl http://localhost:8000/api/v1/info
```

Beide Aufrufe antworten mit `200`. Willst du den Hub ohne Drucker und ohne Reverse Proxy ausprobieren, baut ihn `docker compose -f ../dev/docker-compose.smoke.yml up --build` (aus `examples/` heraus) aus dem lokalen Stand.

### Anmelden

Eine frische Installation hat keinen API-Schlüssel. Leg den ersten Admin-Schlüssel im Container an:

```bash
docker exec labelyard labelyard admin create-key --scope admin --name first-admin
```

Öffne den Hub im Browser und melde dich mit diesem Schlüssel an. (Alternative: Setz `LABELYARD_BOOTSTRAP_ADMIN_KEY` auf einen einmaligen Schlüssel mit mindestens 32 Zeichen und nimm ihn für die erste Anmeldung.) Weitere Schlüssel mit den Bereichen `read`, `print` oder `admin`, wahlweise auf bestimmte Drucker beschränkt, legst du unter **Einstellungen > Zugang und Schlüssel** an.

## 2. Den ersten Drucker anlegen

Drucker stehen nicht in `.env`. Öffne **Einstellungen > Drucker** und leg einen an:

| Feld | Bedeutung |
|---|---|
| Name | was die Leute sehen |
| Slug | ein kurzer Name in Kleinbuchstaben für Adressen und die API (3 bis 64 Buchstaben, Ziffern und Bindestriche); er lässt sich später nicht ändern |
| Treiber | *P-touch (PT)* für einen Banddrucker der PT-Serie, *Brother QL* für einen Drucker der QL-Serie, *Seitendrucker (IPP)* für einen Drucker, der Bögen mit Etiketten bedruckt (er braucht die Adresse des Druckers, die vor dem Speichern einmal gelesen wird) |
| Modell | nur bei Banddruckern, Pflicht; das Formular bietet die Modelle des gewählten Treibers an |
| Host und Port | nur bei Banddruckern: die Adresse des Druckers und TCP-Port `9100`, zum Beispiel `192.0.2.20` |
| IPP-Adresse | nur bei Seitendruckern: die IPP-Adresse des Druckers, zum Beispiel `ipp://printer.example.invalid:631/ipp/print`; **Drucker auslesen** fragt ihn vor dem Speichern einmal ab |
| Zertifikat des Druckers prüfen | nur bei Seitendruckern mit einer Adresse `ipps://` oder `https://`; lass es an, außer der Drucker hat kein gültiges Zertifikat |
| Fächer | nur bei Seitendruckern, nach **Drucker auslesen**: Schalte die Fächer aus, die du nicht nutzt, und wähl das Standardfach |
| Warteschlangen-Zeitlimit (Sekunden) | wie lange die Warteschlange auf den Drucker wartet, 1 bis 600 |

Ein Seitendrucker erscheint in der Übersicht mit seinem Zustand und seinem Verbrauchsmaterial, gelesen über IPP. Ein hier angelegter Banddrucker zeigt anfangs **Nicht überwacht** und **Band unbekannt**: Der Hub liest seinen Status erst, wenn die Statuserkennung an ist, siehe [Statuserkennung einschalten](#statuserkennung-einschalten). Ist sie an und der Drucker erscheint trotzdem als offline, prüf, ob der Container des Hubs die Adresse des Druckers auf dem Port erreicht.

### Statuserkennung einschalten

Der Hub liest Status und Band eines Banddruckers über SNMP, aber nur, wenn für diesen Drucker die Statuserkennung an ist. Ein unter **Einstellungen > Drucker** angelegter Drucker hat sie aus, und das Formular hat dafür noch keinen Schalter ([#296](https://github.com/strausmann/labelyard/issues/296)). Das Drucken hängt nicht davon ab: Ein Druck oder Testdruck prüft den Drucker beim Absenden einmal. Unbekannt bleiben nur der Zustand und das Band in der Übersicht. Ein Admin schaltet die Erkennung über die Admin-API ein, mit dem Slug des Druckers und seinem aktuellen Host und Port (das Objekt `connection` wird als Ganzes ersetzt):

```bash
curl -X PUT http://localhost:8000/api/v1/admin/printers/<slug> \
  -H "X-Label-Hub-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"connection": {"host": "192.0.2.20", "port": 9100,
                      "snmp": {"discover": true, "community": "public"}}}'
```

`snmp.discover` schaltet das Lesen des Status ein; `snmp.community` ist die SNMP-Lese-Community des Druckers (`public`, solange du sie am Drucker nicht geändert hast, höchstens 64 Zeichen, Pflicht bei `discover: true`). Der Hub verdrahtet den Drucker neu, bevor er antwortet; die Übersicht zeigt den Zustand nach der ersten Abfrage, innerhalb von etwa 30 Sekunden. Den vollständigen Anfragekörper findest du in der interaktiven Referenz unter `/docs` eines laufenden Hubs (`PUT /api/v1/admin/printers/{slug}`).

Ein Banddrucker kann die Farbe des Bands nicht über das Netz melden. Wechselt die Rolle, fragt dich der Hub einmal, welche Farbe eingelegt ist.

## 3. Das erste Etikett drucken

Öffne in der Weboberfläche den Druckdialog eines Eintrags (such einen Eintrag aus Snipe-IT, Grocy oder Spoolman oder scanne einen Code), wähl Drucker, Gestaltung und Anzahl, prüf die Vorschau und drück **Drucken**. Der Auftrag erscheint unter **Aufträge** und ändert seinen Zustand, während die Warteschlange ihn abarbeitet.

Dasselbe aus einem Skript, mit einem API-Schlüssel mit Bereich `print`:

```bash
curl -X POST http://localhost:8000/api/v1/print \
  -H "X-Label-Hub-Key: $LABELYARD_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "content_type": "qr_two_lines",
        "data": {"title": "Asset 123", "primary_id": "ASSET-123",
                 "qr_payload": "https://assets.example.com/hardware/123"},
        "options": {"copies": 1}
      }'
```

Die Antwort ist `202` mit einer `job_id`; `GET /api/v1/jobs/<job_id>` zeigt den Zustand. Statt `data` kannst du `"lookup": {"app": "snipeit", "identifier": "123"}` schicken, dann holt sich der Hub den Inhalt des Etiketts aus der App. Den vollständigen Anfragekörper und die Fehlercodes findest du in der [API-Referenz](/de/developers/api/); die interaktive Referenz liegt unter `/docs` eines laufenden Hubs.

Um Snipe-IT, Grocy oder Spoolman für das Nachschlagen anzubinden, öffne **Einstellungen > Integrationen** und trag Adresse und Schlüssel der App ein. Änderungen gelten ab der nächsten Anfrage, ohne Neustart.

## 4. Die Web-App auf dem Handy installieren

Der Hub ist eine Progressive Web App: Du kannst ihn auf den Startbildschirm legen, er öffnet sich wie eine App, und die Kamera scannt Barcodes.

Installieren und auf die Kamera zugreifen erlauben Browser nur auf einer sicheren Adresse: Liefer den Hub über `https://` aus (die Beispiele mit Reverse Proxy tun das) oder öffne ihn auf `localhost`.

- **Android (Chrome):** Hub öffnen, Menü > *App installieren* (oder *Zum Startbildschirm hinzufügen*).
- **iPhone und iPad (Safari):** Hub öffnen, Teilen > *Zum Home-Bildschirm*.
- **Desktop (Chrome, Edge):** das Installationssymbol in der Adressleiste.

Das Symbol auf dem Startbildschirm hat eine Kurzwahl **Scannen**. Setz `LABELYARD_PUBLIC_URL` auf die Adresse, die die Leute öffnen; mit einem `https`-Wert sind die Sitzungs-Cookies `Secure`, und ein Browser schickt sie nicht an einen reinen `http`-Namen desselben Hubs.

## 5. Webhooks: drucken, wenn etwas passiert

Der Hub nimmt Ereignisse von Spoolman und Grocy an und druckt das Etikett des Eintrags, den das Ereignis nennt.

| Methode und Pfad | Felder im Inhalt |
|---|---|
| `POST /api/v1/webhook/spoolman` | `spool_id` (Text), `type` (Text), optional `quantity` |
| `POST /api/v1/webhook/grocy` | `product_id` (Text), `type` (Text), optional `quantity` |

Unbekannte zusätzliche Felder werden ignoriert; ein fehlendes oder falsch getyptes Pflichtfeld beantwortet der Hub mit `422`.

1. Erzeug einen Schlüssel mit mindestens 32 Zeichen, zum Beispiel `openssl rand -hex 32`, und setz ihn in der `.env` des Hubs als `LABELYARD_WEBHOOK_API_KEY`. Starte den Hub neu.
2. Schick ihn bei jedem Aufruf im Header `X-API-Key` mit. Ohne eingerichteten Schlüssel antworten die Webhooks mit `503`, mit einem falschen mit `401`.
3. Mehr als `LABELYARD_WEBHOOK_LIMIT_PER_MINUTE` Aufrufe pro Minute (Standard 120, beide Routen zusammen) beantwortet der Hub mit `429` und `Retry-After`.

```bash
curl -X POST http://localhost:8000/api/v1/webhook/spoolman \
  -H "X-API-Key: $LABELYARD_WEBHOOK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"spool_id": "42", "type": "updated"}'
```

Was bei einem gültigen Aufruf passiert:

- Der Hub druckt **ein** Etikett `qr_two_lines` auf dem **ersten eingeschalteten Banddrucker** (ein Seitendrucker wird für Webhooks nie genommen). `quantity` wird angenommen, ändert aber die Zahl der Etiketten nicht.
- Der Inhalt des Etiketts kommt aus der Integration (Spoolman oder Grocy), sie muss also eingerichtet sein; sonst antwortet der Aufruf mit `503` und `integration_not_configured`. Eine unbekannte Spule oder ein unbekanntes Produkt beantwortet er mit `404` und `app-lookup-not-found`.
- Probleme am Drucker (kein Band, Drucker offline oder ausgeschaltet) beantwortet er wie `POST /api/v1/print`: `409`, `422`, `502` oder `503`. In diesen Fällen landet nichts in der Warteschlange.
- Bei Erfolg kommt `202` mit der Nummer des Auftrags zurück. Der Webhook-Schlüssel kann den Auftrag nicht lesen; ein Admin oder eine per Single Sign-on angemeldete Person sieht ihn unter **Aufträge**.

Hinter Pangolin bekommt der Webhook-Pfad `/api/v1/webhook/` eine eigene Ressource ohne Single Sign-on, weil sich der Absender nicht anmelden kann; der Schlüssel schützt ihn ([`examples/compose.pangolin.yml`](https://github.com/strausmann/labelyard/blob/main/examples/compose.pangolin.yml) und [Reverse Proxy](/de/install/reverse-proxy/#pangolin)).

## Wie es weitergeht

- [Architektur](/de/developers/architecture/) und die [Entscheidungen](https://github.com/strausmann/labelyard/tree/main/docs/decisions) dahinter
- [Plugins schreiben](/de/developers/plugin-authoring/): ein Druckermodell oder ein Nachschlage-Plugin ergänzen
- [Reverse Proxy](/de/install/reverse-proxy/) für die Varianten mit Proxy, [Integrationen](/de/integrations/#labelyard-aus-einem-anderen-container-aufrufen) für den Hub aus anderen Containern heraus
- [Fehlerbehebung](/de/admin/troubleshooting/) für die üblichen Probleme beim ersten Start
