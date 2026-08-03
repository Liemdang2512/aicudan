from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("building_id", "room_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    building_id: Mapped[int] = mapped_column(Integer, ForeignKey("buildings.id"), nullable=False)
    room_number: Mapped[str] = mapped_column(String(20), nullable=False)
    resident_name: Mapped[str | None] = mapped_column(String(255))
    resident_phone: Mapped[str | None] = mapped_column(String(20))
    resident_email: Mapped[str | None] = mapped_column(String(255))
    telegram_id: Mapped[str | None] = mapped_column(String(100))
    initial_reading: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    building = relationship("Building", back_populates="rooms")
    readings = relationship("MeterReading", back_populates="room", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="room", cascade="all, delete-orphan")
