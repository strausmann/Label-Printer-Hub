---
title: Dokumentation schreiben
description: Der Hausstil der Labelyard-Dokumentation, das Glossar, das die Begriffe festlegt, und die Textprüfungen, die bei jedem Pull Request laufen.
---

Für jede Seite hier gilt eine Regel:

> Schreibe für den Leser: was er tun möchte, dann wie. Kurze Sätze, ein Gedanke je Satz. Deutsch wird von Grund auf deutsch geschrieben, nicht Wort für Wort übersetzt, und spricht den Leser mit „du“ an. Nimm für jedes Konzept den Begriff aus dem Glossar, in beiden Sprachen. Eine Änderung an der Dokumentation ist erst fertig, wenn Englisch und Deutsch im selben Pull Request stehen.

## Was die Regel bedeutet

- **Beginne mit dem Ziel.** Eine Seite und jeder Abschnitt beginnt damit, was der Leser erreichen will. Danach folgen die Schritte.
- **Ein Gedanke je Satz.** Halte dich an höchstens 25 Wörter im Deutschen und 30 im Englischen. Ein längerer Satz sind meist zwei.
- **Schreibe deutsch, nicht übersetzt.** Gib den englischen Satz nicht Wort für Wort wieder. Sag es so, wie du es einem Kollegen erklären würdest. Sprich den Leser mit „du“ an und schreibe echte Umlaute: ä, ö, ü, ß.
- **Nimm den Glossarbegriff.** Jedes Konzept hat einen englischen und einen deutschen Begriff im [Glossar](/de/using/glossary/). Mische kein Synonym und kein englisches Wort in eine deutsche Seite.
- **Liefere beide Sprachen zusammen.** Eine Seite unter `website/src/content/docs/` ändert sich auf Englisch und auf Deutsch (`de/`, gleicher Pfad) im selben Pull Request. Die Prüfung `website / locale parity` schlägt sonst fehl.

## Das Glossar

`docs/glossary.toml` ist die einzige Quelle. Sie führt jedes Konzept einmal auf, in beiden Sprachen, mit einer kurzen Bedeutung und den Schreibweisen, die du vermeidest. Daraus entstehen drei Dinge, damit sie nicht auseinanderlaufen:

- die beiden Glossarseiten dieser Website,
- die Vale-Regeln und Wortlisten in `.vale/`,
- die Prüfung der Oberflächentexte in `frontend/src/i18n/locales/`.

Einen Begriff ergänzt oder änderst du in der TOML-Datei. Danach führst du aus:

```bash
python3 scripts/glossary.py write
```

Committe die erzeugten Dateien mit. CI schlägt fehl, wenn sie nicht aktuell sind.

## Die Textprüfungen

Der Workflow `prose` lässt [Vale](https://vale.sh/) über `README.md`, `CONTRIBUTING.md`, `docs/` und diese Website laufen. Codeblöcke werden nicht geprüft. Drei Stufen sind wichtig:

| Stufe | Was sie findet | Wirkung |
|---|---|---|
| Fehler | Den alten Produktnamen. Einen abgelehnten Glossarbegriff, etwa `Job` statt „Auftrag“. | Die Prüfung schlägt fehl |
| Warnung | Einen abgelehnten Begriff mit Ersatz, Füllwörter, einen zu langen Satz. | Wird nur gemeldet |
| Hinweis | Schwammige oder umständliche Formulierungen im Englischen. | Wird nur gemeldet |

Auf deinem Rechner startest du sie so:

```bash
scripts/vale_setup.sh
python3 scripts/vale_scope.py | xargs .vale/bin/vale
```

`vale_setup.sh` installiert das festgelegte Vale-Release und prüft seine Prüfsumme. Mit `--minAlertLevel=error` siehst du nur, was CI fehlschlagen lässt.

Eine Seite, die den alten Produktnamen nennen muss, etwa die Migrationsanleitung, hat in `.vale.ini` einen eigenen Abschnitt. Schreib `Label Printer Hub` sonst nirgends, außer als Untertitel neben Labelyard.
