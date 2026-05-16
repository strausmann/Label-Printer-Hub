"""Runtime configuration via Pydantic Settings.

All settings are read from environment variables prefixed with ``PRINTER_HUB_``
(e.g. ``PRINTER_HUB_QL820_HOST``). A ``.env`` file in the working directory is
loaded automatically when present; values from the environment always take
precedence over ``.env`` values.

Usage::

    from app.config import get_settings

    settings = get_settings()
    print(settings.ql820_host)

:func:`get_settings` is cached with :func:`functools.lru_cache` so that
settings are only parsed once per process. Tests that instantiate
:class:`Settings` directly bypass the cache and get a fresh read each time —
this is intentional and safe. To keep tests hermetic and independent of any
local ``.env`` file, pass ``_env_file=None`` when constructing
:class:`Settings` in test code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, field_validator
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
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite:////data/printer-hub.db"

    # Brother QL-820NWB — address label printer
    ql820_host: str = ""
    ql820_port: int = 9100

    # Brother PT-750W — cable / panel label printer
    pt750w_host: str = ""
    pt750w_port: int = 9100

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

    # --- First-Print ---
    printer_backend: str = "ptouch"
    printer_model: str = "PT-P750W"
    printer_discover_via_snmp: bool = True
    printer_snmp_community: str = "public"
    printer_queue_timeout_s: float = 30.0

    # Server
    server_port: int = 8090
    log_level: str = "INFO"

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
