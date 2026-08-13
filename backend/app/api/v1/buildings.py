from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.building import Building
from app.models.room import Room
from app.models.user import User
from app.schemas.building import BuildingCreate, BuildingResponse, BuildingUpdate

router = APIRouter(prefix="/buildings", tags=["Buildings"])


def _room_count_expression():
    return (
        select(func.count(Room.id))
        .where(Room.building_id == Building.id, Room.is_active.is_(True))
        .correlate(Building)
        .scalar_subquery()
    )


def _building_response(building: Building, room_count: int) -> BuildingResponse:
    response = BuildingResponse.model_validate(building)
    response.room_count = room_count
    return response


@router.get("", response_model=list[BuildingResponse])
async def list_buildings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Building, _room_count_expression().label("room_count"))
        .where(Building.owner_id == current_user.id)
        .order_by(Building.created_at.desc())
    )
    return [_building_response(building, room_count) for building, room_count in result.all()]


@router.post("", response_model=BuildingResponse, status_code=status.HTTP_201_CREATED)
async def create_building(
    body: BuildingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    building = Building(owner_id=current_user.id, name=body.name, address=body.address)
    db.add(building)
    await db.commit()
    await db.refresh(building)
    resp = BuildingResponse.model_validate(building)
    resp.room_count = 0
    return resp


@router.get("/{building_id}", response_model=BuildingResponse)
async def get_building(
    building_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Single query: fetch building + room_count together
    result = await db.execute(
        select(Building, _room_count_expression().label("room_count"))
        .where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")
    return _building_response(row[0], row[1])


@router.patch("/{building_id}", response_model=BuildingResponse)
async def update_building(
    building_id: int,
    body: BuildingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Building).where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    building = result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(building, field, value)

    await db.commit()

    # Single query after update
    rc_result = await db.execute(
        select(Building, _room_count_expression().label("room_count"))
        .where(Building.id == building_id)
    )
    row = rc_result.first()
    return _building_response(row[0], row[1])


@router.delete("/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(
    building_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Building).where(Building.id == building_id, Building.owner_id == current_user.id)
    )
    building = result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")

    await db.delete(building)
    await db.commit()
