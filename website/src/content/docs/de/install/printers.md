---
title: Drucker anschließen
description: Welche Drucker Labelyard ansteuert, was das Netz erlauben muss und wie du einen Drucker in der Weboberfläche hinzufügst.
sidebar:
  label: Drucker und Hardware
---

Labelyard erreicht jeden Drucker über das Netz. Drucker, die nur USB können, werden nicht unterstützt. Drucker fügst du in der Weboberfläche unter **Einstellungen > Drucker** hinzu, im laufenden Betrieb und ohne Neustart; Druckervariablen gibt es nicht.

## Banddrucker

Drucker der Brother PT-Serie und QL-Serie im Netz, zum Beispiel der PT-P750W und der QL-820NWB. Der Hub druckt über TCP-Port 9100 und liest den Zustand des Druckers, auch das eingelegte Band oder die Etikettenrolle, über SNMP (UDP-Port 161).

Prüf vom Host aus, auf dem der Hub läuft, bevor du den Drucker hinzufügst:

```bash
# Drucken
nc -zv <druckeradresse> 9100
# Zustand; die Antwort nennt Hersteller und Modell
snmpwalk -v 2c -c public <druckeradresse> 1.3.6.1.4.1.2435.2.3.9.1.1.7.0
```

Antwortet SNMP nicht, öffne die Webseite des Druckers und schalte SNMPv1/v2c mit der Community `public` ein (bei vielen Modellen unter **Network > Protocols > SNMP**).

### Statuserkennung

Der Hub liest Zustand und Band eines Banddruckers nur dann über SNMP, wenn **Statuserkennung** für diesen Drucker eingeschaltet ist. Schalte sie im Druckerformular unter **Einstellungen > Drucker** ein und gib die **SNMP-Community** ein (`public`, solange du sie am Drucker nicht geändert hast). Der Hub speichert die Community und zeigt sie nie wieder an: Das Feld bleibt leer, und ein Hinweis sagt, dass eine gespeichert ist. Lass das Feld leer, um sie zu behalten, oder gib eine neue ein, um sie zu ersetzen. Änderst du Host oder Port, gib die Community erneut ein; der Hub schickt eine gespeicherte Community nicht an eine andere Adresse. Drucken funktioniert auch ohne Statuserkennung; die Übersicht zeigt den Drucker dann als nicht überwacht.

## Seitendrucker

Bürodrucker, die IPP sprechen, bedrucken Etikettenbögen. Füg sie als **Seitendrucker (IPP)** mit ihrer IPP-Adresse hinzu, zum Beispiel `ipp://printer.example.invalid:631/ipp/print`. Lies den Drucker vor dem Speichern einmal aus, damit der Hub seine Fächer kennt; dann schaltest du die Fächer ein, die du nutzt, und wählst ein Standardfach. Wie es weitergeht, steht unter [Bögen und Layouts](/de/using/sheets/).

## Nach dem Hinzufügen

- **Testdruck.** Jeder Drucker hat einen Testdruck, damit du sofort siehst, dass Adresse und Protokoll stimmen.
- **Seitendrucker kalibrieren.** Ein Seitendrucker druckt selten genau dorthin, wo die Seite es vorgibt. Druck die Kalibrierseite, miss, wie weit er daneben liegt, und der Hub verschiebt jeden Druck aus diesem Fach um das Gegenteil.
- **Den Zustand im Blick behalten.** Die Seite des Druckers zeigt seinen Zustand live: bereit, druckt, Deckel offen, Material leer.

Der Container muss das Netz der Drucker erreichen. Mit dem Standard-Bridge-Netz klappt das, solange der Host es erreicht; sonst prüf Routing und Firewalls zwischen Docker-Host und Druckern.
