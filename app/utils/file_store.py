import asyncio
from pathlib import Path

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.errors import PermanentIngestionError

MAX_DOCUMENT_SIZE_ERROR = "Document exceeds maximum size of 50MB"


async def put_file(
    content: bytes,
    s3_key: str,
    settings: Settings,
    aws_session: aioboto3.Session,
) -> None:
    if settings.app_env == "local":
        path = Path(settings.local_storage_path) / s3_key
        await asyncio.to_thread(_write_bytes, path, content)
        return
    async with aws_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as s3:
        await s3.put_object(Bucket=settings.s3_document_bucket, Key=s3_key, Body=content)


async def get_file(
    s3_key: str,
    settings: Settings,
    aws_session: aioboto3.Session,
) -> bytes:
    if settings.app_env == "local":
        path = Path(settings.local_storage_path) / s3_key
        if path.stat().st_size > settings.max_document_bytes:
            raise PermanentIngestionError(MAX_DOCUMENT_SIZE_ERROR)
        return await asyncio.to_thread(path.read_bytes)
    async with aws_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as s3:
        head = await s3.head_object(Bucket=settings.s3_document_bucket, Key=s3_key)
        if int(head.get("ContentLength", 0)) > settings.max_document_bytes:
            raise PermanentIngestionError(MAX_DOCUMENT_SIZE_ERROR)
        response = await s3.get_object(Bucket=settings.s3_document_bucket, Key=s3_key)
        content = await response["Body"].read()
        if len(content) > settings.max_document_bytes:
            raise PermanentIngestionError(MAX_DOCUMENT_SIZE_ERROR)
        return content


async def delete_file(
    s3_key: str,
    settings: Settings,
    aws_session: aioboto3.Session,
) -> None:
    if settings.app_env == "local":
        path = Path(settings.local_storage_path) / s3_key
        await asyncio.to_thread(_unlink, path)
        return
    async with aws_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as s3:
        await s3.delete_object(Bucket=settings.s3_document_bucket, Key=s3_key)


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
