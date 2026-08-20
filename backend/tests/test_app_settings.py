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


@pytest.mark.asyncio
async def test_telegram_settings_are_isolated_between_accounts(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
    monkeypatch,
):
    async def accept_provider(provider, credential):
        return None

    monkeypatch.setattr(app_settings, "_validate_provider", accept_provider)
    monkeypatch.setattr(app_settings.settings, "SERVER_URL", "")
    monkeypatch.setattr(app_settings.settings, "TELEGRAM_BOT_TOKEN", "legacy-manager-token")
    monkeypatch.setattr(app_settings.settings, "TELEGRAM_KTV_BOT_TOKEN", "legacy-ktv-token")
    monkeypatch.setattr(app_settings.settings, "TELEGRAM_KTV_PASSWORD", "legacy-password")
    monkeypatch.setattr(app_settings.settings, "MANAGER_TELEGRAM_CHAT_ID", "legacy-chat")

    first = await client.patch(
        "/api/v1/settings",
        headers=auth_headers,
        json={
            "telegram_bot_token": "1111:first-manager-aaaa",
            "telegram_ktv_bot_token": "2222:first-ktv-bbbb",
            "telegram_ktv_password": "first-password",
            "manager_telegram_chat_id": "11111111",
        },
    )
    assert first.status_code == 200

    second = await client.get("/api/v1/settings", headers=second_auth_headers)
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["telegram_bot_token_set"] is False
    assert second_payload["telegram_bot_token_masked"] == ""
    assert second_payload["telegram_ktv_bot_token_set"] is False
    assert second_payload["telegram_ktv_bot_token_masked"] == ""
    assert second_payload["telegram_ktv_password_set"] is False
    assert second_payload["manager_telegram_chat_id"] == ""

    assert app_settings.settings.TELEGRAM_BOT_TOKEN == "legacy-manager-token"
    assert app_settings.settings.TELEGRAM_KTV_BOT_TOKEN == "legacy-ktv-token"
    assert app_settings.settings.TELEGRAM_KTV_PASSWORD == "legacy-password"
    assert app_settings.settings.MANAGER_TELEGRAM_CHAT_ID == "legacy-chat"
