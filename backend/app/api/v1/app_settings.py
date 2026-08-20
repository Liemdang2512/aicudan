import logging
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.app_setting import AppSetting
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["Settings"])
logger = logging.getLogger(__name__)

RUNTIME_SYNC_NOTICE = (
    "Thông tin đã được lưu vào cơ sở dữ liệu và áp dụng ngay lập tức."
)


class AppSettingsResponse(BaseModel):
    gemini_api_key_set: bool
    telegram_bot_token_set: bool
    gemini_api_key_masked: str
    telegram_bot_token_masked: str
    payment_management_unit: str
    payment_bank_account: str
    payment_bank_name: str
    payment_account_holder: str
    telegram_ktv_bot_token_set: bool
    telegram_ktv_bot_token_masked: str
    telegram_ktv_password_set: bool
    manager_telegram_chat_id: str
    runtime_sync_notice: str = RUNTIME_SYNC_NOTICE
    ktv_webhook_ok: bool | None = None
    ktv_webhook_url: str | None = None
    ktv_webhook_message: str | None = None


class UpdateSettingsRequest(BaseModel):
    gemini_api_key: str | None = None
    telegram_bot_token: str | None = None
    payment_management_unit: str | None = None
    payment_bank_account: str | None = None
    payment_bank_name: str | None = None
    payment_account_holder: str | None = None
    telegram_ktv_bot_token: str | None = None
    telegram_ktv_password: str | None = None
    manager_telegram_chat_id: str | None = None


class ValidateSettingsRequest(BaseModel):
    provider: Literal["gemini", "telegram"]
    credential: str | None = None


class ValidateSettingsResponse(BaseModel):
    provider: Literal["gemini", "telegram"]
    valid: bool
    account_name: str | None = None


def _mask_key(key: str) -> str:
    if not key or key.startswith("your-"):
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


