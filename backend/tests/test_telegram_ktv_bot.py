import pytest
import pytest_asyncio
from datetime import date
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from app.db.base import Base
from app.models.bot_session import BotSession
from app.models.building import Building
from app.models.room import Room
from app.models.reading import MeterReading
from app.models.technician_profile import TechnicianProfile
from app.core.config import settings

# In-memory SQLite DB cho tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
def setup_settings():
    """Configure settings for tests."""
    original_ktv_password = settings.TELEGRAM_KTV_PASSWORD
    original_ktv_token = settings.TELEGRAM_KTV_BOT_TOKEN
    original_manager_chat = settings.MANAGER_TELEGRAM_CHAT_ID
    settings.TELEGRAM_KTV_PASSWORD = "test_ktv_pass"
    settings.TELEGRAM_KTV_BOT_TOKEN = "test_ktv_token"
    settings.MANAGER_TELEGRAM_CHAT_ID = "999888777"
    yield
    settings.TELEGRAM_KTV_PASSWORD = original_ktv_password
    settings.TELEGRAM_KTV_BOT_TOKEN = original_ktv_token
    settings.MANAGER_TELEGRAM_CHAT_ID = original_manager_chat


@pytest.mark.asyncio
async def test_ktv_auth_correct_password_first_time(db):
    """Lần đầu dùng bot với đúng password → ask for name."""
    from app.api.v1.telegram_bot_ktv import _cmd_ktv_auth, _get_ktv_session, KTV_AWAITING_NAME

    chat_id = 111111
    session = await _get_ktv_session(db, chat_id)

    sent_messages = []
    async def mock_send(cid, text, markup=None):
        sent_messages.append(text)
        return 1

    with patch("app.api.v1.telegram_bot_ktv._ktv_send", side_effect=mock_send):
        await _cmd_ktv_auth(chat_id, "/ktv test_ktv_pass", session, db)

    assert session.is_admin is True
    assert session.state == KTV_AWAITING_NAME
    assert any("Tên" in m or "tên" in m for m in sent_messages), f"Expected name prompt, got: {sent_messages}"


@pytest.mark.asyncio
async def test_ktv_auth_wrong_password(db):
    """Sai password → is_admin vẫn False."""
    from app.api.v1.telegram_bot_ktv import _cmd_ktv_auth, _get_ktv_session, KTV_IDLE

    chat_id = 111112
    session = await _get_ktv_session(db, chat_id)

    sent_messages = []
    async def mock_send(cid, text, markup=None):
        sent_messages.append(text)
        return 1

    with patch("app.api.v1.telegram_bot_ktv._ktv_send", side_effect=mock_send):
        await _cmd_ktv_auth(chat_id, "/ktv wrong_password", session, db)

    assert session.is_admin is False
    assert any("không đúng" in m.lower() or "sai" in m.lower() or "❌" in m for m in sent_messages)


@pytest.mark.asyncio
async def test_ktv_profile_setup_flow(db):
    """First-time setup: nhập tên → nhập SĐT → TechnicianProfile được tạo."""
    from app.api.v1.telegram_bot_ktv import (
        _cmd_ktv_auth, _get_ktv_session, _handle_ktv_name_input, _handle_ktv_phone_input,
        KTV_AWAITING_NAME, KTV_AWAITING_PHONE, KTV_IDLE, _get_profile
    )

    chat_id = 111113
    session = await _get_ktv_session(db, chat_id)

    sent_messages = []
    async def mock_send(cid, text, markup=None):
        sent_messages.append(text)
        return 1

    with patch("app.api.v1.telegram_bot_ktv._ktv_send", side_effect=mock_send):
        # Auth → goes to awaiting_name
        await _cmd_ktv_auth(chat_id, "/ktv test_ktv_pass", session, db)
        assert session.state == KTV_AWAITING_NAME

        # Nhập tên
        await _handle_ktv_name_input(chat_id, "Nguyễn Văn A", session, db)
        assert session.state == KTV_AWAITING_PHONE

        # Nhập SĐT
        await _handle_ktv_phone_input(chat_id, "0901234567", session, db)

    # Verify profile in DB
    profile = await _get_profile(db, chat_id)
    assert profile is not None
    assert profile.ktv_name == "Nguyễn Văn A"
    assert profile.ktv_phone == "0901234567"
    assert session.state == KTV_IDLE


