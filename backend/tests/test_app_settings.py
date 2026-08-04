import os

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.v1 import app_settings


class StubResponse:
    def __init__(self, payload=None, status_error: bool = False):
        self.payload = payload or {}
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            request = app_settings.httpx.Request("GET", "https://provider.test")
            response = app_settings.httpx.Response(401, request=request)
            raise app_settings.httpx.HTTPStatusError("invalid", request=request, response=response)

    def json(self):
        return self.payload


class StubClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, *args, **kwargs):
        return self.response


@pytest.mark.asyncio
async def test_validate_telegram_uses_get_me_without_sending(monkeypatch):
    response = StubResponse({"ok": True, "result": {"username": "test_bot"}})
    monkeypatch.setattr(app_settings.httpx, "AsyncClient", lambda **kwargs: StubClient(response))

    account_name = await app_settings._validate_provider("telegram", "123:test-token")

    assert account_name == "test_bot"


@pytest.mark.asyncio
async def test_validate_provider_rejects_invalid_credential(monkeypatch):
    response = StubResponse(status_error=True)
    monkeypatch.setattr(app_settings.httpx, "AsyncClient", lambda **kwargs: StubClient(response))

    with pytest.raises(HTTPException) as exc_info:
        await app_settings._validate_provider("gemini", "invalid-key")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_settings_update_saves_to_db_and_masks_secret(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
):
    async def accept_provider(provider, credential):
        return None

    secret = "test-gemini-secret"
    monkeypatch.setattr(app_settings, "_validate_provider", accept_provider)
    monkeypatch.setattr(app_settings.settings, "GEMINI_API_KEY", "")
    monkeypatch.setitem(os.environ, "GEMINI_API_KEY", "")

    response = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={"gemini_api_key": secret},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["gemini_api_key_set"] is True
    assert secret not in payload["gemini_api_key_masked"]
    assert payload["gemini_api_key_masked"] != secret
