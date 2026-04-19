# ADR 007: Per-Tenant Rate Limiting — In-Process Fixed Window

**Status:** Accepted
**Date:** 2026-04-20

## Context

TrueRAG v1 supports up to 50 tenants. Each tenant must be limited to a configurable number of requests per minute (FR52) to prevent any single tenant from exhausting platform resources. An enforcement mechanism is needed that integrates with the existing middleware stack and requires no additional infrastructure.

Redis-backed global rate limiting would provide exact cross-replica enforcement but adds operational complexity: a Redis cluster, connection pooling, network latency on every request, and failure-mode handling.

## Decision

Implement an in-process fixed-window counter per tenant per minute, enforced via `RateLimiterMiddleware` in `app/core/rate_limiter.py`.

- Each ECS Fargate replica maintains its own `_counters` dict: `tenant_id → (window_start: float, count: int)`.
- Window duration is exactly 60 seconds, measured using `time.monotonic()` (immune to NTP/clock adjustments).
- When the count reaches the tenant's `rate_limit_rpm` (or `default_rate_limit_rpm` from config if unset or zero), subsequent requests in the same window receive HTTP 429 with `ErrorCode.RATE_LIMIT_EXCEEDED`.
- The middleware runs as the innermost layer, after `RequestIDMiddleware` and `AuthMiddleware` have populated `request.state.request_id` and `request.state.tenant`.

## Consequences

- **Per-replica enforcement:** With N running replicas, a tenant may issue up to N × rpm requests before being uniformly rate-limited across all replicas. At v1 scale (≤50 tenants, low replica count), this is acceptable.
- **No external dependency:** No Redis cluster is required for v1 deployment.
- **Stateless restarts:** Counters reset on replica restart. Tenants can temporarily exceed the limit immediately after a rolling deploy. Acceptable for v1.
- **No GIL concern:** CPython's GIL protects `dict` read/write operations without an explicit lock. `asyncio.Lock` is deliberately omitted to avoid unnecessary await points in the hot path.

## Deferred to v2

Redis-backed sliding window rate limiting with global, cross-replica enforcement. This will provide exact rate limiting regardless of replica count and will support burst allowances.

## References

- Architecture decision D7: "Rate limiting: in-process fixed window per tenant per minute; Redis-backed sliding window deferred to v2"
- FR52: Per-tenant per-minute request rate limits, configurable per tenant in MongoDB
