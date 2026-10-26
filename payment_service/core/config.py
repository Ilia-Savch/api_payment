from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class LoggingConfig(BaseModel):
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    run: RunConfig = Field(default_factory=RunConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


settings = Settings()
