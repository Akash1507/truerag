from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit_service import write_audit_log


def _make_mock_session() -> tuple[MagicMock, AsyncMock]:
    mock_table = AsyncMock()
    mock_table.put_item = AsyncMock()
    mock_dynamodb = AsyncMock()
    mock_dynamodb.Table = AsyncMock(return_value=mock_table)
    mock_resource_ctx = MagicMock()
    mock_resource_ctx.__aenter__ = AsyncMock(return_value=mock_dynamodb)
    mock_resource_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session = MagicMock()
    mock_session.resource.return_value = mock_resource_ctx
    return mock_session, mock_table


@pytest.mark.asyncio
async def test_write_audit_log_writes_correct_item() -> None:
    mock_session, mock_table = _make_mock_session()

    await write_audit_log(
        tenant_id="t1",
        agent_id="a1",
        api_key_hash="abc123hash",
        query_hash="qhash456",
        response_confidence=0.85,
        cache_hit=False,
        session=mock_session,
    )

    mock_table.put_item.assert_awaited_once()
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["tenant_id"] == "t1"
    assert item["agent_id"] == "a1"
    assert item["api_key_hash"] == "abc123hash"
    assert item["query_hash"] == "qhash456"
    assert item["sort_key"].endswith("#qhash456")
    assert item["cache_hit"] is False
    assert item["response_confidence"] == Decimal("0.85")
    assert "query" not in item
    assert "answer" not in item
    assert "chunk_text" not in item


@pytest.mark.asyncio
async def test_write_audit_log_swallows_dynamodb_error() -> None:
    mock_session, mock_table = _make_mock_session()
    mock_table.put_item = AsyncMock(side_effect=Exception("DynamoDB unavailable"))

    with patch("app.services.audit_service.logger.error") as mock_log_error:
        await write_audit_log(
            tenant_id="t1",
            agent_id="a1",
            api_key_hash="hash",
            query_hash="qhash",
            response_confidence=0.0,
            cache_hit=False,
            session=mock_session,
        )

    mock_log_error.assert_called_once()
    assert mock_log_error.call_args.kwargs["extra"]["operation"] == "audit_log_write"


@pytest.mark.asyncio
async def test_write_audit_log_confidence_stored_as_decimal() -> None:
    mock_session, mock_table = _make_mock_session()
    await write_audit_log(
        tenant_id="t1",
        agent_id="a1",
        api_key_hash="h",
        query_hash="q",
        response_confidence=0.333,
        session=mock_session,
    )
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert isinstance(item["response_confidence"], Decimal)


@pytest.mark.asyncio
async def test_write_audit_log_timestamp_in_sort_key() -> None:
    mock_session, mock_table = _make_mock_session()
    await write_audit_log(
        tenant_id="t1",
        agent_id="a1",
        api_key_hash="h",
        query_hash="myhash",
        response_confidence=0.5,
        session=mock_session,
    )
    sort_key = mock_table.put_item.call_args.kwargs["Item"]["sort_key"]
    assert sort_key.endswith("#myhash")
    assert "T" in sort_key
