from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr, ValidationError

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
        webhook_secret=SecretStr("synthetic-webhook-secret"),
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


@pytest.mark.anyio
@pytest.mark.parametrize("secret", [None, "", "   "])
async def test_startup_requires_nonempty_webhook_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    if secret is not None:
        monkeypatch.setenv("WEBHOOK_SECRET", secret)
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            db=DatabaseConfig(password=SecretStr("synthetic-test-password")),
        ),
    )
    helper = MagicMock()
    monkeypatch.setattr(main_module, "DatabaseHelper", helper)
    application = main_module.create_app()

    with pytest.raises(ValidationError) as error:
        async with application.router.lifespan_context(application):
            pytest.fail("Application must not start without WEBHOOK_SECRET")

    assert "webhook_secret" in str(error.value)
    assert "synthetic-test-password" not in str(error.value)
    helper.assert_not_called()
