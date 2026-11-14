---
title: Plugins schreiben
description: "Ein Druckermodell oder ein Nachschlage-Plugin für Labelyard ergänzen: die beiden Andockstellen, ihre Verträge, die Registrierung und die Tests."
---

Der Hub hat zwei Stellen für Plugins. Beide findet er beim Start über Python-Entry-Points.

| Du willst ergänzen | Andockstelle | Entry-Point-Gruppe |
|---|---|---|
| Unterstützung für ein weiteres Druckermodell | Druckermodell-Plugin ([ADR 0004](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0004-plugin-architecture-for-printer-models.md)) | `label_hub.printer_models` |
| Etikettendaten aus einer anderen App | Nachschlage-Plugin | `label_hub.integrations` |

Zwei Dinge sind keine Plugins. Wie die Bytes zum Drucker kommen, ist ein *Backend* (`backend/app/printer_backends/`, [ADR 0020](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0020-backend-kinds-ipp-page-printers.md)); IPP-Seitendrucker sind eine eigene Art von Backend. Und ein neuer Etikettenbogen ist ein Eintrag im Bogenarchiv, kein Code.

Richte zuerst das Backend ein: `cd backend && uv sync --all-extras`, danach führt `uv run pytest <datei>` eine einzelne Testdatei aus. Die Regeln für Commits und Pull Requests stehen unter [Mitmachen](/de/developers/contributing/).

## Teil 1: ein Druckermodell-Plugin

Ein Modell-Plugin kennt genau eine Druckerfamilie: ihre Auflösung, woran man sie im Netz erkennt, wie aus einem Bild der Bytestrom des Druckers wird und wie man einer Person eine Bandbreite beschreibt.

### 1. Einen Treiber kopieren

Kopier `backend/app/printer_models/pt.py` (den Treiber der PT-Serie; `backend/app/printer_models/ql.py` ist der der QL-Serie) nach `backend/app/printer_models/<familie>.py` und benenn die Treiberklasse um.

### 2. Das Protokoll `PrinterModel` umsetzen

Das Protokoll steht in `backend/app/printer_models/base.py`. Eine Treiberklasse trägt diese Klassenattribute:

| Attribut | Bedeutung |
|---|---|
| `model_id` | kanonischer Modellname, zum Beispiel `PT-P750W` |
| `pjl_signatures` | Teile der PJL-Zeichenkette `MDL:` des Druckers, die diesen Treiber auswählen; keiner darf leer sein |
| `snmp_model_oid_value_substr` | Teil des SNMP-Modellwerts, der diesen Treiber auswählt; nicht leer |
| `dpi` | `(width_dpi, height_dpi)` |
| `print_head_pins` | Zahl der Nadeln im Druckkopf |

und diese Methoden: `query_status`, `width_to_pixels`, `build_print_job` und `describe_tape`. `describe_tape` darf nie eine Ausnahme werfen: Für eine Breite, die sie nicht kennt, gibt sie eine sichere Bezeichnung wie `"<N>mm"` zurück.

Ein Treiber wird beim Anlegen an genau ein Drucker-Backend gebunden (`PTP750WDriver(backend=...)`). Er bietet außerdem `make_queue_printer()`, das der Warteschlange das Objekt gibt, über das sie druckt (`backend/app/services/print_queue.py`).

Ein leerer Eintrag in `pjl_signatures` oder ein leeres `snmp_model_oid_value_substr` wird bei der Registrierung abgewiesen: Ein leerer Teilstring passt auf jeden Drucker und würde die anderen Treiber verdecken.

### 3. Ihn registrieren

Das Modul registriert seine Treiberklasse, sobald es importiert wird, mit `ModelRegistry.register(...)` am Ende der Datei, so wie es `pt.py` und `ql.py` tun. Damit der Hub das Modul beim Start importiert, trag in `backend/pyproject.toml` einen Entry Point neben dem vorhandenen ein:

```toml
[project.entry-points."label_hub.printer_models"]
pt-series = "app.printer_models.pt"
my-family = "app.printer_models.my_family"
```

`pyproject.toml` registriert heute nur `pt-series`. `ql.py` meldet seinen Treiber beim Import an (anderer Code des Hubs importiert es), hat aber keinen eigenen Entry Point. Eine neue Familie, die du aus einer der beiden Dateien kopierst, braucht deshalb einen eigenen Entry Point wie oben.

Der Wert darf ein Modul nennen (der Hub sucht darin nach Treiberklassen) oder eine Treiberklasse. Installier das Paket neu (`uv sync`), damit der Entry Point erkannt wird. Ein Paket von Dritten trägt dieselbe Gruppe in seine eigene `pyproject.toml` ein; ein Plugin, das sich nicht laden lässt, wird protokolliert und übersprungen, es hält den Hub nicht an.

