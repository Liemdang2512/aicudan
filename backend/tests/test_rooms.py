from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import rooms as rooms_api
from app.models.reading import MeterReading
from app.models.room import Room


def _room_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "STT",
            "ID Phòng",
            "Phòng",
            "Tên Đại Diện",
            "Chỉ Số Cũ",
            "Chỉ Số Mới",
            "",
            "",
            "",
            "",
            "SĐT",
            "Email",
        ]
    )
    sheet.append(
        [1, "A 102", "A 102", "Nguyễn Văn B", 200, 250, None, None, None, None, "0900000000", "b@example.com"]
    )
    sheet.append([2, None, None, "Thiếu phòng", 0, 10])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_import_rooms_maps_valid_row_and_reports_invalid_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
    db_session: AsyncSession,
):
    response = await client.post(
        f"/api/v1/buildings/{test_building.id}/rooms/import-excel",
        headers=auth_headers,
        files={
            "file": (
                "rooms.xlsx",
                _room_workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] == 1
    assert payload["updated"] == 0
    assert len(payload["errors"]) == 1

    room = (
        await db_session.execute(
            select(Room).where(
                Room.building_id == test_building.id,
                Room.room_number == "102",
            )
        )
    ).scalar_one()
    assert room.resident_name == "Nguyễn Văn B"
    assert room.initial_reading == 200

    reading = (
        await db_session.execute(select(MeterReading).where(MeterReading.room_id == room.id))
    ).scalar_one()
    assert reading.meter_value == 250
    assert reading.status == "approved"


@pytest.mark.asyncio
async def test_import_rooms_rejects_invalid_workbook(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
):
    response = await client.post(
        f"/api/v1/buildings/{test_building.id}/rooms/import-excel",
        headers=auth_headers,
        files={"file": ("rooms.xlsx", b"not-an-excel-file", "application/octet-stream")},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("rooms.xls", "application/vnd.ms-excel"),
        ("rooms.xlsx", "text/plain"),
    ],
)
async def test_import_rooms_rejects_invalid_extension_or_mime(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
    filename: str,
    content_type: str,
):
    response = await client.post(
        f"/api/v1/buildings/{test_building.id}/rooms/import-excel",
        headers=auth_headers,
        files={"file": (filename, _room_workbook(), content_type)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_import_rooms_rejects_file_over_compressed_size_limit(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
):
    monkeypatch.setattr(rooms_api, "MAX_EXCEL_FILE_SIZE", 8)
    response = await client.post(
        f"/api/v1/buildings/{test_building.id}/rooms/import-excel",
        headers=auth_headers,
        files={
            "file": (
                "rooms.xlsx",
                _room_workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_import_rooms_rejects_zip_bomb_by_uncompressed_size(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
):
    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * 1024)
    monkeypatch.setattr(rooms_api, "MAX_EXCEL_UNCOMPRESSED_SIZE", 100)

    response = await client.post(
        f"/api/v1/buildings/{test_building.id}/rooms/import-excel",
        headers=auth_headers,
        files={
            "file": (
                "rooms.xlsx",
                archive_bytes.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 400
    assert "giải nén quá lớn" in response.json()["detail"]


@pytest.mark.asyncio
async def test_room_metrics_use_only_approved_readings_but_history_keeps_all_statuses(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_building,
    test_room: Room,
):
    db_session.add_all(
        [
            MeterReading(
                room_id=test_room.id,
                reading_date=date(2025, 2, 1),
                meter_value=1100,
                status="approved",
            ),
            MeterReading(
                room_id=test_room.id,
                reading_date=date(2025, 2, 2),
                meter_value=9999,
                status="needs_review",
            ),
            MeterReading(
                room_id=test_room.id,
                reading_date=date(2025, 2, 3),
                meter_value=8888,
                status="rejected",
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/buildings/{test_building.id}/rooms",
        headers=auth_headers,
    )

    assert response.status_code == 200
    room = next(item for item in response.json() if item["id"] == test_room.id)
    assert room["previous_reading"] == test_room.initial_reading
    assert room["current_reading"] == 1100
    assert room["consumption"] == 100
    assert [item["status"] for item in room["readings_history"]] == [
        "rejected",
        "needs_review",
        "approved",
    ]
