from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.building import Building
from app.models.invoice import Invoice
from app.models.reading import MeterReading
from app.models.room import Room
from app.models.user import User
from app.schemas.dashboard import ActivityItem, DashboardStats

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _current_month_range() -> tuple[date, date, str]:
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    month_start = today.replace(day=1)
    next_month = (
        date(today.year + 1, 1, 1)
        if today.month == 12
        else date(today.year, today.month + 1, 1)
    )
    return month_start, next_month, month_start.strftime("%Y-%m")


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    building_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    month_start, next_month, current_month = _current_month_range()

    # Get user's buildings
    if building_id is not None:
        building_result = await db.execute(
            select(Building.id).where(
                Building.id == building_id,
                Building.owner_id == current_user.id,
            )
        )
        if building_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")
        building_ids = [building_id]
    else:
        bld_result = await db.execute(
            select(Building.id).where(Building.owner_id == current_user.id)
        )
        building_ids = [r[0] for r in bld_result.fetchall()]

    if not building_ids:
        return DashboardStats(current_month=current_month)

    total_buildings = len(building_ids)

    # Total rooms
    # Get active room ids. Every room belongs to exactly one reading KPI bucket.
    room_ids_result = await db.execute(
        select(Room.id).where(
            Room.building_id.in_(building_ids),
            Room.is_active == True,
        )
    )
    room_ids = [r[0] for r in room_ids_result.fetchall()]
    total_rooms = len(room_ids)

    if not room_ids:
        return DashboardStats(
            total_buildings=total_buildings,
            total_rooms=total_rooms,
            current_month=current_month,
        )

    latest_readings_result = await db.execute(
        select(MeterReading.room_id, MeterReading.status)
        .where(
            MeterReading.room_id.in_(room_ids),
            MeterReading.reading_date >= month_start,
            MeterReading.reading_date < next_month,
        )
        .order_by(
            MeterReading.room_id,
            MeterReading.reading_date.desc(),
            MeterReading.id.desc(),
        )
    )
    latest_status_by_room: dict[int, str] = {}
    for room_id, reading_status in latest_readings_result.all():
        latest_status_by_room.setdefault(room_id, reading_status)

    readings_done = sum(status == "approved" for status in latest_status_by_room.values())
    readings_error = sum(status == "rejected" for status in latest_status_by_room.values())
    readings_pending = total_rooms - readings_done - readings_error

    # Invoice stats
    invoice_result = await db.execute(
        select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.room_id.in_(room_ids),
            Invoice.invoice_month == current_month,
        )
    )
    row = invoice_result.fetchone()
    total_invoices = row[0] or 0
    total_revenue = float(row[1] or 0)

    return DashboardStats(
        total_buildings=total_buildings,
        total_rooms=total_rooms,
        readings_done=readings_done,
        readings_pending=readings_pending,
        readings_error=readings_error,
        total_invoices=total_invoices,
        total_revenue=total_revenue,
        current_month=current_month,
    )


@router.get("/activity", response_model=list[ActivityItem])
async def get_activity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    readings_result = await db.execute(
        select(MeterReading, Room.room_number)
        .join(Room, Room.id == MeterReading.room_id)
        .join(Building, Building.id == Room.building_id)
        .where(Building.owner_id == current_user.id)
        .order_by(MeterReading.created_at.desc())
        .limit(10)
    )

    items = []
    for reading, room_number in readings_result.all():
        if reading.status == "approved":
            desc = f"Phòng {room_number} - Chỉ số {reading.meter_value} đã xác nhận"
        elif reading.status == "needs_review":
            desc = f"Phòng {room_number} - Cần kiểm tra lại"
        elif reading.status == "rejected":
            desc = f"Phòng {room_number} - Chỉ số đã bị từ chối"
        else:
            desc = f"Phòng {room_number} - Đang chờ xử lý"

        items.append(
            ActivityItem(
                id=reading.id,
                type="reading",
                description=desc,
                status=reading.status,
                created_at=reading.created_at.isoformat() if reading.created_at else "",
            )
        )

    return items
