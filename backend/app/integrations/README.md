# Integration Plugins

Lookup clients for external apps (Snipe-IT, Spoolman, Grocy,
third-party) live here. Each plugin implements the `IntegrationPlugin`
protocol from `base.py` and registers itself via setuptools
entry-points.

## Adding a bundled plugin

1. Create `backend/app/integrations/<name>/plugin.py` with a class that
   implements `IntegrationPlugin`:

   ```python
   from app.integrations.live_config import StoreBoundPlugin
   from app.schemas.label_data import LabelData


   class MyAppPlugin(StoreBoundPlugin):
       name = "myapp"
       display_name = "My App"
       secret_suffix = "api_key"  # None when the app needs no key

       def __init__(self) -> None:
           self._init_live()  # no arguments: discovery calls plugin_cls()

       async def lookup(self, identifier: str) -> LabelData:
           self._require_configured()  # raises -> 503 integration_not_configured
           # Use self._base_url / self._api_key / self._client.
           ...
   ```

   `StoreBoundPlugin` provides `bind`, `reconfigure`, `is_configured` and
   `aclose`. The lifespan calls `bind(store)` after discovery; from then on the
   URL, secret and timeout come from the runtime settings store (D4) and a
   change applies on the next request, without a restart.

2. Add the plugin's configuration fields to `backend/app/config.py`:

   ```python
   class Settings(BaseSettings):
       # ... existing fields ...
       myapp_url: str = ""
       myapp_api_key: SecretStr = SecretStr("")
       myapp_timeout: float = 5.0
   ```

   Settings reads them from environment variables prefixed with
   `LABELYARD_` (e.g. `LABELYARD_MYAPP_URL`). Also add the
   `integrations.myapp.*` keys to `app/settings_store/registry.py`; the
   plugin reads them through the store (an environment value locks the
   field, D4).

3. Register the entry-point in `backend/pyproject.toml`:

   ```toml
   [project.entry-points."label_hub.integrations"]
   myapp = "app.integrations.myapp.plugin:MyAppPlugin"
   ```

4. Re-install the package (`pip install -e backend`) and the plugin
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
the same way bundled plugins are — no Labelyard repo change needed.

Third-party plugins cannot add fields to the core `app.config.Settings`
class — it uses `extra="ignore"`, and pip-installed packages cannot
modify the host application's source. External plugins should manage
their own configuration: read environment variables directly (with
`os.environ` or a local `pydantic_settings.BaseSettings` subclass),
or accept a dedicated env-var prefix (e.g. `LABELYARD_OPENFOODFACTS_*`)
that does not collide with the core `LABELYARD_*` namespace.

Bundled plugins read the runtime settings store; third-party plugins
must NOT depend on it for their own keys, because adding a key there
requires a core repo change.

## Plugin contract

| Attribute / method | Type | Purpose |
|---|---|---|
| `name` | `str` | Canonical id used in templates (`TemplateSchema.app`) and audit logs. Must be unique across all registered plugins. |
| `display_name` | `str` | UI label, e.g. shown in template-picker dropdowns. |
| `__init__(self)` | `None` | Must accept no positional or keyword arguments — entry-points discovery instantiates plugins with `plugin_cls()`. Do not read configuration here; it arrives through `bind`. |
| `bind(store)` | `(SettingsStore) -> None` | Called once in the lifespan after discovery. Attaches the runtime settings store and subscribes to changes. |
| `reconfigure()` | `async () -> None` | Closes and recreates the `httpx.AsyncClient` from the current store values. |
| `is_configured()` | `() -> bool` | URL set and, where needed, key set and decryptable. `False` before `bind`. |
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
in an `autouse=True` fixture, then build the plugin with
`tests.unit.integrations._bound.bound(MyAppPlugin)` (binds an env-backed
store). To test live changes, use a `SettingsStore` and `set_many` as in
`test_live_settings.py`:

```python
@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_MYAPP_URL", "https://example.test")
    get_settings.cache_clear()
```
