from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from payment_service.core.config import TariffsConfig
from payment_service.core.models import Payment, PaymentMethod, PaymentStatus, Tariff
from payment_service.core.models.db_helper import DatabaseHelper
from payment_service.main import create_app
from payment_service.services.tariffs import sync_tariffs

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def client(migrated_database: DatabaseHelper) -> AsyncIterator[AsyncClient]:
    async with migrated_database.session() as session:
        await sync_tariffs(session, TariffsConfig())
    application = create_app()
    application.state.db_helper = migrated_database
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as http_client:
        yield http_client


async def test_get_tariffs(
    client: AsyncClient, migrated_database: DatabaseHelper
) -> None:
    async with migrated_database.session() as session:
        rows = await session.execute(
            select(Tariff.id, Tariff.title, Tariff.price).order_by(Tariff.id)
        )
        expected = [
            {"id": tariff_id, "title": title, "price": price}
            for tariff_id, title, price in rows
        ]

    response = await client.get("/tariffs")

    assert response.status_code == 200
    assert response.json() == expected
    assert {row["title"]: row["price"] for row in response.json()} == {
        "basic": 990000,
        "standard": 1990000,
        "premium": 2990000,
    }
    assert all(type(row["price"]) is type(row["id"]) is int for row in response.json())


@pytest.mark.parametrize(
    ("method", "months", "schedule"),
    [
        (PaymentMethod.CARD, None, None),
        (PaymentMethod.SBP, None, None),
        (PaymentMethod.INSTALLMENT, 3, [663334, 663333, 663333]),
    ],
)
async def test_get_payment_serialization(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    method: PaymentMethod,
    months: int | None,
    schedule: list[int] | None,
) -> None:
    helper = migrated_database
    created_at = datetime(
        2026, 10, 26, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=3))
    )
    async with helper.session() as session:
        async with session.begin():
            tariff_id = await session.scalar(
                select(Tariff.id).where(Tariff.title == "standard")
            )
            assert tariff_id is not None
            payment = Payment(
                tariff_id=tariff_id,
                amount=1990000,
                discount=0,
                method=method,
                installment_months=months,
                schedule=schedule,
                email="payer@example.com",
                created_at=created_at,
                idempotency_key=uuid4().hex,
            )
            session.add(payment)
            await session.flush()
            payment_id = payment.id

    try:
        response = await client.get(f"/payments/{payment_id}")

        assert response.status_code == 200
        payload = response.json()
        serialized_time = payload.pop("created_at")
        assert isinstance(serialized_time, str)
        parsed_time = datetime.fromisoformat(serialized_time)
        assert parsed_time.tzinfo is not None
        assert parsed_time == created_at
        assert payload == {
            "id": payment_id,
            "status": "pending",
            "tariff_id": tariff_id,
            "amount": 1990000,
            "discount": 0,
            "method": method.value,
            "installment_months": months,
            "schedule": schedule,
            "email": "payer@example.com",
        }
        assert type(payload["amount"]) is type(payload["discount"]) is int
        if schedule is not None:
            assert all(type(amount) is int for amount in payload["schedule"])

        async with helper.session() as session:
            saved = await session.get(Payment, payment_id)
            assert saved is not None
            assert saved.status == PaymentStatus.PENDING
            assert saved.amount == 1990000
            assert saved.discount == 0
            assert saved.schedule == schedule
            assert saved.created_at == created_at
    finally:
        async with helper.session() as session:
            async with session.begin():
                await session.execute(delete(Payment).where(Payment.id == payment_id))


@pytest.mark.parametrize("payment_id", [None, 2**31, 10**30])
async def test_get_unknown_payment_returns_404(
    client: AsyncClient,
    migrated_database: DatabaseHelper,
    payment_id: int | None,
) -> None:
    if payment_id is None:
        async with migrated_database.session() as session:
            payment_id = await session.scalar(
                select(func.coalesce(func.max(Payment.id), 0) + 1)
            )
    response = await client.get(f"/payments/{payment_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}


async def test_get_payments_filters(
    client: AsyncClient, migrated_database: DatabaseHelper
) -> None:
    helper = migrated_database
    suffix = uuid4().hex
    email = f"payer-{suffix}@example.com"
    other_email = f"payer-{suffix}-other@example.com"
    async with helper.session() as session:
        async with session.begin():
            tariff_id = await session.scalar(
                select(Tariff.id).where(Tariff.title == "basic")
            )
            payments = [
                Payment(
                    tariff_id=tariff_id,
                    amount=990000,
                    discount=0,
                    method=PaymentMethod.CARD,
                    email=payer_email,
                    status=payment_status,
                )
                for payer_email, payment_status in [
                    (email, PaymentStatus.PENDING),
                    (email, PaymentStatus.SUCCEEDED),
                    (other_email, PaymentStatus.PENDING),
                    (other_email, PaymentStatus.FAILED),
                    (other_email, PaymentStatus.REFUNDED),
                ]
            ]
            session.add_all(payments)
            await session.flush()
            payment_ids = [payment.id for payment in payments]

    try:
        async with helper.session() as session:
            before = (
                await session.execute(
                    select(Payment.id, Payment.email, Payment.status).order_by(
                        Payment.id
                    )
                )
            ).all()

        cases: list[tuple[dict[str, str], list[int]]] = [
            ({}, [row.id for row in before]),
            ({"email": email}, payment_ids[:2]),
            ({"email": other_email}, payment_ids[2:]),
            ({"email": email, "status": "pending"}, payment_ids[:1]),
            ({"email": email, "status": "failed"}, []),
            ({"email": f"missing-{suffix}@example.com"}, []),
        ]
        cases.extend(
            (
                {"status": payment_status.value},
                [row.id for row in before if row.status == payment_status],
            )
            for payment_status in PaymentStatus
        )
        for params, expected_ids in cases:
            response = await client.get("/payments", params=params)

            assert response.status_code == 200
            payload = response.json()
            assert [payment["id"] for payment in payload] == expected_ids
            assert all("idempotency_key" not in payment for payment in payload)

        async with helper.session() as session:
            after = (
                await session.execute(
                    select(Payment.id, Payment.email, Payment.status).order_by(
                        Payment.id
                    )
                )
            ).all()
        assert after == before
    finally:
        async with helper.session() as session:
            async with session.begin():
                await session.execute(
                    delete(Payment).where(Payment.id.in_(payment_ids))
                )


@pytest.mark.parametrize(
    ("params", "field"),
    [({"email": "not-an-email"}, "email"), ({"status": "unknown"}, "status")],
)
async def test_get_payments_invalid_filter_returns_422(
    client: AsyncClient, params: dict[str, str], field: str
) -> None:
    response = await client.get("/payments", params=params)

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert len(errors) == 1
    assert errors[0]["loc"] == ["query", field]
    assert {"type", "msg", "input"} <= errors[0].keys()
