---
title: Kept
description: Etiketten für die Dinge, Orte und Kisten der Kept-Hausinventur über die API von Labelyard drucken.
---

[Kept](https://keptinventory.info) ist eine selbst gehostete Inventur für dein Zuhause. Es druckt seine Etiketten über die API von Labelyard, deshalb braucht Labelyard dafür kein Plugin.

## Einrichtung

1. Leg in Labelyard für Kept einen API-Schlüssel mit dem Bereich `print` an. Beschränk ihn auf die Drucker, die Kept nutzen soll (siehe [API-Schlüssel](/de/admin/api-keys/)).
2. Trag in Kept die Adresse des Hubs und diesen Schlüssel ein. Wo, zeigt die Dokumentation von Kept.

Laufen beide im selben Docker-Stack, erreicht Kept den Hub unter `http://labelyard:8000`, ohne über den Reverse Proxy zu gehen; der Schlüssel ist alles, was es braucht.

## Was du prüfen solltest

- Der Schlüssel braucht den Bereich `print`; mit `read` werden die Druckaufrufe abgelehnt.
- Ein Auftrag aus Kept erscheint auf der Seite **Aufträge** wie jeder andere, mit seiner Herkunft, sodass du ihn dort verfolgen kannst.
