"""Telegram chatbot agent cho chủ tòa báo điện.

Flow:
  /admin PASSWORD  → xác thực quản lý
  /duyet           → xem danh sách chỉ số staged từ KTV → duyệt/từ chối từng reading
                     → chọn tòa / bảng giá → xem hóa đơn → gửi cư dân
  /id              → xem Chat ID để cấu hình App Settings
  /huy             → hủy thao tác hiện tại

Thiết kế:
  - Mỗi Telegram chat được lưu trạng thái trong bảng `bot_sessions` (SQLite)
    với composite PK (chat_id, bot_type="manager").
  - Admin xác thực bằng mật khẩu ADMIN_PASSWORD trong settings.
  - Bot chỉ phục vụ chủ tòa; KTV dùng bot riêng (telegram_bot_ktv.py).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session
from app.models.bot_session import BotSession
from app.models.building import Building
from app.models.invoice import Invoice
from app.models.price_config import PriceConfig
from app.models.reading import MeterReading
from app.models.room import Room
from app.services.billing_service import calculate_invoice
from app.services.notification_service import format_invoice_message, send_telegram_message

router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

ST_IDLE = "idle"
ST_SELECTING_BUILDING = "selecting_building"
ST_SELECTING_PRICE = "selecting_price"
ST_REVIEWING_INVOICES = "reviewing_invoices"
ST_REVIEWING_STAGED = "reviewing_staged"
ST_CONFIRMING_DUYET = "confirming_duyet"

# Callback data tokens
CB_INVOICE_SEND = "i:send"
CB_INVOICE_CANCEL = "i:cancel"
CB_BUILDING = "b:"
CB_PRICE = "p:"
CB_DUYET_APPROVE = "d:ok:"
CB_DUYET_REJECT = "d:no:"
CB_DUYET_DONE = "d:done"
CB_DUYET_ALL = "d:all"

# ---------------------------------------------------------------------------
# Low-level Telegram API helpers
# ---------------------------------------------------------------------------


def _token() -> str:
    return settings.TELEGRAM_BOT_TOKEN


async def _api(method: str, **kwargs) -> dict | None:  # type: ignore[type-arg]
    token = _token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN chưa được cấu hình")
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json=kwargs,
            )
            return r.json()
    except Exception as exc:
        logger.warning("Telegram API %s thất bại: %s", method, exc)
        return None


async def _send(chat_id: int, text: str, reply_markup: dict | None = None) -> int | None:  # type: ignore[type-arg]
    """Gửi tin nhắn. Trả về message_id nếu thành công."""
    payload: dict = {"chat_id": chat_id, "text": text}  # type: ignore[type-arg]
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result = await _api("sendMessage", **payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


async def _answer_callback(callback_query_id: str, text: str = "") -> None:
    await _api("answerCallbackQuery", callback_query_id=callback_query_id, text=text)


async def _download_photo(file_id: str) -> bytes | None:
    token = _token()
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
            )
            r.raise_for_status()
            file_path = r.json()["result"]["file_path"]
            photo_r = await client.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}"
            )
            photo_r.raise_for_status()
            return photo_r.content
    except Exception as exc:
        logger.warning("Không tải được ảnh file_id=%s: %s", file_id, exc)
        return None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _load_data(session: BotSession) -> dict:  # type: ignore[type-arg]
    if not session.session_data:
        return {}
    try:
        return json.loads(session.session_data)
    except Exception:
        return {}


def _save_data(session: BotSession, data: dict) -> None:  # type: ignore[type-arg]
    session.session_data = json.dumps(data, ensure_ascii=False)


async def _get_session(db: AsyncSession, chat_id: int) -> BotSession:
    result = await db.execute(
        select(BotSession).where(BotSession.chat_id == chat_id, BotSession.bot_type == "manager")
    )
    session = result.scalar_one_or_none()
    if not session:
        session = BotSession(chat_id=chat_id, bot_type="manager", state=ST_IDLE, is_admin=False)
        db.add(session)
        await db.flush()
    return session


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------


def _invoice_keyboard() -> dict:  # type: ignore[type-arg]
    return {
        "inline_keyboard": [
            [{"text": "✅ Gửi thông báo cho cư dân", "callback_data": CB_INVOICE_SEND}],
            [{"text": "❌ Hủy không gửi", "callback_data": CB_INVOICE_CANCEL}],
        ]
    }


def _building_keyboard(buildings: list[tuple[int, str]]) -> dict:  # type: ignore[type-arg]
    return {
        "inline_keyboard": [
            [{"text": name, "callback_data": f"{CB_BUILDING}{bid}"}]
            for bid, name in buildings
        ]
    }


def _price_keyboard(price_configs: list[tuple[int, str]]) -> dict:  # type: ignore[type-arg]
    return {
        "inline_keyboard": [
            [{"text": name, "callback_data": f"{CB_PRICE}{pid}"}]
            for pid, name in price_configs
        ]
    }


# ---------------------------------------------------------------------------
# Month parser
# ---------------------------------------------------------------------------


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


def _parse_month(text: str) -> str | None:
    """Chuyển đổi nhiều dạng nhập tháng → 'YYYY-MM'. Trả None nếu không nhận ra."""
    text = text.strip()
    # YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", text):
        return text
    # 'tháng N' hoặc 'thang N'
    m = re.search(r"th[aá]ng\s*(\d+)", text, re.IGNORECASE)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{date.today().year}-{month:02d}"
    # MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{4})$", text)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    # YYYY/MM
    m = re.match(r"^(\d{4})/(\d{1,2})$", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    # Số tháng đơn (1-12)
    m = re.match(r"^(\d{1,2})$", text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{date.today().year}-{month:02d}"
    return None


# ---------------------------------------------------------------------------
# Invoice generation
# ---------------------------------------------------------------------------


async def _build_invoices(
    db: AsyncSession,
    building_id: int,
    price_config: PriceConfig,
    invoice_month: str,
    room_ids: set[int],
) -> list[dict]:  # type: ignore[type-arg]
    """Tính và tạo hóa đơn cho các phòng đã duyệt. Trả về danh sách kết quả."""
    month_start = date.fromisoformat(f"{invoice_month}-01")
    if month_start.month == 12:
        next_month_start = date(month_start.year + 1, 1, 1)
    else:
        next_month_start = date(month_start.year, month_start.month + 1, 1)

    rooms_res = await db.execute(
        select(Room).where(
            Room.building_id == building_id,
            Room.id.in_(room_ids),
            Room.is_active == True,  # noqa: E712
        )
    )
    rooms = rooms_res.scalars().all()

    results = []
    for room in rooms:
        # Chỉ số mới nhất đã duyệt trong tháng
        cur_res = await db.execute(
            select(MeterReading)
            .where(
                MeterReading.room_id == room.id,
                MeterReading.status == "approved",
                MeterReading.reading_date >= month_start,
                MeterReading.reading_date < next_month_start,
            )
            .order_by(MeterReading.reading_date.desc(), MeterReading.id.desc())
            .limit(1)
        )
        current_reading = cur_res.scalar_one_or_none()
        if not current_reading:
            results.append(
                {
                    "room_id": room.id,
                    "room_number": room.room_number,
                    "status": "skipped",
                    "detail": "Chưa có chỉ số đã duyệt",
                }
            )
            continue

        # Chỉ số trước
        prev_res = await db.execute(
            select(MeterReading)
            .where(
                MeterReading.room_id == room.id,
                MeterReading.status == "approved",
                or_(
                    MeterReading.reading_date < current_reading.reading_date,
                    and_(
                        MeterReading.reading_date == current_reading.reading_date,
                        MeterReading.id < current_reading.id,
                    ),
                ),
            )
            .order_by(MeterReading.reading_date.desc(), MeterReading.id.desc())
            .limit(1)
        )
        prev_reading = prev_res.scalar_one_or_none()
        previous_value = prev_reading.meter_value if prev_reading else room.initial_reading
        current_value = current_reading.meter_value
        consumption = max(0, current_value - previous_value)

        # Tính tiền
        try:
            calc = calculate_invoice(
                consumption=consumption,
                pricing_type=price_config.pricing_type,
                config_json=price_config.config_json,
            )
        except Exception as exc:
            results.append(
                {
                    "room_id": room.id,
                    "room_number": room.room_number,
                    "status": "error",
                    "detail": str(exc),
                }
            )
            continue

        # Hóa đơn đã tồn tại?
        existing_res = await db.execute(
            select(Invoice).where(
                Invoice.room_id == room.id,
                Invoice.invoice_month == invoice_month,
            )
        )
        if existing_res.scalar_one_or_none():
            results.append(
                {
                    "room_id": room.id,
                    "room_number": room.room_number,
                    "resident_name": room.resident_name,
                    "telegram_id": room.telegram_id,
                    "status": "exists",
                    "consumption": consumption,
                    "total_amount": calc["total_amount"],
                    "previous_reading": previous_value,
                    "current_reading": current_value,
                }
            )
            continue

        # Tạo hóa đơn mới
        invoice = Invoice(
            room_id=room.id,
            reading_id=current_reading.id,
            invoice_month=invoice_month,
            previous_reading=previous_value,
            current_reading=current_value,
            consumption=consumption,
            price_breakdown=json.dumps(calc["price_breakdown"], ensure_ascii=False),
            electricity_amount=calc["electricity_amount"],
            additional_fees=None,
            total_amount=calc["total_amount"],
            sent_status="pending",
        )
        db.add(invoice)
        await db.flush()

        results.append(
            {
                "invoice_id": invoice.id,
                "room_id": room.id,
                "room_number": room.room_number,
                "resident_name": room.resident_name,
                "telegram_id": room.telegram_id,
                "status": "created",
                "consumption": consumption,
                "total_amount": calc["total_amount"],
                "previous_reading": previous_value,
                "current_reading": current_value,
            }
        )

    await db.commit()
    return results


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _cmd_start(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if session.is_admin:
        await _send(
            chat_id,
            "✅ Đã xác thực (Quản lý). Các lệnh:\n"
            "/duyet — Duyệt chỉ số điện mới từ KTV\n"
            "/id — Xem Chat ID của bạn\n"
            "/huy — Hủy thao tác hiện tại",
        )
    else:
        await _send(
            chat_id,
            "Bot quản lý tòa nhà.\n\n"
            "Xác thực: /admin MẬT_KHẨU",
        )


async def _cmd_id(chat_id: int, db: AsyncSession) -> None:
    """Trả về chat_id của manager để cấu hình App Settings."""
    await _send(
        chat_id,
        f"📋 Chat ID của bạn:\n{chat_id}\n\n"
        f"Sao chép số này vào App Settings → Manager Chat ID.",
    )


async def _cmd_admin(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await _send(chat_id, "Cú pháp: /admin MẬT_KHẨU")
        return
    if parts[1].strip() != settings.ADMIN_PASSWORD:
        await _send(chat_id, "❌ Mật khẩu không đúng.")
        return
    session.is_admin = True
    if session.state == ST_IDLE or not session.is_admin:
        session.state = ST_IDLE
    await db.commit()
    await _send(
        chat_id,
        "✅ Xác thực thành công!\n\n"
        "Các lệnh:\n"
        "/duyet — Duyệt chỉ số điện mới từ KTV\n"
        "/id — Xem Chat ID của bạn\n"
        "/huy — Hủy thao tác hiện tại",
    )


async def _cmd_duyet(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if not session.is_admin:
        await _send(chat_id, "Bot quản lý tòa nhà.\n\nXác thực: /admin MẬT_KHẨU")
        return

    result = await db.execute(
        select(MeterReading)
        .where(MeterReading.status == "staged")
        .order_by(MeterReading.reading_date.desc(), MeterReading.id.desc())
    )
    staged = result.scalars().all()

    if not staged:
        await _send(chat_id, "✅ Không có chỉ số nào đang chờ duyệt.")
        return

    room_ids = list({r.room_id for r in staged})
    rooms_r = await db.execute(select(Room).where(Room.id.in_(room_ids)))
    rooms = {r.id: r for r in rooms_r.scalars().all()}

    from collections import defaultdict
    by_month = defaultdict(list)
    for r in staged:
        month_key = r.reading_date.strftime("%Y-%m")
        by_month[month_key].append(r)

    data = {"duyet_readings": [r.id for r in staged], "duyet_decisions": {}}
    _save_data(session, data)
    session.state = ST_REVIEWING_STAGED
    await db.commit()

    # Tóm tắt danh sách gọn
    lines = [f"📋 {len(staged)} chỉ số chờ duyệt ({len(by_month)} tháng)\n"]
    for i, r in enumerate(staged[:20]):
        room = rooms.get(r.room_id)
        room_num = room.room_number if room else f"ID:{r.room_id}"
        by_text = f" ({r.submitted_by})" if r.submitted_by else ""
        lines.append(f"• P.{room_num}: {r.meter_value:,} kWh{by_text}")
    if len(staged) > 20:
        lines.append(f"… và {len(staged) - 20} chỉ số nữa")

    quick_keyboard = {
        "inline_keyboard": [
            [{"text": f"✅ Duyệt tất cả {len(staged)} chỉ số", "callback_data": CB_DUYET_ALL}],
            [{"text": "🔍 Duyệt từng cái", "callback_data": "d:manual"}],
            [{"text": "❌ Hủy", "callback_data": CB_INVOICE_CANCEL}],
        ]
    }
    await _send(chat_id, "\n".join(lines), quick_keyboard)


async def _cb_duyet_all(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    """Duyệt tất cả staged readings cùng lúc."""
    data = _load_data(session)
    reading_ids = data.get("duyet_readings") or []
    if not reading_ids:
        await _send(chat_id, "❌ Không có chỉ số nào.")
        return

    result = await db.execute(select(MeterReading).where(MeterReading.id.in_(reading_ids)))
    readings = result.scalars().all()
    for r in readings:
        r.status = "approved"

    decisions = {str(r.id): "approved" for r in readings}
    data["duyet_decisions"] = decisions
    _save_data(session, data)
    await db.commit()

    await _send(chat_id, f"✅ Đã duyệt tất cả {len(readings)} chỉ số.")
    await _cb_duyet_done(chat_id, session, db)


async def _cb_duyet_manual(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    """Hiển thị từng reading để duyệt thủ công."""
    data = _load_data(session)
    reading_ids = data.get("duyet_readings") or []
    result = await db.execute(select(MeterReading).where(MeterReading.id.in_(reading_ids)))
    staged = result.scalars().all()
    room_ids = list({r.room_id for r in staged})
    rooms_r = await db.execute(select(Room).where(Room.id.in_(room_ids)))
    rooms = {r.id: r for r in rooms_r.scalars().all()}

    for i, r in enumerate(staged):
        if i >= 20:
            await _send(chat_id, "⚠️ Chỉ hiển thị 20 readings đầu tiên.")
            break
        room = rooms.get(r.room_id)
        room_num = room.room_number if room else f"ID:{r.room_id}"
        submitted_by_text = f"\nNgười nộp: {r.submitted_by}" if r.submitted_by else ""
        msg = (
            f"🚪 P.{room_num} | {r.reading_date.strftime('%d/%m/%Y')}{submitted_by_text}\n"
            f"🔢 {r.meter_value:,} kWh"
        )
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Duyệt", "callback_data": f"{CB_DUYET_APPROVE}{r.id}"},
                {"text": "❌ Từ chối", "callback_data": f"{CB_DUYET_REJECT}{r.id}"},
            ]]
        }
        await _send(chat_id, msg, keyboard)

    done_keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Xong — tạo hóa đơn", "callback_data": CB_DUYET_DONE}],
            [{"text": "❌ Hủy", "callback_data": CB_INVOICE_CANCEL}],
        ]
    }
    await _send(chat_id, f"Đã duyệt xong {len(staged)} chỉ số?", done_keyboard)


async def _cb_duyet_approve(chat_id: int, cb_data: str, session: BotSession, db: AsyncSession) -> None:
    try:
        reading_id = int(cb_data[len(CB_DUYET_APPROVE):])
    except ValueError:
        return
    r = await db.execute(select(MeterReading).where(MeterReading.id == reading_id))
    reading = r.scalar_one_or_none()
    if not reading:
        await _send(chat_id, f"❌ Không tìm thấy chỉ số ID {reading_id}")
        return
    
    reading.status = "approved"
    
    data = _load_data(session)
    decisions = data.get("duyet_decisions", {})
    decisions[str(reading_id)] = "approved"
    data["duyet_decisions"] = decisions
    _save_data(session, data)
    await db.commit()

    room_r = await db.execute(select(Room).where(Room.id == reading.room_id))
    room = room_r.scalar_one_or_none()
    room_num = room.room_number if room else "?"
    await _send(chat_id, f"✅ Đã duyệt P.{room_num}: {reading.meter_value:,} kWh")


async def _cb_duyet_reject(chat_id: int, cb_data: str, session: BotSession, db: AsyncSession) -> None:
    try:
        reading_id = int(cb_data[len(CB_DUYET_REJECT):])
    except ValueError:
        return
    r = await db.execute(select(MeterReading).where(MeterReading.id == reading_id))
    reading = r.scalar_one_or_none()
    if not reading:
        return
    
    reading.status = "rejected"
    
    data = _load_data(session)
    decisions = data.get("duyet_decisions", {})
    decisions[str(reading_id)] = "rejected"
    data["duyet_decisions"] = decisions
    _save_data(session, data)
    await db.commit()

    room_r = await db.execute(select(Room).where(Room.id == reading.room_id))
    room = room_r.scalar_one_or_none()
    room_num = room.room_number if room else "?"
    await _send(chat_id, f"❌ Đã từ chối P.{room_num}: {reading.meter_value:,} kWh")


async def _cb_duyet_done(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    data = _load_data(session)
    decisions = data.get("duyet_decisions", {})
    approved_count = sum(1 for v in decisions.values() if v == "approved")
    rejected_count = sum(1 for v in decisions.values() if v == "rejected")
    
    await _send(chat_id, f"📊 Kết quả duyệt:\n✅ Duyệt: {approved_count}\n❌ Từ chối: {rejected_count}")
    
    if approved_count == 0:
        await _send(chat_id, "Không có chỉ số nào được duyệt. Hủy tạo hóa đơn.")
        session.state = ST_IDLE
        session.session_data = None
        await db.commit()
        return

    # Set month for invoices
    approved_ids = [int(k) for k, v in decisions.items() if v == "approved"]
    if approved_ids:
        r = await db.execute(select(MeterReading).where(MeterReading.id.in_(approved_ids)).limit(1))
        first = r.scalar_one_or_none()
        if first:
            data["month"] = first.reading_date.strftime("%Y-%m")
            _save_data(session, data)
            await db.commit()

    # Auto-detect tòa từ readings đã duyệt
    building_id = None
    if approved_ids:
        room_res = await db.execute(
            select(Room).where(Room.id == first.room_id).limit(1)
        )
        room = room_res.scalar_one_or_none()
        if room:
            building_id = room.building_id

    if not building_id:
        bldgs_res = await db.execute(select(Building).where(Building.is_active == True))  # noqa: E712
        buildings = bldgs_res.scalars().all()
        if not buildings:
            await _send(chat_id, "❌ Chưa có tòa nhà.")
            return
        if len(buildings) == 1:
            building_id = buildings[0].id
        else:
            session.state = ST_SELECTING_BUILDING
            kbd = _building_keyboard([(b.id, b.name) for b in buildings])
            await _send(chat_id, "🏢 Tạo hóa đơn cho tòa nhà nào?", kbd)
            await db.commit()
            return

    data["building_id"] = building_id
    _save_data(session, data)
    session.state = ST_SELECTING_PRICE
    await db.commit()
    await _ask_price_config(chat_id, session, db)


async def _cmd_huy(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = ST_IDLE
    session.session_data = None
    await db.commit()
    await _send(chat_id, "✅ Đã hủy phiên. Gõ /duyet để xem chỉ số mới.")


async def _ask_price_config(
    chat_id: int, session: BotSession, db: AsyncSession
) -> None:
    """Hỏi bảng giá hoặc auto-select nếu chỉ có một."""
    prices_res = await db.execute(
        select(PriceConfig).where(PriceConfig.is_active == True).limit(10)  # noqa: E712
    )
    price_configs = prices_res.scalars().all()

    if not price_configs:
        await _send(chat_id, "❌ Chưa có bảng giá nào. Vào web app tạo bảng giá trước.")
        await _cmd_huy(chat_id, session, db)
        return

    data = _load_data(session)
    if len(price_configs) == 1:
        data["price_config_id"] = price_configs[0].id
        _save_data(session, data)
        session.state = ST_REVIEWING_INVOICES
        await db.commit()
        await _generate_and_preview(chat_id, session, db)
    else:
        kbd = _price_keyboard([(p.id, p.config_name) for p in price_configs])
        await _send(chat_id, "💰 Dùng bảng giá nào?", kbd)


async def _cb_select_building(
    chat_id: int, cb_data: str, session: BotSession, db: AsyncSession
) -> None:
    try:
        building_id = int(cb_data[len(CB_BUILDING):])
    except ValueError:
        return
    data = _load_data(session)
    data["building_id"] = building_id
    _save_data(session, data)
    session.state = ST_SELECTING_PRICE
    await db.commit()
    await _ask_price_config(chat_id, session, db)


async def _cb_select_price(
    chat_id: int, cb_data: str, session: BotSession, db: AsyncSession
) -> None:
    try:
        price_id = int(cb_data[len(CB_PRICE):])
    except ValueError:
        return
    data = _load_data(session)
    data["price_config_id"] = price_id
    _save_data(session, data)
    session.state = ST_REVIEWING_INVOICES
    await db.commit()
    await _generate_and_preview(chat_id, session, db)


async def _generate_and_preview(
    chat_id: int, session: BotSession, db: AsyncSession
) -> None:
    """Tính hóa đơn và hiển thị preview cho chủ tòa xác nhận."""
    data = _load_data(session)
    building_id = data.get("building_id")
    price_config_id = data.get("price_config_id")
    month = data.get("month") or _current_month()
    readings: list[dict] = data.get("readings") or []

    if not building_id or not price_config_id:
        await _send(chat_id, "❌ Thiếu thông tin tòa nhà hoặc bảng giá.")
        return

    price_res = await db.execute(select(PriceConfig).where(PriceConfig.id == price_config_id))
    price_config = price_res.scalar_one_or_none()
    if not price_config:
        await _send(chat_id, "❌ Không tìm thấy bảng giá.")
        return

    await _send(chat_id, "⏳ Đang tính hóa đơn...")

    if not readings and data.get("duyet_decisions"):
        approved_reading_ids = [int(k) for k, v in data["duyet_decisions"].items() if v == "approved"]
        if approved_reading_ids:
            r = await db.execute(
                select(MeterReading.room_id)
                .where(MeterReading.id.in_(approved_reading_ids))
            )
            room_ids = {row[0] for row in r.all()}
        else:
            room_ids = set()
    else:
        room_ids = {r["room_id"] for r in readings}

    invoice_results = await _build_invoices(db, building_id, price_config, month, room_ids)

    data["invoice_results"] = invoice_results
    _save_data(session, data)
    await db.commit()

    # Hiển thị preview
    lines = [f"🧾 HÓA ĐƠN THÁNG {month}\n"]
    total_grand = 0.0
    for inv in invoice_results:
        status = inv.get("status")
        room_num = inv.get("room_number", "?")
        if status in ("created", "exists"):
            total = inv.get("total_amount", 0.0)
            consumption = inv.get("consumption", 0)
            total_grand += total
            flag = "✅" if status == "created" else "♻️"
            lines.append(f"{flag} P.{room_num}: {consumption} kWh → {total:,.0f}đ")
        elif status == "skipped":
            lines.append(f"⏭️ P.{room_num}: {inv.get('detail', 'Bỏ qua')}")
        else:
            lines.append(f"❌ P.{room_num}: Lỗi — {inv.get('detail', '')}")

    lines.append(f"\n💰 Tổng: {total_grand:,.0f}đ")
    lines.append("\nXác nhận để gửi thông báo cho cư dân.")
    await _send(chat_id, "\n".join(lines), _invoice_keyboard())


async def _cb_invoice_send(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    """Gửi thông báo hóa đơn đến cư dân qua Telegram."""
    data = _load_data(session)
    invoice_results: list[dict] = data.get("invoice_results") or []
    month = data.get("month") or _current_month()

    sent_ok = 0
    sent_fail = 0
    no_telegram = 0

    for inv in invoice_results:
        if inv.get("status") not in ("created", "exists"):
            continue

        telegram_id = inv.get("telegram_id")
        # Nếu cư dân không có Telegram ID → gửi về cho quản lý xem thay
        fallback_to_manager = not telegram_id
        target_id = telegram_id if telegram_id else settings.MANAGER_TELEGRAM_CHAT_ID
        if not target_id:
            no_telegram += 1
            continue

        # Lấy hóa đơn đầy đủ từ DB
        inv_res = await db.execute(
            select(Invoice)
            .where(Invoice.room_id == inv["room_id"], Invoice.invoice_month == month)
            .limit(1)
        )
        invoice = inv_res.scalar_one_or_none()
        room_res = await db.execute(select(Room).where(Room.id == inv["room_id"]))
        room = room_res.scalar_one_or_none()

        if not invoice or not room:
            sent_fail += 1
            continue

        msg = format_invoice_message(
            room_number=room.room_number,
            resident_name=room.resident_name,
            invoice_month=month,
            previous_reading=invoice.previous_reading,
            current_reading=invoice.current_reading,
            consumption=invoice.consumption,
            price_breakdown_str=invoice.price_breakdown,
            electricity_amount=invoice.electricity_amount,
            additional_fees_str=invoice.additional_fees,
            total_amount=invoice.total_amount,
        )

        if fallback_to_manager:
            msg = f"⚠️ Cư dân P.{room.room_number} chưa có Telegram — gửi cho quản lý xem:\n\n" + msg

        ok = await send_telegram_message(str(target_id), msg)
        if ok:
            invoice.sent_status = "sent"
            invoice.sent_at = datetime.now(UTC).replace(tzinfo=None)
            sent_ok += 1
        else:
            invoice.sent_status = "failed"
            sent_fail += 1

    await db.commit()

    # Báo cáo kết quả
    lines = [f"📨 KẾT QUẢ GỬI THÁNG {month}\n"]
    if sent_ok:
        lines.append(f"✅ Gửi thành công: {sent_ok} phòng")
    if sent_fail:
        lines.append(f"❌ Gửi thất bại: {sent_fail} phòng")
    if no_telegram:
        lines.append(
            f"⚠️ Chưa có Telegram ID: {no_telegram} phòng (vào web app cập nhật)"
        )
    lines.append("\n✅ Phiên báo điện hoàn tất!")
    await _send(chat_id, "\n".join(lines))

    # Reset session
    session.state = ST_IDLE
    session.session_data = None
    await db.commit()


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


async def _dispatch(update: dict) -> None:  # type: ignore[type-arg]
    """Xử lý một Telegram update. Chạy trong background task."""

    # Callback query (nút inline keyboard)
    callback_query = update.get("callback_query")
    if callback_query:
        await _handle_callback_query(callback_query)
        return

    message = update.get("message") or update.get("channel_post") or {}
    chat = message.get("chat", {})
    chat_id: int | None = chat.get("id")
    if not chat_id:
        return

    text: str = (message.get("text") or message.get("caption") or "").strip()
    photos = message.get("photo")

    async with async_session() as db:
        session = await _get_session(db, chat_id)

        # /huy — luôn hoạt động
        if text.lower() in ("/huy", "/cancel"):
            await _cmd_huy(chat_id, session, db)
            return

        # /start
        if text.startswith("/start"):
            await _cmd_start(chat_id, session, db)
            return

        # /admin — xác thực
        if text.startswith("/admin"):
            await _cmd_admin(chat_id, text, session, db)
            return

        # Chưa xác thực
        if not session.is_admin:
            await _send(chat_id, "Bot báo điện dành riêng cho quản lý.\n\nXác thực: /admin MẬT_KHẨU")
            return

        # /duyet
        if text.startswith("/duyet"):
            await _cmd_duyet(chat_id, session, db)
            return

        # /id
        if text.startswith("/id"):
            await _cmd_id(chat_id, db)
            return

        # Ảnh
        if photos:
            await _send(chat_id, "Bot quản lý không nhận ảnh. Vui lòng dùng ứng dụng KTV.")
            return

        # Routing text theo state
        if session.state == ST_IDLE:
            await _send(chat_id, "Gõ /duyet để xem và duyệt chỉ số.")
        else:
            await _send(chat_id, "Sử dụng nút trên màn hình hoặc /huy để hủy.")


async def _handle_callback_query(callback_query: dict) -> None:  # type: ignore[type-arg]
    cb_id: str = callback_query.get("id", "")
    cb_data: str = callback_query.get("data", "")
    chat_id: int = callback_query.get("message", {}).get("chat", {}).get("id", 0)
    if not chat_id:
        return

    await _answer_callback(cb_id)

    try:
        async with async_session() as db:
            session = await _get_session(db, chat_id)

            if cb_data == CB_DUYET_ALL:
                await _cb_duyet_all(chat_id, session, db)
            elif cb_data == "d:manual":
                await _cb_duyet_manual(chat_id, session, db)
            elif cb_data.startswith(CB_DUYET_APPROVE):
                await _cb_duyet_approve(chat_id, cb_data, session, db)
            elif cb_data.startswith(CB_DUYET_REJECT):
                await _cb_duyet_reject(chat_id, cb_data, session, db)
            elif cb_data == CB_DUYET_DONE:
                await _cb_duyet_done(chat_id, session, db)
            elif cb_data == CB_INVOICE_SEND:
                await _cb_invoice_send(chat_id, session, db)
            elif cb_data in (CB_INVOICE_CANCEL, "huy"):
                await _cmd_huy(chat_id, session, db)
            elif cb_data.startswith(CB_BUILDING):
                await _cb_select_building(chat_id, cb_data, session, db)
            elif cb_data.startswith(CB_PRICE):
                await _cb_select_price(chat_id, cb_data, session, db)
    except Exception:
        logger.exception("Callback handler error chat_id=%s data=%s", chat_id, cb_data)
        await _send(chat_id, "⚠️ Có lỗi xảy ra. Gõ /huy rồi thử lại.")


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:  # type: ignore[type-arg]
    webhook_secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if webhook_secret and x_telegram_bot_api_secret_token != webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    background_tasks.add_task(_dispatch, update)
    return {"ok": True}
