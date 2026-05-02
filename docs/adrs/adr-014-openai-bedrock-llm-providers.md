# ADR-014: OpenAI and Bedrock LLM Providers

## Status
Accepted

## Context
TrueRAG supports pluggable LLM providers through `LLMProvider`. We need additional generation backends to support model quality/cost tradeoffs and deployment constraints.

## Decision
- Add `OpenAILLMProvider` using OpenAI chat completions with model configured by `openai_llm_model`.
- Add `BedrockLLMProvider` using `bedrock-runtime:InvokeModel` with model configured by `bedrock_llm_model_id`.
- Keep generation interface backend-agnostic (`generate(prompt, context) -> str`) and preserve current context-injected prompt contract from query generator.
- Apply retry wrappers for transient failures and normalize provider failures to `ProviderUnavailableError`.
- Register both providers in `LLM_REGISTRY` for config-driven provider selection.

## Consequences
- Agents can switch LLM providers without code changes.
- Generation path remains consistent while backend adapters handle provider-specific request/response formats.
- Bedrock model IDs must follow provider-specific payload conventions (Anthropic Bedrock schema by default).
