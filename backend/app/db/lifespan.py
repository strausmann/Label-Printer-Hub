"""FastAPI startup/shutdown helpers — DB-layer concerns only.

Each function here is a focused async helper that the FastAPI lifespan
context manager calls in sequence.  Keeping them as standalone coroutines
(rather than inline lambdas) makes them individually testable and easy to
reorder or disable in CI.

Call order in main.py lifespan:
    1. run_migrations()           — apply pending Alembic revisions
    1b. verify_alembic_at_head()  — assert DB revision == script head (fail fast)
    2. _discover_plugins()        — register integration + model plugins (idempotent)
    3. TemplateLoader.load_dir()  — populate in-memory template cache (Cluster 1a)
    4. recover_inflight_jobs()    — mark stale QUEUED/PRINTING jobs as failed_restart
    5. seed_templates()           — YAML → DB upsert (defensive check on cache)
    6. upsert_runtime_printers()  — printers.yaml → DB Printer rows (Cluster 1b, M-H2-Fix)
    7. ensure_printer_state()     — create missing printer_state rows per Printer

Note: steps 2 and 3 must precede step 5 — TemplateLoader.load_dir() validates
templates against IntegrationRegistry (populated in step 2), and seed_templates()
reads from the cache that load_dir() populates in step 3.

Phase 1i CA-1: upsert_runtime_printer (Settings-abhängig) entfernt.
Ersetzt durch upsert_runtime_printers (PrinterYAMLConfig-List).
R4-M-4/M-5-Fix: alte Funktion referenzierte entfernte Settings-Felder.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer import Printer
from app.schemas.printer_config import PrinterYAMLConfig
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


async def verify_alembic_at_head(settings: Settings) -> None:
    """Raise RuntimeError if the DB's alembic revision does not match the script head.

    Lifespan calls this right after run_migrations() so a half-applied or
    corrupted DB fails startup loudly with a clear log line, instead of
    crashing later inside ORM queries with cryptic schema errors.

    Takes settings explicitly so unit tests can verify against ad-hoc DBs
    without monkey-patching the get_settings() lru_cache singleton — that's
    the C2/D2 testability pattern.
    """
    import asyncio
    from pathlib import Path as _Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    # backend/app/db/lifespan.py → parents[2] = backend/
    ini_path = _Path(__file__).resolve().parents[2] / "alembic.ini"

    def _check() -> tuple[str | None, str | None]:
        cfg = Config(str(ini_path))
        # Prevent alembic from calling logging.config.fileConfig() which would
        # reconfigure the root logger and break pytest caplog fixtures.
        cfg.attributes["configure_logger"] = False
        script = ScriptDirectory.from_config(cfg)
        head_rev = script.get_current_head()

        # SQLAlchemy's synchronous engine: strip the async driver suffix
        sync_url = settings.database_url.replace("+aiosqlite", "")
        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                current_rev = ctx.get_current_revision()
        finally:
            engine.dispose()

        return current_rev, head_rev

    current_rev, head_rev = await asyncio.to_thread(_check)
    if current_rev != head_rev:
        raise RuntimeError(
            f"Alembic migration drift detected: DB at {current_rev!r}, expected head {head_rev!r}"
        )


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


async def upsert_runtime_printers(
    session: AsyncSession,
    configs: list[PrinterYAMLConfig],
) -> list[UUID]:
    """Materialisiert eine DB-Zeile pro Drucker-Eintrag aus printers.yaml.

    M-H2-Fix: Multi-Printer-Loop.
    MA-2-Fix: derive_printer_id(model, host, port) bleibt deterministisch —
              model in printers.yaml MUSS exakt der bisherigen Env-Var entsprechen.
    R4-M-4/M-5-Fix: Alte upsert_runtime_printer (Settings-abhängig) gelöscht —
                    referenzierte entfernte Felder und würde AttributeError geben.

    Returns: Liste der printer_id UUIDs (für lifespan-Wiring).
    """
    ids: list[UUID] = []
    for cfg in configs:
        printer_id = derive_printer_id(cfg.model, cfg.host, cfg.port)
        existing = await session.get(Printer, printer_id)
        if existing is None:
            session.add(
                Printer(
                    id=printer_id,
                    slug=cfg.slug,
                    name=cfg.name,
                    model=cfg.model.lower(),
                    backend=cfg.backend,
                    connection={"host": cfg.host, "port": cfg.port},
                    enabled=True,
                )
            )
        else:
            existing.slug = cfg.slug
            existing.name = cfg.name
            existing.backend = cfg.backend
            # host/port/model bleiben stabil (UUID-Basis)
        ids.append(printer_id)
    await session.commit()
    return ids
