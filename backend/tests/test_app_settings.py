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


def test_update_env_file_uses_stable_path_and_private_permissions(tmp_path, monkeypatch):
    env_path = tmp_path / "backend" / ".env"
    env_path.parent.mkdir()
    env_path.write_text("UNCHANGED=value\nGEMINI_API_KEY=old\n", encoding="utf-8")
    os.chmod(env_path, 0o644)
    monkeypatch.setattr(app_settings, "ENV_PATH", env_path)

    app_settings._update_env_file("GEMINI_API_KEY", "new-secret")

    assert env_path.read_text(encoding="utf-8") == (
        "UNCHANGED=value\nGEMINI_API_KEY=new-secret\n"
    )
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_update_env_file_rejects_newline_injection(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(app_settings, "ENV_PATH", env_path)

    with pytest.raises(HTTPException) as exc_info:
        app_settings._update_env_file("GEMINI_API_KEY", "secret\nADMIN_PASSWORD=owned")

    assert exc_info.value.status_code == 422
    assert not env_path.exists()


@pytest.mark.asyncio
async def test_settings_update_reports_multi_worker_limitation_without_secret(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path,
    monkeypatch,
):
    async def accept_provider(provider, credential):
        return None

    env_path = tmp_path / ".env"
    secret = "test-gemini-secret"
    monkeypatch.setattr(app_settings, "ENV_PATH", env_path)
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
    assert "worker" in payload["runtime_sync_notice"]
    assert secret not in payload["runtime_sync_notice"]
    assert payload["gemini_api_key_masked"] != secret
    assert env_path.stat().st_mode & 0o777 == 0o600
