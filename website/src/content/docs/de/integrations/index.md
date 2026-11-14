---
title: Integrationen
description: Wie Labelyard mit den Apps spricht, aus denen deine Etiketten kommen, über Plugins, Webhooks und seine API.
sidebar:
  label: Überblick
---

Eine App und Labelyard arbeiten auf drei Wegen zusammen:

| Weg | Wer ihn anstößt | Apps |
|---|---|---|
| **Plugin** | Du, in Labelyard: Du scannst oder tippst eine ID, das Plugin schlägt den Eintrag in seiner App nach, und der Hub druckt das Etikett | [Snipe-IT](/de/integrations/snipe-it/), [Grocy](/de/integrations/grocy/), [Spoolman](/de/integrations/spoolman/) |
| **Webhook** | Die App: Ein Ereignis darin schickt eine Anfrage, und der Hub druckt | [Spoolman und Grocy](/de/integrations/webhooks/) |
| **API** | Die App: Sie ruft die REST-API des Hubs mit einem eigenen Schlüssel auf | [Paperless](/de/integrations/paperless/), [Kept](/de/integrations/kept/), deine eigenen Skripte |

## Eine App verbinden

Öffne mit einem Admin-Schlüssel **Einstellungen > Integrationen**. Trag für jede App ihre Adresse ein und, wo nötig, ihren API-Schlüssel oder ihr Token, und prüf die Verbindung mit dem Test-Knopf. Die Änderung gilt ab der nächsten Anfrage; ein Neustart ist nicht nötig.

Dieselben Werte lassen sich als Umgebungsvariablen setzen, zum Beispiel `LABELYARD_SNIPEIT_URL` und `LABELYARD_SNIPEIT_API_KEY` (alle stehen in der [Konfigurationsreferenz](/de/reference/configuration/)). Eine Variable gewinnt und sperrt das Feld in der Oberfläche.

Ein Geheimnis gehört zu der Adresse, mit der es gespeichert wurde: Änderst du die Adresse einer App, gib ihr Geheimnis neu ein.

## Einträge aus Skripten nachschlagen

`GET /api/v1/lookup/{app}/{id}` liefert, was ein Plugin zu einer ID gefunden hat, ohne zu drucken; `POST /api/v1/print` mit einem Objekt `lookup` druckt in einem Schritt. Siehe die [API-Referenz](/de/developers/api/).

## Labelyard aus einem anderen Container aufrufen

Andere Container im selben Docker-Netz rufen den Hub direkt unter `http://<dienst>:8000` auf (zum Beispiel `http://labelyard:8000`) und melden sich mit einem API-Schlüssel im Header `X-Label-Hub-Key` an. Weder ein Reverse Proxy noch SSO sind beteiligt.

- **Schlüssel.** Leg je Client einen unter Einstellungen > Zugang und Schlüssel an, mit seinem Bereich und, wenn du willst, seinen Druckern (siehe [API-Schlüssel](/de/admin/api-keys/)). Aufrufe, die sich mit einem Schlüssel im Header anmelden, unterliegen nicht der CSRF-Prüfung; die schützt nur Browser-Sitzungen.
- **`LABELYARD_PUBLIC_URL` brauchst du trotzdem, aber jede `http(s)`-Adresse geht**, auch interne wie `http://labelyard:8000`, `http://localhost:8000` oder eine Adresse in deinem LAN. Sie bestimmt die Sicherheit der Cookies (`Secure` und das Präfix `__Host-`, wenn sie mit `https` beginnt) und das erlaubte `Origin` für ändernde Anfragen, die sich über Proxy-Header oder den Basic-Bypass anmelden. Nutzt du im Stack nur die API, reicht eine lokale Adresse.
- **Browser: Setz sie auf die Adresse, die die Leute öffnen.** Nutzen Menschen die Weboberfläche, setz die Variable auf die Adresse, die sie eintippen. Mit einem `https`-Wert sind die Sitzungs-Cookies `Secure` und tragen das Präfix `__Host-`, ein Browser schickt sie also nicht an einen internen Namen mit reinem `http`; ein Wert, der nicht passt, bricht außerdem die Anmelde-Cookies und die Prüfung von `Origin`.
- **Proxy-Header.** `Remote-User` und ähnliche Header zählen nur zusammen mit `LABELYARD_SSO_TRUST_TOKEN`, damit sich ein benachbarter Container nicht als SSO-Benutzer ausgeben kann. Lass das Vertrauens-Token leer, wenn du keinen SSO-Proxy nutzt (siehe [Benutzer und SSO](/de/admin/users-and-sso/)).
- **Ein veröffentlichter Port ist nicht nötig**, wenn du den Hub nur intern nutzt; lass `ports:` weg. `examples/compose.backend-only.yml` ist eine Variante nur mit API.

```yaml
services:
  hub:
    image: ghcr.io/strausmann/labelyard:${HUB_VERSION:-1.6.0}
    user: "1000:1000"
    environment:
      - "LABELYARD_SECRET_KEY=${LABELYARD_SECRET_KEY:?set LABELYARD_SECRET_KEY}"
      - "LABELYARD_PUBLIC_URL=${LABELYARD_PUBLIC_URL:?set LABELYARD_PUBLIC_URL}"
    volumes:
      - ./data:/data
    networks: [stack]

  client:
    image: example/client:latest
    environment:
      - LABELYARD_URL=http://hub:8000
      - LABELYARD_KEY=CHANGE_ME   # geht als Header X-Label-Hub-Key mit
    networks: [stack]

networks:
  stack:
```

Du hättest gern eine weitere App als Plugin? Plugins sind Python-Pakete; siehe [Mitmachen](/de/developers/contributing/).
