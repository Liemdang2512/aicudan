"""Generate invoice PDF in the Vietnamese apartment billing format."""
from __future__ import annotations

import json
from pathlib import Path

from fpdf import FPDF

FONT_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "fonts"
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

# ── Vietnamese number-to-words ─────────────────────────────────────────────────

_ONES = ["", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_TEENS = [
    "mười", "mười một", "mười hai", "mười ba", "mười bốn",
    "mười lăm", "mười sáu", "mười bảy", "mười tám", "mười chín",
]


def _hundreds(n: int) -> str:
    """Convert 0–999 to Vietnamese words."""
    if n == 0:
        return ""
    h, rem = divmod(n, 100)
    parts: list[str] = []
    if h:
        parts.append(f"{_ONES[h]} trăm")
    if rem == 0:
        pass
    elif rem < 10:
        parts.append(f"lẻ {_ONES[rem]}")
    elif rem < 20:
        parts.append(_TEENS[rem - 10])
    else:
        tens, ones = divmod(rem, 10)
        t = ["", "", "hai mươi", "ba mươi", "bốn mươi", "năm mươi",
             "sáu mươi", "bảy mươi", "tám mươi", "chín mươi"][tens]
        if ones == 0:
            parts.append(t)
        elif ones == 1:
            parts.append(f"{t} mốt")
        elif ones == 5 and tens > 1:
            parts.append(f"{t} lăm")
        else:
            parts.append(f"{t} {_ONES[ones]}")
    return " ".join(parts)


def number_to_words(amount: int) -> str:
    """Convert a non-negative integer (VND) to Vietnamese words."""
    if amount == 0:
        return "không đồng"
    parts: list[str] = []
    groups = []
    n = amount
    while n:
        groups.append(n % 1000)
        n //= 1000
    units = ["", "nghìn", "triệu", "tỷ"]
    for i, g in reversed(list(enumerate(groups))):
        if g == 0:
            continue
        w = _hundreds(g)
        if units[i]:
            w = f"{w} {units[i]}"
        parts.append(w)
    result = " ".join(parts)
    return result[0].upper() + result[1:] + " đồng"


# ── PDF generation ─────────────────────────────────────────────────────────────

class _InvoicePDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=False)
        self.add_font("DejaVu", "", str(FONT_REGULAR))
        self.add_font("DejaVu", "B", str(FONT_BOLD))


