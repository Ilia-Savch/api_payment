from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud import payments as payments_crud
from payment_service.api.api_v1.dependencies.database import get_session
from payment_service.core.models.payment import PaymentStatus
from payment_service.core.schemas.payment import PaymentCreate, PaymentRead
from payment_service.services import payments as payment_service

router = APIRouter(tags=["payments"])


@router.post(
    "/payments",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": PaymentRead}, 404: {"description": "Tariff not found"}},
)
async def create_payment(
    data: PaymentCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentRead:
    try:
        payment, created = await payment_service.create_payment(
            session, data, idempotency_key
        )
    except payment_service.TariffNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tariff not found"
        ) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return PaymentRead.model_validate(payment)


@router.get("/payments")
async def get_payments(
    session: Annotated[AsyncSession, Depends(get_session)],
    email: EmailStr | None = None,
    status: PaymentStatus | None = None,
) -> list[PaymentRead]:
    payments = await payments_crud.get_payments(session, email=email, status=status)
    return [PaymentRead.model_validate(payment) for payment in payments]


@router.get("/payments/{id}")
async def get_payment(
    id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentRead:
    payment = await payments_crud.get_payment(session, id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )
    return PaymentRead.model_validate(payment)
