from datetime import date, datetime

from pydantic import BaseModel


class RoomCreate(BaseModel):
    room_number: str
    resident_name: str | None = None
    resident_phone: str | None = None
    resident_email: str | None = None
    telegram_id: str | None = None
    initial_reading: int = 0


class RoomUpdate(BaseModel):
    room_number: str | None = None
    resident_name: str | None = None
    resident_phone: str | None = None
    resident_email: str | None = None
    telegram_id: str | None = None
    is_active: bool | None = None


class SimpleReading(BaseModel):
    id: int
    reading_date: date
    meter_value: int
    confidence_score: float | None = None
    status: str
    notes: str | None = None
    image_path: str | None = None

    model_config = {"from_attributes": True}


class RoomResponse(BaseModel):
    id: int
    building_id: int
    room_number: str
    resident_name: str | None = None
    resident_phone: str | None = None
    resident_email: str | None = None
    telegram_id: str | None = None
    initial_reading: int
    previous_reading: int | None = None
    current_reading: int | None = None
    consumption: int | None = None
    is_active: bool
    created_at: datetime
    readings_history: list[SimpleReading] = []

    model_config = {"from_attributes": True}
