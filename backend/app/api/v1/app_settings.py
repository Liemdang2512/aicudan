import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_admin
from app.core.config import settings
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["Settings"])
logger = logging.getLogger(__name__)
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
RUNTIME_SYNC_NOTICE = (
    "Thông tin đã được lưu cho lần khởi động sau và áp dụng trong process hiện tại; "
    "các worker khác cần được khởi động lại để đồng bộ."
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
    runtime_sync_notice: str = RUNTIME_SYNC_NOTICE


class UpdateSettingsRequest(BaseModel):
    gemini_api_key: str | None = None
    telegram_bot_token: str | None = None
    payment_management_unit: str | None = None
    payment_bank_account: str | None = None
    payment_bank_name: str | None = None
    payment_account_holder: str | None = None


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


def _update_env_file(key: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=422, detail="Thông tin xác thực không hợp lệ")

    env_path = ENV_PATH
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=env_path.parent,
            prefix=".env.",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            os.fchmod(temp_file.fileno(), 0o600)
            temp_file.write("\n".join(lines) + "\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, env_path)
        os.chmod(env_path, 0o600)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


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
):
    gemini_key = settings.GEMINI_API_KEY
    telegram_token = settings.TELEGRAM_BOT_TOKEN

    return AppSettingsResponse(
        gemini_api_key_set=bool(gemini_key and not gemini_key.startswith("your-")),
        telegram_bot_token_set=bool(telegram_token and not telegram_token.startswith("your-")),
        gemini_api_key_masked=_mask_key(gemini_key),
        telegram_bot_token_masked=_mask_key(telegram_token),
        payment_management_unit=settings.PAYMENT_MANAGEMENT_UNIT,
        payment_bank_account=settings.PAYMENT_BANK_ACCOUNT,
        payment_bank_name=settings.PAYMENT_BANK_NAME,
        payment_account_holder=settings.PAYMENT_ACCOUNT_HOLDER,
    )


@router.patch("", response_model=AppSettingsResponse)
async def update_settings(
    data: UpdateSettingsRequest,
    current_user: User = Depends(require_admin),
):
    credentials = {
        "gemini": data.gemini_api_key,
        "telegram": data.telegram_bot_token,
    }
    for provider, credential in credentials.items():
        if credential is not None:
            await _validate_provider(provider, credential)

    if data.gemini_api_key is not None:
        _update_env_file("GEMINI_API_KEY", data.gemini_api_key)
        settings.GEMINI_API_KEY = data.gemini_api_key
        os.environ["GEMINI_API_KEY"] = data.gemini_api_key

    if data.telegram_bot_token is not None:
        _update_env_file("TELEGRAM_BOT_TOKEN", data.telegram_bot_token)
        settings.TELEGRAM_BOT_TOKEN = data.telegram_bot_token
        os.environ["TELEGRAM_BOT_TOKEN"] = data.telegram_bot_token

    simple_fields = {
        "payment_management_unit": "PAYMENT_MANAGEMENT_UNIT",
        "payment_bank_account": "PAYMENT_BANK_ACCOUNT",
        "payment_bank_name": "PAYMENT_BANK_NAME",
        "payment_account_holder": "PAYMENT_ACCOUNT_HOLDER",
    }
    for attr, env_key in simple_fields.items():
        value = getattr(data, attr)
        if value is not None:
            _update_env_file(env_key, value)
            setattr(settings, env_key, value)
            os.environ[env_key] = value

    if any(credential is not None for credential in credentials.values()):
        logger.info(
            "Provider credentials updated; other worker processes require restart to sync"
        )

    return AppSettingsResponse(
        gemini_api_key_set=bool(settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("your-")),
        telegram_bot_token_set=bool(settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your-")),
        gemini_api_key_masked=_mask_key(settings.GEMINI_API_KEY),
        telegram_bot_token_masked=_mask_key(settings.TELEGRAM_BOT_TOKEN),
        payment_management_unit=settings.PAYMENT_MANAGEMENT_UNIT,
        payment_bank_account=settings.PAYMENT_BANK_ACCOUNT,
        payment_bank_name=settings.PAYMENT_BANK_NAME,
        payment_account_holder=settings.PAYMENT_ACCOUNT_HOLDER,
    )


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
):
    token = settings.TELEGRAM_BOT_TOKEN
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


@router.post("/validate", response_model=ValidateSettingsResponse)
async def validate_settings(
    data: ValidateSettingsRequest,
    current_user: User = Depends(require_admin),
):
    credential = data.credential
    if credential is None:
        credential = (
            settings.GEMINI_API_KEY
            if data.provider == "gemini"
            else settings.TELEGRAM_BOT_TOKEN
        )
    account_name = await _validate_provider(data.provider, credential)
    return ValidateSettingsResponse(
        provider=data.provider,
        valid=True,
        account_name=account_name,
    )
