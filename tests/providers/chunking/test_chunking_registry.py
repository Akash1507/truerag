from app.providers.chunking.document_aware import DocumentAwareChunker
from app.providers.chunking.fixed_size import FixedSizeChunker
from app.providers.chunking.hierarchical import HierarchicalChunker
from app.providers.chunking.semantic import SemanticChunker
from app.providers.registry import CHUNKING_REGISTRY


def test_semantic_registered() -> None:
    assert CHUNKING_REGISTRY["semantic"] is SemanticChunker


def test_hierarchical_registered() -> None:
    assert CHUNKING_REGISTRY["hierarchical"] is HierarchicalChunker


def test_document_aware_registered() -> None:
    assert CHUNKING_REGISTRY["document_aware"] is DocumentAwareChunker


def test_fixed_size_still_registered() -> None:
    assert CHUNKING_REGISTRY["fixed_size"] is FixedSizeChunker
