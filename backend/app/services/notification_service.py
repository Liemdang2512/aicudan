import asyncio
import json
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

NOTIFICATION_SEND_DELAY_SECONDS = 2.0


async def wait_for_notification_rate_limit() -> None:
    """Pause between provider calls; tests monkeypatch this boundary."""
    await asyncio.sleep(NOTIFICATION_SEND_DELAY_SECONDS)


def format_invoice_message(
    room_number: str,
    resident_name: str | None,
    invoice_month: str,
    previous_reading: int,
    current_reading: int,
    consumption: int,
    price_breakdown_str: str | None,
    electricity_amount: float,
    additional_fees_str: str | None,
    total_amount: float,
) -> str:
    # Parse price breakdown
    tier_lines = ""
    if price_breakdown_str:
        breakdown = json.loads(price_breakdown_str) if isinstance(price_breakdown_str, str) else price_breakdown_str
        tiers = breakdown.get("tiers", [])
        for t in tiers:
            tier_lines += f"  {t['name']}: {t['kwh']} kWh x {t['price']:,.0f}đ = {t['amount']:,.0f}đ\n"

        if "vat_amount" in breakdown and breakdown["vat_amount"] > 0:
            tier_lines += f"  VAT ({breakdown.get('vat_rate', 0) * 100:.0f}%): {breakdown['vat_amount']:,.0f}đ\n"

    # Parse additional fees
    fees_lines = ""
    if additional_fees_str:
        fees = json.loads(additional_fees_str) if isinstance(additional_fees_str, str) else additional_fees_str
        for name, amount in fees.items():
            fees_lines += f"  {name.capitalize()}: {amount:,.0f}đ\n"

    name_display = resident_name or "Cư dân"

    msg = f"""📊 THÔNG BÁO TIỀN ĐIỆN THÁNG {invoice_month}
━━━━━━━━━━━━━━━━━━━━━

🏠 Phòng: {room_number}
👤 {name_display}

⚡ CHỈ SỐ ĐIỆN
  Chỉ số cũ: {previous_reading:,} kWh
  Chỉ số mới: {current_reading:,} kWh
  Tiêu thụ: {consumption:,} kWh

💰 CHI TIẾT TÍNH TIỀN
{tier_lines}  Tiền điện: {electricity_amount:,.0f}đ
"""

    if fees_lines:
        msg += f"\n📋 PHỤ PHÍ\n{fees_lines}"

    msg += f"""
━━━━━━━━━━━━━━━━━━━━━
💵 TỔNG CỘNG: {total_amount:,.0f}đ
━━━━━━━━━━━━━━━━━━━━━"""

    return msg



async def send_telegram_message(chat_id: str, text: str, photo_path: str | None = None, token: str | None = None) -> bool:
    effective_token = settings.TELEGRAM_BOT_TOKEN if token is None else token
    if not effective_token:
        logger.warning("Telegram bot token not configured")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if photo_path:
                with open(photo_path, "rb") as f:
                    r = await client.post(
                        f"https://api.telegram.org/bot{effective_token}/sendPhoto",
                        data={"chat_id": chat_id, "caption": text[:1024]},
                        files={"photo": f},
                    )
            else:
                r = await client.post(
                        f"https://api.telegram.org/bot{effective_token}/sendMessage",
                        json={"chat_id": chat_id, "text": text},
                )
            data = r.json()
            if data.get("ok"):
                return True
            logger.warning(
                "Telegram API returned not-ok for chat_id=%s: error_code=%s description=%s",
                chat_id,
                data.get("error_code"),
                data.get("description"),
            )
            return False
    except Exception:
        logger.error("Telegram message delivery failed for chat_id=%s", chat_id, exc_info=True)
        return False
