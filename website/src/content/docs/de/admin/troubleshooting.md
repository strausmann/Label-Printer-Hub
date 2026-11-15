---
title: Fehlerbehebung
description: Die häufigen Probleme nach der Installation, mit Ursache und Lösung.
---

## Der Hub startet nicht

- **`LABELYARD_SECRET_KEY must decode to exactly 32 bytes`.** Erzeug den Schlüssel neu mit `openssl rand -base64 32 | tr '+/' '-_'`.
- **Ein Prüffehler zum Log-Level.** `LABELYARD_LOG_LEVEL` nimmt `DEBUG`, `INFO`, `WARNING`, `ERROR` oder `CRITICAL`, in Großbuchstaben.
- **Ein unbekannter Schlüssel in `.env`.** Ein Eintrag in `.env` mit dem Präfix des Hubs, der zu keiner Einstellung passt, bricht den Start ab. Entfern oder benenn ihn um; die [Konfigurationsreferenz](/de/reference/configuration/) listet alle gültigen Namen.

## Ich kann mich nicht anmelden

- **„Melde dich mit einem API-Schlüssel mit Druck- oder Admin-Berechtigung an.“** Mit einem `read`-Schlüssel geht die Anmeldung nicht.
- **Der Bootstrap-Schlüssel funktioniert nicht mehr.** Er wird abgelehnt, sobald ein Admin-Schlüssel existiert; melde dich mit diesem an oder leg im Container einen an (siehe [API-Schlüssel](/de/admin/api-keys/)).
- **Die Anmeldung klappt, aber die Sitzung ist sofort weg.** Die Adresse im Browser weicht von `LABELYARD_PUBLIC_URL` ab, oder sie ist `http`, während die öffentliche Adresse `https` ist. Öffne genau die eingestellte Adresse.

## Drucker

- **Keine Drucker in der Übersicht.** Füg sie unter Einstellungen > Drucker hinzu; Drucker werden nicht über Variablen eingerichtet.
- **Der Drucker steht auf offline.** Prüf vom Docker-Host aus: `nc -zv <druckeradresse> 9100` und SNMP wie unter [Drucker anschließen](/de/install/printers/) beschrieben.
- **Ein Auftrag bleibt auf „druckt“ stehen.** Der Drucker hat das Ende des Auftrags nie gemeldet. Schau am Drucker nach: Vielleicht ist ein Deckel offen oder das Band leer.
- **Drucke auf einem Seitendrucker liegen ein paar Millimeter daneben.** Kalibrier das Fach (siehe [Drucker anschließen](/de/install/printers/)).

## Live-Aktualisierung und Webhooks

- **Der Zustand ändert sich erst nach dem Neuladen.** Der Proxy puffert den Ereignisstrom; siehe die Flush-Einstellungen unter [Reverse Proxy](/de/install/reverse-proxy/).
- **Webhooks antworten mit 401.** Der Header `X-API-Key` passt nicht zu `LABELYARD_WEBHOOK_API_KEY`.
- **Webhooks antworten mit 503.** `LABELYARD_WEBHOOK_API_KEY` ist nicht gesetzt.

## Immer noch nicht weiter

Such in den [bestehenden Issues](https://github.com/strausmann/labelyard/issues) oder eröffne eine [Diskussion](https://github.com/strausmann/labelyard/discussions). Gib die Version von der Seite „Über“ und die Logzeilen rund um das Problem an; entfern Adressen und Schlüssel, bevor du etwas veröffentlichst.
