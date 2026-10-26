import asyncio
import logging
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import (
    Table,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.dependencies.database import get_session
from payment_service.core.config import TariffsConfig
from payment_service.core.models import Payment, PaymentMethod, PaymentStatus, Tariff
from payment_service.core.models.db_helper import DatabaseHelper
from payment_service.services.tariffs import sync_tariffs

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_initial_tariffs_survive_repeated_and_concurrent_startup(
    migrated_database: DatabaseHelper,
) -> None:
    helper = migrated_database

    async def initialize() -> int:
        async with helper.session() as session:
            return await sync_tariffs(session, TariffsConfig())

    await asyncio.gather(initialize(), initialize())
    async with helper.session() as session:
        before = (
            await session.execute(select(Tariff.id, Tariff.title, Tariff.price))
        ).all()
    assert await initialize() == 0
    async with helper.session() as session:
        after = (
            await session.execute(select(Tariff.id, Tariff.title, Tariff.price))
        ).all()
    assert set(before) == set(after)
    assert {row.title: row.price for row in after} == {
        "basic": 990000,
        "standard": 1990000,
        "premium": 2990000,
    }
    assert len(after) == 3


async def test_payment_unique_key_and_foreign_key_are_enforced(
    migrated_database: DatabaseHelper,
) -> None:
    helper = migrated_database
    email = f"payer-{uuid4().hex}@example.com"
    key = uuid4().hex
    async with helper.session() as session:
        await sync_tariffs(session, TariffsConfig())
        tariff_id = await session.scalar(
            select(Tariff.id).where(Tariff.title == "basic")
        )
    assert tariff_id is not None
    default_tariff_id = int(tariff_id)

    async def create(key: str | None, tariff: int = default_tariff_id) -> bool:
        try:
            async with helper.session() as session:
                async with session.begin():
                    session.add(
                        Payment(
                            tariff_id=tariff,
                            amount=990000,
                            discount=0,
                            method=PaymentMethod.CARD,
                            email=email,
                            idempotency_key=key,
                        )
                    )
            return True
        except IntegrityError:
            return False

    try:
        assert sorted(await asyncio.gather(create(key), create(key))) == [False, True]
        assert await create(None)
        assert await create(None)
        assert not await create(uuid4().hex, tariff=-1)
        async with helper.session() as session:
            rows = (
                await session.scalars(select(Payment).where(Payment.email == email))
            ).all()
            assert len(rows) == 3
            assert all(row.status == PaymentStatus.PENDING for row in rows)
            assert all(row.created_at.tzinfo is not None for row in rows)
    finally:
        async with helper.session() as session:
            async with session.begin():
                await session.execute(delete(Payment).where(Payment.email == email))


async def test_price_sync_preserves_tariff_ids_and_existing_payments(
    migrated_database: DatabaseHelper, caplog: pytest.LogCaptureFixture
) -> None:
    helper = migrated_database
    config = TariffsConfig()
    async with helper.session() as session:
        await sync_tariffs(session, config)
        before = {
            title: tariff_id
            for title, tariff_id in await session.execute(
                select(Tariff.title, Tariff.id)
            )
        }
    payment_id: int | None = None
    try:
        async with helper.session() as session:
            async with session.begin():
                payment = Payment(
                    tariff_id=before["standard"],
                    amount=1791000,
                    discount=199000,
                    method=PaymentMethod.INSTALLMENT,
                    installment_months=3,
                    schedule=[597000, 597000, 597000],
                    email="payer@example.com",
                )
                session.add(payment)
                await session.flush()
                payment_id = payment.id

        caplog.set_level(logging.INFO, logger="payment_service.services.tariffs")
        caplog.clear()
        changed = TariffsConfig(standard_price=2100000)
        async with helper.session() as session:
            assert await sync_tariffs(session, changed) == 1
        assert "standard 1990000 -> 2100000" in caplog.text

        async with helper.session() as session:
            tariffs = (
                await session.execute(select(Tariff.title, Tariff.id, Tariff.price))
            ).all()
            assert {row.title: row.id for row in tariffs} == before
            assert {row.title: row.price for row in tariffs} == {
                "basic": 990000,
                "standard": 2100000,
                "premium": 2990000,
            }
            saved = await session.get(Payment, payment_id)
            assert saved is not None
            assert saved.amount == 1791000
            assert saved.discount == 199000
            assert saved.schedule == [597000, 597000, 597000]

        caplog.clear()
        async with helper.session() as session:
            assert await sync_tariffs(session, changed) == 0
        assert not caplog.records
    finally:
        async with helper.session() as session:
            await sync_tariffs(session, config)
            async with session.begin():
                if payment_id is not None:
                    await session.execute(
                        delete(Payment).where(Payment.id == payment_id)
                    )


async def test_transaction_commits_on_success(
    database: tuple[DatabaseHelper, Table],
) -> None:
    helper, table = database
    async with helper.session() as session:
        async with session.begin():
            await session.execute(insert(table).values(id=1, value=10))

    async with helper.session() as verification:
        assert await verification.scalar(select(table.c.value)) == 10


async def test_transaction_rolls_back_on_application_error(
    database: tuple[DatabaseHelper, Table],
) -> None:
    helper, table = database
    async with helper.session() as session:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            async with session.begin():
                await session.execute(insert(table).values(id=1, value=10))
                raise RuntimeError("synthetic failure")
        assert not session.in_transaction()

    async with helper.session() as verification:
        assert await verification.scalar(select(func.count()).select_from(table)) == 0


async def test_session_cleanup_rolls_back_uncommitted_work(
    database: tuple[DatabaseHelper, Table],
) -> None:
    helper, table = database
    async with helper.session() as session:
        await session.execute(insert(table).values(id=1, value=10))

    async with helper.session() as verification:
        assert await verification.scalar(select(func.count()).select_from(table)) == 0


async def test_concurrent_requests_have_independent_sessions(
    database: tuple[DatabaseHelper, Table],
) -> None:
    helper, _ = database
    application = FastAPI()
    application.state.db_helper = helper
    sessions: list[AsyncSession] = []
    both_connected = asyncio.Event()

    @application.get("/probe")
    async def probe(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, int]:
        backend_pid = await session.scalar(select(func.pg_backend_pid()))
        assert isinstance(backend_pid, int)
        sessions.append(session)
        if len(sessions) == 2:
            both_connected.set()
        await asyncio.wait_for(both_connected.wait(), timeout=5)
        return {"backend_pid": backend_pid}

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        first, second = await asyncio.gather(client.get("/probe"), client.get("/probe"))

    assert first.status_code == second.status_code == 200
    assert sessions[0] is not sessions[1]
    assert first.json()["backend_pid"] != second.json()["backend_pid"]
