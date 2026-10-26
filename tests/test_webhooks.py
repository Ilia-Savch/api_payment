import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud import payments as payments_crud
from payment_service.core.models import Payment, PaymentStatus, Tariff
from payment_service.core.models.db_helper import DatabaseHelper

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

PostWebhook = Callable[[dict[str, object]], Awaitable[Response]]


@pytest.fixture
def post_webhook(client: AsyncClient, webhook_secret: SecretStr) -> PostWebhook:
    async def post(payload: dict[str, object]) -> Response:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.digest(
            webhook_secret.get_secret_value().encode("utf-8"), body, "sha256"
        ).hex()
        return await client.post(
            "/webhooks/bank",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature": signature},
        )

    return post


async def payment_snapshot(
    helper: DatabaseHelper, payment_id: int
) -> dict[str, object]:
    async with helper.session() as session:
        result = await session.execute(
            select(Payment.__table__).where(Payment.id == payment_id)
        )
        return dict(result.mappings().one())


@pytest.fixture
async def payment(
    client: AsyncClient, migrated_database: DatabaseHelper
) -> AsyncIterator[tuple[int, dict[str, object]]]:
    email = f"payer-{uuid4().hex}@example.com"
    async with migrated_database.session() as session:
        tariff_id = await session.scalar(
            select(Tariff.id).where(Tariff.title == "standard")
        )
    try:
        response = await client.post(
            "/payments",
            headers={"Idempotency-Key": uuid4().hex},
            json={
                "tariff_id": tariff_id,
                "email": email,
                "method": "installment",
                "installment_months": 3,
                "promo_code": "kvitto10",
            },
        )
        assert response.status_code == 201
        payment_id = int(response.json()["id"])
        yield payment_id, await payment_snapshot(migrated_database, payment_id)
    finally:
        async with migrated_database.session() as session:
            async with session.begin():
                await session.execute(delete(Payment).where(Payment.email == email))


@pytest.mark.parametrize(
    "statuses",
    [
        [PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED],
        [PaymentStatus.FAILED],
    ],
)
async def test_allowed_webhook_transitions(
    post_webhook: PostWebhook,
    migrated_database: DatabaseHelper,
    payment: tuple[int, dict[str, object]],
    statuses: list[PaymentStatus],
    caplog: pytest.LogCaptureFixture,
) -> None:
    payment_id, before = payment
    caplog.set_level(logging.INFO, logger="payment_service.services.payments")
    caplog.clear()
    for status in statuses:
        response = await post_webhook(
            {"payment_id": payment_id, "status": status.value}
        )

        assert response.status_code == 200
        assert response.json() == {"result": "ok"}
        assert await payment_snapshot(migrated_database, payment_id) == {
            **before,
            "status": status,
        }
    assert "Payment status changed:" in caplog.text
    assert str(before["email"]) not in caplog.text
    assert str(before["idempotency_key"]) not in caplog.text


async def test_forbidden_webhook_transitions_leave_payment_unchanged(
    post_webhook: PostWebhook,
    migrated_database: DatabaseHelper,
    payment: tuple[int, dict[str, object]],
) -> None:
    payment_id, original = payment
    forbidden = {
        PaymentStatus.PENDING: [PaymentStatus.PENDING, PaymentStatus.REFUNDED],
        PaymentStatus.SUCCEEDED: [
            PaymentStatus.PENDING,
            PaymentStatus.SUCCEEDED,
            PaymentStatus.FAILED,
        ],
        PaymentStatus.FAILED: list(PaymentStatus),
        PaymentStatus.REFUNDED: list(PaymentStatus),
    }
    for current_status, targets in forbidden.items():
        async with migrated_database.session() as session:
            async with session.begin():
                await session.execute(
                    update(Payment)
                    .where(Payment.id == payment_id)
                    .values(status=current_status)
                )
        for target in targets:
            response = await post_webhook(
                {"payment_id": payment_id, "status": target.value}
            )

            assert response.status_code == 409, (current_status, target)
            assert response.json() == {"error": "invalid_transition"}
            assert await payment_snapshot(migrated_database, payment_id) == {
                **original,
                "status": current_status,
            }


