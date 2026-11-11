---
title: Scannen
description: Barcodes, gedruckte Etiketten und Bogencodes mit der Handykamera scannen oder stattdessen ein Foto wählen.
---

Die Weboberfläche scannt mit der Kamera deines Handys oder Laptops. Installier sie zuerst auf dem Startbildschirm des Handys: Öffne die Adresse des Hubs im Browser und bestätige „Zum Startbildschirm hinzufügen“. Danach öffnet sie sich wie eine App.

## Was du scannen kannst

- **Einen Barcode oder eine ID eines Eintrags**, zum Beispiel eine Inventarnummer aus Snipe-IT oder einen Produkt-Barcode aus Grocy. Der Hub schlägt ihn in der App nach, der er gehört, und zeigt sein Etikett, fertig zum Drucken oder für den Warenkorb.
- **Ein Etikett, das der Hub gedruckt hat.** Sein QR-Code ist ein Etikettenlink (`/asset/…`, `/loc/…`, `/spool/…`, `/product/…`), der den Eintrag wieder öffnet.
- **Einen Bogencode**, um genau diesen Bogen zu wählen, wenn du auf einen Bogen druckst.

Statt zu scannen kannst du eine ID auch eintippen: eine Inventarnummer (`AT-0042`), eine numerische ID (`42`) oder einen gedruckten Etikettenlink. Standorte brauchen das Präfix `loc:`, zum Beispiel `loc:17`.

## Wenn die Kamera nicht startet

| Meldung | Ursache | Lösung |
|---|---|---|
| Die Kamera braucht eine sichere Verbindung | Die Seite ist weder `https` noch `localhost` | Öffne den Hub unter seiner [HTTPS](/de/install/https/)-Adresse |
| Die Kamera ist gesperrt | Der Browser hat die Berechtigung verweigert | Erlaube die Kamera für die Seite in den Browser-Einstellungen |
| Keine Kamera | Das Gerät hat keine | Wähle stattdessen ein Foto des Codes |
| Möglicherweise nutzt eine andere App die Kamera | Sie ist belegt | Schließ die andere App und versuch es erneut |

Ein Foto zu wählen funktioniert überall: Der Hub liest den Code aus dem Bild. Findet er keinen, halt die Kamera näher heran und mach das Foto noch einmal.
