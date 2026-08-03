from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReadingUpdate(BaseModel):
    room_id: int | None = None
    meter_value: int | None = Field(default=None, ge=0)
    status: Literal["pending", "needs_review", "approved", "rejected"] | None = None
    notes: str | None = None


class StagedReadingApproval(BaseModel):
    room_id: int
    meter_value: int = Field(ge=0)
    meter_type: Literal["electric"]
    status: Literal["approved"]
    notes: str | None = None


class ReadingResponse(BaseModel):
    id: int
    room_id: int
    reading_date: date
    meter_value: int
    image_path: str | None = None
    confidence_score: float | None = None
    status: str
    notes: str | None = None
    batch_job_id: str | None = None
    created_at: datetime
    room_number: str | None = None
    resident_name: str | None = None
    building_name: str | None = None
    previous_reading: int | None = None
    current_reading: int | None = None
    consumption: int | None = None
    staged_id: None = None
    meter_type: Literal["electric", "water", "unknown"] = "electric"

    model_config = {"from_attributes": True}


class StagedReadingResponse(BaseModel):
    id: None = None
    staged_id: str
    room_id: None = None
    room_number: None = None
    resident_name: None = None
    reading_date: date
    meter_value: int | None = None
    meter_type: Literal["electric", "water", "unknown"]
    image_path: str | None = None
    confidence_score: float | None = None
    status: Literal["needs_review"] = "needs_review"
    notes: str | None = None
    batch_job_id: str


class BatchUploadRequest(BaseModel):
    building_id: int
    reading_date: date


class BatchUploadResponse(BaseModel):
    job_id: str
    status: str
    total_images: int
    message: str


class BatchStatusResponse(BaseModel):
    job_id: str
    status: str
    total: int
    processed: int
    failed: int
    results: list[ReadingResponse | StagedReadingResponse] = []
