"""Model package — re-exports all SQLModel table classes.

Every class listed here is registered with SQLModel.metadata, which is
required for Alembic autogenerate to detect schema changes.
"""
from app.models.printer import Printer

__all__ = ["Printer"]
