# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A lookup request names its integration and its identifier with a bound (#164, #211).

The identifier is sent on to an upstream service (as a path segment), and the sheet path
already refused one above 120 characters; the print routes had no bound at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.integrations.registry import IntegrationRegistry
from app.schemas.print_request import LOOKUP_IDENTIFIER_MAX, PrintLookupRequest
from pydantic import ValidationError

from tests.integration.test_batch_lookup_errors import (
    _Plugin,
    batch_env,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.asyncio


def _body(identifier: str, app_name: str = "snipeit") -> dict[str, Any]:
    return {
        "items": [
            {"content_type": "qr_two_lines", "lookup": {"app": app_name, "identifier": identifier}}
        ]
    }


async def test_identifier_over_120_is_422(batch_env) -> None:  # noqa: F811
    client, queue, _ = batch_env
    IntegrationRegistry.register(_Plugin("snipeit", None))  # type: ignore[arg-type]
    response = await client.post("/api/v1/print/p/batch", json=_body("9" * 121))
    assert response.status_code == 422, response.text
    assert "identifier" in response.text
    queue.enqueue_batch.assert_not_awaited()


async def test_identifier_of_120_reaches_the_lookup(batch_env) -> None:  # noqa: F811
    client, queue, _ = batch_env
    IntegrationRegistry.register(_Plugin("snipeit", None))  # type: ignore[arg-type]
    response = await client.post("/api/v1/print/p/batch", json=_body("9" * 120))
    assert response.status_code == 202, response.text
    queue.enqueue_batch.assert_awaited_once()


async def test_app_over_32_is_422(batch_env) -> None:  # noqa: F811
    client, queue, _ = batch_env
    response = await client.post("/api/v1/print/p/batch", json=_body("1", "a" * 33))
    assert response.status_code == 422, response.text
    # The field bound answers, not the unknown-integration check further down.
    assert "integration_unknown_app" not in response.text
    queue.enqueue_batch.assert_not_awaited()


async def test_unknown_app_keeps_todays_answer(batch_env) -> None:  # noqa: F811
    client, _queue, _ = batch_env
    response = await client.post("/api/v1/print/p/batch", json=_body("1", "nosuchapp"))
    # Not the field bound's answer: the unchanged "unknown integration" error.
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "integration_unknown_app"


async def test_the_bound_is_120() -> None:
    assert LOOKUP_IDENTIFIER_MAX == 120
    PrintLookupRequest(app="x", identifier="a" * 120)
    with pytest.raises(ValidationError):
        PrintLookupRequest(app="x", identifier="a" * 121)


async def test_get_lookup_entity_id_is_bounded(api_client_with_seed) -> None:
    """The GET lookup takes the identifier as a path segment: same bound as the body field."""
    from unittest.mock import AsyncMock, patch

    from tests.integration.api.test_lookup_auth import _LABEL, _insert_key

    key = await _insert_key(["read"])
    headers = {"X-Label-Hub-Key": key}
    with patch(
        "app.api.routes.lookup._lookup_service.lookup", new=AsyncMock(return_value=_LABEL)
    ) as lookup:
        over = await api_client_with_seed.get(
            f"/api/v1/lookup/snipeit/{'9' * (LOOKUP_IDENTIFIER_MAX + 1)}", headers=headers
        )
        assert over.status_code == 422, over.text
        lookup.assert_not_awaited()
        at = await api_client_with_seed.get(
            f"/api/v1/lookup/snipeit/{'9' * LOOKUP_IDENTIFIER_MAX}", headers=headers
        )
        assert at.status_code == 200, at.text
