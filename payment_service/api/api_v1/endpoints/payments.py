from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud import payments as payments_crud
from payment_service.api.api_v1.dependencies.database import get_session
from payment_service.core.models.payment import PaymentStatus
from payment_service.core.schemas.payment import PaymentRead

router = APIRouter(tags=["payments"])


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
