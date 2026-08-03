from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("room_id", "invoice_month", name="uq_invoices_room_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), nullable=False)
    reading_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("meter_readings.id"))
    invoice_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    previous_reading: Mapped[int] = mapped_column(Integer, default=0)
    current_reading: Mapped[int] = mapped_column(Integer, nullable=False)
    consumption: Mapped[int] = mapped_column(Integer, nullable=False)
    price_breakdown: Mapped[str | None] = mapped_column(Text)  # JSON string
    electricity_amount: Mapped[float] = mapped_column(Float, default=0)
    additional_fees: Mapped[str | None] = mapped_column(Text)  # JSON string
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    sent_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/sent/failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    room = relationship("Room", back_populates="invoices")
