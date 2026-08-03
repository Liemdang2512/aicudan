from typing import Literal

from pydantic import BaseModel, Field, PositiveInt


class SendBatchRequest(BaseModel):
    invoice_ids: list[PositiveInt] = Field(min_length=1)
    include_image: bool = True


class SendBatchResponse(BaseModel):
    job_id: str
    total: int
    status: Literal["queued"]


class NotificationStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    total: int
    processed: int
    sent: int
    failed: int
