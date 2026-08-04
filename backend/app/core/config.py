from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings


def _is_weak_or_placeholder_secret(secret: str) -> bool:
    stripped = secret.strip()
    if len(stripped) < 32 or len(set(stripped)) < 8:
        return True

    compact = "".join(character for character in stripped.lower() if character.isalnum())
    placeholder_prefixes = (
        "changeme",
        "defaultsecret",
        "examplesecret",
        "jwtsecret",
        "mysecret",
        "yoursecret",
        "replacewith",
        "supersecret",
        "testsecret",
    )
    return compact.startswith(placeholder_prefixes)


def _is_weak_or_placeholder_password(password: str) -> bool:
    stripped = password.strip()
    if len(stripped) < 12 or len(set(stripped)) < 6:
        return True

    compact = "".join(character for character in stripped.lower() if character.isalnum())
    return compact.startswith(
        ("admin", "changeme", "defaultpassword", "password", "replacewith", "testpassword")
    )


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_TITLE: str = "AI Báo Tiền Điện Cư Dân"
    APP_VERSION: str = "0.1.0"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Seed admin (development convenience; production must override password)
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_PASSWORD: str = "admin123"
    ADMIN_FULL_NAME: str = "Admin"

    # Google Gemini
    GEMINI_API_KEY: str = ""

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # Invoice payment info (shown on PDF invoice)
    PAYMENT_MANAGEMENT_UNIT: str = ""
    PAYMENT_BANK_ACCOUNT: str = ""
    PAYMENT_BANK_NAME: str = ""
    PAYMENT_ACCOUNT_HOLDER: str = ""

    # Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5MB
    MAX_BATCH_SIZE: int = 50

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def upload_path(self) -> Path:
        path = Path(self.UPLOAD_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.APP_ENV.lower() == "production":
            if _is_weak_or_placeholder_secret(self.SECRET_KEY):
                raise ValueError(
                    "SECRET_KEY production phải là giá trị ngẫu nhiên mạnh, ít nhất 32 ký tự"
                )
            if "*" in self.cors_origins_list:
                raise ValueError("CORS_ORIGINS không được dùng wildcard trong production")
            if _is_weak_or_placeholder_password(self.ADMIN_PASSWORD):
                raise ValueError(
                    "ADMIN_PASSWORD production phải là mật khẩu mạnh, không phải giá trị mẫu"
                )
        return self


settings = Settings()
