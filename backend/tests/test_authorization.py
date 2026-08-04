"""Object-level authorization regressions for resources owned through buildings."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.user import User


@pytest_asyncio.fixture
async def non_admin_headers(db_session: AsyncSession) -> dict[str, str]:
    user = User(
        email="resident@test.com",
        password_hash=hash_password("test123"),
        full_name="Resident",
        role="resident",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_owner_cannot_read_another_owners_room(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_room,
):
    response = await client.get(
        f"/api/v1/rooms/{second_room.id}",
        headers=auth_headers,
    )

    assert response.status_code in {403, 404}


@pytest.mark.asyncio
async def test_owner_cannot_edit_or_delete_another_owners_room(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_room,
):
    update_response = await client.patch(
        f"/api/v1/rooms/{second_room.id}",
        headers=auth_headers,
        json={"resident_name": "Không được phép"},
    )
    delete_response = await client.delete(
        f"/api/v1/rooms/{second_room.id}",
        headers=auth_headers,
    )

    assert update_response.status_code in {403, 404}
    assert delete_response.status_code in {403, 404}


@pytest.mark.asyncio
async def test_owner_cannot_edit_another_owners_reading(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_reading,
):
    response = await client.patch(
        f"/api/v1/readings/{second_reading.id}",
        headers=auth_headers,
        json={"meter_value": 9999, "status": "approved"},
    )

    assert response.status_code in {403, 404}


@pytest.mark.asyncio
async def test_owner_cannot_read_another_owners_invoice(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_invoice,
):
    response = await client.get(
        f"/api/v1/invoices/{second_invoice.id}",
        headers=auth_headers,
    )

    assert response.status_code in {403, 404}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/api/v1/settings", None),
        ("PATCH", "/api/v1/settings", {}),
        ("POST", "/api/v1/settings/validate", {"provider": "gemini"}),
        ("GET", "/api/v1/price-configs", None),
        (
            "POST",
            "/api/v1/price-configs",
            {
                "config_name": "Forbidden",
                "pricing_type": "fixed",
                "config_json": '{"price": 3500}',
            },
        ),
        ("PATCH", "/api/v1/price-configs/1", {}),
        ("DELETE", "/api/v1/price-configs/1", None),
    ],
)
async def test_system_resources_require_admin(
    client: AsyncClient,
    non_admin_headers: dict[str, str],
    method: str,
    path: str,
    json_body: dict | None,
):
    response = await client.request(
        method,
        path,
        headers=non_admin_headers,
        json=json_body,
    )

    assert response.status_code == 403