async def _get_or_create_setting(db: AsyncSession, owner_id: int) -> AppSetting:
    result = await db.execute(select(AppSetting).where(AppSetting.owner_id == owner_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppSetting(
            owner_id=owner_id,
            gemini_api_key=settings.GEMINI_API_KEY,
            telegram_bot_token="",
            payment_management_unit=settings.PAYMENT_MANAGEMENT_UNIT,
            payment_bank_account=settings.PAYMENT_BANK_ACCOUNT,
            payment_bank_name=settings.PAYMENT_BANK_NAME,
            payment_account_holder=settings.PAYMENT_ACCOUNT_HOLDER,
            telegram_ktv_bot_token="",
            telegram_ktv_password="",
            manager_telegram_chat_id="",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _setting_to_response(row: AppSetting) -> AppSettingsResponse:
    return AppSettingsResponse(
        gemini_api_key_set=bool(row.gemini_api_key and not row.gemini_api_key.startswith("your-")),
        telegram_bot_token_set=bool(
            row.telegram_bot_token and not row.telegram_bot_token.startswith("your-")
        ),
        gemini_api_key_masked=_mask_key(row.gemini_api_key),
        telegram_bot_token_masked=_mask_key(row.telegram_bot_token),
        payment_management_unit=row.payment_management_unit,
        payment_bank_account=row.payment_bank_account,
        payment_bank_name=row.payment_bank_name,
        payment_account_holder=row.payment_account_holder,
        telegram_ktv_bot_token_set=bool(
            row.telegram_ktv_bot_token and not row.telegram_ktv_bot_token.startswith("your-")
        ),
        telegram_ktv_bot_token_masked=_mask_key(row.telegram_ktv_bot_token),
        telegram_ktv_password_set=bool(row.telegram_ktv_password),
        manager_telegram_chat_id=row.manager_telegram_chat_id or "",
    )


async def _validate_provider(
    provider: Literal["gemini", "telegram"], credential: str
) -> str | None:
    if not credential or credential.startswith("your-"):
        raise HTTPException(status_code=400, detail="Thông tin xác thực đang trống")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if provider == "gemini":
                response = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": credential, "pageSize": 1},
                )
                response.raise_for_status()
                return None

            response = await client.get(f"https://api.telegram.org/bot{credential}/getMe")
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise HTTPException(status_code=400, detail="Telegram Bot Token không hợp lệ")
            return payload.get("result", {}).get("username")
    except HTTPException:
        raise
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(
            status_code=503, detail="Không thể kết nối nhà cung cấp để kiểm tra"
        ) from exc
    except (httpx.HTTPStatusError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Thông tin xác thực {provider} không hợp lệ"
        ) from exc


@router.get("", response_model=AppSettingsResponse)
async def get_settings(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_create_setting(db, current_user.id)
    return _setting_to_response(row)


@router.patch("", response_model=AppSettingsResponse)
async def update_settings(
    data: UpdateSettingsRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    credentials = {
        "gemini": data.gemini_api_key,
        "telegram": data.telegram_bot_token,
    }
    for provider, credential in credentials.items():
        if credential is not None:
            await _validate_provider(provider, credential)

    if data.telegram_ktv_bot_token is not None:
        await _validate_provider("telegram", data.telegram_ktv_bot_token)

    row = await _get_or_create_setting(db, current_user.id)

    if data.gemini_api_key is not None:
        row.gemini_api_key = data.gemini_api_key
        settings.GEMINI_API_KEY = data.gemini_api_key
        os.environ["GEMINI_API_KEY"] = data.gemini_api_key

    if data.telegram_bot_token is not None:
        row.telegram_bot_token = data.telegram_bot_token

    if data.telegram_ktv_bot_token is not None:
        row.telegram_ktv_bot_token = data.telegram_ktv_bot_token

    if data.telegram_ktv_password is not None:
        row.telegram_ktv_password = data.telegram_ktv_password

    if data.manager_telegram_chat_id is not None:
        row.manager_telegram_chat_id = data.manager_telegram_chat_id

    simple_fields = {
        "payment_management_unit": "PAYMENT_MANAGEMENT_UNIT",
        "payment_bank_account": "PAYMENT_BANK_ACCOUNT",
        "payment_bank_name": "PAYMENT_BANK_NAME",
        "payment_account_holder": "PAYMENT_ACCOUNT_HOLDER",
    }
    for attr, env_key in simple_fields.items():
        value = getattr(data, attr)
        if value is not None:
            setattr(row, attr, value)
            setattr(settings, env_key, value)
            os.environ[env_key] = value

    await db.commit()
    await db.refresh(row)

    if any(credential is not None for credential in credentials.values()):
        logger.info("Provider credentials updated in database")

    response = _setting_to_response(row)

    # Tự động đăng ký KTV webhook ngay khi token được cập nhật
    if data.telegram_ktv_bot_token and settings.SERVER_URL:
        server_url = settings.SERVER_URL.rstrip("/")
        webhook_url = f"{server_url}/api/v1/telegram/ktv/webhook/{current_user.id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"https://api.telegram.org/bot{data.telegram_ktv_bot_token}/setWebhook",
                    json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]},
                )
                result = r.json()
                response.ktv_webhook_ok = result.get("ok", False)
                response.ktv_webhook_url = webhook_url
                response.ktv_webhook_message = result.get("description", "")
                logger.info("KTV webhook auto-registered: ok=%s url=%s", response.ktv_webhook_ok, webhook_url)
        except Exception as exc:
            response.ktv_webhook_ok = False
            response.ktv_webhook_message = str(exc)
            logger.warning("Không thể tự đăng ký KTV webhook: %s", exc)

    return response


class SetupWebhookRequest(BaseModel):
    server_url: str  # e.g. https://yourdomain.com


class SetupWebhookResponse(BaseModel):
    ok: bool
    webhook_url: str
    description: str


@router.post("/setup-webhook", response_model=SetupWebhookResponse)
async def setup_telegram_webhook(
    data: SetupWebhookRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_create_setting(db, current_user.id)
    token = row.telegram_bot_token
    if not token:
        raise HTTPException(status_code=400, detail="Chưa cấu hình Telegram Bot Token")

    server_url = data.server_url.rstrip("/")
    webhook_url = f"{server_url}/api/v1/telegram/webhook"

    params: dict = {"url": webhook_url, "allowed_updates": ["message"]}
    if settings.TELEGRAM_WEBHOOK_SECRET:
        params["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json=params,
            )
            r.raise_for_status()
            result = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Không thể kết nối Telegram API: {exc}") from exc

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("description", "Đăng ký webhook thất bại"))

    return SetupWebhookResponse(
        ok=True,
        webhook_url=webhook_url,
        description=result.get("description", "Webhook đã được đăng ký"),
    )


@router.post("/setup-ktv-webhook", response_model=SetupWebhookResponse)
async def setup_ktv_telegram_webhook(
    data: SetupWebhookRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_or_create_setting(db, current_user.id)
    token = row.telegram_ktv_bot_token
    if not token:
        raise HTTPException(status_code=400, detail="Chưa cấu hình KTV Bot Token")
    server_url = data.server_url.rstrip("/")
    # Per-tenant KTV webhook URL uses owner_id path param
    webhook_url = f"{server_url}/api/v1/telegram/ktv/webhook/{current_user.id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]},
            )
            r.raise_for_status()
            result = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Không thể kết nối: {exc}") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("description", "Thất bại"))
    return SetupWebhookResponse(ok=True, webhook_url=webhook_url, description=result.get("description", "OK"))


@router.post("/validate", response_model=ValidateSettingsResponse)
async def validate_settings(
    data: ValidateSettingsRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    credential = data.credential
    if credential is None:
        row = await _get_or_create_setting(db, current_user.id)
        if data.provider == "gemini":
            credential = row.gemini_api_key or settings.GEMINI_API_KEY
        else:
            credential = row.telegram_bot_token
    account_name = await _validate_provider(data.provider, credential)
    return ValidateSettingsResponse(
        provider=data.provider,
        valid=True,
        account_name=account_name,
    )
