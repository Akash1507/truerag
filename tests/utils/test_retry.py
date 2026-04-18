from unittest.mock import AsyncMock, patch

import pytest

from app.utils.retry import retry


@pytest.mark.asyncio
async def test_retry_succeeds_first_attempt() -> None:
    mock_fn = AsyncMock(return_value="ok")

    @retry(max_attempts=3, backoff_factor=2)
    async def wrapped() -> str:
        return await mock_fn()

    result = await wrapped()

    assert result == "ok"
    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt() -> None:
    mock_fn: AsyncMock = AsyncMock(side_effect=[ValueError("fail"), "ok"])

    @retry(max_attempts=3, backoff_factor=2)
    async def wrapped() -> str:
        return await mock_fn()

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await wrapped()

    assert result == "ok"
    assert mock_fn.call_count == 2
    assert mock_sleep.call_count == 1
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_retry_exhausted_raises_last_exception() -> None:
    mock_fn = AsyncMock(side_effect=ValueError("fail"))

    @retry(max_attempts=3, backoff_factor=2)
    async def wrapped() -> str:
        return await mock_fn()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        pytest.raises(ValueError, match="fail"),
    ):
        await wrapped()

    assert mock_fn.call_count == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


@pytest.mark.asyncio
async def test_retry_preserves_function_name() -> None:
    @retry(max_attempts=3, backoff_factor=2)
    async def my_function() -> str:
        return "ok"

    assert my_function.__name__ == "my_function"


@pytest.mark.asyncio
async def test_retry_no_sleep_on_first_attempt_success() -> None:
    @retry(max_attempts=3, backoff_factor=2)
    async def wrapped() -> str:
        return "ok"

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await wrapped()

    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_on_non_matching_exception_propagates_immediately() -> None:
    mock_fn = AsyncMock(side_effect=TypeError("bad type"))

    @retry(max_attempts=3, backoff_factor=2, retry_on=(ValueError,))
    async def wrapped() -> str:
        return await mock_fn()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        pytest.raises(TypeError, match="bad type"),
    ):
        await wrapped()

    assert mock_fn.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_on_matching_exception_retries() -> None:
    mock_fn = AsyncMock(side_effect=ValueError("transient"))

    @retry(max_attempts=3, backoff_factor=2, retry_on=(ValueError,))
    async def wrapped() -> str:
        return await mock_fn()

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(ValueError, match="transient"),
    ):
        await wrapped()

    assert mock_fn.call_count == 3
