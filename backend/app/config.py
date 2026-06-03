"""Runtime configuration via Pydantic Settings.

All settings are read from environment variables prefixed with ``PRINTER_HUB_``
(e.g. ``PRINTER_HUB_DATABASE_URL``). A ``.env`` file in the working directory is
loaded automatically when present; values from the environment always take
precedence over ``.env`` values.

Phase 1i CA-1: Die 9 drucker-spezifischen Einzelfelder (ql820_host, ql820_port,
pt750w_host, pt750w_port, printer_backend, printer_model,
printer_discover_via_snmp, printer_snmp_community, printer_queue_timeout_s)
wurden entfernt. Drucker werden jetzt über printers.yaml konfiguriert.
``extra="forbid"`` stellt sicher dass alte Env-Vars laut fehlschlagen statt
still ignoriert zu werden.

Usage::

    from app.config import get_settings

    settings = get_settings()
    print(settings.printers_config)

:func:`get_settings` is cached with :func:`functools.lru_cache` so that
settings are only parsed once per process. Tests that instantiate
:class:`Settings` directly bypass the cache and get a fresh read each time —
this is intentional and safe. To keep tests hermetic and independent of any
local ``.env`` file, pass ``_env_file=None`` when constructing
:class:`Settings` in test code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide runtime configuration.

    Every field maps to an environment variable with the ``PRINTER_HUB_``
    prefix.  See ``.env.example`` in the ``backend/`` directory for the full
    list of supported variables and their defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="PRINTER_HUB_",
        env_file=".env",
        extra="forbid",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:////data/printer-hub.db"

    # Phase 1i Sub-Task H: Pfad zur printers.yaml (Multi-Printer-Config).
    # CA-1-Fix: Ersetzt die 9 entfernten drucker-spezifischen Felder.
    printers_config: str = "/etc/hub/printers.yaml"

    # Webhook authentication
    webhook_api_key: SecretStr = SecretStr("")

    # Snipe-IT integration (optional)
    snipeit_url: str = ""
    snipeit_api_key: SecretStr = SecretStr("")
    snipeit_timeout: float = 5.0

    # Grocy integration (optional)
    grocy_url: str = ""
    grocy_api_key: SecretStr = SecretStr("")
    grocy_timeout: float = 5.0

    # Spoolman integration (no API key needed)
    spoolman_url: str = ""
    spoolman_timeout: float = 5.0

    # Server
    server_port: int = 8090
    log_level: str = "INFO"

    # SSE EventBus — configurable resource limits
    sse_queue_size: int = Field(default=32, gt=0)
    """Per-subscriber asyncio.Queue depth. Drop-oldest when full.
    Must be > 0; asyncio.Queue(maxsize=0) is unbounded."""

    sse_idle_timeout_s: float = Field(default=300.0, gt=0)
    """Seconds of inactivity before the server closes an SSE connection.
    Must be > 0."""

    sse_max_subscribers: int = Field(default=100, gt=0)
    """Max concurrent SSE subscribers per printer. Returns 429 when exceeded.
    Must be > 0."""

    sse_heartbeat_s: float = Field(default=30.0, gt=0)
    """Interval between SSE keepalive comment frames when no events flow.
    Must be > 0; heartbeat_s=0 creates a tight busy-loop."""

    sse_probe_interval_s: float = Field(default=30.0, gt=0)
    """SNMP probe interval for StatusProbeProducer (seconds). Must be > 0."""

    # Phase 7c: Pangolin-bypass scope downgrade feature flag.
    # When True, the claude-automation Basic-Auth bypass is limited to read-only.
    # Set to False during transition to avoid surprising existing automation.
    pangolin_bypass_scope_downgrade: bool = False

    # Pangolin-SSO Standard-Header-Konfiguration (analog Hangar).
    # Pangolin setzt nach erfolgreicher SSO-Authentifizierung folgende Headers:
    #   Remote-User  — Benutzername / E-Mail-Adresse
    #   X-Pangolin-Token — statischer Trust-Token, der in der Pangolin-Resource
    #                      konfiguriert wird (Resource → Header-Injection)
    # Das Backend vertraut den Remote-* Headers NUR wenn der Trust-Token
    # übereinstimmt. Ein leeres sso_trust_token deaktiviert diesen Pfad.
    sso_user_header: str = "Remote-User"
    sso_trust_header: str = "X-Pangolin-Token"
    sso_trust_token: str = ""  # leer = SSO via Remote-User deaktiviert

    # Phase 2: Job-Retention für CleanupTask
    job_retention_days: int = Field(
        default=30,
        ge=1,
        description=(
            "Terminal Jobs (DONE/FAILED/FAILED_RESTART/CANCELLED) werden nach diesem Zeitraum "
            "vom CleanupTask gelöscht"
        ),
    )

    @field_validator("webhook_api_key")
    @classmethod
    def validate_api_key_length(cls, v: SecretStr) -> SecretStr:
        """Reject keys shorter than 32 characters.

        An empty string is accepted so that the hub can start without
        webhook authentication configured (the webhook endpoint will
        refuse all requests at runtime, but startup succeeds).
        """
        secret = v.get_secret_value()
        if secret and len(secret) < 32:
            raise ValueError("PRINTER_HUB_WEBHOOK_API_KEY must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, cached for the process lifetime.

    Call ``get_settings.cache_clear()`` in tests that need a fresh read after
    mutating environment variables.
    """
    return Settings()
