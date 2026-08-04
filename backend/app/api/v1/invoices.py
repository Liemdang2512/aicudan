import io
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.building import Building
from app.models.invoice import Invoice
from app.models.price_config import PriceConfig
from app.models.reading import MeterReading
from app.models.room import Room
from app.models.user import User
from app.schemas.invoice import (
    InvoiceGenerateRequest,
    InvoiceGenerateResponse,
    InvoiceGenerateRoomResult,
    InvoiceResponse,
)
from app.services.billing_service import calculate_invoice
from app.services.pdf_service import generate_invoice_pdf

router = APIRouter(prefix="/invoices", tags=["Invoices"])


def _month_bounds(invoice_month: str) -> tuple[date, date]:
    try:
        month_start = date.fromisoformat(f"{invoice_month}-01")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Kỳ hóa đơn phải theo định dạng YYYY-MM",
        ) from exc

    if len(invoice_month) != 7 or month_start.strftime("%Y-%m") != invoice_month:
        raise HTTPException(
            status_code=422,
            detail="Kỳ hóa đơn phải theo định dạng YYYY-MM",
        )

    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return month_start, next_month


async def _get_owned_building(
    db: AsyncSession, building_id: int, owner_id: int
) -> Building:
    result = await db.execute(
        select(Building).where(
            Building.id == building_id,
            Building.owner_id == owner_id,
        )
    )
    building = result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Tòa nhà không tồn tại")
    return building


def _invoice_response(invoice: Invoice, room: Room) -> InvoiceResponse:
    response = InvoiceResponse.model_validate(invoice)
    response.room_number = room.room_number
    response.resident_name = room.resident_name
    return response


def _excel_safe(value: str) -> str:
    """Force user-controlled strings to remain text when opened in a spreadsheet."""
    if value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


