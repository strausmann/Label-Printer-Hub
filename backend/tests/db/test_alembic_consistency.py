"""Guards against model/migration drift.

If a SQLModel class is added/changed without a corresponding Alembic
migration, `alembic check` would catch it in CI — this test catches
the same case at PR-author time before push.

`alembic check` requires the target DB to be at the latest migration
head before it can compare metadata against it; on a fresh runner
(no `data/hub.db`) we therefore upgrade-then-check inside an isolated
temp directory so the test does not depend on the developer's local
DB state.
"""

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
