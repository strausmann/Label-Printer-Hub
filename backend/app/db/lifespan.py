"""FastAPI startup/shutdown helpers — DB-layer concerns only.

Each function here is a focused async helper that the FastAPI lifespan
context manager calls in sequence.  Keeping them as standalone coroutines
(rather than inline lambdas) makes them individually testable and easy to
reorder or disable in CI.

Call order in main.py lifespan:
    1. run_migrations()          — apply pending Alembic revisions
    2. recover_inflight_jobs()   — mark stale QUEUED/PRINTING jobs as failed_restart
    3. seed_templates()          — upsert YAML seed templates into DB
    4. upsert_runtime_printer()  — materialise ONE Printer row from env config
    5. ensure_printer_state()    — create missing printer_state rows
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.printer import Printer
from app.services.printer_identity import derive_printer_id
from app.services.template_loader import TemplateLoader


async def run_migrations() -> None:
    """Apply pending Alembic migrations programmatically.

    Alembic's command module is synchronous and performs blocking I/O
    (reads alembic.ini, the migration scripts, and writes to the SQLite
    file).  Wrapping the call in asyncio.to_thread keeps the FastAPI
    event loop unblocked during startup.

    The ini path is resolved relative to this file so the helper works
    regardless of the process working directory.
    """
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    # backend/app/db/lifespan.py → ../../../ = backend/
    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"

    def _upgrade() -> None:
        cfg = Config(str(ini_path))
        # Prevent alembic from calling logging.config.fileConfig() which
        # would reconfigure the root logger and break pytest caplog fixtures.
        cfg.attributes["configure_logger"] = False
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_upgrade)


async def recover_inflight_jobs(session: AsyncSession) -> int:
    """Mark any QUEUED or PRINTING jobs as FAILED_RESTART.

    Returns the number of rows updated.  Safe to call on a fresh DB
    (returns 0).  Called before seed_templates so the log message
    appears before the (potentially longer) seed step.
    """
    from app.repositories import jobs as jobs_repo

    return await jobs_repo.mark_inflight_as_failed_restart(session)


async def seed_templates(session: AsyncSession, loader: type[TemplateLoader]) -> int:
    """Idempotent YAML → DB upsert, delegated to ``loader.seed_db(session)``.

    The conversion logic lives on ``TemplateLoader.seed_db`` (Task 8) so
    there is a single source of truth for the TemplateSchema → Template
    column mapping.  This function exists only as a named startup step that
    main.py can call by name, and is the natural seam for unit tests that
    want to inject a mock loader without touching the real registry.

    Raises RuntimeError if the loader cache is empty — calling seed_templates
    without first running TemplateLoader.load_dir() is a lifespan-ordering bug.

    Returns the count of rows touched (inserted or updated).
    """
    if not loader._cache:
        raise RuntimeError(
            "seed_templates called with empty TemplateLoader cache — "
            "TemplateLoader.load_dir() must run before seed_templates()."
        )
    return await loader.seed_db(session)


async def ensure_printer_state(session: AsyncSession) -> int:
    """Create a printer_state row for every Printer that lacks one.

    Returns the count of rows created.  Idempotent — subsequent calls
    create 0 rows once every printer already has a state row.
    """
    from sqlalchemy import select

    from app.models.printer import Printer
    from app.models.printer_state import PrinterState
    from app.repositories import printer_state as printer_state_repo

    result = await session.execute(select(Printer))
    printers = list(result.scalars())

    created = 0
    for printer in printers:
        existing = await printer_state_repo.get(session, printer.id)
        if existing is None:
            state = PrinterState(printer_id=printer.id, paused=False)
            session.add(state)
            created += 1

    if created:
        await session.commit()

    return created


async def upsert_runtime_printer(
    session: AsyncSession,
    settings: Settings,
) -> UUID | None:
    """Materialise one Printer row from env config; return its deterministic id.

    Returns ``None`` when the environment does NOT declare a printer host
    (e.g. mock backend in CI).  The lifespan calls this between
    ``seed_templates`` and ``ensure_printer_state`` so every restart
    keeps the single runtime printer row consistent with the current env.

    The Printer row is keyed by the deterministic UUIDv5 produced by
    ``derive_printer_id(model, host, port)`` — the same id that the
    print-queue driver uses, so the DB row and the in-memory printer share
    one stable identity across restarts.
    """
    model: str = settings.printer_model
    # Resolve host: pt750w takes precedence, ql820 is the fallback.
    host: str = settings.pt750w_host or settings.ql820_host or ""
    port: int = settings.pt750w_port if settings.pt750w_host else settings.ql820_port

    if not (model and host and port):
        return None

    printer_id: UUID = derive_printer_id(model, host, port)
    connection: dict[str, object] = {
        "host": host,
        "port": port,
        "snmp": settings.printer_discover_via_snmp,
        "snmp_community": settings.printer_snmp_community,
    }
    name: str = f"{model} ({host})"

    existing = await session.get(Printer, printer_id)
    if existing is not None:
        existing.name = name
        existing.connection = connection
        existing.enabled = True
    else:
        session.add(
            Printer(
                id=printer_id,
                name=name,
                model=model.lower(),
                backend=settings.printer_backend,
                connection=connection,
                enabled=True,
            )
        )
    await session.flush()
    return printer_id
