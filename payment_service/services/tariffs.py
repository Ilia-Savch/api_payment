import logging

from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud.tariffs import sync_tariff_prices
from payment_service.core.config import TariffsConfig

logger = logging.getLogger(__name__)


async def sync_tariffs(session: AsyncSession, config: TariffsConfig) -> int:
    prices = {
        "basic": config.basic_price,
        "standard": config.standard_price,
        "premium": config.premium_price,
    }
    async with session.begin():
        changes = await sync_tariff_prices(session, prices)
    for title, previous, current in changes:
        if previous is None:
            logger.info("Tariff created: %s price=%s", title, current)
        else:
            logger.info("Tariff price changed: %s %s -> %s", title, previous, current)
    return len(changes)
