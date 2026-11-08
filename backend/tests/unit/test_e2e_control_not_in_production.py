"""The browser-test control paths exist in the e2e app only (Plan 4, Task 1, C5).

``/__e2e/`` switches a fake printer's state without authentication. It is served by the ASGI
wrapper in ``tests/e2e_app.py`` and must never be reachable in the production app, nor may the
test tree end up in the container image.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.main import create_app

BACKEND = Path(__file__).resolve().parents[2]


def _paths(app: object) -> list[str]:
    inner = getattr(app, "_app", app)
    return [str(getattr(route, "path", "")) for route in inner.routes]  # type: ignore[attr-defined]


def test_e2e_control_route_absent_in_production_app() -> None:
    assert [p for p in _paths(create_app()) if p.startswith("/__e2e")] == []


def test_tests_never_copied_into_image() -> None:
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    copies = [line for line in dockerfile.splitlines() if re.match(r"\s*COPY\b", line, re.I)]
    assert copies, "the Dockerfile has no COPY lines: the guard reads the wrong file"
    offenders = [line for line in copies if re.search(r"(^|[\s/])tests?(/|\s|$)", line)]
    assert offenders == [], f"COPY of the test tree into the image: {offenders}"
