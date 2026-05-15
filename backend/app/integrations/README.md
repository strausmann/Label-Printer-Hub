# Integration Plugins

Lookup clients for external apps (Snipe-IT, Spoolman, Grocy,
third-party) live here. Each plugin implements the `IntegrationPlugin`
protocol from `base.py` and registers itself via setuptools
entry-points.

## Adding a bundled plugin

1. Create `backend/app/integrations/<name>/plugin.py` with a class that
   implements `IntegrationPlugin`:

   ```python
   from app.schemas.label_data import LabelData


   class MyAppPlugin:
       name = "myapp"
       display_name = "My App"

       def __init__(self) -> None:
           # Local import avoids a load-time cycle.
           from app.config import get_settings
           settings = get_settings()
           self._base_url = settings.myapp_url.rstrip("/")

       async def lookup(self, identifier: str) -> LabelData:
           # Call upstream, build LabelData.
           ...
   ```

2. Register the entry-point in `backend/pyproject.toml`:

   ```toml
   [project.entry-points."label_hub.integrations"]
   myapp = "app.integrations.myapp.plugin:MyAppPlugin"
   ```

3. Re-install the package (`pip install -e backend`) and the plugin
   loads at app start. `IntegrationRegistry.names()` will include
   `"myapp"`.

## Adding a third-party plugin (external repo)

External plugins are standalone Python packages. Their own
`pyproject.toml` declares the same entry-points group:

```toml
[project.entry-points."label_hub.integrations"]
openfoodfacts = "label_hub_openfoodfacts.plugin:OpenFoodFactsPlugin"
```

After `pip install label-hub-openfoodfacts` the plugin is registered
the same way bundled plugins are — no Label-Hub repo change needed.

## Plugin contract

| Attribute / method | Type | Purpose |
|---|---|---|
| `name` | `str` | Canonical id used in templates (`TemplateSchema.app`) and audit logs. Must be unique across all registered plugins. |
| `display_name` | `str` | UI label, e.g. shown in template-picker dropdowns. |
| `__init__(self)` | `None` | Must accept no positional or keyword arguments — entry-points discovery instantiates plugins with `plugin_cls()`. Read configuration from `app.config.get_settings()` via a local import. |
| `lookup(identifier)` | `async (str) -> LabelData` | Resolves the integration's identifier to a `LabelData`. Raise `AppLookupNotFoundError` (or a subclass) when the entity does not exist. |

## Defensive loading

Plugin discovery in `app/integrations/__init__.py` catches and logs
four failure modes so a single broken third-party package cannot
prevent the rest of the application from starting:

1. `entry_point.load()` raises an exception.
2. The plugin class's `__init__` raises.
3. The loaded object does not satisfy `IntegrationPlugin` (missing
   required attributes).
4. The plugin's `name` collides with an already-registered plugin, or
   has the wrong type (the registry rejects with
   `ValueError`/`TypeError`).

Failures are logged via `logging` (level: ERROR) with the entry-point
name. Production sysadmins find the broken plugin in their log
aggregator without losing any well-behaved plugins.

## Testing

Plugin tests live in
`backend/tests/unit/integrations/test_<name>_plugin.py`. Use `respx`
to mock the upstream HTTP layer (`respx` is already a dev dependency
in `pyproject.toml`).

To exercise plugin configuration via environment variables in tests,
use the `monkeypatch.setenv` pattern + `get_settings.cache_clear()`
in an `autouse=True` fixture:

```python
@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_MYAPP_URL", "https://example.test")
    get_settings.cache_clear()
```
