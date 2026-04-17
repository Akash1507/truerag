import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_default_values() -> None:
    s = Settings()
    assert s.app_env == "local"
    assert s.log_level == "INFO"
    assert s.aws_region == "us-east-1"
    assert s.default_rate_limit_rpm == 60


def test_invalid_log_level_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="VERBOSE")


def test_missing_field_uses_default() -> None:
    s = Settings()
    assert s.mongodb_secret_name == "truerag/mongodb/uri"
    assert s.pgvector_secret_name == "truerag/pgvector/dsn"


def test_log_level_normalized_to_uppercase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = Settings()
    assert s.log_level == "DEBUG"


def test_get_settings_returns_singleton() -> None:
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
