import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.building import Building
from app.models.invoice import Invoice
from app.models.price_config import PriceConfig
from app.models.reading import MeterReading
from app.models.room import Room
from app.models.user import User

# Test database - in-memory SQLite
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_async_session() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email="test@test.com",
        password_hash=hash_password("test123"),
        full_name="Test User",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict:
    token = create_access_token({"user_id": test_user.id, "email": test_user.email, "role": test_user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_building(db_session: AsyncSession, test_user: User) -> Building:
    building = Building(
        owner_id=test_user.id,
        name="Tòa nhà A",
        address="123 Đường ABC",
    )
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
        resident_phone="0901234567",
        initial_reading=1000,
    )
    db_session.add(room)
    await db_session.commit()
    await db_session.refresh(room)
    return room


@pytest_asyncio.fixture
async def test_evn_price_config(db_session: AsyncSession) -> PriceConfig:
    config = PriceConfig(
        config_name="EVN Bậc Thang 2025",
        pricing_type="tiered",
        config_json=json.dumps({
            "tiers": [
                {"min": 0, "max": 50, "price": 1984, "name": "Bậc 1"},
                {"min": 51, "max": 100, "price": 2050, "name": "Bậc 2"},
                {"min": 101, "max": 200, "price": 2380, "name": "Bậc 3"},
                {"min": 201, "max": 300, "price": 2998, "name": "Bậc 4"},
                {"min": 301, "max": 400, "price": 3350, "name": "Bậc 5"},
                {"min": 401, "max": None, "price": 3460, "name": "Bậc 6"},
            ],
            "vat": 0.08,
        }),
        is_default=True,
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    return config


@pytest_asyncio.fixture
async def test_fixed_price_config(db_session: AsyncSession) -> PriceConfig:
    config = PriceConfig(
        config_name="Giá Cố Định 3500đ",
        pricing_type="fixed",
        config_json=json.dumps({"price": 3500}),
        is_default=False,
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    return config


@pytest_asyncio.fixture
async def test_reading(db_session: AsyncSession, test_room: Room) -> MeterReading:
    reading = MeterReading(
        room_id=test_room.id,
        reading_date=date(2025, 1, 15),
        meter_value=1150,
        confidence_score=0.95,
        status="approved",
    )
    db_session.add(reading)
    await db_session.commit()
    await db_session.refresh(reading)
    return reading


@pytest_asyncio.fixture
async def test_invoice(db_session: AsyncSession, test_room: Room, test_reading: MeterReading) -> Invoice:
    invoice = Invoice(
        room_id=test_room.id,
        reading_id=test_reading.id,
        invoice_month="2025-01",
        previous_reading=1000,
        current_reading=1150,
        consumption=150,
        price_breakdown=json.dumps({
            "tiers": [{"name": "Bậc 1", "kwh": 50, "price": 1984, "amount": 99200}],
            "subtotal": 99200,
            "vat_rate": 0.08,
            "vat_amount": 7936,
            "total": 107136,
        }),
        electricity_amount=107136,
        total_amount=107136,
    )
    db_session.add(invoice)
    await db_session.commit()
    await db_session.refresh(invoice)
    return invoice


@pytest_asyncio.fixture
async def second_user(db_session: AsyncSession) -> User:
    user = User(
        email="other-owner@test.com",
        password_hash=hash_password("test123"),
        full_name="Other Owner",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def second_auth_headers(second_user: User) -> dict[str, str]:
    token = create_access_token(
        {
            "user_id": second_user.id,
            "email": second_user.email,
            "role": second_user.role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_building(db_session: AsyncSession, second_user: User) -> Building:
    building = Building(
        owner_id=second_user.id,
        name="Tòa nhà B",
        address="456 Đường XYZ",
    )
    db_session.add(building)
    await db_session.commit()
    await db_session.refresh(building)
    return building


@pytest_asyncio.fixture
async def second_room(db_session: AsyncSession, second_building: Building) -> Room:
    room = Room(
        building_id=second_building.id,
        room_number="201",
        resident_name="Trần Văn B",
        initial_reading=2000,
    )
    db_session.add(room)
    await db_session.commit()
    await db_session.refresh(room)
    return room


@pytest_asyncio.fixture
async def second_reading(db_session: AsyncSession, second_room: Room) -> MeterReading:
    reading = MeterReading(
        room_id=second_room.id,
        reading_date=date(2025, 1, 20),
        meter_value=2150,
        confidence_score=0.99,
        status="approved",
    )
    db_session.add(reading)
    await db_session.commit()
    await db_session.refresh(reading)
    return reading


@pytest_asyncio.fixture
async def second_invoice(
    db_session: AsyncSession,
    second_room: Room,
    second_reading: MeterReading,
) -> Invoice:
    invoice = Invoice(
        room_id=second_room.id,
        reading_id=second_reading.id,
        invoice_month="2025-01",
        previous_reading=2000,
        current_reading=2150,
        consumption=150,
        electricity_amount=525000,
        total_amount=525000,
    )
    db_session.add(invoice)
    await db_session.commit()
    await db_session.refresh(invoice)
    return invoice
