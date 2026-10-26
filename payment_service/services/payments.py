import logging

from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud import payments as payments_crud
from payment_service.api.api_v1.crud.tariffs import get_tariff
from payment_service.core.models.payment import Payment, PaymentStatus
from payment_service.core.schemas.payment import PaymentCreate
from payment_service.services.calculations import calculate_payment

logger = logging.getLogger(__name__)

ALLOWED_STATUS_TRANSITIONS = {
    (PaymentStatus.PENDING, PaymentStatus.SUCCEEDED),
    (PaymentStatus.PENDING, PaymentStatus.FAILED),
    (PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED),
}


class TariffNotFoundError(Exception):
    pass


class PaymentNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


async def update_payment_status(
    session: AsyncSession, payment_id: int, new_status: PaymentStatus
) -> None:
    async with session.begin():
        payment = await payments_crud.get_payment_for_update(session, payment_id)
        if payment is None:
            raise PaymentNotFoundError
        previous_status = payment.status
        if (previous_status, new_status) not in ALLOWED_STATUS_TRANSITIONS:
            raise InvalidTransitionError
        payment.status = new_status

    logger.info(
        "Payment status changed: id=%s %s -> %s",
        payment_id,
        previous_status.value,
        new_status.value,
    )


async def create_payment(
    session: AsyncSession,
    data: PaymentCreate,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    async with session.begin():
        if idempotency_key is not None:
            existing = await payments_crud.get_payment_by_key(session, idempotency_key)
            if existing is not None:
                return existing, False

        tariff = await get_tariff(session, data.tariff_id)
        if tariff is None:
            raise TariffNotFoundError
        calculation = calculate_payment(
            tariff.price,
            promo_code=data.promo_code,
            installment_months=data.installment_months,
        )
        payment = await payments_crud.insert_payment(
            session,
            Payment(
                tariff_id=tariff.id,
                email=str(data.email),
                method=data.method,
                amount=calculation.amount,
                discount=calculation.discount,
                status=PaymentStatus.PENDING,
                installment_months=data.installment_months,
                schedule=calculation.schedule,
                idempotency_key=idempotency_key,
            ),
        )
        created = payment is not None
        if payment is None and idempotency_key is not None:
            # READ COMMITTED sees the winning insert after ON CONFLICT finishes waiting.
            payment = await payments_crud.get_payment_by_key(session, idempotency_key)
        if payment is None:
            raise RuntimeError("Payment could not be retrieved after insert")

    if created:
        logger.info(
            "Payment created: id=%s tariff_id=%s", payment.id, payment.tariff_id
        )
    return payment, created
