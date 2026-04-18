# Requires: python -m spacy download en_core_web_lg
from typing import Any, cast

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

logger = get_logger(__name__)

# Lazily initialized — expensive to construct; created once on first use
_analyzer: AnalyzerEngine | None = None
_anonymizer: Any = None


def _get_engines() -> tuple[AnalyzerEngine, Any]:
    global _analyzer, _anonymizer
    if _analyzer is None:
        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]
    return _analyzer, _anonymizer


def scrub_pii(text: str, *, document_id: str | None = None) -> str:
    analyzer, anonymizer = _get_engines()
    try:
        results = analyzer.analyze(text=text, language="en")
        if not results:
            return text
        anonymized = anonymizer.anonymize(text=text, analyzer_results=cast(Any, results))
    except Exception as exc:
        raise ProviderUnavailableError(f"PII scrubbing unavailable: {exc}") from exc
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "extra_data": {"entities_found": len(results), "document_id": document_id},
        },
    )
    return str(anonymized.text)
