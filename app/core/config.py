from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_env: str = "local"
    log_level: str = "INFO"
    aws_region: str = "us-east-1"
    default_rate_limit_rpm: int = Field(default=60, gt=0)

    mongodb_secret_name: str = "truerag/mongodb/uri"
    pgvector_secret_name: str = "truerag/pgvector/dsn"
    qdrant_api_key_secret_name: str = "truerag/qdrant/api_key"
    pinecone_api_key_secret_name: str = "truerag/pinecone/api_key"
    cohere_api_key_secret_name: str = "truerag/cohere/api_key"
    openai_api_key_secret_name: str = "truerag/openai/api_key"
    anthropic_api_key_secret_name: str = "truerag/anthropic/api_key"

    # Direct API keys — used when APP_ENV=local (bypasses Secrets Manager)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    qdrant_api_key: str = ""
    pinecone_api_key: str = ""

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "truerag"
    pgvector_dsn: str = "postgresql://postgres:postgres@localhost:5432/truerag"
    qdrant_url: str = "https://your-cluster.qdrant.io"
    pinecone_index_name: str = "truerag"
    cohere_embedding_model: str = "embed-english-v3.0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v1"
    openai_llm_model: str = "gpt-4o-mini"
    bedrock_llm_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    aws_endpoint_url: str | None = None
    sqs_ingestion_queue_url: str = "http://localhost:4566/000000000000/truerag-ingestion"
    queue_backend: Literal["sqs", "kafka", "local"] = "kafka"
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "truerag-ingestion"
    s3_document_bucket: str = "truerag-documents"
    local_storage_path: str = "./local_storage"
    dynamodb_audit_table: str = "truerag-audit-log"
    semantic_cache_ttl_hours: int = 24
    max_document_bytes: int = 52_428_800
    max_dlq_retries: int = 3

    # Bootstrap admin: if set, upserted as admin tenant on every startup
    admin_api_key: str | None = None
    admin_tenant_name: str = "admin"
    admin_display_name: str = "Platform Admin"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
