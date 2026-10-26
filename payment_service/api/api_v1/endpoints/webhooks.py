from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.dependencies.database import get_session
from payment_service.core.schemas.webhook import BankWebhook, BankWebhookResponse
from payment_service.services import payments as payment_service

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhooks/bank",
    response_model=BankWebhookResponse,
    responses={
        404: {"description": "Payment not found"},
        409: {
            "description": "Invalid transition",
            "content": {
                "application/json": {"example": {"error": "invalid_transition"}}
            },
        },
    },
)
async def bank_webhook(
    data: BankWebhook,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BankWebhookResponse | JSONResponse:
    try:
        await payment_service.update_payment_status(
            session, data.payment_id, data.status
        )
    except payment_service.PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        ) from None
    except payment_service.InvalidTransitionError:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "invalid_transition"},
        )
    return BankWebhookResponse()
