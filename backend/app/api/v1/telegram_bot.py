"""Telegram chatbot agent cho chủ tòa báo điện.

Flow:
  /admin PASSWORD  → xác thực quản lý
  /baodien         → bắt đầu phiên, chọn tháng
  [gửi ảnh]        → AI đọc chỉ số → xác nhận từng ảnh (inline keyboard)
  /xong            → xem tổng hợp → chọn tòa / bảng giá → xem hóa đơn → gửi cư dân

Thiết kế:
  - Mỗi Telegram chat được lưu trạng thái trong bảng `bot_sessions` (SQLite).
  - Admin xác thực bằng mật khẩu ADMIN_PASSWORD trong settings.
  - Bot chỉ phục vụ chủ tòa (không có flow cư dân gửi ảnh).
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
from app.services.ai_service import AIService
from app.services.billing_service import calculate_invoice
from app.services.notification_service import format_invoice_message, send_telegram_message

router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])
logger = logging.getLogger(__name__)
_ai_service = AIService()

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

ST_IDLE = "idle"
ST_AWAITING_MONTH = "awaiting_month"
ST_COLLECTING = "collecting_photos"
ST_CONFIRMING = "confirming_photo"
ST_EDITING_VALUE = "editing_value"
ST_EDITING_ROOM = "editing_room"
ST_REVIEWING = "reviewing_summary"
ST_SELECTING_BUILDING = "selecting_building"
ST_SELECTING_PRICE = "selecting_price"
ST_REVIEWING_INVOICES = "reviewing_invoices"

# Callback data tokens
CB_OK = "c:ok"
CB_EDIT_VAL = "c:ev"
CB_EDIT_ROOM = "c:er"
CB_SKIP = "c:skip"
CB_SUMMARY_OK = "s:ok"
CB_INVOICE_SEND = "i:send"
CB_INVOICE_CANCEL = "i:cancel"
CB_BUILDING = "b:"
CB_PRICE = "p:"

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
    result = await db.execute(select(BotSession).where(BotSession.chat_id == chat_id))
    session = result.scalar_one_or_none()
    if not session:
        session = BotSession(chat_id=chat_id, state=ST_IDLE, is_admin=False)
        db.add(session)
        await db.flush()
    return session


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------


def _confirm_keyboard(room_number: str | None) -> dict:  # type: ignore[type-arg]
    room_label = f"🚪 Sửa phòng: {room_number}" if room_number else "🚪 Nhập số phòng"
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Đúng rồi", "callback_data": CB_OK},
                {"text": "✏️ Sửa chỉ số", "callback_data": CB_EDIT_VAL},
            ],
            [
                {"text": room_label, "callback_data": CB_EDIT_ROOM},
                {"text": "🗑️ Bỏ qua ảnh này", "callback_data": CB_SKIP},
            ],
        ]
    }


def _summary_keyboard() -> dict:  # type: ignore[type-arg]
    return {
        "inline_keyboard": [
            [{"text": "✅ Xác nhận — tiếp tục tạo hóa đơn", "callback_data": CB_SUMMARY_OK}],
            [{"text": "❌ Hủy phiên", "callback_data": CB_INVOICE_CANCEL}],
        ]
    }


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
# Photo processor
# ---------------------------------------------------------------------------


async def _process_photo(chat_id: int, file_id: str, db: AsyncSession) -> None:
    """Tải ảnh, chạy AI, cập nhật session → trạng thái confirming_photo."""
    session = await _get_session(db, chat_id)
    if session.state not in (ST_COLLECTING,):
        await _send(chat_id, "Không trong phiên thu ảnh. Gõ /baodien để bắt đầu.")
        return

    await _send(chat_id, "⏳ Đang đọc ảnh...")
    photo_data = await _download_photo(file_id)
    if not photo_data:
        await _send(chat_id, "❌ Không tải được ảnh. Thử gửi lại.")
        return

    # Lưu ảnh vào disk
    upload_dir = settings.upload_path / "telegram"
    upload_dir.mkdir(parents=True, exist_ok=True)
    photo_path = upload_dir / f"{uuid4().hex}.jpg"
    photo_path.write_bytes(photo_data)

    # AI đọc
    ai_result = await _ai_service.extract_meter_reading(str(photo_path))
    meter_value = ai_result.get("meter_reading")
    confidence = float(ai_result.get("confidence") or 0.0)
    room_number_ai = ai_result.get("room_number")
    notes = ai_result.get("notes", "")

    # Tìm phòng từ số phòng AI đọc được
    room: Room | None = None
    if room_number_ai:
        room_num = room_number_ai.strip().split()[-1]
        r = await db.execute(
            select(Room).where(Room.room_number == room_num, Room.is_active == True).limit(1)  # noqa: E712
        )
        room = r.scalar_one_or_none()

    data = _load_data(session)
    data["pending"] = {
        "image_path": str(photo_path),
        "meter_value": meter_value,
        "room_id": room.id if room else None,
        "room_number": room.room_number if room else room_number_ai,
        "confidence": confidence,
        "notes": notes,
    }
    _save_data(session, data)
    session.state = ST_CONFIRMING
    await db.commit()

    # Xây thông báo xác nhận
    if meter_value is None:
        msg = (
            "❌ Không đọc được chỉ số.\n"
            f"🔎 AI đọc phòng: {room_number_ai or 'Không rõ'}\n"
        )
        if notes:
            msg += f"📝 Ghi chú: {notes}\n"
        msg += "\nNhấn ✏️ Sửa chỉ số để nhập tay, hoặc 🗑️ Bỏ qua."
    else:
        conf_pct = f"{confidence * 100:.0f}%"
        room_display = room.room_number if room else (room_number_ai or "Chưa rõ")
        msg = (
            f"📸 Ảnh mới\n"
            f"🔢 Chỉ số: {meter_value:,} kWh (tin cậy {conf_pct})\n"
            f"🚪 Phòng: {room_display}"
        )
        if not room:
            msg += " ⚠️ (chưa tìm thấy trong hệ thống)"
        if notes:
            msg += f"\n📝 {notes}"

    await _send(
        chat_id,
        msg,
        _confirm_keyboard(room.room_number if room else room_number_ai),
    )


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
            "✅ Đã xác thực. Các lệnh:\n"
            "/baodien — Bắt đầu phiên báo điện\n"
            "/xong — Kết thúc thu ảnh\n"
            "/huy — Hủy phiên hiện tại",
        )
    else:
        await _send(
            chat_id,
            "Bot báo điện dành riêng cho quản lý tòa nhà.\n\n"
            "Xác thực: /admin MẬT_KHẨU",
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
        "/baodien — Bắt đầu phiên báo điện\n"
        "/xong — Kết thúc thu ảnh\n"
        "/huy — Hủy phiên hiện tại",
    )


async def _cmd_baodien(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    _save_data(session, {"readings": [], "pending": None})

    # Hỏi tòa nhà trước nếu có nhiều tòa
    bldgs_res = await db.execute(
        select(Building).where(Building.is_active == True)  # noqa: E712
    )
    buildings = bldgs_res.scalars().all()

    if not buildings:
        await _send(chat_id, "❌ Chưa có tòa nhà nào. Vào web app tạo tòa trước.")
        return

    if len(buildings) == 1:
        data = _load_data(session)
        data["building_id"] = buildings[0].id
        _save_data(session, data)
        session.state = ST_AWAITING_MONTH
        await db.commit()
        current = _current_month()
        await _send(
            chat_id,
            f"🏢 Tòa: {buildings[0].name}\n\n"
            f"📅 Báo điện tháng nào?\n"
            f"Nhập: 8, tháng 8, 08/2026, hoặc OK để dùng tháng này ({current}).\n\n"
            "Gõ /huy để hủy.",
        )
    else:
        session.state = ST_SELECTING_BUILDING
        await db.commit()
        kbd = _building_keyboard([(b.id, b.name) for b in buildings])
        await _send(chat_id, "🏢 Báo điện cho tòa nhà nào?", kbd)


async def _cmd_xong(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if session.state not in (ST_COLLECTING, ST_CONFIRMING):
        await _send(chat_id, "Không trong phiên thu ảnh.")
        return

    data = _load_data(session)
    readings = data.get("readings", [])

    if not readings:
        await _send(
            chat_id,
            "Chưa có ảnh nào được xác nhận.\nGửi ảnh đồng hồ hoặc /huy để hủy.",
        )
        return

    session.state = ST_REVIEWING
    await db.commit()

    lines = [f"📊 TỔNG KẾT — Tháng {data.get('month', '?')}\n"]
    for r in readings:
        conf = f" ({r['confidence'] * 100:.0f}%)" if r.get("confidence") else ""
        lines.append(f"🚪 P.{r['room_number']}: {r['meter_value']:,} kWh{conf}")
    lines.append(f"\n✅ {len(readings)} phòng đã ghi nhận.")
    lines.append("Nhấn xác nhận để lưu chỉ số và tiếp tục tạo hóa đơn.")

    await _send(chat_id, "\n".join(lines), _summary_keyboard())


async def _cmd_huy(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = ST_IDLE
    session.session_data = None
    await db.commit()
    await _send(chat_id, "✅ Đã hủy phiên. Gõ /baodien để bắt đầu lại.")


# ---------------------------------------------------------------------------
# Text input handlers (state-driven)
# ---------------------------------------------------------------------------


async def _handle_month_input(
    chat_id: int, text: str, session: BotSession, db: AsyncSession
) -> None:
    # Enter / OK → tháng hiện tại
    month = _current_month() if text.lower() in ("", "ok", ".", "enter") else _parse_month(text)
    if not month:
        await _send(chat_id, f"❓ Không nhận ra tháng '{text}'.\nThử: 8, tháng 8, 08/2026")
        return
    data = _load_data(session)
    data["month"] = month
    _save_data(session, data)
    session.state = ST_COLLECTING
    await db.commit()
    await _send(
        chat_id,
        f"✅ Tháng {month}\n\n"
        "📷 Gửi ảnh đồng hồ điện từng phòng.\n"
        "Bot sẽ xác nhận mỗi ảnh trước khi lưu.\n\n"
        "Gõ /xong khi gửi hết.",
    )


async def _handle_edit_value_input(
    chat_id: int, text: str, session: BotSession, db: AsyncSession
) -> None:
    try:
        value = int(text.strip().replace(",", "").replace(".", ""))
        if value < 0:
            raise ValueError("âm")
    except ValueError:
        await _send(chat_id, "❌ Chỉ số phải là số nguyên dương. Nhập lại:")
        return

    data = _load_data(session)
    pending = data.get("pending") or {}
    pending["meter_value"] = value
    data["pending"] = pending
    _save_data(session, data)
    session.state = ST_CONFIRMING
    await db.commit()

    room_number = pending.get("room_number")
    await _send(
        chat_id,
        f"✏️ Chỉ số đã sửa: {value:,} kWh\n🚪 Phòng: {room_number or 'Chưa rõ'}",
        _confirm_keyboard(room_number),
    )


async def _handle_edit_room_input(
    chat_id: int, text: str, session: BotSession, db: AsyncSession
) -> None:
    # Cho phép nhập "B 101" → lấy phần cuối "101"
    room_num = text.strip().split()[-1]
    r = await db.execute(
        select(Room).where(Room.room_number == room_num, Room.is_active == True).limit(1)  # noqa: E712
    )
    room = r.scalar_one_or_none()
    if not room:
        await _send(chat_id, f"❌ Không tìm thấy phòng '{room_num}'. Nhập lại:")
        return

    data = _load_data(session)
    pending = data.get("pending") or {}
    pending["room_id"] = room.id
    pending["room_number"] = room.room_number
    data["pending"] = pending
    _save_data(session, data)
    session.state = ST_CONFIRMING
    await db.commit()

    meter_value = pending.get("meter_value") or 0
    await _send(
        chat_id,
        f"✏️ Phòng đã sửa: {room.room_number}\n🔢 Chỉ số: {meter_value:,} kWh",
        _confirm_keyboard(room.room_number),
    )


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


async def _cb_confirm_ok(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    data = _load_data(session)
    pending = data.get("pending") or {}
    if pending.get("meter_value") is None:
        await _send(chat_id, "⚠️ Chỉ số chưa có. Nhấn ✏️ Sửa chỉ số trước.")
        return
    if not pending.get("room_id"):
        await _send(chat_id, "⚠️ Phòng chưa xác định. Nhấn 🚪 Nhập số phòng trước.")
        return

    readings: list = data.get("readings") or []
    readings.append(
        {
            "room_id": pending["room_id"],
            "room_number": pending["room_number"],
            "meter_value": pending["meter_value"],
            "image_path": pending.get("image_path", ""),
            "confidence": pending.get("confidence", 0.0),
        }
    )
    data["readings"] = readings
    data["pending"] = None
    _save_data(session, data)
    session.state = ST_COLLECTING
    await db.commit()

    await _send(
        chat_id,
        f"✅ Đã lưu P.{pending['room_number']}: {pending['meter_value']:,} kWh\n"
        f"({len(readings)} phòng đã ghi nhận)\n\nGửi ảnh tiếp hoặc /xong.",
    )


async def _cb_edit_val(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = ST_EDITING_VALUE
    await db.commit()
    await _send(chat_id, "✏️ Nhập chỉ số đúng (số nguyên, ví dụ: 1234):")


async def _cb_edit_room(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = ST_EDITING_ROOM
    await db.commit()
    await _send(chat_id, "🚪 Nhập số phòng đúng (ví dụ: 101 hoặc B101):")


async def _cb_skip(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    data = _load_data(session)
    data["pending"] = None
    _save_data(session, data)
    session.state = ST_COLLECTING
    await db.commit()
    count = len(data.get("readings") or [])
    await _send(chat_id, f"🗑️ Đã bỏ qua.\n({count} phòng đã ghi nhận)\n\nGửi ảnh tiếp hoặc /xong.")


async def _cb_summary_ok(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    """Lưu chỉ số vào DB với trạng thái approved → chọn bảng giá."""
    data = _load_data(session)
    readings: list[dict] = data.get("readings") or []

    # Lưu readings vào DB với status approved
    reading_date = date.today()
    for r in readings:
        reading = MeterReading(
            room_id=r["room_id"],
            reading_date=reading_date,
            meter_value=r["meter_value"],
            image_path=r.get("image_path") or None,
            confidence_score=r.get("confidence") or None,
            status="approved",
            notes="[Bot Telegram]",
        )
        db.add(reading)

    await db.flush()
    await db.commit()

    session.state = ST_SELECTING_PRICE
    await db.commit()
    await _ask_price_config(chat_id, session, db)


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
    session.state = ST_AWAITING_MONTH
    await db.commit()
    current = _current_month()
    await _send(
        chat_id,
        f"📅 Báo điện tháng nào?\n"
        f"Nhập: 8, tháng 8, 08/2026, hoặc OK để dùng tháng này ({current}).\n\n"
        "Gõ /huy để hủy.",
    )


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
        if not telegram_id:
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

        ok = await send_telegram_message(str(telegram_id), msg)
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

        # /baodien
        if text.startswith("/baodien"):
            await _cmd_baodien(chat_id, session, db)
            return

        # /xong
        if text.startswith("/xong"):
            await _cmd_xong(chat_id, session, db)
            return

        # Ảnh
        if photos:
            if session.state != ST_COLLECTING:
                await _send(
                    chat_id,
                    "Gõ /baodien để bắt đầu phiên, rồi gửi ảnh."
                    if session.state == ST_IDLE
                    else "Vui lòng xác nhận ảnh hiện tại trước khi gửi ảnh mới.",
                )
                return
            largest = max(photos, key=lambda p: p.get("file_size", 0))
            await _process_photo(chat_id, largest["file_id"], db)
            return

        # Routing text theo state
        if session.state == ST_AWAITING_MONTH:
            await _handle_month_input(chat_id, text, session, db)
        elif session.state == ST_EDITING_VALUE:
            await _handle_edit_value_input(chat_id, text, session, db)
        elif session.state == ST_EDITING_ROOM:
            await _handle_edit_room_input(chat_id, text, session, db)
        elif session.state == ST_COLLECTING:
            await _send(chat_id, "Gửi ảnh đồng hồ hoặc /xong để kết thúc.")
        elif session.state == ST_IDLE:
            await _send(chat_id, "Gõ /baodien để bắt đầu phiên báo điện.")
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

            if cb_data == CB_OK:
                await _cb_confirm_ok(chat_id, session, db)
            elif cb_data == CB_EDIT_VAL:
                await _cb_edit_val(chat_id, session, db)
            elif cb_data == CB_EDIT_ROOM:
                await _cb_edit_room(chat_id, session, db)
            elif cb_data == CB_SKIP:
                await _cb_skip(chat_id, session, db)
            elif cb_data == CB_SUMMARY_OK:
                await _cb_summary_ok(chat_id, session, db)
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
