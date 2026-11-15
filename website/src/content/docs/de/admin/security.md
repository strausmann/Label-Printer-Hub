---
title: Sicherheitsmodell
description: Was Labelyard schützt, was nicht, das Zugriffsprotokoll für CrowdSec, wie du die Image-Signatur prüfst und wie du eine Sicherheitslücke meldest.
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

## Zugriffsprotokoll

Der Hub schreibt je HTTP-Anfrage eine Zeile in seine Container-Ausgabe (stdout), im Format, das nginx `combined` nennt:

```text
198.51.100.7 - - [15/Nov/2026:17:40:00 +0000] "POST /api/v1/webhook/grocy/label?token=lh_pat_AbCdEfGhI*** HTTP/1.1" 401 52 "-" "Grocy/4.0"
198.51.100.7 - lh_pat_AbCdEfGhI [15/Nov/2026:17:40:01 +0000] "POST /api/v1/print HTTP/1.1" 403 85 "-" "curl/8.5.0"
```

Log-Werkzeuge, die nginx-Logs lesen, lesen es unverändert, CrowdSec auch. Das Zugriffsprotokoll ist vom Anwendungsprotokoll getrennt: ohne Level, ohne Logger-Namen, und es erscheint nie auf der System-Seite.

- **Client-Adresse.** Das erste Feld ist die Adresse, mit der die Ratenbegrenzungen des Hubs rechnen. Hinter einem Reverse Proxy ist das nur dann der echte Client, wenn der Proxy über `FORWARDED_ALLOW_IPS` vertrauenswürdig ist (siehe [Reverse Proxy](/de/install/reverse-proxy/)); sonst zeigt jede Zeile den Proxy.
- **Schlüssel-Präfix, nie ein Schlüssel.** Von einem Schlüssel im URL-Parameter `token` (Grocys Webhook) erscheint nur sein öffentliches Präfix, die ersten 16 Zeichen, gefolgt von `***`. Ein Schlüssel im Header `X-Label-Hub-Key` erscheint mit demselben Präfix im Benutzerfeld. Das Präfix ist dasselbe wie in der Schlüsselliste unter **Einstellungen > Zugang und Schlüssel**, so ordnest du einen abgewiesenen Aufruf einem Schlüssel zu. Das Präfix stammt aus dem gesendeten Wert: Auch ein unbekannter oder geratener Schlüssel zeigt sein Präfix. Ein Wert, der kein Schlüsselformat hat, erscheint als `***` (in der URL) oder `-` (im Benutzerfeld). Jeder andere Parameter, dessen Name nach Schlüssel, Token, Geheimnis oder Passwort aussieht, erscheint als `***`. Außer Referer und User-Agent wird kein Header geschrieben.
- **Ehrliche Statuscodes.** Abweisungen behalten den Status, den der Hub geantwortet hat: `401` bei fehlendem oder falschem Schlüssel, `403` bei einem Schlüssel ohne passenden Bereich, `429` über einer Ratenbegrenzung.
- **Keine gefälschten Zeilen.** Anführungszeichen, Backslashes und Steuerzeichen in Anfrage, Referer und User-Agent werden wie bei nginx als `\xHH` geschrieben, damit ein Client keine zweite Zeile beginnen kann.
- **Erfolgreiche Zustandsprüfungen fehlen**, damit Prüfaufrufe das Protokoll nicht fluten: `/healthz` und `/readiness` bekommen keine Zeile, wenn sie mit `2xx` oder `503` antworten. `/readiness` braucht einen `read`-Schlüssel, ein dort abgewiesener Schlüssel (`401`, `403`, `429`) erscheint deshalb immer.
- **Ein Abbruch ist `499`.** Eine Anfrage, die der Client aufgibt, bevor der Hub antwortet, erscheint mit nginx’ `499`. Anfragen, die der Webserver abweist, bevor der Hub sie sieht, etwa mit kaputter Anfragezeile, bekommen keine Zeile.

Zwei Einstellungen steuern es (siehe [Konfiguration](/de/reference/configuration/)):

| Variable | Standard | Wirkung |
|---|---|---|
| `LABELYARD_ACCESS_LOG` | `true` | `false` schaltet das Zugriffsprotokoll ganz ab |
| `LABELYARD_ACCESS_LOG_PROBES` | `false` | `true` protokolliert auch erfolgreiche Aufrufe von `/healthz` und `/readiness` |

### Mit CrowdSec lesen

CrowdSec liest die Container-Ausgabe des Hubs mit seinem mitgelieferten nginx-Parser. Mit der label-basierten Docker-Erfassung versiehst du nur den Labelyard-Dienst mit Labels.

1. Installiere auf dem CrowdSec-Agenten die [nginx-Sammlung](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/nginx.yaml). Sie bringt den Parser `crowdsecurity/nginx-logs` und die HTTP-Szenarien mit:

   ```bash
   cscli collections install crowdsecurity/nginx
   ```

