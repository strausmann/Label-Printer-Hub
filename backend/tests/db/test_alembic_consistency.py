"""Guards against model/migration drift.

If a SQLModel class is added/changed without a corresponding Alembic
migration, `alembic check` would catch it in CI — this test catches
the same case at PR-author time before push.

`alembic check` requires the target DB to be at the latest migration
head before it can compare metadata against it; on a fresh runner
(no `data/hub.db`) we therefore upgrade-then-check inside an isolated
temp directory so the test does not depend on the developer's local
DB state.

F1 tests: validate that the Docker runtime alembic configuration has an
absolute ``script_location`` so migrations can be found when the app
package is installed into a venv and ``__file__`` no longer resolves to
the backend source root.
"""

import configparser
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Resolve alembic relative to the running interpreter so the test works
# both inside a virtualenv (local dev) and in CI (system-level install).
_ALEMBIC = Path(sys.executable).parent / "alembic"


def test_no_pending_autogenerate_diff() -> None:
    """`alembic check` exits 0 when SQLModel.metadata matches the
    latest migration head; non-zero when a model has drifted ahead
    of the migrations.

    Runs in a temp directory so the `./data/hub.db` referenced by
    `alembic.ini`'s `sqlalchemy.url` is wiped on every invocation —
    avoids interference from a developer's local DB and gives CI a
    clean substrate.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Copy the alembic config + migrations into a working directory
        # whose `./data/` is empty. `sqlalchemy.url = sqlite+aiosqlite:///./data/hub.db`
        # in alembic.ini is CWD-relative, so running alembic from `tmp`
        # creates `tmp/data/hub.db` and we never touch the real one.
        sandbox = Path(tmp)
        shutil.copy2(BACKEND_DIR / "alembic.ini", sandbox / "alembic.ini")
        shutil.copytree(BACKEND_DIR / "alembic", sandbox / "alembic")
        (sandbox / "data").mkdir()

        # alembic env.py does `import app.models` to populate SQLModel.metadata.
        # Make the backend package importable from the sandbox by adding the
        # backend dir to PYTHONPATH for the subprocess.
        import os

        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{existing}" if existing else str(BACKEND_DIR)

        upgrade = subprocess.run(
            [str(_ALEMBIC), "upgrade", "head"],
            cwd=sandbox,
            capture_output=True,
            text=True,
            env=env,
        )
        assert upgrade.returncode == 0, (
            f"alembic upgrade head failed (this should not happen in a clean sandbox)\n"
            f"stdout: {upgrade.stdout}\nstderr: {upgrade.stderr}"
        )

        result = subprocess.run(
            [str(_ALEMBIC), "check"],
            cwd=sandbox,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"alembic check failed — a model field was added without a migration.\n"
            f"Run: cd backend && alembic revision --autogenerate -m '<description>'\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# F1 — Docker runtime alembic.ini must use an absolute script_location.
# ---------------------------------------------------------------------------

_RUNTIME_INI = BACKEND_DIR / "alembic.ini.runtime"
_RUNTIME_MIGRATIONS_DIR = "/opt/migrations/alembic"


def test_runtime_alembic_ini_exists() -> None:
    """alembic.ini.runtime must exist in the backend directory.

    Finding F1: the Dockerfile runtime stage must COPY this file to the path
    that lifespan.py resolves for alembic.ini inside the container
    (/opt/venv/lib/python3.12/site-packages/alembic.ini). If this file is
    missing the COPY directive in the Dockerfile has no source.
    """
    assert _RUNTIME_INI.exists(), (
        f"backend/alembic.ini.runtime not found at {_RUNTIME_INI}. "
        "This file is required for the Docker runtime stage (Finding F1). "
        "Create it with script_location = /opt/migrations/alembic."
    )


def test_runtime_alembic_ini_script_location_is_absolute() -> None:
    """alembic.ini.runtime must have an absolute script_location.

    Finding F1: inside the container the app is installed as a site-package,
    so Path(__file__).parents[2] resolves to the site-packages root, not to
    the backend source directory. A relative script_location like
    '%(here)s/alembic' would point into site-packages and fail. The runtime
    ini must use the absolute path where the Dockerfile COPYs the migrations.
    """
    assert _RUNTIME_INI.exists(), "alembic.ini.runtime missing — see test above"
    cfg = configparser.ConfigParser()
    cfg.read(str(_RUNTIME_INI))
    script_location = cfg.get("alembic", "script_location", fallback=None)
    assert script_location is not None, "alembic.ini.runtime has no [alembic] script_location key."
    assert script_location == _RUNTIME_MIGRATIONS_DIR, (
        f"script_location must be '{_RUNTIME_MIGRATIONS_DIR}' (absolute path), "
        f"got '{script_location}'. "
        "Relative paths break inside the container where the app is a site-package."
    )


def test_dockerfile_copies_runtime_alembic_ini() -> None:
    """Dockerfile runtime stage must COPY alembic.ini.runtime to the expected path.

    Finding F1: without this COPY the container starts without alembic.ini and
    lifespan.run_migrations() fails with 'No script_location key found'.
    """
    dockerfile = BACKEND_DIR / "Dockerfile"
    assert dockerfile.exists(), "backend/Dockerfile not found"
    content = dockerfile.read_text()
    # Check both the source (alembic.ini.runtime) and the destination path
    expected_dest = "/opt/venv/lib/python3.12/site-packages/alembic.ini"
    assert "alembic.ini.runtime" in content, (
        "Dockerfile must COPY alembic.ini.runtime into the runtime stage."
    )
    assert expected_dest in content, (
        f"Dockerfile must COPY alembic.ini.runtime to '{expected_dest}' — "
        "that is where lifespan.py resolves alembic.ini inside the container."
    )


def test_dockerfile_copies_migrations_to_opt_migrations() -> None:
    """Dockerfile runtime stage must COPY alembic/ to /opt/migrations/alembic.

    Finding F1: the runtime ini points script_location to /opt/migrations/alembic.
    If that COPY is missing the path exists in the ini but not on the filesystem.
    """
    dockerfile = BACKEND_DIR / "Dockerfile"
    assert dockerfile.exists()
    content = dockerfile.read_text()
    assert "/opt/migrations" in content, (
        "Dockerfile must COPY alembic/ to /opt/migrations/alembic "
        "(the path referenced by alembic.ini.runtime's script_location)."
    )
