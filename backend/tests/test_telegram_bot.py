"""Tests cho Telegram chatbot agent (chủ tòa flow)."""

import json

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.telegram_bot as bot_module
from app.api.v1.telegram_bot import (
    ST_AWAITING_MONTH,
    ST_COLLECTING,
    ST_CONFIRMING,
    ST_EDITING_ROOM,
    ST_EDITING_VALUE,
    ST_IDLE,
    ST_REVIEWING,
    _get_session,
    _load_data,
    _parse_month,
)
from app.models.bot_session import BotSession
from app.models.building import Building
from app.models.price_config import PriceConfig
from app.models.room import Room
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADMIN_CHAT_ID = 999_001
OTHER_CHAT_ID = 999_002


@pytest_asyncio.fixture
async def admin_session(db_session: AsyncSession) -> BotSession:
    session = BotSession(chat_id=ADMIN_CHAT_ID, is_admin=True, state=ST_IDLE)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest_asyncio.fixture
async def test_building(db_session: AsyncSession) -> Building:

    user = User(
        email="admin@admin.com",
        full_name="Admin",
        password_hash="x",
        is_active=True,
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()

    building = Building(owner_id=user.id, name="Tòa A", is_active=True)
    db_session.add(building)
    await db_session.commit()
    await db_session.refresh(building)
    return building


@pytest_asyncio.fixture
async def test_room(db_session: AsyncSession, test_building: Building) -> Room:
    room = Room(
        building_id=test_building.id,
        room_number="101",
        resident_name="Nguyễn Văn A",
        telegram_id="123456789",
        is_active=True,
        initial_reading=1000,
    )
    db_session.add(room)
    await db_session.commit()
    await db_session.refresh(room)
    return room


@pytest_asyncio.fixture
async def test_price_config(db_session: AsyncSession) -> PriceConfig:
    price_config = PriceConfig(
        config_name="Giá cố định",
        pricing_type="fixed",
        config_json=json.dumps({"price": 3460, "vat": 0.1}),
        is_active=True,
        is_default=True,
    )
    db_session.add(price_config)
    await db_session.commit()
    await db_session.refresh(price_config)
    return price_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(chat_id: int, text: str) -> dict:
    return {
        "message": {
            "chat": {"id": chat_id},
            "text": text,
        }
    }


def _make_callback(chat_id: int, data: str, msg_id: int = 1) -> dict:
    return {
        "callback_query": {
            "id": "cb001",
            "data": data,
            "message": {"chat": {"id": chat_id}, "message_id": msg_id},
        }
    }


def _make_photo(chat_id: int, file_id: str = "file123") -> dict:
    return {
        "message": {
            "chat": {"id": chat_id},
            "photo": [{"file_id": file_id, "file_size": 100}],
        }
    }


# ---------------------------------------------------------------------------
# Webhook security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_no_secret_passes(client: AsyncClient) -> None:
    response = await client.post("/api/v1/telegram/webhook", json={})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_webhook_wrong_secret_rejected(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.TELEGRAM_WEBHOOK_SECRET", "correctsecret")
    response = await client.post(
        "/api/v1/telegram/webhook",
        json={},
        headers={"x-telegram-bot-api-secret-token": "wrongsecret"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Unauthenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_message_prompts_auth(
    db_session: AsyncSession, monkeypatch
) -> None:
    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    # Override async_session to use test db
    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(OTHER_CHAT_ID, "hello"))

    assert any("quản lý" in (m.get("text") or "") for m in sent)


@pytest.mark.asyncio
async def test_wrong_admin_password_rejected(
    db_session: AsyncSession, monkeypatch
) -> None:
    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(OTHER_CHAT_ID, "/admin WRONGPASSWORD"))

    assert any("không đúng" in (m.get("text") or "").lower() for m in sent)

    # Session vẫn chưa là admin
    session = await _get_session(db_session, OTHER_CHAT_ID)
    assert not session.is_admin


@pytest.mark.asyncio
async def test_correct_admin_password_authenticates(
    db_session: AsyncSession, monkeypatch
) -> None:
    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)
    monkeypatch.setattr("app.core.config.settings.ADMIN_PASSWORD", "TestPass123!")

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(OTHER_CHAT_ID, "/admin TestPass123!"))

    assert any("thành công" in (m.get("text") or "").lower() for m in sent)

    session = await _get_session(db_session, OTHER_CHAT_ID)
    assert session.is_admin


# ---------------------------------------------------------------------------
# /baodien flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baodien_sets_awaiting_month(
    db_session: AsyncSession, admin_session: BotSession, test_building: Building, monkeypatch
) -> None:
    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, "/baodien"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_AWAITING_MONTH
    assert any("tháng" in (m.get("text") or "").lower() for m in sent)


@pytest.mark.asyncio
async def test_month_input_sets_collecting(
    db_session: AsyncSession, admin_session: BotSession, monkeypatch
) -> None:
    admin_session.state = ST_AWAITING_MONTH
    await db_session.commit()

    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, "tháng 8"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_COLLECTING
    data = _load_data(admin_session)
    assert data["month"] == f"{__import__('datetime').date.today().year}-08"