2. Lass CrowdSec die Container über Labels auswählen, in seiner `acquis.yaml` (oder einer Datei unter `acquis.d/`). Der Agent braucht dafür den Docker-Socket:

   ```yaml
   source: docker
   use_container_labels: true
   ```

3. Versieh den Labelyard-Dienst in deiner Compose-Datei mit Labels:

   ```yaml
   services:
     labelyard:
       image: ghcr.io/strausmann/labelyard:latest
       environment:
         FORWARDED_ALLOW_IPS: ${PROXY_IP}
       labels:
         - "crowdsec.enable=true"
         - "crowdsec.labels.type=nginx"
   ```

4. Sperr nie deine eigenen Netze. Aufrufer im Docker-Netz (Grocy, das den Webhook direkt aufruft) oder über dein VPN dürfen wegen eines vertippten Schlüssels nicht gesperrt werden. Leg dem Agenten eine Ausnahmeliste an, zum Beispiel `/etc/crowdsec/parsers/s02-enrich/labelyard-whitelist.yaml`, mit deinen eigenen Bereichen statt der Beispiele:

   ```yaml
   name: local/labelyard-whitelist
   description: "Never ban internal callers of Labelyard"
   whitelist:
     reason: "internal Docker and VPN networks"
     cidr:
       - "192.0.2.0/24"     # dein Docker-Netz
       - "198.51.100.0/24"  # dein VPN-Bereich
   ```

   Lade CrowdSec danach neu. `cscli explain --log '<eine Zeile>' --type nginx` zeigt, wie eine Zeile gelesen wird und welche Szenarien sie erreicht.

### Szenarien, die reagieren

Was die mitgelieferten Szenarien der Sammlung zählen (geprüft mit `crowdsecurity/nginx` 0.2 und `crowdsecurity/base-http-scenarios` 1.2 unter CrowdSec 1.7.3):

| Szenario | Zählt | Löst aus |
|---|---|---|
| [`LePresidente/http-generic-401-bf`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-generic-bf.yaml) | `POST` mit Antwort `401` (falscher oder fehlender Schlüssel am Webhook, bei der Anmeldung oder an der API) | mehr als 5 je Adresse in etwa 10 Sekunden |
| [`LePresidente/http-generic-403-bf`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-generic-bf.yaml) | `POST` mit Antwort `403` (Schlüssel ohne passenden Bereich) | mehr als 5 je Adresse in etwa 10 Sekunden |
| [`crowdsecurity/http-probing`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-probing.yaml) | `400`, `403` oder `404` für Seiten, die keine statischen Dateien sind | mehr als 10 je Adresse in etwa 10 Sekunden |
| [`crowdsecurity/http-sensitive-files`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-sensitive-files.yaml) | Anfragen nach Dateien wie `.env` oder Sicherungen, jeder Status | mehr als 4 innerhalb weniger Sekunden |
| [`crowdsecurity/http-crawl-non_statics`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-crawl-non_statics.yaml) | viele `GET`/`HEAD`-Anfragen nach Seiten, die keine statischen Dateien sind | eine Folge von mehr als 40 |
| [`crowdsecurity/http-bad-user-agent`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-bad-user-agent.yaml) | User-Agents bekannter Scanner | die zweite solche Anfrage innerhalb einer Minute |

Die beiden Brute-Force-Szenarien stehen in der [Datei `http-generic-bf`](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/http-generic-bf.yaml) der [Sammlung `base-http-scenarios`](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/base-http-scenarios.yaml); sie zählen nur `POST`. Ein abgewiesenes `GET` zählt bei `http-probing`, wenn die Antwort `403` ist, und gar nicht, wenn sie `401` ist. Kein mitgeliefertes Szenario zählt `429`: Auf zu viele Aufrufe antworten weiter die Ratenbegrenzungen des Hubs. `crowdsecurity/nginx-req-limit-exceeded` aus der Sammlung liest das Fehlerprotokoll von nginx, nicht dieses Zugriffsprotokoll, und greift hier nicht.

Die Szenarien können auch deine eigenen Nutzer treffen: Ein Browser mit abgelaufener Sitzung schickt womöglich mehrere `POST`-Anfragen hintereinander, die mit `401` antworten, und ein reger Tab der Weboberfläche schickt viele `GET`-Anfragen. Nimm die Bereiche, aus denen deine Nutzer kommen, in die Ausnahmeliste oben auf, und behalte in den ersten Tagen nach dem Einschalten `cscli decisions list` im Blick.

## Eine Lücke melden

Bitte eröffne kein öffentliches Issue. Melde sie vertraulich über die [Sicherheitsmeldungen von GitHub](https://github.com/strausmann/labelyard/security/advisories/new); die [Sicherheitsrichtlinie](https://github.com/strausmann/labelyard/blob/main/SECURITY.md) nennt die anderen Wege und die Antwortzeiten.
