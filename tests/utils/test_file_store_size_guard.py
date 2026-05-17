from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.utils.file_store import get_file


@pytest.mark.asyncio
async def test_get_file_rejects_local_files_over_size_limit(tmp_path: Path) -> None:
    settings = Settings(
        app_env="local",
        local_storage_path=str(tmp_path),
        max_document_bytes=10,
    )
    s3_key = "tenant/agent/oversized.bin"
    path = tmp_path / s3_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"01234567890")

    with patch("pathlib.Path.read_bytes", side_effect=AssertionError("read_bytes should not run")):
        with pytest.raises(PermanentIngestionError, match="Document exceeds maximum size of 50MB"):
            await get_file(s3_key, settings, AsyncMock())
