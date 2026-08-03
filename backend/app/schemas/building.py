from datetime import datetime

from pydantic import BaseModel


class BuildingCreate(BaseModel):
    name: str
    address: str | None = None


class BuildingUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    is_active: bool | None = None


class BuildingResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    address: str | None = None
    is_active: bool
    created_at: datetime
    room_count: int = 0

    model_config = {"from_attributes": True}
