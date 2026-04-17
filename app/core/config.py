from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_env: str = "local"
    log_level: str = "INFO"
    aws_region: str = "us-east-1"
    default_rate_limit_rpm: int = 60

    mongodb_secret_name: str = "truerag/mongodb/uri"
    pgvector_secret_name: str = "truerag/pgvector/dsn"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
