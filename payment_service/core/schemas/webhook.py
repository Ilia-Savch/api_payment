from typing import Literal

from pydantic import BaseModel

from payment_service.core.models.payment import PaymentStatus


class BankWebhook(BaseModel):
    payment_id: int
    status: PaymentStatus


class BankWebhookResponse(BaseModel):
    result: Literal["ok"] = "ok"
