import aioboto3  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

logger = get_logger(__name__)

# Module-level fallback session; callers should prefer passing request.app.state.aws_session
_default_session: aioboto3.Session = aioboto3.Session()


async def get_secret(name: str, session: aioboto3.Session | None = None) -> str:
    settings = get_settings()
    _session = session or _default_session
    logger.info(
        "get_secret",
        extra={"operation": "get_secret", "extra_data": {"secret_name": name}},
    )
    try:
        async with _session.client(
            "secretsmanager",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as client:
            response = await client.get_secret_value(SecretId=name)
            return str(response["SecretString"])
    except Exception as exc:
        raise ProviderUnavailableError(f"Secret {name!r} unavailable: {exc}") from exc
