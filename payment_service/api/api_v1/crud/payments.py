from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.core.models.payment import Payment, PaymentStatus


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
