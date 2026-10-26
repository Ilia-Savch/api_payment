import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, Connection, Integer, MetaData, Table
from sqlalchemy.engine import make_url

from alembic import command
from payment_service.core.config import TariffsConfig
from payment_service.core.models.db_helper import DatabaseHelper
from payment_service.main import create_app
from payment_service.services.tariffs import sync_tariffs


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def database() -> AsyncIterator[tuple[DatabaseHelper, Table]]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or not url.database
        or not url.database.endswith("_test")
    ):
        pytest.fail("TEST_DATABASE_URL must use asyncpg and a database ending in _test")

    helper = DatabaseHelper(url, pool_size=2, max_overflow=0)
    metadata = MetaData()
    table = Table(
        f"session_probe_{uuid4().hex}",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
    )
    created = False
    try:
        async with helper.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        created = True
        yield helper, table
    finally:
        try:
            if created:
                async with helper.engine.begin() as connection:
                    await connection.run_sync(metadata.drop_all)
        finally:
            await helper.dispose()


@pytest.fixture
async def migrated_database(database: tuple[DatabaseHelper, Table]) -> DatabaseHelper:
    helper, _ = database

    def migrate(connection: Connection) -> None:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with helper.engine.begin() as connection:
        await connection.run_sync(migrate)
    return helper


@pytest.fixture
async def client(migrated_database: DatabaseHelper) -> AsyncIterator[AsyncClient]:
    async with migrated_database.session() as session:
        await sync_tariffs(session, TariffsConfig())
    application = create_app()
    application.state.db_helper = migrated_database
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as http_client:
        yield http_client
