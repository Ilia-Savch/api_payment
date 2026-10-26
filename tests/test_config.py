from pathlib import Path

import pytest
from pydantic import ValidationError

from payment_service.core.config import Settings


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RUN", "RUN__HOST", "RUN__PORT", "LOGGING", "LOGGING__LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)


def test_settings_read_dotenv_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Настройки запуска\n"
        "RUN__HOST=127.0.0.1\n"
        "RUN__PORT=9000\n"
        "LOGGING__LOG_LEVEL=warning\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RUN__PORT", "9001")

    settings = Settings(_env_file=env_file)

    assert settings.run.host == "127.0.0.1"
    assert settings.run.port == 9001
    assert settings.logging.log_level == "warning"


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_settings_reject_invalid_port(
    port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUN__PORT", port)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGGING__LOG_LEVEL", "invalid")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
