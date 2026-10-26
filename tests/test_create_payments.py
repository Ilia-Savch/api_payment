import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud import payments as payments_crud
from payment_service.core.models import Payment, PaymentStatus, Tariff
from payment_service.core.models.db_helper import DatabaseHelper

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def payment_data(
    client: AsyncClient, migrated_database: DatabaseHelper
) -> AsyncIterator[dict[str, object]]:
    email = f"payer-{uuid4().hex}@example.com"
    async with migrated_database.session() as session:
        tariff_id = await session.scalar(
            select(Tariff.id).where(Tariff.title == "standard")
        )
    assert tariff_id is not None
    try:
        yield {"tariff_id": tariff_id, "email": email, "method": "card"}
    finally:
        async with migrated_database.session() as session:
            async with session.begin():
                await session.execute(delete(Payment).where(Payment.email == email))


@pytest.mark.parametrize(
    ("fields", "amount", "discount", "schedule"),
    [
        ({}, 1990000, 0, None),
        (
            {
                "method": "installment",
                "installment_months": 3,
                "promo_code": "kvitto10",
            },
            1791000,
            199000,
            [597000, 597000, 597000],
        ),
    ],
)
async def test_create_payment_uses_server_values(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment_data: dict[str, object],
    fields: dict[str, object],
    amount: int,
    discount: int,
    schedule: list[int] | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="payment_service.services.payments")
    response = await client.post(
        "/payments",
        json={
            **payment_data,
            **fields,
            "amount": 1,
            "discount": 1,
            "status": "succeeded",
            "schedule": [1],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["amount"] == amount
    assert payload["discount"] == discount
    assert payload["schedule"] == schedule
    assert payload["installment_months"] == fields.get("installment_months")
    assert "idempotency_key" not in payload
    assert "Payment created:" in caplog.text
    assert str(payment_data["email"]) not in caplog.text
    async with migrated_database.session() as session:
        saved = await session.get(Payment, payload["id"])
        assert saved is not None
        assert saved.amount == amount
        assert saved.discount == discount
        assert saved.status == PaymentStatus.PENDING
        assert saved.schedule == schedule
        assert saved.email == payment_data["email"]


async def test_repeated_key_returns_original_payment(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment_data: dict[str, object],
) -> None:
    key = uuid4().hex
    headers = {"Idempotency-Key": key}
    first = await client.post("/payments", json=payment_data, headers=headers)
    repeated = await client.post(
        "/payments",
        json={**payment_data, "tariff_id": -1, "method": "sbp"},
        headers=headers,
    )

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    async with migrated_database.session() as session:
        payments = (
            await session.scalars(select(Payment).where(Payment.idempotency_key == key))
        ).all()
        assert len(payments) == 1
        assert payments[0].id == first.json()["id"]
        assert payments[0].amount == 1990000


async def test_concurrent_key_creates_exactly_one_payment(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = uuid4().hex
    barrier = asyncio.Barrier(2)
    insert_payment = payments_crud.insert_payment
    sessions: list[AsyncSession] = []

    async def simultaneous_insert(
        session: AsyncSession, payment: Payment
    ) -> Payment | None:
        sessions.append(session)
        await asyncio.wait_for(barrier.wait(), timeout=5)
        return await insert_payment(session, payment)

    monkeypatch.setattr(payments_crud, "insert_payment", simultaneous_insert)
    first, second = await asyncio.wait_for(
        asyncio.gather(
            client.post(
                "/payments", json=payment_data, headers={"Idempotency-Key": key}
            ),
            client.post(
                "/payments", json=payment_data, headers={"Idempotency-Key": key}
            ),
        ),
        timeout=15,
    )

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert sorted([first.status_code, second.status_code]) == [200, 201]
    assert first.json() == second.json()
    async with migrated_database.session() as session:
        payments = (
            await session.scalars(select(Payment).where(Payment.idempotency_key == key))
        ).all()
        assert len(payments) == 1
        assert payments[0].id == first.json()["id"]
        assert payments[0].status == PaymentStatus.PENDING
        assert payments[0].amount == 1990000


async def test_requests_without_key_create_separate_payments(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment_data: dict[str, object],
) -> None:
    first = await client.post("/payments", json=payment_data)
    second = await client.post("/payments", json=payment_data)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    async with migrated_database.session() as session:
        payments = (
            await session.scalars(
                select(Payment).where(Payment.email == payment_data["email"])
            )
        ).all()
        assert {payment.id for payment in payments} == {
            first.json()["id"],
            second.json()["id"],
        }
        assert all(payment.idempotency_key is None for payment in payments)


async def test_invalid_creation_does_not_write_payment(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment_data: dict[str, object],
) -> None:
    unknown_tariff = await client.post(
        "/payments", json={**payment_data, "tariff_id": -1}
    )
    invalid_promo = await client.post(
        "/payments", json={**payment_data, "promo_code": "UNKNOWN"}
    )

    assert unknown_tariff.status_code == 404
    assert unknown_tariff.json() == {"detail": "Tariff not found"}
    assert invalid_promo.status_code == 422
    assert invalid_promo.json()["detail"][0]["loc"] == ["body", "promo_code"]
    async with migrated_database.session() as session:
        saved = await session.scalar(
            select(Payment.id).where(Payment.email == payment_data["email"])
        )
        assert saved is None
