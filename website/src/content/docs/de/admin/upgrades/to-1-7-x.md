---
title: Aktualisieren innerhalb von 1.7.x
description: Was sich mit den Patch-Versionen 1.7.x für API-Clients ändert.
sidebar:
  order: 4
---

Die Versionen 1.7.x sind Patch-Versionen. Deine Daten, Schlüssel und Einstellungen ziehen mit um; ändere den Tag wie unter [Tags und Aktualisieren](/de/admin/upgrades/) beschrieben. Prüfe die Punkte unten, wenn ein Skript oder eine Integration Druckerdaten über die API liest oder große oder lange Werte sendet.

## Die Adresse eines Banddruckers sehen nur Admin-Schlüssel

Die Adresse eines Banddruckers ist Verbindungsdetail, wie die Adresse eines Seitendruckers. Ab 1.7.x gilt:

- Lese- und Druckschlüssel erhalten für Banddrucker kein `connection.host`, `connection.port` und `connection.snmp` mehr; `connection` ist für sie ein leeres Objekt. Admin-Schlüssel erhalten alle drei weiterhin.
- `last_error` im Status eines Banddruckers nennt nur noch die Fehlerklasse, zum Beispiel `PySnmpError`, wie bei einem Seitendrucker. Das Server-Protokoll behält die volle Meldung.
- `error` eines fehlgeschlagenen Bandauftrags (`GET /api/v1/jobs`) enthält die Adresse des Druckers nicht mehr: Ein nicht erreichbarer Drucker meldet einen festen Text (`The printer could not be reached.`), ein unerwarteter Fehler nur seine Klasse. Das Server-Protokoll behält die volle Meldung.

Liest ein Skript mit einem Lese- oder Druckschlüssel den Host eines Banddruckers, nimm dafür einen Admin-Schlüssel.

## Grenzen für Anfragegröße und Feldlänge

Anfragekörper über 2 MiB werden für jede Route und vor der Anmeldung (eine angegebene `Content-Length` vor dem Lesen des Körpers, ein Körper ohne Angabe sobald er 2 MiB überschreitet) mit `413` und dem Fehlercode `body_too_large` abgewiesen. Webhook-IDs und Ereignistypen über 64 Zeichen (`spool_id`, `product_id`, `type`) und Lookup-Kennungen über 120 Zeichen werden mit `422` abgewiesen, ebenso ein Lookup-`app` über 32 Zeichen. Im normalen Betrieb sendet nichts Werte dieser Größe. Passende Proxy-Grenzen: [Größe des Anfragekörpers](/de/install/reverse-proxy/#größe-des-anfragekörpers).

## Wartende Etiketten nach einem Neustart

Nach einem Neustart zeichnet der Hub nicht mehr jedes wartende Etikett, bevor er startet; der Start dauert damit bei einer langen Warteschlange nicht mehr länger. Ein wartendes Etikett wird gezeichnet, wenn es an der Reihe ist: Ein Etikett, das sich nicht mehr zeichnen lässt, schlägt erst dann fehl, mit demselben Fehler (`recovery_rerender_failed: …`), nicht schon beim Start. Auf einem Drucker, der beim Beenden des Hubs pausiert war, bleibt ein solches Etikett `queued`, bis du den Drucker fortsetzt.

## Kurze Etiketten auf QL-Druckern

Die QL-Bibliothek ist jetzt `brother-ql-next`. Ein QL-Etikett, das kürzer als etwa 12,7 mm (150 Punkte) ist, bekommt am Ende leeres Band, es druckt also etwas länger, als die Vorschau zeigt. Ein QL-Etikett über 1000 mm (500 mm bei 600 dpi) wird mit `422` und dem Fehlercode `tape_label_too_long` abgewiesen.
