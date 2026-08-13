from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.building import Building
from app.models.reading import MeterReading
from app.models.room import Room
from app.models.user import User
from app.schemas.room import RoomCreate, RoomResponse, RoomUpdate, SimpleReading

router = APIRouter(tags=["Rooms"])

MAX_EXCEL_FILE_SIZE = 5 * 1024 * 1024
MAX_EXCEL_UNCOMPRESSED_SIZE = 50 * 1024 * 1024
MAX_EXCEL_ZIP_ENTRIES = 1000
EXCEL_CHUNK_SIZE = 64 * 1024
ALLOWED_EXCEL_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
    "application/zip",
}


def _room_response(room: Room) -> RoomResponse:
    """Build RoomResponse from a Room with preloaded .readings (selectinload)."""
    return _build_room_response(room, list(room.readings))


def _build_room_response(room: Room, readings: list[MeterReading]) -> RoomResponse:
    """Build RoomResponse from a Room + explicitly provided readings list."""
    response = RoomResponse.model_validate(room)
    sorted_readings = sorted(
        readings,
        key=lambda r: (r.reading_date, r.created_at),
        reverse=True,
    )
    approved = [r for r in sorted_readings if r.status == "approved"]
    if approved:
        response.current_reading = approved[0].meter_value
        response.previous_reading = (
            approved[1].meter_value if len(approved) > 1 else room.initial_reading
        )
        response.consumption = response.current_reading - response.previous_reading
    else:
        response.previous_reading = room.initial_reading
        response.current_reading = None
        response.consumption = None

    response.readings_history = []
    for reading in sorted_readings:
        history_item = SimpleReading.model_validate(reading)
        if history_item.image_path:
            history_item.image_path = f"/readings/{reading.id}/image"
        response.readings_history.append(history_item)
    return response


async def _bulk_load_recent_readings(
    db: AsyncSession,
    room_ids: list[int],
    limit_per_room: int = 10,
) -> dict[int, list[MeterReading]]:
    """Load up to `limit_per_room` most recent readings per room in a single query
    using a window function — avoids loading the entire history for every room.
    """
    if not room_ids:
        return {}

    rn = func.row_number().over(
        partition_by=MeterReading.room_id,
        order_by=[MeterReading.reading_date.desc(), MeterReading.id.desc()],
    ).label("rn")

    subq = (
        select(MeterReading.id, rn)
        .where(MeterReading.room_id.in_(room_ids))
        .subquery()
    )

    result = await db.execute(
        select(MeterReading)
        .join(subq, MeterReading.id == subq.c.id)
        .where(subq.c.rn <= limit_per_room)
        .order_by(MeterReading.room_id, MeterReading.reading_date.desc(), MeterReading.id.desc())
    )
    readings_by_room: dict[int, list[MeterReading]] = defaultdict(list)
    for reading in result.scalars().all():
        readings_by_room[reading.room_id].append(reading)
    return readings_by_room


async def _read_excel_upload(file: UploadFile) -> bytes:
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx")
    if file.content_type not in ALLOWED_EXCEL_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Định dạng file Excel không hợp lệ")

    data = bytearray()
    try:
        while chunk := await file.read(EXCEL_CHUNK_SIZE):
            data.extend(chunk)
            if len(data) > MAX_EXCEL_FILE_SIZE:
                raise HTTPException(status_code=413, detail="File Excel vượt quá 5 MB")
    finally:
        await file.close()

    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_EXCEL_ZIP_ENTRIES:
                raise HTTPException(status_code=400, detail="File Excel có quá nhiều thành phần")
            if any(info.flag_bits & 0x1 for info in entries):
                raise HTTPException(status_code=400, detail="Không hỗ trợ file Excel mã hóa")
            if sum(info.file_size for info in entries) > MAX_EXCEL_UNCOMPRESSED_SIZE:
                raise HTTPException(status_code=400, detail="File Excel giải nén quá lớn")
    except BadZipFile as exc:
        raise HTTPException(status_code=400, detail="File Excel không hợp lệ") from exc

    return bytes(data)