@pytest.mark.asyncio
async def test_ktv_summary_saves_staged_readings(db):
    """Sau khi confirm, readings được lưu với status='staged' và submitted_by=ktv_name."""
    from app.api.v1.telegram_bot_ktv import (
        _cb_ktv_summary_ok, _get_ktv_session, _save_data, KTV_IDLE
    )

    chat_id = 111114

    # Setup: tạo TechnicianProfile
    profile = TechnicianProfile(chat_id=chat_id, ktv_name="KTV Test", ktv_phone="0900000000")
    db.add(profile)

    b = Building(name="Test Building", address="123", is_active=True, owner_id=1)
    db.add(b)
    await db.flush()

    # Setup: tạo Room trong DB
    room = Room(
        room_number="101", building_id=b.id, is_active=True,
        initial_reading=0
    )
    db.add(room)
    await db.flush()

    # Setup: BotSession
    session = await _get_ktv_session(db, chat_id)
    session.is_admin = True
    _save_data(session, {"month": "2026-08", "pending": None})

    # Setup: pre_staged MeterReading (thay vì lưu trong session_data JSON)
    pre_staged = MeterReading(
        room_id=room.id,
        reading_date=date(2026, 8, 1),
        meter_value=1500,
        image_path=None,
        confidence_score=0.95,
        status="pre_staged",
        notes=f"[KTV:{chat_id}]",
    )
    db.add(pre_staged)
    await db.commit()

    sent_messages = []
    async def mock_send(cid, text, markup=None):
        sent_messages.append(text)
        return 1

    async def mock_notify(count, ktv_name, month, building_name=""):
        pass  # Không gọi API thật

    with patch("app.api.v1.telegram_bot_ktv._ktv_send", side_effect=mock_send), \
         patch("app.api.v1.telegram_bot_ktv._notify_manager", side_effect=mock_notify):
        await _cb_ktv_summary_ok(chat_id, session, db)

    # Verify MeterReading trong DB
    result = await db.execute(select(MeterReading).where(MeterReading.room_id == room.id))
    reading = result.scalar_one_or_none()
    assert reading is not None
    assert reading.status == "staged", f"Expected 'staged', got '{reading.status}'"
    assert reading.submitted_by == "KTV Test", f"Expected 'KTV Test', got '{reading.submitted_by}'"
    assert reading.meter_value == 1500


@pytest.mark.asyncio
async def test_ktv_notify_manager_message_format():
    """_notify_manager gửi message với format đúng qua Bot Manager token."""
    from app.api.v1.telegram_bot_ktv import _notify_manager

    manager_api_calls = []
    async def mock_manager_api(method, **kwargs):
        manager_api_calls.append({"method": method, **kwargs})
        return {"ok": True}

    with patch("app.api.v1.telegram_bot_ktv._manager_api", side_effect=mock_manager_api):
        await _notify_manager(count=5, ktv_name="Trần Văn B", month="2026-08")

    assert len(manager_api_calls) == 1
    call = manager_api_calls[0]
    assert call["method"] == "sendMessage"
    assert call["chat_id"] == int(settings.MANAGER_TELEGRAM_CHAT_ID)
    msg = call["text"]
    assert "5" in msg
    assert "Trần Văn B" in msg
    assert "8/2026" in msg or "8" in msg
    assert "/duyet" in msg


@pytest.mark.asyncio
async def test_ktv_notify_manager_skip_if_no_chat_id():
    """Nếu MANAGER_TELEGRAM_CHAT_ID rỗng, không gọi API."""
    from app.api.v1.telegram_bot_ktv import _notify_manager

    api_calls = []
    async def mock_manager_api(method, **kwargs):
        api_calls.append(method)

    original = settings.MANAGER_TELEGRAM_CHAT_ID
    settings.MANAGER_TELEGRAM_CHAT_ID = ""
    try:
        with patch("app.api.v1.telegram_bot_ktv._manager_api", side_effect=mock_manager_api):
            await _notify_manager(count=3, ktv_name="Test", month="2026-08")
        assert len(api_calls) == 0
    finally:
        settings.MANAGER_TELEGRAM_CHAT_ID = original
