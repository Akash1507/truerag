import pytest

from app.core.errors import (
    ErrorCode,
    IngestionError,
    NamespaceViolationError,
    PIIDetectedError,
    ProviderUnavailableError,
    RateLimitError,
    TrueRAGError,
)


def test_error_code_required_values() -> None:
    required = {
        "AGENT_NOT_FOUND",
        "NAMESPACE_VIOLATION",
        "PII_DETECTED",
        "CHUNKING_STRATEGY_MISMATCH",
        "EMBEDDING_MODEL_MISMATCH",
        "REINDEX_REQUIRED",
        "RATE_LIMIT_EXCEEDED",
    }
    enum_values = {e.value for e in ErrorCode}
    assert required.issubset(enum_values)


def test_error_code_values_equal_names() -> None:
    for member in ErrorCode:
        assert member.value == member.name


def test_truerag_error_stores_attributes() -> None:
    err = TrueRAGError(code=ErrorCode.AGENT_NOT_FOUND, message="not found", http_status=404)
    assert err.code == ErrorCode.AGENT_NOT_FOUND
    assert err.message == "not found"
    assert err.http_status == 404


def test_truerag_error_default_http_status() -> None:
    err = TrueRAGError(code=ErrorCode.AGENT_NOT_FOUND, message="oops")
    assert err.http_status == 500


def test_provider_unavailable_error_defaults() -> None:
    err = ProviderUnavailableError()
    assert err.http_status == 503
    assert err.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert isinstance(err, TrueRAGError)


def test_provider_unavailable_error_custom_message() -> None:
    err = ProviderUnavailableError("custom msg")
    assert err.message == "custom msg"


def test_rate_limit_error_defaults() -> None:
    err = RateLimitError()
    assert err.http_status == 429
    assert err.code == ErrorCode.RATE_LIMIT_EXCEEDED
    assert isinstance(err, TrueRAGError)


def test_namespace_violation_error_defaults() -> None:
    err = NamespaceViolationError()
    assert err.http_status == 403
    assert err.code == ErrorCode.NAMESPACE_VIOLATION
    assert isinstance(err, TrueRAGError)


def test_pii_detected_error_defaults() -> None:
    err = PIIDetectedError()
    assert err.http_status == 422
    assert err.code == ErrorCode.PII_DETECTED
    assert isinstance(err, TrueRAGError)


def test_ingestion_error_defaults() -> None:
    err = IngestionError()
    assert err.http_status == 500
    assert err.code == ErrorCode.INGESTION_ERROR
    assert isinstance(err, TrueRAGError)


@pytest.mark.parametrize(
    "cls",
    [
        NamespaceViolationError,
        PIIDetectedError,
        ProviderUnavailableError,
        IngestionError,
        RateLimitError,
    ],
)
def test_subclasses_are_truerag_error(cls: type) -> None:
    assert issubclass(cls, TrueRAGError)


def test_namespace_violation_override_code_and_status() -> None:
    err = NamespaceViolationError(
        message="custom",
        code=ErrorCode.AGENT_NOT_FOUND,
        http_status=404,
    )
    assert err.code == ErrorCode.AGENT_NOT_FOUND
    assert err.http_status == 404
    assert err.message == "custom"


def test_provider_unavailable_override_http_status() -> None:
    err = ProviderUnavailableError(http_status=502)
    assert err.http_status == 502
    assert err.code == ErrorCode.PROVIDER_UNAVAILABLE


def test_rate_limit_override_code() -> None:
    err = RateLimitError(code=ErrorCode.REINDEX_REQUIRED)
    assert err.code == ErrorCode.REINDEX_REQUIRED
    assert err.http_status == 429
