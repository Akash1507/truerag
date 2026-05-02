# ADR-011: Metrics Reset on Restart (v1)

- Status: Accepted
- Date: 2026-05-03
- Owners: Platform/API

## Context

Story 9.3 introduces `GET /v1/metrics` in Prometheus exposition format for platform observability.
The endpoint must be fast (<500ms), safe to scrape, and must not issue runtime database or CloudWatch aggregation queries.

## Decision

1. API metrics are maintained as in-process counters/histograms inside the `truerag-api` process.
2. On ECS task restart, in-process counters reset to zero by design in v1.
3. Prometheus counter-reset handling is delegated to Prometheus queries/functions (for example `increase()`).
4. Persistent metrics state (Redis/DynamoDB/shared store) is deferred to v2.
5. `truerag_ingestion_jobs_total` is not sourced from API in-memory request counters for real production worker throughput.
6. Worker ingestion counts are sourced via CloudWatch log metric filters on `truerag-worker` structured logs; CloudWatch exporter/remote write is the production integration path.

## Consequences

- Simple, low-latency `/v1/metrics` implementation with no scrape-time heavy dependencies.
- Counter resets are expected behavior after process restarts and must be handled in dashboards/alerts.
- Worker ingestion visibility relies on CloudWatch metric plumbing rather than API process memory.
- v2 can introduce persistent metrics storage if continuity across restarts becomes a hard requirement.
