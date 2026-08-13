from fastapi import APIRouter

from app.api.v1 import (
    app_settings,
    auth,
    buildings,
    dashboard,
    invoices,
    notifications,
    price_configs,
    readings,
    rooms,
    telegram_bot,
    telegram_bot_ktv,
    users,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(buildings.router)
api_router.include_router(rooms.router)
api_router.include_router(price_configs.router)
api_router.include_router(readings.router)
api_router.include_router(invoices.router)
api_router.include_router(notifications.router)
api_router.include_router(dashboard.router)
api_router.include_router(app_settings.router)
api_router.include_router(telegram_bot.router)
api_router.include_router(telegram_bot_ktv.router)
