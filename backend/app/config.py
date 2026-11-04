"""Runtime configuration via Pydantic Settings.

All settings are read from environment variables prefixed with ``PRINTER_HUB_``
(e.g. ``PRINTER_HUB_DATABASE_URL``). A ``.env`` file in the working directory is
loaded automatically when present; values from the environment always take
precedence over ``.env`` values.

Printers are managed in the database (UI/API); there is no printer configuration
file and no printer-specific setting here.

``extra="forbid"`` rejects unknown CONSTRUCTOR KWARGS at instantiation time —
NOT unknown environment variables. pydantic-settings silently ignores unknown
env vars; leftover variables like the removed ``PRINTER_HUB_QL820_HOST`` etc.
will be silently dropped on startup. Operators should rely on the changelog
(or ``Settings(...)``-based init in tests) to detect leftover config.

Usage::

    from app.config import get_settings

    settings = get_settings()
    print(settings.server_port)

:func:`get_settings` is cached with :func:`functools.lru_cache` so that
settings are only parsed once per process. Tests that instantiate
:class:`Settings` directly bypass the cache and get a fresh read each time —
this is intentional and safe. To keep tests hermetic and independent of any
local ``.env`` file, pass ``_env_file=None`` when constructing
:class:`Settings` in test code.
"""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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

    # D5: key for secrets stored in the database (base64url of exactly 32 bytes).
    secret_key: SecretStr

    # Public base URL of the hub (used for links and cookie scope).
    public_url: AnyHttpUrl

    # D7: one-time bootstrap key; empty disables bootstrap, otherwise >= 32 chars.
    bootstrap_admin_key: SecretStr = SecretStr("")

    # D1: directory with the built web UI served by this process.
    web_dist_dir: Path = Path("/opt/app/web")

    # Paperless integration (optional)
    paperless_url: str = ""
    paperless_token: SecretStr = SecretStr("")
    paperless_timeout: float = 5.0

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
    log_level: LogLevel = "INFO"
    """Python-Loglevel — auf die fünf dokumentierten Werte beschränkt
    (Issue #46). Ungültige Werte (Tippfehler, lowercase) erzeugen einen
    ValidationError beim Startup statt lautlos defaulten."""

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

    # D10: proxy headers are trusted only with the SSO trust token. The two legacy
    # paths below are opt-in (default off) and never mint a browser session.
    # Legacy ``X-Pangolin-User`` header without a trust token.
    trust_legacy_pangolin_user: bool = False
    # Pangolin ``Authorization: Basic`` bypass (claude-automation credential).
    trust_pangolin_basic_bypass: bool = False
    # When True, the Basic bypass (if trusted at all) is limited to ``read`` scope.
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

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: SecretStr) -> SecretStr:
        """Require base64url text that decodes to exactly 32 bytes (AES-256)."""
        text = v.get_secret_value().strip()
        try:
            raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("PRINTER_HUB_SECRET_KEY must be base64url text") from exc
        if len(raw) != 32:
            raise ValueError(
                "PRINTER_HUB_SECRET_KEY must decode to exactly 32 bytes "
                "(generate with: python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
            )
        return SecretStr(text)

    @field_validator("bootstrap_admin_key")
    @classmethod
    def validate_bootstrap_key(cls, v: SecretStr) -> SecretStr:
        """Empty disables bootstrap; otherwise at least 32 non-whitespace characters."""
        value = v.get_secret_value().strip()
        if value and len(value) < 32:
            raise ValueError("bootstrap_admin_key must be empty or at least 32 characters")
        return SecretStr(value)

    @field_validator("webhook_api_key")
    @classmethod
    def validate_api_key_length(cls, v: SecretStr) -> SecretStr:
        """Reject keys whose effective length (after stripping whitespace) is < 32.

        An empty string is accepted so that the hub can start without
        webhook authentication configured (the webhook endpoint will
        refuse all requests at runtime, but startup succeeds).

        Issue #46: whitespace-only keys (e.g. accidentally pasted as
        ``\"                                \"``) sind faktisch leere Keys —
        sie schützen nichts und sollten beim Startup fehlschlagen statt
        eine trügerische Sicherheit zu suggerieren.

        Gemini-Review (#116): die alte Implementierung verglich `len(secret) < 32`
        gegen die **Rohlänge**. Das liess ``" " * 31 + "a"`` durch — 32 Zeichen
        formal, aber effektiv 1 Zeichen Auth-Material. Wir messen die Stripped-
        Länge und geben den getrimmten Wert als neuen SecretStr zurück, damit
        spätere Vergleiche konsistent gegen den effektiven Key laufen.
        """
        secret = v.get_secret_value()
        if not secret:
            return v
        stripped = secret.strip()
        if len(stripped) < 32:
            raise ValueError(
                "PRINTER_HUB_WEBHOOK_API_KEY must be at least 32 non-whitespace characters"
            )
        return SecretStr(stripped)


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, cached for the process lifetime.

    Call ``get_settings.cache_clear()`` in tests that need a fresh read after
    mutating environment variables.
    """
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
