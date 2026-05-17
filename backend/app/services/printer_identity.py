"""Deterministic printer UUIDv5 derived from environment configuration.

Phase 7b Cluster 1b: lifespan computes a stable identifier from
``(model, host, port)`` so the runtime printer (driver.make_queue_printer)
and the DB row (upsert_runtime_printer) share the same ``printer.id``
across restarts.

The namespace UUID is a constant committed to the repo — do NOT change
without a coordinated DB migration: every existing printer row would
become orphaned.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# Phase 7b namespace constant; chosen randomly. Do not alter.
_PRINTER_NAMESPACE = UUID("6f1b3c7e-9d6a-4f48-9a8c-d4e0e1c5a3b2")


def derive_printer_id(model: str, host: str, port: int) -> UUID:
    """Return a deterministic UUIDv5 for ``(model, host, port)``.

    ``model`` is lower-cased before hashing so environment-supplied values
    like ``PT-P750W`` and ``pt-p750w`` map to the same identifier.
    """
    return uuid5(_PRINTER_NAMESPACE, f"{model.lower()}|{host}|{port}")
