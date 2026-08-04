"""Contract tests for canonical fixed and tiered price configuration JSON."""

import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pricing_type", "config"),
    [
        ("fixed", {"price": 3500, "vat": 0.08}),
        (
            "tiered",
            {
                "tiers": [
                    {"min": 0, "max": 50, "price": 1984},
                    {"min": 51, "max": None, "price": 2050},
                ],
                "vat": 0.08,
            },
        ),
    ],
)
async def test_price_config_round_trips_canonical_contract(
    client: AsyncClient,
    auth_headers: dict[str, str],
    pricing_type: str,
    config: dict,
):
    response = await client.post(
        "/api/v1/price-configs",
        headers=auth_headers,
        json={
            "config_name": f"Canonical {pricing_type}",
            "pricing_type": pricing_type,
            "config_json": json.dumps(config),
            "is_default": False,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["pricing_type"] == pricing_type
    assert json.loads(payload["config_json"]) == config


@pytest.mark.asyncio
async def test_price_config_rejects_legacy_tier_keys(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    response = await client.post(
        "/api/v1/price-configs",
        headers=auth_headers,
        json={
            "config_name": "Legacy config",
            "pricing_type": "tiered",
            "config_json": json.dumps(
                {
                    "tiers": [{"from": 0, "to": 50, "price": 1984}],
                    "vat": 0.08,
                }
            ),
            "is_default": False,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_price_config_rejects_legacy_fixed_price_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    response = await client.post(
        "/api/v1/price-configs",
        headers=auth_headers,
        json={
            "config_name": "Legacy fixed config",
            "pricing_type": "fixed",
            "config_json": json.dumps({"price_per_kwh": 3500, "vat": 0.08}),
            "is_default": False,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_price_config_rejects_percentage_form_vat(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    response = await client.post(
        "/api/v1/price-configs",
        headers=auth_headers,
        json={
            "config_name": "Invalid VAT config",
            "pricing_type": "fixed",
            "config_json": json.dumps({"price": 3500, "vat": 8}),
            "is_default": False,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pricing_type", "config"),
    [
        ("fixed", {"price": -1, "vat": 0.08}),
        ("fixed", {"price": 3500, "vat": 1.01}),
        (
            "tiered",
            {
                "tiers": [
                    {"min": 0, "max": 50, "price": 1984},
                    {"min": 52, "max": None, "price": 2050},
                ],
                "vat": 0.08,
            },
        ),
    ],
)
async def test_price_config_rejects_invalid_canonical_values(
    client: AsyncClient,
    auth_headers: dict[str, str],
    pricing_type: str,
    config: dict,
):
    response = await client.post(
        "/api/v1/price-configs",
        headers=auth_headers,
        json={
            "config_name": "Invalid canonical config",
            "pricing_type": pricing_type,
            "config_json": json.dumps(config),
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), float("-inf")])
async def test_price_config_rejects_non_finite_price_and_vat(
    client: AsyncClient,
    auth_headers: dict[str, str],
    invalid_number: float,
):
    for config in (
        {"price": invalid_number, "vat": 0.08},
        {"price": 3500, "vat": invalid_number},
    ):
        response = await client.post(
            "/api/v1/price-configs",
            headers=auth_headers,
            json={
                "config_name": "Non-finite config",
                "pricing_type": "fixed",
                "config_json": json.dumps(config),
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_price_config_update_validates_merged_type_and_json(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    create_response = await client.post(
        "/api/v1/price-configs",
        headers=auth_headers,
        json={
            "config_name": "Fixed config",
            "pricing_type": "fixed",
            "config_json": json.dumps({"price": 3500}),
        },
    )

    response = await client.patch(
        f"/api/v1/price-configs/{create_response.json()['id']}",
        headers=auth_headers,
        json={"pricing_type": "tiered"},
    )

    assert response.status_code == 422
