---
title: Sicherheitsmodell
description: Was Labelyard schützt, was nicht, und wie du eine Sicherheitslücke meldest.
---

## Was der Hub schützt

- **Jeder API-Aufruf und jede Seite verlangt eine Anmeldung**, mit einem API-Schlüssel oder über einen vertrauenswürdigen SSO-Proxy (siehe [Benutzer und SSO](/de/admin/users-and-sso/)). Bereiche (`read`, `print`, `admin`) und Druckerlisten je Schlüssel begrenzen, was ein Schlüssel darf.
- **Schlüssel werden als bcrypt-Hash gespeichert.** Im Klartext siehst du sie nur einmal, beim Anlegen.
- **Gespeicherte Geheimnisse sind verschlüsselt**, mit `LABELYARD_SECRET_KEY` (32 Bytes), zum Beispiel die API-Schlüssel der Integrationen.
- **Geheimnisse bleiben aus Protokollen, Fehlermeldungen und Seiten heraus.** Die Weboberfläche zeigt ein gespeichertes Geheimnis als gespeichert an, nie seinen Wert.
- **Browsersitzungen sind gegen CSRF geschützt.** Mit einer `https`-Adresse sind die Sitzungs-Cookies `Secure` und tragen das Präfix `__Host-`; ändernde Anfragen müssen vom eingestellten Origin kommen.
- **Proxy-Header zählen nur mit dem Vertrauens-Token,** und weitergereichte Client-Adressen nur vom einen Proxy in `FORWARDED_ALLOW_IPS`.
- **Anmeldeversuche sind begrenzt**, je Client-Adresse, und jeder API-Schlüssel hat sein eigenes Ratenlimit.
- **Webhooks brauchen einen eigenen Schlüssel** (`X-API-Key`, mindestens 32 Zeichen).
- **Der Container läuft nicht als root**, sondern als Benutzer mit der UID 1000.

## Wogegen er nicht schützt

- Angreifer im selben Netz wie die Drucker. Etikettendrucker nehmen Druckdaten über TCP-Port 9100 an und antworten auf SNMP mit der Community `public`, so sind sie gebaut; stell sie in ein Netzsegment, dem du vertraust.
- Einen kompromittierten Reverse Proxy oder Container-Host.
- Bösartige Drucker-Firmware.

## Eine Lücke melden

Bitte eröffne kein öffentliches Issue. Melde sie vertraulich über die [Sicherheitsmeldungen von GitHub](https://github.com/strausmann/labelyard/security/advisories/new); die [Sicherheitsrichtlinie](https://github.com/strausmann/labelyard/blob/main/SECURITY.md) nennt die anderen Wege und die Antwortzeiten.
