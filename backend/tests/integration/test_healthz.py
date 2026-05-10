"""Integration tests for the /healthz endpoint.

The healthz endpoint is the container's liveness probe — Docker, Kubernetes,
and the reverse proxy all use it to decide whether the backend is up. It
intentionally has zero dependencies (no DB, no printer, no SNMP). If
healthz fails, the process is in trouble.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


class TestHealthz:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200

    def test_returns_json_with_status_field(self, client: TestClient) -> None:
        response = client.get("/healthz")
        body = response.json()
        assert "status" in body
        assert body["status"] == "ok"

    def test_includes_version(self, client: TestClient) -> None:
        """Version field lets ops verify which build is running."""
        response = client.get("/healthz")
        body = response.json()
        assert "version" in body
        assert isinstance(body["version"], str)
        assert body["version"]  # not empty

    def test_includes_build_info(self, client: TestClient) -> None:
        """Build metadata identifies the exact build (image label parity)."""
        response = client.get("/healthz")
        body = response.json()
        # All build-info fields are required by the Healthz schema; presence is
        # guaranteed by Pydantic. Verify they're populated as strings.
        for field in ("revision", "build_date", "repository"):
            assert field in body, f"healthz missing {field}"
            assert isinstance(body[field], str)
            assert body[field], f"healthz {field} is empty"
        # Repo URL points at the public GitHub project — useful for users
        # who curl healthz on an unfamiliar host.
        assert "github.com/strausmann/label-printer-hub" in body["repository"]

    def test_no_authentication_required(self, client: TestClient) -> None:
        """Container orchestrators probe healthz without credentials."""
        # No Authorization header — must still succeed
        response = client.get("/healthz")
        assert response.status_code == 200

    def test_does_not_expose_secrets(self, client: TestClient) -> None:
        """Healthz must never leak environment or config values."""
        response = client.get("/healthz")
        body_text = response.text.lower()
        forbidden_substrings = ["password", "token", "api_key", "secret", "snipeit", "grocy"]
        for needle in forbidden_substrings:
            assert needle not in body_text, f"healthz exposed '{needle}'"


class TestAppMetadata:
    def test_openapi_endpoint_available(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        # Per ADR 0011 we pin OpenAPI 3.1.0 explicitly; any drift is a regression.
        assert data["openapi"] == "3.1.0"

    def test_openapi_title(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        data = response.json()
        # Title can be "Label Printer Hub" or "label-printer-hub" — both fine
        title_lower = data["info"]["title"].lower()
        assert "label" in title_lower and "printer" in title_lower and "hub" in title_lower

    def test_swagger_ui_at_docs(self, client: TestClient) -> None:
        response = client.get("/docs")
        assert response.status_code == 200
        assert b"swagger" in response.content.lower()

    def test_redoc_at_redoc(self, client: TestClient) -> None:
        response = client.get("/redoc")
        assert response.status_code == 200
        assert b"redoc" in response.content.lower()


class TestHealthzModel:
    def test_response_model_is_frozen(self) -> None:
        """Healthz response model must be frozen — see code-review-patterns.md."""
        from app.main import Healthz
        from pydantic import ValidationError

        instance = Healthz(
            status="ok",
            version="1.2.3",
            revision="abc1234",
            build_date="2026-05-10T12:00:00Z",
            repository="https://github.com/strausmann/label-printer-hub",
        )
        with pytest.raises(ValidationError):
            instance.status = "tampered"  # type: ignore[misc]
