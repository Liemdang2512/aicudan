from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TechnicianProfile(Base):
    __tablename__ = "technician_profiles"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ktv_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ktv_phone: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
