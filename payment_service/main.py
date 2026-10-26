import uvicorn
from fastapi import FastAPI

from payment_service.api.api_v1.router import router
from payment_service.core.config import settings

app = FastAPI(title="Payments API")
app.include_router(router)


def main() -> None:
    uvicorn.run(
        app,
        host=settings.run.host,
        port=settings.run.port,
        log_level=settings.logging.log_level,
    )


if __name__ == "__main__":
    main()
