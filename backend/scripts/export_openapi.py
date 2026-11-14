# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Print the backend's OpenAPI document to stdout (``pnpm gen:api`` in ``frontend/``).

Needs no running server and no real settings: the app factory is imported with
obviously fake placeholder settings, and the schema is built from the route table.

    python backend/scripts/export_openapi.py > frontend/openapi.json
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile


def _fake_settings_env() -> None:
    """Fill the required settings with non-secret placeholders (never real values)."""
    key = base64.urlsafe_b64encode(b"openapi-export-only-key-00000000"[:32]).decode()
    os.environ.setdefault("LABELYARD_SECRET_KEY", key)
    os.environ.setdefault("LABELYARD_PUBLIC_URL", "http://localhost:8000")
    # The app resolves the web root at import; the directory need not hold a build.
    os.environ.setdefault("LABELYARD_WEB_DIST_DIR", tempfile.gettempdir())
    os.environ.setdefault("LABELYARD_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def main() -> int:
    _fake_settings_env()
    from app.main import create_app  # after the environment is prepared

    # create_app() wraps the FastAPI app; the wrapper keeps it in ``_app``.
    wrapper = create_app()
    schema = wrapper._app.openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