@router.get("/buildings/{building_id}/rooms", response_model=list[RoomResponse])
async def list_rooms(
    building_id: int,
    is_active: bool | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify building belongs to user
    bld_result = await db.execute(
        select(Building).where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    if not bld_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")

    query = select(Room).where(Room.building_id == building_id)

    if is_active is not None:
        query = query.where(Room.is_active == is_active)
    if search:
        query = query.where(
            Room.room_number.contains(search) | Room.resident_name.contains(search)
        )

    query = query.order_by(Room.room_number)
    result = await db.execute(query)
    rooms = result.scalars().all()

    # Bulk-load only last 10 readings per room (window function) instead of all readings
    room_ids = [r.id for r in rooms]
    readings_by_room = await _bulk_load_recent_readings(db, room_ids, limit_per_room=10)

    return [_build_room_response(r, readings_by_room.get(r.id, [])) for r in rooms]


@router.post(
    "/buildings/{building_id}/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room(
    building_id: int,
    body: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify building
    bld_result = await db.execute(
        select(Building).where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    if not bld_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")

    # Check duplicate
    dup_result = await db.execute(
        select(Room).where(Room.building_id == building_id, Room.room_number == body.room_number)
    )
    if dup_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Phòng {body.room_number} đã tồn tại")

    room = Room(building_id=building_id, **body.model_dump())
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return RoomResponse.model_validate(room)


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Room)
        .join(Building, Room.building_id == Building.id)
        .where(Room.id == room_id, Building.owner_id == current_user.id)
        .options(selectinload(Room.readings))
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Phòng không tồn tại")
    return _room_response(room)


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: int,
    body: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Room)
        .join(Building, Room.building_id == Building.id)
        .where(Room.id == room_id, Building.owner_id == current_user.id)
        .options(selectinload(Room.readings))
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Phòng không tồn tại")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    await db.commit()
    await db.refresh(room)
    return _room_response(room)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Room)
        .join(Building, Room.building_id == Building.id)
        .where(Room.id == room_id, Building.owner_id == current_user.id)
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Phòng không tồn tại")

    await db.delete(room)
    await db.commit()


@router.post("/buildings/{building_id}/rooms/import-excel")
async def import_rooms_from_excel(
    building_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Import danh sách phòng từ file Excel.

    Format Excel:
    - Cột A (STT): 1, 2, ...
    - Cột B (ID Phòng): B 1801, B 1822, ... 
    - Cột C (Phòng): B 1801, B 1822, ... (tùy chọn)
    - Cột D (Tên Đại Diện): Nguyễn Văn A
    - Cột E (Chỉ Số Cũ): 1000
    - Cột F (Chỉ Số Mới): 1122
    - Cột K (SĐT): 0375625273...
    - Cột L (Email): dangtanliem37@gmail.com
    """
    # Verify building
    bld_result = await db.execute(
        select(Building).where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    building = bld_result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")

    # Read Excel
    try:
        contents = await _read_excel_upload(file)
        wb = openpyxl.load_workbook(BytesIO(contents))
        ws = wb.active
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không thể đọc file Excel: {str(e)}")

    created_count = 0
    updated_count = 0
    errors = []

    # Skip header row
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        try:
            id_phong = row[1] if len(row) > 1 else None  # Cột B (index 1)
            room_number = row[2] if len(row) > 2 else None  # Cột C (index 2)
            resident_name = row[3] if len(row) > 3 else None  # Cột D
            chi_so_cu = row[4] if len(row) > 4 else None  # Cột E
            chi_so_moi = row[5] if len(row) > 5 else None  # Cột F
            phone = str(row[10]) if len(row) > 10 and row[10] is not None else None  # Cột K (index 10)
            email = row[11] if len(row) > 11 else None  # Cột L (index 11)

            # Parse room number from ID Phòng or Phòng column
            if not room_number and id_phong:
                room_number = str(id_phong).strip().split()[-1]  # "B 1801" -> "1801"
            elif room_number:
                room_number = str(room_number).strip().split()[-1]

            if not room_number:
                errors.append(f"Dòng {row_idx}: Thiếu số phòng")
                continue

            # Check if room exists
            result = await db.execute(
                select(Room).where(
                    Room.building_id == building_id, Room.room_number == room_number
                )
            )
            room = result.scalar_one_or_none()

            if room:
                # Update existing room
                room.resident_name = resident_name
                room.resident_phone = phone
                room.resident_email = email
                if chi_so_cu is not None and not room.initial_reading:
                    room.initial_reading = int(chi_so_cu)
                updated_count += 1
            else:
                # Create new room
                room = Room(
                    building_id=building_id,
                    room_number=room_number,
                    resident_name=resident_name,
                    resident_phone=phone,
                    resident_email=email,
                    initial_reading=int(chi_so_cu) if chi_so_cu is not None else 0,
                    is_active=True,
                )
                db.add(room)
                created_count += 1

            await db.flush()

            # Create meter reading if chi_so_moi exists
            if chi_so_moi and int(chi_so_moi) > 0:
                reading = MeterReading(
                    room_id=room.id,
                    reading_date=date.today(),
                    meter_value=int(chi_so_moi),
                    status="approved",
                    confidence_score=1.0,
                    notes="Imported from Excel",
                )
                db.add(reading)

        except Exception as e:
            errors.append(f"Dòng {row_idx}: {str(e)}")
            continue

    await db.commit()

    return {
        "success": True,
        "created": created_count,
        "updated": updated_count,
        "errors": errors,
        "message": f"Import thành công: {created_count} phòng mới, {updated_count} phòng cập nhật",
    }
