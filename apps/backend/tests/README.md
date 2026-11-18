# Backend Tests

Backend tests are organized by SSOT domain and verify package invariants and end-to-end user cases (`common/meta/flows/user_cases_ssot.json`).

## Test Tiers

1. **Pure unit/integration tests**: Deterministic fixtures, zero network (`-m "not slow and not e2e"`).
2. **Cassette-backed replay tests**: Run with `LLM_CASSETTE_MODE=replay` in CI (`tests/fixtures/llm_cassettes/`); refreshed locally via `make llm-record`; never hand-authored ([`common/llm/readme.md#cassettes`](../../../common/llm/readme.md#cassettes)).
3. **Staging live-token E2E & 3-statement oracle**: Live `LLM_API_KEY` execution via `runtime-hooks.manifest.json` (`staging_gate` / `scheduled_audit`).

## Commands

```bash
moon run :test
uv run pytest tests/accounting/ -v
uv run pytest tests/infra/ tests/ai/test_models_repr.py -v
uv run pytest -n 4 --cov=src --cov-report=term-missing --cov-branch --cov-fail-under=96
```

## SSOT Links

| Need | Source |
|---|---|
| TDD & verification workflow | [tdd.md](../../../common/testing/tdd.md) |
| Test execution stages | [test-execution-matrix.yaml](../../../common/testing/data/test-execution-matrix.yaml) |
| Coverage semantics | [coverage.md](../../../common/testing/coverage.md) |
| Business user cases SSOT | [user_cases_ssot.json](../../../common/meta/flows/user_cases_ssot.json) |
| Traceability exceptions | [traceability-exceptions.md](../../../docs/project/traceability-exceptions.md) |
