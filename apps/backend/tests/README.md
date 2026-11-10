# Backend Tests

Backend tests are organized by SSOT domain and must reference owning AC IDs
unless they are listed in `docs/project/traceability-exceptions.md`.

## Test Tiers

1. **Pure unit/integration tests**: Deterministic fixtures, zero network (`-m "not slow and not e2e"`).
2. **Cassette-backed replay tests**: Run with `LLM_CASSETTE_MODE=replay` in CI (`common/testing/fixtures/llm_cassettes/`); refreshed locally via `make llm-record`; never hand-authored ([`common/llm/readme.md#cassettes`](../../../common/llm/readme.md#cassettes)).
3. **Staging live-token E2E & 3-statement oracle**: Live `AI_API_KEY` execution via `runtime-hooks.manifest.json` (`staging_gate` / `scheduled_audit`).

## Commands

```bash
moon run :test
uv run pytest tests/accounting/ -v
uv run pytest tests/infra/ tests/ai/test_models_repr.py -v
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## SSOT Links

| Need | Source |
|---|---|
| EPIC -> AC -> test workflow | [tdd.md](../../../common/testing/tdd.md) |
| Test execution stages | [test-execution-matrix.yaml](../../../common/testing/data/test-execution-matrix.yaml) |
| Coverage semantics | [coverage.md](../../../common/testing/coverage.md) |
| Concept ownership registry | [MANIFEST.yaml](../../../common/meta/data/MANIFEST.yaml) |
| Traceability exceptions | [traceability-exceptions.md](../../../docs/project/traceability-exceptions.md) |
