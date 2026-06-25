# Backend Tests

Backend tests are organized by SSOT domain and must reference owning AC IDs
unless they are listed in `docs/project/traceability-exceptions.md`.

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
| EPIC -> AC -> test workflow | [tdd.md](../../../docs/ssot/tdd.md) |
| Test execution stages | [test-execution-matrix.yaml](../../../docs/ssot/test-execution-matrix.yaml) |
| Coverage semantics | [coverage.md](../../../docs/ssot/coverage.md) |
| SSOT domain index | [README.md](../../../docs/ssot/README.md) |
| Traceability exceptions | [traceability-exceptions.md](../../../docs/project/traceability-exceptions.md) |