def generate_invoice_pdf(
    invoice_id: int,
    invoice_month: str,
    room_number: str,
    resident_name: str | None,
    previous_reading: int,
    current_reading: int,
    consumption: int,
    price_breakdown_json: str | None,
    electricity_amount: float,
    additional_fees_json: str | None,
    total_amount: float,
    management_unit: str,
    bank_account: str,
    bank_name: str,
    account_holder: str,
) -> bytes:
    """Return raw PDF bytes for a single room invoice."""
    pdf = _InvoicePDF()
    pdf.add_page()

    W = pdf.w - pdf.l_margin - pdf.r_margin  # usable width

    # ── Parse month display ─────────────────────────────────────────────────
    parts = invoice_month.split("-")
    month_display = f"Tháng {parts[1]}/{parts[0]}" if len(parts) == 2 else invoice_month

    # ── Title ───────────────────────────────────────────────────────────────
    pdf.set_font("DejaVu", "B", 13)
    pdf.cell(W, 8, month_display, align="C", ln=True)
    pdf.ln(2)

    # ── Recipient row ────────────────────────────────────────────────────────
    pdf.set_font("DejaVu", "", 9)
    name_str = resident_name or "—"
    left_text = f"Kính gửi Ông/Bà: {name_str} - Căn hộ số: {room_number}"
    right_text = f"MKH: INV-{invoice_id:05d}"
    pdf.cell(W * 0.7, 5, left_text, align="L")
    pdf.cell(W * 0.3, 5, right_text, align="R", ln=True)

    if management_unit:
        pdf.set_font("DejaVu", "", 8)
        pdf.cell(W * 0.7, 4, "Chi tiết phát sinh", align="L")
        pdf.cell(W * 0.3, 4, "ĐVT: ĐỒNG", align="R", ln=True)
    else:
        pdf.cell(W * 0.7, 4, "Chi tiết phát sinh", align="L")
        pdf.cell(W * 0.3, 4, "ĐVT: ĐỒNG", align="R", ln=True)

    pdf.ln(2)

    # ── Table ────────────────────────────────────────────────────────────────
    col_w = [W * 0.32, W * 0.08, W * 0.10, W * 0.10, W * 0.10, W * 0.13, W * 0.17]
    headers = ["Nội dung", "Đvt", "CSC", "CSM", "SL", "Đơn giá", "Tổng tiền"]

    def fmt(n: float | int | None) -> str:
        if n is None or n == 0:
            return ""
        return f"{int(round(n)):,}".replace(",", ".")

    def draw_row(
        cells: list[str],
        bold: bool = False,
        fill: bool = False,
        border: bool = True,
        row_h: float = 6.5,
    ) -> None:
        style = "B" if bold else ""
        pdf.set_font("DejaVu", style, 8)
        if fill:
            pdf.set_fill_color(220, 220, 220)
        aligns = ["L", "C", "R", "R", "R", "R", "R"]
        for i, (cell_text, cw, al) in enumerate(zip(cells, col_w, aligns)):
            brd = 1 if border else "LRB"
            pdf.cell(cw, row_h, cell_text, border=brd, align=al, fill=fill)
        pdf.ln()
        if fill:
            pdf.set_fill_color(255, 255, 255)

    # Header row
    draw_row(headers, bold=True, fill=True)

    # ── Parse breakdown ──────────────────────────────────────────────────────
    breakdown: dict = {}
    try:
        if price_breakdown_json:
            breakdown = json.loads(price_breakdown_json)
    except (json.JSONDecodeError, TypeError):
        pass

    tiers = breakdown.get("tiers") or []
    subtotal = breakdown.get("subtotal")
    vat_rate = breakdown.get("vat_rate", 0)
    vat_amount = breakdown.get("vat_amount")
    price_per_kwh = breakdown.get("price_per_kwh")

    # Row: Tiền điện (main row)
    draw_row([
        "1. Tiền điện",
        "kWh",
        fmt(previous_reading),
        fmt(current_reading),
        fmt(consumption),
        "",
        fmt(electricity_amount),
    ])

    if tiers:
        # Tiered pricing: show each tier as sub-row
        for tier in tiers:
            tier_name = tier.get("name", "")
            tier_kwh = tier.get("kwh", 0)
            tier_price = tier.get("price", 0)
            tier_amount = tier.get("amount", 0)
            draw_row([
                f"  {tier_name}",
                "kWh",
                "",
                "",
                fmt(tier_kwh),
                fmt(tier_price),
                fmt(tier_amount),
            ])
        if subtotal:
            draw_row(["  Cộng chưa thuế", "", "", "", "", "", fmt(subtotal)])
        if vat_amount:
            draw_row([f"  Thuế VAT ({int(vat_rate * 100)}%)", "", "", "", "", "", fmt(vat_amount)])
    elif price_per_kwh:
        # Fixed pricing: single sub-row
        draw_row([
            "  Giá cố định",
            "kWh",
            "",
            "",
            fmt(consumption),
            fmt(price_per_kwh),
            fmt(subtotal or electricity_amount),
        ])
        if vat_amount:
            draw_row([f"  Thuế VAT ({int(vat_rate * 100)}%)", "", "", "", "", "", fmt(vat_amount)])

    # ── Additional fees ──────────────────────────────────────────────────────
    additional_fees: dict = {}
    try:
        if additional_fees_json:
            additional_fees = json.loads(additional_fees_json)
    except (json.JSONDecodeError, TypeError):
        pass

    if additional_fees:
        draw_row(["2. Phí khác", "", "", "", "", "", ""])
        for fee_name, fee_amount in additional_fees.items():
            draw_row([
                f"  {fee_name}",
                "lần",
                "",
                "",
                "1",
                fmt(fee_amount),
                fmt(fee_amount),
            ])

    # ── Total row ────────────────────────────────────────────────────────────
    pdf.set_font("DejaVu", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(sum(col_w[:6]), 7, "Tổng thanh toán", border=1, align="R", fill=True)
    pdf.cell(col_w[6], 7, fmt(total_amount), border=1, align="R", fill=True)
    pdf.ln()
    pdf.set_fill_color(255, 255, 255)

    pdf.ln(3)

    # ── Amount in words ──────────────────────────────────────────────────────
    pdf.set_font("DejaVu", "", 8.5)
    words = number_to_words(int(round(total_amount)))
    pdf.multi_cell(W, 5, f"Bằng chữ: {words}.", border=0)
    pdf.ln(2)

    # ── Payment info ─────────────────────────────────────────────────────────
    if bank_account or bank_name or account_holder:
        pdf.set_font("DejaVu", "B", 8.5)
        pdf.cell(W, 5, "Phương thức thanh toán:", ln=True)
        pdf.set_font("DejaVu", "", 8.5)
        pdf.cell(W, 4.5, "- Thanh toán tiền mặt tại văn phòng Ban quản lý", ln=True)
        pdf.cell(W, 4.5, "- Hoặc chuyển khoản vào:", ln=True)

        if bank_account:
            pdf.cell(5, 4.5, "")
            pdf.cell(W - 5, 4.5, f"Tài khoản số: {bank_account}", ln=True)
        if bank_name:
            pdf.cell(5, 4.5, "")
            pdf.cell(W - 5, 4.5, f"Ngân hàng: {bank_name}", ln=True)
        if account_holder:
            pdf.cell(5, 4.5, "")
            pdf.cell(W - 5, 4.5, f"Chủ tài khoản: {account_holder}", ln=True)

        noi_dung = f"{room_number} + Thanh toán tiền điện {month_display}"
        pdf.cell(5, 4.5, "")
        pdf.cell(W - 5, 4.5, f"Nội dung chuyển khoản: {noi_dung}", ln=True)

    return bytes(pdf.output())
