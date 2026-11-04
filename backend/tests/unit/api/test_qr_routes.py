"""QR paths serve the app shell and render nothing server-side (Task 7).

The end-to-end behaviour (all four paths, API-only mode) is covered in
``tests/integration/api/test_spa_serving.py``; this checks the router in
isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.api.routes.qr import router
from app.web.spa import mount_spa
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(dist: Path | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    if dist is not None:
        mount_spa(app, dist)
    else:
        app.state.spa_index = None
    return app


@pytest.mark.parametrize("prefix", ["loc", "asset", "spool", "product"])
def test_qr_path_returns_the_shell(tmp_path: Path, prefix: str) -> None:
    (tmp_path / "index.html").write_text("<html>shell</html>")
    resp = TestClient(_app(tmp_path)).get(f"/{prefix}/ABC")
    assert resp.status_code == 200
    assert resp.text == "<html>shell</html>"


@pytest.mark.parametrize("prefix", ["loc", "asset", "spool", "product"])
def test_qr_path_without_web_app_is_json_404(prefix: str) -> None:
    resp = TestClient(_app(None)).get(f"/{prefix}/ABC")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_qr_routes_are_not_in_the_openapi_document() -> None:
    paths = _app(None).openapi()["paths"]
    assert not [p for p in paths if p.split("/")[1] in {"loc", "asset", "spool", "product"}]
