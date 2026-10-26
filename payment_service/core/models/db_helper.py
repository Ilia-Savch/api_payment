from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import URL, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseHelper:
    def __init__(self, url: URL, pool_size: int = 5, max_overflow: int = 10) -> None:
        self.engine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 5},
        )
        self.session_factory = async_sessionmaker(
            self.engine, autoflush=False, expire_on_commit=False
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Close the session and roll back unfinished work; never auto-commit."""
        async with self.session_factory() as session:
            try:
                yield session
            finally:
                if session.in_transaction():
                    await session.rollback()

    async def check_connection(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(select(1))

    async def dispose(self) -> None:
        await self.engine.dispose()
