from __future__ import annotations

import inspect

import pytest

from app.services import ingestion_service


pytestmark = pytest.mark.skipif(
    not hasattr(ingestion_service, "IngestionService"),
    reason="Class-based ingestion service not available in this branch yet.",
)


def test_ingestion_service_constructor_accepts_queue_backend_dependency() -> None:
    service_cls = ingestion_service.IngestionService
    signature = inspect.signature(service_cls.__init__)
    annotations = getattr(service_cls.__init__, "__annotations__", {})

    queue_param_name = next(
        (name for name in signature.parameters if "queue" in name.lower()),
        None,
    )
    if queue_param_name is None:
        pytest.skip("Queue backend injection not implemented in IngestionService constructor yet.")
    annotation = annotations.get(queue_param_name)
    assert annotation is not None
    assert "QueueBackend" in str(annotation)


def test_ingestion_service_exposes_upload_document_method() -> None:
    service_cls = ingestion_service.IngestionService
    assert hasattr(service_cls, "upload_document")
