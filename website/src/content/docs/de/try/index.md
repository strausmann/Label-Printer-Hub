---
title: Was Labelyard ist
description: Ein selbst gehosteter Hub zwischen deinen Etikettendruckern und den Apps und Menschen, die Etiketten brauchen.
---

Labelyard ist ein selbst gehosteter Hub zwischen deinen Etikettendruckern und allem, was ein Etikett braucht: Menschen mit dem Handy in der Hand und Apps wie Snipe-IT, Grocy oder Spoolman. Es läuft als ein Container auf deiner eigenen Hardware. Es spricht mit keinem Cloud-Dienst und hält seine Daten in einer SQLite-Datei in seinem Daten-Volume.

## Was du damit machen kannst

- **Aus dem Browser oder vom Handy drucken.** Die Weboberfläche ist eine Progressive Web App. Installier sie auf dem Handy, scanne einen Barcode oder ein gedrucktes Etikett und drucke.
- **Aus anderen Apps drucken.** Integrations-Plugins schlagen ein Asset, ein Produkt oder eine Spule über die ID nach und setzen das Etikett. Webhooks drucken, wenn sich in Spoolman oder Grocy etwas ändert. Jede andere App druckt über die REST-API mit einem eigenen Schlüssel.
- **Banddrucker und Bürodrucker nutzen.** Drucker der Brother PT-Serie und QL-Serie drucken auf Band und Etiketten; IPP-Seitendrucker bedrucken Etikettenbögen, und der Hub merkt sich die belegten Felder jedes Bogens.
- **Wissen, was mit einem Auftrag passiert ist.** Jeder Druck läuft durch eine Warteschlange je Drucker. Du kannst anhalten, fortsetzen, abbrechen und wiederholen, und ein langer Bandauftrag wird so aufgeteilt, dass ein unklares Ergebnis ihn anhält und dich fragt, ob du weitermachen oder neu drucken willst.

## Was es nicht ist

Labelyard ist keine Inventarverwaltung. Es speichert deine Assets, Produkte oder Spulen nicht, sondern fragt die App, der sie gehören, und druckt, was zurückkommt. Es ist auch kein Treiber: Drucker werden über das Netz mit ihren dokumentierten Protokollen angesprochen.

## Ausprobieren

Eine gehostete Demo gibt es noch nicht. Am schnellsten schaust du es dir mit der [Installation](/de/install/) auf deinem eigenen Rechner an; der Hub startet auch ohne Drucker, und du fügst später einen hinzu.

Brother, P-touch, PT-Series und QL-Series sind Marken der Brother Industries, Ltd. Labelyard ist ein unabhängiges Projekt und nicht mit Brother verbunden.
