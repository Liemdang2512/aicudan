import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.init_db import create_tables, seed_data
from app.db.session import async_session, engine

logger = logging.getLogger(__name__)


async def _stamp_alembic_if_fresh() -> None:
    """Sau create_all trên fresh DB, stamp alembic_version = head.

    Cần thiết khi entrypoint.sh bỏ qua alembic upgrade (no DB file).
    Đảm bảo lần deploy tiếp theo alembic biết DB đã ở trạng thái mới nhất.
    """
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        async with engine.connect() as conn:
            def _check_and_stamp(sync_conn):
                ctx = MigrationContext.configure(sync_conn)
                if ctx.get_current_revision() is None:
                    ctx.stamp(script, head_rev)
                    logger.info("Fresh DB: alembic stamped to head (%s)", head_rev)

            await conn.run_sync(_check_and_stamp)
            await conn.commit()
    except Exception as exc:
        logger.warning("Could not stamp alembic version: %s", exc)


async def _hydrate_settings_from_db() -> None:
    """Nạp cài đặt từ app_settings DB vào settings in-memory.

    Đảm bảo sau container restart, notification_service và các service khác
    dùng token đã được cập nhật qua UI thay vì token cũ trong .env.
    """
    import os

    try:
        from sqlalchemy import select

        from app.models.app_setting import AppSetting

        async with async_session() as db:
            result = await db.execute(select(AppSetting).where(AppSetting.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                return

            field_map = {
                "gemini_api_key": ("GEMINI_API_KEY", "GEMINI_API_KEY"),
                "telegram_bot_token": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"),
                "telegram_ktv_bot_token": ("TELEGRAM_KTV_BOT_TOKEN", "TELEGRAM_KTV_BOT_TOKEN"),
                "telegram_ktv_password": ("TELEGRAM_KTV_PASSWORD", "TELEGRAM_KTV_PASSWORD"),
                "manager_telegram_chat_id": ("MANAGER_TELEGRAM_CHAT_ID", "MANAGER_TELEGRAM_CHAT_ID"),
                "payment_management_unit": ("PAYMENT_MANAGEMENT_UNIT", "PAYMENT_MANAGEMENT_UNIT"),
                "payment_bank_account": ("PAYMENT_BANK_ACCOUNT", "PAYMENT_BANK_ACCOUNT"),
                "payment_bank_name": ("PAYMENT_BANK_NAME", "PAYMENT_BANK_NAME"),
                "payment_account_holder": ("PAYMENT_ACCOUNT_HOLDER", "PAYMENT_ACCOUNT_HOLDER"),
            }
            for db_attr, (settings_attr, env_key) in field_map.items():
                value = getattr(row, db_attr, None)
                if value:
                    setattr(settings, settings_attr, value)
                    os.environ[env_key] = value

            logger.info("Settings hydrated from app_settings DB")
    except Exception as exc:
        logger.warning("Could not hydrate settings from DB: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_tables()
    await _stamp_alembic_if_fresh()
    async with async_session() as db:
        await seed_data(db)
    await _hydrate_settings_from_db()
    yield
    # Shutdown


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}