# ---------------------------------------------------------------------------
# Callback confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_confirm_ok_moves_to_collecting(
    db_session: AsyncSession, admin_session: BotSession, test_room: Room, monkeypatch
) -> None:
    admin_session.state = ST_CONFIRMING
    admin_session.session_data = json.dumps(
        {
            "month": "2026-08",
            "readings": [],
            "pending": {
                "room_id": test_room.id,
                "room_number": test_room.room_number,
                "meter_value": 1234,
                "image_path": "",
                "confidence": 0.95,
            },
        }
    )
    await db_session.commit()

    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method in ("sendMessage", "answerCallbackQuery"):
            sent.append({"method": method, **kwargs})
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_callback(ADMIN_CHAT_ID, "c:ok"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_COLLECTING
    data = _load_data(admin_session)
    assert len(data["readings"]) == 1
    assert data["readings"][0]["meter_value"] == 1234


@pytest.mark.asyncio
async def test_callback_skip_discards_pending(
    db_session: AsyncSession, admin_session: BotSession, monkeypatch
) -> None:
    admin_session.state = ST_CONFIRMING
    admin_session.session_data = json.dumps(
        {
            "month": "2026-08",
            "readings": [],
            "pending": {"room_id": 1, "room_number": "101", "meter_value": 999},
        }
    )
    await db_session.commit()

    async def mock_api(method: str, **kwargs) -> dict:
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_callback(ADMIN_CHAT_ID, "c:skip"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_COLLECTING
    data = _load_data(admin_session)
    assert data["pending"] is None
    assert data["readings"] == []


# ---------------------------------------------------------------------------
# /xong flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xong_with_no_readings_sends_error(
    db_session: AsyncSession, admin_session: BotSession, monkeypatch
) -> None:
    admin_session.state = ST_COLLECTING
    admin_session.session_data = json.dumps({"month": "2026-08", "readings": [], "pending": None})
    await db_session.commit()

    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, "/xong"))

    # State should remain (not moved to reviewing)
    await db_session.refresh(admin_session)
    assert admin_session.state == ST_COLLECTING
    assert any("chưa có" in (m.get("text") or "").lower() for m in sent)


@pytest.mark.asyncio
async def test_xong_with_readings_moves_to_reviewing(
    db_session: AsyncSession, admin_session: BotSession, test_room: Room, monkeypatch
) -> None:
    admin_session.state = ST_COLLECTING
    admin_session.session_data = json.dumps(
        {
            "month": "2026-08",
            "readings": [
                {
                    "room_id": test_room.id,
                    "room_number": "101",
                    "meter_value": 1234,
                    "image_path": "",
                    "confidence": 0.9,
                }
            ],
            "pending": None,
        }
    )
    await db_session.commit()

    sent: list[dict] = []

    async def mock_api(method: str, **kwargs) -> dict:
        if method == "sendMessage":
            sent.append(kwargs)
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, "/xong"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_REVIEWING


# ---------------------------------------------------------------------------
# /huy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_huy_resets_session(
    db_session: AsyncSession, admin_session: BotSession, monkeypatch
) -> None:
    admin_session.state = ST_COLLECTING
    admin_session.session_data = json.dumps({"month": "2026-08", "readings": []})
    await db_session.commit()

    async def mock_api(method: str, **kwargs) -> dict:
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, "/huy"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_IDLE
    assert admin_session.session_data is None


# ---------------------------------------------------------------------------
# _parse_month unit tests
# ---------------------------------------------------------------------------


def test_parse_month_yyyy_mm() -> None:
    assert _parse_month("2026-08") == "2026-08"


def test_parse_month_thang_n() -> None:
    from datetime import date

    year = date.today().year
    assert _parse_month("tháng 8") == f"{year}-08"
    assert _parse_month("thang 3") == f"{year}-03"


def test_parse_month_mm_yyyy() -> None:
    assert _parse_month("08/2026") == "2026-08"


def test_parse_month_single_digit() -> None:
    from datetime import date

    year = date.today().year
    assert _parse_month("8") == f"{year}-08"


def test_parse_month_invalid() -> None:
    assert _parse_month("không phải tháng") is None
    assert _parse_month("99") is None


# ---------------------------------------------------------------------------
# Edit value / room input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_value_valid_input(
    db_session: AsyncSession, admin_session: BotSession, monkeypatch
) -> None:
    admin_session.state = ST_EDITING_VALUE
    admin_session.session_data = json.dumps(
        {"pending": {"room_id": 1, "room_number": "101", "meter_value": None}}
    )
    await db_session.commit()

    async def mock_api(method: str, **kwargs) -> dict:
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, "1,500"))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_CONFIRMING
    data = _load_data(admin_session)
    assert data["pending"]["meter_value"] == 1500


@pytest.mark.asyncio
async def test_edit_room_valid_input(
    db_session: AsyncSession, admin_session: BotSession, test_room: Room, monkeypatch
) -> None:
    admin_session.state = ST_EDITING_ROOM
    admin_session.session_data = json.dumps(
        {"pending": {"room_id": None, "room_number": None, "meter_value": 1200}}
    )
    await db_session.commit()

    async def mock_api(method: str, **kwargs) -> dict:
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot_module, "_api", mock_api)

    from unittest.mock import AsyncMock, MagicMock

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(bot_module, "async_session", lambda: session_ctx)

    await bot_module._dispatch(_make_message(ADMIN_CHAT_ID, test_room.room_number))

    await db_session.refresh(admin_session)
    assert admin_session.state == ST_CONFIRMING
    data = _load_data(admin_session)
    assert data["pending"]["room_id"] == test_room.id
