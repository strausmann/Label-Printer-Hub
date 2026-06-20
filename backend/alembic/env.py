import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# Skip when configure_logger=False is set in config.attributes (e.g. in tests
# or when called programmatically to avoid clobbering pytest's caplog handler).
if config.config_file_name is not None and not config.attributes.get("configure_logger", True):
    pass  # caller suppressed logging config
elif config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
import app.models  # noqa: E402, F401 — must follow alembic-config block; F401 keeps the registration import
from sqlmodel import SQLModel  # noqa: E402 — same reason as above

target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _include_object(
    obj: object,
    name: str | None,  # noqa: ARG001
    type_: str,
    reflected: bool,  # noqa: ARG001
    compare_to: object,  # noqa: ARG001
) -> bool:
    """Filter expression-based indexes from autogenerate comparison.

    SQLite cannot reflect text-expression indexes (e.g. ``created_at DESC``)
    back from the database, so Alembic always sees a diff between the in-memory
    model (which uses ``text("created_at DESC")``) and the reflected schema
    (which returns the plain column name).  We exclude any ``Index`` whose
    expressions contain a SQLAlchemy ``TextClause`` from autogenerate so that
    ``alembic check`` stays green on SQLite dev/CI while the migration itself
    still creates the correct expression index at upgrade time.
    """
    if type_ == "index":
        from sqlalchemy import Index as _Index
        from sqlalchemy.sql.elements import TextClause

        if isinstance(obj, _Index):
            for col in obj.expressions:
                if isinstance(col, TextClause):
                    return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
