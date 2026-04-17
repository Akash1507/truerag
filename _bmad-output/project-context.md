# TrueRAG — Project Context

## What This Project Is
TrueRAG is a production-grade open-source RAG Engine.
Part of TruePlatform. Built in public at buildbeyondbackend.com.

## Technology Stack
- Python 3.11+
- FastAPI
- MongoDB — all tenant and agent config stored here, dynamic at runtime
- pgvector on RDS, Qdrant, Pinecone — all three vector stores
- OpenAI, Cohere, AWS Bedrock — embeddings and LLM providers
- AWS SQS — async ingestion queue
- AWS S3 — raw document storage
- AWS DynamoDB — eval results, ingestion job status
- AWS ECS Fargate — compute
- Terraform — infrastructure
- GitHub Actions — CI-CD
- RAGAS — evaluation

## Critical Rules
- Python only — no TypeScript, no Go
- Config-driven — zero code change to swap any provider, strategy, or model
- All tenant and agent configuration lives in MongoDB — not flat files, not env vars
- Namespace isolation enforced at vector store query level — never application layer
- PII scrubbed before anything enters vector store or LLM
- Three abstract interfaces must be honoured: VectorStore, ChunkingStrategy, Reranker
- Async ingestion never blocks retrieval path
- Explicit readable code — no clever one-liners
- Every significant decision documented as an ADR
- Secrets via AWS Secrets Manager only — never in code or config files
