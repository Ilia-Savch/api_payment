from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

import payment_service.main as main_module
from payment_service.core.config import DatabaseConfig, Settings
from payment_service.core.models.db_helper import DatabaseHelper


@pytest.mark.anyio
async def test_startup_failure_disposes_engine_and_hides_driver_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        _env_file=None,
        db=DatabaseConfig(password=SecretStr("synthetic-test-password")),
    )
    helper = MagicMock(spec=DatabaseHelper)
    helper.check_connection = AsyncMock(
        side_effect=ConnectionError("synthetic-driver-detail")
    )
    helper.dispose = AsyncMock()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "DatabaseHelper", MagicMock(return_value=helper))
    application = main_module.create_app()

    with pytest.raises(RuntimeError, match="^Database initialization failed$"):
        async with application.router.lifespan_context(application):
            pytest.fail("Application must not start without the database")

    assert "Database initialization failed" in caplog.text
    assert "synthetic-driver-detail" not in caplog.text
    helper.check_connection.assert_awaited_once()
    helper.dispose.assert_awaited_once()
