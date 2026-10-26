from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.core.models.db_helper import DatabaseHelper


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    db_helper = cast(DatabaseHelper, request.app.state.db_helper)
    async with db_helper.session() as session:
        yield session
