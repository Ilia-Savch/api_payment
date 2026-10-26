import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.dependencies.database import get_session
from payment_service.core.schemas.webhook import BankWebhook, BankWebhookResponse
from payment_service.core.security import is_valid_webhook_signature
from payment_service.services import payments as payment_service

logger = logging.getLogger(__name__)


class SignedWebhookRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def signed_handler(request: Request) -> Response:
            signatures = request.headers.getlist("X-Signature")
            secret = cast(SecretStr, request.app.state.webhook_secret)
            if len(signatures) != 1 or not is_valid_webhook_signature(
                await request.body(),
                signatures[0],
                secret.get_secret_value().encode("utf-8"),
            ):
                logger.warning("Webhook signature rejected")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature"
                )
            # Verify before FastAPI parses JSON or resolves database dependencies.
            return await handler(request)

        return signed_handler


router = APIRouter(tags=["webhooks"], route_class=SignedWebhookRoute)


@router.post(
    "/webhooks/bank",
    response_model=BankWebhookResponse,
    openapi_extra={
        "parameters": [
            {
                "name": "X-Signature",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "minLength": 64, "maxLength": 64},
                "description": "HMAC-SHA256 of the original body bytes, hex encoded",
            }
        ]
    },
    responses={
        401: {"description": "Missing or invalid signature"},
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
