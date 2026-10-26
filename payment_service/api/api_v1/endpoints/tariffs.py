from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.api_v1.crud import tariffs as tariffs_crud
from payment_service.api.api_v1.dependencies.database import get_session
from payment_service.core.schemas.tariff import TariffRead

router = APIRouter(tags=["tariffs"])


@router.get("/tariffs")
async def get_tariffs(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TariffRead]:
    tariffs = await tariffs_crud.get_tariffs(session)
    return [TariffRead.model_validate(tariff) for tariff in tariffs]
