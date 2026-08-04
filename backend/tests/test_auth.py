"""Authentication endpoint security regressions."""
import pytest

from app.api.v1 import auth as auth_api
from app.api.v1.auth import LOGIN_RATE_LIMIT_MAX_ATTEMPTS, reset_login_rate_limit


@pytest.fixture(autouse=True)
def clear_login_rate_limit():
    reset_login_rate_limit()
    yield
    reset_login_rate_limit()


@pytest.mark.asyncio
async def test_login_rate_limits_repeated_failures(client, test_user):
    payload = {"email": test_user.email, "password": "wrong-password"}

    for _ in range(LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        response = await client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 401

    response = await client.post("/api/v1/auth/login", json=payload)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_login_rate_limit_reset_hook_allows_retry(client, test_user):
    payload = {"email": test_user.email, "password": "wrong-password"}

    for _ in range(LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        await client.post("/api/v1/auth/login", json=payload)

    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 429

    reset_login_rate_limit()

    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limit_expires_without_manual_reset(client, test_user, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(auth_api.time, "monotonic", lambda: clock[0])
    payload = {"email": test_user.email, "password": "wrong-password"}

    for _ in range(LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
        await client.post("/api/v1/auth/login", json=payload)

    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 429

    clock[0] += auth_api.LOGIN_RATE_LIMIT_WINDOW_SECONDS + 1

    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401


@pytest.mark.asyncio
async def test_successful_login_clears_failure_count(client, test_user):
    failed_payload = {"email": test_user.email, "password": "wrong-password"}
    for _ in range(LOGIN_RATE_LIMIT_MAX_ATTEMPTS - 1):
        await client.post("/api/v1/auth/login", json=failed_payload)

    success = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "test123"},
    )
    assert success.status_code == 200

    assert (await client.post("/api/v1/auth/login", json=failed_payload)).status_code == 401
