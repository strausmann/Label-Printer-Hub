---
title: Druckwarteschlange und Aufträge
description: Wie Aufträge durch die Warteschlange laufen, was Pausieren, Fortsetzen, Abbrechen und Wiederholen tun und was bei einem unklaren Ergebnis passiert.
sidebar:
  label: Druckwarteschlange
---

Jeder Druck, ob aus der Weboberfläche, einem Plugin, einem Webhook oder der API, wird zu einem **Auftrag** in der Warteschlange seines Druckers. Nichts geht an der Warteschlange vorbei zum Drucker, deshalb kommen sich zwei Aufrufer auf einem Drucker nie in die Quere.

## Die Seite Aufträge

**Aufträge** listet, was wartet, gedruckt wird und fertig ist, mit der Herkunft jedes Auftrags. Eine Auftragsseite zeigt den Fortschritt live.

| Aktion | Was sie tut |
|---|---|
| Pausieren / Fortsetzen | Hält die Warteschlange eines Druckers an oder gibt sie frei |
| Abbrechen | Entfernt einen wartenden Auftrag; ein laufender wird gebeten, an der nächsten sicheren Stelle aufzuhören |
| Wartende abbrechen | Bricht alle wartenden Aufträge eines Druckers auf einmal ab |
| Wiederholen | Reiht einen fehlgeschlagenen Auftrag erneut ein |

Abgeschlossene Aufträge (fertig, fehlgeschlagen, abgebrochen) werden nach `LABELYARD_JOB_RETENTION_DAYS` gelöscht, standardmäßig nach 30 Tagen.

## Lange Bandaufträge

Eine lange Folge von Bandetiketten wird in Teile aufgeteilt. Ist das Ergebnis eines Teils unklar, zum Beispiel weil der Drucker mittendrin offline ging, hält der Auftrag dort an, statt zu raten. Du siehst, welche Etiketten sicher gedruckt sind, und wählst:

- **Mit Teil N weitermachen**, wenn die Etiketten herausgekommen sind, oder
- **Ab Etikett N neu drucken**, wenn nicht.

Bei Seitendruckern gilt dasselbe für die Felder eines Bogens: Sie bleiben unbestätigt, bis du den Bogen geprüft hast (siehe [Bögen](/de/using/sheets/)).

## Aus Skripten

`POST /api/v1/print` gibt sofort eine Auftrags-ID zurück; den Zustand fragst du mit `GET /api/v1/jobs/{job_id}` ab. Probleme, die schon vor dem Druck bekannt sind (kein Band, Deckel offen, Drucker offline), werden gleich mit einem Fehlercode beantwortet statt mit einem eingereihten Auftrag. Die [API-Referenz](/de/developers/api/) listet sie.
