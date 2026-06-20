"""Redaction-Helper fuer printers_audit (Issue #124).

Vor dem Schreiben von before_json/after_json werden bekannte Secret-Pfade
durch '***REDACTED***' ersetzt. Verhindert dass SNMP-Community in
DB-Backups landet.
"""

from __future__ import annotations

import copy
from typing import Any

REDACTED = "***REDACTED***"

SECRET_PATHS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("connection", "snmp", "community"),
    }
)


def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Erzeugt eine Deep-Copy mit allen bekannten Secret-Pfaden redacted.

    Behaviour:
    - Wenn das Feld None ist, bleibt es None (kein Verschleiern fehlender Werte).
    - Wenn ein Zwischenpfad fehlt, ueberspringe stillschweigend.
    - Mutiert die Input-Dict NICHT.
    """
    out = copy.deepcopy(payload)
    for path in SECRET_PATHS:
        _redact_path(out, list(path))
    return out


def _redact_path(node: Any, path: list[str]) -> None:
    if not path:
        return
    if not isinstance(node, dict):
        return
    head, *rest = path
    if head not in node:
        return
    if not rest:
        if node[head] is None:
            return  # None bleibt None
        node[head] = REDACTED
        return
    _redact_path(node[head], rest)
