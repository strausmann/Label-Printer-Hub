---
title: Sicherheitsmodell
description: Was Labelyard schützt, was nicht, wie du die Image-Signatur prüfst und wie du eine Sicherheitslücke meldest.
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

## Die Image-Signatur prüfen

Ab 1.6.0 ist jedes Release-, Vorschau- und `dev`-Image mit [cosign](https://docs.sigstore.dev/) ohne Schlüssel signiert: Die Signatur entsteht mit dem GitHub-Actions-Token des Image-Workflows des Projekts und gilt für den Multi-Arch-Index, also auch für die Plattform-Images und ihre SBOM- und Provenance-Attestierungen. Ein Tag kann wandern, deshalb löst du ihn zuerst in seinen Digest auf und prüfst den Digest:

```bash
docker buildx imagetools inspect ghcr.io/strausmann/labelyard:<version> --format '{{ .Manifest.Digest }}'

cosign verify \
  --certificate-identity-regexp '^https://github\.com/strausmann/(Label-Printer-Hub|labelyard)/\.github/workflows/docker-publish\.yml@refs/(heads/main|heads/milestone/[0-9]+\.[0-9]+\.(0|x))$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/strausmann/labelyard@<digest>
```

Die Identität lässt nur den Image-Workflow dieses Repositorys zu (unter seinem jetzigen und seinem früheren Namen), gestartet von `main` oder einem Milestone-Zweig. `[b]` im Muster steht für den Buchstaben b. Auf Docker Hub ist der Digest derselbe; ersetze die letzte Zeile durch `docker.io/bstrausmann/labelyard@<digest>`, um die Kopie dort zu prüfen. `cosign verify` endet mit einem Fehler, wenn keine gültige Signatur passt. Die [Hinweise zur Lieferkette](https://github.com/strausmann/labelyard/blob/main/docs/supply-chain.md) beschreiben die genaue Release-Identität, die SBOM und die Provenance (auf Englisch).

## Eine Lücke melden

Bitte eröffne kein öffentliches Issue. Melde sie vertraulich über die [Sicherheitsmeldungen von GitHub](https://github.com/strausmann/labelyard/security/advisories/new); die [Sicherheitsrichtlinie](https://github.com/strausmann/labelyard/blob/main/SECURITY.md) nennt die anderen Wege und die Antwortzeiten.
