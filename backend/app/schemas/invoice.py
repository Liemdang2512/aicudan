from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

NonNegativeFiniteFloat = Annotated[
    float,
    Field(ge=0, allow_inf_nan=False),
]


class InvoiceGenerateRequest(BaseModel):
    building_id: int
    invoice_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    price_config_id: int
    additional_fees: dict[str, NonNegativeFiniteFloat] = Field(default_factory=dict)

    @field_validator("invoice_month")
    @classmethod
    def validate_invoice_month(cls, value: str) -> str:
        try:
            date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise ValueError("Kỳ hóa đơn phải theo định dạng YYYY-MM") from exc
        return value


class InvoiceResponse(BaseModel):
    id: int
    room_id: int
    invoice_month: str
    previous_reading: int
    current_reading: int
    consumption: int
    price_breakdown: str | None = None
    electricity_amount: float
    additional_fees: str | None = None
    total_amount: float
    sent_status: Literal["pending", "sending", "sent", "failed"]
    sent_at: datetime | None = None
    created_at: datetime
    room_number: str | None = None
    resident_name: str | None = None

    model_config = {"from_attributes": True}


class InvoiceGenerateRoomResult(BaseModel):
    room_id: int
    room_number: str
    status: Literal["created", "skipped", "error"]
    invoice_id: int | None = None
    detail: str


class InvoiceGenerateResponse(BaseModel):
    total_invoices: int
    total_amount: float
    invoices: list[InvoiceResponse]
    total_skipped: int = 0
    total_errors: int = 0
    results: list[InvoiceGenerateRoomResult] = Field(default_factory=list)
