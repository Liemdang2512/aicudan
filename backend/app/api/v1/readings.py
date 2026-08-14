import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import async_session, get_db
from app.models.batch_job import BatchJob
from app.models.building import Building
from app.models.reading import MeterReading
from app.models.room import Room
from app.models.user import User
from app.schemas.reading import (
    BatchStatusResponse,
    BatchUploadResponse,
    ReadingResponse,
    ReadingUpdate,
    StagedReadingApproval,
    StagedReadingResponse,
)
from app.services.ai_service import ai_service, determine_status
from app.utils.filename_parser import extract_room_number

router = APIRouter(prefix="/readings", tags=["Meter Readings"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
UPLOAD_CHUNK_SIZE = 64 * 1024


def _load_job_data(job: BatchJob) -> dict:
    if not job.result_data:
        return {"unmatched": []}
    try:
        data = json.loads(job.result_data)
    except (TypeError, json.JSONDecodeError):
        return {"unmatched": []}
    if not isinstance(data, dict):
        return {"unmatched": []}
    data.setdefault("unmatched", [])
    return data


def _store_job_data(job: BatchJob, data: dict) -> None:
    job.result_data = json.dumps(data, ensure_ascii=False)


def _parse_reading_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Ngày ghi phải đúng định dạng YYYY-MM-DD",
        ) from exc


def _canonical_room_identifier(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _strip_room_prefix(value: str) -> str:
    """Strip leading non-digit prefix from a room identifier.

    Handles AI-detected labels like 'B 1822', 'P.101', 'A3457' where the
    DB may store only the numeric portion ('1822', '101', '3457').
    """
    stripped = re.sub(r"^[A-Za-z.\-\s]+", "", value).strip()
    return stripped if stripped != value.strip() else ""


def _room_aliases(room_number: str) -> set[str]:
    aliases = {_canonical_room_identifier(room_number)}
    parsed = extract_room_number(f"{room_number}.jpg")
    if parsed:
        aliases.add(_canonical_room_identifier(parsed))
    # If room stored with prefix (e.g. "B 1822"), also expose the numeric part
    numeric = _strip_room_prefix(room_number)
    if numeric:
        aliases.add(_canonical_room_identifier(numeric))
    return aliases


def _match_unique_room(
    rooms: list[Room],
    filename_room: object | None,
    ai_room: object | None,
) -> Room | None:
    identifiers: set[str] = set()
    if filename_room:
        identifiers.add(_canonical_room_identifier(str(filename_room)))
        numeric = _strip_room_prefix(str(filename_room))
        if numeric:
            identifiers.add(_canonical_room_identifier(numeric))
    if ai_room:
        identifiers.add(_canonical_room_identifier(ai_room))
        # Also add numeric-only part so "B 1822" matches room stored as "1822"
        numeric = _strip_room_prefix(str(ai_room))
        if numeric:
            identifiers.add(_canonical_room_identifier(numeric))
        parsed_ai_room = extract_room_number(f"{ai_room}.jpg")
        if parsed_ai_room:
            identifiers.add(_canonical_room_identifier(parsed_ai_room))

    matched = {
        room.id: room
        for room in rooms
        if identifiers.intersection(_room_aliases(room.room_number))
    }
    return next(iter(matched.values())) if len(matched) == 1 else None


def _protected_image_url(reading_id: int) -> str:
    return f"/readings/{reading_id}/image"


def _protected_staged_image_url(staged_id: str) -> str:
    return f"/readings/staged/{staged_id}/image"


def _resolve_upload_file(image_path: str | None) -> Path:
    if not image_path:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")

    upload_root = settings.upload_path.resolve()
    candidate = Path(image_path).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại") from exc

    if candidate.suffix.lower() not in ALLOWED_EXTENSIONS or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")
    return candidate


async def _save_upload_limited(upload: UploadFile, destination: Path) -> bool:
    total_size = 0
    try:
        with destination.open("xb") as output:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > settings.MAX_FILE_SIZE:
                    return False
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    return total_size > 0


async def process_batch_images(job_id: str, image_paths: list[dict], building_id: int, reading_date: str):
    """Background task: process batch images with AI"""
    async with async_session() as db:
        try:
            # Update job status
            result = await db.execute(select(BatchJob).where(BatchJob.job_id == job_id))
            job = result.scalar_one()
            job.status = "processing"
            job_data = _load_job_data(job)
            job_data["building_id"] = building_id
            job_data["reading_date"] = reading_date
            _store_job_data(job, job_data)
            await db.commit()

            # Fetch all rooms once before the loop — avoids N queries per image
            all_rooms_res = await db.execute(
                select(Room).where(Room.building_id == building_id, Room.is_active == True)
            )
            building_rooms = all_rooms_res.scalars().all()

            for i, item in enumerate(image_paths):
                file_path = item["path"]
                room_hint = item.get("room_number")

                try:
                    # AI processing
                    ai_result = await ai_service.extract_meter_reading(file_path)

                    meter_value = ai_result.get("meter_reading")
                    confidence = ai_result.get("confidence", 0.0)
                    ai_room_number = ai_result.get("room_number")
                    meter_type = ai_result.get("meter_type") or "unknown"

                    matched_room = _match_unique_room(
                        building_rooms,
                        room_hint,
                        ai_room_number,
                    )
                    parsed_date = _parse_reading_date(reading_date)

                    if matched_room and meter_type == "electric" and meter_value is not None:
                        status = determine_status(confidence)
                        notes = ai_result.get("notes", "")

                        reading = MeterReading(
                            room_id=matched_room.id,
                            reading_date=parsed_date,
                            meter_value=int(meter_value),
                            image_path=file_path,
                            confidence_score=confidence,
                            status=status,
                            notes=notes,
                            batch_job_id=job_id,
                        )
                        db.add(reading)
                    else:
                        notes = ai_result.get("notes", "")
                        if meter_value is None:
                            confidence = 0.0
                            job.failed_items += 1
                            notes = f"Cần kiểm tra: {notes or 'AI không đọc được chỉ số'}"
                        elif meter_type != "electric":
                            type_note = (
                                "Ảnh không phải đồng hồ điện"
                                if meter_type == "water"
                                else "Không xác định được loại đồng hồ"
                            )
                            notes = f"{type_note}. {notes}".strip()
                        job_data = _load_job_data(job)
                        job_data["unmatched"].append(
                            {
                                "staged_id": uuid.uuid4().hex,
                                "reading_date": parsed_date.isoformat(),
                                "meter_value": int(meter_value) if meter_value is not None else None,
                                "meter_type": meter_type,
                                "image_path": file_path,
                                "confidence_score": confidence,
                                "status": "needs_review",
                                "notes": notes or "Không nhận diện được phòng; cần chọn phòng thủ công",
                                "batch_job_id": job_id,
                            }
                        )
                        _store_job_data(job, job_data)

                    job.processed_items = i + 1
                    await db.commit()

                except Exception as e:
                    logger.exception("Error processing uploaded image %s: %s", file_path, e)
                    job.processed_items = i + 1
                    job.failed_items += 1
                    await db.commit()

            # Mark job as completed
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            result = await db.execute(select(BatchJob).where(BatchJob.job_id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                await db.commit()


@router.post("/batch-upload", response_model=BatchUploadResponse)
async def batch_upload(
    background_tasks: BackgroundTasks,
    building_id: int = Form(...),
    reading_date: str = Form(...),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    parsed_reading_date = _parse_reading_date(reading_date)

    # Validate building
    bld_result = await db.execute(
        select(Building).where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    if not bld_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")

    active_room_result = await db.execute(
        select(Room.id)
        .where(Room.building_id == building_id, Room.is_active == True)
        .limit(1)
    )
    if active_room_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=400,
            detail="Tòa nhà chưa có phòng đang hoạt động",
        )

    if len(files) > settings.MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Tối đa {settings.MAX_BATCH_SIZE} ảnh/lần")

    # Save files
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    upload_root = settings.upload_path.resolve()
    upload_dir = (upload_root / parsed_reading_date.strftime("%Y%m%d")).resolve()
    try:
        upload_dir.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Đường dẫn upload không hợp lệ") from exc
    upload_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []
    for file in files:
        original_filename = file.filename or ""
        ext = Path(original_filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            await file.close()
            continue

        room_number = extract_room_number(original_filename)
        file_path = (upload_dir / f"{uuid.uuid4().hex}{ext}").resolve()
        try:
            file_path.relative_to(upload_root)
        except ValueError:
            await file.close()
            continue

        if not await _save_upload_limited(file, file_path):
            file_path.unlink(missing_ok=True)
            continue

        image_paths.append(
            {
                "path": str(file_path),
                "room_number": room_number,
                "filename": original_filename,
            }
        )

    if not image_paths:
        raise HTTPException(status_code=400, detail="Không có ảnh hợp lệ")

    # Create batch job
    batch_job = BatchJob(
        job_id=job_id,
        job_type="image_processing",
        status="queued",
        total_items=len(image_paths),
        result_data=json.dumps(
            {
                "building_id": building_id,
                "reading_date": parsed_reading_date.isoformat(),
                "unmatched": [],
            },
            ensure_ascii=False,
        ),
    )
    db.add(batch_job)
    await db.commit()

    # Start background processing
    background_tasks.add_task(
        process_batch_images,
        job_id,
        image_paths,
        building_id,
        parsed_reading_date.isoformat(),
    )

    return BatchUploadResponse(
        job_id=job_id,
        status="queued",
        total_images=len(image_paths),
        message=f"Đang xử lý {len(image_paths)} ảnh. Theo dõi tiến trình qua job_id.",
    )


@router.get("/batch-status/{job_id}", response_model=BatchStatusResponse)
async def batch_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BatchJob).where(BatchJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    job_data = _load_job_data(job)
    building_id = job_data.get("building_id")
    if type(building_id) is not int:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    building_result = await db.execute(
        select(Building).where(
            Building.id == building_id,
            Building.owner_id == current_user.id,
        )
    )
    if not building_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    # Get readings for this job
    readings_result = await db.execute(
        select(MeterReading).where(MeterReading.batch_job_id == job_id)
    )
    readings = readings_result.scalars().all()

    # Pre-fetch all rooms in a single IN query — avoids N room queries in loop
    room_ids = [r.room_id for r in readings if r.room_id is not None]
    if room_ids:
        rooms_res = await db.execute(select(Room).where(Room.id.in_(room_ids)))
        room_map = {room.id: room for room in rooms_res.scalars().all()}
    else:
        room_map = {}

    reading_responses = []
    for r in readings:
        room = room_map.get(r.room_id) if r.room_id is not None else None
        resp = ReadingResponse.model_validate(r)
        if room:
            resp.room_number = room.room_number
            resp.resident_name = room.resident_name
        if r.image_path:
            resp.image_path = _protected_image_url(r.id)
        reading_responses.append(resp)

    staged_responses = []
    for item in job_data.get("unmatched", []):
        staged = StagedReadingResponse.model_validate(item)
        if staged.image_path:
            staged.image_path = _protected_staged_image_url(staged.staged_id)
        staged_responses.append(staged)

    return BatchStatusResponse(
        job_id=job.job_id,
        status=job.status,
        total=job.total_items,
        processed=job.processed_items,
        failed=job.failed_items,
        results=[*reading_responses, *staged_responses],
    )


@router.get("/{reading_id}/image")
async def get_reading_image(
    reading_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MeterReading)
        .join(Room, Room.id == MeterReading.room_id)
        .join(Building, Building.id == Room.building_id)
        .where(
            MeterReading.id == reading_id,
            Building.owner_id == current_user.id,
        )
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")
    return FileResponse(
        _resolve_upload_file(reading.image_path),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/staged/{staged_id}/image")
async def get_staged_reading_image(
    staged_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs_result = await db.execute(
        select(BatchJob).where(BatchJob.job_type == "image_processing")
    )
    for job in jobs_result.scalars().all():
        job_data = _load_job_data(job)
        building_id = job_data.get("building_id")
        if type(building_id) is not int:
            continue

        # Ownership check FIRST — skip jobs for buildings not owned by current user
        # This prevents data leak: we never scan unmatched items for other users' jobs
        building_result = await db.execute(
            select(Building.id).where(
                Building.id == building_id,
                Building.owner_id == current_user.id,
            )
        )
        if building_result.scalar_one_or_none() is None:
            continue

        staged = next(
            (
                item
                for item in job_data.get("unmatched", [])
                if item.get("staged_id") == staged_id
            ),
            None,
        )
        if staged is None:
            continue

        return FileResponse(_resolve_upload_file(staged.get("image_path")))

    raise HTTPException(status_code=404, detail="Ảnh không tồn tại")


@router.patch("/staged/{staged_id}", response_model=ReadingResponse)
async def approve_staged_reading(
    staged_id: str,
    body: StagedReadingApproval,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs_result = await db.execute(
        select(BatchJob).where(BatchJob.job_type == "image_processing")
    )
    for job in jobs_result.scalars().all():
        job_data = _load_job_data(job)
        building_id = job_data.get("building_id")

        # Ownership check FIRST — skip jobs for buildings not owned by current user
        # Prevents accepting staged readings from another user's jobs
        if type(building_id) is not int:
            continue
        bld_check = await db.execute(
            select(Building.id).where(
                Building.id == building_id,
                Building.owner_id == current_user.id,
            )
        )
        if bld_check.scalar_one_or_none() is None:
            continue

        staged_items = job_data.get("unmatched", [])
        staged = next(
            (item for item in staged_items if item.get("staged_id") == staged_id),
            None,
        )
        if staged is None:
            continue

        room_result = await db.execute(
            select(Room)
            .join(Building, Building.id == Room.building_id)
            .where(
                Room.id == body.room_id,
                Room.building_id == building_id,
                Building.owner_id == current_user.id,
                Room.is_active == True,
            )
        )
        room = room_result.scalar_one_or_none()
        if not room:
            raise HTTPException(status_code=404, detail="Phòng không tồn tại trong tòa nhà của job")

        notes = body.notes if body.notes is not None else staged.get("notes")
        reading = MeterReading(
            room_id=room.id,
            reading_date=datetime.strptime(staged["reading_date"], "%Y-%m-%d").date(),
            meter_value=body.meter_value,
            image_path=staged.get("image_path"),
            confidence_score=staged.get("confidence_score"),
            status=body.status,
            notes=notes,
            batch_job_id=job.job_id,
        )
        db.add(reading)
        job_data["unmatched"] = [
            item for item in staged_items if item.get("staged_id") != staged_id
        ]
        _store_job_data(job, job_data)
        await db.commit()
        await db.refresh(reading)

        response = ReadingResponse.model_validate(reading)
        response.room_number = room.room_number
        response.resident_name = room.resident_name
        if reading.image_path:
            response.image_path = _protected_image_url(reading.id)
        return response

    raise HTTPException(status_code=404, detail="Kết quả chờ duyệt không tồn tại")


@router.get("", response_model=list[ReadingResponse])
async def list_readings(
    building_id: int | None = None,
    room_id: int | None = None,
    status: str | None = None,
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    previous = aliased(MeterReading)
    previous_value = (
        select(previous.meter_value)
        .where(
            previous.room_id == MeterReading.room_id,
            previous.status == "approved",
            or_(
                previous.reading_date < MeterReading.reading_date,
                and_(
                    previous.reading_date == MeterReading.reading_date,
                    previous.id < MeterReading.id,
                ),
            ),
        )
        .order_by(previous.reading_date.desc(), previous.id.desc())
        .limit(1)
        .correlate(MeterReading)
        .scalar_subquery()
    )
    previous_or_initial = func.coalesce(previous_value, Room.initial_reading)
    query = (
        select(
            MeterReading,
            Room.room_number,
            Room.resident_name,
            Building.name.label("building_name"),
            previous_or_initial.label("previous_reading"),
        )
        .join(Room, Room.id == MeterReading.room_id)
        .join(Building, Building.id == Room.building_id)
        .where(Building.owner_id == current_user.id)
        .order_by(MeterReading.created_at.desc(), MeterReading.id.desc())
    )

    if room_id is not None:
        query = query.where(MeterReading.room_id == room_id)
    if building_id is not None:
        query = query.where(Building.id == building_id)

    if status:
        query = query.where(MeterReading.status == status)
    if month:
        month_start = date.fromisoformat(f"{month}-01")
        next_month = (
            date(month_start.year + 1, 1, 1)
            if month_start.month == 12
            else date(month_start.year, month_start.month + 1, 1)
        )
        query = query.where(
            MeterReading.reading_date >= month_start,
            MeterReading.reading_date < next_month,
        )

    result = await db.execute(query.offset(offset).limit(limit))

    responses = []
    for reading, room_number, resident_name, building_name, previous_reading in result.all():
        resp = ReadingResponse.model_validate(reading)
        resp.room_number = room_number
        resp.resident_name = resident_name
        resp.building_name = building_name
        resp.previous_reading = previous_reading
        resp.current_reading = reading.meter_value
        resp.consumption = reading.meter_value - previous_reading
        if reading.image_path:
            resp.image_path = _protected_image_url(reading.id)
        responses.append(resp)

    return responses


@router.patch("/{reading_id}", response_model=ReadingResponse)
async def update_reading(
    reading_id: int,
    body: ReadingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MeterReading)
        .join(Room, Room.id == MeterReading.room_id)
        .join(Building, Building.id == Room.building_id)
        .where(
            MeterReading.id == reading_id,
            Building.owner_id == current_user.id,
        )
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Chỉ số không tồn tại")

    update_data = body.model_dump(exclude_unset=True)
    if "room_id" in update_data:
        room_result = await db.execute(
            select(Room)
            .join(Building, Building.id == Room.building_id)
            .where(
                Room.id == update_data["room_id"],
                Building.owner_id == current_user.id,
                Room.is_active == True,
            )
        )
        if not room_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Phòng không tồn tại")
    for field, value in update_data.items():
        setattr(reading, field, value)

    await db.commit()
    await db.refresh(reading)
    response = ReadingResponse.model_validate(reading)
    room_result = await db.execute(select(Room).where(Room.id == reading.room_id))
    room = room_result.scalar_one_or_none()
    if room:
        response.room_number = room.room_number
        response.resident_name = room.resident_name
    if reading.image_path:
        response.image_path = _protected_image_url(reading.id)
    return response
