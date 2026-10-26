from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.core.models.payment import Payment, PaymentStatus


async def get_payment_by_key(
    session: AsyncSession, idempotency_key: str
) -> Payment | None:
    result = await session.scalars(
        select(Payment).where(Payment.idempotency_key == idempotency_key)
    )
    return result.first()


async def insert_payment(session: AsyncSession, payment: Payment) -> Payment | None:
    statement = (
        insert(Payment)
        .values(
            tariff_id=payment.tariff_id,
            email=payment.email,
            method=payment.method,
            amount=payment.amount,
            discount=payment.discount,
            status=payment.status,
            installment_months=payment.installment_months,
            schedule=payment.schedule,
            idempotency_key=payment.idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
        .returning(Payment)
    )
    result = await session.scalars(statement)
    return result.first()


async def get_payments(
    session: AsyncSession,
    *,
    email: str | None = None,
    status: PaymentStatus | None = None,
) -> Sequence[Payment]:
    statement = select(Payment).order_by(Payment.id)
    if email is not None:
        statement = statement.where(Payment.email == email)
    if status is not None:
        statement = statement.where(Payment.status == status)
    result = await session.scalars(statement)
    return result.all()


async def get_payment(session: AsyncSession, payment_id: int) -> Payment | None:
    # Values outside PostgreSQL INTEGER range cannot identify a payment.
    if not -(2**31) <= payment_id < 2**31:
        return None
    return await session.get(Payment, payment_id)
