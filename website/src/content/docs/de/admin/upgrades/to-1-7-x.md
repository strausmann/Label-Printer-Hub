---
title: Aktualisieren innerhalb von 1.7.x
description: Was sich mit den Patch-Versionen 1.7.x für API-Clients ändert.
sidebar:
  order: 4
---

Die Versionen 1.7.x sind Patch-Versionen. Deine Daten, Schlüssel und Einstellungen ziehen mit um; ändere den Tag wie unter [Tags und Aktualisieren](/de/admin/upgrades/) beschrieben. Prüfe die Punkte unten, wenn ein Skript oder eine Integration Druckerdaten über die API liest.

## Die Adresse eines Banddruckers sehen nur Admin-Schlüssel

Die Adresse eines Banddruckers ist Verbindungsdetail, wie die Adresse eines Seitendruckers. Ab 1.7.x gilt:

- Lese- und Druckschlüssel erhalten für Banddrucker kein `connection.host`, `connection.port` und `connection.snmp` mehr; `connection` ist für sie ein leeres Objekt. Admin-Schlüssel erhalten alle drei weiterhin.
- `last_error` im Status eines Banddruckers nennt nur noch die Fehlerklasse, zum Beispiel `PySnmpError`, wie bei einem Seitendrucker. Das Server-Protokoll behält die volle Meldung.
- `error` eines fehlgeschlagenen Bandauftrags (`GET /api/v1/jobs`) enthält die Adresse des Druckers nicht mehr: Ein nicht erreichbarer Drucker meldet einen festen Text (`The printer could not be reached.`), ein unerwarteter Fehler nur seine Klasse. Das Server-Protokoll behält die volle Meldung.

Liest ein Skript mit einem Lese- oder Druckschlüssel den Host eines Banddruckers, nimm dafür einen Admin-Schlüssel.
