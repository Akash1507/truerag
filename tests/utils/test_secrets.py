from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import ProviderUnavailableError
from app.utils.secrets import get_secret


@pytest.mark.asyncio
async def test_get_secret_returns_value() -> None:
    mock_client = AsyncMock()
    mock_client.get_secret_value = AsyncMock(return_value={"SecretString": "my-value"})
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await get_secret("my-secret", session=mock_session)

    assert result == "my-value"
    mock_client.get_secret_value.assert_called_once_with(SecretId="my-secret")


@pytest.mark.asyncio
async def test_get_secret_raises_provider_unavailable_on_error() -> None:
    mock_client = AsyncMock()
    mock_client.get_secret_value = AsyncMock(side_effect=Exception("network error"))
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(ProviderUnavailableError):
        await get_secret("my-secret", session=mock_session)


@pytest.mark.asyncio
async def test_get_secret_uses_default_session_when_none_provided() -> None:
    mock_client = AsyncMock()
    mock_client.get_secret_value = AsyncMock(return_value={"SecretString": "val"})
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    import app.utils.secrets as secrets_module

    original = secrets_module._default_session
    secrets_module._default_session = mock_session
    try:
        result = await get_secret("my-secret")
    finally:
        secrets_module._default_session = original

    assert result == "val"
    mock_client.get_secret_value.assert_called_once_with(SecretId="my-secret")


@pytest.mark.asyncio
async def test_get_secret_calls_with_correct_secret_id() -> None:
    mock_client = AsyncMock()
    mock_client.get_secret_value = AsyncMock(return_value={"SecretString": "secret-val"})
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    await get_secret("prod/db/password", session=mock_session)

    mock_client.get_secret_value.assert_called_once_with(SecretId="prod/db/password")
