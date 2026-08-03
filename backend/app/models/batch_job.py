from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)  # image_processing / notification
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued/processing/completed/failed
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    result_data: Mapped[str | None] = mapped_column(Text)  # JSON
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
