---
title: Benutzer und SSO
description: Wie sich Menschen bei Labelyard anmelden, mit einem API-Schlüssel oder über einen SSO-Reverse-Proxy.
sidebar:
  label: Benutzer und SSO
---

Labelyard hat keine Benutzerkonten und keine eigenen Passwörter. Wer sich anmeldet, tut das auf einem von zwei Wegen.

## Mit einem API-Schlüssel

Die Anmeldeseite nimmt einen API-Schlüssel mit dem Bereich `print` oder `admin`; mit einem `read`-Schlüssel geht es nicht. Der Browser hält danach ein Sitzungs-Cookie. Gib jedem Menschen einen eigenen Schlüssel, damit ein Widerruf nur seine Sitzungen beendet und keine anderen.

## Über einen SSO-Proxy

Läuft der Hub hinter einem Proxy mit Single Sign-on (Pangolin, oder Traefik bzw. Caddy mit einem Forward-Auth-Dienst wie Authelia), kann der Proxy dem Hub sagen, wer angemeldet ist:

- Der Proxy schickt den Benutzer im Header `Remote-User` (`LABELYARD_SSO_USER_HEADER`).
- Außerdem schickt er ein gemeinsames Geheimnis in `X-Pangolin-Token` (`LABELYARD_SSO_TRUST_HEADER`), dessen Wert `LABELYARD_SSO_TRUST_TOKEN` entspricht.

Der Benutzer-Header zählt **nur** zusammen mit dem passenden Vertrauens-Token. Ist das Token nicht gesetzt, ist die Anmeldung über den Proxy aus, und kein Nachbarcontainer kann sich mit dem Header als Benutzer ausgeben. Erzeug das Token mit `openssl rand -hex 32` und trag denselben Wert im Proxy ein (siehe das Pangolin-Beispiel unter [Reverse Proxy](/de/install/reverse-proxy/)).

## Alte Wege, standardmäßig aus

Für bestehende Einrichtungen gibt es zwei ältere Pangolin-Wege, die aus sind, solange du sie nicht freischaltest:

| Variable | Was sie erlaubt |
|---|---|
| `LABELYARD_TRUST_LEGACY_PANGOLIN_USER` | den Header `X-Pangolin-User` ohne Vertrauens-Token |
| `LABELYARD_TRUST_PANGOLIN_BASIC_BYPASS` | die Basic-Umgehung von Pangolin (`Authorization: Basic`) |

Keiner von beiden erzeugt eine Browsersitzung. Ändernde Anfragen über die Basic-Umgehung brauchen einen `Origin`, der `LABELYARD_PUBLIC_URL` entspricht, und `LABELYARD_PANGOLIN_BYPASS_SCOPE_DOWNGRADE=true` beschränkt sie auf `read`. Nimm lieber API-Schlüssel und lass beide aus.
