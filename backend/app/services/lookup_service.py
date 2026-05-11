"""Aggregator that routes lookup requests to the right per-app client.

The service does not know any client's internals — it just dispatches by
`source_app` to a registered async lookup callable. New apps (e.g.
OpenFoodFacts) plug in by extending the constructor and the `_AppName`
literal.

UnknownAppError signals a configuration mismatch (the caller asked for an
app that wasn't registered). It deliberately does NOT inherit from
AppLookupNotFoundError — the two failure modes are operationally distinct:

- UnknownAppError: "you misconfigured the request"
- AppLookupNotFoundError (from any client): "the entity doesn't exist"
"""

from __future__ import annotations

from typing import Literal, Protocol, cast, get_args

from app.schemas.label_data import LabelData

_AppName = Literal["snipeit", "grocy", "spoolman"]

AVAILABLE_APPS: tuple[_AppName, ...] = get_args(_AppName)


class _LookupClient(Protocol):
    """Minimal contract every per-app client satisfies.

    SnipeITClient.lookup, GrocyClient.lookup, SpoolmanClient.lookup all
    match this shape — `Protocol` lets us depend on the method without
    importing concrete classes (avoids a cycle and keeps tests trivial).
    """

    async def lookup(self, identifier: str) -> LabelData: ...


class UnknownAppError(Exception):
    """Raised when `source_app` does not match any registered client."""


class AppLookupService:
    """Route `lookup(source_app, id)` to the right per-app client."""

    def __init__(
        self,
        *,
        snipeit: _LookupClient,
        grocy: _LookupClient,
        spoolman: _LookupClient,
    ) -> None:
        self._clients: dict[_AppName, _LookupClient] = {
            "snipeit": snipeit,
            "grocy": grocy,
            "spoolman": spoolman,
        }
        # Computed once at construction — _clients never mutates after __init__.
        self.available_apps: tuple[_AppName, ...] = tuple(sorted(self._clients))

    async def lookup(self, source_app: str, identifier: str) -> LabelData:
        """Dispatch to `source_app`'s client.

        `source_app` is validated against the registry at runtime. The
        `_AppName` Literal exists for static-analysis tooling only and does
        NOT restrict what strings callers may pass — UnknownAppError covers
        the runtime mismatch case.

        Raises UnknownAppError if `source_app` is not registered. Any
        AppLookupNotFoundError from the underlying client propagates
        unchanged so callers can catch it uniformly.
        """
        client = self._clients.get(cast(_AppName, source_app))
        if client is None:
            raise UnknownAppError(
                f"Unknown app {source_app!r}. Available: {list(self.available_apps)}"
            )
        return await client.lookup(identifier)
