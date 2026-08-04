"""Regression tests for the meter-reading review and upload-security contract."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import readings as readings_api
from app.models.batch_job import BatchJob
from app.models.reading import MeterReading
from app.models.room import Room
from app.services.ai_service import determine_status
from tests.conftest import test_async_session as async_session_factory


async def _run_image_job(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    test_room: Room,
    *,
    job_id: str,
    filename: str,
    room_hint: str | None,
    ai_result: dict,
) -> BatchJob:
    job = BatchJob(
        job_id=job_id,
        job_type="image_processing",
        status="queued",
        total_items=1,
    )
    db_session.add(job)
    await db_session.commit()

    async def fake_extract_meter_reading(_image_path: str) -> dict:
        return ai_result

    monkeypatch.setattr(readings_api, "async_session", async_session_factory)
    monkeypatch.setattr(
        readings_api.ai_service,
        "extract_meter_reading",
        fake_extract_meter_reading,
    )
    await readings_api.process_batch_images(
        job.job_id,
        [{"path": f"uploads/test/{filename}", "filename": filename, "room_number": room_hint}],
        test_room.building_id,
        "2025-01-31",
    )
    await db_session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_edit_and_approve_persists_atomically(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_reading: MeterReading,
):
    test_reading.status = "needs_review"
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/readings/{test_reading.id}",
        headers=auth_headers,
        json={"meter_value": 1175, "status": "approved", "notes": "Manual review"},
    )

    assert response.status_code == 200
    assert response.json()["meter_value"] == 1175
    assert response.json()["status"] == "approved"

    reading_id = test_reading.id
    db_session.expire_all()
    persisted = await db_session.get(MeterReading, reading_id)
    assert persisted is not None
    assert persisted.meter_value == 1175
    assert persisted.status == "approved"
    assert persisted.notes == "Manual review"


def test_high_confidence_still_requires_manual_review():
    assert determine_status(0.99) == "needs_review"


@pytest.mark.asyncio
async def test_unmatched_image_is_never_assigned_to_an_arbitrary_room(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_room: Room,
):
    job = BatchJob(
        job_id="job_unmatched_contract",
        job_type="image_processing",
        status="queued",
        total_items=1,
    )
    db_session.add(job)
    await db_session.commit()

    async def fake_extract_meter_reading(_image_path: str) -> dict:
        return {
            "meter_reading": 1234,
            "confidence": 0.99,
            "room_number": None,
            "meter_type": "electric",
            "notes": "No room label detected",
        }

    monkeypatch.setattr(readings_api, "async_session", async_session_factory)
    monkeypatch.setattr(
        readings_api.ai_service,
        "extract_meter_reading",
        fake_extract_meter_reading,
    )

    await readings_api.process_batch_images(
        job_id=job.job_id,
        image_paths=[
            {
                "path": "uploads/test/unmatched.jpg",
                "filename": "unmatched.jpg",
                "room_number": None,
            }
        ],
        building_id=test_room.building_id,
        reading_date="2025-01-31",
    )

    result = await db_session.execute(
        select(MeterReading).where(MeterReading.batch_job_id == job.job_id)
    )
    created_readings = result.scalars().all()

    assert created_readings == []

    status_response = await client.get(
        f"/api/v1/readings/batch-status/{job.job_id}",
        headers=auth_headers,
    )
    assert status_response.status_code == 200
    staged = status_response.json()["results"][0]
    assert staged["id"] is None
    assert staged["staged_id"]
    assert staged["room_id"] is None
    assert staged["meter_value"] == 1234
    assert staged["status"] == "needs_review"

    approve_response = await client.patch(
        f"/api/v1/readings/staged/{staged['staged_id']}",
        headers=auth_headers,
        json={
            "room_id": test_room.id,
            "meter_value": 1235,
            "meter_type": "electric",
            "status": "approved",
            "notes": "Assigned and approved manually",
        },
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["room_id"] == test_room.id
    assert approve_response.json()["meter_value"] == 1235
    assert approve_response.json()["status"] == "approved"

    refreshed_status = await client.get(
        f"/api/v1/readings/batch-status/{job.job_id}",
        headers=auth_headers,
    )
    assert refreshed_status.status_code == 200
    results = refreshed_status.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == approve_response.json()["id"]
    assert results[0]["staged_id"] is None


@pytest.mark.asyncio
async def test_matched_high_confidence_reading_still_needs_review(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    test_room: Room,
):
    job = BatchJob(
        job_id="job_matched_manual_review",
        job_type="image_processing",
        status="queued",
        total_items=1,
    )
    db_session.add(job)
    await db_session.commit()

    async def fake_extract_meter_reading(_image_path: str) -> dict:
        return {
            "meter_reading": 1300,
            "confidence": 0.99,
            "room_number": test_room.room_number,
            "meter_type": "electric",
            "notes": "Clear image",
        }

    monkeypatch.setattr(readings_api, "async_session", async_session_factory)
    monkeypatch.setattr(
        readings_api.ai_service,
        "extract_meter_reading",
        fake_extract_meter_reading,
    )

    await readings_api.process_batch_images(
        job_id=job.job_id,
        image_paths=[
            {
                "path": "uploads/test/matched.jpg",
                "filename": "101.jpg",
                "room_number": test_room.room_number,
            }
        ],
        building_id=test_room.building_id,
        reading_date="2025-01-31",
    )

    result = await db_session.execute(
        select(MeterReading).where(MeterReading.batch_job_id == job.job_id)
    )
    reading = result.scalar_one()
    assert reading.room_id == test_room.id
    assert reading.status == "needs_review"


@pytest.mark.asyncio
async def test_filename_room_101_never_substring_matches_room_1101(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    test_room: Room,
):
    room_1101 = Room(
        building_id=test_room.building_id,
        room_number="1101",
        initial_reading=0,
    )
    db_session.add(room_1101)
    await db_session.commit()

    job = await _run_image_job(
        monkeypatch,
        db_session,
        test_room,
        job_id="job_exact_1101",
        filename="1101.jpg",
        room_hint="1101",
        ai_result={
            "meter_reading": 200,
            "confidence": 0.9,
            "room_number": None,
            "meter_type": "electric",
        },
    )

    reading = (
        await db_session.execute(
            select(MeterReading).where(MeterReading.batch_job_id == job.job_id)
        )
    ).scalar_one()
    assert reading.room_id == room_1101.id


@pytest.mark.asyncio
async def test_ai_room_text_without_identifier_stays_staged(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    test_room: Room,
):
    job = await _run_image_job(
        monkeypatch,
        db_session,
        test_room,
        job_id="job_room_text_no_digits",
        filename="unknown.jpg",
        room_hint=None,
        ai_result={
            "meter_reading": 200,
            "confidence": 0.9,
            "room_number": "không đọc được phòng",
            "meter_type": "electric",
        },
    )

    readings = (
        await db_session.execute(
            select(MeterReading).where(MeterReading.batch_job_id == job.job_id)
        )
    ).scalars().all()
    assert readings == []
    assert len(json.loads(job.result_data)["unmatched"]) == 1


@pytest.mark.asyncio
async def test_duplicate_canonical_room_match_stays_staged(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    test_room: Room,
):
    db_session.add(
        Room(
            building_id=test_room.building_id,
            room_number="P101",
            initial_reading=0,
        )
    )
    await db_session.commit()

    job = await _run_image_job(
        monkeypatch,
        db_session,
        test_room,
        job_id="job_ambiguous_101",
        filename="101.jpg",
        room_hint="101",
        ai_result={
            "meter_reading": 200,
            "confidence": 0.9,
            "room_number": "P101",
            "meter_type": "electric",
        },
    )

    readings = (
        await db_session.execute(
            select(MeterReading).where(MeterReading.batch_job_id == job.job_id)
        )
    ).scalars().all()
    assert readings == []
    assert len(json.loads(job.result_data)["unmatched"]) == 1


@pytest.mark.asyncio
async def test_missing_ai_meter_value_is_staged_and_counted_failed_once(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    test_room: Room,
):
    job = await _run_image_job(
        monkeypatch,
        db_session,
        test_room,
        job_id="job_missing_meter_value",
        filename="101.jpg",
        room_hint="101",
        ai_result={
            "meter_reading": None,
            "confidence": 0.8,
            "room_number": "101",
            "meter_type": "electric",
            "notes": "AI response missing value",
        },
    )

    readings = (
        await db_session.execute(
            select(MeterReading).where(MeterReading.batch_job_id == job.job_id)
        )
    ).scalars().all()
    staged = json.loads(job.result_data)["unmatched"]
    assert readings == []
    assert job.failed_items == 1
    assert staged[0]["meter_value"] is None
    assert staged[0]["status"] == "needs_review"


@pytest.mark.asyncio
async def test_water_result_with_room_match_stays_staged_and_requires_electric_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_room: Room,
):
    job = BatchJob(job_id="job_water", job_type="image_processing", status="queued", total_items=1)
    db_session.add(job)
    await db_session.commit()

    async def fake_extract_meter_reading(_image_path: str) -> dict:
        return {"meter_reading": 42, "confidence": 0.99, "room_number": test_room.room_number, "meter_type": "water", "notes": "m3"}

    monkeypatch.setattr(readings_api, "async_session", async_session_factory)
    monkeypatch.setattr(readings_api.ai_service, "extract_meter_reading", fake_extract_meter_reading)
    await readings_api.process_batch_images(job.job_id, [{"path": "uploads/test/water.jpg", "filename": "101.jpg", "room_number": "101"}], test_room.building_id, "2025-01-31")

    result = await db_session.execute(select(MeterReading).where(MeterReading.batch_job_id == job.job_id))
    assert result.scalars().all() == []
    status = await client.get(f"/api/v1/readings/batch-status/{job.job_id}", headers=auth_headers)
    staged = status.json()["results"][0]
    assert staged["meter_type"] == "water"
    rejected = await client.patch(f"/api/v1/readings/staged/{staged['staged_id']}", headers=auth_headers, json={"room_id": test_room.id, "meter_value": 42, "status": "approved"})
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_list_readings_is_owner_scoped_and_returns_ui_fields(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
    test_reading: MeterReading,
    second_reading: MeterReading,
):
    response = await client.get("/api/v1/readings", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [test_reading.id]
    assert payload[0]["room_number"] == "101"
    assert payload[0]["building_name"] == test_building.name
    assert payload[0]["previous_reading"] == 1000
    assert payload[0]["current_reading"] == 1150
    assert payload[0]["consumption"] == 150


@pytest.mark.asyncio
async def test_list_readings_applies_building_month_and_status_filters(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_building,
    test_room: Room,
    test_reading: MeterReading,
):
    db_session.add_all(
        [
            MeterReading(
                room_id=test_room.id,
                reading_date=date(2025, 1, 22),
                meter_value=1200,
                status="needs_review",
            ),
            MeterReading(
                room_id=test_room.id,
                reading_date=date(2025, 2, 15),
                meter_value=1300,
                status="approved",
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/readings",
        headers=auth_headers,
        params={
            "building_id": test_building.id,
            "month": "2025-01",
            "status": "approved",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [test_reading.id]


@pytest.mark.asyncio
async def test_list_readings_foreign_filters_never_leak_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_building,
    second_room: Room,
    second_reading: MeterReading,
):
    by_building = await client.get(
        "/api/v1/readings",
        headers=auth_headers,
        params={"building_id": second_building.id},
    )
    by_room = await client.get(
        "/api/v1/readings",
        headers=auth_headers,
        params={"room_id": second_room.id},
    )

    assert by_building.status_code == 200
    assert by_building.json() == []
    assert by_room.status_code == 200
    assert by_room.json() == []


@pytest.mark.asyncio
async def test_batch_upload_rejects_path_traversal_date_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
):
    monkeypatch.setattr(readings_api.settings, "UPLOAD_DIR", str(tmp_path))

    response = await client.post(
        "/api/v1/readings/batch-upload",
        headers=auth_headers,
        data={"building_id": test_building.id, "reading_date": "../../outside"},
        files={"files": ("101.jpg", b"image", "image/jpeg")},
    )

    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_batch_upload_rejects_building_without_active_rooms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_building,
    test_room: Room,
):
    test_room.is_active = False
    await db_session.commit()
    monkeypatch.setattr(readings_api.settings, "UPLOAD_DIR", str(tmp_path))

    response = await client.post(
        "/api/v1/readings/batch-upload",
        headers=auth_headers,
        data={"building_id": test_building.id, "reading_date": "2025-02-03"},
        files={"files": ("101.jpg", b"image", "image/jpeg")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Tòa nhà chưa có phòng đang hoạt động"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_batch_upload_uses_server_uuid_filename_under_upload_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
    test_room: Room,
):
    monkeypatch.setattr(readings_api.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(readings_api, "async_session", async_session_factory)

    async def fake_extract_meter_reading(_image_path: str) -> dict:
        return {
            "meter_reading": 10,
            "confidence": 0.9,
            "room_number": None,
            "meter_type": "electric",
        }

    monkeypatch.setattr(readings_api.ai_service, "extract_meter_reading", fake_extract_meter_reading)
    response = await client.post(
        "/api/v1/readings/batch-upload",
        headers=auth_headers,
        data={"building_id": test_building.id, "reading_date": "2025-02-03"},
        files={"files": ("../../101.jpg", b"image", "image/jpeg")},
    )

    assert response.status_code == 200
    saved_files = list((tmp_path / "20250203").iterdir())
    assert len(saved_files) == 1
    assert re.fullmatch(r"[0-9a-f]{32}\.jpg", saved_files[0].name)
    assert saved_files[0].resolve().is_relative_to(tmp_path.resolve())


@pytest.mark.asyncio
async def test_batch_upload_stops_at_size_limit_and_removes_partial_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_building,
    test_room: Room,
):
    monkeypatch.setattr(readings_api.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(readings_api.settings, "MAX_FILE_SIZE", 8)

    response = await client.post(
        "/api/v1/readings/batch-upload",
        headers=auth_headers,
        data={"building_id": test_building.id, "reading_date": "2025-02-03"},
        files={"files": ("101.jpg", b"123456789", "image/jpeg")},
    )

    assert response.status_code == 400
    assert list((tmp_path / "20250203").iterdir()) == []


@pytest.mark.asyncio
async def test_batch_status_fails_closed_for_legacy_job_without_owner_context(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
):
    db_session.add(
        BatchJob(
            job_id="job_legacy_no_owner",
            job_type="image_processing",
            status="completed",
            total_items=1,
            result_data=json.dumps({"unmatched": []}),
        )
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/readings/batch-status/job_legacy_no_owner",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reading_image_requires_auth_and_owner_and_hides_filesystem_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_reading: MeterReading,
):
    monkeypatch.setattr(readings_api.settings, "UPLOAD_DIR", str(tmp_path))
    image_file = tmp_path / "20250115" / "safe.jpg"
    image_file.parent.mkdir()
    image_file.write_bytes(b"private-image")
    test_reading.image_path = str(image_file)
    await db_session.commit()

    reading_response = await client.get("/api/v1/readings", headers=auth_headers)
    protected_path = reading_response.json()[0]["image_path"]
    assert protected_path == f"/readings/{test_reading.id}/image"
    assert str(tmp_path) not in protected_path

    unauthenticated = await client.get(f"/api/v1{protected_path}")
    foreign_owner = await client.get(
        f"/api/v1{protected_path}",
        headers=second_auth_headers,
    )
    owner = await client.get(f"/api/v1{protected_path}", headers=auth_headers)

    assert unauthenticated.status_code == 401
    assert foreign_owner.status_code == 404
    assert owner.status_code == 200
    assert owner.content == b"private-image"

    public_static = await client.get(f"/uploads/{image_file.parent.name}/{image_file.name}")
    assert public_static.status_code == 404


@pytest.mark.asyncio
async def test_staged_image_is_scoped_to_job_building_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
    db_session: AsyncSession,
    second_building,
):
    monkeypatch.setattr(readings_api.settings, "UPLOAD_DIR", str(tmp_path))
    image_file = tmp_path / "20250115" / "staged.jpg"
    image_file.parent.mkdir()
    image_file.write_bytes(b"staged-private-image")
    staged_id = "staged_second_owner"
    db_session.add(
        BatchJob(
            job_id="job_staged_second_owner",
            job_type="image_processing",
            status="completed",
            total_items=1,
            result_data=json.dumps(
                {
                    "building_id": second_building.id,
                    "reading_date": "2025-01-15",
                    "unmatched": [
                        {
                            "staged_id": staged_id,
                            "reading_date": "2025-01-15",
                            "meter_value": 10,
                            "meter_type": "electric",
                            "image_path": str(image_file),
                            "confidence_score": 0.5,
                            "status": "needs_review",
                            "batch_job_id": "job_staged_second_owner",
                        }
                    ],
                }
            ),
        )
    )
    await db_session.commit()

    foreign_owner = await client.get(
        f"/api/v1/readings/staged/{staged_id}/image",
        headers=auth_headers,
    )
    owner = await client.get(
        f"/api/v1/readings/staged/{staged_id}/image",
        headers=second_auth_headers,
    )

    assert foreign_owner.status_code == 404
    assert owner.status_code == 200
    assert owner.content == b"staged-private-image"


@pytest.mark.asyncio
async def test_reading_list_exposes_bounded_pagination(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_room: Room,
    test_reading: MeterReading,
):
    db_session.add(
        MeterReading(
            room_id=test_room.id,
            reading_date=date(2025, 2, 15),
            meter_value=1200,
            status="approved",
        )
    )
    await db_session.commit()

    first_page = await client.get(
        "/api/v1/readings",
        headers=auth_headers,
        params={"offset": 0, "limit": 1},
    )
    second_page = await client.get(
        "/api/v1/readings",
        headers=auth_headers,
        params={"offset": 1, "limit": 1},
    )
    invalid = await client.get(
        "/api/v1/readings",
        headers=auth_headers,
        params={"limit": 0},
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert len(first_page.json()) == len(second_page.json()) == 1
    assert first_page.json()[0]["id"] != second_page.json()[0]["id"]
    assert invalid.status_code == 422
