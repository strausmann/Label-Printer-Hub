"""Public shell info and the admin system-log view.

``GET /api/v1/info`` is public by design: the web shell and the sign-in screen need
version, default language and auth hints before anyone is signed in. It returns
build info and booleans only, never a secret.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions as ui_sessions
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin
from app.build_info import PROJECT_LICENSE, source_url
from app.config import get_settings
from app.db.session import get_session
from app.integrations.registry import IntegrationRegistry
from app.observability.log_buffer import LOG_BUFFER, LOG_BUFFER_CAPACITY
from app.schemas.info import Info, InfoAuth, InfoIntegration, LogEntry

router = APIRouter(tags=["info"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]

# Later modules flip their flag when they ship.
FEATURES: dict[str, bool] = {
    "jobs": True,
    "lookup": True,
    "scan": True,
    "parts": False,
    "sheets": True,
    "calibration": True,
    "asn": False,
    "kept": False,
}


#: The integrations the web UI knows, in the order its navigation lists them.
INTEGRATIONS: tuple[Literal["snipeit", "grocy", "spoolman"], ...] = ("snipeit", "grocy", "spoolman")


def _integration_status() -> list[InfoIntegration]:
    plugins = IntegrationRegistry.all()
    return [
        InfoIntegration(
            name=name, configured=bool(name in plugins and plugins[name].is_configured())
        )
        for name in INTEGRATIONS
    ]


@router.get("/api/v1/info", response_model=Info)
async def get_info(request: Request, db: SessionDep) -> Info:
    # Imported lazily: app.main imports this module.
    from app.main import HUB_BUILD_DATE, HUB_REPO_URL, HUB_REVISION, HUB_VERSION

    settings = get_settings()
    store = request.app.state.settings_store
    language = str(store.get("general.language"))
    bootstrap_open = bool(
        settings.bootstrap_admin_key.get_secret_value()
        and not await ui_sessions.admin_key_exists(db)
    )
    return Info(
        version=HUB_VERSION,
        revision=HUB_REVISION,
        build_date=HUB_BUILD_DATE,
        license=PROJECT_LICENSE,
        source_url=source_url(HUB_REPO_URL, HUB_VERSION, HUB_REVISION),
        default_language=cast(Literal["en", "de"], language if language in ("en", "de") else "en"),
        display_name=str(store.get("general.display_name")),
        auth=InfoAuth(
            sso_configured=bool(settings.sso_trust_token),
            bootstrap_open=bootstrap_open,
        ),
        features=dict(FEATURES),
        integrations=_integration_status(),
    )


@router.get("/api/v1/system/logs", response_model=list[LogEntry])
async def get_system_logs(
    _auth: AdminDep,
    limit: Annotated[int, Query(ge=1)] = 200,
) -> list[LogEntry]:
    """Newest ``limit`` WARNING+ records (capped at the buffer size), oldest first."""
    entries = LOG_BUFFER.snapshot(min(limit, LOG_BUFFER_CAPACITY))
    return [LogEntry(**e) for e in entries]
