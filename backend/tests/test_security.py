"""Security regression tests for credentials, providers, and seed data."""
import logging
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password, verify_token
from app.db import init_db
from app.models.user import User
from app.services.ai_service import AIService
from app.services.notification_service import send_telegram_message


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        hashed = hash_password("mypassword")
        assert isinstance(hashed, str)
        assert hashed != "mypassword"

    def test_verify_password_correct(self):
        hashed = hash_password("admin123")
        assert verify_password("admin123", hashed) is True

    def test_verify_password_wrong(self):
        hashed = hash_password("admin123")
        assert verify_password("wrongpass", hashed) is False

    def test_hash_different_each_time(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts


class TestJWT:
    def test_create_and_verify_token(self):
        data = {"user_id": 1, "email": "test@test.com", "role": "admin"}
        token = create_access_token(data)
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload is not None
        assert payload["user_id"] == 1
        assert payload["email"] == "test@test.com"
        assert "exp" in payload
        assert "iat" in payload

    def test_verify_invalid_token(self):
        result = verify_token("invalid.token.here")
        assert result is None

    def test_verify_tampered_token(self):
        token = create_access_token({"user_id": 1})
        tampered = token[:-5] + "XXXXX"
        result = verify_token(tampered)
        assert result is None

    def test_token_contains_custom_data(self):
        data = {"user_id": 42, "role": "admin"}
        token = create_access_token(data)
        payload = verify_token(token)
        assert payload["user_id"] == 42
        assert payload["role"] == "admin"


class TestProductionSettings:
    @pytest.mark.parametrize(
        "secret",
        [
            "",
            "short-secret",
            "change-me-in-production",
            "your-secret-key-change-in-production",
            "replace-with-a-strong-secret-key",
            "changemechangemechangemechangeme",
            "jwt-secret-for-production-environment",
            "default-secret-default-secret-default",
            "a" * 32,
        ],
    )
    def test_rejects_placeholder_or_weak_secret_in_production(self, secret):
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(
                APP_ENV="production",
                SECRET_KEY=secret,
                CORS_ORIGINS="https://dien.example.com",
                ADMIN_PASSWORD="a-strong-production-password",
            )

    def test_accepts_strong_secret_and_explicit_cors(self):
        config = Settings(
            APP_ENV="production",
            SECRET_KEY="a-production-secret-with-32-characters",
            CORS_ORIGINS="https://dien.example.com",
            ADMIN_PASSWORD="a-strong-production-password",
        )

        assert config.APP_ENV == "production"

    def test_rejects_wildcard_cors_in_production(self):
        with pytest.raises(ValidationError, match="CORS_ORIGINS"):
            Settings(
                APP_ENV="production",
                SECRET_KEY="a-production-secret-with-32-characters",
                CORS_ORIGINS="*",
                ADMIN_PASSWORD="a-strong-production-password",
            )

    @pytest.mark.parametrize(
        "password",
        ["admin123", "replace-with-a-strong-password", "password-password", "a" * 12],
    )
    def test_rejects_seed_or_placeholder_password_in_production(self, password):
        with pytest.raises(ValidationError, match="ADMIN_PASSWORD"):
            Settings(
                APP_ENV="production",
                SECRET_KEY="a-production-secret-with-32-characters",
                ADMIN_PASSWORD=password,
            )


@pytest.mark.asyncio
async def test_seed_data_rotates_legacy_admin_password_in_production(db_session, monkeypatch):
    admin = User(
        email="admin@admin.com",
        password_hash=hash_password("admin123"),
        full_name="Admin",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()

    monkeypatch.setattr(
        init_db,
        "settings",
        SimpleNamespace(
            APP_ENV="production",
            ADMIN_EMAIL="admin@admin.com",
            ADMIN_PASSWORD="a-strong-production-password",
            ADMIN_FULL_NAME="Admin",
        ),
    )

    await init_db.seed_data(db_session)
    await db_session.refresh(admin)

    assert verify_password("a-strong-production-password", admin.password_hash)
    assert not verify_password("admin123", admin.password_hash)


@pytest.mark.asyncio
async def test_seed_data_preserves_changed_admin_password_in_production(db_session, monkeypatch):
    changed_hash = hash_password("already-changed-password")
    admin = User(
        email="admin@admin.com",
        password_hash=changed_hash,
        full_name="Admin",
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()

    monkeypatch.setattr(
        init_db,
        "settings",
        SimpleNamespace(
            APP_ENV="production",
            ADMIN_EMAIL="admin@admin.com",
            ADMIN_PASSWORD="a-strong-production-password",
            ADMIN_FULL_NAME="Admin",
        ),
    )

    await init_db.seed_data(db_session)
    await db_session.refresh(admin)

    assert admin.password_hash == changed_hash
    assert verify_password("already-changed-password", admin.password_hash)


@pytest.mark.asyncio
async def test_ai_provider_error_is_redacted_from_logs_and_notes(tmp_path, monkeypatch, caplog):
    from PIL import Image

    leaked_error = "provider failed with key=gemini-secret-value"

    class FailingModels:
        def generate_content(self, **kwargs):
            raise RuntimeError(leaked_error)

    monkeypatch.setattr(
        AIService,
        "get_client",
        lambda self: SimpleNamespace(models=FailingModels()),
    )
    image_path = tmp_path / "meter.png"
    Image.new("RGB", (2, 2)).save(image_path)

    with caplog.at_level(logging.ERROR):
        result = await AIService().extract_meter_reading(str(image_path))

    assert leaked_error not in caplog.text
    assert leaked_error not in result["notes"]
    assert "gemini-secret-value" not in caplog.text
    assert "gemini-secret-value" not in result["notes"]


@pytest.mark.asyncio
async def test_telegram_provider_error_redacts_chat_and_credentials(monkeypatch, caplog):
    from app.services import notification_service

    token = "telegram-secret-token"
    chat_id = "private-chat-id"
    leaked_error = "provider rejected telegram-secret-token"

    class FailingBot:
        def __init__(self, token):
            self.token = token

        async def send_message(self, **kwargs):
            raise RuntimeError(leaked_error)

    monkeypatch.setattr(notification_service.settings, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setitem(sys.modules, "telegram", SimpleNamespace(Bot=FailingBot))

    with caplog.at_level(logging.ERROR):
        sent = await send_telegram_message(chat_id, "Invoice")

    assert sent is False
    assert token not in caplog.text
    assert chat_id not in caplog.text
    assert leaked_error not in caplog.text
