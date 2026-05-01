# Edge Case Hunter Review Prompt

You are an Edge Case Hunter code reviewer evaluating code changes. You have access to the diff and read access to the project. Your goal is to identify edge cases, boundary conditions, unhandled states, and potential failures under unexpected inputs or environmental conditions.

Please review the following diff and provide your findings as a Markdown list. Each finding must include a one-line title, the edge case condition, and evidence from the diff.

## Diff to Review:
```diff
diff --git a/app/core/config.py b/app/core/config.py
index a0a28b5..abeec03 100644
--- a/app/core/config.py
+++ b/app/core/config.py
@@ -18,6 +18,7 @@ class Settings(BaseSettings):
 
     mongodb_secret_name: str = "truerag/mongodb/uri"
     pgvector_secret_name: str = "truerag/pgvector/dsn"
+    openai_api_key_secret_name: str = "truerag/openai/api_key"
 
     mongodb_uri: str = "mongodb://localhost:27017"
     mongodb_database: str = "truerag"
diff --git a/app/models/chunk.py b/app/models/chunk.py
index f729f7a..b0f275f 100644
--- a/app/models/chunk.py
+++ b/app/models/chunk.py
@@ -14,6 +14,7 @@ class ChunkMetadata(BaseModel):
 class Chunk(BaseModel):
     text: str
     metadata: ChunkMetadata
+    vector: list[float] | None = None
 
 
 class VectorRecord(BaseModel):
diff --git a/app/pipelines/ingestion/pipeline.py b/app/pipelines/ingestion/pipeline.py
index 956b65d..2b09ef1 100644
--- a/app/pipelines/ingestion/pipeline.py
+++ b/app/pipelines/ingestion/pipeline.py
@@ -9,7 +9,7 @@ from app.models.agent import AgentDocument
 from app.models.chunk import Chunk, ChunkMetadata
 from app.models.ingestion_job import IngestionJobPayload
 from app.pipelines.ingestion.parser import parse_document
-from app.providers.registry import CHUNKING_REGISTRY
+from app.providers.registry import CHUNKING_REGISTRY, EMBEDDING_REGISTRY
 from app.utils.observability import get_logger
 from app.utils.pii import scrub_pii
 
@@ -26,7 +26,8 @@ async def run_ingestion_pipeline(
     raw_text = parse_document(content, payload.file_type)
     scrubbed_text = _scrub_with_logging(raw_text, payload)
     chunks = _chunk_text(scrubbed_text, payload, agent)
-    await _embed_upsert_stub(chunks, payload)
+    await _generate_embeddings(chunks, agent, aws_session)
+    await _upsert_to_vector_store_stub(chunks, payload)
 
 
 async def _download_from_s3(
@@ -97,9 +98,38 @@ def _chunk_text(
     return chunks
 
 
-async def _embed_upsert_stub(chunks: list[Chunk], payload: IngestionJobPayload) -> None:
+async def _generate_embeddings(
+    chunks: list[Chunk], agent: AgentDocument, aws_session: aioboto3.Session
+) -> None:
+    embedder_cls = EMBEDDING_REGISTRY[agent.embedding_provider]
+    embedder = embedder_cls(aws_session=aws_session)
+
+    texts = [c.text for c in chunks]
+    vectors = await embedder.embed(texts)
+
+    for chunk, vector in zip(chunks, vectors, strict=True):
+        chunk.vector = vector
+
     logger.info(
-        "embedding_not_yet_implemented",
+        "embedding_complete",
+        extra={
+            "operation": "embedding",
+            "extra_data": {
+                "tenant_id": chunks[0].metadata.tenant_id if chunks else None,
+                "agent_id": agent.id,
+                "provider": agent.embedding_provider,
+                "chunk_count": len(chunks),
+                "vector_dim": len(vectors[0]) if vectors else 0,
+            },
+        },
+    )
+
+
+async def _upsert_to_vector_store_stub(
+    chunks: list[Chunk], payload: IngestionJobPayload
+) -> None:
+    logger.info(
+        "upsert_not_yet_implemented",
         extra={
             "extra_data": {
                 "tenant_id": payload.tenant_id,
@@ -107,6 +137,8 @@ async def _embed_upsert_stub(chunks: list[Chunk], payload: IngestionJobPayload)
                 "job_id": payload.job_id,
                 "document_id": payload.document_id,
                 "chunk_count": len(chunks),
+                "vector_dim": len(chunks[0].vector) if chunks and chunks[0].vector else 0,
             }
         },
     )
+
diff --git a/app/providers/embedding/openai.py b/app/providers/embedding/openai.py
new file mode 100644
index 0000000..facb8e5
--- /dev/null
+++ b/app/providers/embedding/openai.py
@@ -0,0 +1,49 @@
+import aioboto3
+import openai
+from openai import AsyncOpenAI
+
+from app.core.config import get_settings
+from app.core.errors import ProviderUnavailableError
+from app.interfaces.embedding_provider import EmbeddingProvider
+from app.utils.retry import retry
+from app.utils.secrets import get_secret
+
+
+class OpenAIEmbedder(EmbeddingProvider):
+    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
+        self.aws_session = aws_session
+        self.settings = get_settings()
+
+    @retry(
+        max_attempts=3,
+        backoff_factor=2,
+        retry_on=(
+            openai.RateLimitError,
+            openai.APITimeoutError,
+            openai.InternalServerError,
+        ),
+    )
+    async def _embed_with_retry(self, client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
+        response = await client.embeddings.create(
+            input=texts, model="text-embedding-3-small"
+        )
+        return [item.embedding for item in response.data]
+
+    async def embed(self, texts: list[str]) -> list[list[float]]:
+        if not texts:
+            return []
+
+        api_key = await get_secret(
+            self.settings.openai_api_key_secret_name, session=self.aws_session
+        )
+        
+        client = AsyncOpenAI(api_key=api_key)
+        
+        try:
+            return await self._embed_with_retry(client, texts)
+        except (openai.RateLimitError, openai.APITimeoutError, openai.InternalServerError) as exc:
+            raise ProviderUnavailableError(f"OpenAI API exhausted retries: {exc}") from exc
+        except Exception as exc:
+            raise ProviderUnavailableError(f"OpenAI API error: {exc}") from exc
+        finally:
+            await client.close()
diff --git a/app/providers/registry.py b/app/providers/registry.py
index 9b49723..b987157 100644
--- a/app/providers/registry.py
+++ b/app/providers/registry.py
@@ -4,6 +4,7 @@ from app.interfaces.llm_provider import LLMProvider
 from app.interfaces.reranker import Reranker
 from app.interfaces.vector_store import VectorStore
 from app.providers.chunking.fixed_size import FixedSizeChunker
+from app.providers.embedding.openai import OpenAIEmbedder
 from app.providers.rerankers.passthrough import PassthroughReranker
 
 VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]] = {
@@ -20,7 +21,7 @@ RERANKER_REGISTRY: dict[str, type[Reranker]] = {
 }
 
 EMBEDDING_REGISTRY: dict[str, type[EmbeddingProvider]] = {
-    # Populated in Epic 4: "openai": OpenAIEmbedder, ...
+    "openai": OpenAIEmbedder,
 }
 
 LLM_REGISTRY: dict[str, type[LLMProvider]] = {
```
