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

Ein Bandauftrag ist erst **fertig**, wenn der Drucker ihn bestätigt hat: Entweder meldet der Drucker den Auftragsstatus über IPP, oder sein Etikettenzähler ist um die gesendeten Etiketten gestiegen. Der Testdruck auf der Druckerseite findet heraus, was dein Drucker kann, und zeigt es unter **Druckbestätigung**. Jeder Testdruck probiert IPP erneut, ein Drucker, der bei einem Testdruck geschlafen hat, wird also beim nächsten wieder gefunden. Nur wenn der Drucker ein Testetikett über IPP angenommen und nicht fertig gedruckt hat, ohne dass ein Fehler wie ein Stau, eine offene Abdeckung oder das Bandende es erklärt, bleibt der nächste Testdruck beim Etikettenzähler; **Druckbestätigung** sagt dann, dass IPP nicht versucht wird. Der Hub wartet auf die Bestätigung 15 Sekunden, dazu 8 Sekunden je Etikett und eine Sekunde je 20 mm Band, ein langes Etikett bekommt also die Zeit, die es braucht; meldet der Drucker dann noch, dass er druckt, wartet er bis zum Doppelten. Ein Etikett, das länger ist, als das Band erlaubt (1000 mm auf TZe-Band, 500 mm auf Schrumpfschlauch), wird schon beim Drucken abgelehnt, bevor es in die Warteschlange kommt: „Dieses Etikett ist x mm lang, dieses Band erlaubt höchstens y mm.“ Ein Stapel mit einem solchen Etikett wird als Ganzes abgelehnt, nichts davon wird gedruckt; der Drucker bleibt für den nächsten Auftrag frei. Bestätigt der Drucker weniger Etiketten, als gesendet wurden, schlägt der Auftrag mit „Der Drucker hat x von y Etiketten bestätigt“ fehl: Die bestätigten Etiketten sind fertig, und Wiederholen oder **Neu drucken** druckt nur den Rest. Ein Drucker, der beides nicht kann, behält die alte Regel: Ein gesendetes Etikett gilt als gedruckt. Verweigert der Drucker seinen Etikettenzähler dreimal hintereinander (innerhalb einer Stunde und ohne eine andere Antwort auf den Zähler dazwischen; eine Zustandsabfrage, die ganz scheitert, zählt weder dafür noch dagegen), liest der Hub ihn nicht mehr, und **Druckbestätigung** sagt das („Nicht bestätigt – der Etikettenzähler antwortet nicht“). Nach einer Stunde, mit einer neuen Zählung von drei, und bei jedem Testdruck fragt er den Zähler wieder ab.

Hat der Drucker einen Bandauftrag über IPP angenommen, ihn aber nicht rechtzeitig fertig gedruckt und sich auch nicht abbrechen lassen, kommen die Etiketten vielleicht noch heraus. Zeigt der Etikettenzähler nicht alle Etiketten, schlägt der Auftrag mit `outcome_unknown` fehl („Der Druck hat angehalten, während dieses Etikett gesendet wurde. Ob es gedruckt wurde, ist unklar.“), und der Drucker **pausiert** („Ein Druck ist vielleicht nicht fertig – prüf den Drucker“), ein einzelner Auftrag genau wie ein langer Lauf, damit in der Zwischenzeit nichts anderes gesendet wird. Prüf, was herausgekommen ist, druck das Fehlende neu und setz die Warteschlange des Druckers dann mit **Fortsetzen** fort. Fehlen nur Etiketten („Der Drucker hat x von y Etiketten bestätigt“), pausiert der Drucker nicht.

Abgeschlossene Aufträge (fertig, fehlgeschlagen, abgebrochen) werden nach `LABELYARD_JOB_RETENTION_DAYS` gelöscht, standardmäßig nach 30 Tagen.

## Lange Bandaufträge

Eine lange Folge von Bandetiketten wird in Teile aufgeteilt. Ist das Ergebnis eines Teils unklar, zum Beispiel weil der Drucker mittendrin offline ging, hält der Auftrag dort an, statt zu raten. Du siehst, welche Etiketten sicher gedruckt sind, und wählst:

- **Mit Teil N weitermachen**, wenn die Etiketten herausgekommen sind, oder
- **Ab Etikett N neu drucken**, wenn nicht.

Bei Seitendruckern gilt dasselbe für die Felder eines Bogens: Sie bleiben unbestätigt, bis du den Bogen geprüft hast (siehe [Bögen](/de/using/sheets/)).

## Aus Skripten

`POST /api/v1/print` gibt sofort eine Auftrags-ID zurück; den Zustand fragst du mit `GET /api/v1/jobs/{job_id}` ab. Probleme, die schon vor dem Druck bekannt sind (kein Band, Deckel offen, Drucker offline), werden gleich mit einem Fehlercode beantwortet statt mit einem eingereihten Auftrag. Die [API-Referenz](/de/developers/api/) listet sie.
