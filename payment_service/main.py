import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from payment_service.api.api_v1.router import router
from payment_service.core.config import get_settings
from payment_service.core.logging import configure_logging
from payment_service.core.models.db_helper import DatabaseHelper
from payment_service.services.tariffs import sync_tariffs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.logging.log_level)
    application.state.webhook_secret = settings.webhook_secret
    db_helper = DatabaseHelper(
        url=settings.db.url,
        pool_size=settings.db.pool_size,
        max_overflow=settings.db.max_overflow,
    )
    application.state.db_helper = db_helper
    try:
        try:
            await db_helper.check_connection()
            async with db_helper.session() as session:
                await sync_tariffs(session, settings.tariffs)
        except Exception:
            logger.error("Database initialization failed")
            raise RuntimeError("Database initialization failed") from None
        logger.info("Database connection established")
        yield
    finally:
        await db_helper.dispose()
        logger.info("Database engine disposed")


def create_app() -> FastAPI:
    application = FastAPI(title="Payments API", lifespan=lifespan)
    application.include_router(router)
    return application


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.run.host,
        port=settings.run.port,
        log_level=settings.logging.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
