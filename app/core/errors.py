from enum import StrEnum


class ErrorCode(StrEnum):
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    NAMESPACE_VIOLATION = "NAMESPACE_VIOLATION"
    PII_DETECTED = "PII_DETECTED"
    CHUNKING_STRATEGY_MISMATCH = "CHUNKING_STRATEGY_MISMATCH"
    EMBEDDING_MODEL_MISMATCH = "EMBEDDING_MODEL_MISMATCH"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INGESTION_ERROR = "INGESTION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class TrueRAGError(Exception):
    def __init__(self, code: ErrorCode, message: str, http_status: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class NamespaceViolationError(TrueRAGError):
    def __init__(
        self,
        message: str = "Namespace violation",
        code: ErrorCode = ErrorCode.NAMESPACE_VIOLATION,
        http_status: int = 403,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status)


class PIIDetectedError(TrueRAGError):
    def __init__(
        self,
        message: str = "PII detected in input",
        code: ErrorCode = ErrorCode.PII_DETECTED,
        http_status: int = 422,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status)


class ProviderUnavailableError(TrueRAGError):
    def __init__(
        self,
        message: str = "Provider unavailable",
        code: ErrorCode = ErrorCode.PROVIDER_UNAVAILABLE,
        http_status: int = 503,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status)


class IngestionError(TrueRAGError):
    def __init__(
        self,
        message: str = "Ingestion failed",
        code: ErrorCode = ErrorCode.INGESTION_ERROR,
        http_status: int = 500,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status)


class RateLimitError(TrueRAGError):
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        code: ErrorCode = ErrorCode.RATE_LIMIT_EXCEEDED,
        http_status: int = 429,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status)
