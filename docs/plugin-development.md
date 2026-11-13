# Plugin development

The hub has two plugin points. Both are discovered through Python entry points when the hub starts.

| You want to add | Plugin point | Entry-point group |
|---|---|---|
| Support for another printer model | printer model plugin ([ADR 0004](decisions/0004-plugin-architecture-for-printer-models.md)) | `label_hub.printer_models` |
| Label data from another app | lookup plugin | `label_hub.integrations` |

Two things are not plugins. How bytes reach a printer is a *backend* (`backend/app/printer_backends/`, [ADR 0020](decisions/0020-backend-kinds-ipp-page-printers.md)); IPP page printers are a backend kind of their own. And a new sheet of labels is data in the sheet archive, not code.

Set up the backend first: `cd backend && uv sync --all-extras`, then `uv run pytest <file>` runs one test file. [`CONTRIBUTING.md`](../CONTRIBUTING.md) has the commit and pull-request rules.

## Part 1: a printer model plugin

A model plugin knows one printer family: its resolution, how it is recognised on the network, how an image becomes the printer's byte stream, and how a tape width is described to a person.

### 1. Copy a driver

Copy `backend/app/printer_models/pt.py` (the PT-Series driver; `backend/app/printer_models/ql.py` is the QL-Series one) to `backend/app/printer_models/<family>.py` and rename the driver class.

### 2. Implement the `PrinterModel` protocol

The protocol is in `backend/app/printer_models/base.py`. A driver class carries these class attributes:

| Attribute | Meaning |
|---|---|
| `model_id` | canonical model name, for example `PT-P750W` |
| `pjl_signatures` | substrings of the printer's PJL `MDL:` string that select this driver; none may be empty |
| `snmp_model_oid_value_substr` | substring of the SNMP model value that selects this driver; not empty |
| `dpi` | `(width_dpi, height_dpi)` |
| `print_head_pins` | number of pins on the print head |

and these methods: `query_status`, `width_to_pixels`, `build_print_job` and `describe_tape`. `describe_tape` must never raise: it returns a safe label such as `"<N>mm"` for a width it does not know.

A driver is bound to one printer backend at construction (`PTP750WDriver(backend=...)`). It also provides `make_queue_printer()`, which gives the print queue the object it prints through (`backend/app/services/print_queue.py`).

An empty `pjl_signatures` entry or an empty `snmp_model_oid_value_substr` is rejected at registration: an empty substring would match every printer and shadow the other drivers.

### 3. Register it

The module registers its driver class when it is imported, with `ModelRegistry.register(...)` at the end of the file, as `pt.py` and `ql.py` do. To make the hub import the module at start, declare an entry point in `backend/pyproject.toml`, next to the existing one:

```toml
[project.entry-points."label_hub.printer_models"]
pt-series = "app.printer_models.pt"
my-family = "app.printer_models.my_family"
```

The value may name a module (the hub scans it for driver classes) or a driver class. Reinstall the package (`uv sync`) so the entry point is picked up. A third-party package declares the same group in its own `pyproject.toml`; a plugin that fails to load is logged and skipped, it does not stop the hub.

`backend/app/printer_models/registry.py` is where the hub resolves a discovered printer to a driver: `ModelRegistry.find_by_pjl`, `find_by_snmp_oid_value` and `find_by_model_id`.

### 4. Write tests

Test against the fake backend, `MockPrinterBackend` in `backend/app/printer_backends/mock_backend.py`. It satisfies the backend protocol without a network and can be told to fail (offline, tape empty, cover open, tape mismatch), so every error path of the driver can run on a laptop. Start from `backend/tests/unit/printer_models/test_pt_driver.py`:

```python
@pytest.fixture
def backend() -> MockPrinterBackend:
    return MockPrinterBackend(host="192.0.2.10")


def test_constants() -> None:
    assert MyDriver.model_id == "MY-MODEL"
    assert MyDriver.dpi == (180, 180)
```

The registry tests in `backend/tests/unit/printer_models/` clear the class-level registry before each test (`conftest.py` there); do the same when a test registers a driver.

### 5. Hardware test (optional)

A test that needs a real printer carries the `hardware` marker and is skipped unless pytest runs with `--hardware`:

```python
pytestmark = pytest.mark.hardware
```

`backend/tests/hardware/test_pt_p750w_smoke.py` is the template. It also skips itself when the printer address is not in the environment. Use documentation addresses (`192.0.2.0/24`) in anything you commit, never your own network.

## Part 2: a lookup plugin

A lookup plugin turns an identifier from another app into `LabelData`, the content of a label. The contract is the `IntegrationPlugin` protocol in `backend/app/integrations/base.py`:

| Member | Purpose |
|---|---|
| `name`, `display_name` | the id used in requests (`"app": "myapp"`) and the label shown in the UI |
| `lookup(identifier)` | resolve the identifier; raise `AppLookupNotFoundError` (or a subclass) when it does not exist |
| `bind(store)` | called once at start, hands the plugin the runtime settings store |
| `reconfigure()` | rebuild the HTTP client after a setting changed |
| `is_configured()` | whether URL and key are usable |

`backend/app/integrations/registry.py` holds the registered plugins and rejects empty or duplicate names. Use an existing plugin as the template: `backend/app/integrations/spoolman/plugin.py` is a compact one. It builds on `StoreBoundPlugin` from `backend/app/integrations/live_config.py`, which supplies `bind`, `reconfigure`, `is_configured` and the HTTP client, so a plugin only writes `lookup`.

Steps:

1. Create `backend/app/integrations/<name>/plugin.py` with a class derived from `StoreBoundPlugin`. The constructor takes no arguments, because discovery calls `plugin_cls()`; configuration arrives through `bind`.
2. Declare the settings keys (URL, key, timeout) in `backend/app/settings_store/registry.py`. They are stored in the database and an environment variable locks the field ([ADR 0017](decisions/0017-settings-in-database-env-locks-encrypted-secrets.md)).
3. Register the entry point:

   ```toml
   [project.entry-points."label_hub.integrations"]
   myapp = "app.integrations.myapp.plugin:MyAppPlugin"
   ```

4. Test it with `respx`, which stands in for the upstream app. `backend/tests/unit/integrations/test_spoolman_plugin.py` is the template; `bound()` from `backend/tests/unit/integrations/_bound.py` builds a plugin bound to a settings store that reads the patched environment.

`backend/app/integrations/README.md` describes the contract in more detail, including third-party packages. A plugin from another package cannot add fields to the core settings; it reads its own environment variables under its own prefix.

## Checks before a pull request

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/unit/printer_models tests/unit/integrations -q
```

Open the pull request as `feat(printer-models): add <Model> plugin` or `feat(integration): add <App> lookup` (see [`CONTRIBUTING.md`](../CONTRIBUTING.md)).
