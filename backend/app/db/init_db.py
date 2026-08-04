import json
import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.session import engine
from app.models.batch_job import BatchJob  # noqa: F401
from app.models.bot_session import BotSession  # noqa: F401
from app.models.building import Building  # noqa: F401
from app.models.invoice import Invoice  # noqa: F401
from app.models.price_config import PriceConfig
from app.models.reading import MeterReading  # noqa: F401
from app.models.room import Room  # noqa: F401
from app.models.user import User
from app.schemas.price_config import normalize_legacy_price_config

logger = logging.getLogger(__name__)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_invoice_unique_constraint)


def _ensure_invoice_unique_constraint(connection) -> None:
    """Upgrade pre-Alembic databases so invoice idempotency is enforced at DB level."""
    inspector = inspect(connection)
    expected_columns = {"room_id", "invoice_month"}
    unique_constraints = inspector.get_unique_constraints("invoices")
    unique_indexes = [index for index in inspector.get_indexes("invoices") if index.get("unique")]
    if any(
        set(item.get("column_names") or []) == expected_columns
        for item in [*unique_constraints, *unique_indexes]
    ):
        return

    duplicates = connection.execute(
        text(
            """
            SELECT room_id, invoice_month, COUNT(*) AS duplicate_count
            FROM invoices
            GROUP BY room_id, invoice_month
            HAVING COUNT(*) > 1
            LIMIT 20
            """
        )
    ).mappings().all()
    if duplicates:
        details = ", ".join(
            f"room_id={row['room_id']} month={row['invoice_month']} count={row['duplicate_count']}"
            for row in duplicates
        )
        raise RuntimeError(
            "Không thể áp dụng ràng buộc hóa đơn duy nhất vì có dữ liệu trùng: " + details
        )

    connection.execute(
        text(
            "CREATE UNIQUE INDEX uq_invoices_room_month "
            "ON invoices (room_id, invoice_month)"
        )
    )


async def normalize_price_configs(db: AsyncSession) -> tuple[int, int]:
    """Normalize safely recognized legacy pricing rows; leave ambiguous rows untouched."""
    from sqlalchemy import select

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


async def seed_data(db: AsyncSession):
    from sqlalchemy import select

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

    await db.commit()
