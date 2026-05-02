from app.providers.registry import RERANKER_REGISTRY
from app.providers.rerankers.cohere import CohereReranker
from app.providers.rerankers.cross_encoder import CrossEncoderReranker
from app.providers.rerankers.passthrough import PassthroughReranker


def test_registry_cross_encoder_entry() -> None:
    assert RERANKER_REGISTRY["cross_encoder"] is CrossEncoderReranker


def test_registry_cohere_entry() -> None:
    assert RERANKER_REGISTRY["cohere"] is CohereReranker


def test_registry_none_entry_regression() -> None:
    assert RERANKER_REGISTRY["none"] is PassthroughReranker
