"""Guards against model/migration drift.

If a SQLModel class is added/changed without a corresponding Alembic
migration, alembic check would catch it in CI — this test catches
the same case at PR-author time before push.
"""
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Resolve alembic relative to the running interpreter so the test works
# both inside a virtualenv (local dev) and in CI (system-level install).
_ALEMBIC = Path(sys.executable).parent / "alembic"


def test_no_pending_autogenerate_diff() -> None:
    """`alembic check` exits 0 when SQLModel.metadata matches the
    latest migration head; non-zero when a model has drifted ahead
    of the migrations.
    """
    result = subprocess.run(
        [str(_ALEMBIC), "check"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic check failed — a model field was added without a migration.\n"
        f"Run: cd backend && alembic revision --autogenerate -m '<description>'\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