@router.post("/generate", response_model=InvoiceGenerateResponse)
async def generate_invoices(
    body: InvoiceGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    month_start, next_month = _month_bounds(body.invoice_month)
    await _get_owned_building(db, body.building_id, current_user.id)

    # Get price config
    config_result = await db.execute(
        select(PriceConfig).where(
            PriceConfig.id == body.price_config_id,
            PriceConfig.is_active == True,
        )
    )
    price_config = config_result.scalar_one_or_none()
    if not price_config:
        raise HTTPException(status_code=404, detail="Bảng giá không tồn tại")

    # Get all active rooms in building
    rooms_result = await db.execute(
        select(Room).where(Room.building_id == body.building_id, Room.is_active == True)
    )
    rooms = rooms_result.scalars().all()

    if not rooms:
        raise HTTPException(status_code=400, detail="Không có phòng nào trong tòa nhà")

    invoices_created = []
    room_results: list[InvoiceGenerateRoomResult] = []
    total_amount = 0.0

    for room in rooms:
        # Check if invoice already exists
        existing = await db.execute(
            select(Invoice).where(
                Invoice.room_id == room.id,
                Invoice.invoice_month == body.invoice_month,
            )
        )
        existing_invoice = existing.scalar_one_or_none()
        if existing_invoice:
            room_results.append(
                InvoiceGenerateRoomResult(
                    room_id=room.id,
                    room_number=room.room_number,
                    status="skipped",
                    invoice_id=existing_invoice.id,
                    detail="Hóa đơn tháng này đã tồn tại",
                )
            )
            continue

        # Get latest approved reading for this month
        current_result = await db.execute(
            select(MeterReading)
            .where(
                MeterReading.room_id == room.id,
                MeterReading.status == "approved",
                MeterReading.reading_date >= month_start,
                MeterReading.reading_date < next_month,
            )
            .order_by(MeterReading.reading_date.desc(), MeterReading.id.desc())
            .limit(1)
        )
        current_reading_obj = current_result.scalar_one_or_none()
        if not current_reading_obj:
            room_results.append(
                InvoiceGenerateRoomResult(
                    room_id=room.id,
                    room_number=room.room_number,
                    status="skipped",
                    detail="Chưa có chỉ số đã duyệt trong tháng",
                )
            )
            continue

        # Get previous reading
        prev_result = await db.execute(
            select(MeterReading)
            .where(
                MeterReading.room_id == room.id,
                MeterReading.status == "approved",
                or_(
                    MeterReading.reading_date < current_reading_obj.reading_date,
                    and_(
                        MeterReading.reading_date == current_reading_obj.reading_date,
                        MeterReading.id < current_reading_obj.id,
                    ),
                ),
            )
            .order_by(MeterReading.reading_date.desc(), MeterReading.id.desc())
            .limit(1)
        )
        prev_reading_obj = prev_result.scalar_one_or_none()
        previous_value = prev_reading_obj.meter_value if prev_reading_obj else room.initial_reading

        current_value = current_reading_obj.meter_value
        consumption = current_value - previous_value

        if consumption < 0:
            room_results.append(
                InvoiceGenerateRoomResult(
                    room_id=room.id,
                    room_number=room.room_number,
                    status="error",
                    detail="Chỉ số mới nhỏ hơn chỉ số cũ",
                )
            )
            continue

        # Calculate
        try:
            calc_result = calculate_invoice(
                consumption=consumption,
                pricing_type=price_config.pricing_type,
                config_json=price_config.config_json,
                additional_fees=body.additional_fees or None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            room_results.append(
                InvoiceGenerateRoomResult(
                    room_id=room.id,
                    room_number=room.room_number,
                    status="error",
                    detail=f"Không tính được tiền điện: {exc}",
                )
            )
            continue

        invoice = Invoice(
            room_id=room.id,
            reading_id=current_reading_obj.id,
            invoice_month=body.invoice_month,
            previous_reading=previous_value,
            current_reading=current_value,
            consumption=consumption,
            price_breakdown=json.dumps(calc_result["price_breakdown"], ensure_ascii=False),
            electricity_amount=calc_result["electricity_amount"],
            additional_fees=json.dumps(calc_result["additional_fees"], ensure_ascii=False) if calc_result["additional_fees"] else None,
            total_amount=calc_result["total_amount"],
        )
        try:
            async with db.begin_nested():
                db.add(invoice)
                await db.flush()
        except IntegrityError:
            existing = await db.execute(
                select(Invoice).where(
                    Invoice.room_id == room.id,
                    Invoice.invoice_month == body.invoice_month,
                )
            )
            existing_invoice = existing.scalar_one_or_none()
            if existing_invoice:
                room_results.append(
                    InvoiceGenerateRoomResult(
                        room_id=room.id,
                        room_number=room.room_number,
                        status="skipped",
                        invoice_id=existing_invoice.id,
                        detail="Hóa đơn tháng này đã được tạo đồng thời",
                    )
                )
                continue
            raise

        resp = _invoice_response(invoice, room)
        invoices_created.append(resp)
        total_amount += calc_result["total_amount"]
        room_results.append(
            InvoiceGenerateRoomResult(
                room_id=room.id,
                room_number=room.room_number,
                status="created",
                invoice_id=invoice.id,
                detail="Đã tạo hóa đơn",
            )
        )

    await db.commit()

    return InvoiceGenerateResponse(
        total_invoices=len(invoices_created),
        total_amount=total_amount,
        invoices=invoices_created,
        total_skipped=sum(result.status == "skipped" for result in room_results),
        total_errors=sum(result.status == "error" for result in room_results),
        results=room_results,
    )


@router.get("", response_model=list[InvoiceResponse])
async def list_invoices(
    building_id: int | None = None,
    invoice_month: str | None = None,
    sent_status: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Invoice, Room)
        .join(Room, Invoice.room_id == Room.id)
        .join(Building, Room.building_id == Building.id)
        .where(Building.owner_id == current_user.id)
        .order_by(Invoice.created_at.desc())
    )

    if building_id is not None:
        await _get_owned_building(db, building_id, current_user.id)
        query = query.where(Room.building_id == building_id)

    if invoice_month:
        _month_bounds(invoice_month)
        query = query.where(Invoice.invoice_month == invoice_month)
    if sent_status:
        query = query.where(Invoice.sent_status == sent_status)

    result = await db.execute(query.offset(offset).limit(limit))
    return [_invoice_response(invoice, room) for invoice, room in result.all()]


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Invoice, Room)
        .join(Room, Invoice.room_id == Room.id)
        .join(Building, Room.building_id == Building.id)
        .where(
            Invoice.id == invoice_id,
            Building.owner_id == current_user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Hóa đơn không tồn tại")
    invoice, room = row
    return _invoice_response(invoice, room)


@router.get("/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Invoice, Room)
        .join(Room, Invoice.room_id == Room.id)
        .join(Building, Room.building_id == Building.id)
        .where(
            Invoice.id == invoice_id,
            Building.owner_id == current_user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Hóa đơn không tồn tại")
    invoice, room = row

    pdf_bytes = generate_invoice_pdf(
        invoice_id=invoice.id,
        invoice_month=invoice.invoice_month,
        room_number=room.room_number,
        resident_name=room.resident_name,
        previous_reading=invoice.previous_reading,
        current_reading=invoice.current_reading,
        consumption=invoice.consumption,
        price_breakdown_json=invoice.price_breakdown,
        electricity_amount=invoice.electricity_amount,
        additional_fees_json=invoice.additional_fees,
        total_amount=invoice.total_amount,
        management_unit=settings.PAYMENT_MANAGEMENT_UNIT,
        bank_account=settings.PAYMENT_BANK_ACCOUNT,
        bank_name=settings.PAYMENT_BANK_NAME,
        account_holder=settings.PAYMENT_ACCOUNT_HOLDER,
    )

    month_safe = invoice.invoice_month.replace("-", "")
    room_safe = room.room_number.replace(" ", "_").replace("/", "-")
    filename = f"hoa-don-{room_safe}-{month_safe}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/export/excel")
async def export_excel(
    building_id: int,
    invoice_month: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import openpyxl

    _month_bounds(invoice_month)
    await _get_owned_building(db, building_id, current_user.id)

    result = await db.execute(
        select(Invoice, Room)
        .join(Room, Invoice.room_id == Room.id)
        .where(
            Room.building_id == building_id,
            Invoice.invoice_month == invoice_month,
        )
        .order_by(Invoice.room_id)
    )
    invoices = result.all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Hóa đơn {invoice_month}"

    headers = ["STT", "Phòng", "Cư dân", "Chỉ số cũ", "Chỉ số mới", "Tiêu thụ (kWh)", "Tiền điện", "Phụ phí", "Tổng cộng", "Trạng thái"]
    ws.append(headers)

    for i, (inv, room) in enumerate(invoices, 1):
        fees = 0
        if inv.additional_fees:
            fees_data = json.loads(inv.additional_fees)
            fees = sum(fees_data.values())

        ws.append([
            i,
            _excel_safe(room.room_number),
            _excel_safe(room.resident_name or ""),
            inv.previous_reading,
            inv.current_reading,
            inv.consumption,
            inv.electricity_amount,
            fees,
            inv.total_amount,
            inv.sent_status,
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"hoa_don_{invoice_month}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
