from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)  # always 1
    gemini_api_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    telegram_bot_token: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    payment_management_unit: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    payment_bank_account: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    payment_bank_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    payment_account_holder: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
