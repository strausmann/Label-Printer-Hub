---
title: Drucker
description: Die Druckerseiten, was ihre Zustände bedeuten und wie du einen angehaltenen Drucker wieder in Gang bringst.
---

Die Seite **Drucker** listet jeden Drucker, den du hinzugefügt hast, mit seinem Live-Zustand. Öffne einen, um seine Warteschlange, das eingelegte Material und seine Einstellungen zu sehen.

## Band und Etikettenrollen

Bei Druckern der PT-Serie und QL-Serie liest der Hub das eingelegte Band oder die Etikettenrolle beim Drucker selbst aus. Ein Etikett wird für das gesetzt, was eingelegt ist; die Bandbreite stellst du nirgends ein. Meldet der Drucker, dass das Material knapp oder leer ist, sagt es die Übersicht, bevor der nächste Auftrag scheitert.

## Zustände

| Zustand | Bedeutung | Was du tust |
|---|---|---|
| Bereit | Der Drucker antwortet und kann drucken | Nichts |
| Druckt | Ein Auftrag ist unterwegs | Warten; die Auftragsseite zeigt den Fortschritt |
| Deckel offen, kein Band, offline | Der Drucker hat ein Problem gemeldet | Am Drucker beheben, dann die Warteschlange des Druckers fortsetzen |
| Pausiert | Jemand hat die Warteschlange angehalten | Auf der Druckerseite fortsetzen |

Meldet der Drucker mitten in der Warteschlange ein behebbares Problem, hält die Warteschlange an, statt Aufträge wegzuwerfen. Wenn du es behoben hast, setzt du den Drucker fort: in der Weboberfläche auf der Druckerseite oder mit `POST /api/v1/printer/resume`.

## Abgeschaltete Drucker

Ein abgeschalteter Drucker nimmt keine Aufträge an: Ein Druck darauf wird mit `printer_disabled` abgelehnt.
