"""FastAPI startup/shutdown helpers — DB-layer concerns only.

Each function here is a focused async helper that the FastAPI lifespan
context manager calls in sequence.  Keeping them as standalone coroutines
(rather than inline lambdas) makes them individually testable and easy to
reorder or disable in CI.

Call order in main.py lifespan:
    1. run_migrations()          — apply pending Alembic revisions
    2. recover_inflight_jobs()   — mark stale QUEUED/PRINTING jobs as failed_restart
    3. seed_templates()          — upsert YAML seed templates into DB
    4. ensure_printer_state()    — create missing printer_state rows
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


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


async def seed_templates(session: AsyncSession, loader: object) -> int:
    """Idempotent YAML → DB upsert for seed templates.

    Converts each TemplateSchema from the loader's in-memory cache into a
    Template model row with source='seed' and calls the templates repository
    upsert function.

    The mapping from TemplateSchema → Template row:
      - schema.id        → Template.key
      - schema.name      → Template.name
      - schema.app       → Template.app  (None for generic templates)
      - schema.tape_mm   → Template.tape_width_mm
      - schema.schema_version → Template.schema_version
      - "pt-series"      → Template.printer_model (seed templates are PT-series)
      - schema.model_dump() → Template.definition  (full serialised body)

    Returns the count of rows touched (inserted or updated).
    """
    from app.models.template import Template
    from app.repositories import templates as templates_repo
    from app.services.template_loader import TemplateLoader

    the_loader: TemplateLoader = loader  # type: ignore[assignment]

    rows: list[Template] = []
    for schema in the_loader.all().values():
        row = Template(
            key=schema.id,
            name=schema.name,
            app=schema.app,
            printer_model="pt-series",
            tape_width_mm=schema.tape_mm,
            schema_version=schema.schema_version,
            definition=schema.model_dump(),
            source="seed",
        )
        rows.append(row)

    return await templates_repo.upsert_seed(session, rows)


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
