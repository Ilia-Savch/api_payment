from fastapi import APIRouter

from payment_service.api.api_v1.endpoints import payments, tariffs, webhooks

router = APIRouter()
router.include_router(tariffs.router)
router.include_router(payments.router)
router.include_router(webhooks.router)
