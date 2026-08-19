import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.session import engine
from app.models.app_setting import AppSetting  # noqa: F401
from app.models.batch_job import BatchJob  # noqa: F401
from app.models.bot_session import BotSession  # noqa: F401
from app.models.building import Building  # noqa: F401
from app.models.invoice import Invoice  # noqa: F401
from app.models.price_config import PriceConfig
from app.models.reading import MeterReading  # noqa: F401
from app.models.room import Room  # noqa: F401
from app.models.technician_profile import TechnicianProfile  # noqa: F401
from app.models.user import User
from app.schemas.price_config import normalize_legacy_price_config

logger = logging.getLogger(__name__)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def normalize_price_configs(db: AsyncSession) -> tuple[int, int]:
    """Normalize safely recognized legacy pricing rows; leave ambiguous rows untouched."""
    result = await db.execute(select(PriceConfig))
    normalized_count = 0
    skipped_count = 0
    for price_config in result.scalars().all():
        try:
            canonical_json, changed = normalize_legacy_price_config(
                price_config.pricing_type, price_config.config_json
            )
        except ValueError as exc:
            skipped_count += 1
            logger.warning("Skipped invalid price config id=%s: %s", price_config.id, exc)
            continue
        if changed:
            price_config.config_json = canonical_json
            normalized_count += 1

    if normalized_count:
        await db.commit()
    logger.info(
        "Price config normalization complete: normalized=%s skipped=%s",
        normalized_count,
        skipped_count,
    )
    return normalized_count, skipped_count


async def load_settings_from_db(db: AsyncSession, owner_id: int) -> None:
    """Load app settings for a specific owner from DB into the runtime settings object."""
    result = await db.execute(select(AppSetting).where(AppSetting.owner_id == owner_id))
    row = result.scalar_one_or_none()
    if row is None:
        return
    if row.gemini_api_key:
        settings.GEMINI_API_KEY = row.gemini_api_key
    if row.telegram_bot_token:
        settings.TELEGRAM_BOT_TOKEN = row.telegram_bot_token
    if row.payment_management_unit:
        settings.PAYMENT_MANAGEMENT_UNIT = row.payment_management_unit
    if row.payment_bank_account:
        settings.PAYMENT_BANK_ACCOUNT = row.payment_bank_account
    if row.payment_bank_name:
        settings.PAYMENT_BANK_NAME = row.payment_bank_name
    if row.payment_account_holder:
        settings.PAYMENT_ACCOUNT_HOLDER = row.payment_account_holder
    if row.telegram_ktv_bot_token:
        settings.TELEGRAM_KTV_BOT_TOKEN = row.telegram_ktv_bot_token
    if row.telegram_ktv_password:
        settings.TELEGRAM_KTV_PASSWORD = row.telegram_ktv_password
    if row.manager_telegram_chat_id:
        settings.MANAGER_TELEGRAM_CHAT_ID = row.manager_telegram_chat_id
    logger.info("App settings loaded from database for owner_id=%s", owner_id)


async def seed_data(db: AsyncSession):
    await normalize_price_configs(db)

    # Check if admin exists
    result = await db.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
    existing_admin = result.scalar_one_or_none()
    if existing_admin:
        if settings.APP_ENV.lower() == "production" and verify_password(
            "admin123", existing_admin.password_hash
        ):
            existing_admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
            await db.commit()
            logger.warning("Rotated legacy seeded admin password during production startup")
        await _ensure_app_settings(db, existing_admin.id)
        return

    # Create admin user
    admin = User(
        email=settings.ADMIN_EMAIL,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        full_name=settings.ADMIN_FULL_NAME,
        role="admin",
    )
    db.add(admin)

    # Create default EVN price config (QĐ 1279/QĐ-BCT 2025)
    evn_config = PriceConfig(
        config_name="EVN Bậc Thang 2025 (QĐ 1279)",
        pricing_type="tiered",
        config_json=json.dumps(
            {
                "tiers": [
                    {"min": 0, "max": 50, "price": 1984, "name": "Bậc 1"},
                    {"min": 51, "max": 100, "price": 2050, "name": "Bậc 2"},
                    {"min": 101, "max": 200, "price": 2380, "name": "Bậc 3"},
                    {"min": 201, "max": 300, "price": 2998, "name": "Bậc 4"},
                    {"min": 301, "max": 400, "price": 3350, "name": "Bậc 5"},
                    {"min": 401, "max": None, "price": 3460, "name": "Bậc 6"},
                ],
                "vat": 0.08,
            },
            ensure_ascii=False,
        ),
        is_default=True,
    )
    db.add(evn_config)

    # Create fixed price config
    fixed_config = PriceConfig(
        config_name="Giá Cố Định 3.500đ/kWh",
        pricing_type="fixed",
        config_json=json.dumps({"price": 3500}, ensure_ascii=False),
        is_default=False,
    )
    db.add(fixed_config)

    await db.flush()  # flush to get admin.id before _ensure_app_settings
    await _ensure_app_settings(db, admin.id)
    await db.commit()


async def _ensure_app_settings(db: AsyncSession, owner_id: int) -> None:
    """Seed app_settings row for owner_id from env if not yet in DB, then load into runtime settings."""
    result = await db.execute(select(AppSetting).where(AppSetting.owner_id == owner_id))
    if result.scalar_one_or_none() is None:
        db.add(
            AppSetting(
                owner_id=owner_id,
                gemini_api_key=settings.GEMINI_API_KEY,
                telegram_bot_token=settings.TELEGRAM_BOT_TOKEN,
                payment_management_unit=settings.PAYMENT_MANAGEMENT_UNIT,
                payment_bank_account=settings.PAYMENT_BANK_ACCOUNT,
                payment_bank_name=settings.PAYMENT_BANK_NAME,
                payment_account_holder=settings.PAYMENT_ACCOUNT_HOLDER,
                telegram_ktv_bot_token=settings.TELEGRAM_KTV_BOT_TOKEN,
                telegram_ktv_password=settings.TELEGRAM_KTV_PASSWORD,
                manager_telegram_chat_id=settings.MANAGER_TELEGRAM_CHAT_ID,
            )
        )
        await db.flush()
        logger.info("App settings seeded from environment variables for owner_id=%s", owner_id)

    await load_settings_from_db(db, owner_id)
