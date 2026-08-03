import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import async_session, get_db
from app.models.batch_job import BatchJob
from app.models.building import Building
from app.models.invoice import Invoice
from app.models.room import Room
from app.models.user import User
from app.schemas.notification import (
    NotificationStatusResponse,
    SendBatchRequest,
    SendBatchResponse,
)
from app.services.notification_service import (
    format_invoice_message,
    send_telegram_message,
    wait_for_notification_rate_limit,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_job_context(job: BatchJob) -> dict:
    if not job.result_data:
        return {}
    try:
        data = json.loads(job.result_data)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _store_job_context(job: BatchJob, context: dict) -> None:
    job.result_data = json.dumps(context, ensure_ascii=False)


async def send_notifications_task(
    job_id: str,
    invoice_ids: list[int],
    include_image: bool,
    owner_id: int,
) -> None:
    async with async_session() as db:
        sent = 0
        failed = 0
        processed = 0
        try:
            result = await db.execute(select(BatchJob).where(BatchJob.job_id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                return

            context = _load_job_context(job)
            if (
                context.get("owner_id") != owner_id
                or context.get("invoice_ids") != invoice_ids
            ):
                raise ValueError("Notification job owner context is invalid")

            job_claim = await db.execute(
                update(BatchJob)
                .where(BatchJob.job_id == job_id, BatchJob.status == "queued")
                .values(status="processing")
                .execution_options(synchronize_session=False)
            )
            if job_claim.rowcount != 1:
                await db.rollback()
                return
            await db.commit()
            await db.refresh(job)

            for index, inv_id in enumerate(invoice_ids):
                item_result = {"invoice_id": inv_id, "status": "failed"}
                invoice = None
                try:
                    inv_result = await db.execute(
                        select(Invoice).where(Invoice.id == inv_id)
                    )
                    invoice = inv_result.scalar_one_or_none()
                    room = None
                    room_owner_id = None
                    if invoice:
                        room_result = await db.execute(
                            select(Room, Building.owner_id)
                            .join(Building, Room.building_id == Building.id)
                            .where(Room.id == invoice.room_id)
                        )
                        room_row = room_result.one_or_none()
                        if room_row:
                            room, room_owner_id = room_row

                    if not invoice:
                        item_result["reason"] = "invoice_not_found"
                    elif invoice.sent_status != "sending":
                        item_result["reason"] = "claim_lost"
                    elif not room:
                        invoice.sent_status = "failed"
                        invoice.sent_at = None
                        item_result["reason"] = "room_not_found"
                    elif room_owner_id != owner_id:
                        invoice.sent_status = "failed"
                        invoice.sent_at = None
                        item_result["reason"] = "ownership_changed"
                    elif not room.telegram_id:
                        invoice.sent_status = "failed"
                        invoice.sent_at = None
                        item_result["reason"] = "missing_telegram_id"
                    else:
                        message = format_invoice_message(
                            room_number=room.room_number,
                            resident_name=room.resident_name,
                            invoice_month=invoice.invoice_month,
                            previous_reading=invoice.previous_reading,
                            current_reading=invoice.current_reading,
                            consumption=invoice.consumption,
                            price_breakdown_str=invoice.price_breakdown,
                            electricity_amount=invoice.electricity_amount,
                            additional_fees_str=invoice.additional_fees,
                            total_amount=invoice.total_amount,
                        )

                        photo_path = None
                        if include_image and invoice.reading_id:
                            from app.models.reading import MeterReading

                            reading_result = await db.execute(
                                select(MeterReading).where(
                                    MeterReading.id == invoice.reading_id
                                )
                            )
                            reading = reading_result.scalar_one_or_none()
                            if reading and reading.image_path:
                                photo_path = reading.image_path

                        success = await send_telegram_message(
                            room.telegram_id, message, photo_path
                        )
                        if success:
                            invoice.sent_status = "sent"
                            invoice.sent_at = _utcnow()
                            item_result["status"] = "sent"
                            sent += 1
                        else:
                            invoice.sent_status = "failed"
                            invoice.sent_at = None
                            item_result["reason"] = "provider_error"

                    if item_result["status"] == "failed":
                        failed += 1
                except Exception:
                    logger.exception(
                        "Notification item failed for invoice_id=%s", inv_id
                    )
                    if invoice and invoice.sent_status == "sending":
                        invoice.sent_status = "failed"
                        invoice.sent_at = None
                    item_result["reason"] = "send_error"
                    failed += 1

                processed += 1
                context.setdefault("results", []).append(item_result)
                job.processed_items = processed
                job.failed_items = failed
                _store_job_context(job, context)
                await db.commit()

                if index < len(invoice_ids) - 1:
                    await wait_for_notification_rate_limit()

            job.status = "completed"
            job.completed_at = _utcnow()
            await db.commit()
        except Exception:
            logger.exception("Notification job failed for job_id=%s", job_id)
            await db.rollback()
            await db.execute(
                update(Invoice)
                .where(
                    Invoice.id.in_(invoice_ids[processed:]),
                    Invoice.sent_status == "sending",
                )
                .values(sent_status="failed", sent_at=None)
                .execution_options(synchronize_session=False)
            )
            result = await db.execute(select(BatchJob).where(BatchJob.job_id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                job.processed_items = processed
                job.failed_items = failed
                job.error_message = "Không thể hoàn tất tác vụ gửi thông báo"
                job.completed_at = _utcnow()
                await db.commit()


@router.post("/send-batch", response_model=SendBatchResponse)
async def send_batch(
    body: SendBatchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invoice_ids = list(dict.fromkeys(body.invoice_ids))
    result = await db.execute(
        select(Invoice.id, Invoice.sent_status, Room.building_id)
        .join(Room, Invoice.room_id == Room.id)
        .join(Building, Room.building_id == Building.id)
        .where(
            Invoice.id.in_(invoice_ids),
            Building.owner_id == current_user.id,
        )
    )
    owned_invoices = result.all()
    if len(owned_invoices) != len(invoice_ids):
        raise HTTPException(status_code=404, detail="Hóa đơn không tồn tại")

    job_id = f"notify_{uuid.uuid4().hex[:12]}"

    batch_job = BatchJob(
        job_id=job_id,
        job_type="notification",
        status="queued",
        total_items=len(invoice_ids),
        result_data=json.dumps(
            {
                "owner_id": current_user.id,
                "invoice_ids": invoice_ids,
                "building_ids": sorted({row.building_id for row in owned_invoices}),
                "results": [],
            }
        ),
    )
    try:
        claim_result = await db.execute(
            update(Invoice)
            .where(
                Invoice.id.in_(invoice_ids),
                Invoice.sent_status.in_(("pending", "failed")),
            )
            .values(sent_status="sending", sent_at=None)
            .execution_options(synchronize_session=False)
        )
        if claim_result.rowcount != len(invoice_ids):
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Một hoặc nhiều hóa đơn đang được gửi hoặc đã gửi",
            )

        db.add(batch_job)
        await db.flush()
        background_tasks.add_task(
            send_notifications_task,
            job_id,
            invoice_ids,
            body.include_image,
            current_user.id,
        )
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        logger.exception("Unable to enqueue notification job")
        raise HTTPException(
            status_code=503,
            detail="Không thể tạo tác vụ gửi thông báo",
        ) from None

    return SendBatchResponse(
        job_id=job_id,
        total=len(invoice_ids),
        status="queued",
    )


@router.get("/status/{job_id}", response_model=NotificationStatusResponse)
async def notification_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BatchJob).where(BatchJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    context = _load_job_context(job)
    if context.get("owner_id") != current_user.id:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    return NotificationStatusResponse(
        job_id=job.job_id,
        status=job.status,
        total=job.total_items,
        processed=job.processed_items,
        sent=job.processed_items - job.failed_items,
        failed=job.failed_items,
    )