async def test_unknown_payment_and_invalid_status(
    post_webhook: PostWebhook,
    migrated_database: DatabaseHelper,
    payment: tuple[int, dict[str, object]],
) -> None:
    payment_id, before = payment
    async with migrated_database.session() as session:
        missing_id = await session.scalar(
            select(func.coalesce(func.max(Payment.id), 0) + 1)
        )
    for unknown_id in [missing_id, 10**30]:
        response = await post_webhook({"payment_id": unknown_id, "status": "succeeded"})
        assert response.status_code == 404
        assert response.json() == {"detail": "Payment not found"}
    invalid = await post_webhook({"payment_id": payment_id, "status": "unknown"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"] == ["body", "status"]
    assert await payment_snapshot(migrated_database, payment_id) == before


@pytest.mark.parametrize(
    "statuses",
    [
        (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED),
        (PaymentStatus.SUCCEEDED, PaymentStatus.SUCCEEDED),
    ],
)
async def test_concurrent_webhooks_wait_for_row_lock(
    post_webhook: PostWebhook,
    migrated_database: DatabaseHelper,
    payment: tuple[int, dict[str, object]],
    statuses: tuple[PaymentStatus, PaymentStatus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_id, before = payment
    barrier = asyncio.Barrier(2)
    get_for_update = payments_crud.get_payment_for_update
    pids: dict[AsyncSession, int] = {}
    first_holder: AsyncSession | None = None
    lock_observed = False

    async def synchronized_lock(
        session: AsyncSession, target_id: int
    ) -> Payment | None:
        nonlocal first_holder, lock_observed
        pid = await session.scalar(select(func.pg_backend_pid()))
        assert isinstance(pid, int)
        pids[session] = pid
        await asyncio.wait_for(barrier.wait(), timeout=5)
        row = await get_for_update(session, target_id)
        if first_holder is None:
            first_holder = session
            other_pid = next(
                value for owner, value in pids.items() if owner is not session
            )
            # Keep the first transaction open until PostgreSQL confirms the waiter.
            async with asyncio.timeout(5):
                while pid not in (
                    await session.scalar(select(func.pg_blocking_pids(other_pid))) or []
                ):
                    await asyncio.sleep(0)
            lock_observed = True
        return row

    monkeypatch.setattr(payments_crud, "get_payment_for_update", synchronized_lock)
    responses = await asyncio.wait_for(
        asyncio.gather(
            *[
                post_webhook({"payment_id": payment_id, "status": status.value})
                for status in statuses
            ]
        ),
        timeout=15,
    )

    assert len(set(pids.values())) == 2
    assert lock_observed
    assert sorted(response.status_code for response in responses) == [200, 409]
    for response in responses:
        assert response.json() == (
            {"result": "ok"}
            if response.status_code == 200
            else {"error": "invalid_transition"}
        )
    winner = statuses[
        next(i for i, response in enumerate(responses) if response.status_code == 200)
    ]
    assert await payment_snapshot(migrated_database, payment_id) == {
        **before,
        "status": winner,
    }


async def test_invalid_signature_does_not_access_database(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment: tuple[int, dict[str, object]],
    webhook_secret: SecretStr,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payment_id, before = payment
    body = json.dumps({"payment_id": payment_id, "status": "succeeded"}).encode()
    secret = webhook_secret.get_secret_value().encode()
    signature = hmac.digest(secret, body, "sha256").hex()
    wrong_secret_signature = hmac.digest(
        b"another-synthetic-secret", body, "sha256"
    ).hex()
    cases: list[tuple[bytes, list[tuple[str, str]]]] = [
        (body, []),
        (body, [("X-Signature", wrong_secret_signature)]),
        (body, [("X-Signature", "not-hex")]),
        (body, [("X-Signature", "z" * 64)]),
        (body.replace(b"succeeded", b"failed"), [("X-Signature", signature)]),
        (b"{broken-json", []),
        (body, [("X-Signature", signature), ("X-Signature", signature)]),
    ]
    caplog.clear()
    # No rejected request may even obtain a database session.
    with patch.object(
        migrated_database, "session", side_effect=AssertionError("Database accessed")
    ) as session:
        for request_body, headers in cases:
            response = await client.post(
                "/webhooks/bank",
                content=request_body,
                headers=[("Content-Type", "application/json"), *headers],
            )
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid signature"}
        session.assert_not_called()

    assert await payment_snapshot(migrated_database, payment_id) == before
    assert webhook_secret.get_secret_value() not in caplog.text
    assert signature not in caplog.text
    assert wrong_secret_signature not in caplog.text
    assert str(before["email"]) not in caplog.text


async def test_signature_uses_original_body_bytes(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment: tuple[int, dict[str, object]],
    webhook_secret: SecretStr,
) -> None:
    payment_id, before = payment
    payload = {"payment_id": payment_id, "status": "succeeded"}
    body = json.dumps(payload, indent=2).encode("utf-8")
    signature = hmac.digest(
        webhook_secret.get_secret_value().encode("utf-8"), body, "sha256"
    ).hex()
    headers = {"Content-Type": "application/json", "X-Signature": signature}

    accepted = await client.post("/webhooks/bank", content=body, headers=headers)
    reformatted = await client.post(
        "/webhooks/bank",
        content=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"result": "ok"}
    assert reformatted.status_code == 401
    assert await payment_snapshot(migrated_database, payment_id) == {
        **before,
        "status": PaymentStatus.SUCCEEDED,
    }
