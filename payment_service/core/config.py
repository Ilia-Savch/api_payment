from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class RunConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class LoggingConfig(BaseModel):
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"


class TariffsConfig(BaseModel):
    basic_price: int = Field(default=990000, gt=0)
    standard_price: int = Field(default=1990000, gt=0)
    premium_price: int = Field(default=2990000, gt=0)


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = Field(default="payments", min_length=1)
    user: str = Field(default="payments", min_length=1)
    password: SecretStr = Field(min_length=1, repr=False)
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)

    @property
    def url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    run: RunConfig = Field(default_factory=RunConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tariffs: TariffsConfig = Field(default_factory=TariffsConfig)
    db: DatabaseConfig


@lru_cache
def get_settings() -> Settings:
    return Settings()
