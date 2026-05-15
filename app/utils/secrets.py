import aioboto3

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

logger = get_logger(__name__)

_default_session: aioboto3.Session = aioboto3.Session()

# Maps Secrets Manager secret names → Settings field names for local dev bypass
_LOCAL_SECRET_MAP: dict[str, str] = {
    "truerag/openai/api_key": "openai_api_key",
    "truerag/anthropic/api_key": "anthropic_api_key",
    "truerag/cohere/api_key": "cohere_api_key",
    "cohere/api_key": "cohere_api_key",
    "truerag/qdrant/api_key": "qdrant_api_key",
    "truerag/pinecone/api_key": "pinecone_api_key",
    "truerag/mongodb/uri": "mongodb_uri",
    "truerag/pgvector/dsn": "pgvector_dsn",
}


async def get_secret(name: str, session: aioboto3.Session | None = None) -> str:
    settings = get_settings()

    if settings.app_env == "local":
        field = _LOCAL_SECRET_MAP.get(name)
        if field:
            value = str(getattr(settings, field, "") or "")
            if value:
                return value
            raise ProviderUnavailableError(
                f"Secret {name!r} not set. Add {field.upper()} to your .env file."
            )

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
