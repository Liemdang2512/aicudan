import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.v1.notifications as notifications_api
from app.models.app_setting import AppSetting
from app.models.batch_job import BatchJob
from app.models.invoice import Invoice
from app.models.room import Room
from app.services import notification_service

run_notifications_task = notifications_api.send_notifications_task


@pytest.mark.asyncio
async def test_explicit_empty_owner_token_does_not_fallback_to_global(monkeypatch):
    monkeypatch.setattr(
        notification_service.settings,
        "TELEGRAM_BOT_TOKEN",
        "another-owner-token",
    )

    sent = await notification_service.send_telegram_message(
        "chat-id",
        "message",
        token="",
    )

    assert sent is False


async def _create_invoice(
    db_session: AsyncSession,
    room: Room,
    *,
    month: str = "2025-01",
) -> Invoice:
    invoice = Invoice(
        room_id=room.id,
        invoice_month=month,
        previous_reading=100,
        current_reading=150,
        consumption=50,
        electricity_amount=100_000,
        total_amount=108_000,
    )
    db_session.add(invoice)
    await db_session.commit()
    await db_session.refresh(invoice)
    return invoice


async def _queue_without_running_worker(
    client,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    invoice_ids: list[int],
) -> dict:
    async def skip_worker(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(notifications_api, "send_notifications_task", skip_worker)
    response = await client.post(
        "/api/v1/notifications/send-batch",
        headers=auth_headers,
        json={"invoice_ids": invoice_ids, "include_image": False},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_send_batch_is_owner_scoped_and_rejects_mixed_ownership(
    client,
    auth_headers,
    test_invoice: Invoice,
    second_invoice: Invoice,
):
    response = await client.post(
        "/api/v1/notifications/send-batch",
        headers=auth_headers,
        json={"invoice_ids": [test_invoice.id, second_invoice.id]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Hóa đơn không tồn tại"


@pytest.mark.asyncio
async def test_send_batch_rejects_non_positive_invoice_id(client, auth_headers):
    response = await client.post(
        "/api/v1/notifications/send-batch",
        headers=auth_headers,
        json={"invoice_ids": [0]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_notification_job_status_is_visible_only_to_creator(
    client,
    db_session: AsyncSession,
    auth_headers,
    second_auth_headers,
    test_user,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    queued = await _queue_without_running_worker(
        client, auth_headers, monkeypatch, [test_invoice.id]
    )

    assert queued["status"] == "queued"
    job = (
        await db_session.execute(
            select(BatchJob).where(BatchJob.job_id == queued["job_id"])
        )
    ).scalar_one()
    context = json.loads(job.result_data)
    assert context["owner_id"] == test_user.id
    assert context["invoice_ids"] == [test_invoice.id]
    await db_session.refresh(test_invoice)
    assert test_invoice.sent_status == "sending"

    own_status = await client.get(
        f"/api/v1/notifications/status/{queued['job_id']}", headers=auth_headers
    )
    assert own_status.status_code == 200
    assert own_status.json() == {
        "job_id": queued["job_id"],
        "status": "queued",
        "total": 1,
        "processed": 0,
        "sent": 0,
        "failed": 0,
    }

    other_status = await client.get(
        f"/api/v1/notifications/status/{queued['job_id']}",
        headers=second_auth_headers,
    )
    assert other_status.status_code == 404


@pytest.mark.asyncio
async def test_worker_completes_with_sent_missing_id_and_provider_failure(
    client,
    db_session: AsyncSession,
    auth_headers,
    test_user,
    test_building,
    test_room: Room,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    test_room.telegram_id = "chat-success"
    missing_room = Room(
        building_id=test_building.id,
        room_number="102",
        resident_name="Thiếu Telegram",
    )
    failed_room = Room(
        building_id=test_building.id,
        room_number="103",
        resident_name="Provider lỗi",
        telegram_id="chat-provider-fail",
    )
    db_session.add_all([missing_room, failed_room])
    await db_session.commit()
    missing_invoice = await _create_invoice(db_session, missing_room)
    provider_failed_invoice = await _create_invoice(db_session, failed_room)

    queued = await _queue_without_running_worker(
        client,
        auth_headers,
        monkeypatch,
        [test_invoice.id, missing_invoice.id, provider_failed_invoice.id],
    )

    observed_job_statuses: list[str] = []
    provider_calls: list[str] = []
    provider_tokens: list[str | None] = []
    rate_limit_calls = 0
    worker_session_factory = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    db_session.add(
        AppSetting(owner_id=test_user.id, telegram_bot_token="owner-manager-token")
    )
    await db_session.commit()

    async def fake_send(
        chat_id: str,
        text: str,
        photo_path: str | None,
        token: str | None = None,
    ) -> bool:
        provider_calls.append(chat_id)
        provider_tokens.append(token)
        async with worker_session_factory() as session:
            job = (
                await session.execute(
                    select(BatchJob).where(BatchJob.job_id == queued["job_id"])
                )
            ).scalar_one()
            observed_job_statuses.append(job.status)
        return chat_id == "chat-success"

    async def skip_rate_limit() -> None:
        nonlocal rate_limit_calls
        rate_limit_calls += 1

    monkeypatch.setattr(notifications_api, "async_session", worker_session_factory)
    monkeypatch.setattr(notifications_api, "send_telegram_message", fake_send)
    monkeypatch.setattr(
        notifications_api, "wait_for_notification_rate_limit", skip_rate_limit
    )

    await run_notifications_task(
        queued["job_id"],
        [test_invoice.id, missing_invoice.id, provider_failed_invoice.id],
        False,
        test_user.id,
    )

    db_session.expire_all()
    completed = await client.get(
        f"/api/v1/notifications/status/{queued['job_id']}", headers=auth_headers
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["processed"] == 3
    assert completed.json()["sent"] == 1
    assert completed.json()["failed"] == 2
    assert observed_job_statuses == ["processing", "processing"]
    assert provider_calls == ["chat-success", "chat-provider-fail"]
    assert provider_tokens == ["owner-manager-token", "owner-manager-token"]
    assert rate_limit_calls == 2

    for invoice, expected in (
        (test_invoice, "sent"),
        (missing_invoice, "failed"),
        (provider_failed_invoice, "failed"),
    ):
        await db_session.refresh(invoice)
        assert invoice.sent_status == expected


@pytest.mark.asyncio
async def test_worker_marks_invoice_failed_when_room_disappears_after_queue(
    client,
    db_session: AsyncSession,
    auth_headers,
    test_user,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    queued = await _queue_without_running_worker(
        client, auth_headers, monkeypatch, [test_invoice.id]
    )
    test_invoice.room_id = 999_999
    await db_session.commit()

    async def provider_must_not_run(*args, **kwargs) -> bool:
        raise AssertionError("Telegram provider must not run without a room")

    worker_session_factory = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(notifications_api, "async_session", worker_session_factory)
    monkeypatch.setattr(
        notifications_api, "send_telegram_message", provider_must_not_run
    )

    await run_notifications_task(
        queued["job_id"], [test_invoice.id], False, test_user.id
    )

    db_session.expire_all()
    await db_session.refresh(test_invoice)
    assert test_invoice.sent_status == "failed"
    status = await client.get(
        f"/api/v1/notifications/status/{queued['job_id']}", headers=auth_headers
    )
    assert status.json()["status"] == "completed"
    assert status.json()["processed"] == 1
    assert status.json()["failed"] == 1


@pytest.mark.asyncio
async def test_worker_records_provider_exception_as_failed_item(
    client,
    db_session: AsyncSession,
    auth_headers,
    test_user,
    test_room: Room,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    test_room.telegram_id = "chat-raises"
    await db_session.commit()
    queued = await _queue_without_running_worker(
        client, auth_headers, monkeypatch, [test_invoice.id]
    )

    async def raise_provider_error(*args, **kwargs) -> bool:
        raise RuntimeError("provider unavailable")

    worker_session_factory = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(notifications_api, "async_session", worker_session_factory)
    monkeypatch.setattr(
        notifications_api, "send_telegram_message", raise_provider_error
    )

    await run_notifications_task(
        queued["job_id"], [test_invoice.id], False, test_user.id
    )

    db_session.expire_all()
    await db_session.refresh(test_invoice)
    assert test_invoice.sent_status == "failed"
    status = await client.get(
        f"/api/v1/notifications/status/{queued['job_id']}", headers=auth_headers
    )
    assert status.json()["status"] == "completed"
    assert status.json()["processed"] == 1
    assert status.json()["sent"] == 0
    assert status.json()["failed"] == 1


@pytest.mark.asyncio
async def test_worker_marks_job_failed_without_overcounting_unprocessed_items(
    client,
    db_session: AsyncSession,
    auth_headers,
    test_user,
    test_building,
    test_room: Room,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    test_room.telegram_id = "chat-first"
    second_room = Room(
        building_id=test_building.id,
        room_number="104",
        resident_name="Chưa xử lý",
        telegram_id="chat-second",
    )
    db_session.add(second_room)
    await db_session.commit()
    second_invoice = await _create_invoice(db_session, second_room)
    queued = await _queue_without_running_worker(
        client,
        auth_headers,
        monkeypatch,
        [test_invoice.id, second_invoice.id],
    )

    async def fake_send(*args, **kwargs) -> bool:
        return True

    async def fail_rate_limit() -> None:
        raise RuntimeError("worker interrupted")

    worker_session_factory = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(notifications_api, "async_session", worker_session_factory)
    monkeypatch.setattr(notifications_api, "send_telegram_message", fake_send)
    monkeypatch.setattr(
        notifications_api, "wait_for_notification_rate_limit", fail_rate_limit
    )

    await run_notifications_task(
        queued["job_id"],
        [test_invoice.id, second_invoice.id],
        False,
        test_user.id,
    )

    db_session.expire_all()
    await db_session.refresh(test_invoice)
    await db_session.refresh(second_invoice)
    assert test_invoice.sent_status == "sent"
    assert second_invoice.sent_status == "failed"

    status = await client.get(
        f"/api/v1/notifications/status/{queued['job_id']}", headers=auth_headers
    )
    assert status.json()["status"] == "failed"
    assert status.json()["processed"] == 1
    assert status.json()["sent"] == 1
    assert status.json()["failed"] == 0


@pytest.mark.asyncio
async def test_two_consecutive_requests_create_only_one_notification_job(
    client,
    db_session: AsyncSession,
    auth_headers,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    first = await _queue_without_running_worker(
        client, auth_headers, monkeypatch, [test_invoice.id]
    )
    second = await client.post(
        "/api/v1/notifications/send-batch",
        headers=auth_headers,
        json={"invoice_ids": [test_invoice.id], "include_image": False},
    )

    assert first["status"] == "queued"
    assert second.status_code == 409
    jobs = (
        await db_session.execute(
            select(BatchJob).where(BatchJob.job_type == "notification")
        )
    ).scalars().all()
    assert [job.job_id for job in jobs] == [first["job_id"]]
    await db_session.refresh(test_invoice)
    assert test_invoice.sent_status == "sending"


@pytest.mark.asyncio
async def test_enqueue_failure_rolls_back_invoice_claim_and_job(
    client,
    db_session: AsyncSession,
    auth_headers,
    test_invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_enqueue(*args, **kwargs) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(notifications_api.BackgroundTasks, "add_task", fail_enqueue)
    response = await client.post(
        "/api/v1/notifications/send-batch",
        headers=auth_headers,
        json={"invoice_ids": [test_invoice.id], "include_image": False},
    )

    assert response.status_code == 503
    db_session.expire_all()
    await db_session.refresh(test_invoice)
    assert test_invoice.sent_status == "pending"
    jobs = (
        await db_session.execute(
            select(BatchJob).where(BatchJob.job_type == "notification")
        )
    ).scalars().all()
    assert jobs == []


@pytest.mark.asyncio
async def test_rate_limit_delay_can_be_monkeypatched(
    monkeypatch: pytest.MonkeyPatch,
):
    observed_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        observed_delays.append(delay)

    monkeypatch.setattr(notification_service, "NOTIFICATION_SEND_DELAY_SECONDS", 0)
    monkeypatch.setattr(notification_service.asyncio, "sleep", fake_sleep)

    await notification_service.wait_for_notification_rate_limit()

    assert observed_delays == [0]
