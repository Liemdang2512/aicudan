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
    runtime_sync_notice: str = RUNTIME_SYNC_NOTICE


class UpdateSettingsRequest(BaseModel):
    gemini_api_key: str | None = None
    telegram_bot_token: str | None = None


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

    if any(credential is not None for credential in credentials.values()):
        logger.info(
            "Provider credentials updated; other worker processes require restart to sync"
        )

    return AppSettingsResponse(
        gemini_api_key_set=bool(settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("your-")),
        telegram_bot_token_set=bool(settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your-")),
        gemini_api_key_masked=_mask_key(settings.GEMINI_API_KEY),
        telegram_bot_token_masked=_mask_key(settings.TELEGRAM_BOT_TOKEN),
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
