# EPIC-012: Foundation Libraries Enhancement

> **Status**: In Progress
> **Vision Anchor**: `decision-7-tech-stack`

Addresses infrastructure foundation items across observability, DB pooling/transactions, unified errors (`BaseAppException` / `DomainError` in `src/platform/base/errors.py`), and schemas. Package-owned ACs live in `common/{observability,audit,runtime,platform,meta,reconciliation}/contract.py`.

## Horizontal Residue & Deferred Rows

| ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC12.22.1 | Move 6 inline schemas from statements router to review module | N/A (mechanical) | N/A | P0 | <!-- epic-owned: horizontal -->
| AC12.22.2 | Extract background task schemas from inline/background definitions into dedicated modules | N/A (mechanical) | N/A | P0 | <!-- epic-owned: horizontal -->
| AC12.24.1 | ~~`/metrics` endpoint returns 200 OK~~ | Removed | Deferred: OTLP path, no Prometheus scrape config | P1 | <!-- epic-owned: horizontal -->
| AC12.24.2 | ~~`/metrics` endpoint returns text/plain~~ | Removed | Deferred: OTLP path | P1 | <!-- epic-owned: horizontal -->
| AC12.24.3 | ~~`/metrics` response contains Prometheus data~~ | Removed | Deferred: OTLP path | P1 | <!-- epic-owned: horizontal -->
| AC12.25.1 | UUID auto-serialization structlog processor remains EPIC-012 P2 backlog until implemented | `test_AC12_25_1_uuid_logging_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 | <!-- epic-owned: horizontal -->

## References

- [common/observability/observability.md](../../common/observability/observability.md) · [common/meta/development.md](../../common/meta/development.md) · [EPIC-010](./EPIC-010.observability-logging.md)