In `backend/app/printer_models/registry.py` ordnet der Hub einem gefundenen Drucker einen Treiber zu: `ModelRegistry.find_by_pjl`, `find_by_snmp_oid_value` und `find_by_model_id`.

### 4. Tests schreiben

Teste gegen das Schein-Backend `MockPrinterBackend` in `backend/app/printer_backends/mock_backend.py`. Es erfüllt das Backend-Protokoll ohne Netz und lässt sich auf Fehler einstellen (offline, Band leer, Deckel offen, falsches Band), sodass jeder Fehlerpfad des Treibers auf dem Laptop läuft. Fang bei `backend/tests/unit/printer_models/test_pt_driver.py` an:

```python
@pytest.fixture
def backend() -> MockPrinterBackend:
    return MockPrinterBackend(host="192.0.2.10")


def test_constants() -> None:
    assert MyDriver.model_id == "MY-MODEL"
    assert MyDriver.dpi == (180, 180)
```

Die Tests der Registry in `backend/tests/unit/printer_models/` leeren die Registry auf Klassenebene vor jedem Test (`conftest.py` dort); mach das genauso, wenn ein Test einen Treiber registriert.

### 5. Test an echter Hardware (optional)

Ein Test, der einen echten Drucker braucht, trägt die Markierung `hardware` und wird übersprungen, außer pytest läuft mit `--hardware`:

```python
pytestmark = pytest.mark.hardware
```

`backend/tests/hardware/test_pt_p750w_smoke.py` ist die Vorlage. Er überspringt sich auch selbst, wenn die Adresse des Druckers nicht in der Umgebung steht. Nimm in allem, was du eincheckst, Dokumentationsadressen (`192.0.2.0/24`), nie dein eigenes Netz.

## Teil 2: ein Nachschlage-Plugin

Ein Nachschlage-Plugin macht aus einer Kennung einer anderen App `LabelData`, den Inhalt eines Etiketts. Der Vertrag ist das Protokoll `IntegrationPlugin` in `backend/app/integrations/base.py`:

| Bestandteil | Zweck |
|---|---|
| `name`, `display_name` | die Kennung in Anfragen (`"app": "myapp"`) und der Name in der Oberfläche |
| `lookup(identifier)` | die Kennung auflösen; `AppLookupNotFoundError` (oder eine Unterklasse) werfen, wenn es sie nicht gibt |
| `bind(store)` | wird beim Start einmal aufgerufen und gibt dem Plugin den Speicher der Laufzeit-Einstellungen |
| `reconfigure()` | den HTTP-Client neu bauen, nachdem sich eine Einstellung geändert hat |
| `is_configured()` | ob Adresse und Schlüssel brauchbar sind |

`backend/app/integrations/registry.py` hält die registrierten Plugins und weist leere oder doppelte Namen ab. Nimm ein vorhandenes Plugin als Vorlage: `backend/app/integrations/spoolman/plugin.py` ist ein kompaktes. Es baut auf `StoreBoundPlugin` aus `backend/app/integrations/live_config.py` auf, das `bind`, `reconfigure`, `is_configured` und den HTTP-Client mitbringt, sodass ein Plugin nur `lookup` schreibt.

Die Schritte:

1. Leg `backend/app/integrations/<name>/plugin.py` mit einer Klasse an, die von `StoreBoundPlugin` erbt. Der Konstruktor nimmt keine Argumente, weil die Erkennung `plugin_cls()` aufruft; die Einstellungen kommen über `bind`.
2. Deklarier die Einstellungsschlüssel (Adresse, Schlüssel, Zeitlimit) in `backend/app/settings_store/registry.py`. Sie liegen in der Datenbank, und eine Umgebungsvariable sperrt das Feld ([ADR 0017](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0017-settings-in-database-env-locks-encrypted-secrets.md)).
3. Registrier den Entry Point:

   ```toml
   [project.entry-points."label_hub.integrations"]
   myapp = "app.integrations.myapp.plugin:MyAppPlugin"
   ```

4. Teste es mit `respx`, das die fremde App vertritt. `backend/tests/unit/integrations/test_spoolman_plugin.py` ist die Vorlage; `bound()` aus `backend/tests/unit/integrations/_bound.py` baut ein Plugin, das an einen Einstellungsspeicher gebunden ist, der die gepatchte Umgebung liest.

`backend/app/integrations/README.md` beschreibt den Vertrag ausführlicher, auch für Pakete von Dritten. Ein Plugin aus einem anderen Paket kann den zentralen Einstellungen keine Felder hinzufügen; es liest eigene Umgebungsvariablen mit eigenem Präfix.

## Prüfungen vor einem Pull Request

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/unit/printer_models tests/unit/integrations -q
```

Öffne den Pull Request als `feat(printer-models): add <Model> plugin` oder `feat(integration): add <App> lookup` (siehe [Mitmachen](/de/developers/contributing/)).
