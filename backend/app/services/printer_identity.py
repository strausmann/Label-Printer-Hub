"""Deterministischer Drucker-UUIDv5 aus Umgebungskonfiguration.

Phase 7b Cluster 1b: Der Lifespan berechnet eine stabile Kennung aus
``(model, host, port)`` damit Runtime-Drucker (driver.make_queue_printer)
und DB-Zeile (upsert_runtime_printer) beim Neustart dieselbe ``printer.id``
teilen.

Issue #124: Erweiterung auf 4-arg mit timezone-aware ``created_at_utc``.
Bestandsdrucker nutzen noch den 3-arg-Aufruf in upsert_runtime_printers —
dieser wird in Phase 5 entfernt.

Die Namespace-UUID ist eine Repo-Konstante — NICHT ändern ohne koordinierte
DB-Migration: jede bestehende Drucker-Zeile würde verwaisen.
"""

from __future__ import annotations

import uuid
from datetime import datetime

# Phase 7b Namespace-Konstante; zufällig gewählt. Nicht verändern.
_PRINTER_NAMESPACE = uuid.UUID("6f1b3c7e-9d6a-4f48-9a8c-d4e0e1c5a3b2")


def derive_printer_id(
    model: str,
    host: str,
    port: int,
    created_at_utc: datetime,
) -> uuid.UUID:
    """UUIDv5 aus Model+Host+Port+Created-At (UTC).

    ``model`` wird vor dem Hashing in Kleinbuchstaben umgewandelt, damit
    umgebungsbedingte Schreibweisen wie ``'PT-P750W'`` und ``'pt-p750w'``
    zur selben Kennung führen.

    ``created_at_utc`` MUSS timezone-aware sein. Naive datetime → ValueError.
    Der Salt ist TZ-sensitiv — der ISO-String würde je nach lokaler TZ variieren.
    """
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware (UTC)")
    salt = f"{model.lower()}|{host}|{port}|{created_at_utc.isoformat()}"
    return uuid.uuid5(_PRINTER_NAMESPACE, salt)
