"""Telegram chatbot agent cho Kỹ Thuật Viên ngoài hiện trường.

Flow:
  /ktv PASSWORD    → xác thực KTV (lần đầu hỏi tên, SĐT)
  /baodien         → bắt đầu phiên, chọn tháng
  [gửi ảnh]        → AI đọc chỉ số → xác nhận từng ảnh (inline keyboard)
  /xong            → xem tổng hợp → lưu với status 'staged' và push thông báo cho manager
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session
from app.models.bot_session import BotSession
from app.models.room import Room
from app.models.reading import MeterReading
from app.models.technician_profile import TechnicianProfile
from app.services.ai_service import AIService

router = APIRouter(prefix="/telegram", tags=["Telegram KTV Bot"])
logger = logging.getLogger(__name__)
_ai_service = AIService()

# ---------------------------------------------------------------------------
# State constants (prefix KTV_)
# ---------------------------------------------------------------------------

KTV_IDLE = "ktv_idle"
KTV_AWAITING_NAME = "ktv_awaiting_name"
KTV_AWAITING_PHONE = "ktv_awaiting_phone"
KTV_AWAITING_UPDATE_NAME = "ktv_awaiting_update_name"
KTV_AWAITING_UPDATE_PHONE = "ktv_awaiting_update_phone"
KTV_AWAITING_MONTH = "ktv_awaiting_month"
KTV_COLLECTING = "ktv_collecting"
KTV_CONFIRMING = "ktv_confirming"
KTV_EDITING_VALUE = "ktv_editing_value"
KTV_EDITING_ROOM = "ktv_editing_room"
KTV_REVIEWING = "ktv_reviewing"

# Callback data tokens
CB_KTV_OK = "k:ok"
CB_KTV_EDIT_VAL = "k:ev"
CB_KTV_EDIT_ROOM = "k:er"
CB_KTV_SKIP = "k:skip"
CB_KTV_SUMMARY_OK = "k:sok"
CB_KTV_CANCEL = "k:cancel"

# ---------------------------------------------------------------------------
# Low-level Telegram API helpers
# ---------------------------------------------------------------------------

def _ktv_token() -> str:
    return settings.TELEGRAM_KTV_BOT_TOKEN


async def _ktv_api(method: str, **kwargs) -> dict | None:
    token = _ktv_token()
    if not token:
        logger.warning("TELEGRAM_KTV_BOT_TOKEN chưa được cấu hình")
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=kwargs)
            return r.json()
    except Exception as exc:
        logger.warning("KTV Telegram API %s thất bại: %s", method, exc)
        return None


async def _ktv_send(chat_id: int, text: str, reply_markup: dict | None = None) -> int | None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result = await _ktv_api("sendMessage", **payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


async def _ktv_answer_callback(callback_query_id: str, text: str = "") -> None:
    await _ktv_api("answerCallbackQuery", callback_query_id=callback_query_id, text=text)


async def _ktv_download_photo(file_id: str) -> bytes | None:
    token = _ktv_token()
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
        logger.warning("Không tải được ảnh KTV file_id=%s: %s", file_id, exc)
        return None


async def _manager_api(method: str, **kwargs) -> dict | None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN chưa được cấu hình")
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=kwargs)
            return r.json()
    except Exception as exc:
        logger.warning("Manager Telegram API %s thất bại: %s", method, exc)
        return None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _load_data(session: BotSession) -> dict:
    if not session.session_data:
        return {}
    try:
        return json.loads(session.session_data)
    except Exception:
        return {}


def _save_data(session: BotSession, data: dict) -> None:
    session.session_data = json.dumps(data, ensure_ascii=False)


async def _get_ktv_session(db: AsyncSession, chat_id: int) -> BotSession:
    result = await db.execute(select(BotSession).where(BotSession.chat_id == chat_id))
    session = result.scalar_one_or_none()
    if not session:
        session = BotSession(chat_id=chat_id, state=KTV_IDLE, is_admin=False)
        db.add(session)
        await db.flush()
    return session


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

async def _get_profile(db: AsyncSession, chat_id: int) -> TechnicianProfile | None:
    r = await db.execute(select(TechnicianProfile).where(TechnicianProfile.chat_id == chat_id))
    return r.scalar_one_or_none()


async def _save_profile(db: AsyncSession, chat_id: int, ktv_name: str, ktv_phone: str) -> TechnicianProfile:
    r = await db.execute(select(TechnicianProfile).where(TechnicianProfile.chat_id == chat_id))
    profile = r.scalar_one_or_none()
    if profile:
        profile.ktv_name = ktv_name
        profile.ktv_phone = ktv_phone
    else:
        profile = TechnicianProfile(chat_id=chat_id, ktv_name=ktv_name, ktv_phone=ktv_phone)
        db.add(profile)
    await db.flush()
    return profile


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

def _ktv_confirm_keyboard(room_number: str | None) -> dict:
    room_label = f"🚪 Sửa phòng: {room_number}" if room_number else "🚪 Nhập số phòng"
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Đúng rồi", "callback_data": CB_KTV_OK},
                {"text": "✏️ Sửa chỉ số", "callback_data": CB_KTV_EDIT_VAL},
            ],
            [
                {"text": room_label, "callback_data": CB_KTV_EDIT_ROOM},
                {"text": "🗑️ Bỏ qua ảnh này", "callback_data": CB_KTV_SKIP},
            ],
        ]
    }


def _ktv_summary_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "✅ Xác nhận — gửi cho quản lý duyệt", "callback_data": CB_KTV_SUMMARY_OK}],
            [{"text": "❌ Hủy phiên", "callback_data": CB_KTV_CANCEL}],
        ]
    }


# ---------------------------------------------------------------------------
# Month parser
# ---------------------------------------------------------------------------

def _current_month() -> str:
    return date.today().strftime("%Y-%m")


def _parse_month(text: str) -> str | None:
    text = text.strip()
    if re.match(r"^\d{4}-\d{2}$", text):
        return text
    m = re.search(r"th[aá]ng\s*(\d+)", text, re.IGNORECASE)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{date.today().year}-{month:02d}"
    m = re.match(r"^(\d{1,2})/(\d{4})$", text)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{4})/(\d{1,2})$", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{1,2})$", text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{date.today().year}-{month:02d}"
    return None


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _cmd_ktv_start(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if session.is_admin:
        await _ktv_send(
            chat_id,
            "✅ Đã xác thực. Lệnh:\n"
            "/baodien — Bắt đầu phiên\n"
            "/capnhat — Cập nhật thông tin\n"
            "/xong — Kết thúc thu ảnh\n"
            "/huy — Hủy"
        )
    else:
        await _ktv_send(
            chat_id,
            "Bot báo điện dành cho Kỹ Thuật Viên.\n\n"
            "Xác thực: /ktv MẬT_KHẨU"
        )


async def _cmd_ktv_auth(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await _ktv_send(chat_id, "Cú pháp: /ktv MẬT_KHẨU")
        return
    if parts[1].strip() != settings.TELEGRAM_KTV_PASSWORD:
        await _ktv_send(chat_id, "❌ Mật khẩu không đúng.")
        return

    session.is_admin = True
    profile = await _get_profile(db, chat_id)
    if not profile:
        session.state = KTV_AWAITING_NAME
        await db.commit()
        await _ktv_send(chat_id, "✅ Xác thực thành công!\n\nĐây là lần đầu bạn dùng bot. Vui lòng nhập tên đầy đủ của bạn:")
    else:
        session.state = KTV_IDLE
        await db.commit()
        await _ktv_send(chat_id, f"✅ Xác thực thành công! Chào {profile.ktv_name}!\n\nGõ /baodien để bắt đầu.")


async def _cmd_ktv_capnhat(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if not session.is_admin:
        await _ktv_send(chat_id, "Chưa xác thực. Dùng /ktv MẬT_KHẨU")
        return
    session.state = KTV_AWAITING_UPDATE_NAME
    await db.commit()
    await _ktv_send(chat_id, "Nhập tên mới của bạn:")


async def _cmd_ktv_baodien(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if not session.is_admin:
        await _ktv_send(chat_id, "Chưa xác thực. Dùng /ktv MẬT_KHẨU")
        return
    profile = await _get_profile(db, chat_id)
    if not profile:
        session.state = KTV_AWAITING_NAME
        await db.commit()
        await _ktv_send(chat_id, "Vui lòng nhập tên đầy đủ của bạn:")
        return

    _save_data(session, {"readings": [], "pending": None})
    session.state = KTV_AWAITING_MONTH
    await db.commit()
    current = _current_month()
    await _ktv_send(
        chat_id,
        f"📅 Báo điện tháng nào? Nhập: 8, tháng 8, 08/2026, hoặc OK cho tháng này ({current}).\n\n"
        "Gõ /huy để hủy."
    )


async def _cmd_ktv_xong(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    if session.state not in (KTV_COLLECTING, KTV_CONFIRMING):
        await _ktv_send(chat_id, "Không trong phiên thu ảnh.")
        return

    data = _load_data(session)
    readings = data.get("readings", [])
    if not readings:
        await _ktv_send(chat_id, "Chưa có ảnh nào được xác nhận. Gửi ảnh hoặc /huy.")
        return

    session.state = KTV_REVIEWING
    await db.commit()

    month = data.get("month", "?")
    lines = [f"📊 TỔNG KẾT — Tháng {month}\n"]
    for r in readings:
        lines.append(f"🚪 P.{r['room_number']}: {r['meter_value']:,} kWh")
    lines.append(f"\n✅ {len(readings)} phòng đã ghi nhận.")
    lines.append("Xác nhận để gửi cho quản lý duyệt.")

    await _ktv_send(chat_id, "\n".join(lines), _ktv_summary_keyboard())


async def _cmd_ktv_huy(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = KTV_IDLE
    session.session_data = None
    await db.commit()
    await _ktv_send(chat_id, "✅ Đã hủy phiên. Gõ /baodien để bắt đầu lại.")


# ---------------------------------------------------------------------------
# Text input handlers (state-driven)
# ---------------------------------------------------------------------------

async def _handle_ktv_name_input(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    text = text.strip()
    if not text or len(text) > 200:
        await _ktv_send(chat_id, "Tên không hợp lệ. Vui lòng nhập lại:")
        return

    data = _load_data(session)
    if session.state == KTV_AWAITING_NAME:
        data["pending_name"] = text
        _save_data(session, data)
        session.state = KTV_AWAITING_PHONE
        await db.commit()
        await _ktv_send(chat_id, "Số điện thoại của bạn?")
    elif session.state == KTV_AWAITING_UPDATE_NAME:
        data["pending_name"] = text
        _save_data(session, data)
        session.state = KTV_AWAITING_UPDATE_PHONE
        await db.commit()
        await _ktv_send(chat_id, "Số điện thoại mới của bạn? (Enter để giữ nguyên SĐT cũ)")


async def _handle_ktv_phone_input(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    text = text.strip()
    data = _load_data(session)
    pending_name = data.get("pending_name", "")

    if session.state == KTV_AWAITING_PHONE:
        if not text:
            await _ktv_send(chat_id, "Số điện thoại không được để trống:")
            return
        await _save_profile(db, chat_id, pending_name, text)
        data.pop("pending_name", None)
        _save_data(session, data)
        session.state = KTV_IDLE
        await db.commit()
        await _ktv_send(
            chat_id,
            f"✅ Đã lưu thông tin:\nTên: {pending_name}\nSĐT: {text}\n\nGõ /baodien để bắt đầu phiên."
        )
    elif session.state == KTV_AWAITING_UPDATE_PHONE:
        profile = await _get_profile(db, chat_id)
        ktv_phone = text or (profile.ktv_phone if profile else "")
        await _save_profile(db, chat_id, pending_name, ktv_phone)
        data.pop("pending_name", None)
        _save_data(session, data)
        session.state = KTV_IDLE
        await db.commit()
        await _ktv_send(chat_id, f"✅ Đã cập nhật:\nTên: {pending_name}\nSĐT: {ktv_phone}")


async def _handle_ktv_month_input(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    month = _current_month() if text.lower() in ("", "ok", ".", "enter") else _parse_month(text)
    if not month:
        await _ktv_send(chat_id, f"❓ Không nhận ra tháng '{text}'. Thử: 8, tháng 8, 08/2026")
        return
    data = _load_data(session)
    data["month"] = month
    _save_data(session, data)
    session.state = KTV_COLLECTING
    await db.commit()
    await _ktv_send(
        chat_id,
        f"✅ Tháng {month}\n\n"
        "📷 Gửi ảnh đồng hồ điện từng phòng.\n"
        "Gõ /xong khi gửi hết."
    )


async def _handle_ktv_edit_value_input(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    try:
        value = int(text.strip().replace(",", "").replace(".", ""))
        if value < 0:
            raise ValueError("âm")
    except ValueError:
        await _ktv_send(chat_id, "❌ Chỉ số phải là số nguyên dương. Nhập lại:")
        return

    data = _load_data(session)
    pending = data.get("pending") or {}
    pending["meter_value"] = value
    data["pending"] = pending
    _save_data(session, data)
    session.state = KTV_CONFIRMING
    await db.commit()

    room_number = pending.get("room_number")
    await _ktv_send(
        chat_id,
        f"✏️ Chỉ số: {value:,} kWh\n🚪 Phòng: {room_number or 'Chưa rõ'}",
        _ktv_confirm_keyboard(room_number),
    )


async def _handle_ktv_edit_room_input(chat_id: int, text: str, session: BotSession, db: AsyncSession) -> None:
    room_num = text.strip().split()[-1]
    r = await db.execute(
        select(Room).where(Room.room_number == room_num, Room.is_active == True).limit(1)  # noqa: E712
    )
    room = r.scalar_one_or_none()
    if not room:
        await _ktv_send(chat_id, f"❌ Không tìm thấy phòng '{room_num}'. Nhập lại:")
        return

    data = _load_data(session)
    pending = data.get("pending") or {}
    pending["room_id"] = room.id
    pending["room_number"] = room.room_number
    data["pending"] = pending
    _save_data(session, data)
    session.state = KTV_CONFIRMING
    await db.commit()

    meter_value = pending.get("meter_value") or 0
    await _ktv_send(
        chat_id,
        f"✏️ Phòng đã sửa: {room.room_number}\n🔢 Chỉ số: {meter_value:,} kWh",
        _ktv_confirm_keyboard(room.room_number),
    )


# ---------------------------------------------------------------------------
# Photo processor
# ---------------------------------------------------------------------------

async def _ktv_process_photo(chat_id: int, file_id: str, db: AsyncSession) -> None:
    session = await _get_ktv_session(db, chat_id)
    if session.state != KTV_COLLECTING:
        await _ktv_send(chat_id, "Không trong phiên thu ảnh. Gõ /baodien.")
        return

    await _ktv_send(chat_id, "⏳ Đang đọc ảnh...")
    photo_data = await _ktv_download_photo(file_id)
    if not photo_data:
        await _ktv_send(chat_id, "❌ Không tải được ảnh. Thử gửi lại.")
        return

    upload_dir = settings.upload_path / "telegram_ktv"
    upload_dir.mkdir(parents=True, exist_ok=True)
    photo_path = upload_dir / f"{uuid4().hex}.jpg"
    photo_path.write_bytes(photo_data)

    ai_result = await _ai_service.extract_meter_reading(str(photo_path))
    meter_value = ai_result.get("meter_reading")
    confidence = float(ai_result.get("confidence") or 0.0)
    room_number_ai = ai_result.get("room_number")
    notes = ai_result.get("notes", "")

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
    session.state = KTV_CONFIRMING
    await db.commit()

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

    await _ktv_send(chat_id, msg, _ktv_confirm_keyboard(room.room_number if room else room_number_ai))


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

async def _cb_ktv_confirm_ok(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    data = _load_data(session)
    pending = data.get("pending") or {}
    if pending.get("meter_value") is None:
        await _ktv_send(chat_id, "⚠️ Chỉ số chưa có. Nhấn ✏️ Sửa chỉ số trước.")
        return
    if not pending.get("room_id"):
        await _ktv_send(chat_id, "⚠️ Phòng chưa xác định. Nhấn 🚪 Nhập số phòng trước.")
        return

    readings = data.get("readings") or []
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
    session.state = KTV_COLLECTING
    await db.commit()

    await _ktv_send(
        chat_id,
        f"✅ Đã lưu P.{pending['room_number']}: {pending['meter_value']:,} kWh\n"
        f"({len(readings)} phòng)\n\nGửi ảnh tiếp hoặc /xong.",
    )


async def _cb_ktv_edit_val(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = KTV_EDITING_VALUE
    await db.commit()
    await _ktv_send(chat_id, "✏️ Nhập chỉ số đúng:")


async def _cb_ktv_edit_room(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    session.state = KTV_EDITING_ROOM
    await db.commit()
    await _ktv_send(chat_id, "🚪 Nhập số phòng đúng:")


async def _cb_ktv_skip(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    data = _load_data(session)
    data["pending"] = None
    _save_data(session, data)
    session.state = KTV_COLLECTING
    await db.commit()
    count = len(data.get("readings") or [])
    await _ktv_send(chat_id, f"🗑️ Đã bỏ qua. ({count} phòng)\n\nGửi ảnh tiếp hoặc /xong.")


async def _notify_manager(count: int, ktv_name: str, month: str) -> None:
    manager_chat_id = settings.MANAGER_TELEGRAM_CHAT_ID
    if not manager_chat_id:
        logger.warning("MANAGER_TELEGRAM_CHAT_ID chưa được cấu hình, không thể gửi thông báo cho quản lý.")
        return
    parts = month.split("-")
    month_display = f"{int(parts[1])}/{parts[0]}" if len(parts) == 2 else month
    msg = f"📥 Có {count} chỉ số mới từ {ktv_name}, tháng {month_display}. Dùng /duyet để xem."
    await _manager_api("sendMessage", chat_id=int(manager_chat_id), text=msg)


async def _cb_ktv_summary_ok(chat_id: int, session: BotSession, db: AsyncSession) -> None:
    data = _load_data(session)
    readings = data.get("readings") or []
    
    profile = await _get_profile(db, chat_id)
    ktv_name = profile.ktv_name if profile else "Unknown KTV"
    reading_date = date.today()

    for r in readings:
        reading = MeterReading(
            room_id=r["room_id"],
            reading_date=reading_date,
            meter_value=r["meter_value"],
            image_path=r.get("image_path") or None,
            confidence_score=r.get("confidence") or None,
            status="staged",
            notes="[Bot KTV Telegram]",
            submitted_by=ktv_name,
        )
        db.add(reading)

    await db.flush()
    await db.commit()

    month = data.get("month", "")
    count = len(readings)

    session.state = KTV_IDLE
    session.session_data = None
    await db.commit()

    await _ktv_send(chat_id, f"✅ Đã ghi nhận {count} chỉ số tháng {month}.\n\nQuản lý sẽ nhận thông báo để duyệt.")
    await _notify_manager(count, ktv_name, month)


async def _handle_ktv_callback(callback_query: dict, db: AsyncSession) -> None:
    cb_id = callback_query.get("id", "")
    cb_data = callback_query.get("data", "")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id", 0)

    await _ktv_answer_callback(cb_id)
    session = await _get_ktv_session(db, chat_id)

    try:
        if cb_data == CB_KTV_OK:
            await _cb_ktv_confirm_ok(chat_id, session, db)
        elif cb_data == CB_KTV_EDIT_VAL:
            await _cb_ktv_edit_val(chat_id, session, db)
        elif cb_data == CB_KTV_EDIT_ROOM:
            await _cb_ktv_edit_room(chat_id, session, db)
        elif cb_data == CB_KTV_SKIP:
            await _cb_ktv_skip(chat_id, session, db)
        elif cb_data == CB_KTV_SUMMARY_OK:
            await _cb_ktv_summary_ok(chat_id, session, db)
        elif cb_data == CB_KTV_CANCEL or cb_data == "huy":
            await _cmd_ktv_huy(chat_id, session, db)
    except Exception:
        logger.exception("KTV callback handler error")
        await _ktv_send(chat_id, "⚠️ Có lỗi xảy ra.")


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

async def _ktv_dispatch(update: dict) -> None:
    async for db in async_session():
        try:
            callback_query = update.get("callback_query")
            if callback_query:
                await _handle_ktv_callback(callback_query, db)
                return

            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            if not chat_id:
                return

            text = (message.get("text") or message.get("caption") or "").strip()
            photos = message.get("photo")
            session = await _get_ktv_session(db, chat_id)

            if text.startswith("/huy") or text.startswith("/cancel"):
                await _cmd_ktv_huy(chat_id, session, db)
                return
            elif text.startswith("/start"):
                await _cmd_ktv_start(chat_id, session, db)
                return
            elif text.startswith("/ktv"):
                await _cmd_ktv_auth(chat_id, text, session, db)
                return

            if not session.is_admin:
                await _ktv_send(chat_id, "Bot báo điện dành cho Kỹ Thuật Viên.\n\nXác thực: /ktv MẬT_KHẨU")
                return

            if text.startswith("/capnhat"):
                await _cmd_ktv_capnhat(chat_id, session, db)
                return
            elif text.startswith("/baodien"):
                await _cmd_ktv_baodien(chat_id, session, db)
                return
            elif text.startswith("/xong"):
                await _cmd_ktv_xong(chat_id, session, db)
                return

            if photos:
                if session.state != KTV_COLLECTING:
                    if session.state == KTV_CONFIRMING:
                        await _ktv_send(chat_id, "Xác nhận ảnh hiện tại trước khi gửi ảnh mới.")
                    else:
                        await _ktv_send(chat_id, "Gõ /baodien để bắt đầu thu ảnh.")
                    return
                largest_photo = max(photos, key=lambda p: p.get("file_size", 0))
                await _ktv_process_photo(chat_id, largest_photo["file_id"], db)
                return

            if session.state in (KTV_AWAITING_NAME, KTV_AWAITING_UPDATE_NAME):
                await _handle_ktv_name_input(chat_id, text, session, db)
            elif session.state in (KTV_AWAITING_PHONE, KTV_AWAITING_UPDATE_PHONE):
                await _handle_ktv_phone_input(chat_id, text, session, db)
            elif session.state == KTV_AWAITING_MONTH:
                await _handle_ktv_month_input(chat_id, text, session, db)
            elif session.state == KTV_EDITING_VALUE:
                await _handle_ktv_edit_value_input(chat_id, text, session, db)
            elif session.state == KTV_EDITING_ROOM:
                await _handle_ktv_edit_room_input(chat_id, text, session, db)
            elif session.state == KTV_COLLECTING:
                await _ktv_send(chat_id, "Gửi ảnh hoặc /xong.")
            elif session.state == KTV_IDLE:
                await _ktv_send(chat_id, "Gõ /baodien để bắt đầu.")
            else:
                await _ktv_send(chat_id, "Sử dụng nút trên màn hình hoặc gõ /huy.")

        except Exception:
            logger.exception("Lỗi trong KTV dispatch")
        finally:
            break


# ---------------------------------------------------------------------------
# Webhook Endpoint
# ---------------------------------------------------------------------------

@router.post("/ktv/webhook")
async def telegram_ktv_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}
    background_tasks.add_task(_ktv_dispatch, update)
    return {"ok": True}
