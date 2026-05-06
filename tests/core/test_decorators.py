from unittest.mock import MagicMock, patch

import pytest

from app.core.decorators import service_method
from app.core.errors import InvalidCursorError, ProviderUnavailableError


@pytest.mark.asyncio
async def test_service_method_success_returns_result() -> None:
    bound_logger = MagicMock()
    with patch("app.core.decorators.logger.bind", return_value=bound_logger) as bind_mock:

        @service_method("list_tenants")
        async def list_tenants() -> str:
            return "ok"

        result = await list_tenants()

    assert result == "ok"
    bind_mock.assert_called_once_with(operation="list_tenants")
    bound_logger.debug.assert_called_once_with("list_tenants_ok")


@pytest.mark.asyncio
async def test_service_method_reraises_truerag_error() -> None:
    bound_logger = MagicMock()
    expected = ProviderUnavailableError("provider unavailable")

    with patch("app.core.decorators.logger.bind", return_value=bound_logger):

        @service_method("query_docs")
        async def query_docs() -> None:
            raise expected

        with pytest.raises(ProviderUnavailableError) as exc_info:
            await query_docs()

    assert exc_info.value is expected
    bound_logger.warning.assert_called_once_with("query_docs_truerag_error")


@pytest.mark.asyncio
async def test_service_method_translates_value_error_to_invalid_cursor() -> None:
    bound_logger = MagicMock()
    message = "Invalid cursor"

    with patch("app.core.decorators.logger.bind", return_value=bound_logger):

        @service_method("list_agents")
        async def list_agents() -> None:
            raise ValueError(message)

        with pytest.raises(InvalidCursorError) as exc_info:
            await list_agents()

    assert str(exc_info.value) == message
    assert isinstance(exc_info.value.__cause__, ValueError)
    bound_logger.warning.assert_called_once_with(f"list_agents_invalid_cursor | {message}")


@pytest.mark.asyncio
async def test_service_method_reraises_generic_exception() -> None:
    bound_logger = MagicMock()
    expected = RuntimeError("boom")

    with patch("app.core.decorators.logger.bind", return_value=bound_logger):

        @service_method("run_eval")
        async def run_eval() -> None:
            raise expected

        with pytest.raises(RuntimeError) as exc_info:
            await run_eval()

    assert exc_info.value is expected
    bound_logger.exception.assert_called_once_with("run_eval_unhandled | boom")


@pytest.mark.asyncio
async def test_service_method_preserves_wrapped_name() -> None:
    @service_method("create_tenant")
    async def create_tenant() -> None:
        """Create tenant."""

    assert create_tenant.__name__ == "create_tenant"
