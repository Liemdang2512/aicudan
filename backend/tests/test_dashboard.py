"""Dashboard regression tests for month scoping and owner isolation."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading import MeterReading
from app.models.room import Room


def _previous_month(day: date) -> date:
    return date(day.year - 1, 12, 15) if day.month == 1 else date(day.year, day.month - 1, 15)


@pytest.mark.asyncio
async def test_dashboard_reading_counts_only_include_current_month(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_room: Room,
):
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    db_session.add_all(
        [
            MeterReading(
                room_id=test_room.id,
                reading_date=today.replace(day=1),
                meter_value=1100,
                status="approved",
            ),
            MeterReading(
                room_id=test_room.id,
                reading_date=today,
                meter_value=1200,
                status="needs_review",
            ),
            MeterReading(
                room_id=test_room.id,
                reading_date=_previous_month(today),
                meter_value=1000,
                status="approved",
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/v1/dashboard/stats", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["current_month"] == today.strftime("%Y-%m")
    assert response.json()["readings_done"] == 0
    assert response.json()["readings_pending"] == 1


@pytest.mark.asyncio
async def test_dashboard_rejects_foreign_building_filter(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_building,
):
    response = await client.get(
        "/api/v1/dashboard/stats",
        headers=auth_headers,
        params={"building_id": second_building.id},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_partitions_distinct_rooms_and_counts_no_reading_as_pending(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_building,
    test_room: Room,
):
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    no_reading_room = Room(
        building_id=test_building.id,
        room_number="102",
        initial_reading=0,
    )
    rejected_room = Room(
        building_id=test_building.id,
        room_number="103",
        initial_reading=0,
    )
    db_session.add_all([no_reading_room, rejected_room])
    await db_session.flush()
    db_session.add_all(
        [
            MeterReading(
                room_id=test_room.id,
                reading_date=today.replace(day=1),
                meter_value=1100,
                status="approved",
            ),
            MeterReading(
                room_id=test_room.id,
                reading_date=today,
                meter_value=1200,
                status="approved",
            ),
            MeterReading(
                room_id=rejected_room.id,
                reading_date=today,
                meter_value=10,
                status="rejected",
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/v1/dashboard/stats", headers=auth_headers)
    payload = response.json()

    assert response.status_code == 200
    assert payload["total_rooms"] == 3
    assert payload["readings_done"] == 1
    assert payload["readings_pending"] == 1
    assert payload["readings_error"] == 1
    assert (
        payload["readings_done"]
        + payload["readings_pending"]
        + payload["readings_error"]
        == payload["total_rooms"]
    )
