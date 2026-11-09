"""The browser-test control paths exist in the e2e app only (Plan 4, Task 1, C5).

``/__e2e/`` switches a fake printer's state without authentication. It is served by the ASGI
wrapper in ``tests/e2e_app.py`` and must never be reachable in the production app, nor may the
test tree end up in the container image.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.main import create_app

BACKEND = Path(__file__).resolve().parents[2]


def _paths(app: object) -> list[str]:
    inner = getattr(app, "_app", app)
    return [str(getattr(route, "path", "")) for route in inner.routes]  # type: ignore[attr-defined]


def test_e2e_control_route_absent_in_production_app() -> None:
    assert [p for p in _paths(create_app()) if p.startswith("/__e2e")] == []


REPO = BACKEND.parent
_BROAD_SOURCES = {".", "./", "backend", "backend/", "./backend", "./backend/", "backend/."}


def _copy_offenders(dockerfile: str, dockerignore: str) -> list[str]:
    """COPY lines that could bring the test tree into the image.

    A source with a ``tests`` path segment is always an offender. A broad source (the whole
    context or the whole ``backend/``) is one unless ``.dockerignore`` excludes ``backend/tests``.
    """
    ignored = {line.strip().rstrip("/") for line in dockerignore.splitlines()}
    excluded = "backend/tests" in ignored or "**/tests" in ignored
    offenders = []
    for line in dockerfile.splitlines():
        if not re.match(r"\s*COPY\b", line, re.I):
            continue
        args = [a for a in line.split()[1:] if not a.startswith("--")]
        for source in args[:-1]:  # the last argument is the destination
            segments = source.strip("/").split("/")
            has_tests = "tests" in segments or "test" in segments
            if has_tests or (source in _BROAD_SOURCES and not excluded):
                offenders.append(line)
    return offenders


@pytest.mark.parametrize(
    ("dockerfile", "dockerignore", "bad"),
    [
        ("COPY backend/app/ ./app/", "", False),
        ("COPY backend/tests/ ./tests/", "backend/tests", True),
        ("COPY backend/ ./", "", True),
        ("COPY . .", "", True),
        ("COPY --chown=hub:hub backend/ ./", "backend/tests\n", False),
        ("COPY --from=builder /opt/venv /opt/venv", "", False),
    ],
)
def test_copy_guard_flags_broad_and_test_sources(
    dockerfile: str, dockerignore: str, bad: bool
) -> None:
    assert bool(_copy_offenders(dockerfile, dockerignore)) is bad


def test_tests_never_copied_into_image() -> None:
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
    assert "COPY" in dockerfile, "the guard reads the wrong file"
    assert "backend/tests" in dockerignore.split(), ".dockerignore no longer excludes the tests"
    assert _copy_offenders(dockerfile, dockerignore) == []
