---
title: Bögen und Layouts
description: Mit einem Seitendrucker auf Etikettenbögen drucken, belegte Felder im Blick behalten und Bandetiketten setzen.
---

Ein Seitendrucker bedruckt Etikettenbögen: A4- oder Letter-Seiten mit einem Raster aus Etiketten. Labelyard merkt sich jeden echten Bogen, damit ein halb genutzter Bogen zurück ins Fach kann und später weiter befüllt wird.

## Bogentypen

Ein **Bogentyp** beschreibt ein Produkt: Seitengröße, Zahl der Zeilen und Spalten und die Maße eines Felds. Unter **Bögen** legst du einen an oder importierst einen. Bogentypen haben Versionen: Wenn du ein Maß korrigierst, fügst du eine Version hinzu, und Bögen, die schon in Gebrauch sind, behalten die Version, mit der sie gedruckt wurden.

Einen Bogentyp kannst du in eine Datei exportieren und in diesem oder einem anderen Hub importieren, damit ein Produkt nur einmal vermessen werden muss.

Jeder Bogentyp hat einen eigenen Schalter **QR-Codes auf Etiketten**, in den Details des Typs im **Bogenarchiv**. Ein neuer Typ beginnt mit eingeschaltetem Schalter, wenn die kürzere Seite eines Etiketts mindestens 10 mm misst: Auf Etiketten mit 25,4 × 10 mm lässt sich ein QR-Code mit einer kurzen Nummer daneben drucken und scannen. Ist der Schalter aus, werden die Etiketten dieses Typs ohne QR-Code gedruckt, auch das ID-Etikett des Bogens, und die Druckvorschau kennzeichnet diese Felder mit „Nur der Code auf diesem Bogentyp“. Bereits angelegte Typen behalten ihre Einstellung.

## Bögen und ihr ID-Etikett

Jeder echte Bogen bekommt einen eigenen Code. Wenn du einen Bogen hinzufügst, kannst du gleich ein ID-Etikett dafür drucken, damit du ihn später scannen kannst. Ein Bogen weiß, welche seiner Felder frei und welche belegt sind.

- **Freie Felder** nehmen die nächsten Etiketten auf.
- **Unbestätigte Felder** gehören zu einem Auftrag mit unklarem Ergebnis, zum Beispiel wenn der Drucker mitten auf der Seite ausgefallen ist. Schau dir den Bogen an und bestätige, welche davon gedruckt wurden.
- **Verwerfen** nimmt einen Bogen aus der Auswahl. Sein Code wird nie wieder vergeben; schon gedruckte Etiketten bleiben gedruckt.

## Auf einen Bogen drucken

Wähle **Auf einen Bogen drucken**, nimm den Bogen (oder scanne seinen Code) und die Felder. Die Vorschau zeigt, wohin jedes Etikett kommt. Passt nicht alles drauf, bleibt der Rest für den nächsten Bogen im [Warenkorb](/de/using/cart/), oder die Vorschau plant ihn auf dem nächsten.

Hat ein anderes Gerät Felder desselben Bogens belegt, während du geschaut hast, sagt dir der Hub das und bittet dich, den neuen Plan zu prüfen, bevor er druckt.

## Layouts

Ein Layout bestimmt, was ein Etikett zeigt: einen QR-Code, einen Code, einen Titel und eine Detailzeile, in Kombinationen von „Nur Code“ bis „QR-Code, Code, Titel und Detail“. Layouts, die ein Feld brauchen, das der Eintrag nicht hat, werden vor dem Druck abgelehnt, mit dem fehlenden Feld benannt. Auf einem Bogentyp mit ausgeschalteten QR-Codes druckt ein QR-Layout nur seinen Text (siehe [Bogentypen](#bogentypen)).
