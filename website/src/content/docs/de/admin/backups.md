---
title: Sicherung und Wiederherstellung
description: Was du sichern musst, wie du eine stimmige Kopie der Datenbank ziehst und wie du sie wiederherstellst.
sidebar:
  label: Sicherung und Wiederherstellung
---

Labelyard hält seinen gesamten Zustand an zwei Stellen, und eine Sicherung braucht beide:

1. **Das Daten-Volume** (`/data` im Container, in den Beispielen `./data` neben der Compose-Datei). Darin liegt die SQLite-Datenbank: Drucker, Bogentypen, Bögen und ihre Felder, API-Schlüssel, Einstellungen und Aufträge.
2. **`LABELYARD_SECRET_KEY`.** Geheimnisse in der Datenbank, etwa die API-Schlüssel der Integrationen, sind damit verschlüsselt. Eine Datenbank ohne ihren Schlüssel stellt alles wieder her außer diesen Geheimnissen; die Seite der Integrationen bittet dich dann, sie neu einzugeben.

Bewahr den Schlüssel woanders auf als die Sicherung des Volumes, zum Beispiel in deinem Passwortmanager.

## Eine Sicherung ziehen

Die einfachste stimmige Kopie entsteht bei angehaltenem Container:

```bash
docker compose stop labelyard
tar -czf labelyard-$(date +%F).tar.gz data
docker compose start labelyard
```

Ohne Anhalten nimmst du den Sicherungsbefehl von SQLite selbst auf die Datenbankdatei; er kopiert einen stimmigen Stand, während der Hub läuft (die Datei heißt `printer-hub.db`, solange du `LABELYARD_DATABASE_URL` nicht geändert hast):

```bash
sqlite3 data/printer-hub.db ".backup 'labelyard-backup.db'"
```

## Wiederherstellen

1. Halte den Container an.
2. Leg das gesicherte Verzeichnis `data` (oder die Datenbankdatei) zurück, im Besitz des Benutzers, unter dem der Container läuft (`1000:1000` in den Beispielen).
3. Sorg dafür, dass der Container denselben `LABELYARD_SECRET_KEY` wie vorher bekommt.
4. Starte den Container. Datenbankmigrationen laufen beim Start, eine Sicherung aus einer älteren Version wird also automatisch auf den aktuellen Stand gebracht. Mit einer neueren Datenbank zurück auf eine ältere Version zu gehen, wird nicht unterstützt.

## Einstellungen exportieren

Admins können die Laufzeit-Einstellungen außerdem auf der Einstellungsseite als Datei exportieren. Dieser Export erleichtert das Umziehen von Einstellungen, ersetzt aber keine Sicherung des Volumes.
