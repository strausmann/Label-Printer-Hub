---
title: Bögen und Layouts
description: Mit einem Seitendrucker auf Etikettenbögen drucken, belegte Felder im Blick behalten und Bandetiketten setzen.
---

Ein Seitendrucker bedruckt Etikettenbögen: A4- oder Letter-Seiten mit einem Raster aus Etiketten. Labelyard merkt sich jeden echten Bogen, damit ein halb genutzter Bogen zurück ins Fach kann und später weiter befüllt wird.

## Bogentypen

Ein **Bogentyp** beschreibt ein Produkt: Seitengröße, Zahl der Zeilen und Spalten und die Maße eines Felds. Unter **Bögen** legst du einen an oder importierst einen. Bogentypen haben Versionen: Wenn du ein Maß korrigierst, fügst du eine Version hinzu, und Bögen, die schon in Gebrauch sind, behalten die Version, mit der sie gedruckt wurden.

Bogentypen mit dem Vermerk **geprüft** wurden auf echten Bögen vermessen. Labelyard 1.7.0 bringt Avery Zweckform 6121, 3490 und L4737REV mit (bei 3490 kommt der Bogencode auf die Rückseite des Trägerpapiers, siehe [Wo der Bogencode hinkommt](#wo-der-bogencode-hinkommt)) und korrigiert L4731REV (Bögen, die du schon hast, behalten die alte Messung). Einen Typ, den du unter demselben Schlüssel selbst angelegt oder importiert hast, übernimmt Labelyard mit deinem Präfix und behält die älteren Versionen; die Glocke sagt es dir einmal. Ein übernommener Typ gilt ab dann als mitgeliefert: Du kannst ihn archivieren, aber nicht löschen.

Einen Bogentyp kannst du in eine Datei exportieren und in diesem oder einem anderen Hub importieren, damit ein Produkt nur einmal vermessen werden muss.

Jeder Bogentyp hat einen eigenen Schalter **QR-Codes auf Etiketten**, in den Details des Typs im **Bogenarchiv**. Ein neuer Typ beginnt mit eingeschaltetem Schalter, wenn die kürzere Seite eines Etiketts mindestens 10 mm misst: Auf Etiketten mit 25,4 × 10 mm lässt sich ein QR-Code mit einer kurzen Nummer daneben drucken und scannen. Ist der Schalter aus, werden die Etiketten dieses Typs ohne QR-Code gedruckt, auch das ID-Etikett des Bogens, und die Druckvorschau kennzeichnet diese Felder mit „Nur der Code auf diesem Bogentyp“. Bereits angelegte Typen behalten ihre Einstellung.

## Bögen und ihr ID-Etikett

Jeder echte Bogen bekommt einen eigenen Code. Wenn du einen Bogen hinzufügst, kannst du gleich ein ID-Etikett dafür drucken, damit du ihn später scannen kannst. Ein Bogen weiß, welche seiner Felder frei und welche belegt sind.

- **Freie Felder** nehmen die nächsten Etiketten auf.
- **Unbestätigte Felder** gehören zu einem Auftrag mit unklarem Ergebnis, zum Beispiel wenn der Drucker mitten auf der Seite ausgefallen ist. Schau dir den Bogen an und bestätige einzeln, welche davon gedruckt wurden. Sind es zwei oder mehr, erledigen **Alle als gedruckt bestätigen** und **Alle als nicht gedruckt bestätigen** das in einem Zug; der Hub fragt vorher nach und nennt, um wie viele Zellen es geht. Hat sich die Zahl inzwischen geändert, wird nichts geschrieben, und du prüfst die Liste noch einmal.
- **Verwerfen** nimmt einen Bogen aus der Auswahl. Sein Code wird nie wieder vergeben; schon gedruckte Etiketten bleiben gedruckt.

## Wo der Bogencode hinkommt

Der Bogencode erkennt einen Bogen, wenn du ihn scannst, zum Beispiel `A3490-0001`. Jeder Bogentyp legt fest, wo der Hub ihn druckt; ändern kannst du das im **Bogenarchiv**, Reiter **Wo der Code hinkommt**:

- **Rand**: Der Code kommt in den freien Rand um die Etiketten, mit dem ersten Druck auf den Bogen. Kein zusätzlicher Durchgang.
- **Rückseite**: Der Code kommt auf die Rückseite des Trägerpapiers, in einem eigenen Durchgang.
- **Reservierte Zelle**: Eine Zelle des Bogens trägt den Code und nimmt kein Etikett auf. Du wählst die Zelle; die Planung lässt sie aus, und ist sie schon belegt, nimmt der Code die erste freie Zelle.

Ein neuer Bogentyp wählt automatisch: den Rand, wenn auf dem Drucker ein Rand von 4 mm passt, sonst die Rückseite. Der Reiter zeigt diese Möglichkeit als **Standard für diesen Bogen**. Avery Zweckform 3490 hat keinen nutzbaren Rand, deshalb kommt sein Code auf die Rückseite.

**Einen Bogen mit dem Code auf der Rückseite aktivieren.** Wenn du so einen Bogen hinzufügst, führt dich der Hub in drei Schritten: Bogen an der langen Kante umdrehen und mit der oberen Kante zuerst einlegen, Bogencode drucken, dann prüfen. Der Code gilt erst als gedruckt, wenn du **Ja, ist gedruckt** antwortest: Ein fertiger Auftrag sagt nichts über verschmierten Toner. Ist er verschmiert, druckt **Noch einmal drucken** auf denselben Bogen. Schließt du den Dialog, bevor du bestätigst, bietet die Seite des Bogens später **Rückseite drucken** an. Bis dahin markiert die Bogenliste den Bogen mit **Rückseite fehlt**, und der gleichnamige Filter zeigt nur diese Bögen. Beim ersten Mal fragt der Hub, wie das Fach das Papier nimmt (siehe [Wie ein Fach das Papier nimmt](/de/using/printers/#wie-ein-fach-das-papier-nimmt)).

**Trägerdesigns.** Viele Trägerpapiere tragen auf der Rückseite einen Herstelleraufdruck. Ein Trägerdesign nennt dessen freie Streifen, und der Code kommt in den ersten Streifen, der ihn aufnimmt. Labelyard bringt das Design von Avery Zweckform ultragrip mit und verknüpft es mit 3490 und 6121. Ein Design oder unbedrucktes Trägerpapier wählst du im selben Reiter, **Automatisch wählen** stellt einen Typ wieder auf die automatische Wahl; ein Design anlegen oder ändern geht über die API (`/api/v1/backing-designs`).

Ein Bogen, den du im Druckdialog anfängst oder den ein Grocy-Etikett öffnet, folgt seinem Typ genauso. Ein Bogen mit dem Code im Rand, dessen Code nie gedruckt wurde, etwa ein 3490-Bogen von vor 1.7.0, kann auf die Rückseite wechseln, wenn sein Typ den Code dorthin legt: Öffne ihn und wähle **Rückseite drucken**. Ein Bogen, dessen Code du von Hand aufgebracht hast, behält ihn und bekommt den Code zusätzlich auf die Rückseite (siehe unten).

**Das Feld Bogencode.** Die Seite jedes Bogens hat neben dem Raster ein Feld **Bogencode**. Es nennt, wo der Code ist (in einer Zelle, im Rand, von Hand aufgebracht, auf der Rückseite des Trägerpapiers) und ob er gedruckt ist. Hat ein Bogen einen Code auf der Rückseite oder ist einer gewünscht, zeigt das Feld **Rückseite: fehlt**. Nach deiner Bestätigung steht dort **Rückseite: bestätigt**. Ein Bogen, der nie einen Code auf der Rückseite wollte, hat diese Zeile nicht und gilt nicht als **Rückseite fehlt**. Mit einem Schlüssel, der drucken darf, siehst du die Knöpfe:

- **Randcode erneut drucken** druckt den Code noch einmal in den Rand eines Bogens mit Randcode, etwa wenn der erste verschmiert oder abgeschnitten ist. Leg den Bogen so ein, wie er beim ersten Mal hineinging, und wähle Drucker und Fach. Gedruckt wird nur der Code: Keine Zelle wird belegt, kein Etikett gedruckt. Der Hub wählt den Rand für diesen Drucker und dieses Fach neu. Auf einem anderen Drucker kann der Code deshalb in einer anderen Ecke landen als der erste. Ist noch ein Randcode auf dem Weg zum Drucker, wird ein zweiter abgelehnt.
- **Rückseite drucken** geht auch bei einem Bogen, dessen Code schon in einer Zelle oder im Rand gedruckt ist. Das gilt auch für jeden Bogen, dessen Code du von Hand aufgebracht hast. Der Code bleibt, wo er ist, und kommt zusätzlich auf die Rückseite. Bis du mit **Ja, die Rückseite ist gedruckt** bestätigst, markiert die Liste den Bogen mit **Rückseite fehlt**.

## Auf einen Bogen drucken

Wähle **Auf einen Bogen drucken**, nimm den Bogen (oder scanne seinen Code) und die Felder. Die Vorschau zeigt, wohin jedes Etikett kommt. Passt nicht alles drauf, bleibt der Rest für den nächsten Bogen im [Warenkorb](/de/using/cart/), oder die Vorschau plant ihn auf dem nächsten.

Hat ein anderes Gerät Felder desselben Bogens belegt, während du geschaut hast, sagt dir der Hub das und bittet dich, den neuen Plan zu prüfen, bevor er druckt.

## Layouts

Ein Layout bestimmt, was ein Etikett zeigt: einen QR-Code, einen Code, einen Titel und eine Detailzeile, in Kombinationen von „Nur Code“ bis „QR-Code, Code, Titel und Detail“. Layouts, die ein Feld brauchen, das der Eintrag nicht hat, werden vor dem Druck abgelehnt, mit dem fehlenden Feld benannt. Auf einem Bogentyp mit ausgeschalteten QR-Codes druckt ein QR-Layout nur seinen Text (siehe [Bogentypen](#bogentypen)).
